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
# Admin Authorization Bypass Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def bypass_admin_auth() -> Generator[None, None, None]:
    """Bypass admin authorization check for tests.
    
    The admin CLI checks if the current user has admin role before
    executing commands. This fixture bypasses that check for all tests.
    """
    with patch("pulldb.cli.admin._check_admin_authorization"):
        yield


# ---------------------------------------------------------------------------
# Mock MySQL Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mysql_pool() -> Generator[MagicMock, None, None]:
    """Mock the repositories for admin commands.
    
    The admin commands use repository pattern via pulldb.infra.factory,
    not direct MySQL connections. This fixture mocks those factories.
    """
    with patch("pulldb.infra.factory.get_job_repository") as mock_job_repo, \
         patch("pulldb.infra.factory.get_host_repository") as mock_host_repo, \
         patch("pulldb.infra.factory.get_user_repository") as mock_user_repo, \
         patch("pulldb.infra.factory.get_disallowed_user_repository") as mock_disallow_repo:
        
        # Create mock repositories
        job_repo = MagicMock()
        host_repo = MagicMock()
        user_repo = MagicMock()
        disallow_repo = MagicMock()
        
        mock_job_repo.return_value = job_repo
        mock_host_repo.return_value = host_repo
        mock_user_repo.return_value = user_repo
        mock_disallow_repo.return_value = disallow_repo
        
        # Create a combined mock object for backward compatibility
        pool = MagicMock()
        pool._job_repo = job_repo
        pool._host_repo = host_repo
        pool._user_repo = user_repo
        pool._disallow_repo = disallow_repo
        
        # Simulate cursor-like interface for test helpers
        cursor = MagicMock()
        pool._mock_cursor = cursor
        pool._mock_conn = MagicMock()
        
        yield pool


@pytest.fixture
def mock_settings_mysql_pool() -> Generator[MagicMock, None, None]:
    """Mock the settings repository for settings commands.
    
    Settings commands use the repository pattern via pulldb.infra.factory.
    """
    with patch("pulldb.infra.factory.get_settings_repository") as mock_settings_repo:
        settings_repo = MagicMock()
        settings_repo.get_all_settings.return_value = {}
        mock_settings_repo.return_value = settings_repo
        
        # Create a pool-like object for backward compatibility
        pool = MagicMock()
        pool._settings_repo = settings_repo
        pool._mock_cursor = MagicMock()
        pool._mock_conn = MagicMock()
        
        yield pool


@pytest.fixture
def mock_settings_repo() -> Generator[MagicMock, None, None]:
    """Mock the SettingsRepository for settings commands.
    
    Settings commands use pulldb.infra.factory.get_settings_repository.
    """
    with patch("pulldb.infra.factory.get_settings_repository") as mock_factory:
        repo = MagicMock()
        repo.get_all_settings.return_value = {}
        mock_factory.return_value = repo
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
# Mock Repository Configuration Helpers
# ---------------------------------------------------------------------------


