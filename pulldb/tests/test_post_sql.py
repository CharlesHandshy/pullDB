"""Tests for post_sql.execute_post_sql logic.

Uses a temporary directory with simple SQL scripts. We simulate MySQL by
monkeypatching mysql.connector.connect to return a lightweight fake
connection + cursor object implementing the subset we use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from pulldb.domain.errors import PostSQLError
from pulldb.worker.post_sql import (
    PostSQLConnectionSpec,
    execute_post_sql,
)


@dataclass
class _FakeCursor:
    scripts: list[str]
    fail_on: str | None = None
    rowcount: int | None = 0

    def execute(self, sql: str) -> None:
        self.scripts.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise ValueError("boom failure")
        # simulate rowcount for UPDATE/DELETE statements
        if sql.lower().startswith("update"):
            self.rowcount = 3
        elif sql.lower().startswith("delete"):
            self.rowcount = 2
        else:
            self.rowcount = 0


@dataclass
class _FakeConnection:
    cursor_obj: _FakeCursor
    closed: bool = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


def _write_script(dir_path: Path, name: str, content: str) -> None:
    (dir_path / name).write_text(content, encoding="utf-8")


def test_execute_post_sql_no_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = PostSQLConnectionSpec(
        staging_db="staging_db",
        script_dir=tmp_path,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="user",
        mysql_password="pw",
    )

    import mysql.connector

    def _connect_factory(**_k: object) -> _FakeConnection:
        return _FakeConnection(_FakeCursor([]))

    monkeypatch.setattr(mysql.connector, "connect", _connect_factory)

    result = execute_post_sql(spec)
    assert result.staging_db == "staging_db"
    assert result.scripts_executed == []
    assert result.total_duration_seconds == 0.0


def test_execute_post_sql_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_script(tmp_path, "010.create_table.sql", "CREATE TABLE t(id INT);")
    _write_script(tmp_path, "020.update_rows.sql", "UPDATE t SET id = id;")
    _write_script(tmp_path, "030.delete_rows.sql", "DELETE FROM t WHERE id=1;")

    spec = PostSQLConnectionSpec(
        staging_db="staging_db",
        script_dir=tmp_path,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="user",
        mysql_password="pw",
    )

    import mysql.connector

    fc = _FakeCursor([])

    def _connect_factory2(**_k: object) -> _FakeConnection:
        return _FakeConnection(fc)

    monkeypatch.setattr(mysql.connector, "connect", _connect_factory2)

    result = execute_post_sql(spec)
    names = [r.script_name for r in result.scripts_executed]
    assert names == [
        "010.create_table.sql",
        "020.update_rows.sql",
        "030.delete_rows.sql",
    ]
    # Validate rowcount capture for update/delete (non-negative only)
    updated_rows = 3
    deleted_rows = 2
    rc_map = {r.script_name: r.rows_affected for r in result.scripts_executed}
    assert rc_map["020.update_rows.sql"] == updated_rows
    assert rc_map["030.delete_rows.sql"] == deleted_rows


def test_execute_post_sql_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_script(tmp_path, "010.first.sql", "CREATE TABLE a(id INT);")
    _write_script(tmp_path, "020.bad.sql", "SELECT * FROM missing_table;")
    _write_script(tmp_path, "030.never.sql", "UPDATE a SET id=id;")

    spec = PostSQLConnectionSpec(
        staging_db="staging_db",
        script_dir=tmp_path,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="user",
        mysql_password="pw",
    )

    import mysql.connector

    failing_cursor = _FakeCursor([], fail_on="missing_table")

    def _connect_factory3(**_k: object) -> _FakeConnection:
        return _FakeConnection(failing_cursor)

    monkeypatch.setattr(mysql.connector, "connect", _connect_factory3)

    with pytest.raises(PostSQLError) as exc:
        execute_post_sql(spec)

    # Ensure completed scripts recorded and failing script surfaced
    assert "020.bad.sql" in str(exc.value)
    assert exc.value.detail["completed_scripts"] == ["010.first.sql"]
