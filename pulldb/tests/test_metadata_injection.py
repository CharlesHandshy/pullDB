"""Tests for metadata table injection logic.

We simulate MySQL connection/cursor behavior to avoid real database.
Focus: error translation paths and successful insert flow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import mysql.connector
import pytest

from pulldb.domain.errors import MetadataInjectionError
from pulldb.worker.metadata import (
    MetadataConnectionSpec,
    MetadataSpec,
    inject_metadata_table,
)


class FakeCursor:
    def __init__(self, fail_op: str | None = None) -> None:
        self.queries: list[str] = []
        self.params: list[tuple[Any, ...]] = []
        self.fail_op = fail_op

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.queries.append(sql.strip())
        if params:
            self.params.append(params)
        if self.fail_op == "create_table" and sql.lstrip().upper().startswith(
            "CREATE TABLE"
        ):
            raise mysql.connector.Error("CREATE TABLE failure")
        if self.fail_op == "insert" and sql.lstrip().upper().startswith("INSERT INTO"):
            raise mysql.connector.Error("INSERT failure")

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class FakeConnection:
    def __init__(self, fail_op: str | None = None) -> None:
        self.fail_op = fail_op
        self.closed = False
        self.cursor_obj = FakeCursor(fail_op)

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


def _conn_spec() -> MetadataConnectionSpec:
    return MetadataConnectionSpec(
        staging_db="staging_db_deadbeefcafe",
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        timeout_seconds=5,
    )


def _metadata_spec() -> MetadataSpec:
    now = datetime.now(UTC)
    return MetadataSpec(
        job_id="job-xyz",
        owner_username="tester",
        target_db="target_db",
        backup_filename="daily_mydumper_target_2025-11-02T00-00-00Z_Mon_dbimp.tar",
        restore_started_at=now,
        restore_completed_at=now,
        post_sql_result=None,
    )


def test_metadata_injection_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import pulldb.worker.metadata as mod

    conn_instance = FakeConnection()

    def fake_connect(**_kw: Any) -> FakeConnection:
        return conn_instance

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    inject_metadata_table(_conn_spec(), _metadata_spec())

    cursor = conn_instance.cursor_obj
    # Ensure CREATE TABLE and INSERT executed
    create_found = any(q.upper().startswith("CREATE TABLE") for q in cursor.queries)
    insert_found = any(q.upper().startswith("INSERT INTO") for q in cursor.queries)
    assert create_found
    assert insert_found


def test_metadata_injection_create_table_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pulldb.worker.metadata as mod

    def fake_connect(**_kw: Any) -> FakeConnection:
        return FakeConnection(fail_op="create_table")

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    with pytest.raises(MetadataInjectionError) as exc:
        inject_metadata_table(_conn_spec(), _metadata_spec())

    assert exc.value.detail["operation"] == "create_table"


def test_metadata_injection_insert_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pulldb.worker.metadata as mod

    def fake_connect(**_kw: Any) -> FakeConnection:
        return FakeConnection(fail_op="insert")

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    with pytest.raises(MetadataInjectionError) as exc:
        inject_metadata_table(_conn_spec(), _metadata_spec())

    assert exc.value.detail["operation"] == "insert"
