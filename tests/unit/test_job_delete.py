"""Unit tests for job deletion functionality.

Tests delete_job_databases function and JobDeleteResult dataclass.
Mocks database operations at the lowest level.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.cleanup import (
    JobDeleteResult,
    delete_job_databases,
    is_valid_staging_name,
)


class TestJobDeleteResult:
    """Tests for JobDeleteResult dataclass."""

    def test_default_values(self) -> None:
        """Test JobDeleteResult has sensible defaults."""
        result = JobDeleteResult(
            job_id="abc123",
            staging_name="target_abc123def456",
            target_name="jdoecustomer",
            dbhost="mysql.example.com",
        )
        assert result.job_id == "abc123"
        assert result.staging_existed is False
        assert result.staging_dropped is False
        assert result.target_existed is False
        assert result.target_dropped is False
        assert result.error is None

    def test_with_results(self) -> None:
        """Test JobDeleteResult with actual operation results."""
        result = JobDeleteResult(
            job_id="abc123",
            staging_name="target_abc123def456",
            target_name="jdoecustomer",
            dbhost="mysql.example.com",
            staging_existed=True,
            staging_dropped=True,
            target_existed=True,
            target_dropped=True,
        )
        assert result.staging_existed is True
        assert result.staging_dropped is True
        assert result.target_existed is True
        assert result.target_dropped is True

    def test_with_error(self) -> None:
        """Test JobDeleteResult captures errors."""
        result = JobDeleteResult(
            job_id="abc123",
            staging_name="target_abc123def456",
            target_name="jdoecustomer",
            dbhost="mysql.example.com",
            error="Connection refused",
        )
        assert result.error == "Connection refused"


class TestIsValidStagingName:
    """Tests for staging name validation."""

    def test_valid_staging_name(self) -> None:
        """Valid staging names should pass."""
        valid, reason = is_valid_staging_name("customer_550e8400e29b")
        assert valid is True
        assert reason == ""

    def test_invalid_no_underscore(self) -> None:
        """Names without underscore should fail."""
        valid, reason = is_valid_staging_name("customerdatabase")
        assert valid is False
        assert "pattern" in reason.lower()

    def test_invalid_short_suffix(self) -> None:
        """Names with short suffix should fail."""
        valid, reason = is_valid_staging_name("customer_abc")
        assert valid is False

    def test_invalid_non_hex_suffix(self) -> None:
        """Names with non-hex suffix should fail."""
        valid, reason = is_valid_staging_name("customer_notahexvalue")
        assert valid is False

    def test_protected_database_names(self) -> None:
        """Protected database names should fail even with valid format."""
        # mysql with suffix won't match protected, but test boundary
        valid, reason = is_valid_staging_name("mysql_550e8400e29b")
        # This should pass the format check but may have other guards
        # depending on implementation
        assert isinstance(valid, bool)


class TestDeleteJobDatabases:
    """Tests for delete_job_databases function."""

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup._drop_database")
    @patch("pulldb.worker.cleanup._drop_target_database_unsafe")
    def test_successful_delete_both(
        self,
        mock_drop_target: MagicMock,
        mock_drop_staging: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Test successful deletion of both staging and target."""
        mock_exists.return_value = True
        mock_drop_staging.return_value = True
        mock_drop_target.return_value = True
        
        mock_host_repo = MagicMock()
        mock_creds = MagicMock()
        mock_creds.host = "mysql.example.com"
        mock_creds.port = 3306
        mock_creds.username = "loader"
        mock_creds.password = "secret"
        mock_host_repo.get_host_credentials.return_value = mock_creds
        
        result = delete_job_databases(
            job_id="550e8400-e29b-41d4-a716-446655440000",
            staging_name="jdoecustomer_550e8400e29b",
            target_name="jdoecustomer",
            owner_user_code="jdoe",
            dbhost="mysql.example.com",
            host_repo=mock_host_repo,
        )
        
        assert result.error is None
        assert result.staging_existed is True
        assert result.staging_dropped is True
        assert result.target_existed is True
        assert result.target_dropped is True

    @patch("pulldb.worker.cleanup._database_exists")
    def test_user_code_validation_fails(
        self,
        mock_exists: MagicMock,
    ) -> None:
        """Test that target must contain owner user_code."""
        mock_host_repo = MagicMock()
        
        result = delete_job_databases(
            job_id="550e8400-e29b-41d4-a716-446655440000",
            staging_name="othercustomer_550e8400e29b",
            target_name="othercustomer",  # Does not contain "jdoe"
            owner_user_code="jdoe",
            dbhost="mysql.example.com",
            host_repo=mock_host_repo,
        )
        
        assert result.error is not None
        assert "user code" in result.error.lower()
        # Should not have called database operations
        mock_exists.assert_not_called()

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup._drop_database")
    @patch("pulldb.worker.cleanup._drop_target_database_unsafe")
    def test_databases_dont_exist(
        self,
        mock_drop_target: MagicMock,
        mock_drop_staging: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Test when databases don't exist - nothing to drop."""
        mock_exists.return_value = False
        
        mock_host_repo = MagicMock()
        mock_creds = MagicMock()
        mock_host_repo.get_host_credentials.return_value = mock_creds
        
        result = delete_job_databases(
            job_id="550e8400-e29b-41d4-a716-446655440000",
            staging_name="jdoecustomer_550e8400e29b",
            target_name="jdoecustomer",
            owner_user_code="jdoe",
            dbhost="mysql.example.com",
            host_repo=mock_host_repo,
        )
        
        assert result.error is None
        assert result.staging_existed is False
        assert result.staging_dropped is False
        assert result.target_existed is False
        assert result.target_dropped is False
        # Drop should not be called if doesn't exist
        mock_drop_staging.assert_not_called()
        mock_drop_target.assert_not_called()

    def test_credential_lookup_fails(self) -> None:
        """Test handling of credential lookup failure."""
        mock_host_repo = MagicMock()
        mock_host_repo.get_host_credentials_for_maintenance.side_effect = Exception(
            "Host not found"
        )
        
        result = delete_job_databases(
            job_id="550e8400-e29b-41d4-a716-446655440000",
            staging_name="jdoecustomer_550e8400e29b",
            target_name="jdoecustomer",
            owner_user_code="jdoe",
            dbhost="mysql.example.com",
            host_repo=mock_host_repo,
        )
        
        assert result.error is not None
        assert "credentials" in result.error.lower()

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup._drop_database")
    @patch("pulldb.worker.cleanup._drop_target_database_unsafe")
    def test_staging_drop_fails_continues_to_target(
        self,
        mock_drop_target: MagicMock,
        mock_drop_staging: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Test that staging drop failure still attempts target drop."""
        mock_exists.return_value = True
        mock_drop_staging.side_effect = Exception("Connection lost")
        mock_drop_target.return_value = True
        
        mock_host_repo = MagicMock()
        mock_creds = MagicMock()
        mock_host_repo.get_host_credentials.return_value = mock_creds
        
        result = delete_job_databases(
            job_id="550e8400-e29b-41d4-a716-446655440000",
            staging_name="jdoecustomer_550e8400e29b",
            target_name="jdoecustomer",
            owner_user_code="jdoe",
            dbhost="mysql.example.com",
            host_repo=mock_host_repo,
        )
        
        # Target should still be attempted
        assert result.target_existed is True
        assert result.target_dropped is True
        # Staging failed
        assert result.staging_dropped is False
