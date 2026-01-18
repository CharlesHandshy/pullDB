"""Worker job executor wiring queue entries to restore workflow.

This module bridges the polling loop with the existing downloader + restore
workflow implementation. It encapsulates the per-job orchestration steps:

1. Discover the newest backup in S3 for the job target
2. Download the archive with disk-capacity guard (leveraging downloader.py)
3. Extract the archive into a job-scoped working directory
4. Build staging/post-SQL connection specs using host credentials
5. Invoke ``orchestrate_restore_workflow`` and update job status/events

All filesystem activity is isolated under ``config.work_dir / <job_id>`` so
cleanup is deterministic and failures do not leak temp data across jobs.
"""

from __future__ import annotations

import json
import shutil
import tarfile
import time
import typing as t
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pulldb.domain.config import Config, S3BackupLocationConfig
from pulldb.domain.errors import (
    BackupDiscoveryError,
    BackupValidationError,
    CancellationError,
    DownloadError,
    ExtractionError,
    TargetCollisionError,
)
from pulldb.domain.config import parse_s3_bucket_path
from pulldb.domain.models import Job
from pulldb.infra.logging import get_logger
from pulldb.infra.s3 import (
    BackupSpec,
    S3Client,
    discover_latest_backup,
)
from pulldb.infra.secrets import MySQLCredentials
from pulldb.worker.downloader import download_backup
from pulldb.worker.heartbeat import HeartbeatContext
from pulldb.worker.post_sql import PostSQLConnectionSpec
from pulldb.worker.profiling import RestorePhase, RestoreProfiler
from pulldb.worker.restore import (
    build_restore_workflow_spec,
    orchestrate_restore_workflow,
)
from pulldb.worker.staging import StagingConnectionSpec


logger = get_logger("pulldb.worker.executor")

JobExecutor = t.Callable[[Job], None]

DEFAULT_MYSQL_TIMEOUT_SECONDS = 7200
DEFAULT_POST_SQL_TIMEOUT_SECONDS = 600

# Extraction progress emission thresholds (hybrid: bytes OR files OR time)
EXTRACTION_PROGRESS_BYTES = 64 * 1024 * 1024  # Every 64MB
EXTRACTION_PROGRESS_FILES = 1000  # Every 1000 files
EXTRACTION_PROGRESS_TIME = 30.0  # Every 30 seconds (fallback for large single files)

# Type alias for extraction progress callback
# (extracted_bytes, total_bytes, percent, elapsed_seconds, files_extracted, total_files)
ExtractionProgressCallback = t.Callable[[int, int, float, float, int, int], None]


def derive_backup_lookup_target(job: Job) -> str:
    """Return the canonical S3 target name for a job.

    S3 backups are stored under the original customer name (e.g., "antex"),
    not the target database name which includes user_code prefix and optional
    suffix (e.g., "charleantexzzz"). This function extracts the clean customer
    name for S3 lookup.

    Priority order:
    1. customer_id from options_json (cleanest source - original request value)
    2. is_qatemplate flag -> returns "qatemplate"
    3. Strip user_code prefix from target (legacy fallback)
    4. job.target as last resort
    """
    options = job.options_json or {}

    # Priority 1: Use customer_id from options - this is the clean original value
    raw_customer = options.get("customer_id")
    if isinstance(raw_customer, str):
        sanitized = "".join(ch for ch in raw_customer.lower() if ch.isalpha())
        if sanitized:
            return sanitized

    # Priority 2: Check for qatemplate restore
    raw_qatemplate = options.get("is_qatemplate", "")
    if isinstance(raw_qatemplate, str) and raw_qatemplate.strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return "qatemplate"

    # Priority 3: Strip user_code prefix from target (for legacy jobs without options)
    user_code = job.owner_user_code or ""
    target = job.target or ""
    if user_code and target.startswith(user_code):
        remainder = target[len(user_code):]
        if remainder:
            return remainder

    # Priority 4: Fall back to raw target
    logger.warning(
        "Unable to derive S3 backup target; defaulting to job.target",
        extra={"job_id": job.id, "target": job.target},
    )
    return job.target


