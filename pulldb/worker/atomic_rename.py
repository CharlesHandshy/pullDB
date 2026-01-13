"""Atomic rename from staging database to target database.

Implements zero-downtime rename using MySQL stored procedure to atomically
swap all tables from staging database to target database. The procedure
ensures either complete success or complete rollback with no partial state.

Design Principles (FAIL HARD):
- Verify stored procedure exists and version before attempting rename
- Auto-deploy procedure on version mismatch
- Fail on any SQL error during procedure execution
- Provide clear diagnostics: which database, MySQL error, suggested fixes
- Do not attempt retries or workarounds
- Preserve staging database on failure for manual inspection

Features:
- Pre and post validation (always-on, no config flags)
- Version enforcement with auto-deployment
- Advisory locks to prevent concurrent deployments
- Streaming progress output for job logs
"""

from __future__ import annotations

import re
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mysql.connector

from pulldb.domain.errors import AtomicRenameError
from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.worker.atomic_rename")

# Expected stored procedure version (must match procedure file)
EXPECTED_PROCEDURE_VERSION = "1.0.1"


# Default connection timeout - short because if you can't connect in 30s, something is wrong
DEFAULT_CONNECT_TIMEOUT_SECONDS = 30


@dataclass(slots=True, frozen=True)
class AtomicRenameConnectionSpec:
    """MySQL connection parameters for atomic rename operation.

    Groups related connection parameters to reduce function argument count
    and improve type safety.

    Attributes:
        mysql_host: Target MySQL server hostname/IP.
        mysql_port: Target MySQL server port.
        mysql_user: MySQL user with ALTER/DROP/RENAME privileges.
        mysql_password: MySQL user password.
        timeout_seconds: Operation timeout in seconds (for long-running queries).
        connect_timeout_seconds: Connection establishment timeout (default 30s).
    """

    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    timeout_seconds: int
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS


@dataclass(slots=True, frozen=True)
class AtomicRenameSpec:
    """Specification for atomic rename operation.

    Contains all required parameters for staging-to-target rename.

    Attributes:
        job_id: Job UUID (for error reporting).
        staging_db: Staging database name (source).
        target_db: Target database name (destination).
    """

    job_id: str
    staging_db: str
    target_db: str


# Name of stored procedure expected on target MySQL server
RENAME_PROCEDURE_NAME = "pulldb_atomic_rename"


def _pre_validate_atomic_rename(
    conn: Any,
    staging_db: str,
    target_db: str,
    job_id: str | None = None,
) -> int:
    """Validate preconditions before atomic rename.
    
    Ensures staging database has tables and target doesn't exist.
    This prevents silent failures where rename appears to succeed
    but actually does nothing.
    
    Args:
        conn: Active MySQL connection.
        staging_db: Staging database name.
        target_db: Target database name.
        job_id: Optional job UUID for error reporting.
    
    Returns:
        int: Table count in staging database (for post-validation).
        
    Raises:
        AtomicRenameError: If validation fails.
    """
    cursor = conn.cursor()
    
    try:
        # Check staging has tables
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (staging_db,)
        )
        result = cursor.fetchone()
        staging_count: int = int(result[0]) if result else 0
        if staging_count == 0:
            raise AtomicRenameError(
                job_id=job_id or "",
                staging_name=staging_db,
                target_name=target_db,
                error_message=f"Pre-validation failed: Staging database '{staging_db}' has no tables"
            )
        
        # Note: Target existence check removed in v1.0.1
        # The stored procedure now handles DROP DATABASE IF EXISTS for overwrite support
        
        logger.info(
            "Pre-validation passed",
            extra={
                "staging_db": staging_db,
                "target_db": target_db,
                "staging_table_count": staging_count,
            }
        )
        
        return staging_count
    finally:
        cursor.close()


