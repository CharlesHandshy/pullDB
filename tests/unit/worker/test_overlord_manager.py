"""Unit tests for overlord_manager module.

Feature: 54166071 - Button to update overlord.companies

Tests the OverlordManager business logic for managing overlord.companies
integration with safety enforcement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pulldb.infra.overlord import (
    OverlordAlreadyClaimedError,
    OverlordCompany,
    OverlordOwnershipError,
    OverlordSafetyError,
    OverlordTracking,
    OverlordTrackingStatus,
)
from pulldb.worker.overlord_manager import (
    OverlordManager,
    ReleaseAction,
    ReleaseResult,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock MySQL pool."""
    return MagicMock()


@pytest.fixture
def mock_overlord_connection() -> MagicMock:
    """Create a mock overlord connection."""
    return MagicMock()


@pytest.fixture
def mock_job_repo() -> MagicMock:
    """Create a mock job repository."""
    repo = MagicMock()
    # Default: job exists and is deployed
    mock_job = MagicMock()
    mock_job.id = "test-job-id"
    mock_job.target = "test_database"
    mock_job.status = MagicMock()
    mock_job.status.value = "deployed"
    repo.get_job_by_id.return_value = mock_job
    return repo


@pytest.fixture
def mock_audit_repo() -> MagicMock:
    """Create a mock audit repository."""
    return MagicMock()


@pytest.fixture
def manager(
    mock_pool: MagicMock,
    mock_overlord_connection: MagicMock,
    mock_job_repo: MagicMock,
    mock_audit_repo: MagicMock,
) -> OverlordManager:
    """Create an OverlordManager with mocked dependencies."""
    with patch("pulldb.worker.overlord_manager.OverlordTrackingRepository") as mock_tracking_repo_cls, \
         patch("pulldb.worker.overlord_manager.OverlordRepository") as mock_overlord_repo_cls:
        
        # Set up tracking repo mock
        mock_tracking_repo = MagicMock()
        mock_tracking_repo_cls.return_value = mock_tracking_repo
        
        # Set up overlord repo mock
        mock_overlord_repo = MagicMock()
        mock_overlord_repo_cls.return_value = mock_overlord_repo
        
        mgr = OverlordManager(
            pool=mock_pool,
            overlord_connection=mock_overlord_connection,
            job_repo=mock_job_repo,
            audit_repo=mock_audit_repo,
        )
        
        # Store mocks for test access
        mgr._tracking_repo = mock_tracking_repo
        mgr._overlord_repo = mock_overlord_repo
        
        return mgr


# =============================================================================
# Test: is_enabled
# =============================================================================


class TestIsEnabled:
    """Tests for is_enabled property."""

    def test_enabled_when_connection_exists(self, manager: OverlordManager) -> None:
        """Manager is enabled when overlord connection exists."""
        assert manager.is_enabled is True

    def test_disabled_when_no_connection(
        self,
        mock_pool: MagicMock,
        mock_job_repo: MagicMock,
        mock_audit_repo: MagicMock,
    ) -> None:
        """Manager is disabled when no overlord connection."""
        with patch("pulldb.worker.overlord_manager.OverlordTrackingRepository"):
            mgr = OverlordManager(
                pool=mock_pool,
                overlord_connection=None,
                job_repo=mock_job_repo,
                audit_repo=mock_audit_repo,
            )
            assert mgr.is_enabled is False


# =============================================================================
# Test: verify_ownership
# =============================================================================


