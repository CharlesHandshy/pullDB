"""Tests for secret rotation service.

Tests the atomic credential rotation workflow including:
- Password generation
- MySQL connection testing
- ALTER USER execution
- AWS Secrets Manager updates
- Rollback scenarios
"""

from __future__ import annotations

"""HCA Layer: tests."""

from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.secret_rotation import (
    DEFAULT_PASSWORD_LENGTH,
    PASSWORD_ALPHABET,
    RotationResult,
    _generate_secure_password,
    _mask_password,
    _test_mysql_connection,
    rotate_host_secret,
)


class TestPasswordGeneration:
    """Test secure password generation."""

    def test_generate_default_length(self) -> None:
        """Test password generation with default length."""
        password = _generate_secure_password()
        assert len(password) == DEFAULT_PASSWORD_LENGTH
        assert all(c in PASSWORD_ALPHABET for c in password)

    def test_generate_custom_length(self) -> None:
        """Test password generation with custom length."""
        password = _generate_secure_password(48)
        assert len(password) == 48

    def test_generate_unique(self) -> None:
        """Test that generated passwords are unique."""
        passwords = [_generate_secure_password() for _ in range(100)]
        # All should be unique
        assert len(set(passwords)) == 100


class TestPasswordMasking:
    """Test password masking for logging."""

    def test_mask_normal_password(self) -> None:
        """Test masking a normal length password."""
        result = _mask_password("secretpassword123")
        assert result == "se*************23"
        assert "secretpassword123" not in result

    def test_mask_short_password(self) -> None:
        """Test masking a short password."""
        result = _mask_password("abc")
        assert result == "***"

    def test_mask_empty_password(self) -> None:
        """Test masking empty password."""
        result = _mask_password("")
        assert result == "***"

    def test_mask_none_password(self) -> None:
        """Test masking None password."""
        result = _mask_password(None)  # type: ignore
        assert result == "***"


