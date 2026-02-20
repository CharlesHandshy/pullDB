"""Unit tests for HostProvisioningService.

Tests the provisioning service in isolation using mock dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pulldb.domain.models import DBHost
from pulldb.worker.provisioning import (
    ConnectionTestResult,
    DeleteHostResult,
    HostProvisioningService,
    ProvisioningResult,
    ProvisioningStep,
)


# =============================================================================
# Test Fixtures and Mocks
# =============================================================================


@dataclass
class MockProvisioningResult:
    """Mock result from mysql_provisioning.provision_host_full."""

    success: bool
    message: str
    error: str | None = None
    suggestions: list[str] | None = None
    data: dict[str, Any] | None = None


@dataclass
class MockSecretExistsResult:
    """Mock result from check_secret_exists."""

    exists: bool
    secret_data: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class MockSecretUpsertResult:
    """Mock result from safe_upsert_single_secret."""

    success: bool
    was_new: bool
    secret_path: str
    error: str | None = None


class MockHostRepository:
    """Mock host repository for testing."""

    def __init__(self) -> None:
        self.hosts: dict[str, DBHost] = {}
        self.add_host_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.delete_calls: list[str] = []

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        return self.hosts.get(hostname)

    def get_host_by_alias(self, alias: str) -> DBHost | None:
        for host in self.hosts.values():
            if host.host_alias == alias:
                return host
        return None

    def add_host(
        self,
        hostname: str,
        max_concurrent: int,
        credential_ref: str | None,
        host_id: str | None = None,
        host_alias: str | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        self.add_host_calls.append({
            "hostname": hostname,
            "max_concurrent": max_concurrent,
            "credential_ref": credential_ref,
            "host_id": host_id,
            "host_alias": host_alias,
            "max_active_jobs": max_active_jobs,
        })
        # Actually store it
        hid = host_id or "test-uuid"
        self.hosts[hostname] = DBHost(
            id=hid,
            hostname=hostname,
            credential_ref=credential_ref or "",
            max_running_jobs=max_concurrent,
            max_active_jobs=max_active_jobs or 10,
            enabled=True,
            created_at=datetime.now(),
            host_alias=host_alias,
        )

    def update_host_config(
        self,
        host_id: str,
        host_alias: str | None = None,
        credential_ref: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        self.update_calls.append({
            "host_id": host_id,
            "host_alias": host_alias,
            "credential_ref": credential_ref,
            "max_running_jobs": max_running_jobs,
            "max_active_jobs": max_active_jobs,
        })

    def delete_host(self, hostname: str) -> None:
        self.delete_calls.append(hostname)
        if hostname in self.hosts:
            del self.hosts[hostname]
        else:
            raise ValueError(f"Host not found: {hostname}")


class MockAuditRepository:
    """Mock audit repository for testing."""

    def __init__(self) -> None:
        self.log_calls: list[dict[str, Any]] = []

    def log_action(
        self,
        actor_user_id: str,
        action: str,
        target_user_id: str | None = None,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        self.log_calls.append({
            "actor_user_id": actor_user_id,
            "action": action,
            "target_user_id": target_user_id,
            "detail": detail,
            "context": context,
        })
        return "audit-log-id"


@pytest.fixture
def mock_host_repo() -> MockHostRepository:
    """Create a mock host repository."""
    return MockHostRepository()


@pytest.fixture
def mock_audit_repo() -> MockAuditRepository:
    """Create a mock audit repository."""
    return MockAuditRepository()


@pytest.fixture
def service(
    mock_host_repo: MockHostRepository, mock_audit_repo: MockAuditRepository
) -> HostProvisioningService:
    """Create a provisioning service with mock dependencies."""
    return HostProvisioningService(
        host_repo=mock_host_repo,
        audit_repo=mock_audit_repo,
        actor_user_id="test-actor-uuid",
    )


# =============================================================================
# Test: Input Validation
# =============================================================================


class TestProvisionHostValidation:
    """Test input validation for provision_host."""

    def test_empty_host_alias_fails(
        self, service: HostProvisioningService
    ) -> None:
        """Test that empty host_alias fails validation."""
        result = service.provision_host(
            host_alias="",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
        )
        assert not result.success
        assert "Host alias is required" in result.message

    def test_empty_mysql_host_fails(
        self, service: HostProvisioningService
    ) -> None:
        """Test that empty mysql_host fails validation."""
        result = service.provision_host(
            host_alias="test-host",
            mysql_host="",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
        )
        assert not result.success
        assert "MySQL host is required" in result.message

    def test_empty_credentials_fails(
        self, service: HostProvisioningService
    ) -> None:
        """Test that empty admin credentials fail validation."""
        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="",
            admin_password="password",
        )
        assert not result.success
        assert "Admin credentials are required" in result.message

    def test_invalid_max_running_jobs_fails(
        self, service: HostProvisioningService
    ) -> None:
        """Test that max_running_jobs < 1 fails validation."""
        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
            max_running_jobs=0,
        )
        assert not result.success
        assert "max_running_jobs must be at least 1" in result.message

    def test_negative_max_active_jobs_fails(
        self, service: HostProvisioningService
    ) -> None:
        """Test that negative max_active_jobs fails validation."""
        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
            max_active_jobs=-1,
        )
        assert not result.success
        assert "max_active_jobs cannot be negative" in result.message

    def test_running_exceeds_active_fails(
        self, service: HostProvisioningService
    ) -> None:
        """Test that max_running_jobs > max_active_jobs fails."""
        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
            max_running_jobs=5,
            max_active_jobs=3,
        )
        assert not result.success
        assert "max_running_jobs cannot exceed max_active_jobs" in result.message


# =============================================================================
# Test: Successful Provisioning
# =============================================================================


class TestProvisionHostSuccess:
    """Test successful provisioning scenarios."""

    @patch("pulldb.infra.secrets.check_secret_exists")
    @patch("pulldb.infra.secrets.safe_upsert_single_secret")
    @patch("pulldb.infra.mysql_provisioning.provision_host_full")
    @patch("pulldb.infra.secrets.generate_credential_ref")
    @patch("pulldb.infra.secrets.get_secret_path_from_alias")
    def test_new_host_provision_success(
        self,
        mock_get_path: MagicMock,
        mock_gen_ref: MagicMock,
        mock_provision: MagicMock,
        mock_upsert: MagicMock,
        mock_check: MagicMock,
        service: HostProvisioningService,
        mock_host_repo: MockHostRepository,
        mock_audit_repo: MockAuditRepository,
    ) -> None:
        """Test successful provisioning of a new host."""
        # Setup mocks
        mock_get_path.return_value = "/pulldb/mysql/dev-db-01"
        mock_gen_ref.return_value = "aws-secretsmanager:/pulldb/mysql/dev-db-01"
        mock_check.return_value = MockSecretExistsResult(exists=False)
        mock_provision.return_value = (
            MockProvisioningResult(
                success=True,
                message="All steps completed",
                data={
                    "loader_username": "pulldb_loader",
                    "loader_password": "generated-password",
                },
            ),
            {"user_created": True, "database_created": True},
        )
        mock_upsert.return_value = MockSecretUpsertResult(
            success=True,
            was_new=True,
            secret_path="/pulldb/mysql/dev-db-01",
        )

        # Execute
        result = service.provision_host(
            host_alias="dev-db-01",
            mysql_host="10.0.1.50",
            mysql_port=3306,
            admin_username="root",
            admin_password="admin-password",
            max_running_jobs=2,
            max_active_jobs=10,
        )

        # Verify result
        assert result.success
        assert result.host_id is not None
        assert result.message == "Host provisioned successfully"
        assert not result.rollback_performed

        # Verify steps
        assert result.steps is not None
        step_names = [s.name for s in result.steps]
        assert "Check Host" in step_names
        assert "Check Secret" in step_names
        assert "MySQL Setup" in step_names
        assert "AWS Secret" in step_names
        assert "Register Host" in step_names

        # Verify repository was called
        assert len(mock_host_repo.add_host_calls) == 1
        call = mock_host_repo.add_host_calls[0]
        assert call["hostname"] == "dev-db-01"
        assert call["max_concurrent"] == 2
        assert call["max_active_jobs"] == 10

        # Verify audit log
        assert len(mock_audit_repo.log_calls) == 1
        audit = mock_audit_repo.log_calls[0]
        assert audit["action"] == "host_provisioned"
        assert audit["actor_user_id"] == "test-actor-uuid"

    @patch("pulldb.infra.secrets.check_secret_exists")
    @patch("pulldb.infra.secrets.safe_upsert_single_secret")
    @patch("pulldb.infra.mysql_provisioning.provision_host_full")
    @patch("pulldb.infra.secrets.generate_credential_ref")
    @patch("pulldb.infra.secrets.get_secret_path_from_alias")
    def test_existing_host_update_success(
        self,
        mock_get_path: MagicMock,
        mock_gen_ref: MagicMock,
        mock_provision: MagicMock,
        mock_upsert: MagicMock,
        mock_check: MagicMock,
        service: HostProvisioningService,
        mock_host_repo: MockHostRepository,
        mock_audit_repo: MockAuditRepository,
    ) -> None:
        """Test updating an existing host."""
        # Pre-populate host
        mock_host_repo.hosts["existing-host"] = DBHost(
            id="existing-uuid",
            hostname="existing-host",
            credential_ref="aws-secretsmanager:/pulldb/mysql/existing-host",
            max_running_jobs=1,
            max_active_jobs=5,
            enabled=True,
            created_at=datetime.now(),
            host_alias="existing-host",
        )

        # Setup mocks
        mock_get_path.return_value = "/pulldb/mysql/existing-host"
        mock_gen_ref.return_value = "aws-secretsmanager:/pulldb/mysql/existing-host"
        mock_check.return_value = MockSecretExistsResult(exists=True)
        mock_provision.return_value = (
            MockProvisioningResult(
                success=True,
                message="All steps completed",
                data={
                    "loader_username": "pulldb_loader",
                    "loader_password": "new-password",
                },
            ),
            {"user_created": False, "database_created": False},
        )
        mock_upsert.return_value = MockSecretUpsertResult(
            success=True,
            was_new=False,
            secret_path="/pulldb/mysql/existing-host",
        )

        # Execute
        result = service.provision_host(
            host_alias="existing-host",
            mysql_host="10.0.1.60",
            mysql_port=3306,
            admin_username="root",
            admin_password="admin-password",
            max_running_jobs=3,
            max_active_jobs=15,
        )

        # Verify result
        assert result.success
        assert result.host_id == "existing-uuid"

        # Verify update was called instead of add
        assert len(mock_host_repo.add_host_calls) == 0
        assert len(mock_host_repo.update_calls) == 1


# =============================================================================
# Test: Failure Scenarios
# =============================================================================


class TestProvisionHostFailure:
    """Test failure scenarios in provisioning."""

    @patch("pulldb.infra.secrets.check_secret_exists")
    @patch("pulldb.infra.secrets.get_secret_path_from_alias")
    def test_aws_secret_check_failure(
        self,
        mock_get_path: MagicMock,
        mock_check: MagicMock,
        service: HostProvisioningService,
    ) -> None:
        """Test handling of AWS secret check failure."""
        mock_get_path.return_value = "/pulldb/mysql/test-host"
        mock_check.return_value = MockSecretExistsResult(
            exists=False,
            error="Access denied to secret. Check IAM permissions.",
        )

        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
        )

        assert not result.success
        assert "AWS error" in result.message

    @patch("pulldb.infra.secrets.check_secret_exists")
    @patch("pulldb.infra.mysql_provisioning.provision_host_full")
    @patch("pulldb.infra.secrets.get_secret_path_from_alias")
    def test_mysql_provision_failure(
        self,
        mock_get_path: MagicMock,
        mock_provision: MagicMock,
        mock_check: MagicMock,
        service: HostProvisioningService,
    ) -> None:
        """Test handling of MySQL provisioning failure."""
        mock_get_path.return_value = "/pulldb/mysql/test-host"
        mock_check.return_value = MockSecretExistsResult(exists=False)
        mock_provision.return_value = (
            MockProvisioningResult(
                success=False,
                message="Connection failed",
                error="Access denied for user 'root'",
                suggestions=["Check username and password"],
            ),
            {},
        )

        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="wrong-password",
        )

        assert not result.success
        assert "Connection failed" in result.message
        assert result.suggestions is not None

    @patch("pulldb.infra.secrets.check_secret_exists")
    @patch("pulldb.infra.secrets.safe_upsert_single_secret")
    @patch("pulldb.infra.mysql_provisioning.provision_host_full")
    @patch("pulldb.infra.secrets.get_secret_path_from_alias")
    def test_aws_secret_upsert_failure(
        self,
        mock_get_path: MagicMock,
        mock_provision: MagicMock,
        mock_upsert: MagicMock,
        mock_check: MagicMock,
        service: HostProvisioningService,
    ) -> None:
        """Test handling of AWS secret creation failure."""
        mock_get_path.return_value = "/pulldb/mysql/test-host"
        mock_check.return_value = MockSecretExistsResult(exists=False)
        mock_provision.return_value = (
            MockProvisioningResult(
                success=True,
                message="All steps completed",
                data={
                    "loader_username": "pulldb_loader",
                    "loader_password": "password",
                },
            ),
            {"user_created": True},
        )
        mock_upsert.return_value = MockSecretUpsertResult(
            success=False,
            was_new=False,
            secret_path="/pulldb/mysql/test-host",
            error="Access denied for CreateSecret",
        )

        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
        )

        assert not result.success
        assert "AWS error" in result.message


# =============================================================================
# Test: Connection Testing
# =============================================================================


class TestConnectionTest:
    """Test connection testing functionality."""

    @patch("pulldb.infra.mysql_provisioning.test_admin_connection")
    def test_connection_success(
        self,
        mock_test: MagicMock,
        service: HostProvisioningService,
    ) -> None:
        """Test successful connection test."""
        mock_test.return_value = MockProvisioningResult(
            success=True,
            message="Successfully connected to localhost:3306",
        )

        result = service.test_connection(
            mysql_host="localhost",
            mysql_port=3306,
            username="root",
            password="password",
        )

        assert result.success
        assert "Successfully connected" in result.message

    @patch("pulldb.infra.mysql_provisioning.test_admin_connection")
    def test_connection_failure(
        self,
        mock_test: MagicMock,
        service: HostProvisioningService,
    ) -> None:
        """Test failed connection test."""
        mock_test.return_value = MockProvisioningResult(
            success=False,
            message="Connection failed",
            error="Access denied",
            suggestions=["Check credentials"],
        )

        result = service.test_connection(
            mysql_host="localhost",
            mysql_port=3306,
            username="root",
            password="wrong",
        )

        assert not result.success
        assert "Connection failed" in result.message
        assert result.suggestions is not None


# =============================================================================
# Test: Host Deletion
# =============================================================================


class TestDeleteHost:
    """Test host deletion functionality."""

    def test_delete_nonexistent_host(
        self,
        service: HostProvisioningService,
    ) -> None:
        """Test deleting a non-existent host."""
        result = service.delete_host("nonexistent-host")

        assert not result.success
        assert "Host not found" in result.message

    def test_delete_host_without_secret(
        self,
        service: HostProvisioningService,
        mock_host_repo: MockHostRepository,
        mock_audit_repo: MockAuditRepository,
    ) -> None:
        """Test deleting a host without deleting its secret."""
        # Add a host first
        mock_host_repo.hosts["test-host"] = DBHost(
            id="test-uuid",
            hostname="test-host",
            credential_ref="aws-secretsmanager:/pulldb/mysql/test-host",
            max_running_jobs=1,
            max_active_jobs=10,
            enabled=True,
            created_at=datetime.now(),
            host_alias="test-host",
        )

        result = service.delete_host("test-host", delete_secret=False)

        assert result.success
        assert result.host_deleted
        assert not result.secret_deleted
        assert "test-host" in mock_host_repo.delete_calls

        # Verify audit log
        assert len(mock_audit_repo.log_calls) == 1
        assert mock_audit_repo.log_calls[0]["action"] == "host_deleted"

    @patch("pulldb.infra.secrets.delete_secret_if_new")
    @patch("pulldb.infra.secrets.get_secret_path_from_alias")
    def test_delete_host_with_secret(
        self,
        mock_get_path: MagicMock,
        mock_delete: MagicMock,
        service: HostProvisioningService,
        mock_host_repo: MockHostRepository,
    ) -> None:
        """Test deleting a host and its secret."""
        # Add a host first
        mock_host_repo.hosts["test-host"] = DBHost(
            id="test-uuid",
            hostname="test-host",
            credential_ref="aws-secretsmanager:/pulldb/mysql/test-host",
            max_running_jobs=1,
            max_active_jobs=10,
            enabled=True,
            created_at=datetime.now(),
            host_alias="test-host",
        )

        mock_get_path.return_value = "/pulldb/mysql/test-host"
        mock_delete.return_value = True

        result = service.delete_host("test-host", delete_secret=True)

        assert result.success
        assert result.host_deleted
        assert result.secret_deleted


# =============================================================================
# Test: Service Without Audit Repo
# =============================================================================


class TestServiceWithoutAuditRepo:
    """Test service behavior when audit repo is None."""

    @patch("pulldb.infra.secrets.check_secret_exists")
    @patch("pulldb.infra.secrets.safe_upsert_single_secret")
    @patch("pulldb.infra.mysql_provisioning.provision_host_full")
    @patch("pulldb.infra.secrets.generate_credential_ref")
    @patch("pulldb.infra.secrets.get_secret_path_from_alias")
    def test_provision_without_audit(
        self,
        mock_get_path: MagicMock,
        mock_gen_ref: MagicMock,
        mock_provision: MagicMock,
        mock_upsert: MagicMock,
        mock_check: MagicMock,
        mock_host_repo: MockHostRepository,
    ) -> None:
        """Test provisioning works without audit repo."""
        service = HostProvisioningService(
            host_repo=mock_host_repo,
            audit_repo=None,  # No audit repo
            actor_user_id="test-actor-uuid",
        )

        # Setup mocks
        mock_get_path.return_value = "/pulldb/mysql/test-host"
        mock_gen_ref.return_value = "aws-secretsmanager:/pulldb/mysql/test-host"
        mock_check.return_value = MockSecretExistsResult(exists=False)
        mock_provision.return_value = (
            MockProvisioningResult(
                success=True,
                message="All steps completed",
                data={
                    "loader_username": "pulldb_loader",
                    "loader_password": "password",
                },
            ),
            {"user_created": True, "database_created": True},
        )
        mock_upsert.return_value = MockSecretUpsertResult(
            success=True,
            was_new=True,
            secret_path="/pulldb/mysql/test-host",
        )

        # Execute
        result = service.provision_host(
            host_alias="test-host",
            mysql_host="localhost",
            mysql_port=3306,
            admin_username="root",
            admin_password="password",
        )

        # Should succeed without audit
        assert result.success
