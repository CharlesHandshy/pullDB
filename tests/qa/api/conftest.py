"""
API Test Fixtures for pullDB QA Testing

Provides fixtures for:
- FastAPI TestClient
- Mock repositories (UserRepo, JobRepo, HostRepo, SettingsRepo)
- Sample data factories
- API state mocking

Usage:
    pytest tests/qa/api/ -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pulldb.domain.models import Job, JobEvent, JobStatus, MySQLCredentials, User


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
# TestClient Fixture
# ---------------------------------------------------------------------------


class MockAPIState:
    """Wrapper for APIState that allows test attribute assignment."""
    
    def __init__(
        self,
        config,
        pool,
        user_repo,
        job_repo,
        settings_repo,
        host_repo,
        auth_repo=None,
    ):
        self.config = config
        self.pool = pool
        self.user_repo = user_repo
        self.job_repo = job_repo
        self.settings_repo = settings_repo
        self.host_repo = host_repo
        self.auth_repo = auth_repo
    
    # Aliases for backward compatibility with tests
    @property
    def _mock_user_repo(self):
        return self.user_repo
    
    @property
    def _mock_job_repo(self):
        return self.job_repo
    
    @property
    def _mock_settings_repo(self):
        return self.settings_repo
    
    @property
    def _mock_host_repo(self):
        return self.host_repo


@pytest.fixture
def mock_api_state() -> Generator[MockAPIState, None, None]:
    """Mock the API state and its repositories."""
    from pulldb.api.main import app
    
    # Create mock repositories
    mock_config = MagicMock()
    mock_config.mysql_host = "localhost"
    mock_config.mysql_user = "pulldb_api"
    mock_config.mysql_password = "test"
    mock_config.mysql_database = "pulldb_service"
    mock_config.default_dbhost = SAMPLE_DBHOST
    mock_config.aws_profile = None
    
    mock_pool = MagicMock()
    mock_user_repo = MagicMock()
    mock_job_repo = MagicMock()
    mock_settings_repo = MagicMock()
    mock_host_repo = MagicMock()
    
    # Create state using our wrapper class
    state = MockAPIState(
        config=mock_config,
        pool=mock_pool,
        user_repo=mock_user_repo,
        job_repo=mock_job_repo,
        settings_repo=mock_settings_repo,
        host_repo=mock_host_repo,
        auth_repo=None,
    )
    
    # Install as app state
    app.state.api_state = state
    
    yield state
    
    # Clean up
    if hasattr(app.state, "api_state"):
        delattr(app.state, "api_state")


@pytest.fixture
def mock_admin_user() -> User:
    """Mock admin user for authenticated endpoints."""
    from pulldb.domain.models import UserRole
    return User(
        user_id="admin-1",
        username="admin",
        user_code="admin",
        role=UserRole.ADMIN,
        created_at=datetime.now(UTC),
        disabled_at=None,
        allowed_hosts=[SAMPLE_DBHOST],
    )


@pytest.fixture
def client(mock_api_state: MockAPIState, mock_admin_user: User) -> Generator[TestClient, None, None]:
    """FastAPI test client with mocked state and auth dependencies."""
    from pulldb.api.main import app
    from pulldb.api.auth import get_authenticated_user, get_admin_user, get_manager_user
    
    # Override auth dependencies to return mock admin user
    async def mock_auth_user():
        return mock_admin_user
    
    async def mock_admin():
        return mock_admin_user
    
    async def mock_manager():
        return mock_admin_user
    
    app.dependency_overrides[get_authenticated_user] = mock_auth_user
    app.dependency_overrides[get_admin_user] = mock_admin
    app.dependency_overrides[get_manager_user] = mock_manager
    
    yield TestClient(app)
    
    # Clean up overrides
    app.dependency_overrides.pop(get_authenticated_user, None)
    app.dependency_overrides.pop(get_admin_user, None)
    app.dependency_overrides.pop(get_manager_user, None)


# ---------------------------------------------------------------------------
# Sample Data Factories - Users
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_user() -> User:
    """Sample user object."""
    from pulldb.domain.models import UserRole
    return User(
        user_id="1",
        username=SAMPLE_USERNAME,
        user_code=SAMPLE_USER_CODE,
        role=UserRole.USER,
        created_at=datetime.now(UTC),
        disabled_at=None,
        allowed_hosts=[SAMPLE_DBHOST],
    )


@pytest.fixture
def user_factory() -> Callable[..., User]:
    """Factory for creating User objects."""
    from pulldb.domain.models import UserRole
    
    def _create(
        user_id: str = "1",
        username: str = SAMPLE_USERNAME,
        user_code: str = SAMPLE_USER_CODE,
        role: UserRole = UserRole.USER,
        disabled: bool = False,
        allowed_hosts: list[str] | None = None,
    ) -> User:
        return User(
            user_id=user_id,
            username=username,
            user_code=user_code,
            role=role,
            created_at=datetime.now(UTC),
            disabled_at=datetime.now(UTC) if disabled else None,
            allowed_hosts=allowed_hosts if allowed_hosts is not None else [SAMPLE_DBHOST],
        )
    return _create


# ---------------------------------------------------------------------------
# Sample Data Factories - Jobs
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_job() -> Job:
    """Sample job object."""
    return Job(
        id=SAMPLE_JOB_ID,
        owner_user_id="1",
        owner_username=SAMPLE_USERNAME,
        owner_user_code=SAMPLE_USER_CODE,
        target=SAMPLE_TARGET,
        staging_name=SAMPLE_STAGING_NAME,
        dbhost=SAMPLE_DBHOST,
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(UTC),
        options_json={"is_qatemplate": "true"},
    )


@pytest.fixture
def job_factory() -> Callable[..., Job]:
    """Factory for creating Job objects."""
    def _create(
        job_id: str = SAMPLE_JOB_ID,
        owner_user_id: str = "1",
        owner_username: str = SAMPLE_USERNAME,
        owner_user_code: str = SAMPLE_USER_CODE,
        target: str = SAMPLE_TARGET,
        staging_name: str | None = None,
        dbhost: str = SAMPLE_DBHOST,
        status: JobStatus = JobStatus.QUEUED,
        submitted_at: datetime | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        current_operation: str | None = None,
        error_detail: str | None = None,
        options_json: dict[str, str] | None = None,
        retry_count: int = 0,
    ) -> Job:
        if staging_name is None:
            staging_name = f"{target}_{job_id[:8]}{job_id[9:13]}"
        if submitted_at is None:
            submitted_at = datetime.now(UTC)
        if options_json is None:
            options_json = {"is_qatemplate": "true"}
        return Job(
            id=job_id,
            owner_user_id=owner_user_id,
            owner_username=owner_username,
            owner_user_code=owner_user_code,
            target=target,
            staging_name=staging_name,
            dbhost=dbhost,
            status=status,
            submitted_at=submitted_at,
            started_at=started_at,
            completed_at=completed_at,
            current_operation=current_operation,
            error_detail=error_detail,
            options_json=options_json,
            retry_count=retry_count,
        )
    return _create


# ---------------------------------------------------------------------------
# Sample Data Factories - Events
# ---------------------------------------------------------------------------


@pytest.fixture
def event_factory() -> Callable[..., JobEvent]:
    """Factory for creating JobEvent objects."""
    def _create(
        event_id: int = 1,
        job_id: str = SAMPLE_JOB_ID,
        event_type: str = "running",
        detail: str = "Job started",
        logged_at: datetime | None = None,
    ) -> JobEvent:
        if logged_at is None:
            logged_at = datetime.now(UTC)
        return JobEvent(
            id=event_id,
            job_id=job_id,
            event_type=event_type,
            detail=detail,
            logged_at=logged_at,
        )
    return _create


# ---------------------------------------------------------------------------
# Repository Configuration Helpers
# ---------------------------------------------------------------------------


def configure_user_repo(
    state: MagicMock,
    user: User | None = None,
    create_user: User | None = None,
) -> None:
    """Configure mock user repository."""
    repo = state._mock_user_repo
    repo.get_user_by_username.return_value = user
    if create_user:
        repo.get_or_create_user.return_value = create_user
    elif user:
        repo.get_or_create_user.return_value = user


def configure_job_repo(
    state: MagicMock,
    job: Job | None = None,
    jobs: list[Job] | None = None,
    events: list[JobEvent] | None = None,
    active_count: int = 0,
    user_active_count: int = 0,
    has_active_for_target: bool = False,
    locked_job: Job | None = None,
    deployed_job: Job | None = None,
) -> None:
    """Configure mock job repository."""
    repo = state._mock_job_repo
    repo.get_job_by_id.return_value = job
    repo.get_recent_jobs.return_value = jobs or []
    repo.get_active_jobs.return_value = jobs or []
    repo.get_job_events.return_value = events or []
    repo.find_jobs_by_prefix.return_value = [job] if job else []
    repo.count_all_active_jobs.return_value = active_count
    repo.count_active_jobs_for_user.return_value = user_active_count
    repo.enqueue_job.return_value = None
    repo.request_cancellation.return_value = True
    repo.has_active_jobs_for_target.return_value = has_active_for_target
    repo.get_locked_by_target.return_value = locked_job
    repo.get_deployed_job_for_target.return_value = deployed_job


def configure_settings_repo(
    state: MagicMock,
    max_global: int = 0,
    max_per_user: int = 0,
) -> None:
    """Configure mock settings repository."""
    repo = state._mock_settings_repo
    repo.get_max_active_jobs_global.return_value = max_global
    repo.get_max_active_jobs_per_user.return_value = max_per_user


def configure_host_repo(
    state: MagicMock,
    hosts: list | None = None,
    default_host: str = SAMPLE_DBHOST,
) -> None:
    """Configure mock host repository with proper credentials.
    
    Args:
        state: The MockAPIState instance.
        hosts: List of enabled hosts.
        default_host: Default hostname for credentials (used in get_host_credentials).
    """
    repo = state._mock_host_repo
    repo.get_enabled_hosts.return_value = hosts or []
    
    # Configure get_host_credentials to return proper MySQLCredentials
    # And database_exists / get_pulldb_metadata_owner for DB protection checks
    def mock_get_credentials(hostname: str) -> MySQLCredentials:
        return MySQLCredentials(
            username="mock_user",
            password="mock_password",
            host=hostname,
            port=3306,
        )
    
    repo.get_host_credentials.side_effect = mock_get_credentials
    repo.get_host_credentials_for_maintenance.side_effect = mock_get_credentials
    repo.database_exists.return_value = False
    repo.get_pulldb_metadata_owner.return_value = (False, None, None)


# ---------------------------------------------------------------------------
# Assertion Helpers
# ---------------------------------------------------------------------------


def assert_success(response, status_code: int = 200) -> dict[str, Any]:
    """Assert response is successful and return JSON."""
    assert response.status_code == status_code, (
        f"Expected status {status_code}, got {response.status_code}\n"
        f"Response: {response.text}"
    )
    return response.json()


def assert_error(response, status_code: int = 400) -> dict[str, Any]:
    """Assert response is an error and return JSON."""
    assert response.status_code == status_code, (
        f"Expected status {status_code}, got {response.status_code}\n"
        f"Response: {response.text}"
    )
    return response.json()


def assert_contains(data: dict, *keys: str) -> None:
    """Assert dict contains all specified keys."""
    for key in keys:
        assert key in data, f"Expected key '{key}' in {data.keys()}"
