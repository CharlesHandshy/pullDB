"""Staging database lifecycle management for pullDB restore workflow.

This module handles the staging-to-production rename pattern:
1. Generate staging database name from target and job_id
2. Clean up orphaned staging databases from previous restores
3. Verify staging database doesn't exist after cleanup
4. Coordinate atomic rename from staging to production (placeholder)

The staging pattern provides zero-downtime restores with validation before
cutover and rollback capability.
"""

import re
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass

import mysql.connector

from pulldb.domain.errors import StagingError


# MySQL database name length limit (63 chars but we use 64 for legacy compatibility)
MAX_DATABASE_NAME_LENGTH = 64

# Staging suffix length: underscore + 12 hex chars from job_id
STAGING_SUFFIX_LENGTH = 13

# Job ID prefix length for staging suffix (hex characters)
JOB_ID_PREFIX_LENGTH = 12

# Pattern for matching orphaned staging databases: {target}_[0-9a-f]{12}
STAGING_PATTERN_TEMPLATE = r"^{target}_[0-9a-f]{{12}}$"


@dataclass(slots=True, frozen=True)
class StagingConnectionSpec:
    """MySQL connection parameters for staging database operations.

    Groups related connection parameters to reduce function argument count
    and improve type safety.

    Attributes:
        mysql_host: Target MySQL server hostname/IP.
        mysql_port: Target MySQL server port.
        mysql_user: MySQL user with CREATE/DROP/RENAME database privileges.
        mysql_password: MySQL user password.
        timeout_seconds: Connection and query timeout in seconds.
    """

    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    timeout_seconds: int


@dataclass(slots=True, frozen=True)
class StagingResult:
    """Result of staging database lifecycle operations.

    Attributes:
        staging_db: Generated staging database name.
        target_db: Final target database name.
        orphans_dropped: List of orphaned staging databases that were dropped.
    """

    staging_db: str
    target_db: str
    orphans_dropped: list[str]


def generate_staging_name(target_db: str, job_id: str) -> str:
    """Generate staging database name from target and job_id.

    Format: {target}_{job_id_first_12_chars}
    Example: jdoecustomer_550e8400e29b

    Args:
        target_db: Final target database name (must be <= 51 chars).
        job_id: Job UUID (will use first 12 hex characters).

    Returns:
        Staging database name.

    Raises:
        StagingError: If target_db exceeds maximum length (51 chars) or
            job_id is too short (< 12 chars).
    """
    max_target_length = MAX_DATABASE_NAME_LENGTH - STAGING_SUFFIX_LENGTH

    if len(target_db) > max_target_length:
        raise StagingError(
            f"Target database name '{target_db}' is {len(target_db)} chars, "
            f"exceeds maximum of {max_target_length} chars. "
            f"Staging name would exceed MySQL's {MAX_DATABASE_NAME_LENGTH} char limit. "
            f"Choose a shorter customer ID or username."
        )

    if len(job_id) < JOB_ID_PREFIX_LENGTH:
        raise StagingError(
            f"Job ID '{job_id}' is too short ({len(job_id)} chars), "
            f"need at least {JOB_ID_PREFIX_LENGTH} characters for staging suffix."
        )

    # Strip hyphens from UUID and take first 12 hex chars
    job_id_clean = job_id.replace("-", "").lower()
    job_id_prefix = job_id_clean[:JOB_ID_PREFIX_LENGTH]

    # Validate job_id prefix contains only hex characters
    if len(job_id_prefix) < JOB_ID_PREFIX_LENGTH:
        raise StagingError(
            f"Job ID '{job_id}' has insufficient hex characters after "
            f"removing hyphens ({len(job_id_prefix)} chars). "
            f"Expected at least {JOB_ID_PREFIX_LENGTH} hex digits."
        )

    if not re.match(r"^[0-9a-f]{12}$", job_id_prefix):
        raise StagingError(
            f"Job ID prefix '{job_id_prefix}' contains non-hexadecimal characters. "
            f"Expected 12 hex digits from job_id."
        )

    staging_name = f"{target_db}_{job_id_prefix}"

    return staging_name


