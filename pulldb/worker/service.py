"""Worker daemon service entrypoint.

Provides long-running worker process that polls the MySQL coordination queue
for restore jobs. Adds graceful shutdown via SIGINT/SIGTERM, metrics emission
for active worker state, and integrates with the polling loop's stop callback.

This module intentionally keeps orchestration minimal—full restore workflow
execution (download + myloader + post-SQL + atomic rename) is handled in
subsequent modules; the service only manages lifecycle and infrastructure.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import typing as t
from types import FrameType

from dotenv import load_dotenv

from pulldb.domain.config import Config
from pulldb.domain.models import JobStatus
from pulldb.infra.logging import get_logger
from pulldb.infra.metrics import MetricLabels, emit_event, emit_gauge
from pulldb.infra.mysql import (
    HostRepository,
    JobRepository,
    MySQLPool,
    build_default_pool,
)
from pulldb.infra.s3 import S3Client
from pulldb.infra.secrets import CredentialResolver
from pulldb.worker.executor import WorkerExecutorDependencies, WorkerJobExecutor
from pulldb.worker.loop import MIN_POLL_INTERVAL_SECONDS, run_poll_loop


logger = get_logger("pulldb.worker")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _parse_args(argv: t.Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pullDB worker daemon")
    parser.add_argument(
        "--max-iterations",
        type=_positive_int,
        default=None,
        help="Maximum poll iterations before exiting (default: infinite)",
    )
    parser.add_argument(
        "--poll-interval",
        type=_positive_float,
        default=MIN_POLL_INTERVAL_SECONDS,
        help=(
            "Initial poll interval in seconds (defaults to poller minimum). "
            "Useful for diagnostics."
        ),
    )
    parser.add_argument(
        "--oneshot",
        action="store_true",
        help="Run a single poll-loop pass (overrides --max-iterations)",
    )
    return parser.parse_args(argv)


def _load_config() -> Config:
    config = Config.minimal_from_env()

    # Default to pr-dev profile if not specified (required for Secrets Manager access)
    if not config.aws_profile:
        config.aws_profile = "pr-dev"

    # Resolve coordination credentials if provided via secret
    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if (
        coordination_secret
        and config.mysql_user == "root"
        and not config.mysql_password
    ):
        try:
            resolver = CredentialResolver(config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            config.mysql_host = creds.host
            config.mysql_user = creds.username
            config.mysql_password = creds.password
            # Note: Config doesn't currently support port override for coordination DB
        except Exception as e:
            logger.warning(f"Failed to resolve coordination secret: {e}")

    return config


def _build_job_repository(config: Config) -> JobRepository:
    kwargs = {
        "host": config.mysql_host,
        "user": config.mysql_user,
        "password": config.mysql_password,
        "database": config.mysql_database,
    }
    if config.mysql_socket:
        kwargs["unix_socket"] = config.mysql_socket

    pool = MySQLPool(**kwargs)
    return JobRepository(pool)


def _build_job_executor(config: Config, job_repo: JobRepository) -> WorkerJobExecutor:
    credential_resolver = CredentialResolver(config.aws_profile)
    host_repo = HostRepository(job_repo.pool, credential_resolver)
    s3_profile = config.s3_aws_profile or config.aws_profile
    s3_client = S3Client(profile=s3_profile)
    deps = WorkerExecutorDependencies(
        job_repo=job_repo,
        host_repo=host_repo,
        s3_client=s3_client,
    )
    return WorkerJobExecutor(config=config, deps=deps)


def _register_signal_handlers(stop_event: threading.Event) -> None:
    def _handle_signal(signum: int, _: FrameType | None) -> None:
        if not stop_event.is_set():
            logger.info(
                "Shutdown signal received",
                extra={"phase": "shutdown", "signal": signum},
            )
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


def _set_worker_active(value: int, phase: str) -> None:
    emit_gauge("worker_active", value, MetricLabels(phase=phase))


def _emit_startup_event(
    config: Config,
    args: argparse.Namespace,
    *,
    effective_poll_interval: float,
) -> None:
    logger.info(
        "Worker starting",
        extra={
            "phase": "startup",
            "mysql_host": config.mysql_host,
            "mysql_database": config.mysql_database,
            "max_iterations": 1 if args.oneshot else args.max_iterations,
            "poll_interval": effective_poll_interval,
        },
    )
    emit_event("worker_daemon_start", "daemon process starting")


def _emit_stop_event(stop_event: threading.Event) -> None:
    emit_event(
        "worker_daemon_stop",
        "daemon process stopping",
        MetricLabels(phase="shutdown", status="stopping"),
    )
    logger.info(
        "Worker stopped normally",
        extra={"phase": "shutdown", "signal": "set" if stop_event.is_set() else "none"},
    )


def _emit_fatal(error: Exception) -> None:
    logger.error(
        "Worker fatal error",
        extra={"error": str(error), "phase": "fatal"},
        exc_info=True,
    )
    emit_event(
        "worker_daemon_fatal",
        str(error),
        MetricLabels(phase="fatal", status="error"),
    )


def _cleanup_zombies(job_repo: JobRepository) -> None:
    """Detect and cleanup zombie jobs at startup.

    If this is the only worker process running, any jobs marked 'running'
    are zombies from a previous crash and should be marked failed.
    """
    try:
        # Check if we are the only worker process
        # We need to check for both module execution and entrypoint script
        pids: set[str] = set()
        for pattern in ["pulldb.worker.service", "pulldb-worker"]:
            cmd = ["pgrep", "-f", pattern]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                for pid in result.stdout.strip().splitlines():
                    pids.add(pid)

        count = len(pids)

        # If count > 1, we are not alone.
        if count > 1:
            logger.info(
                "Multiple worker processes detected, skipping zombie cleanup",
                extra={"worker_count": count, "phase": "startup"},
            )
            return

        # We are the only worker. Check for running jobs.
        active_jobs = job_repo.get_active_jobs()
        running_jobs = [j for j in active_jobs if j.status == JobStatus.RUNNING]

        if not running_jobs:
            return

        logger.warning(
            f"Found {len(running_jobs)} zombie jobs at startup",
            extra={"phase": "startup", "zombie_count": len(running_jobs)},
        )

        for job in running_jobs:
            msg = "Zombie job detected at worker startup (single worker mode)"
            logger.warning(
                f"Marking zombie job {job.id} as failed",
                extra={"job_id": job.id, "target": job.target, "phase": "startup"},
            )
            job_repo.mark_job_failed(job.id, msg)
            emit_event(
                "worker_zombie_cleanup",
                f"job_id={job.id}",
                MetricLabels(phase="startup", status="cleanup"),
            )

    except FileNotFoundError:
        logger.warning(
            "pgrep not found, skipping zombie cleanup", extra={"phase": "startup"}
        )
    except Exception as e:
        logger.error(
            "Failed to cleanup zombie jobs",
            extra={"error": str(e), "phase": "startup"},
            exc_info=True,
        )


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
    load_dotenv()
    args = _parse_args(argv)
    stop_event = threading.Event()
    _register_signal_handlers(stop_event)

    try:
        # 1. Bootstrap config from env
        bootstrap_config = _load_config()

        # 2. Build repo (connects to DB)
        job_repo = _build_job_repository(bootstrap_config)

        # 3. Load full config from env + MySQL
        config = Config.from_env_and_mysql(job_repo.pool)

        logger.info(
            "DEBUG: Loaded config",
            extra={
                "s3_bucket_path": config.s3_bucket_path,
                "s3_backup_locations": str(config.s3_backup_locations),
            },
        )

        # 4. Build executor with full config
        job_executor = _build_job_executor(config, job_repo)
    except Exception as exc:
        _emit_fatal(exc)
        _set_worker_active(0, "fatal")
        return 1

    # Cleanup zombie jobs before starting the main loop
    _cleanup_zombies(job_repo)

    poll_interval = MIN_POLL_INTERVAL_SECONDS if args.oneshot else args.poll_interval

    _emit_startup_event(
        config,
        args,
        effective_poll_interval=poll_interval,
    )
    _set_worker_active(1, "startup")

    try:
        max_iterations = 1 if args.oneshot else args.max_iterations
        run_poll_loop(
            job_repo,
            job_executor,
            max_iterations=max_iterations,
            poll_interval=poll_interval,
            should_stop=stop_event.is_set,
        )
    except Exception as exc:
        _emit_fatal(exc)
        _set_worker_active(0, "fatal")
        return 1

    _emit_stop_event(stop_event)
    _set_worker_active(0, "shutdown")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
