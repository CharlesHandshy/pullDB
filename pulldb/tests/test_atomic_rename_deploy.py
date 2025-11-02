"""Tests for `scripts/deploy_atomic_rename.py` deployment behaviors.

We exercise dry-run, host selection validation, missing SQL file, connection
failure, drop failure, creation failure, and success path. To avoid real MySQL
access these tests monkeypatch `mysql.connector.connect` with lightweight fake
objects whose cursor.execute method simulates failures based on injected
flags.

FAIL HARD expectations: each failure scenario must surface a structured
diagnostic (Goal/Problem/Root Cause/Solutions) and exit with code 1. We capture
stderr to assert presence of those fields.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import scripts.deploy_atomic_rename as deploy


class _FakeCursor:
    """Fake cursor configurable with failure points.

    Attributes:
        fail_drop: When True, DROP PROCEDURE invocation fails.
        fail_create: When True, CREATE PROCEDURE statement fails.
        statements: Collected executed statements for later assertions.
    """

    def __init__(self, fail_drop: bool = False, fail_create: bool = False) -> None:
        self.fail_drop = fail_drop
        self.fail_create = fail_create
        self.closed = False
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:  # pragma: no cover - trivial logic
        if "DROP PROCEDURE" in statement and self.fail_drop:
            raise deploy.mysql.connector.Error("simulated drop failure")
        if "CREATE" in statement and "PROCEDURE" in statement and self.fail_create:
            raise deploy.mysql.connector.Error("simulated create failure")
        self.statements.append(statement)

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


class _FakeConnection:
    """Fake MySQL connection returning configured cursor.

    Accepts callable to build the cursor allowing per-test failure injection.
    """

    def __init__(self, cursor_factory: Callable[[], _FakeCursor]) -> None:
        self._cursor_factory = cursor_factory
        self.closed = False
        self.cursors_created = 0

    def cursor(self) -> _FakeCursor:  # pragma: no cover - trivial
        self.cursors_created += 1
        return self._cursor_factory()

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


def _run_script(argv: list[str]) -> tuple[int, str, str]:
    """Helper to run main() with patched argv, capturing stdout/stderr.

    Returns:
        (exit_code, stdout, stderr)
    """
    orig_argv = sys.argv
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    try:
        sys.argv = ["deploy_atomic_rename.py", *argv]
        from io import StringIO

        buf_out = StringIO()
        buf_err = StringIO()
        sys.stdout = buf_out
        sys.stderr = buf_err
        try:
            code = deploy.main()
        except SystemExit as e:
            # e.code may be None or non-int; normalize to int (default 0)
            code = int(e.code) if isinstance(e.code, (int, str)) else 0
        return code, buf_out.getvalue(), buf_err.getvalue()
    finally:  # pragma: no cover - cleanup
        sys.argv = orig_argv
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr


@pytest.fixture()
def sql_file(tmp_path: Path) -> Path:
    path = tmp_path / "procedure.sql"
    path.write_text(
        (
            "DROP PROCEDURE IF EXISTS pulldb_atomic_rename; "
            "CREATE PROCEDURE pulldb_atomic_rename() BEGIN SELECT 1; END;"
        ),
        encoding="utf-8",
    )
    return path


def test_dry_run_single_host(sql_file: Path) -> None:
    code, out, err = _run_script(
        [
            "--sql-file",
            str(sql_file),
            "--host",
            "db1.example.com",
            "--user",
            "root",
            "--password",
            "pw",
            "--dry-run",
        ]
    )
    assert code == 0
    assert "DRY RUN" in out
    assert err == ""


def test_host_conflict_validation(sql_file: Path) -> None:
    code, out, err = _run_script(
        [
            "--sql-file",
            str(sql_file),
            "--host",
            "db1.example.com",
            "--hosts",
            "db2.example.com",
            "--user",
            "root",
            "--password",
            "pw",
        ]
    )
    assert code == 1
    assert "Goal:" in err and "Problem:" in err and "Root Cause:" in err
    assert "either --host or --hosts" in err
    assert out == ""


def test_missing_sql_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.sql"
    code, out, err = _run_script(
        [
            "--sql-file",
            str(missing),
            "--host",
            "db1.example.com",
            "--user",
            "root",
            "--password",
            "pw",
        ]
    )
    assert code == 1
    assert "SQL file" in err and "not found" in err
    assert out == ""


def test_connection_failure(sql_file: Path, monkeypatch: Any) -> None:
    def fake_connect(**_: Any) -> Any:
        raise deploy.mysql.connector.Error("simulated connect error")

    monkeypatch.setattr(deploy.mysql.connector, "connect", fake_connect)
    code, out, err = _run_script(
        [
            "--sql-file",
            str(sql_file),
            "--host",
            "db1.example.com",
            "--user",
            "root",
            "--password",
            "pw",
        ]
    )
    assert code == 1
    assert "Connection failed" in err
    assert "simulated connect error" in err
    # Progress line emitted before failure diagnostics
    assert "Deploying pulldb_atomic_rename to db1.example.com:3306" in out


def test_drop_failure(sql_file: Path, monkeypatch: Any) -> None:
    def fake_connect(**_: Any) -> _FakeConnection:
        return _FakeConnection(lambda: _FakeCursor(fail_drop=True))

    monkeypatch.setattr(deploy.mysql.connector, "connect", fake_connect)
    code, out, err = _run_script(
        [
            "--sql-file",
            str(sql_file),
            "--host",
            "db1.example.com",
            "--user",
            "root",
            "--password",
            "pw",
        ]
    )
    assert code == 1
    assert "DROP PROCEDURE failed" in err
    assert "Deploying pulldb_atomic_rename to db1.example.com:3306" in out


def test_create_failure(sql_file: Path, monkeypatch: Any) -> None:
    def fake_connect(**_: Any) -> _FakeConnection:
        return _FakeConnection(lambda: _FakeCursor(fail_create=True))

    monkeypatch.setattr(deploy.mysql.connector, "connect", fake_connect)
    code, out, err = _run_script(
        [
            "--sql-file",
            str(sql_file),
            "--host",
            "db1.example.com",
            "--user",
            "root",
            "--password",
            "pw",
        ]
    )
    assert code == 1
    assert "Procedure creation failed" in err
    assert "Deploying pulldb_atomic_rename to db1.example.com:3306" in out


def test_success_single_host(sql_file: Path, monkeypatch: Any) -> None:
    cursor_instance = _FakeCursor()

    def fake_connect(**_: Any) -> _FakeConnection:
        # Return same cursor so we can assert executed statements later if needed
        return _FakeConnection(lambda: cursor_instance)

    monkeypatch.setattr(deploy.mysql.connector, "connect", fake_connect)
    code, out, err = _run_script(
        [
            "--sql-file",
            str(sql_file),
            "--host",
            "db1.example.com",
            "--user",
            "root",
            "--password",
            "pw",
        ]
    )
    assert code == 0
    assert "Deployment complete" in out
    assert err == ""
    assert any("DROP PROCEDURE IF EXISTS" in s for s in cursor_instance.statements)
