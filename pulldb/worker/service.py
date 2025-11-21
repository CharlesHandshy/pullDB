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
import signal
import sys
import threading
import typing as t
from types import FrameType

from pulldb.domain.config import Config
from pulldb.infra.logging import get_logger
from pulldb.infra.metrics import MetricLabels, emit_event, emit_gauge
from pulldb.infra.mysql import HostRepository, JobRepository, build_default_pool
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
    return parser.parse_args(list(argv) if argv is not None else [])


def _load_config() -> Config:
    return Config.minimal_from_env()


def _build_job_repository(config: Config) -> JobRepository:
    pool = build_default_pool(
        host=config.mysql_host,
        user=config.mysql_user,
        password=config.mysql_password,
        database=config.mysql_database,
    )
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
    args = _parse_args(argv)
    stop_event = threading.Event()
    _register_signal_handlers(stop_event)

    try:
        config = _load_config()
    except Exception as exc:
        _emit_fatal(exc)
        _set_worker_active(0, "fatal")
        return 1

    try:
        job_repo = _build_job_repository(config)
        job_executor = _build_job_executor(config, job_repo)
    except Exception as exc:
        _emit_fatal(exc)
        _set_worker_active(0, "fatal")
        return 1

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
