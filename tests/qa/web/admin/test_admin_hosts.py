"""
Tests for Admin Hosts LazyTable API Endpoints

Tests for:
- GET /web/admin/api/hosts/paginated
- POST /web/admin/api/hosts/{host_id}/toggle

Test Count: 8 tests
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Generator
from unittest.mock import MagicMock
import uuid

import pytest
from fastapi.testclient import TestClient

from pulldb.domain.models import User, UserRole


# ---------------------------------------------------------------------------
# Sample Data
# ---------------------------------------------------------------------------

SAMPLE_HOST_ID = str(uuid.uuid4())
SAMPLE_HOST_ID_2 = str(uuid.uuid4())
SAMPLE_HOSTNAME = "mysql-staging-01.example.com"
SAMPLE_HOSTNAME_2 = "mysql-staging-02.example.com"
SAMPLE_ADMIN_ID = "admin-user-123"
SAMPLE_USER_ID = "regular-user-456"


def create_mock_host(
    host_id: str = SAMPLE_HOST_ID,
    hostname: str = SAMPLE_HOSTNAME,
    host_alias: str | None = "staging-db-01",
    enabled: bool = True,
    max_running_jobs: int = 2,
    max_active_jobs: int = 10,
) -> MagicMock:
    """Create a mock host object."""
    host = MagicMock()
    host.id = host_id
    host.hostname = hostname
    host.host_alias = host_alias
    host.credential_ref = f"/pulldb/mysql/{host_alias or hostname}"
    host.max_running_jobs = max_running_jobs
    host.max_active_jobs = max_active_jobs
    host.enabled = enabled
    host.created_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    return host


def create_admin_user() -> User:
    """Create an admin user for testing."""
    return User(
        user_id=SAMPLE_ADMIN_ID,
        username="admin",
        user_code="ADMIN123",
        is_admin=True,
        role=UserRole.ADMIN,
        created_at=datetime.now(UTC),
        disabled_at=None,
    )


def create_regular_user() -> User:
    """Create a regular user for testing."""
    return User(
        user_id=SAMPLE_USER_ID,
        username="testuser",
        user_code="USER456",
        is_admin=False,
        role=UserRole.USER,
        created_at=datetime.now(UTC),
        disabled_at=None,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class MockWebState:
    """Mock API state for web route testing."""
    
    def __init__(self) -> None:
        self._mock_host_repo = MagicMock()
        self._mock_job_repo = MagicMock()
        self._mock_user_repo = MagicMock()
        self._mock_auth_repo = MagicMock()
        self._mock_settings_repo = MagicMock()
        self._mock_config = MagicMock()
        
        # Default config values
        self._mock_config.mysql_host = "localhost"
        self._mock_config.mysql_user = "pulldb_api"
        
    @property
    def host_repo(self) -> MagicMock:
        return self._mock_host_repo
    
    @property
    def job_repo(self) -> MagicMock:
        return self._mock_job_repo
    
    @property
    def user_repo(self) -> MagicMock:
        return self._mock_user_repo
    
    @property
    def auth_repo(self) -> MagicMock:
        return self._mock_auth_repo
    
    @property
    def settings_repo(self) -> MagicMock:
        return self._mock_settings_repo
    
    @property
    def config(self) -> MagicMock:
        return self._mock_config


@pytest.fixture
def mock_web_state() -> Generator[MockWebState, None, None]:
    """Mock the API state for web tests."""
    from pulldb.api.main import app
    
    state = MockWebState()
    app.state.api_state = state
    
    yield state
    
    # Clean up
    if hasattr(app.state, "api_state"):
        delattr(app.state, "api_state")


@pytest.fixture
def admin_client(mock_web_state: MockWebState) -> TestClient:
    """TestClient with mocked admin authentication.
    
    Overrides require_admin to return an admin user without session validation.
    """
    from pulldb.api.main import app
    from pulldb.web.dependencies import require_admin, require_login, get_session_user
    
    admin_user = create_admin_user()
    
    # Override auth dependencies to bypass session validation
    app.dependency_overrides[get_session_user] = lambda: admin_user
    app.dependency_overrides[require_login] = lambda: admin_user
    app.dependency_overrides[require_admin] = lambda: admin_user
    
    client = TestClient(app, follow_redirects=False)
    
    yield client
    
    # Clean up overrides
    app.dependency_overrides.clear()


@pytest.fixture
def user_client(mock_web_state: MockWebState) -> TestClient:
    """TestClient with mocked non-admin user authentication.
    
    Does NOT override require_admin, so admin-protected routes will fail.
    """
    from pulldb.api.main import app
    from pulldb.web.dependencies import require_login, get_session_user
    from fastapi import HTTPException
    
    regular_user = create_regular_user()
    
    # Only override session user - require_admin will still check is_admin
    app.dependency_overrides[get_session_user] = lambda: regular_user
    app.dependency_overrides[require_login] = lambda: regular_user
    # Do NOT override require_admin - it should reject non-admin users
    
    client = TestClient(app, follow_redirects=False)
    
    yield client
    
    # Clean up overrides
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /web/admin/api/hosts/paginated Tests
# ---------------------------------------------------------------------------


class TestHostsPaginated:
    """Tests for paginated hosts endpoint."""

    def test_hosts_paginated_returns_rows(
        self, admin_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """GET /web/admin/api/hosts/paginated returns paginated host data."""
        mock_host = create_mock_host()
        mock_web_state._mock_host_repo.list_hosts.return_value = [mock_host]
        mock_web_state._mock_job_repo.get_active_jobs.return_value = []
        mock_web_state._mock_job_repo.count_jobs_by_host.return_value = 5

        response = admin_client.get("/web/admin/api/hosts/paginated")
        assert response.status_code == 200
        
        data = response.json()
        assert "rows" in data
        assert "totalCount" in data
        assert "stats" in data
        assert data["totalCount"] == 1
        assert len(data["rows"]) == 1
        
        row = data["rows"][0]
        assert row["hostname"] == SAMPLE_HOSTNAME
        assert row["host_alias"] == "staging-db-01"
        assert row["enabled"] is True
        assert row["total_restores"] == 5

    def test_hosts_paginated_returns_stats(
        self, admin_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """GET /web/admin/api/hosts/paginated returns stats for UI."""
        host1 = create_mock_host(SAMPLE_HOST_ID, SAMPLE_HOSTNAME, "db-01", enabled=True)
        host2 = create_mock_host(SAMPLE_HOST_ID_2, SAMPLE_HOSTNAME_2, "db-02", enabled=False)
        mock_web_state._mock_host_repo.list_hosts.return_value = [host1, host2]
        mock_web_state._mock_job_repo.get_active_jobs.return_value = []
        mock_web_state._mock_job_repo.count_jobs_by_host.return_value = 0

        response = admin_client.get("/web/admin/api/hosts/paginated")
        data = response.json()
        
        assert data["stats"]["total"] == 2
        assert data["stats"]["enabled"] == 1
        assert data["stats"]["disabled"] == 1

    def test_hosts_paginated_with_filter(
        self, admin_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """GET /web/admin/api/hosts/paginated supports status filter."""
        host1 = create_mock_host(SAMPLE_HOST_ID, SAMPLE_HOSTNAME, "db-01", enabled=True)
        host2 = create_mock_host(SAMPLE_HOST_ID_2, SAMPLE_HOSTNAME_2, "db-02", enabled=False)
        mock_web_state._mock_host_repo.list_hosts.return_value = [host1, host2]
        mock_web_state._mock_job_repo.get_active_jobs.return_value = []
        mock_web_state._mock_job_repo.count_jobs_by_host.return_value = 0

        response = admin_client.get(
            "/web/admin/api/hosts/paginated",
            params={"filter_status": "enabled"}
        )
        data = response.json()
        
        # Filter should return only enabled hosts
        assert data["filteredCount"] == 1
        assert len(data["rows"]) == 1
        assert data["rows"][0]["enabled"] is True

    def test_hosts_paginated_with_sorting(
        self, admin_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """GET /web/admin/api/hosts/paginated supports sorting."""
        host1 = create_mock_host(SAMPLE_HOST_ID, SAMPLE_HOSTNAME, "aaa-db", enabled=True)
        host2 = create_mock_host(SAMPLE_HOST_ID_2, SAMPLE_HOSTNAME_2, "zzz-db", enabled=True)
        mock_web_state._mock_host_repo.list_hosts.return_value = [host1, host2]
        mock_web_state._mock_job_repo.get_active_jobs.return_value = []
        mock_web_state._mock_job_repo.count_jobs_by_host.return_value = 0

        response = admin_client.get(
            "/web/admin/api/hosts/paginated",
            params={"sortColumn": "display_name", "sortDirection": "desc"}
        )
        data = response.json()
        
        # Should be sorted descending by display_name (alias)
        assert len(data["rows"]) == 2
        assert data["rows"][0]["host_alias"] == "zzz-db"
        assert data["rows"][1]["host_alias"] == "aaa-db"


# ---------------------------------------------------------------------------
# POST /web/admin/api/hosts/{host_id}/toggle Tests
# ---------------------------------------------------------------------------


class TestHostToggle:
    """Tests for host toggle endpoint."""

    def test_toggle_enables_disabled_host(
        self, admin_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """POST toggle enables a disabled host."""
        mock_host = create_mock_host(enabled=False)
        mock_web_state._mock_host_repo.get_host_by_id.return_value = mock_host
        mock_web_state._mock_host_repo.enable_host = MagicMock()

        response = admin_client.post(f"/web/admin/api/hosts/{SAMPLE_HOST_ID}/toggle")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["enabled"] is True
        mock_web_state._mock_host_repo.enable_host.assert_called_once_with(SAMPLE_HOSTNAME)

    def test_toggle_disables_enabled_host(
        self, admin_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """POST toggle disables an enabled host."""
        mock_host = create_mock_host(enabled=True)
        mock_web_state._mock_host_repo.get_host_by_id.return_value = mock_host
        mock_web_state._mock_host_repo.disable_host = MagicMock()

        response = admin_client.post(f"/web/admin/api/hosts/{SAMPLE_HOST_ID}/toggle")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["enabled"] is False
        mock_web_state._mock_host_repo.disable_host.assert_called_once_with(SAMPLE_HOSTNAME)

    def test_toggle_host_not_found(
        self, admin_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """POST toggle returns error for nonexistent host."""
        mock_web_state._mock_host_repo.get_host_by_id.return_value = None

        response = admin_client.post(f"/web/admin/api/hosts/{SAMPLE_HOST_ID}/toggle")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    def test_toggle_requires_admin(
        self, user_client: TestClient, mock_web_state: MockWebState
    ) -> None:
        """POST toggle requires admin role."""
        response = user_client.post(f"/web/admin/api/hosts/{SAMPLE_HOST_ID}/toggle")
        # Should redirect to login or return 403
        assert response.status_code in (302, 303, 403)