class TestVerifyOwnership:
    """Tests for verify_ownership method."""

    def test_ownership_verified_success(self, manager: OverlordManager) -> None:
        """Ownership verification succeeds for valid job."""
        result = manager.verify_ownership("test_database", "test-job-id")
        assert result is True

    def test_ownership_fails_job_not_found(self, manager: OverlordManager) -> None:
        """Ownership verification fails when job not found."""
        manager._job_repo.get_job_by_id.return_value = None
        
        with pytest.raises(OverlordOwnershipError, match="not found"):
            manager.verify_ownership("test_database", "nonexistent-job")

    def test_ownership_fails_wrong_target(self, manager: OverlordManager) -> None:
        """Ownership verification fails when job target doesn't match."""
        mock_job = manager._job_repo.get_job_by_id.return_value
        mock_job.target = "different_database"
        
        with pytest.raises(OverlordOwnershipError, match="target is"):
            manager.verify_ownership("test_database", "test-job-id")

    def test_ownership_fails_not_deployed(self, manager: OverlordManager) -> None:
        """Ownership verification fails when job not deployed."""
        mock_job = manager._job_repo.get_job_by_id.return_value
        mock_job.status.value = "running"
        
        with pytest.raises(OverlordOwnershipError, match="not 'deployed'"):
            manager.verify_ownership("test_database", "test-job-id")


# =============================================================================
# Test: claim
# =============================================================================


class TestClaim:
    """Tests for claim method."""

    def test_claim_success_no_existing_row(self, manager: OverlordManager) -> None:
        """Claim succeeds when no existing overlord row."""
        # No existing tracking
        manager._tracking_repo.get.return_value = None
        # No existing overlord row
        manager._overlord_repo.get_all_by_database.return_value = []
        # Return tracking after create
        mock_tracking = MagicMock(spec=OverlordTracking)
        manager._tracking_repo.get.side_effect = [None, mock_tracking]
        
        result = manager.claim("test_database", "test-job-id", "user123")
        
        # Verify tracking was created
        manager._tracking_repo.create.assert_called_once()
        call_kwargs = manager._tracking_repo.create.call_args.kwargs
        assert call_kwargs["database_name"] == "test_database"
        assert call_kwargs["job_id"] == "test-job-id"
        assert call_kwargs["row_existed_before"] is False
        assert call_kwargs["previous_dbhost"] is None

    def test_claim_success_existing_row(self, manager: OverlordManager) -> None:
        """Claim succeeds and backs up existing overlord row."""
        # No existing tracking
        manager._tracking_repo.get.return_value = None
        # Existing overlord rows (multi-company snapshot)
        manager._overlord_repo.get_all_by_database.return_value = [
            {
                "companyID": 123,
                "database": "test_database",
                "dbHost": "old-host.example.com",
                "dbHostRead": "old-host-read.example.com",
                "subdomain": "sub1",
            },
            {
                "companyID": 456,
                "database": "test_database",
                "dbHost": "old-host.example.com",
                "dbHostRead": "old-host-read.example.com",
                "subdomain": "sub2",
            },
        ]
        # Return tracking after create
        mock_tracking = MagicMock(spec=OverlordTracking)
        manager._tracking_repo.get.side_effect = [None, mock_tracking]
        
        result = manager.claim("test_database", "test-job-id", "user123")
        
        # Verify tracking was created with backup
        manager._tracking_repo.create.assert_called_once()
        call_kwargs = manager._tracking_repo.create.call_args.kwargs
        assert call_kwargs["row_existed_before"] is True
        assert call_kwargs["previous_dbhost"] == "old-host.example.com"
        assert call_kwargs["previous_dbhost_read"] == "old-host-read.example.com"
        assert call_kwargs["company_id"] == 123
        # Full snapshot stores all companies
        assert "companies" in call_kwargs["previous_snapshot"]
        assert len(call_kwargs["previous_snapshot"]["companies"]) == 2

    def test_claim_returns_existing_if_same_job(self, manager: OverlordManager) -> None:
        """Claim returns existing tracking if same job already claimed."""
        existing_tracking = MagicMock(spec=OverlordTracking)
        existing_tracking.job_id = "test-job-id"
        existing_tracking.status = OverlordTrackingStatus.CLAIMED
        manager._tracking_repo.get.return_value = existing_tracking
        
        result = manager.claim("test_database", "test-job-id", "user123")
        
        assert result == existing_tracking
        manager._tracking_repo.create.assert_not_called()

    def test_claim_fails_if_different_job_claimed(self, manager: OverlordManager) -> None:
        """Claim fails if database already claimed by different job."""
        existing_tracking = MagicMock(spec=OverlordTracking)
        existing_tracking.job_id = "other-job-id"
        existing_tracking.status = OverlordTrackingStatus.CLAIMED
        manager._tracking_repo.get.return_value = existing_tracking
        
        with pytest.raises(OverlordAlreadyClaimedError, match="already claimed"):
            manager.claim("test_database", "test-job-id", "user123")

    def test_claim_fails_if_disabled(self, manager: OverlordManager) -> None:
        """Claim fails if overlord integration is disabled."""
        manager._overlord_conn = None
        
        with pytest.raises(OverlordOwnershipError, match="disabled"):
            manager.claim("test_database", "test-job-id", "user123")


