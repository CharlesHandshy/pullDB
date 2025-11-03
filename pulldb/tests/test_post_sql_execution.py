"""Tests for post-SQL execution module.

We simulate MySQL connection and cursor to validate ordering, failure
propagation, and size limit enforcement without a real database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pulldb.domain.errors import PostSQLError
from pulldb.worker.post_sql import (
    MAX_SCRIPT_SIZE_BYTES,
    PostSQLConnectionSpec,
    execute_post_sql,
)


class FakeCursor:
    def __init__(self, fail_script: str | None = None) -> None:
        self.fail_script = fail_script
        self.executed: list[str] = []
        self.rowcount = 1

    def execute(self, sql: str) -> None:
        # Use a marker inserted by test harness to decide failure
        marker = sql.strip().split("\n", 1)[0]
        if self.fail_script and self.fail_script in marker:
            raise Exception("Script failure simulated")
        self.executed.append(marker)

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class FakeConnection:
    def __init__(self, fail_script: str | None = None) -> None:
        self.cursor_obj = FakeCursor(fail_script)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


def _spec(tmp_path: Path) -> PostSQLConnectionSpec:
    return PostSQLConnectionSpec(
        staging_db="staging_db",
        script_dir=tmp_path,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
    )


def _write_script(dir_path: Path, name: str, content: str) -> None:
    (dir_path / name).write_text(content, encoding="utf-8")


def test_post_sql_no_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pulldb.worker.post_sql as mod

    def fake_connect(**_kw: Any) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    result = execute_post_sql(_spec(tmp_path))
    assert result.scripts_executed == []
    assert result.total_duration_seconds == 0.0


def test_post_sql_success_ordering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pulldb.worker.post_sql as mod

    _write_script(tmp_path, "010.first.sql", "-- 010.first\nSELECT 1;")
    _write_script(tmp_path, "020.second.sql", "-- 020.second\nSELECT 2;")
    _write_script(tmp_path, "015.middle.sql", "-- 015.middle\nSELECT 3;")

    def fake_connect(**_kw: Any) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    result = execute_post_sql(_spec(tmp_path))
    names = [r.script_name for r in result.scripts_executed]
    assert names == ["010.first.sql", "015.middle.sql", "020.second.sql"]
    assert all(r.duration_seconds >= 0 for r in result.scripts_executed)


def test_post_sql_failure_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pulldb.worker.post_sql as mod

    _write_script(tmp_path, "010.first.sql", "-- 010.first\nSELECT 1;")
    _write_script(tmp_path, "020.bad.sql", "-- 020.bad\nSELECT BROKEN;")
    _write_script(tmp_path, "030.after.sql", "-- 030.after\nSELECT 3;")

    def fake_connect(**_kw: Any) -> FakeConnection:
        # Fail on 020.bad marker
        return FakeConnection(fail_script="020.bad")

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    with pytest.raises(PostSQLError) as exc:
        execute_post_sql(_spec(tmp_path))

    detail = exc.value.detail
    assert detail["script_name"].startswith("020.bad")
    assert "010.first.sql" in detail["completed_scripts"]
    assert "030.after.sql" not in detail["completed_scripts"]


def test_post_sql_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pulldb.worker.post_sql as mod

    big_content = "X" * (MAX_SCRIPT_SIZE_BYTES + 1)
    _write_script(tmp_path, "010.too_big.sql", big_content)

    def fake_connect(**_kw: Any) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    with pytest.raises(ValueError) as exc:
        execute_post_sql(_spec(tmp_path))

    assert "exceeds max size" in str(exc.value)
