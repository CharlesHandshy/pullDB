"""Pytest fixtures for pullDB web application tests.

Provides test client, mock authentication, and sample data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Generator


# ---------------------------------------------------------------------------
# Sample Test Data
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_user() -> MagicMock:
    """Sample authenticated user."""
    user = MagicMock()
    user.user_id = 1
    user.username = "testuser"
    user.user_code = "testu"
    user.role = "operator"
    user.disabled_at = None
    return user


@pytest.fixture
def admin_user() -> MagicMock:
    """Sample admin user with elevated permissions."""
    user = MagicMock()
    user.user_id = 2
    user.username = "admin"
    user.user_code = "admin"
    user.role = "admin"
    user.disabled_at = None
    return user


@pytest.fixture
def sample_job() -> MagicMock:
    """Sample job for testing."""
    job = MagicMock()
    job.id = str(uuid4())
    job.target = "testdb"
    job.staging_name = "testdb_abc123def456"
    job.dbhost = "db-host-01"
    job.owner_user_id = 1
    job.owner_username = "testuser"
    job.owner_user_code = "testu"
    job.status = MagicMock()
    job.status.value = "running"
    job.submitted_at = datetime.now(UTC) - timedelta(minutes=5)
    job.started_at = datetime.now(UTC) - timedelta(minutes=4)
    job.completed_at = None
    job.worker_id = "worker-001"
    job.current_operation = "restore"
    job.error_detail = None
    job.options_json = None
    return job


@pytest.fixture
def completed_job() -> MagicMock:
    """Sample completed job."""
    job = MagicMock()
    job.id = str(uuid4())
    job.target = "completed_db"
    job.staging_name = "completed_db_111222333444"
    job.dbhost = "db-host-02"
    job.owner_user_id = 1
    job.owner_username = "testuser"
    job.owner_user_code = "testu"
    job.status = MagicMock()
    job.status.value = "complete"
    job.submitted_at = datetime.now(UTC) - timedelta(hours=1)
    job.started_at = datetime.now(UTC) - timedelta(minutes=55)
    job.completed_at = datetime.now(UTC) - timedelta(minutes=30)
    job.worker_id = "worker-002"
    job.current_operation = None
    job.error_detail = None
    job.options_json = None
    return job


@pytest.fixture
def failed_job() -> MagicMock:
    """Sample failed job."""
    job = MagicMock()
    job.id = str(uuid4())
    job.target = "failed_db"
    job.staging_name = "failed_db_aabbccddeeff"
    job.dbhost = "db-host-01"
    job.owner_user_id = 1
    job.owner_username = "testuser"
    job.owner_user_code = "testu"
    job.status = MagicMock()
    job.status.value = "failed"
    job.submitted_at = datetime.now(UTC) - timedelta(hours=2)
    job.started_at = datetime.now(UTC) - timedelta(hours=1, minutes=55)
    job.completed_at = datetime.now(UTC) - timedelta(hours=1, minutes=50)
    job.worker_id = "worker-001"
    job.current_operation = None
    job.error_detail = "Disk space exhausted"
    job.options_json = None
    return job


@pytest.fixture
def sample_event() -> MagicMock:
    """Sample job event."""
    event = MagicMock()
    event.id = 1
    event.job_id = "test-job-id"
    event.event_type = "start"
    event.detail = "Job started"
    event.created_at = datetime.now(UTC) - timedelta(minutes=5)
    return event


@pytest.fixture
def sample_events() -> list[MagicMock]:
    """Sample list of job events."""
    events = []
    for i, (event_type, detail) in enumerate([
        ("queued", "Job submitted"),
        ("start", "Worker claimed job"),
        ("progress", "Downloading backup"),
        ("progress", "Extracting archive"),
        ("progress", "Running myloader"),
    ]):
        event = MagicMock()
        event.id = i + 1
        event.job_id = "test-job-id"
        event.event_type = event_type
        event.detail = detail
        event.created_at = datetime.now(UTC) - timedelta(minutes=5 - i)
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Mock API State
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api_state(
    sample_user: MagicMock,
    sample_job: MagicMock,
    completed_job: MagicMock,
    sample_events: list[MagicMock],
) -> MagicMock:
    """Mock API state with repositories."""
    state = MagicMock()
    
    # User repo
    state.user_repo.get_user_by_id.return_value = sample_user
    state.user_repo.get_user_by_username.return_value = sample_user
    
    # Auth repo
    state.auth_repo.validate_session.return_value = sample_user.user_id
    state.auth_repo.get_password_hash.return_value = "hashed_password"
    state.auth_repo.create_session.return_value = (1, "test_session_token")
    
    # Job repo
    state.job_repo.get_active_jobs.return_value = [sample_job]
    state.job_repo.get_recent_jobs.return_value = [sample_job, completed_job]
    state.job_repo.get_job_by_id.return_value = sample_job
    state.job_repo.get_job_events.return_value = sample_events
    
    return state


# ---------------------------------------------------------------------------
# Test Client Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def web_client(mock_api_state: MagicMock) -> Generator[TestClient, None, None]:
    """Test client for web routes with mocked dependencies."""
    from pulldb.api.main import create_app
    
    app = create_app()
    
    with patch("pulldb.web.routes._get_api_state", return_value=mock_api_state):
        with TestClient(app) as client:
            yield client


@pytest.fixture
def authenticated_client(
    web_client: TestClient,
    mock_api_state: MagicMock,
) -> TestClient:
    """Test client with authenticated session cookie."""
    web_client.cookies.set("session_token", "valid_session_token")
    return web_client


@pytest.fixture
def unauthenticated_client(web_client: TestClient) -> TestClient:
    """Test client without authentication."""
    web_client.cookies.clear()
    return web_client
