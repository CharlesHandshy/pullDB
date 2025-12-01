"""
Admin CLI Test Fixtures for pullDB QA Testing

Provides fixtures for:
- Click CLI testing via CliRunner
- MySQL mocking (admin CLI uses direct MySQL, not API)
- Sample data for jobs, hosts, users, settings
- Connection pool mocks

Usage:
    pytest tests/qa/admin/ -v
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pulldb.cli.admin import cli  # noqa: F401 - Used in test files


# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"
SAMPLE_JOB_PREFIX = "75777a4c"
SAMPLE_USER_CODE = "charle"
SAMPLE_USERNAME = "charleshandshy"
SAMPLE_TARGET = "charleqatemplate"
SAMPLE_DBHOST = "mysql-stg-01.example.com"
SAMPLE_STAGING_NAME = "charleqatemplate_75777a4c3dd9"


# ---------------------------------------------------------------------------
# CLI Runner Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def isolated_runner() -> CliRunner:
    """Click CLI test runner with isolated filesystem."""
    return CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# Mock MySQL Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mysql_pool() -> Generator[MagicMock, None, None]:
    """Mock the MySQL pool for admin commands."""
    with patch("pulldb.cli.admin_commands._get_mysql_pool") as mock_pool:
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        
        # Set up context manager chain
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_pool.return_value = pool
        
        # Attach cursor for test access
        pool._mock_cursor = cursor
        pool._mock_conn = conn
        
        yield pool


@pytest.fixture
def mock_settings_mysql_pool() -> Generator[MagicMock, None, None]:
    """Mock the MySQL pool for settings commands."""
    with patch("pulldb.cli.settings._get_mysql_pool") as mock_pool:
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        
        # Set up context manager chain
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_pool.return_value = pool
        pool._mock_cursor = cursor
        pool._mock_conn = conn
        
        yield pool


@pytest.fixture
def mock_settings_repo() -> Generator[MagicMock, None, None]:
    """Mock the SettingsRepository for settings commands."""
    with patch("pulldb.cli.settings._get_settings_repo") as mock_repo:
        repo = MagicMock()
        repo.get_all_settings.return_value = {}
        mock_repo.return_value = repo
        yield repo


# ---------------------------------------------------------------------------
# Sample Data Fixtures - Jobs
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_job_row() -> tuple:
    """Sample job database row."""
    return (
        SAMPLE_JOB_ID,                    # id
        "complete",                        # status
        SAMPLE_TARGET,                     # target
        SAMPLE_DBHOST,                     # dbhost
        SAMPLE_USERNAME,                   # username
        SAMPLE_USER_CODE,                  # user_code
        datetime(2025, 11, 29, 2, 8, 40),  # submitted_at
        datetime(2025, 11, 29, 2, 9, 9),   # started_at
        datetime(2025, 11, 29, 2, 10, 2),  # finished_at
        "complete",                        # current_operation
    )


@pytest.fixture
def sample_job_columns() -> list[str]:
    """Column names for job queries."""
    return [
        "id", "status", "target", "dbhost", "username", 
        "user_code", "submitted_at", "started_at", "finished_at",
        "current_operation"
    ]


@pytest.fixture
def job_row_factory() -> Callable[..., tuple]:
    """Factory for creating job database rows."""
    def _create(
        job_id: str = SAMPLE_JOB_ID,
        status: str = "complete",
        target: str = SAMPLE_TARGET,
        dbhost: str = SAMPLE_DBHOST,
        username: str = SAMPLE_USERNAME,
        user_code: str = SAMPLE_USER_CODE,
        submitted_at: datetime | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        current_operation: str | None = None,
    ) -> tuple:
        if submitted_at is None:
            submitted_at = datetime(2025, 11, 29, 2, 8, 40)
        if started_at is None:
            started_at = datetime(2025, 11, 29, 2, 9, 9)
        if finished_at is None and status in ("complete", "failed"):
            finished_at = datetime(2025, 11, 29, 2, 10, 2)
        return (
            job_id, status, target, dbhost, username, user_code,
            submitted_at, started_at, finished_at, current_operation
        )
    return _create


# ---------------------------------------------------------------------------
# Sample Data Fixtures - Hosts
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_host_row() -> tuple:
    """Sample database host row."""
    return (
        SAMPLE_DBHOST,                     # hostname
        2,                                 # max_concurrent_jobs
        True,                              # enabled
        "aws-secretsmanager:/pulldb/mysql/stg-01",  # credential_reference
        datetime(2025, 1, 15, 10, 0, 0),   # created_at
    )


@pytest.fixture
def sample_host_columns() -> list[str]:
    """Column names for host queries."""
    return ["hostname", "max_concurrent_jobs", "enabled", "credential_reference", "created_at"]


@pytest.fixture
def host_row_factory() -> Callable[..., tuple]:
    """Factory for creating host database rows."""
    def _create(
        hostname: str = SAMPLE_DBHOST,
        max_concurrent: int = 2,
        enabled: bool = True,
        credential_ref: str | None = None,
        created_at: datetime | None = None,
    ) -> tuple:
        if credential_ref is None:
            credential_ref = f"aws-secretsmanager:/pulldb/mysql/{hostname.split('.')[0]}"
        if created_at is None:
            created_at = datetime(2025, 1, 15, 10, 0, 0)
        return (hostname, max_concurrent, enabled, credential_ref, created_at)
    return _create


# ---------------------------------------------------------------------------
# Sample Data Fixtures - Users
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_user_row() -> tuple:
    """Sample user database row."""
    return (
        1,                                 # id
        SAMPLE_USERNAME,                   # username
        SAMPLE_USER_CODE,                  # user_code
        False,                             # is_admin
        False,                             # disabled
        datetime(2025, 1, 15, 10, 0, 0),   # created_at
        2,                                 # active_jobs
    )


@pytest.fixture
def sample_user_columns() -> list[str]:
    """Column names for user list queries."""
    return ["id", "username", "user_code", "is_admin", "disabled", "created_at", "active_jobs"]


@pytest.fixture
def user_row_factory() -> Callable[..., tuple]:
    """Factory for creating user database rows."""
    def _create(
        user_id: int = 1,
        username: str = SAMPLE_USERNAME,
        user_code: str = SAMPLE_USER_CODE,
        is_admin: bool = False,
        disabled: bool = False,
        created_at: datetime | None = None,
        active_jobs: int = 0,
    ) -> tuple:
        if created_at is None:
            created_at = datetime(2025, 1, 15, 10, 0, 0)
        return (user_id, username, user_code, is_admin, disabled, created_at, active_jobs)
    return _create


@pytest.fixture
def sample_user_detail_columns() -> list[str]:
    """Column names for user detail queries."""
    return [
        "id", "username", "user_code", "is_admin", "disabled", 
        "created_at", "total_jobs", "complete_jobs", "failed_jobs", "active_jobs"
    ]


@pytest.fixture
def user_detail_row_factory() -> Callable[..., tuple]:
    """Factory for creating user detail database rows."""
    def _create(
        user_id: int = 1,
        username: str = SAMPLE_USERNAME,
        user_code: str = SAMPLE_USER_CODE,
        is_admin: bool = False,
        disabled: bool = False,
        created_at: datetime | None = None,
        total_jobs: int = 10,
        complete_jobs: int = 8,
        failed_jobs: int = 1,
        active_jobs: int = 1,
    ) -> tuple:
        if created_at is None:
            created_at = datetime(2025, 1, 15, 10, 0, 0)
        return (
            user_id, username, user_code, is_admin, disabled, created_at,
            total_jobs, complete_jobs, failed_jobs, active_jobs
        )
    return _create


# ---------------------------------------------------------------------------
# Sample Data Fixtures - Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_orphan_columns() -> list[str]:
    """Column names for orphan cleanup queries."""
    return ["id", "staging_name", "dbhost", "status", "finished_at"]


@pytest.fixture
def orphan_row_factory() -> Callable[..., tuple]:
    """Factory for creating orphan database rows."""
    def _create(
        job_id: str = SAMPLE_JOB_ID,
        staging_name: str = SAMPLE_STAGING_NAME,
        dbhost: str = SAMPLE_DBHOST,
        status: str = "complete",
        finished_at: datetime | None = None,
    ) -> tuple:
        if finished_at is None:
            finished_at = datetime.now() - timedelta(hours=48)
        return (job_id, staging_name, dbhost, status, finished_at)
    return _create


# ---------------------------------------------------------------------------
# Environment Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_admin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up environment for admin commands."""
    monkeypatch.setenv("PULLDB_COORDINATION_SECRET", "aws-secretsmanager:/pulldb/mysql/coordination-db")
    monkeypatch.setenv("PULLDB_API_MYSQL_USER", "pulldb_api")
    monkeypatch.setenv("PULLDB_MYSQL_DATABASE", "pulldb_service")


