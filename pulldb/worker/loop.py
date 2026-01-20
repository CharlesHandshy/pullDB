"""Worker polling loop for job queue.

Polls MySQL for queued jobs, claims them atomically, and executes restores.
Uses SELECT FOR UPDATE SKIP LOCKED for safe multi-worker operation.
Implements exponential backoff when queue is empty to reduce database load.

Also supports polling for admin tasks (lower priority than restore jobs).

Example:
    >>> from pulldb.infra.mysql import MySQLPool, JobRepository
    >>> pool = MySQLPool(host="localhost", user="worker", password="...")
    >>> repo = JobRepository(pool)
    >>> executor = lambda job: None
    >>> run_poll_loop(repo, executor, max_iterations=10)

HCA Layer: features
"""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from pulldb.domain.models import AdminTask, Job
from pulldb.infra.logging import current_task_name, get_logger
from pulldb.infra.metrics import (
    MetricLabels,
    emit_counter,
    emit_event,
    emit_gauge,
    time_operation,
)


if TYPE_CHECKING:
    from pulldb.infra.mysql import AdminTaskRepository, HostRepository, JobRepository

logger = get_logger("pulldb.worker.loop")

# Backoff configuration
MIN_POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_INTERVAL_SECONDS = 30.0
BACKOFF_MULTIPLIER = 2.0


JobExecutor = Callable[[Job], None]
AdminTaskExecutorFunc = Callable[[AdminTask], None]


def get_worker_id() -> str:
    """Generate a unique identifier for this worker instance.

    Checks PULLDB_WORKER_ID env var first for explicit identification
    (useful for systemd template instances), falls back to hostname:pid.

    Returns:
        Worker ID, e.g. "worker-1" or "worker-node-1:12345".
    """
    env_id = os.getenv("PULLDB_WORKER_ID")
    if env_id:
        return env_id
    hostname = socket.gethostname()
    pid = os.getpid()
    return f"{hostname}:{pid}"


# -----------------------------------------------------------------------------
# Poll Loop Task Handlers
# -----------------------------------------------------------------------------


def _try_process_restore_job(
    job_repo: JobRepository,
    job_executor: JobExecutor,
    worker_id: str,
) -> bool:
    """Attempt to claim and process a queued restore job.

    Args:
        job_repo: Repository for job operations.
        job_executor: Callable that runs the restore workflow.
        worker_id: Worker identifier for claiming.

    Returns:
        True if a job was claimed and processed, False otherwise.
    """
    with time_operation(
        "queue_poll_duration_seconds",
        MetricLabels(phase="queue_poll"),
    ):
        job = job_repo.claim_next_job(worker_id=worker_id)

    if not job:
        return False

    token = current_task_name.set(job.id)
    try:
        logger.info(
            "Job claimed from queue",
            extra={
                "job_id": job.id,
                "target": job.target,
                "owner": job.owner_username,
                "worker_id": worker_id,
                "phase": "queue_poll",
            },
        )

        _emit_running_event(job_repo, job)

        try:
            _execute_job(job_executor, job)
            emit_event(
                "worker_job_success",
                f"job_id={job.id}",
                MetricLabels(phase="job_execute", status="success"),
            )
        except Exception as exc:
            logger.error(
                "Job executor raised error",
                extra={
                    "job_id": job.id,
                    "target": job.target,
                    "phase": "job_execute",
                    "error": str(exc),
                },
                exc_info=True,
            )
            emit_event(
                "worker_job_error",
                str(exc),
                MetricLabels(phase="job_execute", status="error"),
            )
    finally:
        current_task_name.reset(token)

    return True


def _try_handle_stale_running_job(
    job_repo: JobRepository,
    host_repo: HostRepository,
    worker_id: str,
) -> bool:
    """Check for and handle candidate stale running jobs.

    Args:
        job_repo: Repository for job operations.
        host_repo: Repository for host credentials.
        worker_id: Worker identifier.

    Returns:
        True if a stale running job was handled, False otherwise.
    """
    candidate = job_repo.get_candidate_stale_running_job()
    if not candidate:
        return False

    token = current_task_name.set(candidate.id)
    try:
        logger.info(
            "Checking candidate stale running job",
            extra={
                "job_id": candidate.id,
                "target": candidate.target,
                "started_at": candidate.started_at,
                "worker_id": worker_id,
                "phase": "stale_running_check",
            },
        )

        try:
            from pulldb.worker.cleanup import execute_stale_running_cleanup

            result = execute_stale_running_cleanup(
                candidate,
                job_repo,
                host_repo,
                worker_id=worker_id,
            )
            if result.was_actually_stale:
                emit_event(
                    "stale_running_recovered",
                    f"job_id={candidate.id}",
                    MetricLabels(phase="stale_running", status="success"),
                )
            else:
                emit_event(
                    "stale_running_still_active",
                    f"job_id={candidate.id}",
                    MetricLabels(phase="stale_running", status="skipped"),
                )
        except Exception as exc:
            logger.error(
                "Stale running cleanup raised error",
                extra={
                    "job_id": candidate.id,
                    "target": candidate.target,
                    "phase": "stale_running",
                    "error": str(exc),
                },
                exc_info=True,
            )
            emit_event(
                "stale_running_error",
                str(exc),
                MetricLabels(phase="stale_running", status="error"),
            )
    finally:
        current_task_name.reset(token)

    return True


