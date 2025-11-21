"""Tests for worker.executor helper behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

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
) -> WorkerJobExecutor:
    config = Config(
        mysql_host="localhost",
        mysql_user="pulldb",
        mysql_password="secret",
        s3_backup_locations=locations,
        work_dir=tmp_path / "work",
    )
    deps = WorkerExecutorDependencies(
        job_repo=MagicMock(spec=JobRepository),
        host_repo=MagicMock(spec=HostRepository),
        s3_client=cast(S3Client, object()),
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


def test_discover_backup_iterates_locations(tmp_path: Path) -> None:
    job = _job()
    first = _location("staging", "staging-bucket", "daily/stg")
    second = _location("prod", "prod-bucket", "daily/prod", format_tag="prod")
    calls: list[tuple[str, str, str]] = []

    def fake_discover(
        _client: S3Client,
        bucket: str,
        prefix: str,
        target: str,
    ) -> BackupSpec:
        calls.append((bucket, prefix, target))
        if bucket == "staging-bucket":
            raise BackupValidationError(job.id, f"s3://{bucket}/{prefix}", ["tar"])
        return BackupSpec(
            bucket=bucket,
            key=f"{prefix}daily_mydumper_{target}_2024-01-01T00-00-00Z_Mon_dbimp.tar",
            target=target,
            timestamp=datetime(2024, 1, 1),
            size_bytes=123,
        )

    hooks = WorkerExecutorHooks(discover_backup=fake_discover)
    executor = _make_executor(tmp_path, locations=(first, second), hooks=hooks)

    spec, location, lookup_target = executor.discover_backup_for_job(job)

    assert location.name == "prod"
    assert lookup_target == "acme"
    assert spec.bucket == "prod-bucket"
    assert spec.format_tag == "prod"
    assert calls == [
        ("staging-bucket", "daily/stg/", "acme"),
        ("staging-bucket", "daily/stg/", "qaengiacme"),
        ("prod-bucket", "daily/prod/", "acme"),
    ]


def test_discover_backup_raises_when_all_locations_fail(tmp_path: Path) -> None:
    job = _job()
    location = _location("prod", "prod-bucket", "daily/prod")

    def fail_discover(
        _client: S3Client,
        _bucket: str,
        _prefix: str,
        _target: str,
    ) -> BackupSpec:
        raise BackupValidationError(job.id, "s3://prod-bucket/daily/prod/", ["tar"])

    hooks = WorkerExecutorHooks(discover_backup=fail_discover)
    executor = _make_executor(tmp_path, locations=(location,), hooks=hooks)

    try:
        executor.discover_backup_for_job(job)
    except BackupDiscoveryError as exc:
        detail = exc.detail
        assert isinstance(detail, dict)
        assert detail["job_id"] == job.id
        assert len(detail["attempts"]) == 2
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected BackupDiscoveryError when all locations fail")
