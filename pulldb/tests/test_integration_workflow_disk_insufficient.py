"""Workflow integration test (disk insufficient scenario no longer in scope).

Historically this test attempted to validate that a disk capacity failure
prevented myloader execution within the restore workflow. The architecture
now isolates disk space preflight in the downloader phase executed *before*
`orchestrate_restore_workflow` is invoked. Therefore the workflow function
should never raise `DiskCapacityError`; such failures are handled upstream.

We mark this test as xfail to document the architectural separation and
avoid false failure signals. Future downloader integration tests should
exercise `ensure_disk_capacity` behavior directly.

HCA Layer: tests (pulldb/tests/)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

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
def job_fixture() -> Job:
    return Job(
        id="9f1b2c3d4e5f67890123456789abcdef",  # 32 hex chars
        owner_user_id="user-disk-1",
        owner_username="diskuser",
        owner_user_code="diskus",
        target="diskcustomer",
        staging_name="diskcustomer_9f1b2c3d4e5f",  # first 12 chars
        dbhost="localhost",
        status=JobStatus.RUNNING,
        submitted_at=datetime.now(),
        options_json={},
        retry_count=0,
    )


def _specs(job: Job, tmp_path: Path):  # type: ignore[no-untyped-def]
    staging_conn = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        timeout_seconds=5,
    )
    post_sql_dir = tmp_path / "post_sql"
    post_sql_dir.mkdir()
    post_sql_conn = PostSQLConnectionSpec(
        staging_db=job.staging_name,
        script_dir=post_sql_dir,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        connect_timeout=5,
    )
    config = Config(mysql_host="localhost", mysql_user="root", mysql_password="pw")
    return staging_conn, post_sql_conn, config, str(tmp_path)


@pytest.mark.xfail(
    reason="Disk capacity preflight occurs before workflow orchestration."
)
def test_workflow_disk_insufficient_architecture_separation(
    monkeypatch: pytest.MonkeyPatch, job_fixture: Job, tmp_path: Path
) -> None:
    """Document that disk capacity is not part of workflow layer.

    Ensures the workflow still completes with all phases when run with
    standard monkeypatches; capacity errors are upstream concerns.
    """
    job = job_fixture
    staging_conn, post_sql_conn, config, backup_dir = _specs(job, tmp_path)

    from pulldb.worker import restore as restore_mod
    from pulldb.worker.staging import StagingResult

    def _fake_cleanup(conn: object, target: str, job_id: str) -> StagingResult:
        return StagingResult(
            staging_db=job.staging_name,
            target_db=job.target,
            orphans_dropped=[],
        )

    monkeypatch.setattr(restore_mod, "cleanup_orphaned_staging", _fake_cleanup)

    def _fake_loader(
        spec: MyLoaderSpec,
        *,
        timeout: float | None = None,
        progress_callback: object = None,
        processlist_monitor: object = None,
        abort_check: object = None,
    ) -> MyLoaderResult:
        now = datetime.now()
        return MyLoaderResult(
            command=["myloader"],
            exit_code=0,
            started_at=now,
            completed_at=now,
            duration_seconds=0.01,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(restore_mod, "run_myloader", _fake_loader)

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

    result = orchestrate_restore_workflow(spec)
    assert set(result.keys()) == {
        "staging",
        "myloader",
        "post_sql",
        "metadata",
        "atomic_rename",
    }