def _try_handle_stale_deleting_job(
    job_repo: JobRepository,
    host_repo: HostRepository,
    worker_id: str,
) -> bool:
    """Attempt to claim and retry a stale deleting job.

    Args:
        job_repo: Repository for job operations.
        host_repo: Repository for host credentials.
        worker_id: Worker identifier for claiming.

    Returns:
        True if a stale deleting job was claimed and processed, False otherwise.
    """
    stale_job = job_repo.claim_stale_deleting_job(worker_id=worker_id)
    if not stale_job:
        return False

    token = current_task_name.set(stale_job.id)
    try:
        logger.info(
            "Stale deleting job claimed for retry",
            extra={
                "job_id": stale_job.id,
                "target": stale_job.target,
                "retry_count": stale_job.retry_count,
                "worker_id": worker_id,
                "phase": "delete_retry",
            },
        )

        try:
            from pulldb.worker.cleanup import execute_delete_job

            delete_result = execute_delete_job(stale_job, job_repo, host_repo)
            if delete_result.success:
                emit_event(
                    "delete_job_success",
                    f"job_id={stale_job.id}",
                    MetricLabels(phase="delete_retry", status="success"),
                )
            else:
                emit_event(
                    "delete_job_retry_failed",
                    f"job_id={stale_job.id} error={delete_result.error}",
                    MetricLabels(phase="delete_retry", status="error"),
                )
        except Exception as exc:
            logger.error(
                "Delete job executor raised error",
                extra={
                    "job_id": stale_job.id,
                    "target": stale_job.target,
                    "phase": "delete_retry",
                    "error": str(exc),
                },
                exc_info=True,
            )
            emit_event(
                "delete_job_error",
                str(exc),
                MetricLabels(phase="delete_retry", status="error"),
            )
    finally:
        current_task_name.reset(token)

    return True


def _try_handle_admin_task(
    admin_task_repo: AdminTaskRepository,
    admin_task_executor: AdminTaskExecutorFunc,
    worker_id: str,
) -> bool:
    """Attempt to claim and execute an admin task.

    Args:
        admin_task_repo: Repository for admin task operations.
        admin_task_executor: Callable for admin task execution.
        worker_id: Worker identifier for claiming.

    Returns:
        True if an admin task was claimed and processed, False otherwise.
    """
    admin_task = admin_task_repo.claim_next_task(worker_id=worker_id)
    if not admin_task:
        return False

    logger.info(
        "Admin task claimed from queue",
        extra={
            "task_id": admin_task.task_id,
            "task_type": admin_task.task_type.value,
            "worker_id": worker_id,
            "phase": "admin_task",
        },
    )

    try:
        admin_task_executor(admin_task)
        emit_event(
            "admin_task_success",
            f"task_id={admin_task.task_id}",
            MetricLabels(phase="admin_task", status="success"),
        )
    except Exception as exc:
        logger.error(
            "Admin task executor raised error",
            extra={
                "task_id": admin_task.task_id,
                "task_type": admin_task.task_type.value,
                "phase": "admin_task",
                "error": str(exc),
            },
            exc_info=True,
        )
        emit_event(
            "admin_task_error",
            str(exc),
            MetricLabels(phase="admin_task", status="error"),
        )

    return True


# -----------------------------------------------------------------------------
# Main Poll Loop
# -----------------------------------------------------------------------------


