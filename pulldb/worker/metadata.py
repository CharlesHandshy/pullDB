"""Metadata table injection for restored databases.

Adds a `pullDB` table to the staging database after successful restore and
post-SQL execution, capturing job details, timing, backup source, and
post-SQL execution status for audit trail and diagnostics.

Design Principles (FAIL HARD):
- Fail on any SQL error during table creation or data insertion.
- Provide clear diagnostics: which operation failed and MySQL error details.
- Do not attempt retries or workarounds.
- Table schema is fixed and immutable for prototype (no migrations).
"""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

import mysql.connector

from pulldb.domain.errors import MetadataInjectionError
from pulldb.infra.logging import get_logger
from pulldb.worker.post_sql import PostSQLExecutionResult


logger = get_logger("pulldb.worker.metadata")


# Default connection timeout - short because if you can't connect in 30s, something is wrong
DEFAULT_CONNECT_TIMEOUT_SECONDS = 30


@dataclass(slots=True, frozen=True)
class MetadataConnectionSpec:
    """MySQL connection parameters for metadata table injection.

    Groups related connection parameters to reduce function argument count
    and improve type safety.

    Attributes:
        staging_db: Staging database name where metadata table will be created.
        mysql_host: Target MySQL server hostname/IP.
        mysql_port: Target MySQL server port.
        mysql_user: MySQL user with CREATE TABLE and INSERT privileges.
        mysql_password: MySQL user password.
        timeout_seconds: Operation timeout in seconds (for long-running queries).
        connect_timeout_seconds: Connection establishment timeout (default 30s).
    """

    staging_db: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    timeout_seconds: int
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS


@dataclass(slots=True, frozen=True)
class MetadataSpec:
    """Specification for metadata table injection.

    Contains all required data to populate the pullDB metadata table.

    Attributes:
        job_id: Job UUID.
        owner_username: Username of job owner.
        target_db: Final target database name.
        backup_filename: S3 backup filename used for restore.
        restore_started_at: UTC timestamp when restore began.
        restore_completed_at: UTC timestamp when restore completed.
        post_sql_result: Post-SQL execution result (if any).
    """

    job_id: str
    owner_username: str
    target_db: str
    backup_filename: str
    restore_started_at: datetime
    restore_completed_at: datetime
    post_sql_result: PostSQLExecutionResult | None


# pullDB metadata table schema (fixed for prototype)
_CREATE_METADATA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `pullDB` (
    `job_id` VARCHAR(36) NOT NULL COMMENT 'UUID of restore job',
    `restored_by` VARCHAR(255) NOT NULL COMMENT 'Username who initiated restore',
    `restored_at` DATETIME(6) NOT NULL COMMENT 'UTC timestamp of restore completion',
    `target_database` VARCHAR(64) NOT NULL COMMENT 'Final target database name',
    `backup_filename` VARCHAR(512) NOT NULL COMMENT 'S3 backup filename used',
    `restore_duration_seconds` DECIMAL(10, 3) NOT NULL COMMENT 'Total restore duration',
    `post_sql_report` JSON NULL COMMENT 'Post-SQL execution status (JSON)',
    PRIMARY KEY (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='pullDB restore metadata - do not modify';
"""


def inject_metadata_table(
    conn_spec: MetadataConnectionSpec,
    metadata_spec: MetadataSpec,
) -> None:
    """Inject pullDB metadata table into staging database.

    Creates the `pullDB` table if it doesn't exist and inserts a record
    with restore metadata including job details, timing, and post-SQL status.

    Args:
        conn_spec: MySQL connection parameters.
        metadata_spec: Metadata to insert into table.

    Raises:
        MetadataInjectionError: On connection failure, table creation failure,
            or insert failure. Preserves original MySQL error for diagnostics.
    """
    # Connect to staging database
    logger.info(
        "Injecting metadata table",
        extra={
            "job_id": metadata_spec.job_id,
            "staging_db": conn_spec.staging_db,
            "target_db": metadata_spec.target_db,
        },
    )
    try:
        connection = mysql.connector.connect(
            host=conn_spec.mysql_host,
            port=conn_spec.mysql_port,
            user=conn_spec.mysql_user,
            password=conn_spec.mysql_password,
            database=conn_spec.staging_db,
            connect_timeout=conn_spec.connect_timeout_seconds,
            autocommit=True,
        )
    except mysql.connector.Error as e:
        raise MetadataInjectionError(
            job_id=metadata_spec.job_id,
            operation="connect",
            error_message=(
                f"Failed to connect to staging database '{conn_spec.staging_db}' "
                f"on {conn_spec.mysql_host}:{conn_spec.mysql_port} "
                f"(timeout={conn_spec.connect_timeout_seconds}s): {e}. "
                f"Verify credentials and database exists."
            ),
        ) from e

    try:
        cursor = connection.cursor()

        # Create pullDB table if not exists
        try:
            cursor.execute(_CREATE_METADATA_TABLE_SQL)
        except mysql.connector.Error as e:
            raise MetadataInjectionError(
                job_id=metadata_spec.job_id,
                operation="create_table",
                error_message=(
                    f"Failed to create pullDB metadata table in "
                    f"'{conn_spec.staging_db}': {e}. "
                    f"Verify user {conn_spec.mysql_user} has CREATE TABLE privilege."
                ),
            ) from e

        # Prepare post-SQL report JSON
        post_sql_json = None
        if metadata_spec.post_sql_result:
            post_sql_json = json.dumps(
                {
                    "scripts_executed": [
                        {
                            "script_name": s.script_name,
                            "started_at": s.started_at.isoformat(),
                            "completed_at": s.completed_at.isoformat(),
                            "duration_seconds": s.duration_seconds,
                            "rows_affected": s.rows_affected,
                        }
                        for s in metadata_spec.post_sql_result.scripts_executed
                    ],
                    "total_duration_seconds": (
                        metadata_spec.post_sql_result.total_duration_seconds
                    ),
                }
            )

        # Calculate restore duration
        restore_duration = (
            metadata_spec.restore_completed_at - metadata_spec.restore_started_at
        ).total_seconds()

        # Insert metadata record
        insert_sql = """
            INSERT INTO `pullDB` (
                job_id,
                restored_by,
                restored_at,
                target_database,
                backup_filename,
                restore_duration_seconds,
                post_sql_report
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        try:
            cursor.execute(
                insert_sql,
                (
                    metadata_spec.job_id,
                    metadata_spec.owner_username,
                    metadata_spec.restore_completed_at,
                    metadata_spec.target_db,
                    metadata_spec.backup_filename,
                    restore_duration,
                    post_sql_json,
                ),
            )
        except mysql.connector.Error as e:
            raise MetadataInjectionError(
                job_id=metadata_spec.job_id,
                operation="insert",
                error_message=(
                    f"Failed to insert metadata record into pullDB table "
                    f"in '{conn_spec.staging_db}': {e}. "
                    f"Verify table schema matches expected structure."
                ),
            ) from e

        logger.info("Metadata injection successful")
        cursor.close()

    finally:
        with suppress(Exception):  # pragma: no cover - best effort cleanup
            connection.close()


__all__ = [
    "MetadataConnectionSpec",
    "MetadataSpec",
    "inject_metadata_table",
]
