"""Secret rotation service for database host credentials.

This service provides atomic, verified credential rotation for MySQL hosts.
It follows the FAIL HARD principle - any failure is reported with full
diagnostic information and actionable suggestions.

WORKFLOW:
1. VALIDATION: Verify current credentials work, check privileges
2. GENERATION: Create new secure password
3. MYSQL UPDATE: Alter user password on MySQL server
4. VERIFICATION: Test new password works
5. AWS UPDATE: Update AWS Secrets Manager
6. FINAL VERIFY: Round-trip test (fetch from AWS, connect to MySQL)

The service handles rollback scenarios and provides manual fix instructions
when partial failures occur.

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError

from pulldb.infra.secrets import (
    CredentialResolver,
    safe_upsert_single_secret,
)
from pulldb.infra.timeouts import DEFAULT_MYSQL_CONNECT_TIMEOUT_API


logger = logging.getLogger(__name__)


# Password generation settings
DEFAULT_PASSWORD_LENGTH = 32
PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*"


@dataclass
class RotationResult:
    """Result of a secret rotation operation.

    Attributes:
        success: Whether the entire rotation completed successfully.
        message: Human-readable result message.
        error: Detailed error message if failed.
        error_code: MySQL or AWS error code if applicable.
        phase: The phase where failure occurred (if failed).
        suggestions: List of actionable suggestions on failure.
        manual_fix_required: If True, includes instructions for manual recovery.
        manual_fix_instructions: Instructions for manual recovery.
        rollback_attempted: Whether a rollback was attempted.
        rollback_success: Whether the rollback succeeded.
        timing: Dict with phase timing information.
        old_password_masked: Masked old password for logging.
        new_password_masked: Masked new password for logging.
    """

    success: bool
    message: str
    error: str | None = None
    error_code: int | str | None = None
    phase: str | None = None
    suggestions: list[str] | None = None
    manual_fix_required: bool = False
    manual_fix_instructions: str | None = None
    rollback_attempted: bool = False
    rollback_success: bool | None = None
    timing: dict[str, float] = field(default_factory=dict)
    old_password_masked: str | None = None
    new_password_masked: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "message": self.message,
            "error": self.error,
            "error_code": self.error_code,
            "phase": self.phase,
            "suggestions": self.suggestions,
            "manual_fix_required": self.manual_fix_required,
            "manual_fix_instructions": self.manual_fix_instructions,
            "rollback_attempted": self.rollback_attempted,
            "rollback_success": self.rollback_success,
            "timing": self.timing,
        }


def _mask_password(password: str) -> str:
    """Mask password for logging, showing first 2 and last 2 chars."""
    if not password or len(password) < 6:
        return "***"
    return f"{password[:2]}{'*' * (len(password) - 4)}{password[-2:]}"


def _generate_secure_password(length: int = DEFAULT_PASSWORD_LENGTH) -> str:
    """Generate a cryptographically secure password.

    Args:
        length: Password length (default 32 for strong entropy).

    Returns:
        Random password with letters, digits, and safe special chars.
    """
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def _test_mysql_connection(
    host: str,
    port: int,
    username: str,
    password: str,
    check_alter_user: bool = False,
) -> tuple[bool, str | None]:
    """Test MySQL connection and optionally verify ALTER USER privilege.

    Args:
        host: MySQL server hostname.
        port: MySQL server port.
        username: MySQL username.
        password: MySQL password.
        check_alter_user: If True, verify user has ALTER USER privilege.

    Returns:
        Tuple of (success, error_message).
    """
    conn = None
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_API,
        )

        if check_alter_user:
            cursor = conn.cursor()
            try:
                # Check SHOW GRANTS to see if user can modify passwords
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = cursor.fetchall()
                grant_str = " ".join(str(g) for g in grants).upper()

                # Check for privileges that allow ALTER USER
                has_privilege = any(
                    p in grant_str
                    for p in [
                        "ALL PRIVILEGES",
                        "SUPER",
                        "CREATE USER",
                        "WITH GRANT OPTION",
                    ]
                )
                if not has_privilege:
                    return False, "User lacks ALTER USER privilege"
            finally:
                cursor.close()

        return True, None

    except MySQLError as e:
        error_code = e.errno if hasattr(e, "errno") else None
        if error_code == 1045:
            return False, f"Access denied (invalid credentials)"
        elif error_code == 2003:
            return False, f"Cannot connect to MySQL server at {host}:{port}"
        else:
            return False, f"MySQL error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                # Connection cleanup failure - connection may already be closed
                logger.debug("Failed to close MySQL connection in test function", exc_info=True)


def _alter_mysql_password(
    host: str,
    port: int,
    current_username: str,
    current_password: str,
    new_password: str,
) -> tuple[bool, str | None]:
    """Execute ALTER USER to change the password.

    Auto-detects the MySQL user's host specifier from mysql.user table.
    Falls back to '%' if detection fails.

    Args:
        host: MySQL server hostname.
        port: MySQL server port.
        current_username: MySQL username.
        current_password: Current password for authentication.
        new_password: New password to set.

    Returns:
        Tuple of (success, error_message).
    """
    conn = None
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=current_username,
            password=current_password,
            connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_API,
            autocommit=True,
        )
        cursor = conn.cursor()

        # Auto-detect the user's host specifier from mysql.user
        # This handles both 'user@localhost' and 'user@%' cases
        user_host = "%"  # Default fallback
        try:
            cursor.execute(
                "SELECT Host FROM mysql.user WHERE User = %s ORDER BY Host LIMIT 1",
                (current_username,),
            )
            row = cursor.fetchone()
            if row:
                user_host = str(row[0])  # type: ignore[index]
                logger.debug(f"Detected MySQL user host: {current_username}@{user_host}")
        except MySQLError:
            # If we can't query mysql.user (permissions), fall back to '%'
            logger.debug(f"Could not detect user host, using default: {current_username}@%")

        # Execute ALTER USER with detected host
        cursor.execute(
            f"ALTER USER %s@%s IDENTIFIED BY %s",
            (current_username, user_host, new_password),
        )
        cursor.execute("FLUSH PRIVILEGES")
        cursor.close()

        return True, None

    except MySQLError as e:
        error_code = e.errno if hasattr(e, "errno") else None
        if error_code == 1396:
            return False, f"User '{current_username}' does not exist in MySQL"
        elif error_code == 1045:
            return False, "Access denied - current password may be incorrect"
        elif error_code == 1227:
            return False, "Access denied - user lacks ALTER USER privilege"
        else:
            return False, f"MySQL error ({error_code}): {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                # Connection cleanup failure - connection may already be closed
                logger.debug("Failed to close MySQL connection in alter function", exc_info=True)


def rotate_host_secret(
    host_id: str,
    hostname: str,
    credential_ref: str,
    new_password: str | None = None,
    password_length: int = DEFAULT_PASSWORD_LENGTH,
    aws_profile: str | None = None,
    aws_region: str | None = None,
) -> RotationResult:
    """Rotate credentials for a database host.

    This function performs an atomic credential rotation:
    1. Fetches current credentials from AWS Secrets Manager
    2. Validates current credentials work on MySQL
    3. Verifies user has ALTER USER privilege
    4. Generates or uses provided new password
    5. Updates MySQL user password
    6. Verifies new password works
    7. Updates AWS Secrets Manager
    8. Verifies round-trip (AWS → MySQL)

    FAIL HARD: Any failure returns detailed diagnostic information.
    If MySQL update succeeds but AWS update fails, provides manual fix instructions.

    Args:
        host_id: UUID of the host (for audit logging).
        hostname: Hostname for logging purposes.
        credential_ref: AWS Secrets Manager credential reference
                       (e.g., "aws-secretsmanager:/pulldb/mysql/dev-db-01").
        new_password: Explicit new password. If None, generates random password.
        password_length: Length of generated password (default 32).
        aws_profile: AWS profile name for Secrets Manager access.
        aws_region: AWS region for Secrets Manager access.

    Returns:
        RotationResult with success status and detailed information.
    """
    timing: dict[str, float] = {}
    start_time = time.time()

    # Validate credential_ref format
    if not credential_ref or not credential_ref.startswith("aws-secretsmanager:"):
        return RotationResult(
            success=False,
            message="Invalid credential reference",
            error=f"credential_ref must start with 'aws-secretsmanager:', got: {credential_ref}",
            phase="validation",
            suggestions=["Verify the host has a valid AWS Secrets Manager credential reference"],
        )

    # Extract secret path
    secret_path = credential_ref.replace("aws-secretsmanager:", "")
    if not secret_path:
        return RotationResult(
            success=False,
            message="Empty secret path",
            error="Could not extract secret path from credential_ref",
            phase="validation",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 1: FETCH CURRENT CREDENTIALS
    # ─────────────────────────────────────────────────────────────────────────
    phase_start = time.time()
    logger.info(f"[rotate] Phase 1: Fetching current credentials for {hostname}")

    try:
        resolver = CredentialResolver(aws_profile=aws_profile, aws_region=aws_region)
        current_creds = resolver.resolve(credential_ref)
    except Exception as e:
        return RotationResult(
            success=False,
            message="Failed to fetch current credentials from AWS",
            error=str(e),
            phase="fetch_credentials",
            suggestions=[
                f"Verify secret exists: {secret_path}",
                "Check AWS credentials and IAM permissions",
                "Run: aws secretsmanager get-secret-value --secret-id <secret-path>",
            ],
        )

    timing["fetch_credentials"] = time.time() - phase_start

    mysql_host = current_creds.host
    mysql_port = current_creds.port
    mysql_username = current_creds.username
    current_password = current_creds.password

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 2: VALIDATE CURRENT CREDENTIALS
    # ─────────────────────────────────────────────────────────────────────────
    phase_start = time.time()
    logger.info(f"[rotate] Phase 2: Validating current credentials for {hostname}")

    success, error = _test_mysql_connection(
        host=mysql_host,
        port=mysql_port,
        username=mysql_username,
        password=current_password,
        check_alter_user=True,
    )

    if not success:
        return RotationResult(
            success=False,
            message="Current credentials are invalid",
            error=error,
            phase="validate_current",
            suggestions=[
                "Current stored credentials may have been changed outside this system",
                f"Test manually: mysql -h {mysql_host} -P {mysql_port} -u {mysql_username} -p",
                "Consider resetting the credentials in AWS Secrets Manager first",
            ],
        )

    timing["validate_current"] = time.time() - phase_start

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 3: GENERATE NEW PASSWORD
    # ─────────────────────────────────────────────────────────────────────────
    phase_start = time.time()
    logger.info(f"[rotate] Phase 3: Generating new password for {hostname}")

    if new_password:
        generated_password = new_password
    else:
        generated_password = _generate_secure_password(password_length)

    timing["generate_password"] = time.time() - phase_start

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 4: UPDATE MYSQL PASSWORD
    # ─────────────────────────────────────────────────────────────────────────
    phase_start = time.time()
    logger.info(f"[rotate] Phase 4: Updating MySQL password for {hostname}")

    success, error = _alter_mysql_password(
        host=mysql_host,
        port=mysql_port,
        current_username=mysql_username,
        current_password=current_password,
        new_password=generated_password,
    )

    if not success:
        return RotationResult(
            success=False,
            message="Failed to update MySQL password",
            error=error,
            phase="mysql_update",
            suggestions=[
                "MySQL password was NOT changed",
                "No manual intervention needed",
                "Fix the underlying issue and retry",
            ],
        )

    timing["mysql_update"] = time.time() - phase_start

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 5: VERIFY NEW PASSWORD
    # ─────────────────────────────────────────────────────────────────────────
    phase_start = time.time()
    logger.info(f"[rotate] Phase 5: Verifying new password for {hostname}")

    success, error = _test_mysql_connection(
        host=mysql_host,
        port=mysql_port,
        username=mysql_username,
        password=generated_password,
    )

    if not success:
        # MySQL update succeeded but new password doesn't work - attempt rollback
        logger.error(f"[rotate] New password verification failed, attempting rollback")

        rollback_success, rollback_error = _alter_mysql_password(
            host=mysql_host,
            port=mysql_port,
            current_username=mysql_username,
            current_password=generated_password,  # Try with new password
            new_password=current_password,  # Restore old password
        )

        if not rollback_success:
            # Try with old password in case new wasn't actually set
            rollback_success, _ = _alter_mysql_password(
                host=mysql_host,
                port=mysql_port,
                current_username=mysql_username,
                current_password=current_password,
                new_password=current_password,
            )

        return RotationResult(
            success=False,
            message="New password verification failed",
            error=error,
            phase="verify_new_password",
            rollback_attempted=True,
            rollback_success=rollback_success,
            manual_fix_required=not rollback_success,
            manual_fix_instructions=(
                f"CRITICAL: MySQL may be in inconsistent state.\n"
                f"Test manually: mysql -h {mysql_host} -P {mysql_port} -u {mysql_username} -p\n"
                f"If neither password works, manual MySQL admin intervention required."
                if not rollback_success
                else None
            ),
            suggestions=[
                "Rollback was " + ("successful" if rollback_success else "FAILED"),
                "Original password should still work" if rollback_success else "Manual intervention required",
            ],
        )

    timing["verify_new_password"] = time.time() - phase_start

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 6: UPDATE AWS SECRETS MANAGER
    # ─────────────────────────────────────────────────────────────────────────
    phase_start = time.time()
    logger.info(f"[rotate] Phase 6: Updating AWS Secrets Manager for {hostname}")

    secret_data = {
        "host": mysql_host,
        "port": mysql_port,
        "username": mysql_username,
        "password": generated_password,
    }

    result = safe_upsert_single_secret(
        secret_path=secret_path,
        secret_data=secret_data,
        aws_profile=aws_profile,
        aws_region=aws_region,
        update_only=True,
    )

    if not result.success:
        # CRITICAL: MySQL was updated but AWS failed
        # Provide detailed manual fix instructions
        return RotationResult(
            success=False,
            message="CRITICAL: MySQL updated but AWS Secrets Manager failed",
            error=result.error,
            phase="aws_update",
            manual_fix_required=True,
            manual_fix_instructions=(
                f"CRITICAL: MySQL password was changed but AWS was NOT updated.\n"
                f"\n"
                f"Manual fix required - update AWS secret:\n"
                f"  aws secretsmanager put-secret-value \\\n"
                f"    --secret-id '{secret_path}' \\\n"
                f"    --secret-string '{json.dumps(secret_data)}'\n"
                f"\n"
                f"Or via AWS Console:\n"
                f"  1. Go to Secrets Manager\n"
                f"  2. Find secret: {secret_path}\n"
                f"  3. Update password value\n"
                f"\n"
                f"If you need to revert MySQL instead:\n"
                f"  ALTER USER '{mysql_username}'@'<host>' IDENTIFIED BY '<old-password>';\n"
                f"  -- Replace <host> with 'localhost' or '%' depending on your user setup\n"
                f"  FLUSH PRIVILEGES;"
            ),
            suggestions=[
                "MySQL password WAS changed - services may fail until AWS is updated",
                "Follow manual fix instructions above",
            ],
            old_password_masked=_mask_password(current_password),
            new_password_masked=_mask_password(generated_password),
        )

    timing["aws_update"] = time.time() - phase_start

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 7: FINAL VERIFICATION (Round-trip)
    # ─────────────────────────────────────────────────────────────────────────
    phase_start = time.time()
    logger.info(f"[rotate] Phase 7: Final round-trip verification for {hostname}")

    try:
        # Create a NEW resolver to ensure fresh fetch (no boto3 client caching)
        fresh_resolver = CredentialResolver(aws_profile=aws_profile, aws_region=aws_region)
        fresh_creds = fresh_resolver.resolve(credential_ref)

        # Verify it matches what we set
        if fresh_creds.password != generated_password:
            return RotationResult(
                success=False,
                message="AWS verification mismatch",
                error="Password in AWS doesn't match what was set",
                phase="final_verify",
                suggestions=[
                    "AWS secret may have been modified by another process",
                    "Check for concurrent secret modifications",
                ],
            )

        # Final MySQL test with AWS credentials
        success, error = _test_mysql_connection(
            host=fresh_creds.host,
            port=fresh_creds.port,
            username=fresh_creds.username,
            password=fresh_creds.password,
        )

        if not success:
            return RotationResult(
                success=False,
                message="Final round-trip verification failed",
                error=error,
                phase="final_verify",
                suggestions=[
                    "Credentials in AWS may not match MySQL",
                    "Check for concurrent modifications",
                ],
            )

    except Exception as e:
        return RotationResult(
            success=False,
            message="Final verification failed",
            error=str(e),
            phase="final_verify",
            suggestions=["Rotation may have succeeded - verify manually"],
        )

    timing["final_verify"] = time.time() - phase_start

    # ─────────────────────────────────────────────────────────────────────────
    # SUCCESS
    # ─────────────────────────────────────────────────────────────────────────
    total_time = time.time() - start_time
    timing["total"] = total_time

    logger.info(
        f"[rotate] SUCCESS: Rotated credentials for {hostname} "
        f"({mysql_username}@{mysql_host}) in {total_time:.2f}s"
    )

    return RotationResult(
        success=True,
        message=f"Successfully rotated credentials for {hostname}",
        timing=timing,
        old_password_masked=_mask_password(current_password),
        new_password_masked=_mask_password(generated_password),
    )
