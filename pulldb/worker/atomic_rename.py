"""Atomic rename from staging database to target database.

Implements zero-downtime rename using MySQL stored procedure to atomically
swap all tables from staging database to target database. The procedure
ensures either complete success or complete rollback with no partial state.

Design Principles (FAIL HARD):
- Verify stored procedure exists before attempting rename
- Fail on any SQL error during procedure execution
- Provide clear diagnostics: which database, MySQL error, suggested fixes
- Do not attempt retries or workarounds
- Preserve staging database on failure for manual inspection

Deferred / Future Enhancements:
- Stored procedure deployment automation
- Version checking for procedure compatibility
- Parallel rename for very large databases (100+ tables)
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import mysql.connector

from pulldb.domain.errors import AtomicRenameError
from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.worker.atomic_rename")


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
        timeout_seconds: Connection and query timeout in seconds.
    """

    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    timeout_seconds: int


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
) -> None:
    """Atomically rename staging database to target database.

    Executes stored procedure `pulldb_atomic_rename` which performs:
    1. Verify staging database exists
    2. Drop target database if exists (optional based on overwrite flag)
    3. Rename staging database to target database
    4. Verify target database exists after rename

    The stored procedure ensures atomic execution - either all operations
    succeed or all are rolled back, with no partial state.

    Args:
        conn_spec: MySQL connection parameters.
        rename_spec: Staging and target database names.

    Raises:
        AtomicRenameError: On connection failure, missing stored procedure,
            or procedure execution failure. Preserves original MySQL error.
    """
    # Connect to MySQL server (not to any specific database)
    logger.info(
        "Initiating atomic rename",
        extra={
            "job_id": rename_spec.job_id,
            "staging_db": rename_spec.staging_db,
            "target_db": rename_spec.target_db,
        },
    )
    try:
        connection = mysql.connector.connect(
            host=conn_spec.mysql_host,
            port=conn_spec.mysql_port,
            user=conn_spec.mysql_user,
            password=conn_spec.mysql_password,
            connect_timeout=conn_spec.timeout_seconds,
            autocommit=True,
        )
    except mysql.connector.Error as e:
        raise AtomicRenameError(
            job_id=rename_spec.job_id,
            staging_name=rename_spec.staging_db,
            target_name=rename_spec.target_db,
            error_message=(
                f"Failed to connect to MySQL server {conn_spec.mysql_host}:"
                f"{conn_spec.mysql_port} for atomic rename: {e}. "
                f"Verify credentials and network connectivity."
            ),
        ) from e

    try:
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
                    f"Deploy procedure using script in "
                    f"docs/atomic_rename_procedure.sql. "
                    f"Contact DBA for deployment assistance."
                ),
            )

        # Increase group_concat_max_len to handle many tables (default 1024 is too small)
        # This is required for GROUP_CONCAT in the stored procedure to build the full RENAME statement
        cursor.execute("SET SESSION group_concat_max_len = 1000000")

        # Execute stored procedure
        try:
            cursor.callproc(
                f"{proc_schema}.{RENAME_PROCEDURE_NAME}",
                (rename_spec.staging_db, rename_spec.target_db),
            )
            # Consume any result sets to avoid "Unread result found" error
            for _ in cursor.stored_results():
                pass
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

        logger.info("Atomic rename successful")
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
