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
    ExtractionError,
)
from pulldb.domain.models import Job
from pulldb.infra.logging import get_logger
from pulldb.infra.mysql import HostRepository, JobRepository
from pulldb.infra.s3 import (
    BackupSpec,
    S3Client,
    discover_latest_backup,
    parse_s3_bucket_path,
)
from pulldb.infra.secrets import MySQLCredentials
from pulldb.worker.downloader import download_backup
from pulldb.worker.post_sql import PostSQLConnectionSpec
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
    """Repositories and shared clients required by the executor."""

    job_repo: JobRepository
    host_repo: HostRepository
    s3_client: S3Client


@dataclass(slots=True)
class WorkerExecutorTimeouts:
    """Timeout configuration in seconds for restore phases."""

    staging_seconds: int = DEFAULT_MYSQL_TIMEOUT_SECONDS
    post_sql_seconds: int = DEFAULT_POST_SQL_TIMEOUT_SECONDS


@dataclass(slots=True)
class WorkerExecutorHooks:
    """Optional hook overrides for discovery, download, and extraction."""

    discover_backup: t.Callable[[S3Client, str, str, str], BackupSpec] = (
        discover_latest_backup
    )
    download_backup: t.Callable[[S3Client, BackupSpec, str, str], str] = (
        download_backup
    )
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
                msg = (
                    "Config must provide either s3_backup_locations or s3_bucket_path"
                )
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

    def execute(self, job: Job) -> None:
        """Run the full restore workflow for a job."""
        logger.info(
            "Executing job",
            extra={"job_id": job.id, "target": job.target, "phase": "executor_start"},
        )
        job_dir, download_dir, extract_dir = self._prepare_job_dirs(job.id)
        try:
            host_credentials = self.host_repo.get_host_credentials(job.dbhost)
            backup_spec, location, lookup_target = self.discover_backup_for_job(job)
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
            archive_path = self._download_backup(
                self.s3_client,
                backup_spec,
                job.id,
                str(download_dir),
            )
            self._append_event(
                job.id,
                "download_complete",
                {"path": archive_path},
            )

            extracted_dir = self._extract_archive(archive_path, extract_dir, job.id)
            self._append_event(
                job.id,
                "extraction_complete",
                {"path": extracted_dir},
            )

            script_dir = self._resolve_post_sql_dir(job)
            staging_conn, post_sql_conn = self._build_connection_specs(
                job,
                host_credentials,
                script_dir,
            )

            workflow_spec = build_restore_workflow_spec(
                config=self.config,
                job=job,
                backup_filename=backup_spec.filename,
                backup_dir=extracted_dir,
                staging_conn=staging_conn,
                post_sql_conn=post_sql_conn,
            )
            self._append_event(
                job.id,
                "restore_started",
                {
                    "backup_filename": backup_spec.filename,
                    "staging_db": job.staging_name,
                },
            )

            orchestrate_restore_workflow(workflow_spec)

            self._append_event(
                job.id,
                "restore_complete",
                {
                    "backup_filename": backup_spec.filename,
                    "target": job.target,
                },
            )
            self.job_repo.mark_job_complete(job.id)
            logger.info(
                "Job completed",
                extra={
                    "job_id": job.id,
                    "target": job.target,
                    "phase": "executor_complete",
                },
            )
        except Exception as exc:
            self._handle_failure(job, exc)
            raise
        finally:
            self._cleanup_job_dir(job_dir)

    def discover_backup_for_job(
        self,
        job: Job,
    ) -> tuple[BackupSpec, S3BackupLocationConfig, str]:
        attempts: list[dict[str, str]] = []
        for location in self.backup_locations:
            for lookup_target in build_lookup_targets_for_location(job, location):
                try:
                    spec = self._discover_backup(
                        self.s3_client,
                        location.bucket,
                        location.prefix,
                        lookup_target,
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
                spec.format_tag = location.format_tag
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
        self._append_event(
            job.id,
            "restore_failed",
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
    "build_lookup_targets_for_location",
    "derive_backup_lookup_target",
    "JobExecutor",
    "WorkerExecutorDependencies",
    "WorkerExecutorHooks",
    "WorkerExecutorTimeouts",
    "WorkerJobExecutor",
    "extract_tar_archive",
]
