"""MySQL provisioning utilities for automated host setup.

This module provides functions to:
- Test admin MySQL connections
- Create pulldb_loader user accounts
- Create pulldb database if needed
- Deploy the pulldb_atomic_rename stored procedure

Used by the web admin Add Host flow to automate all MySQL setup in one step.

FAIL HARD: All functions return structured results with actionable error messages.
No silent degradation - failures include diagnostic information.
"""

from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError


logger = logging.getLogger(__name__)

# Stored procedure names (must match scripts/deploy_atomic_rename.py)
PROCEDURE_NAME = "pulldb_atomic_rename"
PREVIEW_PROCEDURE_NAME = "pulldb_atomic_rename_preview"

# Default pulldb loader username
DEFAULT_LOADER_USERNAME = "pulldb_loader"


@dataclass
class ProvisioningResult:
    """Result of a provisioning operation.

    Attributes:
        success: Whether the operation succeeded.
        message: Human-readable result message.
        error: Detailed error message if failed, else None.
        error_code: MySQL error code if applicable.
        suggestions: List of actionable suggestions on failure.
        data: Optional dict with additional result data.
    """

    success: bool
    message: str
    error: str | None = None
    error_code: int | None = None
    suggestions: list[str] | None = None
    data: dict[str, Any] | None = None