class TestRotationResult:
    """Test RotationResult dataclass."""

    def test_success_result(self) -> None:
        """Test creating a success result."""
        result = RotationResult(
            success=True,
            message="Successfully rotated",
            timing={"total": 1.5},
        )
        assert result.success is True
        assert result.error is None
        assert result.phase is None

    def test_failure_result(self) -> None:
        """Test creating a failure result."""
        result = RotationResult(
            success=False,
            message="Rotation failed",
            error="Connection refused",
            phase="validate_current",
            suggestions=["Check network", "Verify host"],
        )
        assert result.success is False
        assert result.error == "Connection refused"
        assert result.phase == "validate_current"
        assert len(result.suggestions) == 2

    def test_to_dict(self) -> None:
        """Test converting result to dictionary."""
        result = RotationResult(
            success=True,
            message="Done",
            timing={"total": 1.0},
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["message"] == "Done"
        assert d["timing"]["total"] == 1.0


class TestMySQLConnectionTest:
    """Test MySQL connection testing function."""

    @patch("pulldb.worker.secret_rotation.mysql.connector.connect")
    def test_connection_success(self, mock_connect: MagicMock) -> None:
        """Test successful connection."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        success, error = _test_mysql_connection(
            host="localhost",
            port=3306,
            username="test",
            password="pass",
        )

        assert success is True
        assert error is None
        mock_conn.close.assert_called_once()

    @patch("pulldb.worker.secret_rotation.mysql.connector.connect")
    def test_connection_with_alter_user_check(self, mock_connect: MagicMock) -> None:
        """Test connection with ALTER USER privilege check."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("GRANT ALL PRIVILEGES ON *.* TO 'user'@'%'",)]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        success, error = _test_mysql_connection(
            host="localhost",
            port=3306,
            username="test",
            password="pass",
            check_alter_user=True,
        )

        assert success is True
        assert error is None
        mock_cursor.execute.assert_called_with("SHOW GRANTS FOR CURRENT_USER()")

    @patch("pulldb.worker.secret_rotation.mysql.connector.connect")
    def test_connection_lacks_privilege(self, mock_connect: MagicMock) -> None:
        """Test connection with insufficient privileges."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Grants without ALTER USER capability
        mock_cursor.fetchall.return_value = [("GRANT SELECT ON *.* TO 'user'@'%'",)]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        success, error = _test_mysql_connection(
            host="localhost",
            port=3306,
            username="test",
            password="pass",
            check_alter_user=True,
        )

        assert success is False
        assert "privilege" in error.lower()


class TestRotateHostSecret:
    """Test the main rotation function."""

    def test_invalid_credential_ref(self) -> None:
        """Test with invalid credential reference."""
        result = rotate_host_secret(
            host_id="host-123",
            hostname="test.example.com",
            credential_ref="invalid-ref",
        )

        assert result.success is False
        assert result.phase == "validation"
        assert "aws-secretsmanager:" in result.error

    def test_empty_credential_ref(self) -> None:
        """Test with empty credential reference."""
        result = rotate_host_secret(
            host_id="host-123",
            hostname="test.example.com",
            credential_ref="",
        )

        assert result.success is False
        assert result.phase == "validation"

    @patch("pulldb.worker.secret_rotation.CredentialResolver")
    def test_aws_fetch_failure(self, mock_resolver_class: MagicMock) -> None:
        """Test handling AWS fetch failure."""
        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = Exception("AWS connection failed")
        mock_resolver_class.return_value = mock_resolver

        result = rotate_host_secret(
            host_id="host-123",
            hostname="test.example.com",
            credential_ref="aws-secretsmanager:/pulldb/test",
        )

        assert result.success is False
        assert result.phase == "fetch_credentials"
        assert "AWS" in result.message

    @patch("pulldb.worker.secret_rotation.safe_upsert_single_secret")
    @patch("pulldb.worker.secret_rotation._test_mysql_connection")
    @patch("pulldb.worker.secret_rotation._alter_mysql_password")
    @patch("pulldb.worker.secret_rotation.CredentialResolver")
    def test_full_rotation_success(
        self,
        mock_resolver_class: MagicMock,
        mock_alter: MagicMock,
        mock_test: MagicMock,
        mock_upsert: MagicMock,
    ) -> None:
        """Test successful full rotation."""
        # Setup mocks - initial credentials
        mock_creds_initial = MagicMock()
        mock_creds_initial.host = "localhost"
        mock_creds_initial.port = 3306
        mock_creds_initial.username = "testuser"
        mock_creds_initial.password = "oldpass"

        # Setup mocks - after rotation credentials (with new password)
        mock_creds_final = MagicMock()
        mock_creds_final.host = "localhost"
        mock_creds_final.port = 3306
        mock_creds_final.username = "testuser"
        mock_creds_final.password = "newpass123"  # Same as provided new_password

        mock_resolver = MagicMock()
        # First call returns initial creds, second call (verification) returns new creds
        mock_resolver.resolve.side_effect = [mock_creds_initial, mock_creds_final]
        mock_resolver_class.return_value = mock_resolver

        mock_test.return_value = (True, None)
        mock_alter.return_value = (True, None)

        mock_upsert_result = MagicMock()
        mock_upsert_result.success = True
        mock_upsert.return_value = mock_upsert_result

        # Execute
        result = rotate_host_secret(
            host_id="host-123",
            hostname="test.example.com",
            credential_ref="aws-secretsmanager:/pulldb/test",
            new_password="newpass123",
        )

        # Verify
        assert result.success is True
        assert "Successfully" in result.message
        assert "total" in result.timing

    @patch("pulldb.worker.secret_rotation.safe_upsert_single_secret")
    @patch("pulldb.worker.secret_rotation._test_mysql_connection")
    @patch("pulldb.worker.secret_rotation._alter_mysql_password")
    @patch("pulldb.worker.secret_rotation.CredentialResolver")
    def test_mysql_update_failure(
        self,
        mock_resolver_class: MagicMock,
        mock_alter: MagicMock,
        mock_test: MagicMock,
        mock_upsert: MagicMock,
    ) -> None:
        """Test MySQL update failure (before AWS update)."""
        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "testuser"
        mock_creds.password = "oldpass"

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_creds
        mock_resolver_class.return_value = mock_resolver

        mock_test.return_value = (True, None)
        mock_alter.return_value = (False, "Access denied")

        result = rotate_host_secret(
            host_id="host-123",
            hostname="test.example.com",
            credential_ref="aws-secretsmanager:/pulldb/test",
        )

        assert result.success is False
        assert result.phase == "mysql_update"
        # AWS should NOT be called
        mock_upsert.assert_not_called()

    @patch("pulldb.worker.secret_rotation.safe_upsert_single_secret")
    @patch("pulldb.worker.secret_rotation._test_mysql_connection")
    @patch("pulldb.worker.secret_rotation._alter_mysql_password")
    @patch("pulldb.worker.secret_rotation.CredentialResolver")
    def test_aws_update_failure_manual_fix(
        self,
        mock_resolver_class: MagicMock,
        mock_alter: MagicMock,
        mock_test: MagicMock,
        mock_upsert: MagicMock,
    ) -> None:
        """Test AWS update failure after MySQL success (requires manual fix)."""
        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "testuser"
        mock_creds.password = "oldpass"

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_creds
        mock_resolver_class.return_value = mock_resolver

        mock_test.return_value = (True, None)
        mock_alter.return_value = (True, None)

        mock_upsert_result = MagicMock()
        mock_upsert_result.success = False
        mock_upsert_result.error = "AWS permission denied"
        mock_upsert.return_value = mock_upsert_result

        result = rotate_host_secret(
            host_id="host-123",
            hostname="test.example.com",
            credential_ref="aws-secretsmanager:/pulldb/test",
        )

        assert result.success is False
        assert result.phase == "aws_update"
        assert result.manual_fix_required is True
        assert result.manual_fix_instructions is not None
        assert "CRITICAL" in result.message
