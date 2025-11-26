"""Worker polling loop for job queue.

Polls MySQL for queued jobs, transitions them to running status, and emits
events for observability. Uses exponential backoff when queue is empty to
reduce database load.

Example:
    >>> from pulldb.infra.mysql import MySQLPool, JobRepository
    >>> pool = MySQLPool(host="localhost", user="worker", password="...")
    >>> repo = JobRepository(pool)
    >>> executor = lambda job: None
    >>> run_poll_loop(repo, executor, max_iterations=10)
"""

from __future__ import annotations

import time
import typing as t

from pulldb.domain.models import Job
from pulldb.infra.logging import current_task_name, get_logger
from pulldb.infra.metrics import (
    MetricLabels,
    emit_event,
    emit_gauge,
    time_operation,
)


if t.TYPE_CHECKING:
    from pulldb.infra.mysql import JobRepository

logger = get_logger("pulldb.worker.loop")

# Backoff configuration
MIN_POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_INTERVAL_SECONDS = 30.0
BACKOFF_MULTIPLIER = 2.0


JobExecutor = t.Callable[[Job], None]


def run_poll_loop(
    job_repo: JobRepository,
    job_executor: JobExecutor,
    *,
    max_iterations: int | None = None,
    poll_interval: float = MIN_POLL_INTERVAL_SECONDS,
    should_stop: t.Callable[[], bool] | None = None,
) -> None:
    """Poll job queue and process jobs.

    Continuously polls MySQL for queued jobs. When a job is found, transitions
    it to running status and emits events. Uses exponential backoff when queue
    is empty to reduce load.

    Args:
        job_repo: Repository for job operations.
        job_executor: Callable that runs the restore workflow for a job.
        max_iterations: Maximum poll iterations (None = infinite loop).
        poll_interval: Initial poll interval in seconds.
        should_stop: Optional callback returning True to request loop stop.
            Checked at start of each iteration for graceful shutdown (e.g.,
            signal handler sets an Event).

    Example:
        >>> pool = MySQLPool(...)
        >>> repo = JobRepository(pool)
        >>> executor = lambda job: None
        >>> run_poll_loop(
        ...     repo, executor, max_iterations=100
        ... )  # Poll 100 times then exit
        >>> # Graceful stop after external condition:
        >>> stop = False
        >>> def _should_stop():
        ...     return stop
        >>> run_poll_loop(
        ...     repo, executor, should_stop=_should_stop
        ... )  # Infinite until stop
    """
    iteration = 0
    current_interval = poll_interval

    logger.info("Poll loop started", extra={"phase": "startup"})
    emit_event("worker_start", "Worker poll loop started")

    while (max_iterations is None or iteration < max_iterations) and not (
        should_stop and should_stop()
    ):
        iteration += 1

        try:
            # Attempt to fetch next queued job
            with time_operation(
                "queue_poll_duration_seconds",
                MetricLabels(phase="queue_poll"),
            ):
                job = job_repo.get_next_queued_job()

            if job:
                # Set task name context for logging
                token = current_task_name.set(job.id)
                try:
                    # Reset backoff on successful job fetch
                    current_interval = poll_interval
                    emit_gauge("queue_backoff_interval_seconds", current_interval)

                    logger.info(
                        "Job acquired from queue",
                        extra={
                            "job_id": job.id,
                            "target": job.target,
                            "owner": job.owner_username,
                            "phase": "queue_poll",
                        },
                    )

                    # Transition job to running status
                    _transition_to_running(job_repo, job)

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

            else:
                # No job found - apply exponential backoff
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

                # Increase backoff interval (capped at max)
                current_interval = min(
                    current_interval * BACKOFF_MULTIPLIER,
                    MAX_POLL_INTERVAL_SECONDS,
                )

        except KeyboardInterrupt:
            logger.info("Poll loop interrupted by user", extra={"phase": "shutdown"})
            emit_event("worker_interrupt", "Worker poll loop interrupted")
            break

        except Exception as e:
            # Log unexpected errors but continue polling
            logger.error(
                "Unexpected error in poll loop",
                extra={"error": str(e), "phase": "error"},
                exc_info=True,
            )
            emit_event(
                "worker_poll_error", str(e), MetricLabels(phase="error", status="error")
            )
            # Brief sleep before retry to avoid tight error loop
            time.sleep(1.0)

    logger.info(
        "Poll loop stopped",
        extra={"iterations": iteration, "phase": "shutdown"},
    )
    emit_event("worker_stop", f"iterations={iteration}", MetricLabels(phase="shutdown"))


def _transition_to_running(job_repo: JobRepository, job: Job) -> None:
    """Transition job from queued to running status.

    Updates job status in database and emits running event for audit trail.

    Args:
        job_repo: Repository for job operations.
        job: Job to transition.
    """
    try:
        # Mark job as running (updates started_at timestamp)
        job_repo.mark_job_running(job.id)

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

        logger.info(
            "Job transitioned to running",
            extra={
                "job_id": job.id,
                "target": job.target,
                "phase": "status_transition",
            },
        )

    except Exception as e:
        logger.error(
            "Failed to transition job to running",
            extra={
                "job_id": job.id,
                "target": job.target,
                "error": str(e),
                "phase": "status_transition",
            },
            exc_info=True,
        )
        raise


def _execute_job(job_executor: JobExecutor, job: Job) -> None:
    """Execute job via provided callable with timing metrics."""
    with time_operation(
        "job_execution_duration_seconds",
        MetricLabels(phase="job_execute"),
    ):
        job_executor(job)
