"""Tests for worker.restore.run_myloader wrapper.

These tests simulate myloader using the Python interpreter to avoid
external binary dependency. This exercises command construction,
non-zero exit translation, and timeout handling.
"""

from __future__ import annotations

# ruff: noqa: I001
import sys
from typing import Any

import pytest

from pulldb.domain.errors import MyLoaderError
from pulldb.domain.restore_models import MyLoaderSpec
from pulldb.worker import restore as restore_module
from pulldb.worker.restore import run_myloader

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
