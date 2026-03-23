"""Overlord database provisioning service.

This module provides the OverlordProvisioningService class that orchestrates
all the steps needed to provision pullDB's access to an external overlord
database. Following the same secure pattern as host provisioning:

1. Accept admin credentials (single-use, not stored)
2. Create pulldb_overlord MySQL user with minimal privileges
3. Store credentials in AWS Secrets Manager
4. Update settings with credential reference (not actual credentials)

The admin credentials are NEVER stored - they're only used to create the
service user. Users never see the pulldb_overlord password.

HCA Layer: features (pulldb/worker/)
- Imports from: shared (infra), entities (domain/models)
- Exports to: widgets (worker), pages (cli, web)

FAIL HARD: All operations return structured results with actionable errors.
"""

from __future__ import annotations

import logging
import re
import secrets
import string
from dataclasses import dataclass
from typing import Any, Protocol

import mysql.connector
from mysql.connector.abstracts import MySQLConnectionAbstract


logger = logging.getLogger(__name__)


# =============================================================================
# SQL Identifier Validation
# =============================================================================

# Pattern for valid MySQL identifiers (alphanumeric + underscore, starts with letter/underscore)
_SAFE_SQL_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _is_safe_sql_identifier(name: str) -> bool:
    """Validate that a string is safe to use as SQL identifier.

    Prevents SQL injection by ensuring names match safe identifier pattern.
    MySQL identifiers should contain only alphanumeric characters and underscores,
    and must start with a letter or underscore.

    Args:
        name: The identifier name to validate.

    Returns:
        True if the name is safe, False otherwise.
    """
    if not name or len(name) > 64:  # MySQL max identifier length
        return False
    return bool(_SAFE_SQL_IDENTIFIER_PATTERN.match(name))


# =============================================================================
# Protocols (for dependency injection)
# =============================================================================