def configure_cursor_for_query(
    mock_pool: MagicMock,
    rows: list[tuple],
    columns: list[str],
) -> None:
    """Configure repository mocks to return data based on rows/columns.
    
    This helper bridges the old cursor-based test design to repository pattern.
    It infers which repository method to mock based on the column names and
    configures appropriate return values.
    """
    from pulldb.domain.models import DBHost, Job, JobStatus, User, UserRole
    
    # Determine which type of data based on columns
    if "hostname" in columns and "max_concurrent_jobs" in columns:
        # Hosts data - configure host repository
        hosts = []
        for row in rows:
            # Map tuple to DBHost using column positions
            col_map = {c: i for i, c in enumerate(columns)}
            hosts.append(DBHost(
                id=str(row[col_map.get("id", 0)] if "id" in col_map else 1),
                hostname=row[col_map["hostname"]],
                credential_ref=row[col_map.get("credential_reference", col_map.get("credential_ref", 3))] or "",
                max_running_jobs=row[col_map.get("max_concurrent_jobs", col_map.get("max_running_jobs", 1))],
                max_active_jobs=row[col_map.get("max_active_jobs", 1)] if "max_active_jobs" in col_map else 10,
                enabled=row[col_map.get("enabled", 2)],
                created_at=row[col_map.get("created_at", 4)] if "created_at" in col_map else datetime(2025, 1, 15),
            ))
        if hasattr(mock_pool, "_host_repo"):
            mock_pool._host_repo.get_all_hosts.return_value = hosts
            mock_pool._host_repo.list_hosts.return_value = hosts
    
    elif "target" in columns and "dbhost" in columns:
        # Jobs data - configure job repository
        jobs = []
        for row in rows:
            col_map = {c: i for i, c in enumerate(columns)}
            status_val = row[col_map.get("status", 1)]
            status = JobStatus(status_val) if isinstance(status_val, str) else status_val
            job_id = row[col_map.get("id", col_map.get("job_id", 0))]
            target_val = row[col_map["target"]]
            # Handle staging_name
            if "staging_name" in col_map:
                staging_name = row[col_map["staging_name"]]
            else:
                staging_name = f"{target_val}_{str(job_id)[:12]}"
            jobs.append(Job(
                id=job_id,
                owner_user_id=str(row[col_map.get("user_id", 0)] if "user_id" in col_map else 1),
                owner_username=row[col_map.get("username", 4)],
                owner_user_code=row[col_map.get("user_code", 5)],
                target=target_val,
                staging_name=staging_name,
                dbhost=row[col_map["dbhost"]],
                status=status,
                submitted_at=row[col_map.get("submitted_at", 6)] or datetime(2025, 1, 15),
                started_at=row[col_map.get("started_at", 7)] if "started_at" in col_map else None,
                completed_at=row[col_map.get("finished_at", col_map.get("completed_at", 8))] if "finished_at" in col_map or "completed_at" in col_map else None,
                current_operation=row[col_map.get("current_operation", 9)] if "current_operation" in col_map else None,
            ))
        if hasattr(mock_pool, "_job_repo"):
            mock_pool._job_repo.list_jobs.return_value = jobs
            mock_pool._job_repo.find_orphaned_staging_databases.return_value = jobs
    
    elif "staging_name" in columns and "finished_at" in columns:
        # Orphan cleanup data - configure job repository
        jobs = []
        for row in rows:
            col_map = {c: i for i, c in enumerate(columns)}
            status_val = row[col_map.get("status", 3)]
            status = JobStatus(status_val) if isinstance(status_val, str) else status_val
            jobs.append(Job(
                id=row[col_map.get("id", col_map.get("job_id", 0))],
                owner_user_id="1",
                owner_username="test",
                owner_user_code="test01",
                target=row[col_map.get("staging_name", 1)].rsplit("_", 1)[0] if "staging_name" in col_map else "test",
                staging_name=row[col_map.get("staging_name", 1)],
                dbhost=row[col_map.get("dbhost", 2)],
                status=status,
                submitted_at=datetime(2025, 1, 15),
                completed_at=row[col_map.get("finished_at", 4)] if "finished_at" in col_map else None,
            ))
        if hasattr(mock_pool, "_job_repo"):
            mock_pool._job_repo.find_orphaned_staging_databases.return_value = jobs
    
    elif "username" in columns and "user_code" in columns:
        # Users data - configure user repository
        from pulldb.domain.models import UserSummary  # May need to handle this
        users = []
        for row in rows:
            col_map = {c: i for i, c in enumerate(columns)}
            user = User(
                user_id=str(row[col_map.get("id", col_map.get("user_id", 0))]),
                username=row[col_map["username"]],
                user_code=row[col_map["user_code"]],
                is_admin=row[col_map.get("is_admin", 3)] if "is_admin" in col_map else False,
                role=UserRole.ADMIN if row[col_map.get("is_admin", 3)] else UserRole.USER if "is_admin" in col_map else UserRole.USER,
                created_at=row[col_map.get("created_at", 5)] if "created_at" in col_map else datetime(2025, 1, 15),
                disabled_at=datetime.now() if row[col_map.get("disabled", 4)] else None if "disabled" in col_map else None,
            )
            users.append(user)
        if hasattr(mock_pool, "_user_repo"):
            # The list command uses get_users_with_job_counts which returns UserSummary objects
            # Create minimal UserSummary-like objects
            class UserSummaryMock:
                def __init__(self, user, active_jobs):
                    self.user = user
                    self.active_jobs_count = active_jobs
            
            summaries = []
            for i, user in enumerate(users):
                col_map = {c: j for j, c in enumerate(columns)}
                active_jobs = rows[i][col_map.get("active_jobs", 6)] if "active_jobs" in col_map else 0
                summaries.append(UserSummaryMock(user, active_jobs))
            mock_pool._user_repo.get_users_with_job_counts.return_value = summaries
    
    # Also set cursor for backward compatibility
    cursor = mock_pool._mock_cursor
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.description = [(col,) for col in columns]


