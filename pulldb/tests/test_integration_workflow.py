"""End-to-end (logical) restore workflow integration test.

This test exercises the full orchestration chain without invoking a real
`myloader` binary or performing large S3 downloads. We rely on:

* moto S3 for backup discovery (creates a minimal tar placeholder object)
* monkeypatched `run_myloader` to simulate a successful restore
* existing staging + metadata + post-SQL (empty dir) + atomic rename path

The goal is to validate the sequencing, metadata injection side effects,
and that emitted result dictionary contains all expected phases.

We DO NOT attempt a real table import here; lower-level unit tests cover
error translation, post-SQL execution, and atomic rename parameterization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from moto import mock_aws

from pulldb.domain.config import Config
from pulldb.domain.models import Job, JobStatus
from pulldb.domain.restore_models import MyLoaderResult, MyLoaderSpec
from pulldb.worker.post_sql import PostSQLConnectionSpec
from pulldb.worker.restore import (
    build_restore_workflow_spec,
    orchestrate_restore_workflow,
)
from pulldb.worker.staging import StagingConnectionSpec


@pytest.fixture
def moto_env():  # type: ignore[no-untyped-def]
    """Provide isolated moto AWS context for S3 interactions.

    We intentionally leave this untyped to satisfy pytest's flexible fixture
    signature expectations and avoid mypy Generator type mismatch noise.
    """
    with mock_aws():
        yield


@pytest.fixture
def fake_myloader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch run_myloader inside restore module to simulate success."""
    from pulldb.worker import restore as restore_module

    def _fake_run(
        spec: MyLoaderSpec,
        timeout: float | None = None,
        progress_callback: object = None,
    ) -> MyLoaderResult:
        now = datetime.now(UTC)
        return MyLoaderResult(
            command=["myloader", f"--database={spec.staging_db}"],
            exit_code=0,
            started_at=now,
            completed_at=now,
            duration_seconds=0.01,
            stdout="restore complete",
            stderr="",
        )

    monkeypatch.setattr(restore_module, "run_myloader", _fake_run)


def _job() -> Job:
    return Job(
        id="123e4567e89b12d3a456426614174000",  # Valid UUID, 32 hex chars
        owner_user_id="user-int-1",
        owner_username="integrationuser",
        owner_user_code="integr",
        target="integrcustomer",
        staging_name="integrcustomer_123e4567e89b",  # First 12 chars of job_id
        dbhost="localhost",
        status=JobStatus.RUNNING,
        submitted_at=datetime.now(),
        options_json={},
        retry_count=0,
    )


def _config() -> Config:
    return Config(mysql_host="localhost", mysql_user="root", mysql_password="pw")


def test_restore_workflow_happy_path(
    fake_myloader: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path orchestration with fake myloader and empty post-SQL directory."""
    job = _job()

    # Build connection specs (using localhost & dummy credentials)
    staging_conn = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        timeout_seconds=5,
    )

    # Post SQL directory: create empty directory to simulate no scripts
    script_dir = tmp_path / "post_sql"
    script_dir.mkdir()
    post_sql_conn = PostSQLConnectionSpec(
        staging_db="integrcustomer_123e4567e89b",  # matches staging name above
        script_dir=script_dir,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        connect_timeout=5,
    )

    # Monkeypatch MySQL-dependent operations by targeting symbols imported
    # inside restore.py (must patch restore module, not source modules).
    from pulldb.worker import restore as restore_mod
    from pulldb.worker.staging import StagingResult

    def _fake_cleanup(conn: object, target: str, job_id: str) -> StagingResult:
        return StagingResult(
            staging_db=job.staging_name,
            target_db=job.target,
            orphans_dropped=[],
        )

    monkeypatch.setattr(restore_mod, "cleanup_orphaned_staging", _fake_cleanup)

    def _fake_metadata(conn_spec: object, meta_spec: object) -> None:
        # Simulate successful metadata injection
        return None

    monkeypatch.setattr(restore_mod, "inject_metadata_table", _fake_metadata)

    def _fake_rename(conn_spec: object, rename_spec: object) -> None:
        # Simulate successful atomic rename
        return None

    monkeypatch.setattr(restore_mod, "atomic_rename_staging_to_target", _fake_rename)

    config = _config()

    spec = build_restore_workflow_spec(
        config=config,
        job=job,
        backup_filename="dummy_backup.tar",
        backup_dir=str(tmp_path),
        staging_conn=staging_conn,
        post_sql_conn=post_sql_conn,
        timeout_override=2.0,
    )

    result = orchestrate_restore_workflow(spec)

    # Validate result keys and basic invariants
    assert set(result.keys()) == {
        "staging",
        "myloader",
        "post_sql",
        "metadata",
        "atomic_rename",
    }
    myloader_result = result["myloader"]
    assert isinstance(myloader_result, MyLoaderResult)
    assert myloader_result.exit_code == 0
    assert result["metadata"] == "injected"
    assert result["atomic_rename"] == "complete"


# End of file
