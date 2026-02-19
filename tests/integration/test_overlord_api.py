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
    state.job_repo.get_job_by_id.return_value = mock_job
    
    # Mock overlord manager
    state.overlord_manager = MagicMock()
    state.overlord_manager.is_enabled = True
    
    return state


@pytest.fixture
def mock_user() -> MagicMock:
    """Create mock authenticated user."""
    from pulldb.domain.models import UserRole

    user = MagicMock()
    user.username = "testuser"
    user.user_code = "testuser"
    user.role = UserRole.ADMIN
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
        mock_tracking = MagicMock()
        mock_tracking.id = 1
        mock_tracking.database_name = "test_database"
        mock_tracking.job_id = "test-job-id-123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.previous_dbhost = "old-host.example.com"
        mock_tracking.previous_dbhost_read = None
        mock_tracking.current_dbhost = "new-host.example.com"
        mock_tracking.current_subdomain = "test"
        mock_tracking.company_id = 123
        mock_tracking.created_at = None
        mock_tracking.updated_at = None
        mock_tracking.released_at = None
        
        # Setup company mock as raw dict (matches get_all_companies return)
        mock_company_row = {
            "companyID": 123,
            "database": "test_database",
            "name": "Test Company",
            "subdomain": "test",
            "dbHost": "new-host.example.com",
            "dbHostRead": None,
        }
        
        mock_api_state.overlord_manager.get_state.return_value = (
            mock_tracking,
            mock_company_row,
        )
        mock_api_state.overlord_manager.get_all_companies.return_value = [mock_company_row]
        mock_api_state.overlord_manager.check_subdomain_duplicates.return_value = []
        
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
        mock_api_state.overlord_manager.get_all_companies.return_value = []
        
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
        mock_api_state.job_repo.get_job_by_id.return_value = None
        
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
        mock_tracking = MagicMock()
        mock_tracking.id = 1
        mock_tracking.database_name = "test_database"
        mock_tracking.job_id = "test-job-id-123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = False
        mock_tracking.previous_dbhost = None
        mock_tracking.previous_dbhost_read = None
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = "test"
        mock_tracking.company_id = 999
        mock_tracking.created_at = None
        mock_tracking.updated_at = None
        mock_tracking.released_at = None
        
        mock_api_state.overlord_manager.get_tracking.side_effect = [None, mock_tracking]
        mock_api_state.overlord_manager.claim.return_value = mock_tracking
        
        response = client.post(
            "/api/v1/overlord/test-job-id-123/sync",
            json={
                "job_id": "test-job-id-123",
                "database": "test_database",
                "dbHost": "staging.example.com",
                "subdomain": "test",
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
                "subdomain": "test",
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


# =============================================================================
# Test: POST /api/v1/overlord/{job_id}/company (Add Company)
# =============================================================================


class TestAddCompany:
    """Tests for POST /api/v1/overlord/{job_id}/company endpoint."""

    def test_add_company_success(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Add company creates a new record and returns success."""
        mock_api_state.overlord_manager.add_company.return_value = 999
        mock_tracking = MagicMock()
        mock_tracking.id = 1
        mock_tracking.database_name = "test_database"
        mock_tracking.job_id = "test-job-id-123"
        mock_tracking.status = OverlordTrackingStatus.CLAIMED
        mock_tracking.row_existed_before = False
        mock_tracking.previous_dbhost = None
        mock_tracking.previous_dbhost_read = None
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = "newco"
        mock_tracking.company_id = None
        mock_tracking.created_at = None
        mock_tracking.updated_at = None
        mock_tracking.released_at = None
        mock_api_state.overlord_manager.get_tracking.return_value = mock_tracking

        response = client.post(
            "/api/v1/overlord/test-job-id-123/company",
            json={
                "job_id": "test-job-id-123",
                "database": "test_database",
                "dbHost": "staging.example.com",
                "subdomain": "newco",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "999" in data["message"]

    def test_add_company_disabled(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Add company returns 400 when overlord disabled."""
        mock_api_state.overlord_manager.is_enabled = False

        response = client.post(
            "/api/v1/overlord/test-job-id-123/company",
            json={
                "job_id": "test-job-id-123",
                "database": "test_database",
                "dbHost": "staging.example.com",
                "subdomain": "newco",
            },
        )

        assert response.status_code == 400

    def test_add_company_requires_deployed_status(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Add company rejects non-deployed jobs."""
        mock_job = mock_api_state.job_repo.get_job.return_value
        mock_job.status.value = "restoring"

        response = client.post(
            "/api/v1/overlord/test-job-id-123/company",
            json={
                "job_id": "test-job-id-123",
                "database": "test_database",
                "dbHost": "staging.example.com",
                "subdomain": "newco",
            },
        )

        assert response.status_code == 400
        assert "restoring" in response.json()["detail"]


# =============================================================================
# Test: DELETE /api/v1/overlord/{job_id}/company/{company_id}
# =============================================================================


class TestDeleteCompany:
    """Tests for DELETE /api/v1/overlord/{job_id}/company/{company_id} endpoint."""

    def test_delete_company_success(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Delete company removes the record."""
        mock_api_state.overlord_manager.remove_company.return_value = True

        response = client.delete(
            "/api/v1/overlord/test-job-id-123/company/42",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_delete_company_not_found(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Delete company returns 404 when company doesn't exist."""
        mock_api_state.overlord_manager.remove_company.return_value = False

        response = client.delete(
            "/api/v1/overlord/test-job-id-123/company/999",
        )

        assert response.status_code == 404

    def test_delete_company_cross_database(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Delete company returns 400 when row belongs to different database."""
        from pulldb.domain.overlord import OverlordSafetyError

        mock_api_state.overlord_manager.remove_company.side_effect = OverlordSafetyError(
            "Company 42 belongs to 'other_db', not 'test_database'"
        )

        response = client.delete(
            "/api/v1/overlord/test-job-id-123/company/42",
        )

        assert response.status_code == 400
        assert "belongs to" in response.json()["detail"]

    def test_delete_company_requires_deployed_status(
        self,
        client: TestClient,
        mock_api_state: MagicMock,
    ) -> None:
        """Delete company rejects non-deployed jobs (6B fix)."""
        mock_job = mock_api_state.job_repo.get_job.return_value
        mock_job.status.value = "restoring"

        response = client.delete(
            "/api/v1/overlord/test-job-id-123/company/42",
        )

        assert response.status_code == 400
        assert "restoring" in response.json()["detail"]