def _find_orphaned_staging_databases(
    target_db: str,
    all_databases: Sequence[str],
) -> list[str]:
    """(Private) Identify orphaned staging databases matching target pattern.

    Internal helper; prefer :func:`find_orphaned_staging_databases` for
    external usage and tests.
    """
    pattern = STAGING_PATTERN_TEMPLATE.format(target=re.escape(target_db))
    regex = re.compile(pattern)
    return sorted([db for db in all_databases if regex.match(db)])


def find_orphaned_staging_databases(
    target_db: str,
    all_databases: Sequence[str],
) -> list[str]:
    """Public wrapper to list orphaned staging databases for a target.

    Args:
        target_db: Target database name to match.
        all_databases: Collection of all database names.

    Returns:
        Sorted list of orphaned staging database names.
    """
    return _find_orphaned_staging_databases(target_db, all_databases)


def cleanup_orphaned_staging(
    conn_spec: StagingConnectionSpec,
    target_db: str,
    job_id: str,
) -> StagingResult:
    """Clean up orphaned staging databases and prepare for restore.

    Steps:
    1. Generate staging database name from target + job_id
    2. List all databases on target MySQL server
    3. Find orphaned staging databases matching {target}_[0-9a-f]{12}
    4. Drop all orphaned staging databases
    5. Verify staging database doesn't exist after cleanup

    Args:
        conn_spec: MySQL connection parameters.
        target_db: Final target database name.
        job_id: Job UUID for generating staging name.

    Returns:
        StagingResult with staging name and dropped orphans list.

    Raises:
        StagingError: If staging database exists after cleanup, connection
            fails, or drop operations fail.
    """
    staging_db = generate_staging_name(target_db, job_id)

    # Connect to MySQL server (not to any specific database)
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
        raise StagingError(
            f"Failed to connect to MySQL server {conn_spec.mysql_host}:"
            f"{conn_spec.mysql_port} for staging cleanup: {e}. "
            f"Verify credentials and network connectivity."
        ) from e

    try:
        cursor = connection.cursor()

        # List all databases
        try:
            cursor.execute("SHOW DATABASES")
            rows = cursor.fetchall()
            all_databases = [str(row[0]) for row in rows]  # type: ignore[index]
        except mysql.connector.Error as e:
            raise StagingError(
                f"Failed to list databases on {conn_spec.mysql_host}: {e}. "
                f"Verify user {conn_spec.mysql_user} has SHOW DATABASES privilege."
            ) from e

        # Find orphaned staging databases
        orphans = _find_orphaned_staging_databases(target_db, all_databases)

        # Drop each orphaned database
        for orphan_db in orphans:
            try:
                # Use parameterized identifier (MySQL 8.0+ supports this pattern)
                drop_sql = f"DROP DATABASE IF EXISTS `{orphan_db}`"
                cursor.execute(drop_sql)
            except mysql.connector.Error as e:
                raise StagingError(
                    f"Failed to drop orphaned staging database '{orphan_db}': {e}. "
                    f"Verify user {conn_spec.mysql_user} has DROP privilege."
                ) from e

        # Verify staging database doesn't exist after cleanup
        cursor.execute("SHOW DATABASES")
        remaining_rows = cursor.fetchall()
        remaining_databases = [str(row[0]) for row in remaining_rows]  # type: ignore[index]

        if staging_db in remaining_databases:
            raise StagingError(
                f"Staging database '{staging_db}' still exists after cleanup. "
                f"This should never happen - indicates concurrency issue or "
                f"privilege problem preventing DROP."
            )

        cursor.close()

    finally:
        with suppress(Exception):
            connection.close()

    return StagingResult(
        staging_db=staging_db,
        target_db=target_db,
        orphans_dropped=orphans,
    )
