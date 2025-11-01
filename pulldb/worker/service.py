"""Worker Service with polling loop.

Milestone 2: Polls MySQL queue for jobs, transitions them to running status,
and emits events. Restore workflow execution remains a stub (milestone 3+).
"""

from __future__ import annotations

import sys
import typing as t

from pulldb.domain.config import Config
from pulldb.infra.logging import get_logger
from pulldb.infra.mysql import JobRepository, build_default_pool
from pulldb.worker.loop import run_poll_loop


logger = get_logger("pulldb.worker")


def main(argv: t.Sequence[str] | None = None) -> int:
    """Worker service main entry point.

    Loads configuration, connects to MySQL coordination database, and runs
    the job polling loop. Continues until interrupted or fatal error occurs.

    Args:
        argv: Command-line arguments (currently unused).

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    try:
        # Load minimal configuration (MySQL coordination DB only for now)
        config = Config.minimal_from_env()

        logger.info(
            "Worker starting",
            extra={
                "phase": "startup",
                "mysql_host": config.mysql_host,
                "mysql_database": config.mysql_database,
            },
        )

        # Build MySQL connection pool for coordination database
        pool = build_default_pool(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
        )

        # Create job repository
        job_repo = JobRepository(pool)

        # Run polling loop (blocks until interrupted or max iterations reached)
        run_poll_loop(job_repo, max_iterations=None)

        logger.info("Worker stopped normally", extra={"phase": "shutdown"})
        return 0

    except KeyboardInterrupt:
        logger.info("Worker interrupted by user", extra={"phase": "shutdown"})
        return 0

    except Exception as e:
        logger.error(
            "Worker failed to start",
            extra={"error": str(e), "phase": "startup"},
            exc_info=True,
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