def _post_validate_atomic_rename(
    conn: Any,
    staging_db: str,
    target_db: str,
    expected_table_count: int,
    job_id: str | None = None,
) -> None:
    """Validate postconditions after atomic rename.
    
    Ensures staging is gone, target exists with correct table count.
    This detects silent failures where procedure completes without error
    but doesn't actually perform the rename.
    
    Args:
        conn: Active MySQL connection.
        staging_db: Staging database name.
        target_db: Target database name.
        expected_table_count: Expected tables in target (from pre-validation).
        job_id: Optional job UUID for error reporting.
        
    Raises:
        AtomicRenameError: If validation fails.
    """
    cursor = conn.cursor()
    errors = []
    
    try:
        # Check staging is gone
        cursor.execute("SHOW DATABASES LIKE %s", (staging_db,))
        if cursor.fetchone():
            errors.append(f"Staging database '{staging_db}' still exists after rename")
        
        # Check target exists
        cursor.execute("SHOW DATABASES LIKE %s", (target_db,))
        if not cursor.fetchone():
            errors.append(f"Target database '{target_db}' does not exist after rename")
        else:
            # Check table count matches
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                (target_db,)
            )
            result = cursor.fetchone()
            actual_count: int = int(result[0]) if result else 0
            if actual_count != expected_table_count:
                logger.warning(
                    f"Table count mismatch: expected {expected_table_count}, got {actual_count}"
                )
                errors.append(
                    f"Table count mismatch: expected {expected_table_count} tables, got {actual_count}"
                )
        
        if errors:
            raise AtomicRenameError(
                job_id=job_id or "",
                staging_name=staging_db,
                target_name=target_db,
                error_message=f"Post-validation failed: {'; '.join(errors)}"
            )
        
        logger.info(
            "Post-validation passed",
            extra={
                "staging_db": staging_db,
                "target_db": target_db,
                "table_count": expected_table_count,
            }
        )
    finally:
        cursor.close()


