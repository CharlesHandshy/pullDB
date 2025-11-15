"""Unit tests for JobRepository active job queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from mysql.connector import errorcode
from mysql.connector.errors import ProgrammingError

from pulldb.domain.models import Job
from pulldb.infra.mysql import JobRepository, MySQLPool


class _FakeCursor:
    """Minimal cursor stub that tracks executed SQL."""

    def __init__(
        self,
        *,
        view_rows: list[dict[str, Any]],
        table_rows: list[dict[str, Any]],
        raise_view_error: bool = False,
    ) -> None:
        self.view_rows = view_rows
        self.table_rows = table_rows
        self.raise_view_error = raise_view_error
        self.executed: list[str] = []
        self._last_query: str | None = None
        self._view_error_raised = False

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        self._last_query = query
        self.executed.append(query)
        if (
            "FROM active_jobs" in query
            and self.raise_view_error
            and not self._view_error_raised
        ):
            self._view_error_raised = True
            raise ProgrammingError(
                msg="Table 'active_jobs' doesn't exist",
                errno=errorcode.ER_NO_SUCH_TABLE,
            )

    def fetchall(self) -> list[dict[str, Any]]:
        if self._last_query and "FROM active_jobs" in self._last_query:
            return self.view_rows
        return self.table_rows


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self, dictionary: bool = False) -> _FakeCursor:
        assert dictionary, "JobRepository should request dictionary rows"
        return self._cursor

    def close(self) -> None:
        return None


class _ConnectionContext:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._connection = _FakeConnection(cursor)

    def __enter__(self) -> _FakeConnection:
        return self._connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        self._connection.close()


class _FakePool:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def connection(self) -> _ConnectionContext:
        return _ConnectionContext(self._cursor)


def _row(job_id: str, *, status: str = "queued") -> dict[str, Any]:
    return {
        "id": job_id,
        "owner_user_id": "user-123",
        "owner_username": "jane",
        "owner_user_code": "janedo",
        "target": f"target-{job_id}",
        "status": status,
        "submitted_at": datetime(2025, 11, 3, 12, 0, 0),
        "started_at": None,
    }


def _build_repo(cursor: _FakeCursor) -> JobRepository:
    return JobRepository(cast(MySQLPool, _FakePool(cursor)))


def test_active_jobs_prefers_view_when_available() -> None:
    cursor = _FakeCursor(
        view_rows=[_row("job-view")],
        table_rows=[],
        raise_view_error=False,
    )
    repo = _build_repo(cursor)

    jobs: list[Job] = repo.get_active_jobs()

    assert [job.id for job in jobs] == ["job-view"]
    assert len(cursor.executed) == 1
    assert "FROM active_jobs" in cursor.executed[0]


def test_active_jobs_falls_back_when_view_missing() -> None:
    cursor = _FakeCursor(
        view_rows=[],
        table_rows=[_row("job-fallback")],
        raise_view_error=True,
    )
    repo = _build_repo(cursor)

    first_run = repo.get_active_jobs()
    assert [job.id for job in first_run] == ["job-fallback"]
    assert "FROM active_jobs" in cursor.executed[0]
    assert "FROM jobs" in cursor.executed[1]

    cursor.table_rows = [_row("job-second", status="running")]
    second_run = repo.get_active_jobs()
    assert [job.id for job in second_run] == ["job-second"]
    assert "active_jobs" not in cursor.executed[-1]
