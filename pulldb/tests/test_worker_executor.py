"""Tests for worker.executor helper behavior."""

from __future__ import annotations

"""HCA Layer: tests."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from pulldb.domain.config import Config, S3BackupLocationConfig
from pulldb.domain.errors import BackupDiscoveryError, BackupValidationError
from pulldb.domain.models import Job, JobStatus
from pulldb.infra.mysql import HostRepository, JobRepository
from pulldb.infra.s3 import BackupSpec, S3Client
from pulldb.worker.executor import (
    WorkerExecutorDependencies,
    WorkerExecutorHooks,
    WorkerJobExecutor,
    build_lookup_targets_for_location,
    derive_backup_lookup_target,
)


_BASE_JOB = Job(
    id="job-123",
    owner_user_id="owner-1",
    owner_username="qaengineer",
    owner_user_code="qaengi",
    target="qaengiacme",
    staging_name="qaengiacme_deadbeefcafe",
    dbhost="localhost",
    status=JobStatus.QUEUED,
    submitted_at=datetime.now(),
    options_json={"customer_id": "acme"},
    retry_count=0,
)


def _job(**overrides: object) -> Job:
    return replace(_BASE_JOB, **overrides)


def test_derive_backup_target_strips_user_code() -> None:
    job = _job()
    assert derive_backup_lookup_target(job) == "acme"


def test_derive_backup_target_qatemplate_suffix() -> None:
    job = _job(target="qaengiqatemplate", options_json={"is_qatemplate": "true"})
    assert derive_backup_lookup_target(job) == "qatemplate"


def test_derive_backup_target_falls_back_to_options() -> None:
    job = _job(
        target="mismatch",
        options_json={"customer_id": "ACME-123"},
    )
    assert derive_backup_lookup_target(job) == "acme"


def test_derive_backup_target_defaults_to_target() -> None:
    job = _job(target="lonely", options_json=None)
    assert derive_backup_lookup_target(job) == "lonely"


def _make_executor(
    tmp_path: Path,
    *,
    locations: tuple[S3BackupLocationConfig, ...],
    hooks: WorkerExecutorHooks | None = None,
    s3_client: S3Client | None = None,
) -> WorkerJobExecutor:
    config = Config(
        mysql_host="localhost",
        mysql_user="pulldb_app",
        mysql_password="secret",
        s3_backup_locations=locations,
        work_dir=tmp_path / "work",
    )
    deps = WorkerExecutorDependencies(
        job_repo=MagicMock(spec=JobRepository),
        host_repo=MagicMock(spec=HostRepository),
        s3_client=s3_client if s3_client else cast(S3Client, object()),
    )
    return WorkerJobExecutor(
        config=config,
        deps=deps,
        work_dir=tmp_path / "work",
        hooks=hooks,
    )


def _location(
    name: str,
    bucket: str,
    prefix: str,
    *,
    format_tag: str = "legacy",
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> S3BackupLocationConfig:
    bucket_path = f"s3://{bucket}/{prefix.strip('/')}"
    normalized_prefix = f"{prefix.strip('/')}/"
    return S3BackupLocationConfig(
        name,
        bucket_path,
        bucket,
        normalized_prefix,
        format_tag,
        aliases or {},
    )


def test_build_lookup_targets_function_includes_aliases() -> None:
    job = _job(target="qaengiqatemplate", options_json={"is_qatemplate": "true"})
    location = _location(
        "prod",
        "backups",
        "daily/prod",
        aliases={
            "qatemplate": ("qatemplate", "qatemplate_legacy"),
        },
    )

    targets = build_lookup_targets_for_location(job, location)

    assert targets == ["qatemplate", "qatemplate_legacy", "qaengiqatemplate"]


def test_discover_backup_with_backup_path(tmp_path: Path) -> None:
    """Test that backup_path in options_json is used directly."""
    backup_path = "s3://prod-bucket/daily/prod/daily_mydumper_acme_2024-01-01T00-00-00Z_Mon_dbimp.tar"
    job = _job(options_json={"customer_id": "acme", "backup_path": backup_path})
    location = _location("prod", "prod-bucket", "daily/prod", format_tag="prod")

    # Mock S3 client to return size for the backup
    mock_s3 = MagicMock(spec=S3Client)
    mock_s3.get_object_size.return_value = 12345

    executor = _make_executor(tmp_path, locations=(location,), s3_client=mock_s3)

    spec, returned_location, lookup_target = executor.discover_backup_for_job(job)

    assert spec.bucket == "prod-bucket"
    assert "acme" in spec.key
    assert returned_location.name == "prod"
    assert spec.size_bytes == 12345
    mock_s3.get_object_size.assert_called_once()


def test_discover_backup_raises_when_backup_path_missing(tmp_path: Path) -> None:
    """Test that BackupDiscoveryError is raised when backup_path not in options."""
    job = _job()  # No backup_path in options_json
    location = _location("prod", "prod-bucket", "daily/prod")

    executor = _make_executor(tmp_path, locations=(location,))

    with pytest.raises(BackupDiscoveryError) as exc_info:
        executor.discover_backup_for_job(job)

    assert "backup_path" in str(exc_info.value)
