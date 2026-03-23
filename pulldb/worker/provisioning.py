"""Host provisioning service for unified CLI/Web host management.

This module provides the HostProvisioningService class that orchestrates
all the steps needed to provision a target MySQL host for pullDB worker
operations:

1. Test admin connection to target host
2. Create pulldb_loader MySQL user with required privileges
3. Create pulldb_service database on target
4. Deploy pulldb_atomic_rename stored procedure
5. Store credentials in AWS Secrets Manager
6. Register host in pulldb coordination database

Both the admin CLI (pulldb-admin hosts provision) and the Web UI
(/admin/hosts/provision) use this service to ensure consistent behavior.

HCA Layer: features (pulldb/worker/)
- Imports from: shared (infra), entities (domain/models)
- Exports to: widgets (worker), pages (cli, web)

FAIL HARD: All operations return structured results with actionable errors.
No silent degradation - failures include diagnostic information.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pulldb.domain.models import DBHost


logger = logging.getLogger(__name__)


# =============================================================================
# Protocols (for dependency injection)
# =============================================================================


class HostRepositoryProtocol(Protocol):
    """Protocol for host repository operations needed by provisioning."""

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        """Get host by hostname."""
        ...

    def get_host_by_alias(self, alias: str) -> DBHost | None:
        """Get host by alias."""
        ...

    def add_host(
        self,
        hostname: str,
        max_concurrent: int,
        credential_ref: str | None,
        *,
        host_id: str | None = None,
        host_alias: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Add a new host to the database."""
        ...

    def update_host_config(
        self,
        host_id: str,
        *,
        host_alias: str | None = None,
        credential_ref: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Update an existing host's configuration."""
        ...

    def delete_host(self, hostname: str) -> None:
        """Delete a host from the database."""
        ...


class AuditRepositoryProtocol(Protocol):
    """Protocol for audit logging operations needed by provisioning."""

    def log_action(
        self,
        actor_user_id: str,
        action: str,
        target_user_id: str | None = None,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Record an audit log entry."""
        ...


# =============================================================================
# Result Data Classes
# =============================================================================


@dataclass
class ProvisioningStep:
    """Result of a single provisioning step.

    Attributes:
        name: Human-readable step name (e.g., "Check Host", "MySQL Setup").
        success: Whether the step succeeded.
        message: Brief result message.
        details: Optional additional details (error info, paths, etc.).
    """

    name: str
    success: bool
    message: str
    details: str | None = None


@dataclass
class ProvisioningResult:
    """Complete result of a provisioning operation.

    Attributes:
        success: Whether the entire operation succeeded.
        message: Summary message.
        host_id: UUID of the provisioned host (on success).
        steps: List of individual step results for UI display.
        rollback_performed: Whether rollback was needed due to failure.
        error: Detailed error message if failed.
        suggestions: Actionable suggestions on failure.
    """

    success: bool
    message: str
    host_id: str | None = None
    steps: list[ProvisioningStep] | None = None
    rollback_performed: bool = False
    error: str | None = None
    suggestions: list[str] | None = None


@dataclass
class ConnectionTestResult:
    """Result of a MySQL connection test.

    Attributes:
        success: Whether connection succeeded.
        message: Result message.
        error: Error details if failed.
        suggestions: Actionable suggestions on failure.
    """

    success: bool
    message: str
    error: str | None = None
    suggestions: list[str] | None = None


@dataclass
class DeleteHostResult:
    """Result of a host deletion operation.

    Attributes:
        success: Whether deletion succeeded.
        message: Result message.
        secret_deleted: Whether AWS secret was deleted.
        host_deleted: Whether database entry was deleted.
        error: Error details if failed.
    """

    success: bool
    message: str
    secret_deleted: bool = False
    host_deleted: bool = False
    error: str | None = None


# =============================================================================
# HostProvisioningService
# =============================================================================


class HostProvisioningService:
    """Service for provisioning and managing pullDB target hosts.

    This service provides unified operations for both CLI and Web UI:
    - provision_host(): Complete setup of a new target host
    - delete_host(): Remove a host and optionally its AWS secret
    - test_connection(): Test MySQL connectivity

    The service uses constructor injection for all dependencies, making
    it testable and allowing different implementations (real vs. mock).

    Example:
        >>> from pulldb.infra.factory import get_provisioning_service
        >>>
        >>> # Get service for a specific actor
        >>> service = get_provisioning_service(actor_user_id="admin-uuid")
        >>>
        >>> # Provision a new host
        >>> result = service.provision_host(
        ...     host_alias="dev-db-01",
        ...     mysql_host="dev-db.example.com",
        ...     mysql_port=3306,
        ...     admin_username="admin",
        ...     admin_password="secret",
        ...     max_running_jobs=2,
        ...     max_active_jobs=10,
        ... )
        >>> if result.success:
        ...     print(f"Host provisioned: {result.host_id}")
        ... else:
        ...     print(f"Failed: {result.message}")

    Attributes:
        host_repo: Repository for host database operations.
        audit_repo: Repository for audit logging.
        actor_user_id: UUID of the user performing operations (for audit).
    """

    def __init__(
        self,
        host_repo: HostRepositoryProtocol,
        audit_repo: AuditRepositoryProtocol | None,
        actor_user_id: str,
    ) -> None:
        """Initialize HostProvisioningService.

        Args:
            host_repo: Repository for host database operations.
            audit_repo: Repository for audit logging (optional for testing).
            actor_user_id: UUID of the user performing operations.
                Used for audit logging.
        """
        self.host_repo = host_repo
        self.audit_repo = audit_repo
        self.actor_user_id = actor_user_id

    def provision_host(
        self,
        host_alias: str,
        mysql_host: str,
        mysql_port: int,
        admin_username: str,
        admin_password: str,
        max_running_jobs: int = 1,
        max_active_jobs: int = 10,
        sql_file: str | Path | None = None,
    ) -> ProvisioningResult:
        """Provision a new target host with complete MySQL setup.

        Performs all setup steps in order:
        1. Check if host alias already exists (updates if so)
        2. Check if AWS secret already exists (reuses if so)
        3. Test admin MySQL connection
        4. Create pulldb_loader user on target
        5. Create pulldb_service database on target
        6. Deploy pulldb_atomic_rename stored procedure
        7. Create/update AWS secret with credentials
        8. Register/update host in coordination database

        On failure, rolls back only newly-created resources:
        - Deletes AWS secret only if created in this operation
        - Leaves pre-existing users/databases/secrets untouched

        Args:
            host_alias: Short alias for the host (e.g., "dev-db-01").
                Used as the hostname in db_hosts and for AWS secret path.
            mysql_host: Actual MySQL server hostname or IP.
            mysql_port: MySQL port (usually 3306).
            admin_username: Admin user with CREATE USER privilege.
            admin_password: Admin password (single-use, not stored).
            max_running_jobs: Maximum concurrent running jobs (default 1).
            max_active_jobs: Maximum queued + running jobs (default 10).
            sql_file: Optional path to stored procedure SQL file.

        Returns:
            ProvisioningResult with step-by-step details.
        """
        from pulldb.infra.secrets import (
            check_secret_exists,
            safe_upsert_single_secret,
            delete_secret_if_new,
            generate_credential_ref,
            get_secret_path_from_alias,
        )
        from pulldb.infra.mysql_provisioning import provision_host_full

        steps: list[ProvisioningStep] = []

        def add_step(
            name: str, success: bool, message: str, details: str | None = None
        ) -> None:
            steps.append(ProvisioningStep(name, success, message, details))

        # Validate inputs
        validation_error = self._validate_provision_inputs(
            host_alias,
            mysql_host,
            admin_username,
            admin_password,
            max_running_jobs,
            max_active_jobs,
        )
        if validation_error:
            return ProvisioningResult(
                success=False,
                message=validation_error,
                steps=steps,
            )

        # Track what was newly created for rollback
        secret_was_new = False
        created_secret_path: str | None = None

        try:
            # Step 1: Check existing host
            existing_host = self.host_repo.get_host_by_alias(host_alias)
            host_id: str | None = None

            if existing_host:
                add_step("Check Host", True, f"Host '{host_alias}' exists, will update")
                host_id = existing_host.id
            else:
                add_step("Check Host", True, f"New host '{host_alias}'")
                host_id = str(uuid.uuid4())

            # Step 2: Check existing AWS secret
            secret_path = get_secret_path_from_alias(host_alias)
            credential_ref = generate_credential_ref(host_alias)

            secret_check = check_secret_exists(secret_path, fetch_value=True)
            if secret_check.error:
                add_step(
                    "Check Secret", False, "Error checking AWS secret", secret_check.error
                )
                return ProvisioningResult(
                    success=False,
                    message=f"AWS error: {secret_check.error}",
                    steps=steps,
                )

            if secret_check.exists:
                add_step(
                    "Check Secret",
                    True,
                    "Existing credentials found",
                    f"Secret: {secret_path}",
                )
            else:
                add_step(
                    "Check Secret",
                    True,
                    "No existing credentials",
                    f"Will create: {secret_path}",
                )

            # Step 3: Provision MySQL (test connection, create user, db, sproc)
            prov_result, created_resources = provision_host_full(
                mysql_host=mysql_host,
                mysql_port=mysql_port,
                admin_username=admin_username,
                admin_password=admin_password,
                sql_file=sql_file,
            )

            if not prov_result.success:
                add_step(
                    "MySQL Setup", False, prov_result.message, prov_result.error or ""
                )
                suggestions = prov_result.suggestions or []
                suggestion_msg = f". Try: {suggestions[0]}" if suggestions else ""
                return ProvisioningResult(
                    success=False,
                    message=f"{prov_result.message}{suggestion_msg}",
                    steps=steps,
                    suggestions=suggestions,
                )

            # Extract created user credentials
            prov_data = prov_result.data or {}
            loader_username = prov_data.get("loader_username", "pulldb_loader")
            loader_password = prov_data.get("loader_password", "")

            user_action = "created" if created_resources.get("user_created") else "updated"
            db_action = "created" if created_resources.get("database_created") else "exists"

            add_step(
                "MySQL Setup",
                True,
                f"User {user_action}, database {db_action}, procedure deployed",
                f"User: {loader_username}",
            )

            # Step 4: Create or update AWS secret
            secret_data = {
                "host": mysql_host,
                "password": loader_password,
                "username": loader_username,
                "port": mysql_port,
            }

            upsert_result = safe_upsert_single_secret(
                secret_path=secret_path,
                secret_data=secret_data,
            )

            if not upsert_result.success:
                add_step(
                    "AWS Secret",
                    False,
                    "Failed to save credentials",
                    upsert_result.error or "",
                )
                return ProvisioningResult(
                    success=False,
                    message=f"AWS error: {upsert_result.error}",
                    steps=steps,
                )

            secret_was_new = upsert_result.was_new
            created_secret_path = secret_path

            secret_action = "created" if upsert_result.was_new else "updated"
            add_step(
                "AWS Secret",
                True,
                f"Credentials {secret_action}",
                f"Path: {secret_path}",
            )

            # Step 5: Register or update host in database
            if existing_host:
                # Update existing host
                self.host_repo.update_host_config(
                    host_id=host_id,
                    host_alias=host_alias,
                    credential_ref=credential_ref,
                    max_running_jobs=max_running_jobs,
                    max_active_jobs=max_active_jobs,
                )
                add_step("Register Host", True, "Host configuration updated")
            else:
                # Add new host - use alias as hostname
                self.host_repo.add_host(
                    hostname=host_alias,
                    max_concurrent=max_running_jobs,
                    credential_ref=credential_ref,
                    host_id=host_id,
                    host_alias=host_alias,
                    max_active_jobs=max_active_jobs,
                )
                add_step("Register Host", True, "Host registered successfully")

            # Audit log
            if self.audit_repo:
                self.audit_repo.log_action(
                    actor_user_id=self.actor_user_id,
                    action="host_provisioned",
                    detail=f"Provisioned database host {host_alias} ({mysql_host}:{mysql_port})",
                    context={
                        "host_id": host_id,
                        "host_alias": host_alias,
                        "mysql_host": mysql_host,
                        "mysql_port": mysql_port,
                        "max_running_jobs": max_running_jobs,
                        "max_active_jobs": max_active_jobs,
                        "was_update": existing_host is not None,
                    },
                )

            return ProvisioningResult(
                success=True,
                message="Host provisioned successfully",
                host_id=host_id,
                steps=steps,
            )

        except Exception as e:
            logger.exception(f"Unexpected error during provisioning: {e}")

            # Rollback: Delete secret only if it was newly created
            if secret_was_new and created_secret_path:
                delete_secret_if_new(created_secret_path, was_new=True)
                add_step(
                    "Rollback",
                    True,
                    "Cleaned up newly-created secret",
                    f"Deleted: {created_secret_path}",
                )
                return ProvisioningResult(
                    success=False,
                    message=f"Unexpected error: {e}",
                    steps=steps,
                    rollback_performed=True,
                    error=str(e),
                )

            add_step("Error", False, str(e))
            return ProvisioningResult(
                success=False,
                message=f"Unexpected error: {e}",
                steps=steps,
                error=str(e),
            )

    def test_connection(
        self,
        mysql_host: str,
        mysql_port: int,
        username: str,
        password: str,
    ) -> ConnectionTestResult:
        """Test MySQL connection with provided credentials.

        This tests both connectivity and sufficient privileges.
        Used for validating admin credentials before provisioning.

        Args:
            mysql_host: MySQL server hostname or IP.
            mysql_port: MySQL port.
            username: MySQL username to test.
            password: MySQL password.

        Returns:
            ConnectionTestResult with success status and details.
        """
        from pulldb.infra.mysql_provisioning import test_admin_connection

        result = test_admin_connection(
            host=mysql_host,
            port=mysql_port,
            username=username,
            password=password,
        )

        return ConnectionTestResult(
            success=result.success,
            message=result.message,
            error=result.error,
            suggestions=result.suggestions,
        )

    def delete_host(
        self,
        hostname: str,
        delete_secret: bool = False,
        force: bool = False,
    ) -> DeleteHostResult:
        """Delete a host from the coordination database.

        Optionally also deletes the AWS secret. By default, only removes
        the database entry (preserves credentials for safety).

        Args:
            hostname: Hostname or alias to delete.
            delete_secret: Also delete AWS secret (requires confirmation).
            force: Skip confirmation checks (for testing).

        Returns:
            DeleteHostResult with deletion status.
        """
        from pulldb.infra.secrets import get_secret_path_from_alias, delete_secret_if_new

        # Find the host
        host = self.host_repo.get_host_by_hostname(hostname)
        if host is None:
            host = self.host_repo.get_host_by_alias(hostname)
        if host is None:
            return DeleteHostResult(
                success=False,
                message=f"Host not found: {hostname}",
            )

        secret_deleted = False
        host_deleted = False

        try:
            # Optionally delete AWS secret
            if delete_secret and host.host_alias:
                secret_path = get_secret_path_from_alias(host.host_alias)
                # Use delete_secret_if_new with was_new=True to force deletion
                if delete_secret_if_new(secret_path, was_new=True):
                    secret_deleted = True
                    logger.info(f"Deleted secret: {secret_path}")

            # Delete from database
            self.host_repo.delete_host(host.hostname)
            host_deleted = True

            # Audit log
            if self.audit_repo:
                self.audit_repo.log_action(
                    actor_user_id=self.actor_user_id,
                    action="host_deleted",
                    detail=f"Deleted database host {hostname}",
                    context={
                        "host_id": host.id,
                        "hostname": host.hostname,
                        "host_alias": host.host_alias,
                        "secret_deleted": secret_deleted,
                    },
                )

            return DeleteHostResult(
                success=True,
                message=f"Host '{hostname}' deleted successfully",
                secret_deleted=secret_deleted,
                host_deleted=host_deleted,
            )

        except Exception as e:
            logger.exception(f"Error deleting host {hostname}: {e}")
            return DeleteHostResult(
                success=False,
                message=f"Error deleting host: {e}",
                secret_deleted=secret_deleted,
                host_deleted=host_deleted,
                error=str(e),
            )

    def _validate_provision_inputs(
        self,
        host_alias: str,
        mysql_host: str,
        admin_username: str,
        admin_password: str,
        max_running_jobs: int,
        max_active_jobs: int,
    ) -> str | None:
        """Validate provisioning inputs.

        Args:
            All provisioning parameters.

        Returns:
            Error message if validation fails, None if valid.
        """
        if not host_alias or not host_alias.strip():
            return "Host alias is required"
        if not mysql_host or not mysql_host.strip():
            return "MySQL host is required"
        if not admin_username or not admin_password:
            return "Admin credentials are required"
        if max_running_jobs < 1:
            return "max_running_jobs must be at least 1"
        if max_active_jobs < 0:
            return "max_active_jobs cannot be negative"
        if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
            return "max_running_jobs cannot exceed max_active_jobs"
        return None