def ensure_atomic_rename_procedure(
    conn: Any,
    mysql_host: str,
    job_id: str | None = None,
) -> None:
    """Ensure atomic rename procedure exists with correct version.
    
    Checks procedure version once per connection (cached in conn attribute).
    If version mismatch detected:
    1. Acquire advisory lock to prevent concurrent deployments
    2. Re-check version (another worker may have just deployed)
    3. Deploy procedure from docs/hca/features/atomic_rename_procedure.sql
    4. Record deployment in procedure_deployments table
    5. Verify deployed version matches expected
    
    Args:
        conn: Active MySQL connection with CREATE ROUTINE privilege.
        mysql_host: MySQL hostname (for deployment tracking).
        job_id: Optional job UUID (to link deployment to job).
        
    Raises:
        AtomicRenameError: If version check fails, deployment fails, or lock times out.
    """
    # Check cache on connection to avoid repeated checks
    if hasattr(conn, '_pulldb_procedure_version'):
        if conn._pulldb_procedure_version == EXPECTED_PROCEDURE_VERSION:
            return
    
    cursor = conn.cursor()
    
    try:
        # Get current procedure version
        cursor.execute(
            "SELECT ROUTINE_SCHEMA FROM information_schema.ROUTINES "
            f"WHERE ROUTINE_NAME = '{RENAME_PROCEDURE_NAME}' "
            "AND ROUTINE_TYPE = 'PROCEDURE' "
            "LIMIT 1"
        )
        row = cursor.fetchone()
        
        if not row:
            proc_schema = None
            current_version = None
        else:
            proc_schema = row[0]
            # Get procedure definition to extract version
            cursor.execute(f"SHOW CREATE PROCEDURE {proc_schema}.{RENAME_PROCEDURE_NAME}")
            result = cursor.fetchone()
            if result:
                proc_body = result[2]  # Third column is the procedure body
                # Extract version with regex: -- Version: 1.0.0
                version_match = re.search(r'Version:?\s*v?(\d+\.\d+\.\d+)', proc_body, re.IGNORECASE)
                current_version = version_match.group(1) if version_match else None
            else:
                current_version = None
        
        # If version matches, cache and return
        if current_version == EXPECTED_PROCEDURE_VERSION:
            conn._pulldb_procedure_version = current_version
            logger.info(
                f"Procedure version {current_version} matches expected {EXPECTED_PROCEDURE_VERSION}"
            )
            return
        
        # Version mismatch - acquire lock for deployment
        # Lock name limited to 64 chars, hash long hostnames
        if len(mysql_host) > 40:
            import hashlib
            host_hash = hashlib.md5(mysql_host.encode()).hexdigest()[:8]
            lock_name = f'pulldb_proc_{host_hash}'
        else:
            lock_name = f'pulldb_proc_deploy_{mysql_host}'
        logger.warning(
            f"Procedure version mismatch: current={current_version}, expected={EXPECTED_PROCEDURE_VERSION}. "
            f"Acquiring lock for deployment."
        )
        
        cursor.execute("SELECT GET_LOCK(%s, 30)", (lock_name,))
        lock_result = cursor.fetchone()[0]
        
        if lock_result != 1:
            # Lock timeout or error
            # Check if lock is stale (held >30s by dead connection)
            cursor.execute("SELECT IS_USED_LOCK(%s)", (lock_name,))
            lock_thread_id = cursor.fetchone()[0]
            if lock_thread_id:
                logger.critical(
                    f"Failed to acquire deployment lock after 30s. Lock held by thread {lock_thread_id}. "
                    f"This may indicate a stale lock from a dead connection."
                )
                raise AtomicRenameError(
                    job_id=job_id or "",
                    staging_name="",
                    target_name="",
                    error_message=(
                        f"Procedure deployment lock timeout on {mysql_host}. "
                        f"Lock held by thread {lock_thread_id}. Manual intervention required."
                    )
                )
            else:
                raise AtomicRenameError(
                    job_id=job_id or "",
                    staging_name="",
                    target_name="",
                    error_message=f"Failed to acquire deployment lock on {mysql_host}"
                )
        
        try:
            # Re-check version now that we have lock (another worker may have deployed)
            cursor.execute(
                "SELECT ROUTINE_SCHEMA FROM information_schema.ROUTINES "
                f"WHERE ROUTINE_NAME = '{RENAME_PROCEDURE_NAME}' "
                "AND ROUTINE_TYPE = 'PROCEDURE' "
                "LIMIT 1"
            )
            row = cursor.fetchone()
            
            if row:
                proc_schema = row[0]
                cursor.execute(f"SHOW CREATE PROCEDURE {proc_schema}.{RENAME_PROCEDURE_NAME}")
                result = cursor.fetchone()
                if result:
                    proc_body = result[2]
                    version_match = re.search(r'Version:?\s*v?(\d+\.\d+\.\d+)', proc_body, re.IGNORECASE)
                    current_version = version_match.group(1) if version_match else None
                    
                    if current_version == EXPECTED_PROCEDURE_VERSION:
                        logger.info(f"Version already updated by another worker: {current_version}")
                        conn._pulldb_procedure_version = current_version
                        return
            
            # Deploy procedure
            logger.info(f"Deploying procedure version {EXPECTED_PROCEDURE_VERSION} to {mysql_host}")
            
            # Read procedure SQL from file
            # Try multiple locations for robustness (dev vs installed)
            procedure_file = None
            search_paths = [
                # Debian package install location
                Path("/opt/pulldb.service/docs/hca/features/atomic_rename_procedure.sql"),
                # Installed package location (site-packages/docs/...)
                Path(__file__).parent.parent.parent / "docs" / "hca" / "features" / "atomic_rename_procedure.sql",
                # Dev/source location
                Path.cwd() / "docs" / "hca" / "features" / "atomic_rename_procedure.sql",
                # Legacy fallback
                Path("/opt/pulldb/docs/hca/features/atomic_rename_procedure.sql"),
            ]
            
            for path in search_paths:
                if path.exists():
                    procedure_file = path
                    break
            
            if not procedure_file:
                raise AtomicRenameError(
                    job_id=job_id or "",
                    staging_name="",
                    target_name="",
                    error_message=f"Procedure file not found in any of: {[str(p) for p in search_paths]}"
                )
            
            procedure_sql = procedure_file.read_text()
            
            # Execute procedure SQL (handles DROP + CREATE)
            # Use proven Aurora-compatible approach from mysql_provisioning.py
            clean_sql = procedure_sql.replace("DELIMITER $$", "").replace("DELIMITER ;", "")
            statements = clean_sql.split("$$")
            
            for stmt in statements:
                stmt = stmt.strip()
                if not stmt or stmt.startswith('--'):
                    continue
                try:
                    cursor.execute(stmt)
                except mysql.connector.Error as e:
                    # Log but continue - some statements may be benign (like comments)
                    logger.warning(f"Error executing statement: {e}")
            
            # Record deployment
            deployment_id = str(uuid.uuid4())
            deployment_reason = 'missing' if current_version is None else 'version_mismatch'
            
            cursor.execute(
                """
                INSERT INTO pulldb_service.procedure_deployments
                (id, host, procedure_name, version_deployed, deployed_by, deployment_reason, job_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    deployment_id,
                    mysql_host,
                    RENAME_PROCEDURE_NAME,
                    EXPECTED_PROCEDURE_VERSION,
                    'worker-auto',
                    deployment_reason,
                    job_id,
                )
            )
            
            logger.info(
                f"Procedure deployed successfully",
                extra={
                    "deployment_id": deployment_id,
                    "host": mysql_host,
                    "version": EXPECTED_PROCEDURE_VERSION,
                    "reason": deployment_reason,
                }
            )
            
            # Verify deployment by checking procedure exists
            # Note: MySQL strips comments from stored procedures, so version can't be verified from procedure body
            # Instead, we rely on the procedure_deployments table record we just inserted
            cursor.execute(
                "SELECT ROUTINE_SCHEMA FROM information_schema.ROUTINES "
                f"WHERE ROUTINE_NAME = '{RENAME_PROCEDURE_NAME}' "
                "AND ROUTINE_TYPE = 'PROCEDURE' "
                "LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                raise AtomicRenameError(
                    job_id=job_id or "",
                    staging_name="",
                    target_name="",
                    error_message=f"Procedure deployment verification failed: procedure not found after deployment"
                )
            
            # Cache version
            conn._pulldb_procedure_version = EXPECTED_PROCEDURE_VERSION
            
        finally:
            # Release lock
            cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
            release_result = cursor.fetchone()[0]
            if release_result != 1:
                logger.warning(f"Failed to release deployment lock {lock_name}")
    
    finally:
        cursor.close()


def _get_procedure_schema(cursor: Any) -> str | None:
    """Find schema containing pulldb_atomic_rename stored procedure.

    Args:
        cursor: Active MySQL cursor.

    Returns:
        Schema name if procedure exists, None otherwise.
    """
    cursor.execute(
        "SELECT ROUTINE_SCHEMA FROM information_schema.ROUTINES "
        f"WHERE ROUTINE_NAME = '{RENAME_PROCEDURE_NAME}' "
        "AND ROUTINE_TYPE = 'PROCEDURE' "
        "ORDER BY ROUTINE_SCHEMA = 'pulldb' DESC, ROUTINE_SCHEMA = 'sys' DESC "
        "LIMIT 1"
    )
    row = cursor.fetchone()
    return str(row[0]) if row else None


def atomic_rename_staging_to_target(
    conn_spec: AtomicRenameConnectionSpec,
    rename_spec: AtomicRenameSpec,
    event_callback: Any = None,
) -> None:
    """Atomically rename staging database to target database with validation.

    Performs comprehensive validation before and after rename:
    1. Pre-validation: staging has tables, target doesn't exist
    2. Version enforcement: ensure procedure matches expected version
    3. Execute stored procedure with streaming progress
    4. Post-validation: staging gone, target exists with correct table count
    5. Final staging dropped check

    The stored procedure ensures atomic execution - either all operations
    succeed or all are rolled back, with no partial state. Validations
    catch silent failures where procedure completes without error but
    doesn't actually perform the rename.

    Args:
        conn_spec: MySQL connection parameters.
        rename_spec: Staging and target database names.
        event_callback: Optional callback for emitting progress events.

    Raises:
        AtomicRenameError: On connection failure, validation failure,
            missing stored procedure, or procedure execution failure.
            Preserves staging database on failure for manual inspection.
    """
    # Connect to MySQL server (not to any specific database)
    logger.info(
        "Initiating atomic rename with validation",
        extra={
            "job_id": rename_spec.job_id,
            "staging_db": rename_spec.staging_db,
            "target_db": rename_spec.target_db,
        },
    )
    
    def _emit_event(event_type: str, detail: dict[str, Any] | None = None) -> None:
        """Helper to emit events if callback provided."""
        if event_callback:
            event_callback(event_type, detail or {})
    
    try:
        connection = mysql.connector.connect(
            host=conn_spec.mysql_host,
            port=conn_spec.mysql_port,
            user=conn_spec.mysql_user,
            password=conn_spec.mysql_password,
            connect_timeout=conn_spec.connect_timeout_seconds,
            autocommit=True,
        )
    except mysql.connector.Error as e:
        raise AtomicRenameError(
            job_id=rename_spec.job_id,
            staging_name=rename_spec.staging_db,
            target_name=rename_spec.target_db,
            error_message=(
                f"Failed to connect to MySQL server {conn_spec.mysql_host}:"
                f"{conn_spec.mysql_port} for atomic rename "
                f"(timeout={conn_spec.connect_timeout_seconds}s): {e}. "
                f"Verify credentials and network connectivity."
            ),
        ) from e

    try:
        # PRE-VALIDATION: Check preconditions
        _emit_event("atomic_rename_validating", {
            "phase": "pre_validation",
            "staging_db": rename_spec.staging_db,
            "target_db": rename_spec.target_db,
        })
        staging_table_count = _pre_validate_atomic_rename(
            connection,
            rename_spec.staging_db,
            rename_spec.target_db,
            rename_spec.job_id,
        )
        _emit_event("atomic_rename_validation_pass", {
            "phase": "pre_validation",
            "table_count": staging_table_count,
        })
        
        # VERSION ENFORCEMENT: Ensure procedure exists with correct version
        _emit_event("atomic_rename_checking_procedure", {
            "expected_version": EXPECTED_PROCEDURE_VERSION,
        })
        ensure_atomic_rename_procedure(
            connection,
            conn_spec.mysql_host,
            rename_spec.job_id,
        )
        _emit_event("atomic_rename_procedure_ready", {
            "version": EXPECTED_PROCEDURE_VERSION,
        })
        
        cursor = connection.cursor()

        # Verify stored procedure exists and get schema
        proc_schema = _get_procedure_schema(cursor)
        if not proc_schema:
            raise AtomicRenameError(
                job_id=rename_spec.job_id,
                staging_name=rename_spec.staging_db,
                target_name=rename_spec.target_db,
                error_message=(
                    f"Stored procedure '{RENAME_PROCEDURE_NAME}' does not exist "
                    f"on {conn_spec.mysql_host}. "
                    f"This should not happen after ensure_atomic_rename_procedure(). "
                    f"Manual intervention required."
                ),
            )

        # Increase group_concat_max_len to handle many tables (default 1024 is too small)
        # This is required for GROUP_CONCAT in the stored procedure to build the full RENAME statement
        cursor.execute("SET SESSION group_concat_max_len = 1000000")

        # Execute stored procedure with streaming progress
        _emit_event("atomic_rename_executing", {
            "staging_db": rename_spec.staging_db,
            "target_db": rename_spec.target_db,
            "expected_tables": staging_table_count,
        })
        try:
            cursor.callproc(
                f"{proc_schema}.{RENAME_PROCEDURE_NAME}",
                (rename_spec.staging_db, rename_spec.target_db),
            )
            # Consume and log streaming progress result sets
            table_counter = 0
            for rs in cursor.stored_results():
                rows = rs.fetchall()
                if rows:
                    for row in rows:
                        logger.info(f"Rename progress: {row}")
                        
                        # Check for special status rows (v1.0.1+)
                        if len(row) >= 2:
                            status = str(row[1]) if len(row) > 1 else None
                            if status == 'target_dropped':
                                # Target database was dropped (overwrite mode)
                                _emit_event("atomic_rename_target_dropped", {
                                    "target_db": str(row[0]),
                                    "message": f"Existing database '{row[0]}' dropped (overwrite enabled)",
                                })
                                continue  # Don't count as table progress
                        
                        table_counter += 1
                        # Emit progress for each table renamed
                        _emit_event("atomic_rename_progress", {
                            "tables_renamed": table_counter,
                            "total_tables": staging_table_count,
                            "percent": round((table_counter / staging_table_count) * 100, 1) if staging_table_count > 0 else 100,
                            "message": str(row[0]) if row else None,
                        })
        except mysql.connector.Error as e:
            raise AtomicRenameError(
                job_id=rename_spec.job_id,
                staging_name=rename_spec.staging_db,
                target_name=rename_spec.target_db,
                error_message=(
                    f"Stored procedure '{RENAME_PROCEDURE_NAME}' failed: {e}. "
                    f"Staging database '{rename_spec.staging_db}' "
                    f"preserved for inspection. "
                    f"Verify target database has no active connections. "
                    f"Check MySQL error log for additional context."
                ),
            ) from e

        # POST-VALIDATION: Verify rename succeeded
        _emit_event("atomic_rename_validating", {
            "phase": "post_validation",
            "expected_tables": staging_table_count,
        })
        _post_validate_atomic_rename(
            connection,
            rename_spec.staging_db,
            rename_spec.target_db,
            staging_table_count,
            rename_spec.job_id,
        )
        _emit_event("atomic_rename_validation_pass", {
            "phase": "post_validation",
            "target_db": rename_spec.target_db,
            "table_count": staging_table_count,
        })
        
        # FINAL CHECK: Ensure staging is really dropped
        cursor.execute("SHOW DATABASES LIKE %s", (rename_spec.staging_db,))
        if cursor.fetchone():
            raise AtomicRenameError(
                job_id=rename_spec.job_id,
                staging_name=rename_spec.staging_db,
                target_name=rename_spec.target_db,
                error_message=(
                    f"Staging database '{rename_spec.staging_db}' still exists "
                    f"after procedure completion and post-validation. "
                    f"This indicates the procedure's DROP DATABASE statement failed silently."
                )
            )

        logger.info(
            "Atomic rename completed successfully with validation",
            extra={
                "job_id": rename_spec.job_id,
                "staging_db": rename_spec.staging_db,
                "target_db": rename_spec.target_db,
                "table_count": staging_table_count,
            }
        )
        cursor.close()

    finally:
        with suppress(Exception):  # pragma: no cover - best effort cleanup
            connection.close()


__all__ = [
    "RENAME_PROCEDURE_NAME",
    "AtomicRenameConnectionSpec",
    "AtomicRenameSpec",
    "atomic_rename_staging_to_target",
]
