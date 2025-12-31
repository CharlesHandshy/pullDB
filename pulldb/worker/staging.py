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
from typing import Any, cast

import mysql.connector

from pulldb.domain.errors import StagingError
from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.worker.staging")


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
    """Drop all orphaned staging databases for the target before a new restore.

    Updated requirement: Any existing staging databases matching the pattern
    ``{target}_[0-9a-f]{12}`` MUST be dropped prior to starting a new job. We
    do not retain or reuse prior staging databases. This enforces FAIL HARD
    isolation and guarantees the workflow begins from a clean slate.

    Steps:
        1. Generate staging database name from target + job_id
        2. Connect to MySQL server (no specific database selected)
        3. List all databases
        4. Identify staging candidates matching pattern
        5. Drop all identified staging databases
        6. Re-list databases and verify generated staging name does not exist

    Args:
        conn_spec: MySQL connection parameters.
        target_db: Final target database name.
        job_id: Job UUID for generating staging name.

    Returns:
        StagingResult containing the generated staging database name, target
        name, and list of dropped orphan databases.

    Raises:
        StagingError: On connection failure, listing failure, drop failure, or
        staging name collision after cleanup.
    """
    staging_db = generate_staging_name(target_db, job_id)
    logger.info(
        "Starting staging cleanup",
        extra={
            "job_id": job_id,
            "target": target_db,
            "staging_db": staging_db,
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
        raise StagingError(
            "Failed to connect to MySQL server "
            f"{conn_spec.mysql_host}:{conn_spec.mysql_port} "
            f"for staging cleanup: {e}. "
            "Verify credentials and network connectivity."
        ) from e

    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW DATABASES")
            rows = cast(list[tuple[Any, ...]], cursor.fetchall())
            all_databases = [str(row[0]) for row in rows]
        except mysql.connector.Error as e:
            raise StagingError(
                f"Failed to list databases on {conn_spec.mysql_host}: {e}. "
                f"Verify user {conn_spec.mysql_user} has SHOW DATABASES privilege."
            ) from e

        staging_candidates = _find_orphaned_staging_databases(target_db, all_databases)
        orphans_dropped: list[str] = []

        if staging_candidates:
            logger.info(
                f"Found {len(staging_candidates)} orphaned staging databases",
                extra={"orphans": staging_candidates},
            )

        # Get databases with active connections (e.g., myloader still running)
        # We must not DROP these - they'll be cleaned up by subsequent jobs
        try:
            cursor.execute(
                "SELECT db FROM information_schema.processlist "
                "WHERE db IS NOT NULL GROUP BY db"
            )
            active_db_rows = cast(list[tuple[Any, ...]], cursor.fetchall())
            active_databases = {str(row[0]) for row in active_db_rows}
        except mysql.connector.Error:
            # If we can't check, assume none are active (fail-safe: DROP may block)
            active_databases = set()

        for orphan_db in staging_candidates:
            # Skip databases with active connections (myloader may still be running
            # from a canceled job - we let it finish rather than blocking on MDL)
            if orphan_db in active_databases:
                logger.info(
                    f"Skipping orphan database with active connections: {orphan_db}",
                    extra={"orphan_db": orphan_db, "reason": "active_connections"},
                )
                continue

            try:
                logger.info(f"Dropping orphaned database: {orphan_db}")
                cursor.execute(f"DROP DATABASE IF EXISTS `{orphan_db}`")
                orphans_dropped.append(orphan_db)
            except mysql.connector.Error as e:
                raise StagingError(
                    f"Failed to drop staging database '{orphan_db}': {e}. "
                    f"Verify user {conn_spec.mysql_user} has DROP privilege."
                ) from e

            # Collision check (should not occur - dropped above if existed)
        try:
            cursor.execute("SHOW DATABASES")
            remaining_rows = cast(list[tuple[Any, ...]], cursor.fetchall())
            remaining_databases = [str(row[0]) for row in remaining_rows]
        except mysql.connector.Error as e:
            raise StagingError(
                "Failed to re-list databases after cleanup on "
                f"{conn_spec.mysql_host}: {e}."
            ) from e

        if staging_db in remaining_databases:
            raise StagingError(
                f"Generated staging database name '{staging_db}' still exists after "
                "cleanup; concurrency issue or UUID collision detected. Retry "
                "with a new job id."
            )

        logger.info(
            "Staging cleanup complete",
            extra={
                "orphans_dropped_count": len(orphans_dropped),
                "orphans_dropped": orphans_dropped,
            },
        )

        cursor.close()
    finally:
        with suppress(Exception):
            connection.close()

    return StagingResult(
        staging_db=staging_db,
        target_db=target_db,
        orphans_dropped=orphans_dropped,
    )