# =============================================================================
# Test: sync
# =============================================================================


class TestSync:
    """Tests for sync method."""

    def test_sync_creates_new_row(self, manager: OverlordManager) -> None:
        """Sync creates new overlord row when none exists."""
        # Active claim exists
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.CLAIMED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        # No existing overlord row
        manager._overlord_repo.get_by_database.return_value = None
        manager._overlord_repo.insert.return_value = 999
        
        result = manager.sync("test_database", "test-job-id", {
            "dbHost": "new-host.example.com",
        })
        
        assert result is True
        manager._overlord_repo.insert.assert_called_once()
        manager._tracking_repo.update_synced.assert_called_once()

    def test_sync_updates_existing_row(self, manager: OverlordManager) -> None:
        """Sync updates existing overlord row."""
        # Active claim exists
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        # Existing overlord row
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.company_id = 123
        manager._overlord_repo.get_by_database.return_value = mock_company
        
        result = manager.sync("test_database", "test-job-id", {
            "dbHost": "updated-host.example.com",
        })
        
        assert result is True
        manager._overlord_repo.update.assert_called_once()
        manager._overlord_repo.insert.assert_not_called()

    def test_sync_fails_without_claim(self, manager: OverlordManager) -> None:
        """Sync fails when no active claim exists."""
        manager._tracking_repo.get.return_value = None
        
        with pytest.raises(OverlordOwnershipError, match="No active claim"):
            manager.sync("test_database", "test-job-id", {"dbHost": "x"})

    def test_sync_fails_wrong_job(self, manager: OverlordManager) -> None:
        """Sync fails when claim is owned by different job."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "other-job-id"
        mock_tracking.status = OverlordTrackingStatus.CLAIMED
        manager._tracking_repo.get.return_value = mock_tracking
        
        with pytest.raises(OverlordOwnershipError, match="owned by job"):
            manager.sync("test_database", "test-job-id", {"dbHost": "x"})


# =============================================================================
# Test: release
# =============================================================================


class TestRelease:
    """Tests for release method."""

    def test_release_restore_success(self, manager: OverlordManager) -> None:
        """Release with RESTORE action restores routing-only fields from snapshot."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.previous_dbhost = "original-host.example.com"
        mock_tracking.previous_dbhost_read = "original-host-read.example.com"
        mock_tracking.current_dbhost = "staging-host.example.com"
        mock_tracking.current_subdomain = None
        # Multi-company snapshot format
        mock_tracking.previous_snapshot = {
            "companies": [
                {
                    "dbHost": "original-host.example.com",
                    "dbHostRead": "original-host-read.example.com",
                    "subdomain": "original-subdomain",
                    "name": "Original Company Name",
                },
                {
                    "dbHost": "original-host.example.com",
                    "dbHostRead": "original-host-read.example.com",
                    "subdomain": "second-subdomain",
                    "name": "Second Company",
                },
            ]
        }
        manager._tracking_repo.get.return_value = mock_tracking
        manager._overlord_repo.update.return_value = True
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.RESTORE)
        
        assert result.success is True
        assert result.action_taken == ReleaseAction.RESTORE
        assert "Restored" in result.message
        # Verify ONLY routing fields are restored (not subdomain/name)
        call_args = manager._overlord_repo.update.call_args
        update_data = call_args[0][1]
        assert update_data["dbHost"] == "original-host.example.com"
        assert update_data["dbHostRead"] == "original-host-read.example.com"
        assert "subdomain" not in update_data
        assert "name" not in update_data
        manager._tracking_repo.update_released.assert_called_once()

    def test_release_restore_fails_no_previous(self, manager: OverlordManager) -> None:
        """Release with RESTORE fails when no previous values."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = False
        mock_tracking.previous_dbhost = None
        mock_tracking.current_dbhost = "staging-host.example.com"
        mock_tracking.current_subdomain = None
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Mock overlord row exists (for state verification)
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "staging-host.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.RESTORE)
        
        assert result.success is False
        assert "Cannot restore" in result.message
        # Tracking should still be marked released
        manager._tracking_repo.update_released.assert_called_once()

    def test_release_clear_success(self, manager: OverlordManager) -> None:
        """Release with CLEAR action clears host fields."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.current_dbhost = "staging-host.example.com"
        mock_tracking.current_subdomain = None
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Mock overlord row exists (for state verification)
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "staging-host.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company
        manager._overlord_repo.update.return_value = True
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.CLEAR)
        
        assert result.success is True
        assert result.action_taken == ReleaseAction.CLEAR
        # Verify empty strings were set
        call_args = manager._overlord_repo.update.call_args
        assert call_args[0][1]["dbHost"] == ""
        assert call_args[0][1]["dbHostRead"] == ""

    def test_release_delete_success(self, manager: OverlordManager) -> None:
        """Release with DELETE action deletes the row."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = False
        mock_tracking.current_dbhost = "staging-host.example.com"
        mock_tracking.current_subdomain = None
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Mock overlord row matches expected host
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "staging-host.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company
        manager._overlord_repo.delete.return_value = True
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.DELETE)
        
        assert result.success is True
        assert result.action_taken == ReleaseAction.DELETE
        manager._overlord_repo.delete.assert_called_once_with("test_database")

    def test_release_delete_safety_check_fails(self, manager: OverlordManager) -> None:
        """Release with DELETE fails if dbHost was modified externally."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = False
        mock_tracking.current_dbhost = "staging-host.example.com"
        mock_tracking.current_subdomain = None
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Mock overlord row has DIFFERENT host (external modification)
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "different-host.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company
        
        with pytest.raises(OverlordSafetyError, match="dbHost mismatch"):
            manager.release("test_database", "test-job-id", ReleaseAction.DELETE)

    def test_release_no_active_claim(self, manager: OverlordManager) -> None:
        """Release succeeds (no-op) when no active claim."""
        manager._tracking_repo.get.return_value = None
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.RESTORE)
        
        assert result.success is True
        assert "No active claim" in result.message

    # =========================================================================
    # Edge Case Tests: External Changes to overlord.companies
    # =========================================================================
    
    def test_release_restore_when_row_deleted_externally(self, manager: OverlordManager) -> None:
        """Release RESTORE fails gracefully when row deleted externally."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.previous_dbhost = "original.example.com"
        mock_tracking.previous_dbhost_read = "original-read.example.com"
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = None
        mock_tracking.previous_snapshot = {
            "companies": [
                {
                    "dbHost": "original.example.com",
                    "dbHostRead": "original-read.example.com",
                    "subdomain": "original-subdomain",
                },
            ]
        }
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Row was deleted externally - get_by_database returns None
        manager._overlord_repo.get_by_database.return_value = None
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.RESTORE)
        
        # RESTORE should fail - can't restore a deleted row
        assert result.success is False
        assert result.external_change_detected is True
        assert "deleted externally" in result.message.lower()
        # But tracking should still be marked released
        manager._tracking_repo.update_released.assert_called_once()

    def test_release_clear_when_row_deleted_externally(self, manager: OverlordManager) -> None:
        """Release CLEAR fails gracefully when row deleted externally."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = None
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Row was deleted externally
        manager._overlord_repo.get_by_database.return_value = None
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.CLEAR)
        
        # CLEAR should fail - can't clear a deleted row
        assert result.success is False
        assert result.external_change_detected is True
        # But tracking should still be marked released
        manager._tracking_repo.update_released.assert_called_once()

    def test_release_delete_when_row_deleted_externally(self, manager: OverlordManager) -> None:
        """Release DELETE succeeds (no-op) when row already deleted externally."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = False  # We created it
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = None
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Row was already deleted externally
        manager._overlord_repo.get_by_database.return_value = None
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.DELETE)
        
        # DELETE should succeed - row already gone, which is what we wanted
        assert result.success is True
        assert result.external_change_detected is True
        # delete() should NOT be called since row doesn't exist
        manager._overlord_repo.delete.assert_not_called()

    def test_release_restore_when_dbhost_modified_externally(self, manager: OverlordManager) -> None:
        """Release RESTORE proceeds with warning when dbHost modified externally."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.previous_dbhost = "original.example.com"
        mock_tracking.previous_dbhost_read = "original-read.example.com"
        mock_tracking.current_dbhost = "staging.example.com"  # We set this
        mock_tracking.current_subdomain = None
        mock_tracking.previous_snapshot = {
            "companies": [
                {
                    "dbHost": "original.example.com",
                    "dbHostRead": "original-read.example.com",
                    "subdomain": "original-subdomain",
                },
            ]
        }
        manager._tracking_repo.get.return_value = mock_tracking
        
        # dbHost was changed externally to something else
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "external-change.example.com"  # Different!
        manager._overlord_repo.get_by_database.return_value = mock_company
        manager._overlord_repo.update.return_value = True
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.RESTORE)
        
        # Should succeed but flag external change
        assert result.success is True
        assert result.external_change_detected is True
        # Should restore routing-only fields (not subdomain)
        call_args = manager._overlord_repo.update.call_args
        update_data = call_args[0][1]
        assert update_data["dbHost"] == "original.example.com"
        assert "subdomain" not in update_data

    def test_release_update_fails_race_condition(self, manager: OverlordManager) -> None:
        """Release RESTORE fails when UPDATE returns 0 rows (race condition)."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.previous_dbhost = "original.example.com"
        mock_tracking.previous_dbhost_read = "original-read.example.com"
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = None
        mock_tracking.previous_snapshot = {
            "companies": [
                {
                    "dbHost": "original.example.com",
                    "dbHostRead": "original-read.example.com",
                    "subdomain": "original-subdomain",
                },
            ]
        }
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Row exists when we check
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "staging.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company
        # But UPDATE returns False (0 rows affected - row disappeared during operation)
        manager._overlord_repo.update.return_value = False
        
        result = manager.release("test_database", "test-job-id", ReleaseAction.RESTORE)
        
        # Should fail due to race condition
        assert result.success is False
        assert "deleted during operation" in result.message.lower()


# =============================================================================
# Test: cleanup_on_job_delete
# =============================================================================


class TestCleanupOnJobDelete:
    """Tests for cleanup_on_job_delete method."""

    def test_cleanup_deletes_if_created_by_us(self, manager: OverlordManager) -> None:
        """Cleanup deletes row if it was created by pullDB."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = False  # We created it
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = None
        manager._tracking_repo.get_by_job_id.return_value = mock_tracking
        manager._tracking_repo.get.return_value = mock_tracking
        
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "staging.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company
        manager._overlord_repo.delete.return_value = True
        
        result = manager.cleanup_on_job_delete("test-job-id")
        
        assert result is not None
        assert result.action_taken == ReleaseAction.DELETE

    def test_cleanup_restores_if_existed_before(self, manager: OverlordManager) -> None:
        """Cleanup restores routing-only fields if row existed before."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True  # Row existed
        mock_tracking.previous_dbhost = "original.example.com"
        mock_tracking.previous_dbhost_read = "original-read.example.com"
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = None
        mock_tracking.previous_snapshot = {
            "companies": [
                {
                    "dbHost": "original.example.com",
                    "dbHostRead": "original-read.example.com",
                    "subdomain": "original-subdomain",
                    "name": "Original Company Name",
                },
            ]
        }
        manager._tracking_repo.get_by_job_id.return_value = mock_tracking
        manager._tracking_repo.get.return_value = mock_tracking
        
        # Mock overlord row exists (for state verification)
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "staging.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company
        manager._overlord_repo.update.return_value = True
        
        result = manager.cleanup_on_job_delete("test-job-id")
        
        assert result is not None
        assert result.action_taken == ReleaseAction.RESTORE
        # Verify only routing fields are restored (not subdomain/name)
        call_args = manager._overlord_repo.update.call_args
        update_data = call_args[0][1]
        assert update_data["dbHost"] == "original.example.com"
        assert update_data["dbHostRead"] == "original-read.example.com"
        assert "subdomain" not in update_data
        assert "name" not in update_data

    def test_cleanup_returns_none_if_no_tracking(self, manager: OverlordManager) -> None:
        """Cleanup returns None if no tracking record exists."""
        manager._tracking_repo.get_by_job_id.return_value = None
        
        result = manager.cleanup_on_job_delete("test-job-id")
        
        assert result is None


# =============================================================================
# Test: Multi-Company Operations
# =============================================================================


class TestMultiCompany:
    """Tests for multi-company support (get_all, add, remove, sync by ID)."""

    def test_get_all_companies(self, manager: OverlordManager) -> None:
        """get_all_companies returns list from repository."""
        manager._overlord_repo.get_all_by_database.return_value = [
            {"companyID": 1, "database": "test_db", "subdomain": "sub1"},
            {"companyID": 2, "database": "test_db", "subdomain": "sub2"},
        ]

        result = manager.get_all_companies("test_db")

        assert len(result) == 2
        assert result[0]["companyID"] == 1
        assert result[1]["subdomain"] == "sub2"
        manager._overlord_repo.get_all_by_database.assert_called_once_with("test_db")

    def test_get_all_companies_empty(self, manager: OverlordManager) -> None:
        """get_all_companies returns empty list when no rows."""
        manager._overlord_repo.get_all_by_database.return_value = []

        result = manager.get_all_companies("test_db")

        assert result == []

    def test_add_company_enforces_claim(self, manager: OverlordManager) -> None:
        """add_company raises OwnershipError without active claim."""
        manager._tracking_repo.get.return_value = None

        with pytest.raises(OverlordOwnershipError, match="No active claim"):
            manager.add_company("test_db", "test-job-id", {"subdomain": "new"})

    def test_add_company_forces_database_field(self, manager: OverlordManager) -> None:
        """add_company always sets data['database'] to database_name."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        manager._overlord_repo.insert.return_value = 999

        manager.add_company("test_db", "test-job-id", {"subdomain": "new", "database": "hacked"})

        call_args = manager._overlord_repo.insert.call_args[0][0]
        assert call_args["database"] == "test_db"  # forced, not "hacked"

    def test_add_company_wrong_job(self, manager: OverlordManager) -> None:
        """add_company raises OwnershipError when claim is from different job."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "other-job-id"
        mock_tracking.status = OverlordTrackingStatus.CLAIMED
        manager._tracking_repo.get.return_value = mock_tracking

        with pytest.raises(OverlordOwnershipError, match="owned by job"):
            manager.add_company("test_db", "test-job-id", {"subdomain": "new"})

    def test_remove_company_success(self, manager: OverlordManager) -> None:
        """remove_company deletes the correct row."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        manager._overlord_repo.get_by_id.return_value = {"database": "test_db", "companyID": 5}
        manager._overlord_repo.delete_by_id.return_value = True

        result = manager.remove_company("test_db", "test-job-id", 5)

        assert result is True
        manager._overlord_repo.delete_by_id.assert_called_once_with(5)

    def test_remove_company_cross_database_check(self, manager: OverlordManager) -> None:
        """remove_company rejects if company belongs to different database."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        # Row belongs to a different database
        manager._overlord_repo.get_by_id.return_value = {"database": "other_db", "companyID": 5}

        with pytest.raises(OverlordSafetyError, match="belongs to"):
            manager.remove_company("test_db", "test-job-id", 5)

    def test_remove_company_not_found(self, manager: OverlordManager) -> None:
        """remove_company returns False when company doesn't exist."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        manager._overlord_repo.get_by_id.return_value = None

        result = manager.remove_company("test_db", "test-job-id", 999)

        assert result is False

    def test_sync_with_company_id(self, manager: OverlordManager) -> None:
        """sync with company_id uses update_by_id (PK-safe path)."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        # Existing company with that ID
        manager._overlord_repo.get_by_id.return_value = {"companyID": 42, "database": "test_db"}

        result = manager.sync(
            "test_db", "test-job-id",
            {"dbHost": "new-host.example.com"},
            company_id=42,
        )

        assert result is True
        manager._overlord_repo.update_by_id.assert_called_once()
        manager._overlord_repo.update.assert_not_called()
        manager._overlord_repo.insert.assert_not_called()

    def test_sync_with_company_id_not_found_inserts(self, manager: OverlordManager) -> None:
        """sync with company_id inserts when PK doesn't exist."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.created_by = "user123"
        manager._tracking_repo.get.return_value = mock_tracking
        manager._overlord_repo.get_by_id.return_value = None
        manager._overlord_repo.insert.return_value = 100

        result = manager.sync(
            "test_db", "test-job-id",
            {"dbHost": "new-host.example.com"},
            company_id=999,
        )

        assert result is True
        manager._overlord_repo.insert.assert_called_once()
        manager._overlord_repo.update_by_id.assert_not_called()

    def test_release_restore_legacy_single_row_snapshot(self, manager: OverlordManager) -> None:
        """Release restore works with legacy single-row snapshot format."""
        mock_tracking = MagicMock(spec=OverlordTracking)
        mock_tracking.job_id = "test-job-id"
        mock_tracking.database_name = "test_database"
        mock_tracking.created_by = "user123"
        mock_tracking.status = OverlordTrackingStatus.SYNCED
        mock_tracking.row_existed_before = True
        mock_tracking.previous_dbhost = "original.example.com"
        mock_tracking.previous_dbhost_read = "original-read.example.com"
        mock_tracking.current_dbhost = "staging.example.com"
        mock_tracking.current_subdomain = None
        # Legacy format: single row dict (no "companies" key)
        mock_tracking.previous_snapshot = {
            "dbHost": "original.example.com",
            "dbHostRead": "original-read.example.com",
            "subdomain": "legacy-subdomain",
        }
        manager._tracking_repo.get.return_value = mock_tracking
        manager._overlord_repo.update.return_value = True

        # Mock overlord row exists
        mock_company = MagicMock(spec=OverlordCompany)
        mock_company.db_host = "staging.example.com"
        manager._overlord_repo.get_by_database.return_value = mock_company

        result = manager.release("test_database", "test-job-id", ReleaseAction.RESTORE)

        assert result.success is True
        call_args = manager._overlord_repo.update.call_args
        update_data = call_args[0][1]
        assert update_data["dbHost"] == "original.example.com"
        assert update_data["dbHostRead"] == "original-read.example.com"
        assert "subdomain" not in update_data