def run_poll_loop(
    job_repo: JobRepository,
    job_executor: JobExecutor,
    *,
    max_iterations: int | None = None,
    poll_interval: float = MIN_POLL_INTERVAL_SECONDS,
    should_stop: Callable[[], bool] | None = None,
    worker_id: str | None = None,
    admin_task_repo: AdminTaskRepository | None = None,
    admin_task_executor: AdminTaskExecutorFunc | None = None,
    host_repo: HostRepository | None = None,
) -> None:
    """Poll job queue and process jobs.

    Continuously polls MySQL for queued jobs using atomic claim with
    SELECT FOR UPDATE SKIP LOCKED. This is safe for multi-worker deployments
    where multiple workers poll the same queue concurrently.

    Task priority (highest to lowest):
    1. Restore jobs - primary workload
    2. Stale running job cleanup - recover stuck jobs
    3. Stale deleting job retry - complete failed deletions
    4. Admin tasks - background maintenance

    If no work is found, applies exponential backoff to reduce database load.

    Args:
        job_repo: Repository for job operations.
        job_executor: Callable that runs the restore workflow for a job.
        max_iterations: Maximum poll iterations (None = infinite loop).
        poll_interval: Initial poll interval in seconds.
        should_stop: Optional callback returning True to request loop stop.
            Checked at start of each iteration for graceful shutdown.
        worker_id: Unique identifier for this worker instance. If None,
            auto-generated as "hostname:pid".
        admin_task_repo: Optional repository for admin task operations.
        admin_task_executor: Optional callable for admin task execution.
        host_repo: Optional repository for host credentials (enables stale
            job recovery).
    """
    effective_worker_id = worker_id or get_worker_id()
    iteration = 0
    current_interval = poll_interval

    logger.info(
        "Poll loop started",
        extra={"phase": "startup", "worker_id": effective_worker_id},
    )
    emit_event("worker_start", f"Worker {effective_worker_id} poll loop started")

    while (max_iterations is None or iteration < max_iterations) and not (
        should_stop and should_stop()
    ):
        iteration += 1

        try:
            work_done = False

            # Priority 1: Restore jobs (primary workload)
            if _try_process_restore_job(job_repo, job_executor, effective_worker_id):
                work_done = True
                current_interval = poll_interval
                emit_gauge("queue_backoff_interval_seconds", current_interval)

            # Priority 2: Stale running job cleanup
            elif host_repo and _try_handle_stale_running_job(
                job_repo, host_repo, effective_worker_id
            ):
                work_done = True
                current_interval = poll_interval
                emit_gauge("queue_backoff_interval_seconds", current_interval)

            # Priority 3: Stale deleting job retry
            elif host_repo and _try_handle_stale_deleting_job(
                job_repo, host_repo, effective_worker_id
            ):
                work_done = True
                current_interval = poll_interval
                emit_gauge("queue_backoff_interval_seconds", current_interval)

            # Priority 4: Admin tasks
            elif (
                admin_task_repo
                and admin_task_executor
                and _try_handle_admin_task(
                    admin_task_repo, admin_task_executor, effective_worker_id
                )
            ):
                work_done = True
                current_interval = poll_interval
                emit_gauge("queue_backoff_interval_seconds", current_interval)

            # No work found - apply exponential backoff
            if not work_done:
                _apply_backoff(current_interval)
                current_interval = min(
                    current_interval * BACKOFF_MULTIPLIER,
                    MAX_POLL_INTERVAL_SECONDS,
                )

        except KeyboardInterrupt:
            logger.info("Poll loop interrupted by user", extra={"phase": "shutdown"})
            emit_event("worker_interrupt", "Worker poll loop interrupted")
            break

        except Exception as e:
            logger.error(
                "Unexpected error in poll loop",
                extra={"error": str(e), "phase": "error"},
                exc_info=True,
            )
            emit_event(
                "worker_poll_error", str(e), MetricLabels(phase="error", status="error")
            )
            time.sleep(1.0)

    logger.info(
        "Poll loop stopped",
        extra={
            "iterations": iteration,
            "worker_id": effective_worker_id,
            "phase": "shutdown",
        },
    )
    emit_event(
        "worker_stop",
        f"worker={effective_worker_id} iterations={iteration}",
        MetricLabels(phase="shutdown"),
    )


def _apply_backoff(current_interval: float) -> None:
    """Apply exponential backoff when no work is found.

    Args:
        current_interval: Current backoff interval in seconds.
    """
    logger.debug(
        "Queue empty, backing off",
        extra={
            "current_interval": current_interval,
            "next_interval": min(
                current_interval * BACKOFF_MULTIPLIER,
                MAX_POLL_INTERVAL_SECONDS,
            ),
            "phase": "backoff",
        },
    )
    emit_event(
        "queue_empty",
        f"backoff={current_interval}",
        MetricLabels(phase="backoff"),
    )
    time.sleep(current_interval)


def _emit_running_event(job_repo: JobRepository, job: Job) -> None:
    """Emit running event for job audit trail.

    Called after job is atomically claimed. The job status has already been
    updated to 'running' by claim_next_job(), so this only emits the event.

    Args:
        job_repo: Repository for job operations.
        job: Job that was claimed (already in 'running' status).
    """
    try:
        # Emit running event (support legacy append_event name for tests)
        event_kwargs = {
            "job_id": job.id,
            "event_type": "running",
            "detail": f"Job started by worker (target: {job.target})",
        }
        # Append running event to audit log. Support legacy/mocked name
        # append_event in tests while using append_job_event in real repo.
        append_event_method = getattr(job_repo, "append_event", None)
        if callable(append_event_method):  # test mocks provide append_event
            append_event_method(**event_kwargs)
        else:
            job_repo.append_job_event(**event_kwargs)

        logger.debug(
            "Running event emitted",
            extra={
                "job_id": job.id,
                "target": job.target,
                "phase": "status_transition",
            },
        )

    except Exception as e:
        logger.error(
            "Failed to emit running event",
            extra={
                "job_id": job.id,
                "target": job.target,
                "error": str(e),
                "phase": "status_transition",
            },
            exc_info=True,
        )
        # Track event emission failures for monitoring
        emit_counter(
            "event_emission_failures_total",
            labels=MetricLabels(phase="running_event"),
        )
        # Don't re-raise - job is already claimed and running
        # Event emission failure shouldn't stop job execution


def _execute_job(job_executor: JobExecutor, job: Job) -> None:
    """Execute job via provided callable with timing metrics."""
    with time_operation(
        "job_execution_duration_seconds",
        MetricLabels(phase="job_execute"),
    ):
        job_executor(job)