def pre_flight_verify_target_overwrite_safe(
    job: Job,
    credentials: MySQLCredentials,
) -> None:
    """PRE-FLIGHT CHECK: Verify target is safe to overwrite BEFORE expensive operations.

    Called by worker at the START of restore, BEFORE:
    - Downloading backup from S3
    - Extracting archive
    - Running myloader
    - Any other expensive operations

    APPLIES TO ALL TARGETS (custom and auto-generated) when overwrite=true.

    Args:
        job: The job being executed.
        credentials: MySQL credentials for the target host.

    Raises:
        TargetCollisionError: If target exists but is not pullDB-managed,
            or if owned by a different user.
    """
    import mysql.connector

    options = job.options_json or {}
    overwrite = options.get("overwrite", "false") == "true"

    # Only check when overwrite is enabled
    if not overwrite:
        return  # No overwrite: skip check (new DB will be created)

    logger.info(
        "Pre-flight check: verifying target is safe to overwrite",
        extra={"job_id": job.id, "target": job.target, "dbhost": job.dbhost},
    )

    try:
        conn = mysql.connector.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.username,
            password=credentials.password,
            connect_timeout=30,
        )
    except mysql.connector.Error as e:
        # Can't connect - log warning but don't block (API check should have caught issues)
        logger.warning(
            "Pre-flight check: cannot connect to verify target - proceeding with caution",
            extra={"job_id": job.id, "target": job.target, "error": str(e)},
        )
        return

    try:
        cursor = conn.cursor()

        # Check if target database exists
        cursor.execute("SHOW DATABASES LIKE %s", (job.target,))
        if cursor.fetchone() is None:
            logger.info(
                "Pre-flight check: target does not exist - safe to proceed",
                extra={"job_id": job.id, "target": job.target},
            )
            return  # DB doesn't exist - safe to proceed

        # DB exists - check for pullDB metadata table
        try:
            cursor.execute(f"SHOW TABLES IN `{job.target}` LIKE 'pullDB'")
            has_pulldb_table = cursor.fetchone() is not None
        except mysql.connector.Error:
            # Can't query tables - assume external DB (fail safe)
            has_pulldb_table = False

        if not has_pulldb_table:
            # FAIL HARD, FAIL FAST: External database detected
            logger.error(
                "Pre-flight check FAILED: external database detected",
                extra={
                    "job_id": job.id,
                    "target": job.target,
                    "dbhost": job.dbhost,
                    "collision_type": "external_db",
                },
            )
            raise TargetCollisionError(
                job_id=job.id,
                target=job.target,
                dbhost=job.dbhost,
                collision_type="external_db",
            )

        # DB exists with pullDB table - check ownership
        try:
            cursor.execute(
                f"SELECT owner_user_code FROM `{job.target}`.pullDB "
                "ORDER BY restored_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
        except mysql.connector.Error:
            # Can't query ownership - table may be old schema, allow overwrite
            row = None

        if row:
            db_owner_code = str(row[0]) if row[0] else None
            if db_owner_code and db_owner_code != job.owner_user_code:
                # FAIL HARD: Database owned by different user
                logger.error(
                    "Pre-flight check FAILED: database owned by different user",
                    extra={
                        "job_id": job.id,
                        "target": job.target,
                        "dbhost": job.dbhost,
                        "db_owner": db_owner_code,
                        "job_owner": job.owner_user_code,
                    },
                )
                raise TargetCollisionError(
                    job_id=job.id,
                    target=job.target,
                    dbhost=job.dbhost,
                    collision_type="owner_mismatch",
                    owner_info=db_owner_code,
                )

        logger.info(
            "Pre-flight check passed: target is pullDB-managed and owned by job owner",
            extra={"job_id": job.id, "target": job.target},
        )

    finally:
        conn.close()


def build_lookup_targets_for_location(
    job: Job,
    location: S3BackupLocationConfig,
) -> list[str]:
    """Create ordered list of lookup targets for a job/location pair."""
    candidates: list[str] = []
    base_target = derive_backup_lookup_target(job)

    def _add(value: str | None) -> None:
        if value and value not in candidates:
            candidates.append(value)

    for key in (job.target, base_target):
        for alias in location.aliases_for_target(key):
            _add(alias)

    _add(base_target)
    _add(job.target)
    return candidates


def extract_tar_archive(
    archive_path: str,
    dest_dir: Path,
    job_id: str,
    progress_callback: ExtractionProgressCallback | None = None,
    abort_check: t.Callable[[], bool] | None = None,
) -> str:
    """Extract tar archive into *dest_dir* with progress reporting.

    Extracts member-by-member to support progress callbacks and abort checks.
    Emits progress every 64MB extracted OR every 1000 files OR every 30 seconds
    (hybrid approach ensures UI never appears frozen).

    Args:
        archive_path: Path to tar archive.
        dest_dir: Destination directory for extraction.
        job_id: Job identifier for error context.
        progress_callback: Optional callback for progress updates.
            Signature: (extracted_bytes, total_bytes, percent, elapsed_seconds,
                       files_extracted, total_files)
        abort_check: Optional callback that returns True to abort extraction.

    Returns:
        Path to destination directory.

    Raises:
        ExtractionError: When tar extraction fails or path escape attempted.
        CancellationError: If abort_check returns True during extraction.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:*") as tar:
            _safe_extract_with_progress(
                tar, dest_dir, progress_callback, abort_check, job_id
            )
    except CancellationError:
        raise  # Re-raise cancellation without wrapping
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise ExtractionError(job_id, archive_path, str(exc)) from exc
    return str(dest_dir)


def _safe_extract_with_progress(
    tar: tarfile.TarFile,
    dest: Path,
    progress_callback: ExtractionProgressCallback | None,
    abort_check: t.Callable[[], bool] | None,
    job_id: str,
) -> None:
    """Extract tar members with progress tracking and abort support.

    Validates each member path before extraction to prevent directory escape.
    Emits progress using hybrid threshold: 64MB or 1000 files or 30 seconds.
    """
    base = dest.resolve()
    members = tar.getmembers()
    total_files = len(members)
    total_bytes = sum(m.size for m in members if m.isfile())

    extracted_bytes = 0
    files_extracted = 0
    last_progress_bytes = 0
    last_progress_files = 0
    last_progress_time = time.monotonic()
    start_time = last_progress_time

    for member in members:
        # Abort check before each file
        if abort_check and abort_check():
            raise CancellationError(job_id, "extraction")

        # Validate path safety
        member_path = (base / member.name).resolve()
        if not str(member_path).startswith(str(base)):
            raise ValueError(
                f"Archive entry '{member.name}' escapes extraction directory"
            )

        # Extract single member
        tar.extract(member, path=base)
        files_extracted += 1
        if member.isfile():
            extracted_bytes += member.size

        # Emit progress using hybrid threshold (bytes OR files OR time)
        current_time = time.monotonic()
        bytes_since_last = extracted_bytes - last_progress_bytes
        files_since_last = files_extracted - last_progress_files
        time_since_last = current_time - last_progress_time

        should_emit = (
            bytes_since_last >= EXTRACTION_PROGRESS_BYTES
            or files_since_last >= EXTRACTION_PROGRESS_FILES
            or time_since_last >= EXTRACTION_PROGRESS_TIME
            or files_extracted == total_files  # Always emit on completion
        )

        if progress_callback and should_emit:
            elapsed = current_time - start_time
            percent = (extracted_bytes / total_bytes * 100) if total_bytes > 0 else 100.0
            progress_callback(
                extracted_bytes, total_bytes, percent, elapsed,
                files_extracted, total_files
            )
            last_progress_bytes = extracted_bytes
            last_progress_files = files_extracted
            last_progress_time = current_time


def _default_extract_archive(
    archive_path: str,
    dest_dir: Path,
    job_id: str,
    progress_callback: ExtractionProgressCallback | None = None,
    abort_check: t.Callable[[], bool] | None = None,
) -> str:
    """Forward to extract_tar_archive as overridable hook."""
    return extract_tar_archive(
        archive_path, dest_dir, job_id, progress_callback, abort_check
    )


def _get_dir_size(path: Path) -> int:
    """Calculate total size of all files in a directory recursively.

    Args:
        path: Directory path to measure.

    Returns:
        Total size in bytes of all files under the directory.
    """
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except OSError:
        pass  # Ignore permission errors, return what we have
    return total


@dataclass(slots=True)
class WorkerExecutorDependencies:
    """Repositories and shared clients required by the executor.

    Uses t.Any types to allow both real and simulated implementations.
    """

    job_repo: t.Any  # JobRepository or SimulatedJobRepository
    host_repo: t.Any  # HostRepository or SimulatedHostRepository
    s3_client: t.Any  # S3Client or MockS3Client


@dataclass(slots=True)
class WorkerExecutorTimeouts:
    """Timeout configuration in seconds for restore phases."""

    staging_seconds: int = DEFAULT_MYSQL_TIMEOUT_SECONDS
    post_sql_seconds: int = DEFAULT_POST_SQL_TIMEOUT_SECONDS


@dataclass(slots=True)
class WorkerExecutorHooks:
    """Optional hook overrides for discovery, download, and extraction."""

    discover_backup: t.Callable[[S3Client, str, str, str, str | None], BackupSpec] = (
        discover_latest_backup
    )
    download_backup: t.Callable[
        [
            S3Client,
            BackupSpec,
            str,
            str,
            t.Callable[[int, int, float, float], None] | None,
            t.Callable[[], bool] | None,
        ],
        str,
    ] = download_backup
    extract_archive: t.Callable[
        [str, Path, str, ExtractionProgressCallback | None, t.Callable[[], bool] | None],
        str,
    ] = _default_extract_archive


class WorkerJobExecutor:
    """Execute queued jobs end-to-end using downloader + restore workflow."""

    def __init__(
        self,
        *,
        config: Config,
        deps: WorkerExecutorDependencies,
        work_dir: Path | None = None,
        timeouts: WorkerExecutorTimeouts | None = None,
        hooks: WorkerExecutorHooks | None = None,
    ) -> None:
        """Initialize executor with dependencies, timeouts, and hooks."""
        timeout_cfg = timeouts or WorkerExecutorTimeouts()
        hook_cfg = hooks or WorkerExecutorHooks()
        self.config = config
        self.job_repo = deps.job_repo
        self.host_repo = deps.host_repo
        self.s3_client = deps.s3_client
        self.work_dir = Path(work_dir or config.work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.staging_timeout_seconds = timeout_cfg.staging_seconds
        self.post_sql_timeout_seconds = timeout_cfg.post_sql_seconds
        self._discover_backup = hook_cfg.discover_backup
        self._download_backup = hook_cfg.download_backup
        self._extract_archive = hook_cfg.extract_archive
        self.backup_locations = list(config.s3_backup_locations)
        if not self.backup_locations:
            if config.s3_bucket_path is None:
                msg = "Config must provide either s3_backup_locations or s3_bucket_path"
                raise ValueError(msg)
            bucket, prefix = parse_s3_bucket_path(config.s3_bucket_path)
            self.backup_locations.append(
                S3BackupLocationConfig(
                    name="default",
                    bucket_path=config.s3_bucket_path,
                    bucket=bucket,
                    prefix=prefix,
                    format_tag="legacy",
                )
            )

    def __call__(self, job: Job) -> None:
        """Invoke ``execute`` so the instance can act as a callable."""
        self.execute(job)

    def _check_cancellation(self, job_id: str, phase: str) -> None:
        """Check if job cancellation was requested; raise if so.

        Called at checkpoints between major phases to allow graceful
        termination. The caller is responsible for cleanup.

        Args:
            job_id: Job UUID to check.
            phase: Current phase name for logging (e.g., 'post_download').

        Raises:
            CancellationError: If cancellation was requested.
        """
        if self.job_repo.is_cancellation_requested(job_id):
            logger.info(
                "Cancellation detected at checkpoint",
                extra={"job_id": job_id, "phase": phase},
            )
            self._append_event(
                job_id,
                "cancellation_detected",
                {"phase": phase},
            )
            raise CancellationError(job_id, phase)

    def execute(self, job: Job) -> None:
        """Run the full restore workflow for a job.

        Wraps execution in a heartbeat context to prevent stale job detection
        from killing the worker during long-running operations. Heartbeat events
        are emitted every 60 seconds to keep the job alive.
        """
        logger.info(
            "Executing job",
            extra={"job_id": job.id, "target": job.target, "phase": "executor_start"},
        )

        # Create heartbeat emission function
        def _emit_heartbeat() -> None:
            try:
                self._append_event(job.id, "heartbeat", {"status": "worker_alive"})
            except Exception as e:
                logger.warning(
                    "Failed to emit heartbeat",
                    extra={"job_id": job.id, "error": str(e)},
                )

        # Wrap entire execution in heartbeat context to prevent stale detection
        with HeartbeatContext(_emit_heartbeat, interval_seconds=60.0):
            self._execute_workflow(job)

    def _execute_workflow(self, job: Job) -> None:
        """Internal workflow execution (called within heartbeat context)."""
        job_dir, download_dir, extract_dir = self._prepare_job_dirs(job.id)
        profiler = RestoreProfiler(job.id)

        try:
            host_credentials = self.host_repo.get_host_credentials(job.dbhost)

            # PRE-FLIGHT: Verify target is safe to overwrite BEFORE expensive operations
            # This catches external databases and ownership conflicts early
            pre_flight_verify_target_overwrite_safe(job, host_credentials)

            # Phase: Discovery
            with profiler.phase(RestorePhase.DISCOVERY) as discovery_profile:
                backup_spec, location, lookup_target = self.discover_backup_for_job(job)
                discovery_profile.metadata["bucket"] = backup_spec.bucket
                discovery_profile.metadata["key"] = backup_spec.key
                discovery_profile.metadata["lookup_target"] = lookup_target
                discovery_profile.metadata["location"] = location.name

            self._append_event(
                job.id,
                "backup_selected",
                {
                    "bucket": backup_spec.bucket,
                    "key": backup_spec.key,
                    "size_bytes": backup_spec.size_bytes,
                    "lookup_target": lookup_target,
                    "location": location.name,
                    "location_format": location.format_tag,
                },
            )

            self._append_event(
                job.id,
                "download_started",
                {"bucket": backup_spec.bucket, "key": backup_spec.key},
            )

            def _progress_callback(
                downloaded: int, total: int, percent: float, elapsed: float
            ) -> None:
                self._append_event(
                    job.id,
                    "download_progress",
                    {
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "percent_complete": percent,
                        "elapsed_seconds": round(elapsed, 1),
                    },
                )

            def _cancel_check() -> bool:
                # Check if job should abort: cancelled OR no longer running
                # This catches both user cancellation AND stale recovery marking job failed
                return bool(self.job_repo.should_abort_job(job.id))

            # Phase: Download
            with profiler.phase(RestorePhase.DOWNLOAD) as download_profile:
                download_profile.metadata["bucket"] = backup_spec.bucket
                download_profile.metadata["key"] = backup_spec.key
                archive_path = self._download_backup(
                    self.s3_client,
                    backup_spec,
                    job.id,
                    str(download_dir),
                    _progress_callback,
                    _cancel_check,
                )
                download_profile.metadata["bytes_processed"] = backup_spec.size_bytes
                download_profile.metadata["archive_path"] = archive_path

            self._append_event(
                job.id,
                "download_complete",
                {"path": archive_path},
            )

            # Checkpoint: check for cancellation after download
            self._check_cancellation(job.id, "post_download")

            # Progress callback for extraction phase
            def _extraction_progress_callback(
                extracted: int,
                total: int,
                percent: float,
                elapsed: float,
                files_extracted: int,
                total_files: int,
            ) -> None:
                self._append_event(
                    job.id,
                    "extraction_progress",
                    {
                        "extracted_bytes": extracted,
                        "total_bytes": total,
                        "percent_complete": round(percent, 1),
                        "elapsed_seconds": round(elapsed, 1),
                        "files_extracted": files_extracted,
                        "total_files": total_files,
                    },
                )

            self._append_event(
                job.id,
                "extraction_started",
                {"archive_path": archive_path, "archive_size": backup_spec.size_bytes},
            )

            # Phase: Extraction
            with profiler.phase(RestorePhase.EXTRACTION) as extraction_profile:
                extracted_dir = self._extract_archive(
                    archive_path,
                    extract_dir,
                    job.id,
                    _extraction_progress_callback,
                    _cancel_check,
                )
                extraction_profile.metadata["extracted_dir"] = extracted_dir
                # Estimate extracted size from archive size (typically 1:1 for tar)
                extraction_profile.metadata["bytes_processed"] = backup_spec.size_bytes

            self._append_event(
                job.id,
                "extraction_complete",
                {"path": extracted_dir},
            )

            # Checkpoint: check for cancellation after extraction
            self._check_cancellation(job.id, "post_extraction")

            # Resolve actual backup root (handle top-level directory in tarball)
            backup_dir = self._resolve_backup_dir(Path(extracted_dir))

            # Detect backup format from extracted contents (not S3 bucket)
            # This determines whether metadata synthesis is needed
            from pulldb.worker.restore import _detect_backup_version

            detected_version = _detect_backup_version(str(backup_dir))
            # format_tag is informational only - all backups use myloader 0.19.3-3
            # with metadata synthesis for legacy formats
            format_tag = "new" if "0.19" in detected_version else "legacy"

            self._append_event(
                job.id,
                "format_detected",
                {"detected_version": detected_version, "format_tag": format_tag},
            )

            # Checkpoint: check for cancellation before restore starts
            self._check_cancellation(job.id, "pre_restore")

            script_dir = self._resolve_post_sql_dir(job)
            staging_conn, post_sql_conn = self._build_connection_specs(
                job,
                host_credentials,
                script_dir,
            )

            # Progress callback for restore phase
            last_percent_logged = -1.0
            # Deduplication state for processlist_update events
            # Key: (rounded_percent, active_threads, tuple of (table, rounded_pct))
            last_processlist_key: tuple[int, int, tuple[tuple[str, int], ...]] | None = (
                None
            )

            def _restore_progress_callback(
                percent: float, detail: dict[str, t.Any]
            ) -> None:
                nonlocal last_percent_logged
                nonlocal last_processlist_key

                # Log file statistics as requested
                if detail.get("status") == "finished":
                    logger.info(
                        f"Restored file: {detail.get('file')}",
                        extra={
                            "job_id": job.id,
                            "phase": "restore_file",
                            "file": detail.get("file"),
                            "percent": f"{percent:.1f}",
                        },
                    )

                # Deduplicate processlist updates - only emit when meaningful change occurs
                # Emits when: overall percent changes by 1%+ OR any table progress changes by 1%+
                if detail.get("status") == "processlist_update":
                    # Build dedup key: overall percent (1% increments) + active threads + per-table progress
                    tables = detail.get("tables", {})
                    table_progress = tuple(
                        sorted(
                            (name, int(info.get("percent_complete", 0)))
                            for name, info in tables.items()
                        )
                    )
                    current_key = (
                        int(percent),
                        detail.get("active_threads", 0),
                        table_progress,
                    )

                    # Skip if identical to last emitted event
                    if current_key == last_processlist_key:
                        return

                    last_processlist_key = current_key
                    self._append_event(
                        job.id,
                        "restore_progress",
                        {"percent": percent, "detail": detail},
                    )
                    return

                # Emit progress event (throttled to every 5% or completion)
                if percent >= 100.0 or (percent - last_percent_logged) >= 5.0:
                    self._append_event(
                        job.id,
                        "restore_progress",
                        {"percent": percent, "detail": detail},
                    )
                    last_percent_logged = percent

            # Event callback for internal workflow phases (post_sql, metadata, atomic_rename)
            def _workflow_event_callback(event_type: str, detail: dict[str, t.Any]) -> None:
                self._append_event(job.id, event_type, detail)

            workflow_spec = build_restore_workflow_spec(
                config=self.config,
                job=job,
                backup_filename=backup_spec.filename,
                backup_dir=str(backup_dir),
                staging_conn=staging_conn,
                post_sql_conn=post_sql_conn,
                format_tag=format_tag,  # Detected from backup contents
                progress_callback=_restore_progress_callback,
                event_callback=_workflow_event_callback,
                abort_check=_cancel_check,  # Pass cancel check for myloader abort
            )

            # CRITICAL: Lock for restore - this is the point of no return.
            # Atomically verify no cancellation was requested and flip can_cancel to FALSE.
            # This prevents race conditions between cancel requests and restore start.
            # Use job.worker_id which was set when the job was claimed.
            worker_id = job.worker_id or "unknown"
            if not self.job_repo.lock_for_restore(job.id, worker_id):
                # Cancellation was requested between last checkpoint and now
                logger.info(
                    "Cancellation detected at restore gate, aborting before myloader",
                    extra={"job_id": job.id, "phase": "restore_gate"},
                )
                raise CancellationError(job.id, "restore_gate")

            self._append_event(
                job.id,
                "restore_started",
                {
                    "backup_filename": backup_spec.filename,
                    "staging_db": job.staging_name,
                },
            )

            # Note: orchestrate_restore_workflow internally profiles myloader, post_sql,
            # metadata, and atomic_rename phases. We wrap the entire call here for
            # the "restore" phase timing in the executor.
            workflow_result = orchestrate_restore_workflow(workflow_spec)

            # Add MYLOADER phase with throughput calculation from extracted dir size
            myloader_result = workflow_result.get("myloader")
            if myloader_result and hasattr(myloader_result, "duration_seconds"):
                myloader_profile = profiler.profile.start_phase(RestorePhase.MYLOADER)
                myloader_profile.duration_seconds = float(myloader_result.duration_seconds)
                myloader_profile.completed_at = datetime.now(UTC)
                # Calculate extracted directory size for accurate throughput
                extracted_bytes = _get_dir_size(backup_dir)
                if extracted_bytes > 0 and myloader_profile.duration_seconds > 0:
                    myloader_profile.bytes_processed = extracted_bytes
                    myloader_profile.bytes_per_second = (
                        extracted_bytes / myloader_profile.duration_seconds
                    )

            # Add internal workflow phase durations to profiler (no throughput for SQL ops)
            # These phases run inside orchestrate_restore_workflow and return timing in result
            for phase_key, phase_enum in [
                ("post_sql_duration_seconds", RestorePhase.POST_SQL),
                ("metadata_duration_seconds", RestorePhase.METADATA),
                ("atomic_rename_duration_seconds", RestorePhase.ATOMIC_RENAME),
            ]:
                if phase_key in workflow_result:
                    # Create phase profile with just the duration
                    phase_profile = profiler.profile.start_phase(phase_enum)
                    phase_profile.duration_seconds = float(workflow_result[phase_key])  # type: ignore[arg-type]
                    phase_profile.completed_at = datetime.now(UTC)

            self._append_event(
                job.id,
                "restore_complete",
                {
                    "backup_filename": backup_spec.filename,
                    "target": job.target,
                },
            )

            # Complete profiling and emit profile event
            profiler.complete()
            self._append_event(
                job.id,
                "restore_profile",
                profiler.profile.to_dict(),
            )

            self.job_repo.mark_job_deployed(job.id)
            logger.info(
                "Job deployed",
                extra={
                    "job_id": job.id,
                    "target": job.target,
                    "phase": "executor_deployed",
                    "profile": profiler.profile.phase_breakdown,
                },
            )
        except CancellationError as exc:
            # Cancellation is controlled termination, not an error
            profiler.complete(error=f"Canceled at {exc.detail.get('phase', 'unknown')}")
            self._append_event(job.id, "restore_profile", profiler.profile.to_dict())
            self._handle_failure(job, exc)
            # Don't re-raise - job terminated cleanly
        except Exception as exc:
            profiler.complete(error=str(exc))
            self._append_event(job.id, "restore_profile", profiler.profile.to_dict())
            self._handle_failure(job, exc)
            raise
        finally:
            self._cleanup_job_dir(job_dir)

    def _resolve_backup_dir(self, extracted_root: Path) -> Path:
        """Resolve the actual backup directory containing metadata.

        Handles cases where the tarball contains a top-level directory.
        """
        # Check for metadata in root
        if (extracted_root / "metadata").exists() or (
            extracted_root / "metadata.partial"
        ).exists():
            return extracted_root

        # Check subdirectories
        subdirs = [p for p in extracted_root.iterdir() if p.is_dir()]
        if len(subdirs) == 1:
            subdir = subdirs[0]
            if (subdir / "metadata").exists() or (subdir / "metadata.partial").exists():
                return subdir

        # If we can't find it, return root and let myloader fail (or raise here)
        return extracted_root

    def discover_backup_for_job(
        self,
        job: Job,
    ) -> tuple[BackupSpec, S3BackupLocationConfig, str]:
        """Discover backup for job, honoring user-selected backup_path if present.

        If job.options_json contains 'backup_path', the worker uses that specific
        backup instead of auto-discovering the latest. This ensures user selection
        is honored and jobs are deterministic.

        If backup_path is provided but the S3 object doesn't exist, this raises
        BackupDiscoveryError (no fallback to latest - FAIL HARD).

        Args:
            job: Job with options_json potentially containing backup_path.

        Returns:
            Tuple of (BackupSpec, S3BackupLocationConfig, lookup_target).

        Raises:
            BackupDiscoveryError: If backup not found (either user-selected or auto-discovery).
        """
        from pulldb.domain.config import find_location_for_backup_path, parse_backup_path
        from pulldb.infra.s3 import BACKUP_FILENAME_REGEX

        options = job.options_json or {}

        # Priority 1: Use user-selected backup_path if provided
        backup_path = options.get("backup_path")
        if backup_path:
            logger.info(
                "Using user-selected backup path",
                extra={"job_id": job.id, "backup_path": backup_path},
            )

            # Parse backup path
            parsed = parse_backup_path(backup_path)
            if not parsed:
                raise BackupDiscoveryError(
                    job.id,
                    [{"error": f"Invalid backup_path format: {backup_path}"}],
                )

            bucket, key = parsed

            # Find matching S3 location config
            location = find_location_for_backup_path(backup_path, self.backup_locations)
            if not location:
                raise BackupDiscoveryError(
                    job.id,
                    [{"error": f"No S3 location config matches backup_path: {backup_path}"}],
                )

            # Use stored profile or location's profile
            profile = options.get("s3_profile") or location.profile

            # Verify the backup exists in S3 (HEAD request)
            try:
                size_bytes = self.s3_client.get_object_size(bucket, key, profile=profile)
                if size_bytes is None:
                    raise BackupDiscoveryError(
                        job.id,
                        [{
                            "error": f"Backup not found in S3 (may have been deleted): s3://{bucket}/{key}",
                            "bucket": bucket,
                            "key": key,
                        }],
                    )
            except Exception as exc:
                raise BackupDiscoveryError(
                    job.id,
                    [{
                        "error": f"Failed to verify backup exists: {exc}",
                        "bucket": bucket,
                        "key": key,
                    }],
                ) from exc

            # Parse timestamp and target from filename
            filename = key.rsplit("/", 1)[-1] if "/" in key else key
            match = BACKUP_FILENAME_REGEX.match(filename)
            if match:
                target = match.group("target")
                ts_str = match.group("ts")
                # Parse timestamp: 2024-01-02T12-30-45Z -> datetime
                try:
                    timestamp = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=UTC)
                except ValueError:
                    timestamp = datetime.now(UTC)
            else:
                # Fallback: derive target from customer_id
                target = options.get("customer_id", "unknown")
                timestamp = datetime.now(UTC)

            spec = BackupSpec(
                bucket=bucket,
                key=key,
                target=target,
                timestamp=timestamp,
                size_bytes=size_bytes,
                format_tag=location.format_tag,
                profile=profile,
            )

            return spec, location, target

        # FAIL HARD: backup_path is required - no auto-discovery fallback
        raise BackupDiscoveryError(
            job.id,
            [{
                "error": "Job missing required backup_path in options_json. "
                         "Jobs must specify the exact backup to restore. "
                         "This job may have been submitted before backup_path was required.",
                "api_version": options.get("api_version", "unknown"),
            }],
        )

    def _prepare_job_dirs(self, job_id: str) -> tuple[Path, Path, Path]:
        job_dir = self.work_dir / job_id
        download_dir = job_dir / "download"
        extract_dir = job_dir / "extracted"
        download_dir.mkdir(parents=True, exist_ok=True)
        extract_dir.mkdir(parents=True, exist_ok=True)
        return job_dir, download_dir, extract_dir

    def _cleanup_job_dir(self, job_dir: Path) -> None:
        try:
            shutil.rmtree(job_dir)
        except FileNotFoundError:  # pragma: no cover - best effort cleanup
            return
        except Exception as exc:  # pragma: no cover - log but do not raise
            logger.warning(
                "Failed to cleanup job work dir",
                extra={"job_dir": str(job_dir), "error": str(exc)},
            )

    def _resolve_post_sql_dir(self, job: Job) -> Path:
        options = job.options_json or {}
        raw_is_qatemplate = options.get("is_qatemplate")
        is_qatemplate = False
        if isinstance(raw_is_qatemplate, str):
            is_qatemplate = raw_is_qatemplate.strip().lower() in {"1", "true", "yes"}
        return (
            self.config.qa_template_after_sql_dir
            if is_qatemplate
            else self.config.customers_after_sql_dir
        )

    def _build_connection_specs(
        self,
        job: Job,
        creds: MySQLCredentials,
        script_dir: Path,
    ) -> tuple[StagingConnectionSpec, PostSQLConnectionSpec]:
        staging_conn = StagingConnectionSpec(
            mysql_host=creds.host,
            mysql_port=creds.port,
            mysql_user=creds.username,
            mysql_password=creds.password,
            timeout_seconds=self.staging_timeout_seconds,
        )
        post_sql_conn = PostSQLConnectionSpec(
            staging_db=job.staging_name,
            script_dir=script_dir,
            mysql_host=creds.host,
            mysql_port=creds.port,
            mysql_user=creds.username,
            mysql_password=creds.password,
            # Use default connect_timeout (5s) from PostSQLConnectionSpec
            # post_sql_timeout_seconds is for script execution, not connection
        )
        return staging_conn, post_sql_conn

    def _append_event(
        self,
        job_id: str,
        event_type: str,
        detail: dict[str, t.Any],
    ) -> None:
        detail_json = json.dumps(detail, separators=(",", ":"))
        try:
            self.job_repo.append_job_event(job_id, event_type, detail_json)
        except Exception:  # pragma: no cover - logging only
            logger.exception(
                "Failed to append job event",
                extra={"job_id": job_id, "event_type": event_type},
            )

    def _handle_failure(self, job: Job, exc: Exception) -> None:
        # Handle cancellation specially - mark as canceled, not failed
        if isinstance(exc, CancellationError):
            try:
                self.job_repo.mark_job_canceled(
                    job.id,
                    f"Canceled by user at phase: {exc.detail.get('phase', 'unknown')}",
                )
                logger.info(
                    "Job canceled successfully",
                    extra={"job_id": job.id, "phase": exc.detail.get("phase")},
                )
            except Exception:  # pragma: no cover - logging only
                logger.exception(
                    "Failed to mark job as canceled",
                    extra={"job_id": job.id, "target": job.target},
                )
            return

        event_type = "restore_failed"
        if isinstance(exc, (DownloadError, BackupDiscoveryError)):
            event_type = "download_failed"
        elif isinstance(exc, ExtractionError):
            event_type = "extraction_failed"

        # Extract command output from exceptions that capture it
        event_detail = self._extract_failure_detail(exc)

        self._append_event(job.id, event_type, event_detail)
        try:
            # Redact sensitive data from the error message stored in job status
            from pulldb.infra.exec import redact_sensitive_data

            self.job_repo.mark_job_failed(job.id, redact_sensitive_data(str(exc)))
        except Exception:  # pragma: no cover - logging only
            logger.exception(
                "Failed to mark job as failed",
                extra={"job_id": job.id, "target": job.target},
            )

    def _extract_failure_detail(self, exc: Exception) -> dict[str, t.Any]:
        """Extract structured failure detail from exception, redacting secrets.

        Extracts stdout/stderr from exceptions that capture command output,
        and applies password redaction to prevent credential leakage in logs.

        Handles:
          - MyLoaderError: stdout/stderr in detail dict
          - CommandAbortedError: partial_stdout attribute
          - CommandTimeoutError: partial_stdout/partial_stderr attributes
          - JobExecutionError subclasses: detail dict
          - Generic Exception: just error name and message

        Returns:
            Dict with error type, detail message, and optionally stdout/stderr.
        """
        from pulldb.infra.exec import (
            CommandAbortedError,
            CommandTimeoutError,
            redact_sensitive_data,
        )
        from pulldb.domain.errors import JobExecutionError

        result: dict[str, t.Any] = {
            "error": exc.__class__.__name__,
            "detail": redact_sensitive_data(str(exc)),
        }

        # CommandAbortedError: worker death or job cancellation during execution
        if isinstance(exc, CommandAbortedError):
            if hasattr(exc, "partial_stdout") and exc.partial_stdout:
                result["stdout"] = redact_sensitive_data(exc.partial_stdout[-5000:])
            if hasattr(exc, "command") and exc.command:
                result["command"] = redact_sensitive_data(" ".join(exc.command))
            return result

        # CommandTimeoutError: command exceeded timeout
        if isinstance(exc, CommandTimeoutError):
            if hasattr(exc, "partial_stdout") and exc.partial_stdout:
                result["stdout"] = redact_sensitive_data(exc.partial_stdout[-5000:])
            if hasattr(exc, "partial_stderr") and exc.partial_stderr:
                result["stderr"] = redact_sensitive_data(exc.partial_stderr[-5000:])
            if hasattr(exc, "command") and exc.command:
                result["command"] = redact_sensitive_data(" ".join(exc.command))
            return result

        # JobExecutionError subclasses: have detail dict with structured info
        if isinstance(exc, JobExecutionError) and hasattr(exc, "detail"):
            detail = exc.detail
            if isinstance(detail, dict):
                # Extract and redact command output
                if "stdout" in detail:
                    result["stdout"] = redact_sensitive_data(str(detail["stdout"])[-5000:])
                if "stderr" in detail:
                    result["stderr"] = redact_sensitive_data(str(detail["stderr"])[-5000:])
                if "command" in detail:
                    result["command"] = redact_sensitive_data(str(detail["command"]))
                if "exit_code" in detail:
                    result["exit_code"] = detail["exit_code"]

        return result


__all__ = [
    "JobExecutor",
    "WorkerExecutorDependencies",
    "WorkerExecutorHooks",
    "WorkerExecutorTimeouts",
    "WorkerJobExecutor",
    "build_lookup_targets_for_location",
    "derive_backup_lookup_target",
    "extract_tar_archive",
]