# ---------------------------------------------------------------------------
# Mock Cursor Configuration Helpers
# ---------------------------------------------------------------------------


def configure_cursor_for_query(
    mock_pool: MagicMock,
    rows: list[tuple],
    columns: list[str],
) -> None:
    """Configure mock cursor to return specified rows and columns."""
    cursor = mock_pool._mock_cursor
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.description = [(col,) for col in columns]


def configure_cursor_for_update(
    mock_pool: MagicMock,
    rowcount: int = 1,
) -> None:
    """Configure mock cursor for UPDATE/INSERT operations."""
    cursor = mock_pool._mock_cursor
    cursor.rowcount = rowcount


def configure_cursor_fetchone(
    mock_pool: MagicMock,
    row: tuple | None,
    columns: list[str] | None = None,
) -> None:
    """Configure mock cursor fetchone result."""
    cursor = mock_pool._mock_cursor
    cursor.fetchone.return_value = row
    if columns:
        cursor.description = [(col,) for col in columns]


# ---------------------------------------------------------------------------
# Assertion Helpers
# ---------------------------------------------------------------------------


def assert_success(result) -> None:
    """Assert CLI command succeeded."""
    assert result.exit_code == 0, (
        f"Expected exit code 0, got {result.exit_code}\n"
        f"Output: {result.output}\n"
        f"Exception: {result.exception}"
    )


def assert_error(result, exit_code: int = 1) -> None:
    """Assert CLI command failed with expected exit code."""
    assert result.exit_code == exit_code, (
        f"Expected exit code {exit_code}, got {result.exit_code}\n"
        f"Output: {result.output}"
    )


def assert_contains(result, *texts: str) -> None:
    """Assert output contains all specified texts."""
    for text in texts:
        assert text in result.output, f"Expected '{text}' in output:\n{result.output}"


def assert_not_contains(result, *texts: str) -> None:
    """Assert output does not contain any specified texts."""
    for text in texts:
        assert text not in result.output, f"Did not expect '{text}' in output:\n{result.output}"


def assert_valid_json(result) -> Any:
    """Assert output is valid JSON and return parsed data."""
    try:
        return json.loads(result.output.strip())
    except json.JSONDecodeError as e:
        pytest.fail(f"Invalid JSON output: {e}\nOutput: {result.output}")
