"""Worker polling loop for job queue.

Polls MySQL for queued jobs, transitions them to running status, and emits
events for observability. Uses exponential backoff when queue is empty to
reduce database load.

Example:
    >>> from pulldb.infra.mysql import MySQLPool, JobRepository
    >>> pool = MySQLPool(host="localhost", user="worker", password="...")
    >>> repo = JobRepository(pool)
    >>> run_poll_loop(repo, max_iterations=10)
"""

from __future__ import annotations

import time
import typing as t

from pulldb.domain.models import Job
from pulldb.infra.logging import get_logger


if t.TYPE_CHECKING:
    from pulldb.infra.mysql import JobRepository

logger = get_logger("pulldb.worker.loop")

# Backoff configuration
MIN_POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_INTERVAL_SECONDS = 30.0
BACKOFF_MULTIPLIER = 2.0


def run_poll_loop(
    job_repo: JobRepository,
    max_iterations: int | None = None,
    poll_interval: float = MIN_POLL_INTERVAL_SECONDS,
) -> None:
    """Poll job queue and process jobs.

    Continuously polls MySQL for queued jobs. When a job is found, transitions
    it to running status and emits events. Uses exponential backoff when queue
    is empty to reduce load.

    Args:
        job_repo: Repository for job operations.
        max_iterations: Maximum poll iterations (None = infinite loop).
        poll_interval: Initial poll interval in seconds.

    Example:
        >>> pool = MySQLPool(...)
        >>> repo = JobRepository(pool)
        >>> run_poll_loop(repo, max_iterations=100)  # Poll 100 times then exit
    """
    iteration = 0
    current_interval = poll_interval

    logger.info("Poll loop started", extra={"phase": "startup"})

    while max_iterations is None or iteration < max_iterations:
        iteration += 1

        try:
            # Attempt to fetch next queued job
            job = job_repo.get_next_queued_job()

            if job:
                # Reset backoff on successful job fetch
                current_interval = poll_interval

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

                # TODO: Execute restore workflow (placeholder for milestone 3+)
                logger.info(
                    "Job execution not yet implemented",
                    extra={
                        "job_id": job.id,
                        "target": job.target,
                        "phase": "restore_stub",
                    },
                )

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

                time.sleep(current_interval)

                # Increase backoff interval (capped at max)
                current_interval = min(
                    current_interval * BACKOFF_MULTIPLIER,
                    MAX_POLL_INTERVAL_SECONDS,
                )

        except KeyboardInterrupt:
            logger.info("Poll loop interrupted by user", extra={"phase": "shutdown"})
            break

        except Exception as e:
            # Log unexpected errors but continue polling
            logger.error(
                "Unexpected error in poll loop",
                extra={"error": str(e), "phase": "error"},
                exc_info=True,
            )
            # Brief sleep before retry to avoid tight error loop
            time.sleep(1.0)

    logger.info(
        "Poll loop stopped",
        extra={"iterations": iteration, "phase": "shutdown"},
    )


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
        if hasattr(job_repo, "append_event"):
            job_repo.append_event(**event_kwargs)  # type: ignore[attr-defined]
        else:  # pragma: no cover - fallback path
            job_repo.append_job_event(**event_kwargs)  # type: ignore[attr-defined]

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