def configure_cursor_for_update(
    mock_pool: MagicMock,
    rowcount: int = 1,
) -> None:
    """Configure repository mocks for UPDATE/INSERT operations.
    
    For repository pattern, this configures enable/disable methods to succeed or fail.
    """
    cursor = mock_pool._mock_cursor
    cursor.rowcount = rowcount
    
    # Configure repository methods based on rowcount
    if hasattr(mock_pool, "_host_repo"):
        if rowcount > 0:
            mock_pool._host_repo.enable_host.return_value = None
            mock_pool._host_repo.disable_host.return_value = None
            mock_pool._host_repo.add_host.return_value = None
        else:
            mock_pool._host_repo.enable_host.side_effect = ValueError("Host not found")
            mock_pool._host_repo.disable_host.side_effect = ValueError("Host not found")
    
    if hasattr(mock_pool, "_user_repo"):
        if rowcount > 0:
            mock_pool._user_repo.enable_user.return_value = None
            mock_pool._user_repo.disable_user.return_value = None
        else:
            mock_pool._user_repo.enable_user.side_effect = ValueError("User not found")
            mock_pool._user_repo.disable_user.side_effect = ValueError("User not found")
    
    if hasattr(mock_pool, "_job_repo"):
        if rowcount > 0:
            mock_pool._job_repo.request_cancellation.return_value = True
            mock_pool._job_repo.mark_staging_cleaned.return_value = None
        else:
            mock_pool._job_repo.request_cancellation.return_value = False


def configure_cursor_fetchone(
    mock_pool: MagicMock,
    row: tuple | None,
    columns: list[str] | None = None,
) -> None:
    """Configure repository mocks for single-record fetch operations.
    
    This is used for operations like jobs cancel (get_job_by_id) and users show.
    """
    from pulldb.domain.models import Job, JobStatus, User, UserRole
    
    cursor = mock_pool._mock_cursor
    cursor.fetchone.return_value = row
    if columns:
        cursor.description = [(col,) for col in columns]
    
    # Configure repository based on data type
    if row is None:
        if hasattr(mock_pool, "_job_repo"):
            mock_pool._job_repo.get_job_by_id.return_value = None
            mock_pool._job_repo.find_jobs_by_prefix.return_value = []
        if hasattr(mock_pool, "_user_repo"):
            mock_pool._user_repo.get_user_detail.return_value = None
        return
    
    # If row is a single status value (from old job cancel tests)
    if len(row) == 1 and isinstance(row[0], str):
        status_val = row[0]
        if hasattr(mock_pool, "_job_repo"):
            # Create a mock job with this status
            job = Job(
                id=SAMPLE_JOB_ID,
                owner_user_id="1",
                owner_username=SAMPLE_USERNAME,
                owner_user_code=SAMPLE_USER_CODE,
                target=SAMPLE_TARGET,
                staging_name=SAMPLE_STAGING_NAME,
                dbhost=SAMPLE_DBHOST,
                status=JobStatus(status_val),
                submitted_at=datetime(2025, 1, 15),
            )
            mock_pool._job_repo.get_job_by_id.return_value = job
            mock_pool._job_repo.find_jobs_by_prefix.return_value = [job]
        return
    
    # Full user detail row
    if columns and "total_jobs" in columns:
        col_map = {c: i for i, c in enumerate(columns)}
        user = User(
            user_id=str(row[col_map.get("id", 0)]),
            username=row[col_map["username"]],
            user_code=row[col_map["user_code"]],
            is_admin=row[col_map.get("is_admin", 3)] if "is_admin" in col_map else False,
            role=UserRole.ADMIN if row[col_map.get("is_admin", 3)] else UserRole.USER if "is_admin" in col_map else UserRole.USER,
            created_at=row[col_map.get("created_at", 5)] if "created_at" in col_map else datetime(2025, 1, 15),
            disabled_at=datetime.now() if row[col_map.get("disabled", 4)] else None if "disabled" in col_map else None,
        )
        
        class UserDetailMock:
            def __init__(self, user, total, complete, failed, active):
                self.user = user
                self.total_jobs = total
                self.complete_jobs = complete
                self.failed_jobs = failed
                self.active_jobs = active
        
        detail = UserDetailMock(
            user,
            row[col_map.get("total_jobs", 6)] if "total_jobs" in col_map else 0,
            row[col_map.get("complete_jobs", 7)] if "complete_jobs" in col_map else 0,
            row[col_map.get("failed_jobs", 8)] if "failed_jobs" in col_map else 0,
            row[col_map.get("active_jobs", 9)] if "active_jobs" in col_map else 0,
        )
        if hasattr(mock_pool, "_user_repo"):
            mock_pool._user_repo.get_user_detail.return_value = detail


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