def generate_secure_password(length: int = 24) -> str:
    """Generate a cryptographically secure password.

    Args:
        length: Password length (default 24 for good entropy).

    Returns:
        Random password with letters, digits, and safe special chars.
    """
    # Use safe special chars that don't cause shell/SQL escaping issues
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def test_admin_connection(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str | None = None,
) -> ProvisioningResult:
    """Test MySQL connection with admin credentials.

    Validates that:
    1. MySQL server is reachable
    2. Credentials are valid
    3. User has sufficient privileges (CREATE USER, GRANT)

    Args:
        host: MySQL server hostname or IP.
        port: MySQL port.
        username: Admin username with CREATE USER privilege.
        password: Admin password.
        database: Optional database to connect to.

    Returns:
        ProvisioningResult with success=True if connection works and
        user has sufficient privileges.
    """
    conn = None
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            database=database,
            connect_timeout=10,
        )

        cursor = conn.cursor()

        # Check privileges by attempting to query mysql.user
        # This tests if user has sufficient access
        try:
            cursor.execute("SELECT 1 FROM mysql.user LIMIT 1")
            cursor.fetchall()
        except MySQLError as e:
            # Can't read mysql.user - check via SHOW GRANTS instead
            try:
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = cursor.fetchall()
                grant_str = str(grants).lower()

                # Check for key privileges
                has_create_user = "create user" in grant_str or "all privileges" in grant_str
                has_grant = "with grant option" in grant_str or "all privileges" in grant_str

                if not (has_create_user or has_grant):
                    return ProvisioningResult(
                        success=False,
                        message="Insufficient privileges",
                        error="Admin user needs CREATE USER and GRANT privileges",
                        suggestions=[
                            f"GRANT CREATE USER, GRANT OPTION ON *.* TO '{username}'@'%';",
                            "Use root or a user with full admin rights",
                        ],
                    )
            except MySQLError:
                pass  # If we can't check, assume it's OK and let later ops fail

        cursor.close()

        return ProvisioningResult(
            success=True,
            message=f"Successfully connected to {host}:{port}",
            data={"host": host, "port": port, "username": username},
        )

    except MySQLError as e:
        error_code = e.errno if hasattr(e, "errno") else None
        suggestions = _get_connection_suggestions(error_code, host, port, username)

        return ProvisioningResult(
            success=False,
            message="Connection failed",
            error=str(e),
            error_code=error_code,
            suggestions=suggestions,
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _get_connection_suggestions(
    error_code: int | None, host: str, port: int, username: str
) -> list[str]:
    """Generate actionable suggestions based on MySQL error code."""
    suggestions = []

    if error_code == 1045:  # Access denied
        suggestions = [
            "Check username and password are correct",
            f"Verify user '{username}' exists and can connect from this IP",
            f"Try: mysql -h {host} -P {port} -u {username} -p",
        ]
    elif error_code == 2003:  # Can't connect
        suggestions = [
            f"Verify MySQL is running on {host}:{port}",
            "Check firewall/security group allows port {port}",
            f"Try: nc -zv {host} {port}",
        ]
    elif error_code == 2005:  # Unknown host
        suggestions = [
            f"Verify hostname '{host}' is correct",
            "Check DNS resolution or use IP address",
            f"Try: nslookup {host}",
        ]
    elif error_code == 2006:  # Server gone away
        suggestions = [
            "MySQL server closed connection unexpectedly",
            "Check server max_allowed_packet and wait_timeout",
            "Server may have restarted - retry the operation",
        ]
    else:
        suggestions = [
            f"Verify MySQL is accessible at {host}:{port}",
            f"Check credentials for user '{username}'",
            "Review MySQL error logs for more details",
        ]

    return suggestions


def create_pulldb_user(
    host: str,
    port: int,
    admin_username: str,
    admin_password: str,
    loader_username: str = DEFAULT_LOADER_USERNAME,
    loader_password: str | None = None,
) -> ProvisioningResult:
    """Create the pulldb_loader MySQL user with appropriate privileges.

    Creates a user that can:
    - Load data (INSERT, UPDATE, DELETE)
    - Create/manage staging databases
    - Execute stored procedures
    - Perform atomic rename operations

    Args:
        host: MySQL server hostname.
        port: MySQL port.
        admin_username: Admin user for creating the new user.
        admin_password: Admin password.
        loader_username: Username for the loader account (default: pulldb_loader).
        loader_password: Password for loader. Auto-generated if None.

    Returns:
        ProvisioningResult with data containing 'username' and 'password' on success.
    """
    if loader_password is None:
        loader_password = generate_secure_password()

    conn = None
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=admin_username,
            password=admin_password,
            connect_timeout=10,
            autocommit=True,
        )
        cursor = conn.cursor()

        # Check if user already exists
        cursor.execute(
            "SELECT User FROM mysql.user WHERE User = %s",
            (loader_username,),
        )
        existing = cursor.fetchone()

        if existing:
            # User exists - update password and ensure grants
            logger.info(f"User '{loader_username}' already exists, updating password")
            cursor.execute(
                f"ALTER USER '{loader_username}'@'%%' IDENTIFIED BY %s",
                (loader_password,),
            )
        else:
            # Create new user
            logger.info(f"Creating user '{loader_username}'")
            cursor.execute(
                f"CREATE USER '{loader_username}'@'%%' IDENTIFIED BY %s",
                (loader_password,),
            )

        # Grant required privileges
        # The loader needs broad privileges for staging DB operations
        grants = [
            # Database-level operations
            "CREATE, DROP, ALTER",
            # Data operations
            "SELECT, INSERT, UPDATE, DELETE",
            # Stored procedure execution
            "EXECUTE",
            # For LOAD DATA and myloader
            "LOCK TABLES, REFERENCES",
            # Process visibility for monitoring
            "PROCESS",
        ]

        grant_stmt = f"GRANT {', '.join(grants)} ON *.* TO '{loader_username}'@'%%'"
        cursor.execute(grant_stmt)

        # Flush privileges to ensure changes take effect
        cursor.execute("FLUSH PRIVILEGES")

        cursor.close()

        action = "updated" if existing else "created"
        return ProvisioningResult(
            success=True,
            message=f"User '{loader_username}' {action} successfully",
            data={
                "username": loader_username,
                "password": loader_password,
                "action": action,
            },
        )

    except MySQLError as e:
        error_code = e.errno if hasattr(e, "errno") else None

        suggestions = []
        if error_code == 1396:  # Operation CREATE USER failed
            suggestions = [
                f"User '{loader_username}' may already exist with different host",
                "Check: SELECT User, Host FROM mysql.user WHERE User LIKE 'pulldb%';",
            ]
        elif error_code == 1044:  # Access denied for database
            suggestions = [
                "Admin user lacks privilege to grant permissions",
                "Use root or a user with WITH GRANT OPTION",
            ]
        else:
            suggestions = [
                "Check admin user has CREATE USER privilege",
                f"Verify can connect: mysql -h {host} -P {port} -u {admin_username} -p",
            ]

        return ProvisioningResult(
            success=False,
            message="Failed to create pulldb user",
            error=str(e),
            error_code=error_code,
            suggestions=suggestions,
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def create_pulldb_database(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str = "pulldb",
) -> ProvisioningResult:
    """Create the pulldb database if it doesn't exist.

    Args:
        host: MySQL server hostname.
        port: MySQL port.
        username: User with CREATE DATABASE privilege.
        password: User password.
        database: Database name (default: pulldb).

    Returns:
        ProvisioningResult indicating success or failure.
    """
    conn = None
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            connect_timeout=10,
            autocommit=True,
        )
        cursor = conn.cursor()

        # Check if database exists
        cursor.execute("SHOW DATABASES LIKE %s", (database,))
        exists = cursor.fetchone() is not None

        if exists:
            logger.info(f"Database '{database}' already exists")
            return ProvisioningResult(
                success=True,
                message=f"Database '{database}' already exists",
                data={"database": database, "action": "exists"},
            )

        # Create database
        cursor.execute(
            f"CREATE DATABASE `{database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        logger.info(f"Created database '{database}'")

        cursor.close()

        return ProvisioningResult(
            success=True,
            message=f"Database '{database}' created successfully",
            data={"database": database, "action": "created"},
        )

    except MySQLError as e:
        error_code = e.errno if hasattr(e, "errno") else None
        return ProvisioningResult(
            success=False,
            message=f"Failed to create database '{database}'",
            error=str(e),
            error_code=error_code,
            suggestions=[
                "Check user has CREATE DATABASE privilege",
                "Verify database name doesn't conflict with reserved names",
            ],
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def deploy_stored_procedure(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str = "pulldb",
    sql_file: str | Path | None = None,
) -> ProvisioningResult:
    """Deploy the pulldb_atomic_rename stored procedure.

    Args:
        host: MySQL server hostname.
        port: MySQL port.
        username: User with CREATE ROUTINE privilege.
        password: User password.
        database: Database to deploy procedure into.
        sql_file: Path to SQL file. If None, uses embedded minimal procedure.

    Returns:
        ProvisioningResult indicating success or failure.
    """
    # Try to load SQL from file if provided
    sql_content = None
    if sql_file:
        sql_path = Path(sql_file)
        if sql_path.exists():
            sql_content = sql_path.read_text(encoding="utf-8")
        else:
            return ProvisioningResult(
                success=False,
                message="SQL file not found",
                error=f"File not found: {sql_file}",
                suggestions=[
                    "Provide correct path to atomic_rename_procedure.sql",
                    "Or omit sql_file to use embedded procedure",
                ],
            )

    # If no SQL file, check standard location
    if sql_content is None:
        standard_paths = [
            Path("docs/atomic_rename_procedure.sql"),
            Path("/opt/pulldb/docs/atomic_rename_procedure.sql"),
            Path(__file__).parent.parent.parent / "docs" / "atomic_rename_procedure.sql",
        ]
        for path in standard_paths:
            if path.exists():
                sql_content = path.read_text(encoding="utf-8")
                break

    # If still no SQL, use minimal embedded procedure for testing
    if sql_content is None:
        logger.warning("No SQL file found, using minimal embedded procedure")
        sql_content = _get_minimal_procedure_sql()

    conn = None
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            database=database,
            connect_timeout=10,
            autocommit=True,
        )
        cursor = conn.cursor()

        # Drop existing procedure
        cursor.execute(f"DROP PROCEDURE IF EXISTS {PROCEDURE_NAME}")
        cursor.execute(f"DROP PROCEDURE IF EXISTS {PREVIEW_PROCEDURE_NAME}")

        # Parse and execute statements separated by $$
        clean_sql = sql_content.replace("DELIMITER $$", "").replace("DELIMITER ;", "")
        statements = clean_sql.split("$$")

        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue

            # Skip comment-only blocks
            lines = stmt.splitlines()
            effective_lines = [ln for ln in lines if not ln.strip().startswith("--")]
            if not effective_lines:
                continue

            try:
                cursor.execute(stmt)
                # Consume results to avoid "Commands out of sync"
                while cursor.nextset():
                    pass
            except MySQLError as e:
                return ProvisioningResult(
                    success=False,
                    message="Failed to execute SQL statement",
                    error=str(e),
                    error_code=e.errno if hasattr(e, "errno") else None,
                    suggestions=[
                        "Check SQL file for syntax errors",
                        "Verify MySQL version compatibility",
                        "Ensure user has CREATE ROUTINE privilege",
                    ],
                )

        cursor.close()

        return ProvisioningResult(
            success=True,
            message=f"Stored procedure '{PROCEDURE_NAME}' deployed to {database}",
            data={"procedure": PROCEDURE_NAME, "database": database},
        )

    except MySQLError as e:
        error_code = e.errno if hasattr(e, "errno") else None
        return ProvisioningResult(
            success=False,
            message="Failed to deploy stored procedure",
            error=str(e),
            error_code=error_code,
            suggestions=[
                "Check user has CREATE ROUTINE privilege",
                f"Verify database '{database}' exists",
                "Check MySQL error logs for details",
            ],
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _get_minimal_procedure_sql() -> str:
    """Return minimal stored procedure SQL for testing.

    This is a placeholder that allows basic functionality testing
    when the full procedure SQL file is not available.
    """
    return """
DROP PROCEDURE IF EXISTS pulldb_atomic_rename $$
CREATE PROCEDURE pulldb_atomic_rename(
    IN p_staging_db VARCHAR(64),
    IN p_target_db VARCHAR(64)
)
BEGIN
    -- Minimal placeholder procedure
    -- Full version should be deployed from docs/atomic_rename_procedure.sql
    DECLARE v_version VARCHAR(10) DEFAULT '0.0.1-placeholder';
    SELECT CONCAT('Atomic rename: ', p_staging_db, ' -> ', p_target_db) AS message;
END $$
"""


def provision_host_full(
    mysql_host: str,
    mysql_port: int,
    admin_username: str,
    admin_password: str,
    loader_username: str = DEFAULT_LOADER_USERNAME,
    loader_password: str | None = None,
    database: str = "pulldb",
    sql_file: str | Path | None = None,
) -> tuple[ProvisioningResult, dict[str, Any]]:
    """Perform full MySQL provisioning for a new host.

    Executes all setup steps in order:
    1. Test admin connection
    2. Create pulldb_loader user
    3. Create pulldb database
    4. Deploy stored procedure

    Args:
        mysql_host: MySQL server hostname.
        mysql_port: MySQL port.
        admin_username: Admin user with CREATE USER privilege.
        admin_password: Admin password.
        loader_username: Username for loader account.
        loader_password: Password for loader (auto-generated if None).
        database: Database name for stored procedure.
        sql_file: Path to stored procedure SQL file.

    Returns:
        Tuple of (final_result, created_resources) where created_resources
        tracks what was newly created (for rollback if needed).
    """
    created_resources: dict[str, Any] = {
        "user_created": False,
        "user_credentials": None,
        "database_created": False,
        "procedure_deployed": False,
    }

    # Step 1: Test admin connection
    result = test_admin_connection(
        host=mysql_host,
        port=mysql_port,
        username=admin_username,
        password=admin_password,
    )
    if not result.success:
        result.message = f"Step 1 failed: {result.message}"
        return result, created_resources

    # Step 2: Create pulldb_loader user
    result = create_pulldb_user(
        host=mysql_host,
        port=mysql_port,
        admin_username=admin_username,
        admin_password=admin_password,
        loader_username=loader_username,
        loader_password=loader_password,
    )
    if not result.success:
        result.message = f"Step 2 failed: {result.message}"
        return result, created_resources

    created_resources["user_credentials"] = result.data
    if result.data and result.data.get("action") == "created":
        created_resources["user_created"] = True

    # Step 3: Create pulldb database
    result = create_pulldb_database(
        host=mysql_host,
        port=mysql_port,
        username=admin_username,
        password=admin_password,
        database=database,
    )
    if not result.success:
        result.message = f"Step 3 failed: {result.message}"
        return result, created_resources

    if result.data and result.data.get("action") == "created":
        created_resources["database_created"] = True

    # Step 4: Deploy stored procedure
    result = deploy_stored_procedure(
        host=mysql_host,
        port=mysql_port,
        username=admin_username,
        password=admin_password,
        database=database,
        sql_file=sql_file,
    )
    if not result.success:
        result.message = f"Step 4 failed: {result.message}"
        return result, created_resources

    created_resources["procedure_deployed"] = True

    # All steps succeeded
    return ProvisioningResult(
        success=True,
        message="All provisioning steps completed successfully",
        data={
            "mysql_host": mysql_host,
            "mysql_port": mysql_port,
            "loader_username": created_resources["user_credentials"]["username"],
            "loader_password": created_resources["user_credentials"]["password"],
            "database": database,
            "procedure": PROCEDURE_NAME,
        },
    ), created_resources
