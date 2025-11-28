"""Tests for atomic rename invocation logic.

We cannot execute the real stored procedure in unit tests (depends on
MySQL instance state). Instead we simulate cursor behavior to verify:
  * Procedure existence check failure raises AtomicRenameError
  * Successful path attempts to call cursor.callproc with correct args

The actual SQL procedure is documented in docs/atomic_rename_procedure.sql.
"""

from __future__ import annotations

from typing import Any

import pytest

from pulldb.domain.errors import AtomicRenameError
from pulldb.worker.atomic_rename import (
    RENAME_PROCEDURE_NAME,
    AtomicRenameConnectionSpec,
    AtomicRenameSpec,
    atomic_rename_staging_to_target,
)


class FakeCursor:
    def __init__(self, procedures: set[str]) -> None:
        self.procedures = procedures
        self.callproc_args: tuple[str, tuple[str, str]] | None = None
        self._stored_results_consumed = False

    def execute(self, sql: str) -> None:  # pragma: no cover - trivial branch
        # Minimal implementation: detect procedure existence query
        if "FROM information_schema.ROUTINES" in sql:
            # Simulate schema result
            self._result = (
                ("pulldb",) if RENAME_PROCEDURE_NAME in self.procedures else None
            )
        else:
            self._result = None

    def fetchone(self) -> tuple[str] | None:
        return self._result

    def callproc(self, name: str, args: tuple[str, str]) -> None:
        # Handle schema-qualified name
        simple_name = name.split(".")[-1]
        if simple_name not in self.procedures:
            raise ValueError(f"Procedure {name} missing")
        self.callproc_args = (name, args)

    def stored_results(self) -> list[Any]:  # pragma: no cover - simple iterator
        self._stored_results_consumed = True
        return []

    def close(self) -> None:  # pragma: no cover - no resources
        pass


class FakeConnection:
    def __init__(self, procedures: set[str]) -> None:
        self.cursor_obj = FakeCursor(procedures)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


def _conn_spec() -> AtomicRenameConnectionSpec:
    return AtomicRenameConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        timeout_seconds=5,
    )


def test_atomic_rename_missing_procedure(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = AtomicRenameSpec(
        job_id="job-123",
        staging_db="staging_db_abc123def456",
        target_db="target_db",
    )

    def fake_connect(**_kw: Any) -> FakeConnection:
        return FakeConnection(set())  # no procedures present

    import pulldb.worker.atomic_rename as mod

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    with pytest.raises(AtomicRenameError) as exc:
        atomic_rename_staging_to_target(_conn_spec(), spec)

    assert "Stored procedure" in str(exc.value)
    assert exc.value.detail["staging_name"] == spec.staging_db


def test_atomic_rename_success(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = AtomicRenameSpec(
        job_id="job-456",
        staging_db="staging_db_deadbeefcafe",
        target_db="target_db",
    )

    fake_conn = FakeConnection({RENAME_PROCEDURE_NAME})

    def fake_connect(**_kw: Any) -> FakeConnection:
        return fake_conn

    import pulldb.worker.atomic_rename as mod

    monkeypatch.setattr(mod.mysql.connector, "connect", fake_connect)

    atomic_rename_staging_to_target(_conn_spec(), spec)

    assert fake_conn.cursor_obj.callproc_args == (
        f"pulldb.{RENAME_PROCEDURE_NAME}",
        (spec.staging_db, spec.target_db),
    )
