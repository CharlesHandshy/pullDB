"""Worker daemon service entrypoint.

Provides long-running worker process that polls the MySQL coordination queue
for restore jobs. Adds graceful shutdown via SIGINT/SIGTERM, metrics emission
for active worker state, and integrates with the polling loop's stop callback.

This module intentionally keeps orchestration minimal—full restore workflow
execution (download + myloader + post-SQL + atomic rename) is handled in
subsequent modules; the service only manages lifecycle and infrastructure.

HCA Layer: features
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import Any

from dotenv import load_dotenv

from pulldb.domain.config import Config
from pulldb.domain.models import Job, JobStatus
from pulldb.infra.factory import is_simulation_mode
from pulldb.infra.logging import get_logger
from pulldb.infra.metrics import MetricLabels, emit_event, emit_gauge
from pulldb.infra.mysql import (
    AdminTaskRepository,
    AuditRepository,
    HostRepository,
    JobRepository,
    MySQLPool,
    SettingsRepository,
    UserRepository,
)
from pulldb.infra.s3 import S3Client
from pulldb.infra.secrets import CredentialResolver
from pulldb.worker.admin_tasks import AdminTaskExecutor
from pulldb.worker.executor import WorkerExecutorDependencies, WorkerJobExecutor
from pulldb.worker.loop import MIN_POLL_INTERVAL_SECONDS, run_poll_loop
from pulldb.worker.staging import StagingConnectionSpec, cleanup_orphaned_staging


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


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    # Get default poll interval from environment or use minimum
    default_poll_interval = MIN_POLL_INTERVAL_SECONDS
    env_poll = os.getenv("PULLDB_WORKER_POLL_INTERVAL")
    if env_poll:
        try:
            default_poll_interval = float(env_poll)
            if default_poll_interval <= 0:
                default_poll_interval = MIN_POLL_INTERVAL_SECONDS
        except ValueError:
            logger.debug(
                "Invalid PULLDB_WORKER_POLL_INTERVAL value, using default %s",
                MIN_POLL_INTERVAL_SECONDS,
                extra={"invalid_value": env_poll},
            )

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
        default=default_poll_interval,
        help=(
            "Initial poll interval in seconds (defaults to PULLDB_WORKER_POLL_INTERVAL "
            "or poller minimum). Useful for diagnostics."
        ),
    )
    parser.add_argument(
        "--oneshot",
        action="store_true",
        help="Run a single poll-loop pass (overrides --max-iterations)",
    )
    return parser.parse_args(argv)


def _load_config_and_pool() -> tuple[Config, MySQLPool]:
    """Load config and create MySQL pool using shared bootstrap.
    
    Uses shared bootstrap module for two-phase config loading:
    1. Bootstrap from environment (MySQL credentials, AWS profile)
    2. Resolve Secrets Manager credentials
    3. Connect to MySQL
    4. Load full config from env + MySQL settings
    
    Returns:
        Tuple of (fully_loaded_config, mysql_pool)
    """
    from pulldb.infra.bootstrap import bootstrap_service_config

    return bootstrap_service_config(
        service_mysql_user_env="PULLDB_WORKER_MYSQL_USER",
        service_name="Worker service",
    )


def _load_config() -> Config:
    """Load worker configuration (legacy wrapper for compatibility).
    
    Note: This returns only the config, not the pool. For new code,
    prefer _load_config_and_pool() which returns both.
    """
    config = Config.minimal_from_env()

    # Default to pr-dev profile if not specified (required for Secrets Manager access)
    if not config.aws_profile:
        config.aws_profile = "pr-dev"

    # REQUIRED: Worker service must have its own MySQL user
    worker_mysql_user = os.getenv("PULLDB_WORKER_MYSQL_USER")
    if not worker_mysql_user:
        raise RuntimeError(
            "PULLDB_WORKER_MYSQL_USER is required. "
            "Set it to the worker service MySQL user (e.g., pulldb_worker)."
        )
    config.mysql_user = worker_mysql_user.strip()

    # Resolve coordination credentials if provided via secret
    # Only fetch from Secrets Manager if password is not already set
    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if coordination_secret and not config.mysql_password:
        try:
            resolver = CredentialResolver(config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            # Secret provides host and password; username comes from PULLDB_WORKER_MYSQL_USER
            config.mysql_host = creds.host
            config.mysql_password = creds.password
            logger.info(
                f"Resolved coordination credentials from {coordination_secret} "
                f"(host={creds.host}, user={config.mysql_user})"
            )
        except Exception as e:
            logger.warning(f"Failed to resolve coordination secret: {e}")

    return config


def _build_job_repository(config: Config) -> JobRepository:
    """Build job repository based on mode.
    
    Args:
        config: Application configuration with MySQL connection details.
    
    Returns:
        JobRepository implementation (real or simulated).
    """
    if is_simulation_mode():
        from pulldb.simulation import SimulatedJobRepository

        return SimulatedJobRepository()  # type: ignore[return-value]

    kwargs: dict[str, Any] = {
        "host": config.mysql_host,
        "user": config.mysql_user,
        "password": config.mysql_password,
        "database": config.mysql_database,
    }
    if config.mysql_socket:
        kwargs["unix_socket"] = config.mysql_socket

    pool = MySQLPool(**kwargs)
    return JobRepository(pool)


def _build_job_executor(
    config: Config,
    job_repo: JobRepository,
    host_repo: HostRepository | None = None,
) -> WorkerJobExecutor:
    """Build job executor with appropriate dependencies for mode.

    Args:
        config: Application configuration.
        job_repo: Job repository for database operations.
        host_repo: Optional pre-built host repository. If None, one will be created.

    Returns:
        Configured WorkerJobExecutor instance.
    """
    if is_simulation_mode():
        from pulldb.simulation import (
            MockS3Client,
            SimulatedHostRepository,
        )

        # Note: In simulation mode, subprocess execution still uses real exec
        # The full mock of subprocess execution requires deeper refactoring
        # of the restore workflow to inject an executor dependency.
        deps = WorkerExecutorDependencies(
            job_repo=job_repo,
            host_repo=SimulatedHostRepository(),
            s3_client=MockS3Client(),
        )
        return WorkerJobExecutor(config=config, deps=deps)

    # Use provided host_repo or create a new one
    if host_repo is None:
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


def _cleanup_zombie_work_dir(work_dir: Path, job_id: str) -> None:
    """Cleanup work directory for a zombie job.

    Removes the job's download/extraction directory to reclaim disk space.

    Args:
        work_dir: Base work directory (e.g., /mnt/data/tmp/user/pulldb-work).
        job_id: UUID of the zombie job.
    """
    job_dir = work_dir / job_id
    if not job_dir.exists():
        return

    try:
        shutil.rmtree(job_dir)
        logger.info(
            f"Cleaned up zombie job work directory: {job_dir}",
            extra={"job_id": job_id, "phase": "startup"},
        )
    except Exception as e:
        logger.warning(
            f"Failed to cleanup zombie work directory: {e}",
            extra={"job_id": job_id, "job_dir": str(job_dir), "error": str(e)},
        )


def _cleanup_zombie_staging(
    job: Job,
    host_repo: HostRepository,
    staging_timeout: int = 30,
) -> None:
    """Cleanup staging database for a zombie job.

    Attempts to drop any orphaned staging databases for the zombie job's target.
    This is best-effort - failures are logged but don't prevent job cleanup.

    Args:
        job: The zombie job to cleanup staging for.
        host_repo: Repository to resolve host credentials.
        staging_timeout: Timeout for staging cleanup operations.
    """
    try:
        creds = host_repo.get_host_credentials(job.dbhost)
        conn_spec = StagingConnectionSpec(
            mysql_host=creds.host,
            mysql_port=creds.port,
            mysql_user=creds.username,
            mysql_password=creds.password,
            timeout_seconds=staging_timeout,
        )
        result = cleanup_orphaned_staging(conn_spec, job.target, job.id)
        if result.orphans_dropped:
            logger.info(
                f"Cleaned up {len(result.orphans_dropped)} orphaned staging databases "
                f"for zombie job {job.id}",
                extra={
                    "job_id": job.id,
                    "target": job.target,
                    "orphans": result.orphans_dropped,
                    "phase": "startup",
                },
            )
    except Exception as e:
        # Best effort - log but don't fail zombie cleanup
        logger.warning(
            f"Failed to cleanup staging for zombie job {job.id}: {e}",
            extra={"job_id": job.id, "target": job.target, "error": str(e)},
        )


def _cleanup_zombies(
    job_repo: JobRepository,
    pool: MySQLPool,
    config: Config | None = None,
    host_repo: HostRepository | None = None,
) -> None:
    """Detect and cleanup zombie jobs at startup.

    Uses MySQL advisory lock to ensure only one worker performs cleanup,
    preventing race conditions when multiple workers start simultaneously.
    Any jobs marked 'running' when cleanup runs are zombies from a previous
    crash and should be marked failed.

    Comprehensive cleanup includes:
    1. Marking the job as failed (clears cancel_requested_at)
    2. Dropping orphaned staging databases (if host_repo provided)
    3. Removing work directories with downloaded archives (if config provided)

    Args:
        job_repo: Repository for job state queries and updates.
        pool: MySQL connection pool for advisory lock.
        config: Optional config for work directory cleanup.
        host_repo: Optional host repository for staging cleanup.
    """
    try:
        # Use MySQL advisory lock to ensure only one worker performs cleanup.
        # GET_LOCK with timeout=0 returns immediately: 1 if acquired, 0 if held.
        with pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT GET_LOCK('pulldb_zombie_cleanup', 0)")
            lock_result = cursor.fetchone()
            acquired = lock_result is not None and lock_result[0] == 1

            if not acquired:
                logger.info(
                    "Another worker is performing zombie cleanup, skipping",
                    extra={"phase": "startup"},
                )
                return

            try:
                # We hold the lock. Check for running jobs.
                active_jobs = job_repo.get_active_jobs()
                running_jobs = [j for j in active_jobs if j.status == JobStatus.RUNNING]

                if not running_jobs:
                    return

                logger.warning(
                    f"Found {len(running_jobs)} zombie jobs at startup",
                    extra={"phase": "startup", "zombie_count": len(running_jobs)},
                )

                for job in running_jobs:
                    msg = "Zombie job detected at worker startup"
                    logger.warning(
                        f"Marking zombie job {job.id} as failed",
                        extra={"job_id": job.id, "target": job.target, "phase": "startup"},
                    )

                    # 1. Cleanup staging databases (best effort)
                    if host_repo is not None:
                        _cleanup_zombie_staging(job, host_repo)

                    # 2. Cleanup work directory (best effort)
                    if config is not None:
                        _cleanup_zombie_work_dir(config.work_dir, job.id)

                    # 3. Mark job as failed (also clears cancel_requested_at)
                    job_repo.mark_job_failed(job.id, msg)
                    emit_event(
                        "worker_zombie_cleanup",
                        f"job_id={job.id}",
                        MetricLabels(phase="startup", status="cleanup"),
                    )
            finally:
                # Always release the lock
                cursor.execute("SELECT RELEASE_LOCK('pulldb_zombie_cleanup')")

    except Exception as e:
        logger.error(
            "Failed to cleanup zombie jobs",
            extra={"error": str(e), "phase": "startup"},
            exc_info=True,
        )


def main(argv: Sequence[str] | None = None) -> int:
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

    host_repo: HostRepository | None = None
    admin_task_repo: AdminTaskRepository | None = None
    admin_task_executor: AdminTaskExecutor | None = None

    try:
        # 1. Bootstrap config and pool using shared bootstrap module
        config, pool = _load_config_and_pool()

        # 2. Build job repository with the pool
        job_repo = JobRepository(pool)

        logger.info(
            "DEBUG: Loaded config",
            extra={
                "s3_bucket_path": config.s3_bucket_path,
                "s3_backup_locations": str(config.s3_backup_locations),
            },
        )

        # 3. Build host repository for credential resolution
        if not is_simulation_mode():
            credential_resolver = CredentialResolver(config.aws_profile)
            host_repo = HostRepository(pool, credential_resolver)

        # 4. Build executor with full config (reuse host_repo)
        job_executor = _build_job_executor(config, job_repo, host_repo)

        # 5. Build admin task executor (if not in simulation mode)
        if not is_simulation_mode() and host_repo:
            admin_task_repo = AdminTaskRepository(pool)
            user_repo = UserRepository(pool)
            audit_repo = AuditRepository(pool)
            settings_repo = SettingsRepository(pool)
            admin_task_executor = AdminTaskExecutor(
                task_repo=admin_task_repo,
                job_repo=job_repo,
                user_repo=user_repo,
                host_repo=host_repo,
                audit_repo=audit_repo,
                pool=pool,
                settings_repo=settings_repo,
            )
            logger.info("Admin task executor initialized")
    except Exception as exc:
        _emit_fatal(exc)
        _set_worker_active(0, "fatal")
        return 1

    # Cleanup zombie jobs before starting the main loop
    # Uses MySQL advisory lock to prevent race conditions with multiple workers
    _cleanup_zombies(job_repo, pool, config=config, host_repo=host_repo)

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
            admin_task_repo=admin_task_repo,
            admin_task_executor=admin_task_executor.execute if admin_task_executor else None,
            host_repo=host_repo,
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
