"""Integration tests for overlord API routes.

Feature: 54166071 - Button to update overlord.companies

These tests verify the API routes work correctly with the OverlordManager.
Uses mocked repositories to avoid database dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulldb.api.overlord import create_overlord_router
from pulldb.infra.overlord import (
    OverlordCompany,
    OverlordTracking,
    OverlordTrackingStatus,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_api_state() -> MagicMock:
    """Create mock API state with overlord manager."""
    state = MagicMock()
    
    # Mock job repository
    mock_job = MagicMock()
    mock_job.id = "test-job-id-123"
    mock_job.target = "test_database"
    mock_job.status = MagicMock()
    mock_job.status.value = "deployed"
    mock_job.dbhost = "test-host.example.com"
    mock_job.owner_user_code = "testuser"
    state.job_repo.get_job.return_value = mock_job
    
    # Mock overlord manager
    state.overlord_manager = MagicMock()
    state.overlord_manager.is_enabled = True
    
    return state


@pytest.fixture
def mock_user() -> MagicMock:
    """Create mock authenticated user."""
    user = MagicMock()
    user.username = "testuser"
    user.role = MagicMock()
    user.role.name = "user"
    return user


@pytest.fixture
def client(mock_api_state: MagicMock, mock_user: MagicMock) -> TestClient:
    """Create test client with mocked dependencies."""
    app = FastAPI()
    
    def get_api_state():
        return mock_api_state
    
    def require_auth():
        return mock_user
    
    router = create_overlord_router(get_api_state, require_auth)
    app.include_router(router)
    
    return TestClient(app)


# =============================================================================
# Test: GET /api/v1/overlord/{job_id}
# =============================================================================


class TestGetOverlordState:
    """Tests for GET /api/v1/overlord/{job_id} endpoint."""

    def test_get_state_success(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Get state returns job, tracking, and company data."""
        # Setup tracking mock
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.id = 1
        mock_tracking.database_name = "test_database"
        mock_tracking.job_id = "test-job-id-123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.previous_dbhost = "old-host.example.com"
        mock_tracking.previous_dbhost_read = None
        mock_tracking.current_dbhost = "new-host.example.com"
        mock_tracking.company_id = 123
        mock_tracking.claimed_at = None
        mock_tracking.synced_at = None
        
        # Setup company mock
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.company_id = 123
        mock_company.database = "test_database"
        mock_company.name = "Test Company"
        mock_company.subdomain = "test"
        mock_company.db_host = "new-host.example.com"
        mock_company.db_host_read = None
        
        mock_api_state.overlord_manager.get_state.return_value = (
            mock_tracking,
            mock_company,
        )
        
        response = client.get("/api/v1/overlord/test-job-id-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["job"]["id"] == "test-job-id-123"
        assert data["tracking"]["status"] == "synced"
        assert data["company"]["name"] == "Test Company"

    def test_get_state_no_tracking(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Get state returns null tracking when not claimed."""
        mock_api_state.overlord_manager.get_state.return_value = (None, None)
        
        response = client.get("/api/v1/overlord/test-job-id-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["tracking"] is None
        assert data["company"] is None

    def test_get_state_disabled(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Get state returns enabled=false when overlord disabled."""
        mock_api_state.overlord_manager.is_enabled = False
        
        response = client.get("/api/v1/overlord/test-job-id-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

    def test_get_state_job_not_found(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Get state returns 404 when job not found."""
        mock_api_state.job_repo.get_job.return_value = None
        
        response = client.get("/api/v1/overlord/nonexistent-job")
        
        assert response.status_code == 404


# =============================================================================
# Test: POST /api/v1/overlord/{job_id}/sync
# =============================================================================


class TestSyncOverlord:
    """Tests for POST /api/v1/overlord/{job_id}/sync endpoint."""

    def test_sync_success(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Sync successfully updates overlord."""
        # Mock claim (auto-claim)
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.id = 1
        mock_tracking.database_name = "test_database"
        mock_tracking.job_id = "test-job-id-123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = False
        mock_tracking.previous_dbhost = None
        mock_tracking.previous_dbhost_read = None
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.company_id = 999
        mock_tracking.claimed_at = None
        mock_tracking.synced_at = None
        
        mock_api_state.overlord_manager.get_tracking.side_effect = [None, mock_tracking]
        mock_api_state.overlord_manager.claim.return_value = mock_tracking
        
        response = client.post(
            "/api/v1/overlord/test-job-id-123/sync",
            json={
                "job_id": "test-job-id-123",
                "database": "test_database",
                "dbHost": "staging.example.com",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_api_state.overlord_manager.sync.assert_called_once()

    def test_sync_disabled(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Sync returns 400 when overlord disabled."""
        mock_api_state.overlord_manager.is_enabled = False
        
        response = client.post(
            "/api/v1/overlord/test-job-id-123/sync",
            json={
                "job_id": "test-job-id-123",
                "database": "test_database",
                "dbHost": "staging.example.com",
            },
        )
        
        assert response.status_code == 400


# =============================================================================
# Test: POST /api/v1/overlord/{job_id}/release
# =============================================================================


class TestReleaseOverlord:
    """Tests for POST /api/v1/overlord/{job_id}/release endpoint."""

    def test_release_restore_success(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Release with restore action succeeds."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.action_taken = MagicMock()
        mock_result.action_taken.value = "restore"
        mock_result.message = "Restored original values"
        
        mock_api_state.overlord_manager.release.return_value = mock_result
        
        response = client.post(
            "/api/v1/overlord/test-job-id-123/release",
            json={
                "job_id": "test-job-id-123",
                "action": "restore",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["action_taken"] == "restore"

    def test_release_delete_success(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Release with delete action succeeds."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.action_taken = MagicMock()
        mock_result.action_taken.value = "delete"
        mock_result.message = "Deleted row"
        
        mock_api_state.overlord_manager.release.return_value = mock_result
        
        response = client.post(
            "/api/v1/overlord/test-job-id-123/release",
            json={
                "job_id": "test-job-id-123",
                "action": "delete",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["action_taken"] == "delete"
