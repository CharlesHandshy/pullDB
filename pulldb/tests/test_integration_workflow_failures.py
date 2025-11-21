"""Failure-mode integration tests for restore workflow.

Covers:
* Myloader failure propagation
* Post-SQL script execution failure propagation
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulldb.domain.config import Config
from pulldb.domain.errors import MyLoaderError, PostSQLError
from pulldb.domain.models import Job, JobStatus
from pulldb.domain.restore_models import MyLoaderResult, MyLoaderSpec
from pulldb.worker.post_sql import PostSQLConnectionSpec
from pulldb.worker.restore import (
    RestoreWorkflowSpec,
    build_restore_workflow_spec,
    orchestrate_restore_workflow,
)
from pulldb.worker.staging import StagingConnectionSpec


@pytest.fixture(name="job_fixture")
def job_fixture() -> Job:
    return Job(
        id="550e8400e29b41d4a716446655440000",  # Valid UUID, 32 hex chars
        owner_user_id="user-fail-1",
        owner_username="failureuser",
        owner_user_code="failur",
        target="failurecustomer",
        staging_name="failurecustomer_550e8400e29b",  # First 12 chars of job_id
        dbhost="localhost",
        status=JobStatus.RUNNING,
        submitted_at=datetime.now(),
        options_json={},
        retry_count=0,
    )


def _base_specs(
    job: Job, tmp_path: Path
) -> tuple[StagingConnectionSpec, PostSQLConnectionSpec, Config, str]:
    staging_conn = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        timeout_seconds=5,
    )
    script_dir = tmp_path / "post_sql"
    script_dir.mkdir()
    post_sql_conn = PostSQLConnectionSpec(
        staging_db=job.staging_name,
        script_dir=script_dir,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        connect_timeout=5,
    )
    config = Config(mysql_host="localhost", mysql_user="root", mysql_password="pw")
    return staging_conn, post_sql_conn, config, str(tmp_path)


def test_workflow_myloader_failure(
    monkeypatch: pytest.MonkeyPatch, job_fixture: Job, tmp_path: Path
) -> None:
    job = job_fixture
    staging_conn, post_sql_conn, config, backup_dir = _base_specs(job, tmp_path)

    # Patch staging cleanup inside restore module
    from pulldb.worker import restore as restore_mod
    from pulldb.worker.staging import StagingResult

    def _fake_cleanup(conn: object, target: str, job_id: str) -> StagingResult:
        return StagingResult(
            staging_db=job.staging_name,
            target_db=job.target,
            orphans_dropped=[],
        )

    monkeypatch.setattr(restore_mod, "cleanup_orphaned_staging", _fake_cleanup)

    # Monkeypatch run_myloader to raise MyLoaderError
    def _raise_loader(
        spec: MyLoaderSpec, timeout: float | None = None
    ) -> MyLoaderResult:
        raise MyLoaderError(
            job_id=spec.job_id,
            command=["myloader"],
            exit_code=9,
            stdout="",
            stderr="simulated failure",
        )

    monkeypatch.setattr(restore_mod, "run_myloader", _raise_loader)

    # Prevent real metadata injection and atomic rename attempts
    def _fake_metadata(conn_spec: object, meta_spec: object) -> None:
        return None

    monkeypatch.setattr(restore_mod, "inject_metadata_table", _fake_metadata)

    def _fake_rename(conn_spec: object, rename_spec: object) -> None:
        return None

    monkeypatch.setattr(restore_mod, "atomic_rename_staging_to_target", _fake_rename)

    spec = build_restore_workflow_spec(
        config=config,
        job=job,
        backup_filename="dummy_backup.tar",
        backup_dir=backup_dir,
        staging_conn=staging_conn,
        post_sql_conn=post_sql_conn,
        timeout_override=1.0,
    )

    with pytest.raises(MyLoaderError):
        orchestrate_restore_workflow(spec)


def test_workflow_post_sql_failure(
    monkeypatch: pytest.MonkeyPatch, job_fixture: Job, tmp_path: Path
) -> None:
    job = job_fixture
    staging_conn, post_sql_conn, config, backup_dir = _base_specs(job, tmp_path)

    from pulldb.worker import restore as restore_mod
    from pulldb.worker.staging import StagingResult

    def _fake_cleanup(conn: object, target: str, job_id: str) -> StagingResult:
        return StagingResult(
            staging_db=job.staging_name,
            target_db=job.target,
            orphans_dropped=[],
        )

    monkeypatch.setattr(restore_mod, "cleanup_orphaned_staging", _fake_cleanup)

    # Fake successful myloader
    def _fake_loader(
        spec: MyLoaderSpec, timeout: float | None = None
    ) -> MyLoaderResult:
        now = datetime.now(UTC)
        return MyLoaderResult(
            command=["myloader"],
            exit_code=0,
            started_at=now,
            completed_at=now,
            duration_seconds=0.01,
            stdout="restore ok",
            stderr="",
        )

    monkeypatch.setattr(restore_mod, "run_myloader", _fake_loader)

    def _fail_post_sql(conn_spec: PostSQLConnectionSpec) -> None:
        raise PostSQLError(
            job_id=job.id,
            script_name="010.fail.sql",
            error_message="boom",
            completed_scripts=[],
        )

    # IMPORTANT: restore.py imports execute_post_sql symbol directly; must patch there
    monkeypatch.setattr(restore_mod, "execute_post_sql", _fail_post_sql)

    # Prevent real metadata injection and atomic rename attempts
    def _fake_metadata(conn_spec: object, meta_spec: object) -> None:
        return None

    monkeypatch.setattr(restore_mod, "inject_metadata_table", _fake_metadata)

    def _fake_rename(conn_spec: object, rename_spec: object) -> None:
        return None

    monkeypatch.setattr(restore_mod, "atomic_rename_staging_to_target", _fake_rename)

    spec = build_restore_workflow_spec(
        config=config,
        job=job,
        backup_filename="dummy_backup.tar",
        backup_dir=backup_dir,
        staging_conn=staging_conn,
        post_sql_conn=post_sql_conn,
        timeout_override=1.0,
    )

    with pytest.raises(PostSQLError):
        orchestrate_restore_workflow(spec)