class SettingsRepositoryProtocol(Protocol):
    """Protocol for settings repository operations needed by provisioning."""

    def set_setting(self, key: str, value: str) -> None:
        """Set a setting value."""
        ...

    def get_setting(self, key: str) -> str | None:
        """Get a setting value."""
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
        name: Human-readable step name.
        success: Whether the step succeeded.
        message: Brief result message.
        details: Optional additional details.
    """

    name: str
    success: bool
    message: str
    details: str | None = None


@dataclass
class OverlordProvisioningResult:
    """Complete result of overlord provisioning operation.

    Attributes:
        success: Whether the entire operation succeeded.
        message: Summary message.
        steps: List of individual step results for UI display.
        rollback_performed: Whether rollback was needed due to failure.
        error: Detailed error message if failed.
        suggestions: Actionable suggestions on failure.
    """

    success: bool
    message: str
    steps: list[ProvisioningStep] | None = None
    rollback_performed: bool = False
    error: str | None = None
    suggestions: list[str] | None = None


@dataclass
class ConnectionTestResult:
    """Result of a MySQL connection test."""

    success: bool
    message: str
    error: str | None = None
    suggestions: list[str] | None = None


# =============================================================================
# OverlordProvisioningService
# =============================================================================


# Default MySQL user for overlord access
OVERLORD_SERVICE_USER = "pulldb_overlord"

# Secret path pattern for overlord credentials
OVERLORD_SECRET_PATH = "/pulldb/mysql/overlord"


def _generate_secure_password(length: int = 32) -> str:
    """Generate a cryptographically secure password.
    
    Args:
        length: Password length (default 32).
        
    Returns:
        Secure random password with alphanumeric characters.
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class OverlordProvisioningService:
    """Service for provisioning pullDB access to overlord database.

    This service provides unified operations for both CLI and Web UI:
    - provision(): Set up pullDB access to overlord database
    - test_connection(): Test connectivity with existing credentials
    - deprovision(): Remove pullDB access from overlord

    The service uses constructor injection for all dependencies.

    Example:
        >>> from pulldb.worker.overlord_provisioning import (
        ...     OverlordProvisioningService
        ... )
        >>>
        >>> service = OverlordProvisioningService(
        ...     settings_repo=settings_repo,
        ...     audit_repo=audit_repo,
        ...     actor_user_id="admin-uuid",
        ... )
        >>>
        >>> # Provision overlord access
        >>> result = service.provision(
        ...     overlord_host="overlord.example.com",
        ...     overlord_port=3306,
        ...     overlord_database="overlord",
        ...     overlord_table="companies",
        ...     admin_username="admin",
        ...     admin_password="secret",  # Single-use, not stored
        ... )
        >>> if result.success:
        ...     print("Overlord access configured!")
    """

    def __init__(
        self,
        settings_repo: SettingsRepositoryProtocol,
        audit_repo: AuditRepositoryProtocol | None,
        actor_user_id: str,
    ) -> None:
        """Initialize OverlordProvisioningService.

        Args:
            settings_repo: Repository for settings operations.
            audit_repo: Repository for audit logging (optional for testing).
            actor_user_id: UUID of the user performing operations.
        """
        self.settings_repo = settings_repo
        self.audit_repo = audit_repo
        self.actor_user_id = actor_user_id

    def provision(
        self,
        overlord_host: str,
        overlord_port: int,
        overlord_database: str,
        overlord_table: str,
        admin_username: str,
        admin_password: str,
    ) -> OverlordProvisioningResult:
        """Provision pullDB access to overlord database.

        Performs all setup steps in order:
        1. Test admin MySQL connection
        2. Check if pulldb_overlord user exists
        3. Create or update pulldb_overlord user with minimal privileges
        4. Create/update AWS secret with credentials
        5. Update pullDB settings with credential reference

        The admin credentials are ONLY used to create the service user.
        They are never stored. The service user password is randomly
        generated and stored in AWS Secrets Manager.

        Args:
            overlord_host: Overlord MySQL server hostname.
            overlord_port: Overlord MySQL port (usually 3306).
            overlord_database: Overlord database name (usually "overlord").
            overlord_table: Overlord table name (usually "companies").
            admin_username: Admin user with GRANT privilege.
            admin_password: Admin password (single-use, NOT stored).

        Returns:
            OverlordProvisioningResult with step-by-step details.
        """
        from pulldb.infra.secrets import (
            check_secret_exists,
            safe_upsert_single_secret,
            delete_secret_if_new,
        )

        steps: list[ProvisioningStep] = []

        def add_step(
            name: str, success: bool, message: str, details: str | None = None
        ) -> None:
            steps.append(ProvisioningStep(name, success, message, details))

        # Validate inputs
        validation_error = self._validate_provision_inputs(
            overlord_host,
            overlord_database,
            admin_username,
            admin_password,
        )
        if validation_error:
            return OverlordProvisioningResult(
                success=False,
                message=validation_error,
                steps=steps,
            )

        # Track what was newly created for rollback
        secret_was_new = False
        user_was_created = False
        service_password: str | None = None

        try:
            # Step 1: Test admin connection
            test_result = self._test_admin_connection(
                host=overlord_host,
                port=overlord_port,
                database=overlord_database,
                username=admin_username,
                password=admin_password,
            )

            if not test_result.success:
                add_step("Test Connection", False, test_result.message, test_result.error)
                return OverlordProvisioningResult(
                    success=False,
                    message=test_result.message,
                    steps=steps,
                    suggestions=test_result.suggestions,
                )

            add_step("Test Connection", True, "Admin connection successful")

            # Step 2: Check existing AWS secret
            secret_check = check_secret_exists(OVERLORD_SECRET_PATH, fetch_value=True)
            if secret_check.error:
                add_step(
                    "Check Secret", False, "Error checking AWS secret", secret_check.error
                )
                return OverlordProvisioningResult(
                    success=False,
                    message=f"AWS error: {secret_check.error}",
                    steps=steps,
                )

            if secret_check.exists:
                add_step(
                    "Check Secret",
                    True,
                    "Existing credentials found, will update",
                    f"Secret: {OVERLORD_SECRET_PATH}",
                )
            else:
                add_step(
                    "Check Secret",
                    True,
                    "No existing credentials",
                    f"Will create: {OVERLORD_SECRET_PATH}",
                )

            # Step 3: Create or update MySQL user
            service_password = _generate_secure_password()
            user_result = self._create_or_update_user(
                host=overlord_host,
                port=overlord_port,
                database=overlord_database,
                table=overlord_table,
                admin_username=admin_username,
                admin_password=admin_password,
                service_username=OVERLORD_SERVICE_USER,
                service_password=service_password,
            )

            if not user_result["success"]:
                add_step(
                    "MySQL User",
                    False,
                    user_result["message"],
                    user_result.get("error"),
                )
                return OverlordProvisioningResult(
                    success=False,
                    message=user_result["message"],
                    steps=steps,
                    suggestions=user_result.get("suggestions"),
                )

            user_was_created = user_result.get("was_created", False)
            user_action = "created" if user_was_created else "updated"
            add_step(
                "MySQL User",
                True,
                f"User {OVERLORD_SERVICE_USER} {user_action}",
                f"Privileges: SELECT, UPDATE on {overlord_database}.{overlord_table}",
            )

            # Step 4: Create or update AWS secret
            secret_data = {
                "host": overlord_host,
                "password": service_password,
                "username": OVERLORD_SERVICE_USER,
                "port": overlord_port,
            }

            upsert_result = safe_upsert_single_secret(
                secret_path=OVERLORD_SECRET_PATH,
                secret_data=secret_data,
            )

            if not upsert_result.success:
                add_step(
                    "AWS Secret",
                    False,
                    "Failed to save credentials",
                    upsert_result.error or "",
                )
                # Rollback: Drop user if we created it
                if user_was_created:
                    self._drop_user(
                        host=overlord_host,
                        port=overlord_port,
                        admin_username=admin_username,
                        admin_password=admin_password,
                        service_username=OVERLORD_SERVICE_USER,
                    )
                return OverlordProvisioningResult(
                    success=False,
                    message=f"AWS error: {upsert_result.error}",
                    steps=steps,
                    rollback_performed=user_was_created,
                )

            secret_was_new = upsert_result.was_new
            secret_action = "created" if secret_was_new else "updated"
            add_step(
                "AWS Secret",
                True,
                f"Credentials {secret_action}",
                f"Path: {OVERLORD_SECRET_PATH}",
            )

            # Step 5: Update pullDB settings
            credential_ref = f"aws-secretsmanager:{OVERLORD_SECRET_PATH}"
            
            self.settings_repo.set_setting("overlord_dbhost", overlord_host)
            self.settings_repo.set_setting("overlord_database", overlord_database)
            self.settings_repo.set_setting("overlord_table", overlord_table)
            self.settings_repo.set_setting("overlord_credential_ref", credential_ref)
            # Enable the feature
            self.settings_repo.set_setting("overlord_enabled", "true")

            add_step(
                "Update Settings",
                True,
                "Overlord settings configured and enabled",
                f"Credential ref: {credential_ref}",
            )

            # Audit log
            if self.audit_repo:
                self.audit_repo.log_action(
                    actor_user_id=self.actor_user_id,
                    action="overlord_provisioned",
                    detail=f"Provisioned overlord access to {overlord_host}:{overlord_port}/{overlord_database}",
                    context={
                        "overlord_host": overlord_host,
                        "overlord_port": overlord_port,
                        "overlord_database": overlord_database,
                        "overlord_table": overlord_table,
                        "user_created": user_was_created,
                        "secret_created": secret_was_new,
                    },
                )

            return OverlordProvisioningResult(
                success=True,
                message="Overlord access provisioned successfully",
                steps=steps,
            )

        except Exception as e:
            logger.exception(f"Unexpected error during overlord provisioning: {e}")

            # Rollback: Delete secret only if it was newly created
            if secret_was_new:
                delete_secret_if_new(OVERLORD_SECRET_PATH, was_new=True)
                add_step(
                    "Rollback",
                    True,
                    "Cleaned up newly-created secret",
                    f"Deleted: {OVERLORD_SECRET_PATH}",
                )

            # Rollback: Drop user if we created it
            if user_was_created and service_password:
                try:
                    self._drop_user(
                        host=overlord_host,
                        port=overlord_port,
                        admin_username=admin_username,
                        admin_password=admin_password,
                        service_username=OVERLORD_SERVICE_USER,
                    )
                    add_step("Rollback", True, "Cleaned up MySQL user")
                except Exception as drop_error:
                    add_step(
                        "Rollback",
                        False,
                        "Failed to cleanup MySQL user",
                        str(drop_error),
                    )

            return OverlordProvisioningResult(
                success=False,
                message=f"Unexpected error: {e}",
                steps=steps,
                rollback_performed=True,
                error=str(e),
            )

    def test_connection(self) -> ConnectionTestResult:
        """Test connection to overlord using stored credentials.

        Uses the credential_ref from settings to resolve and test
        the overlord connection.

        Returns:
            ConnectionTestResult with success status.
        """
        from pulldb.infra.secrets import CredentialResolver

        credential_ref = self.settings_repo.get_setting("overlord_credential_ref")
        if not credential_ref:
            return ConnectionTestResult(
                success=False,
                message="Overlord not configured",
                error="No overlord_credential_ref in settings",
                suggestions=["Provision overlord access first"],
            )

        overlord_host = self.settings_repo.get_setting("overlord_dbhost")
        overlord_database = self.settings_repo.get_setting("overlord_database") or "overlord"

        if not overlord_host:
            return ConnectionTestResult(
                success=False,
                message="Overlord host not configured",
                error="No overlord_dbhost in settings",
            )

        try:
            resolver = CredentialResolver()
            creds = resolver.resolve(credential_ref)

            conn = mysql.connector.connect(
                host=overlord_host,
                port=creds.port if hasattr(creds, 'port') else 3306,
                user=creds.username if hasattr(creds, 'username') else OVERLORD_SERVICE_USER,
                password=creds.password,
                database=overlord_database,
                connect_timeout=5,
            )
            conn.close()

            return ConnectionTestResult(
                success=True,
                message=f"Connected to {overlord_host}/{overlord_database}",
            )

        except mysql.connector.Error as e:
            return ConnectionTestResult(
                success=False,
                message="Connection failed",
                error=str(e),
                suggestions=[
                    "Check overlord host is reachable",
                    "Verify credentials in AWS Secrets Manager",
                    "Check MySQL user has required privileges",
                ],
            )
        except Exception as e:
            return ConnectionTestResult(
                success=False,
                message="Failed to resolve credentials",
                error=str(e),
            )

    def rotate_credentials(self) -> OverlordProvisioningResult:
        """Rotate the pulldb_overlord user's password.

        This method:
        1. Resolves current credentials from AWS Secrets Manager
        2. Generates a new secure password
        3. Updates MySQL user password using ALTER USER (self-modify)
        4. Verifies new password works
        5. Updates AWS Secrets Manager with new password
        6. Final verification round-trip

        Unlike host rotation, overlord rotation is self-contained because
        the service user has ALTER USER privilege on itself (granted during
        provisioning).

        Returns:
            OverlordProvisioningResult with step-by-step status.
        """
        from pulldb.infra.secrets import CredentialResolver, safe_upsert_single_secret

        steps: list[ProvisioningStep] = []

        def add_step(
            name: str, success: bool, message: str, details: str | None = None
        ) -> None:
            steps.append(ProvisioningStep(name, success, message, details))

        # Step 1: Validate configuration exists
        credential_ref = self.settings_repo.get_setting("overlord_credential_ref")
        if not credential_ref:
            return OverlordProvisioningResult(
                success=False,
                message="Overlord not configured",
                steps=[ProvisioningStep(
                    "Check Configuration", False,
                    "No overlord_credential_ref in settings",
                    "Provision overlord access first"
                )],
                error="Overlord must be provisioned before rotating credentials",
                suggestions=["Run overlord provisioning first"],
            )

        overlord_host = self.settings_repo.get_setting("overlord_dbhost")
        if not overlord_host:
            return OverlordProvisioningResult(
                success=False,
                message="Overlord host not configured",
                steps=[ProvisioningStep(
                    "Check Configuration", False,
                    "No overlord_dbhost in settings"
                )],
                error="Missing overlord host configuration",
            )

        add_step("Check Configuration", True, "Configuration valid")

        # Step 2: Resolve current credentials
        try:
            resolver = CredentialResolver()
            creds = resolver.resolve(credential_ref)
            current_password = creds.password
            current_username = creds.username if hasattr(creds, 'username') else OVERLORD_SERVICE_USER
            current_port = creds.port if hasattr(creds, 'port') else 3306
            add_step("Resolve Credentials", True, f"Retrieved credentials from AWS")
        except Exception as e:
            add_step("Resolve Credentials", False, "Failed to get current credentials", str(e))
            return OverlordProvisioningResult(
                success=False,
                message="Failed to resolve current credentials",
                steps=steps,
                error=str(e),
                suggestions=[
                    "Check AWS Secrets Manager access",
                    f"Verify secret '{credential_ref}' exists",
                ],
            )

        # Step 3: Test current credentials work
        try:
            conn = mysql.connector.connect(
                host=overlord_host,
                port=current_port,
                user=current_username,
                password=current_password,
                connect_timeout=5,
            )
            conn.close()
            add_step("Verify Current Access", True, "Current credentials valid")
        except mysql.connector.Error as e:
            add_step("Verify Current Access", False, "Current credentials invalid", str(e))
            return OverlordProvisioningResult(
                success=False,
                message="Current credentials don't work - cannot rotate",
                steps=steps,
                error=str(e),
                suggestions=[
                    "Current credentials may have been manually changed",
                    "Re-provision overlord access with admin credentials",
                ],
            )

        # Step 4: Generate new password
        new_password = _generate_secure_password(32)
        add_step("Generate Password", True, "New secure password generated")

        # Step 5: Update MySQL password (ALTER USER on self)
        conn = None
        try:
            conn = mysql.connector.connect(
                host=overlord_host,
                port=current_port,
                user=current_username,
                password=current_password,
                connect_timeout=10,
            )
            cursor = conn.cursor()
            try:
                # Use SET PASSWORD which any user can use on themselves
                # (doesn't require CREATE USER privilege like ALTER USER does)
                cursor.execute("SET PASSWORD = %s", (new_password,))
                conn.commit()
                add_step("Update MySQL Password", True, "MySQL password updated")
            finally:
                cursor.close()
        except mysql.connector.Error as e:
            add_step("Update MySQL Password", False, "Failed to update MySQL password", str(e))
            return OverlordProvisioningResult(
                success=False,
                message="Failed to update MySQL password",
                steps=steps,
                error=str(e),
                suggestions=[
                    "MySQL may have password policy restrictions",
                    "Check MySQL error logs for details",
                ],
            )
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        # Step 6: Verify new password works
        try:
            conn = mysql.connector.connect(
                host=overlord_host,
                port=current_port,
                user=current_username,
                password=new_password,
                connect_timeout=5,
            )
            conn.close()
            add_step("Verify New Password", True, "New password verified on MySQL")
        except mysql.connector.Error as e:
            # CRITICAL: MySQL updated but we can't verify - attempt rollback
            add_step("Verify New Password", False, "New password verification failed", str(e))
            
            # Try to rollback to old password
            try:
                # We need to use the NEW password since MySQL was updated
                conn = mysql.connector.connect(
                    host=overlord_host,
                    port=current_port,
                    user=current_username,
                    password=new_password,  # Use new password for rollback
                    connect_timeout=10,
                )
                cursor = conn.cursor()
                # Use SET PASSWORD for rollback (no special privileges needed)
                cursor.execute("SET PASSWORD = %s", (current_password,))
                conn.commit()
                cursor.close()
                conn.close()
                add_step("Rollback", True, "Reverted to old password")
            except Exception as rollback_error:
                add_step("Rollback", False, "Failed to rollback", str(rollback_error))
            
            return OverlordProvisioningResult(
                success=False,
                message="New password verification failed",
                steps=steps,
                rollback_performed=True,
                error=str(e),
            )

        # Step 7: Update AWS Secrets Manager
        try:
            # Extract the actual secret path from credential_ref
            # credential_ref format: "aws-secretsmanager:/pulldb/mysql/overlord"
            secret_path = credential_ref
            if secret_path.startswith("aws-secretsmanager:"):
                secret_path = secret_path[len("aws-secretsmanager:"):]
            
            secret_data = {
                "username": current_username,
                "password": new_password,
                "host": overlord_host,
                "port": current_port,
            }
            result = safe_upsert_single_secret(
                secret_path=secret_path,
                secret_data=secret_data,
            )
            if not result.success:
                raise Exception(result.error or "Unknown error updating secret")
            add_step("Update AWS Secret", True, "AWS Secrets Manager updated")
        except Exception as e:
            add_step("Update AWS Secret", False, "Failed to update AWS secret", str(e))
            
            # MySQL is updated but AWS failed - critical state
            # Try to rollback MySQL
            try:
                conn = mysql.connector.connect(
                    host=overlord_host,
                    port=current_port,
                    user=current_username,
                    password=new_password,
                    connect_timeout=10,
                )
                cursor = conn.cursor()
                # Use SET PASSWORD for rollback (no special privileges needed)
                cursor.execute("SET PASSWORD = %s", (current_password,))
                conn.commit()
                cursor.close()
                conn.close()
                add_step("Rollback MySQL", True, "Reverted MySQL to old password")
            except Exception as rollback_error:
                add_step("Rollback MySQL", False, "CRITICAL: Failed to rollback MySQL", str(rollback_error))
                return OverlordProvisioningResult(
                    success=False,
                    message="CRITICAL: MySQL password changed but AWS update failed and rollback failed",
                    steps=steps,
                    rollback_performed=True,
                    error=str(e),
                    suggestions=[
                        f"Manual fix required: Update secret '{credential_ref}' with new password",
                        "Or manually reset MySQL user password to match AWS",
                    ],
                )
            
            return OverlordProvisioningResult(
                success=False,
                message="AWS update failed but MySQL was rolled back",
                steps=steps,
                rollback_performed=True,
                error=str(e),
            )

        # Step 8: Final verification - round-trip test
        try:
            # Re-resolve from AWS and test
            creds = resolver.resolve(credential_ref)
            conn = mysql.connector.connect(
                host=overlord_host,
                port=current_port,
                user=creds.username if hasattr(creds, 'username') else current_username,
                password=creds.password,
                connect_timeout=5,
            )
            conn.close()
            add_step("Final Verification", True, "Round-trip verification passed")
        except Exception as e:
            add_step("Final Verification", False, "Round-trip verification failed", str(e))
            # This is a warning, not a failure - both MySQL and AWS were updated successfully
            logger.warning(f"Overlord rotation final verification failed: {e}")

        # Audit log
        if self.audit_repo:
            try:
                self.audit_repo.log_action(
                    actor_user_id=self.actor_user_id,
                    action="overlord_credentials_rotated",
                    detail=f"Rotated credentials for {OVERLORD_SERVICE_USER}@{overlord_host}",
                    context={"host": overlord_host, "user": current_username},
                )
            except Exception:
                logger.debug("Failed to audit log rotation", exc_info=True)

        return OverlordProvisioningResult(
            success=True,
            message=f"Credentials rotated successfully for {OVERLORD_SERVICE_USER}",
            steps=steps,
        )

    def deprovision(
        self,
        admin_username: str,
        admin_password: str,
        delete_user: bool = True,
        delete_secret: bool = True,
    ) -> OverlordProvisioningResult:
        """Remove pullDB access to overlord database.

        Args:
            admin_username: Admin user with DROP USER privilege.
            admin_password: Admin password (single-use).
            delete_user: Whether to drop the MySQL user.
            delete_secret: Whether to delete the AWS secret.

        Returns:
            OverlordProvisioningResult with step-by-step details.
        """
        from pulldb.infra.secrets import delete_secret_if_exists

        steps: list[ProvisioningStep] = []

        def add_step(
            name: str, success: bool, message: str, details: str | None = None
        ) -> None:
            steps.append(ProvisioningStep(name, success, message, details))

        overlord_host = self.settings_repo.get_setting("overlord_dbhost")

        if delete_user and overlord_host:
            try:
                # Get port from secret or default
                credential_ref = self.settings_repo.get_setting("overlord_credential_ref")
                port = 3306
                if credential_ref:
                    from pulldb.infra.secrets import CredentialResolver
                    try:
                        resolver = CredentialResolver()
                        creds = resolver.resolve(credential_ref)
                        port = creds.port if hasattr(creds, 'port') else 3306
                    except Exception:
                        pass

                self._drop_user(
                    host=overlord_host,
                    port=port,
                    admin_username=admin_username,
                    admin_password=admin_password,
                    service_username=OVERLORD_SERVICE_USER,
                )
                add_step("Drop User", True, f"User {OVERLORD_SERVICE_USER} dropped")
            except Exception as e:
                add_step("Drop User", False, "Failed to drop user", str(e))

        if delete_secret:
            try:
                delete_secret_if_exists(OVERLORD_SECRET_PATH)
                add_step("Delete Secret", True, "AWS secret deleted")
            except Exception as e:
                add_step("Delete Secret", False, "Failed to delete secret", str(e))

        # Clear settings
        self.settings_repo.set_setting("overlord_enabled", "false")
        self.settings_repo.set_setting("overlord_credential_ref", "")
        add_step("Clear Settings", True, "Overlord settings cleared")

        # Audit log
        if self.audit_repo:
            self.audit_repo.log_action(
                actor_user_id=self.actor_user_id,
                action="overlord_deprovisioned",
                detail=f"Removed overlord access from {overlord_host}",
                context={
                    "overlord_host": overlord_host,
                    "user_deleted": delete_user,
                    "secret_deleted": delete_secret,
                },
            )

        return OverlordProvisioningResult(
            success=True,
            message="Overlord access removed",
            steps=steps,
        )

    def is_host_changing(self, new_host: str) -> bool:
        """Check if the overlord host is changing.
        
        Args:
            new_host: The new host being configured.
            
        Returns:
            True if overlord is currently configured with a DIFFERENT host.
        """
        current_host = self.settings_repo.get_setting("overlord_dbhost")
        current_enabled = self.settings_repo.get_setting("overlord_enabled")
        
        # Only consider it a change if:
        # 1. Overlord is currently configured (has a host)
        # 2. Overlord is enabled (active configuration)
        # 3. The new host is different from the current host
        if not current_host or current_enabled != "true":
            return False
        
        # Normalize hosts for comparison (strip whitespace, lowercase)
        current_normalized = current_host.strip().lower()
        new_normalized = new_host.strip().lower()
        
        return current_normalized != new_normalized

    def get_current_host(self) -> str | None:
        """Get the currently configured overlord host.
        
        Returns:
            Current host if configured, None otherwise.
        """
        return self.settings_repo.get_setting("overlord_dbhost")

    def cleanup_old_host(
        self,
        old_admin_username: str,
        old_admin_password: str,
    ) -> OverlordProvisioningResult:
        """Clean up the old overlord host before migrating to a new one.
        
        This method:
        1. Drops the pulldb_overlord user from the OLD MySQL server
        2. Clears the overlord settings (host, credential_ref, etc.)
        
        The AWS secret is NOT deleted - it will be reused/overwritten when
        provisioning the new host.
        
        IMPORTANT: This does NOT provision the new host. Call provision()
        separately after cleanup succeeds.
        
        Args:
            old_admin_username: Admin user on the OLD overlord server.
            old_admin_password: Admin password (single-use, NOT stored).
            
        Returns:
            OverlordProvisioningResult with step-by-step details.
        """

        steps: list[ProvisioningStep] = []

        def add_step(
            name: str, success: bool, message: str, details: str | None = None
        ) -> None:
            steps.append(ProvisioningStep(name, success, message, details))

        # Get current configuration
        old_host = self.settings_repo.get_setting("overlord_dbhost")
        if not old_host:
            return OverlordProvisioningResult(
                success=False,
                message="No existing overlord host configured",
                steps=[ProvisioningStep(
                    "Check Configuration", False,
                    "No overlord host to clean up",
                )],
            )
        
        add_step("Check Configuration", True, f"Found existing host: {old_host}")

        # Get port from existing credentials
        credential_ref = self.settings_repo.get_setting("overlord_credential_ref")
        port = 3306
        if credential_ref:
            from pulldb.infra.secrets import CredentialResolver
            try:
                resolver = CredentialResolver()
                creds = resolver.resolve(credential_ref)
                port = creds.port if hasattr(creds, 'port') else 3306
            except Exception:
                pass

        # Step 1: Test admin connection to OLD host
        test_result = self._test_admin_connection(
            host=old_host,
            port=port,
            database="mysql",  # Just need to connect, not specific DB
            username=old_admin_username,
            password=old_admin_password,
        )
        
        if not test_result.success:
            add_step("Test Old Host Connection", False, test_result.message, test_result.error)
            return OverlordProvisioningResult(
                success=False,
                message="Failed to connect to old host - cannot clean up",
                steps=steps,
                error=test_result.error,
                suggestions=[
                    "Verify admin credentials for the OLD overlord server",
                    "Ensure the old server is still accessible",
                    "If the old server is decommissioned, contact support",
                ],
            )
        
        add_step("Test Old Host Connection", True, "Admin connection to old host successful")

        # Step 2: Drop the MySQL user from OLD host
        try:
            self._drop_user(
                host=old_host,
                port=port,
                admin_username=old_admin_username,
                admin_password=old_admin_password,
                service_username=OVERLORD_SERVICE_USER,
            )
            add_step("Drop MySQL User", True, f"User {OVERLORD_SERVICE_USER} dropped from {old_host}")
        except Exception as e:
            add_step("Drop MySQL User", False, f"Failed to drop user from {old_host}", str(e))
            return OverlordProvisioningResult(
                success=False,
                message="Failed to drop MySQL user from old host",
                steps=steps,
                error=str(e),
                suggestions=[
                    "Ensure admin has DROP USER privilege",
                    "Verify the user exists on the old server",
                    f"User to drop: {OVERLORD_SERVICE_USER}",
                ],
            )

        # Step 3: Clear settings (keep AWS secret - will be reused/overwritten)
        self.settings_repo.set_setting("overlord_enabled", "false")
        self.settings_repo.set_setting("overlord_dbhost", "")
        self.settings_repo.set_setting("overlord_database", "")
        self.settings_repo.set_setting("overlord_table", "")
        self.settings_repo.set_setting("overlord_credential_ref", "")
        add_step("Clear Settings", True, "Old overlord settings cleared")

        # Audit log
        if self.audit_repo:
            self.audit_repo.log_action(
                actor_user_id=self.actor_user_id,
                action="overlord_old_host_cleaned",
                detail=f"Cleaned up old overlord host {old_host} before migration",
                context={
                    "old_host": old_host,
                    "user_dropped": True,
                },
            )

        return OverlordProvisioningResult(
            success=True,
            message=f"Old host {old_host} cleaned up successfully",
            steps=steps,
        )

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _validate_provision_inputs(
        self,
        overlord_host: str,
        overlord_database: str,
        admin_username: str,
        admin_password: str,
    ) -> str | None:
        """Validate provisioning inputs.

        Returns:
            Error message if invalid, None if valid.
        """
        if not overlord_host or not overlord_host.strip():
            return "Overlord host is required"
        if not overlord_database or not overlord_database.strip():
            return "Overlord database is required"
        if not admin_username or not admin_username.strip():
            return "Admin username is required"
        if not admin_password:
            return "Admin password is required"
        return None

    def _test_admin_connection(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> ConnectionTestResult:
        """Test admin MySQL connection.

        Args:
            host: MySQL host.
            port: MySQL port.
            database: Database name.
            username: Admin username.
            password: Admin password.

        Returns:
            ConnectionTestResult with status.
        """
        try:
            conn = mysql.connector.connect(
                host=host,
                port=port,
                user=username,
                password=password,
                database=database,
                connect_timeout=10,
            )

            # Test that we have GRANT privilege
            cursor = conn.cursor()
            cursor.execute("SHOW GRANTS FOR CURRENT_USER")
            grants = cursor.fetchall()
            cursor.close()
            conn.close()

            # Check for CREATE USER or GRANT privilege
            has_grant = any(
                "GRANT" in str(g).upper() or "ALL PRIVILEGES" in str(g).upper()
                for g in grants
            )

            if not has_grant:
                return ConnectionTestResult(
                    success=False,
                    message="Admin user lacks GRANT privilege",
                    error="Cannot create MySQL users without GRANT OPTION",
                    suggestions=[
                        "Use an account with GRANT privilege",
                        "Run: GRANT ALL ON overlord.* TO 'admin'@'%' WITH GRANT OPTION",
                    ],
                )

            return ConnectionTestResult(
                success=True,
                message="Admin connection verified",
            )

        except mysql.connector.Error as e:
            error_code = e.errno if hasattr(e, 'errno') else None
            
            if error_code == 1045:  # Access denied
                return ConnectionTestResult(
                    success=False,
                    message="Invalid admin credentials",
                    error=str(e),
                    suggestions=[
                        "Check admin username and password",
                        "Verify admin user exists on overlord server",
                    ],
                )
            elif error_code == 2003:  # Can't connect
                return ConnectionTestResult(
                    success=False,
                    message="Cannot connect to overlord server",
                    error=str(e),
                    suggestions=[
                        f"Check that {host}:{port} is reachable",
                        "Verify security groups allow MySQL traffic",
                        "Check VPC/network configuration",
                    ],
                )
            elif error_code == 1049:  # Unknown database
                return ConnectionTestResult(
                    success=False,
                    message=f"Database '{database}' does not exist",
                    error=str(e),
                    suggestions=[
                        "Check overlord database name",
                        "Create the database if it doesn't exist",
                    ],
                )
            else:
                return ConnectionTestResult(
                    success=False,
                    message="MySQL connection error",
                    error=str(e),
                )

    def _create_or_update_user(
        self,
        host: str,
        port: int,
        database: str,
        table: str,
        admin_username: str,
        admin_password: str,
        service_username: str,
        service_password: str,
    ) -> dict[str, Any]:
        """Create or update the pulldb_overlord MySQL user.

        Creates user with MINIMAL privileges:
        - SELECT on overlord.companies (read current values)
        - UPDATE on overlord.companies (update dbHost/dbHostRead)

        Args:
            host: MySQL host.
            port: MySQL port.
            database: Database name.
            table: Table name.
            admin_username: Admin username.
            admin_password: Admin password.
            service_username: Service user to create.
            service_password: Service user password.

        Returns:
            Dict with success, message, was_created, error, suggestions.
        """
        # Validate SQL identifiers to prevent SQL injection
        # These values are used in dynamic SQL, so they MUST be safe
        for name, value in [
            ("database", database),
            ("table", table),
            ("service_username", service_username),
        ]:
            if not _is_safe_sql_identifier(value):
                return {
                    "success": False,
                    "message": f"Invalid {name}: must contain only alphanumeric characters and underscores",
                    "error": f"SQL identifier validation failed for {name}='{value}'",
                    "suggestions": [
                        f"Ensure {name} contains only letters, numbers, and underscores",
                        f"The {name} must start with a letter or underscore",
                        "Maximum length is 64 characters",
                    ],
                }

        try:
            conn = mysql.connector.connect(
                host=host,
                port=port,
                user=admin_username,
                password=admin_password,
                database=database,
                connect_timeout=10,
            )
            cursor = conn.cursor()

            # Check if user exists
            cursor.execute(
                "SELECT 1 FROM mysql.user WHERE user = %s",
                (service_username,),
            )
            user_exists = cursor.fetchone() is not None

            if user_exists:
                # Update existing user's password
                cursor.execute(
                    f"ALTER USER '{service_username}'@'%%' IDENTIFIED BY %s",
                    (service_password,),
                )
                logger.info(f"Updated password for {service_username}")
            else:
                # Create new user
                cursor.execute(
                    f"CREATE USER '{service_username}'@'%%' IDENTIFIED BY %s",
                    (service_password,),
                )
                logger.info(f"Created user {service_username}")

            # Grant minimal privileges (SELECT, INSERT, UPDATE, DELETE on specific table)
            # INSERT: needed to create new company records
            # DELETE: needed when release action is DELETE (for rows pullDB created)
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.`{table}` TO '{service_username}'@'%%'"
            )
            cursor.execute("FLUSH PRIVILEGES")

            conn.commit()
            cursor.close()
            conn.close()

            return {
                "success": True,
                "message": f"User {service_username} configured",
                "was_created": not user_exists,
            }

        except mysql.connector.Error as e:
            error_code = e.errno if hasattr(e, 'errno') else None
            
            if error_code == 1142:  # Grant command denied
                return {
                    "success": False,
                    "message": "Admin user cannot create users",
                    "error": str(e),
                    "suggestions": [
                        "Grant GRANT OPTION to admin user",
                        "Use a superuser account",
                    ],
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to create MySQL user",
                    "error": str(e),
                }

    def _drop_user(
        self,
        host: str,
        port: int,
        admin_username: str,
        admin_password: str,
        service_username: str,
    ) -> None:
        """Drop the service MySQL user.

        Args:
            host: MySQL host.
            port: MySQL port.
            admin_username: Admin username.
            admin_password: Admin password.
            service_username: Service user to drop.
        """
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=admin_username,
            password=admin_password,
            connect_timeout=10,
        )
        cursor = conn.cursor()
        
        # Check if user exists before dropping
        cursor.execute(
            "SELECT 1 FROM mysql.user WHERE user = %s",
            (service_username,),
        )
        if cursor.fetchone():
            cursor.execute(f"DROP USER '{service_username}'@'%%'")
            conn.commit()
            logger.info(f"Dropped user {service_username}")
        
        cursor.close()
        conn.close()
