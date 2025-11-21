"""Tests for worker.restore.run_myloader wrapper.

These tests simulate myloader using the Python interpreter to avoid
external binary dependency. This exercises command construction,
non-zero exit translation, and timeout handling.
"""

from __future__ import annotations

# ruff: noqa: I001
from datetime import datetime
import sys
from typing import Any

import pytest

from pulldb.domain.config import Config
from pulldb.domain.errors import MyLoaderError
from pulldb.domain.models import Job, JobStatus
from pulldb.domain.restore_models import MyLoaderSpec
from pulldb.worker import restore as restore_module
from pulldb.worker.post_sql import PostSQLConnectionSpec
from pulldb.worker.restore import build_restore_workflow_spec, run_myloader
from pulldb.worker.staging import StagingConnectionSpec

PY = sys.executable
MYLOADER_ERROR_EXIT = 7


def _spec(tmp_path: Any) -> MyLoaderSpec:
    return MyLoaderSpec(
        job_id="job-123",
        staging_db="stg_db",
        backup_dir=str(tmp_path),
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        extra_args=(),
    )


def _job_model() -> Job:
    return Job(
        id="123e4567e89b12d3a456426614174000",
        owner_user_id="user-1",
        owner_username="workeruser",
        owner_user_code="worker",
        target="workerdb",
        staging_name="workerdb_123e4567e89b",
        dbhost="localhost",
        status=JobStatus.RUNNING,
        submitted_at=datetime.now(),
        options_json={},
        retry_count=0,
    )


def test_run_myloader_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    spec = _spec(tmp_path)

    from datetime import UTC, datetime

    class FakeResult:
        def __init__(self) -> None:
            self.command = ["myloader", "--database=stg_db"]
            self.exit_code = 0
            self.started_at = datetime.now(UTC)
            self.completed_at = self.started_at
            self.duration_seconds = 0.0
            self.stdout = "restore ok"
            self.stderr = ""

    def fake_run_command(*_a: Any, **_k: Any) -> FakeResult:
        return FakeResult()

    monkeypatch.setattr(restore_module, "run_command", fake_run_command)

    result = run_myloader(spec)
    assert result.exit_code == 0
    assert "restore ok" in result.stdout


def test_run_myloader_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Ensure non-zero exit from underlying command raises MyLoaderError.

    We monkeypatch worker.restore.run_command to simulate a finished process
    with exit_code 7 so we exercise error translation logic without invoking
    a real myloader binary.
    """

    spec = _spec(tmp_path)

    from datetime import UTC, datetime
    from pulldb.worker import restore as restore_mod

    class FakeResult:
        def __init__(self) -> None:
            self.command = ["myloader", "--host", spec.mysql_host]
            self.exit_code = MYLOADER_ERROR_EXIT
            self.started_at = self.completed_at = datetime.now(UTC)
            self.duration_seconds = 0.0
            self.stdout = "ok"
            self.stderr = "boom"

    def fake_run_command(
        *_a: Any, **_k: Any
    ) -> FakeResult:  # pragma: no cover - trivial
        return FakeResult()

    monkeypatch.setattr(restore_mod, "run_command", fake_run_command)

    with pytest.raises(MyLoaderError) as exc:
        run_myloader(spec)

    detail = exc.value.detail
    assert detail.get("exit_code") == MYLOADER_ERROR_EXIT
    assert detail.get("stderr", "").endswith("boom")


def test_run_myloader_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    spec = _spec(tmp_path)

    from pulldb.infra import exec as exec_mod
    from pulldb.worker import restore as restore_mod

    def fake_run_command(*_a: Any, **_k: Any) -> None:  # raise timeout every call
        raise exec_mod.CommandTimeoutError(
            ["myloader"], 0.1, "partial out", "partial err"
        )

    monkeypatch.setattr(restore_mod, "run_command", fake_run_command)

    with pytest.raises(MyLoaderError) as exc:
        run_myloader(spec, timeout=0.05)

    # Either message contains 'timed out' or exit_code sentinel present
    msg = str(exc.value).lower()
    assert "timed" in msg or exc.value.detail.get("exit_code") in {-1, 0}


def test_build_restore_workflow_spec_uses_config(tmp_path: Any) -> None:
    job = _job_model()
    staging_conn = StagingConnectionSpec(
        mysql_host="mysql-host",
        mysql_port=3307,
        mysql_user="worker",
        mysql_password="secret",
        timeout_seconds=5,
    )
    script_dir = tmp_path / "post_sql"
    script_dir.mkdir()
    post_sql_conn = PostSQLConnectionSpec(
        staging_db=job.staging_name,
        script_dir=script_dir,
        mysql_host="mysql-host",
        mysql_port=3307,
        mysql_user="worker",
        mysql_password="secret",
        connect_timeout=5,
    )
    config = Config(
        mysql_host="cfg-host",
        mysql_user="cfg-user",
        mysql_password="cfg-pass",
        myloader_binary="/opt/myloader",
        myloader_extra_args=("--skip-triggers",),
        myloader_timeout_seconds=1337.0,
        myloader_threads=6,
    )

    spec = build_restore_workflow_spec(
        config=config,
        job=job,
        backup_filename="backup.tar",
        backup_dir=str(tmp_path),
        staging_conn=staging_conn,
        post_sql_conn=post_sql_conn,
        extra_myloader_args=["--rows-per-insert=500"],
    )

    assert spec.timeout == pytest.approx(1337.0)
    assert spec.myloader_spec.binary_path == "/opt/myloader"
    assert spec.myloader_spec.extra_args == (
        "--skip-triggers",
        "--rows-per-insert=500",
        "--threads=6",
    )


def test_build_restore_workflow_spec_allows_timeout_override(tmp_path: Any) -> None:
    job = _job_model()
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
    config = Config(mysql_host="cfg", mysql_user="user", mysql_password="pw")

    spec = build_restore_workflow_spec(
        config=config,
        job=job,
        backup_filename="backup.tar",
        backup_dir=str(tmp_path),
        staging_conn=staging_conn,
        post_sql_conn=post_sql_conn,
        timeout_override=42.0,
    )

    assert spec.timeout == 42.0
