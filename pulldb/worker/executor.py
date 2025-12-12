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
import typing as t
from dataclasses import dataclass
from pathlib import Path

from pulldb.domain.config import Config, S3BackupLocationConfig
from pulldb.domain.errors import (
    BackupDiscoveryError,
    BackupValidationError,
    CancellationError,
    DownloadError,
    ExtractionError,
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


def derive_backup_lookup_target(job: Job) -> str:
    """Return the canonical S3 target name for a job.

    Customer restores store backups under the sanitized customer token while
    target databases prepend the operator's user_code. This helper strips the
    user_code prefix (when present) and falls back to the options snapshot so
    discovery queries the correct S3 key namespace.
    """
    user_code = job.owner_user_code or ""
    target = job.target or ""
    if user_code and target.startswith(user_code):
        suffix = target[len(user_code) :]
        if suffix:
            return suffix

    options = job.options_json or {}
    raw_customer = options.get("customer_id")
    if isinstance(raw_customer, str):
        sanitized = "".join(ch for ch in raw_customer.lower() if ch.isalpha())
        if sanitized:
            return sanitized

    raw_qatemplate = options.get("is_qatemplate", "")
    if isinstance(raw_qatemplate, str) and raw_qatemplate.strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return "qatemplate"

    logger.warning(
        "Unable to derive S3 backup target; defaulting to job.target",
        extra={"job_id": job.id, "target": job.target},
    )
    return job.target


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


def extract_tar_archive(archive_path: str, dest_dir: Path, job_id: str) -> str:
    """Extract tar archive into *dest_dir* returning directory path.

    Raises ``ExtractionError`` when tar extraction fails or attempts to escape
    the destination directory.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:*") as tar:
            _safe_extract(tar, dest_dir)
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise ExtractionError(job_id, archive_path, str(exc)) from exc
    return str(dest_dir)


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    base = dest.resolve()
    for member in tar.getmembers():
        member_path = (base / member.name).resolve()
        if not str(member_path).startswith(str(base)):
            raise ValueError(
                f"Archive entry '{member.name}' escapes extraction directory"
            )
    tar.extractall(path=base)


def _default_extract_archive(archive_path: str, dest_dir: Path, job_id: str) -> str:
    """Forward to extract_tar_archive as overridable hook."""
    return extract_tar_archive(archive_path, dest_dir, job_id)


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
        [S3Client, BackupSpec, str, str, t.Callable[[int, int], None] | None], str
    ] = download_backup
    extract_archive: t.Callable[[str, Path, str], str] = _default_extract_archive


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
        """Run the full restore workflow for a job."""
        logger.info(
            "Executing job",
            extra={"job_id": job.id, "target": job.target, "phase": "executor_start"},
        )
        job_dir, download_dir, extract_dir = self._prepare_job_dirs(job.id)
        profiler = RestoreProfiler(job.id)

        try:
            host_credentials = self.host_repo.get_host_credentials(job.dbhost)

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

            def _progress_callback(downloaded: int, total: int) -> None:
                self._append_event(
                    job.id,
                    "download_progress",
                    {"downloaded_bytes": downloaded, "total_bytes": total},
                )

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

            # Phase: Extraction
            with profiler.phase(RestorePhase.EXTRACTION) as extraction_profile:
                extracted_dir = self._extract_archive(archive_path, extract_dir, job.id)
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

            def _restore_progress_callback(
                percent: float, detail: dict[str, t.Any]
            ) -> None:
                nonlocal last_percent_logged

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

                # Emit progress event (throttled to every 5% or completion)
                if percent >= 100.0 or (percent - last_percent_logged) >= 5.0:
                    self._append_event(
                        job.id,
                        "restore_progress",
                        {"percent": percent, "detail": detail},
                    )
                    last_percent_logged = percent

            workflow_spec = build_restore_workflow_spec(
                config=self.config,
                job=job,
                backup_filename=backup_spec.filename,
                backup_dir=str(backup_dir),
                staging_conn=staging_conn,
                post_sql_conn=post_sql_conn,
                format_tag=format_tag,  # Detected from backup contents
                progress_callback=_restore_progress_callback,
            )
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
            orchestrate_restore_workflow(workflow_spec)

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

            self.job_repo.mark_job_complete(job.id)
            logger.info(
                "Job completed",
                extra={
                    "job_id": job.id,
                    "target": job.target,
                    "phase": "executor_complete",
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
        attempts: list[dict[str, str]] = []
        
        # Get env filter from job options (if specified)
        options = job.options_json or {}
        job_env = options.get("env")  # e.g., "staging", "prod", or None for all
        
        # Filter locations by job's env preference
        locations_to_search = self.backup_locations
        if job_env:
            locations_to_search = [
                loc for loc in self.backup_locations
                if loc.name.lower() == job_env.lower()
                or job_env.lower() in loc.name.lower()
            ]
            if not locations_to_search:
                # No matching locations - log and fall back to all locations
                logger.warning(
                    "No backup locations match requested env, searching all",
                    extra={"job_id": job.id, "requested_env": job_env},
                )
                locations_to_search = self.backup_locations
        
        for location in locations_to_search:
            for lookup_target in build_lookup_targets_for_location(job, location):
                try:
                    spec = self._discover_backup(
                        self.s3_client,
                        location.bucket,
                        location.prefix,
                        lookup_target,
                        location.profile,
                    )
                except BackupValidationError as exc:
                    attempts.append(
                        {
                            "location": location.name,
                            "bucket": location.bucket,
                            "prefix": location.prefix,
                            "lookup_target": lookup_target,
                            "error": str(exc),
                        }
                    )
                    continue
                # spec.format_tag is already set by discover_latest_backup based on bucket
                # Do not overwrite it with location.format_tag which defaults to legacy
                return spec, location, lookup_target
        raise BackupDiscoveryError(job.id, attempts)

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
            connect_timeout=self.post_sql_timeout_seconds,
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

        self._append_event(
            job.id,
            event_type,
            {"error": str(exc.__class__.__name__), "detail": str(exc)},
        )
        try:
            self.job_repo.mark_job_failed(job.id, str(exc))
        except Exception:  # pragma: no cover - logging only
            logger.exception(
                "Failed to mark job as failed",
                extra={"job_id": job.id, "target": job.target},
            )


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
