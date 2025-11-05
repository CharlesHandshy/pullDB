"""Worker daemon service entrypoint.

Provides long-running worker process that polls the MySQL coordination queue
for restore jobs. Adds graceful shutdown via SIGINT/SIGTERM, metrics emission
for active worker state, and integrates with the polling loop's stop callback.

This module intentionally keeps orchestration minimal—full restore workflow
execution (download + myloader + post-SQL + atomic rename) is handled in
subsequent modules; the service only manages lifecycle and infrastructure.
"""

from __future__ import annotations

import signal
import sys
import threading
import typing as t
from types import FrameType

from pulldb.domain.config import Config
from pulldb.infra.logging import get_logger
from pulldb.infra.metrics import MetricLabels, emit_event, emit_gauge
from pulldb.infra.mysql import JobRepository, build_default_pool
from pulldb.worker.loop import run_poll_loop


logger = get_logger("pulldb.worker")


def main(argv: t.Sequence[str] | None = None) -> int:
    """Worker daemon main entry point.

    Responsibilities:
    - Load configuration from environment
    - Establish MySQL coordination pool
    - Register signal handlers for graceful shutdown
    - Emit lifecycle metrics (start, active gauge, stop)
    - Run polling loop until stop requested

    Args:
        argv: Optional CLI arguments (unused; reserved for future flags).

    Returns:
        Process exit code (0 normal termination, non-zero on fatal error).
    """
    stop_event = threading.Event()

    def _handle_signal(signum: int, _: FrameType | None) -> None:
        if not stop_event.is_set():  # only log first signal distinctly
            logger.info(
                "Shutdown signal received",
                extra={"phase": "shutdown", "signal": signum},
            )
        stop_event.set()

    # Register handlers early (KeyboardInterrupt still raises normally)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        config = Config.minimal_from_env()
        logger.info(
            "Worker starting",
            extra={
                "phase": "startup",
                "mysql_host": config.mysql_host,
                "mysql_database": config.mysql_database,
            },
        )
        emit_event("worker_daemon_start", "daemon process starting")

        pool = build_default_pool(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
        )
        job_repo = JobRepository(pool)

        # Active worker gauge (1 while process running)
        emit_gauge("worker_active", 1, MetricLabels(phase="startup"))

        # Run until stop_event is set by signal handler
        while not stop_event.is_set():
            run_poll_loop(job_repo, max_iterations=None, should_stop=stop_event.is_set)
            # The loop internally handles backoff & sleep; we only re-enter if
            # it returned due to should_stop or KeyboardInterrupt.

        emit_event(
            "worker_daemon_stop",
            "daemon process stopping",
            MetricLabels(phase="shutdown"),
        )
        emit_gauge("worker_active", 0, MetricLabels(phase="shutdown"))
        logger.info("Worker stopped normally", extra={"phase": "shutdown"})
        return 0

    except Exception as e:  # FAIL HARD startup errors
        logger.error(
            "Worker fatal error",
            extra={"error": str(e), "phase": "fatal"},
            exc_info=True,
        )
        emit_event(
            "worker_daemon_fatal",
            str(e),
            MetricLabels(phase="fatal", status="error"),
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
