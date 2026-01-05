"""Scheduled staging database cleanup.

Background task to clean up abandoned staging databases across all db_hosts.
This catches edge cases where a user doesn't re-restore the same target,
preventing automatic cleanup via the job-triggered mechanism.

MANDATE: Safety-first approach with multiple verification steps before deletion.

CLEANUP PHILOSOPHY:
1. Job-based cleanup: Only delete staging DBs that have a matching job record.
   For each job, verify the DB exists, drop it, confirm deletion, then archive.
2. Orphan detection: Databases matching the pattern but with no job record are
   NEVER auto-deleted. Instead, generate an admin report for manual review.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import mysql.connector

from pulldb.infra.factory import is_simulation_mode
from pulldb.infra.metrics import MetricLabels, emit_counter, emit_gauge


if TYPE_CHECKING:
    from pulldb.domain.models import Job
    from pulldb.infra.mysql import (
        HostRepository,
        JobRepository,
        SettingsRepository,
        UserRepository,
    )
    from pulldb.infra.secrets import MySQLCredentials


logger = logging.getLogger(__name__)


# Default retention: staging databases older than 7 days are candidates
DEFAULT_RETENTION_DAYS = 7

# Pattern for staging database names: {target}_{hex12}
STAGING_PATTERN = re.compile(r"^(.+)_([0-9a-f]{12})$")

# Protected databases that must NEVER be dropped, regardless of name matching.
# This is a defense-in-depth measure to prevent catastrophic mistakes.
PROTECTED_DATABASES = frozenset({
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
    "pulldb",
    "pulldb_service",
})


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CleanupCandidate:
    """A staging database eligible for cleanup (has matching job record)."""

    database_name: str
    target_name: str
    job_id_prefix: str  # First 12 chars of job UUID
    dbhost: str
    matched_job_id: str
    job_status: str
    job_completed_at: datetime | None = None
    db_exists: bool = False  # Verified on target server
    db_dropped: bool = False  # Confirmed dropped
    job_archived: bool = False  # Job record updated


@dataclass
class OrphanCandidate:
    """A database matching staging pattern but with NO job record.

    These are NEVER auto-deleted. They require manual admin review.
    """

    database_name: str
    target_name: str
    job_id_prefix: str
    dbhost: str
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    size_mb: float | None = None  # Database size in MB from INFORMATION_SCHEMA


@dataclass
class OrphanMetadata:
    """Metadata from pullDB table inside an orphan database.
    
    Loaded on-demand when user clicks details icon.
    """
    
    job_id: str | None = None
    restored_by: str | None = None
    restored_at: datetime | None = None
    target_database: str | None = None
    backup_filename: str | None = None
    restore_duration_seconds: float | None = None


@dataclass
class CleanupResult:
    """Result of a scheduled cleanup run on a single host."""

    dbhost: str
    jobs_processed: int = 0
    databases_dropped: int = 0
    databases_not_found: int = 0  # Job exists but staging DB already gone
    databases_skipped: int = 0
    jobs_archived: int = 0
    errors: list[str] = field(default_factory=list)
    dropped_names: list[str] = field(default_factory=list)

    # Legacy compatibility properties
    @property
    def candidates_found(self) -> int:
        """Alias for jobs_processed for backwards compatibility."""
        return self.jobs_processed


@dataclass
class OrphanReport:
    """Report of orphaned databases for admin review."""

    dbhost: str
    scanned_at: datetime
    orphans: list[OrphanCandidate] = field(default_factory=list)


@dataclass
class ScheduledCleanupSummary:
    """Summary of a complete cleanup run across all hosts."""

    started_at: datetime
    completed_at: datetime | None = None
    retention_days: int = DEFAULT_RETENTION_DAYS
    hosts_scanned: int = 0
    total_jobs_processed: int = 0
    total_dropped: int = 0
    total_not_found: int = 0
    total_skipped: int = 0
    total_archived: int = 0
    total_errors: int = 0
    per_host_results: list[CleanupResult] = field(default_factory=list)
    orphan_reports: list[OrphanReport] = field(default_factory=list)

    # Legacy compatibility properties
    @property
    def total_candidates(self) -> int:
        """Alias for total_jobs_processed for backwards compatibility."""
        return self.total_jobs_processed


# =============================================================================
# Database Operations
# =============================================================================


def _parse_staging_name(db_name: str) -> tuple[str, str] | None:
    """Parse a staging database name into target and job_id prefix.

    Args:
        db_name: Database name to parse.

    Returns:
        Tuple of (target_name, job_id_prefix) or None if not a staging DB.
    """
    match = STAGING_PATTERN.match(db_name)
    if match:
        return (match.group(1), match.group(2))
    return None


def is_valid_staging_name(db_name: str) -> tuple[bool, str]:
    """Validate a database name is a legitimate pullDB staging database.

    Defense-in-depth validation before any cleanup operation. Checks:
    1. Not a protected system database
    2. Matches the staging pattern {target}_{hex12}
    3. Target portion is not a system database name

    Args:
        db_name: Database name to validate.

    Returns:
        (is_valid, reason) - reason explains why invalid, empty if valid.
    """
    # Check 1: Not a protected database
    if db_name.lower() in PROTECTED_DATABASES:
        return False, f"'{db_name}' is a protected database"

    # Check 2: Matches staging pattern
    match = STAGING_PATTERN.match(db_name)
    if not match:
        return False, f"'{db_name}' does not match staging pattern {{target}}_{{hex12}}"

    target, job_prefix = match.groups()

    # Check 3: Target is not a system database name
    if target.lower() in PROTECTED_DATABASES:
        return False, f"Target '{target}' is a protected database name"

    # Check 4: Job prefix is valid hex (redundant with regex but explicit)
    if not all(c in "0123456789abcdef" for c in job_prefix):
        return False, f"Job prefix '{job_prefix}' contains non-hex characters"

    return True, ""


@dataclass
class TargetProtectionResult:
    """Result of checking if a target database is protected from deletion."""
    
    can_drop: bool
    reason: str | None = None
    blocking_job_id: str | None = None
    blocking_job_owner: str | None = None


def is_target_database_protected(
    target: str,
    dbhost: str,
    job_repo: "JobRepository",
) -> TargetProtectionResult:
    """Check if a target database is protected from deletion.
    
    A target database is protected if:
    1. It's in the protected database list (mysql, sys, etc.)
    2. ANY user has a deployed job for this target on this host
    3. ANY user has a locked job for this target on this host
    
    This is the SINGLE SOURCE OF TRUTH for deletion safety.
    
    Args:
        target: Target database name to check.
        dbhost: Database host where target exists.
        job_repo: JobRepository for job lookups.
        
    Returns:
        TargetProtectionResult with can_drop=False if protected.
    """
    # Check 1: Protected database list
    if target.lower() in PROTECTED_DATABASES:
        return TargetProtectionResult(
            can_drop=False,
            reason=f"'{target}' is a protected system database",
        )
    
    # Check 2: Any deployed job exists for this target
    deployed_job = job_repo.has_any_deployed_job_for_target(target, dbhost)
    if deployed_job:
        return TargetProtectionResult(
            can_drop=False,
            reason=f"Active deployment exists (job {deployed_job.id[:8]}... by {deployed_job.owner_username})",
            blocking_job_id=deployed_job.id,
            blocking_job_owner=deployed_job.owner_username,
        )
    
    # Check 3: Any locked job exists for this target
    locked_job = job_repo.has_any_locked_job_for_target(target, dbhost)
    if locked_job:
        return TargetProtectionResult(
            can_drop=False,
            reason=f"Database is locked (job {locked_job.id[:8]}... locked by {locked_job.locked_by})",
            blocking_job_id=locked_job.id,
            blocking_job_owner=locked_job.owner_username,
        )
    
    # All checks passed - safe to drop
    return TargetProtectionResult(can_drop=True)


def _list_databases(credentials: MySQLCredentials) -> list[str]:
    """List all databases on a host.

    Returns:
        List of database names.
    """
    conn = mysql.connector.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        connect_timeout=30,
    )
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES")
        rows = cursor.fetchall()
        return [str(row[0]) for row in rows]
    finally:
        conn.close()


def _get_database_size_mb(credentials: MySQLCredentials, db_name: str) -> float | None:
    """Get the size of a database in MB.

    Args:
        credentials: MySQL credentials for the host.
        db_name: Name of the database to measure.

    Returns:
        Size in MB, or None if unable to determine.
    """
    conn = mysql.connector.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        connect_timeout=30,
    )
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) as size_mb
            FROM information_schema.TABLES
            WHERE table_schema = %s
        """, (db_name,))
        row = cursor.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return 0.0  # Empty database
    except Exception as e:
        logger.warning("Failed to get size for database %s: %s", db_name, e)
        return None
    finally:
        conn.close()


def _has_pulldb_table(credentials: MySQLCredentials, db_name: str) -> bool:
    """Check if a database contains the pullDB marker table.

    The pullDB table is created during restore operations, so its presence
    confirms the database was created/managed by pullDB. Databases without
    this table should not be considered pullDB orphans.

    Args:
        credentials: MySQL credentials for the host.
        db_name: Name of the database to check.

    Returns:
        True if pullDB table exists, False otherwise.
    """
    conn = mysql.connector.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        connect_timeout=30,
    )
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.TABLES 
            WHERE table_schema = %s AND table_name = 'pullDB'
        """, (db_name,))
        row = cursor.fetchone()
        return bool(row and row[0] > 0)
    except Exception as e:
        logger.warning("Failed to check pullDB table in %s: %s", db_name, e)
        return False
    finally:
        conn.close()


def get_orphan_metadata(
    credentials: MySQLCredentials,
    db_name: str,
) -> OrphanMetadata | None:
    """Get metadata from pullDB table inside an orphan database.

    The pullDB table is created by the restore process and contains
    information about when/how the database was restored.

    Args:
        credentials: MySQL credentials for the host.
        db_name: Name of the orphan database to query.

    Returns:
        OrphanMetadata if pullDB table exists and has data, None otherwise.
    """
    conn = mysql.connector.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        database=db_name,
        connect_timeout=30,
    )
    try:
        cursor = conn.cursor(dictionary=True)
        # Check if pullDB table exists
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM information_schema.TABLES 
            WHERE table_schema = %s AND table_name = 'pullDB'
        """, (db_name,))
        row = cursor.fetchone()
        if not row or row["cnt"] == 0:
            return None
        
        # Query the pullDB metadata table
        cursor.execute("""
            SELECT job_id, restored_by, restored_at, target_database,
                   backup_filename, restore_duration_seconds
            FROM pullDB
            LIMIT 1
        """)
        meta_row = cursor.fetchone()
        if not meta_row:
            return None
        
        return OrphanMetadata(
            job_id=meta_row.get("job_id"),
            restored_by=meta_row.get("restored_by"),
            restored_at=meta_row.get("restored_at"),
            target_database=meta_row.get("target_database"),
            backup_filename=meta_row.get("backup_filename"),
            restore_duration_seconds=float(meta_row["restore_duration_seconds"]) 
                if meta_row.get("restore_duration_seconds") else None,
        )
    except Exception as e:
        logger.warning("Failed to get metadata for orphan %s: %s", db_name, e)
        return None
    finally:
        conn.close()


def _database_exists(credentials: MySQLCredentials, db_name: str) -> bool:
    """Check if a specific database exists on a host.

    Args:
        credentials: MySQL credentials for the host.
        db_name: Name of the database to check.

    Returns:
        True if database exists, False otherwise.
    """
    databases = _list_databases(credentials)
    return db_name in databases


def _drop_database(credentials: MySQLCredentials, db_name: str) -> bool:
    """Drop a database on a host and verify deletion.

    SAFETY: This function includes hard blocks to prevent dropping protected
    databases. These checks are defense-in-depth and should never be reached
    if callers properly validate with is_valid_staging_name() first.

    Args:
        credentials: MySQL credentials for the host.
        db_name: Name of the database to drop.

    Returns:
        True if database was dropped and confirmed gone, False otherwise.

    Raises:
        ValueError: If attempting to drop a protected database.
    """
    # HARD BLOCK: Never drop protected databases
    if db_name.lower() in PROTECTED_DATABASES:
        raise ValueError(
            f"FATAL: Attempted to drop protected database: {db_name}. "
            f"This should never happen - report this as a critical bug."
        )

    # Validate staging name pattern as additional safety layer
    is_valid, reason = is_valid_staging_name(db_name)
    if not is_valid:
        raise ValueError(
            f"FATAL: Attempted to drop non-staging database: {db_name}. "
            f"Reason: {reason}. This should never happen - report this as a critical bug."
        )

    conn = mysql.connector.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        connect_timeout=30,
        autocommit=True,
    )
    try:
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        logger.info(f"Dropped staging database: {db_name}")
    finally:
        conn.close()

    # Verify the database is actually gone
    if _database_exists(credentials, db_name):
        logger.error(f"Database {db_name} still exists after DROP command!")
        return False

    return True


@dataclass
class JobDeleteResult:
    """Result of deleting a job's databases.
    
    Tracks what databases were found and dropped for audit purposes.
    """
    
    job_id: str
    staging_name: str
    target_name: str
    dbhost: str
    staging_existed: bool = False
    staging_dropped: bool = False
    target_existed: bool = False
    target_dropped: bool = False
    error: str | None = None


def _drop_target_database_unsafe(credentials: MySQLCredentials, db_name: str) -> bool:
    """Drop a target database without staging pattern validation.
    
    WARNING: This function bypasses staging name validation and should ONLY
    be called after verifying the database name matches the expected user_code
    pattern. Used for user-initiated database deletion.
    
    SAFETY: Still blocks protected databases.
    
    Args:
        credentials: MySQL credentials for the host.
        db_name: Name of the database to drop.
        
    Returns:
        True if database was dropped and confirmed gone, False otherwise.
        
    Raises:
        ValueError: If attempting to drop a protected database.
    """
    # HARD BLOCK: Never drop protected databases
    if db_name.lower() in PROTECTED_DATABASES:
        raise ValueError(
            f"FATAL: Attempted to drop protected database: {db_name}. "
            f"This should never happen - report this as a critical bug."
        )
    
    conn = mysql.connector.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        connect_timeout=30,
        autocommit=True,
    )
    try:
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        logger.info(f"Dropped target database: {db_name}")
    finally:
        conn.close()
    
    # Verify the database is actually gone
    if _database_exists(credentials, db_name):
        logger.error(f"Database {db_name} still exists after DROP command!")
        return False
    
    return True


def delete_job_databases(
    job_id: str,
    staging_name: str,
    target_name: str,
    owner_user_code: str,
    dbhost: str,
    host_repo: HostRepository,
    job_repo: JobRepository | None = None,
    skip_protection_check: bool = False,
) -> JobDeleteResult:
    """Delete both staging and target databases for a job.
    
    User-initiated deletion of job databases. Drops BOTH:
    - staging_name: The staging database ({target}_{job_id[:12]})
    - target_name: The target database ({user_code}{customer/template})
    
    SAFETY CHECKS:
    - Validates target_name contains the owner's user_code
    - Protected databases are never dropped
    - If job_repo provided: checks no deployed/locked job exists for target
    - Logs all operations
    
    Args:
        job_id: Job UUID for logging.
        staging_name: Staging database name to drop.
        target_name: Target database name to drop.
        owner_user_code: User code of the job owner (for validation).
        dbhost: Database host where databases exist.
        host_repo: HostRepository for credential resolution.
        job_repo: Optional JobRepository for deployment protection check.
        skip_protection_check: If True, skip deployed/locked check (use with caution).
        
    Returns:
        JobDeleteResult with details of what was found and dropped.
    """
    result = JobDeleteResult(
        job_id=job_id,
        staging_name=staging_name,
        target_name=target_name,
        dbhost=dbhost,
    )
    
    # SAFETY: Validate target_name contains owner's user_code
    if owner_user_code not in target_name:
        result.error = (
            f"Target database '{target_name}' does not contain "
            f"owner user code '{owner_user_code}' - refusing to delete"
        )
        logger.error(result.error)
        return result
    
    # SAFETY: Check if target is protected by deployed/locked job
    # FAIL-SAFE: If protection check throws an exception, BLOCK deletion
    # This prevents accidental data loss if the protection system is broken
    if job_repo and not skip_protection_check:
        try:
            protection = is_target_database_protected(target_name, dbhost, job_repo)
            if not protection.can_drop:
                result.error = f"Cannot drop target database: {protection.reason}"
                logger.warning(
                    "Target deletion blocked for job %s: %s (blocking_job=%s)",
                    job_id,
                    protection.reason,
                    protection.blocking_job_id,
                )
                # Still try to drop staging, just skip target
        except Exception as e:
            # FAIL-SAFE: Protection check failed - BLOCK target deletion
            result.error = f"Protection check failed, blocking deletion for safety: {e}"
            logger.error(
                "FAIL-SAFE: Protection check threw exception for job %s target %s: %s. "
                "Blocking target deletion to prevent potential data loss.",
                job_id,
                target_name,
                e,
            )
            # Still try to drop staging, just skip target
    
    try:
        credentials = host_repo.get_host_credentials(dbhost)
    except Exception as e:
        result.error = f"Failed to get credentials for {dbhost}: {e}"
        logger.error(result.error)
        return result
    
    # Check and drop staging database
    try:
        result.staging_existed = _database_exists(credentials, staging_name)
        if result.staging_existed:
            # Staging names pass is_valid_staging_name, use regular _drop_database
            is_valid, reason = is_valid_staging_name(staging_name)
            if is_valid:
                result.staging_dropped = _drop_database(credentials, staging_name)
            else:
                logger.warning(
                    f"Staging name {staging_name} failed validation: {reason}"
                )
    except Exception as e:
        logger.error(f"Error dropping staging database {staging_name}: {e}")
        # Continue to try target
    
    # Check and drop target database (only if not blocked by protection check)
    if result.error and "Cannot drop target database" in result.error:
        # Target is protected, skip drop
        logger.info(
            f"Skipping target database drop for job {job_id}: protection check failed"
        )
    else:
        try:
            result.target_existed = _database_exists(credentials, target_name)
            if result.target_existed:
                result.target_dropped = _drop_target_database_unsafe(credentials, target_name)
        except Exception as e:
            logger.error(f"Error dropping target database {target_name}: {e}")
            if not result.error:
                result.error = f"Failed to drop target database: {e}"
    
    logger.info(
        f"Job {job_id} database deletion complete: "
        f"staging={staging_name} (existed={result.staging_existed}, dropped={result.staging_dropped}), "
        f"target={target_name} (existed={result.target_existed}, dropped={result.target_dropped})"
    )
    
    return result


# Default stale delete constants
DEFAULT_STALE_DELETE_TIMEOUT_MINUTES = 5
MAX_DELETE_RETRY_COUNT = 5


@dataclass
class DeleteJobResult:
    """Result of executing a delete job (worker retry of stale deleting job)."""

    job_id: str
    success: bool
    databases_already_gone: bool = False
    retry_count: int = 0
    error: str | None = None


def execute_delete_job(
    job: Job,
    job_repo: JobRepository,
    host_repo: HostRepository,
) -> DeleteJobResult:
    """Execute database deletion for a job in 'deleting' status.

    Called by the worker when processing a stale deleting job. Handles:
    1. Checking if databases already gone (skip drop, mark deleted)
    2. Attempting to drop staging and target databases
    3. Marking job as deleted on success
    4. Marking job as failed if max retries exceeded

    Args:
        job: Job in 'deleting' status (claimed by worker).
        job_repo: JobRepository for status updates.
        host_repo: HostRepository for credential resolution.

    Returns:
        DeleteJobResult with outcome details.
    """
    import json

    result = DeleteJobResult(
        job_id=job.id,
        success=False,
        retry_count=job.retry_count,
    )

    try:
        credentials = host_repo.get_host_credentials(job.dbhost)
    except Exception as e:
        error_msg = f"Failed to get credentials for {job.dbhost}: {e}"
        logger.error(error_msg, extra={"job_id": job.id})
        result.error = error_msg

        # Check if we've exceeded retries
        if job.retry_count >= MAX_DELETE_RETRY_COUNT:
            job_repo.mark_job_delete_failed(job.id, error_msg)
        return result

    # Check if databases already gone (deleted by another means)
    staging_exists = _database_exists(credentials, job.staging_name)
    target_exists = _database_exists(credentials, job.target)

    if not staging_exists and not target_exists:
        # Both databases already gone - mark as deleted
        logger.info(
            "Databases already deleted, marking job as deleted",
            extra={
                "job_id": job.id,
                "staging_name": job.staging_name,
                "target": job.target,
            },
        )

        # Log delete_skipped event
        detail = json.dumps({
            "reason": "databases_already_gone",
            "staging_name": job.staging_name,
            "target": job.target,
        })
        job_repo.append_job_event(job.id, "delete_skipped", detail)
        job_repo.mark_job_deleted(job.id, "Databases already deleted")

        result.success = True
        result.databases_already_gone = True
        return result

    # Attempt to drop databases
    delete_result = delete_job_databases(
        job_id=job.id,
        staging_name=job.staging_name,
        target_name=job.target,
        owner_user_code=job.owner_user_code,
        dbhost=job.dbhost,
        host_repo=host_repo,
        job_repo=job_repo,
        skip_protection_check=False,
    )

    if delete_result.error:
        result.error = delete_result.error
        logger.error(
            "Delete job database drop failed",
            extra={
                "job_id": job.id,
                "error": delete_result.error,
                "retry_count": job.retry_count,
            },
        )

        # Check if we've exceeded retries
        if job.retry_count >= MAX_DELETE_RETRY_COUNT:
            job_repo.mark_job_delete_failed(job.id, delete_result.error)
        return result

    # Success - mark as deleted
    logger.info(
        "Delete job completed successfully",
        extra={
            "job_id": job.id,
            "staging_dropped": delete_result.staging_dropped,
            "target_dropped": delete_result.target_dropped,
        },
    )
    job_repo.mark_job_deleted(job.id, "Databases deleted by worker retry")

    result.success = True
    return result


# =============================================================================
# Job-Based Cleanup (Safe - only cleans databases with job records)
# =============================================================================


def find_cleanup_candidates_from_jobs(
    dbhost: str,
    job_repo: JobRepository,
    host_repo: HostRepository,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> list[CleanupCandidate]:
    """Find staging databases eligible for cleanup based on job records.

    This is the SAFE approach: we start from the jobs table and look for
    staging databases that should be cleaned up. Only databases with a
    matching job record are considered.

    Args:
        dbhost: Hostname to scan.
        job_repo: JobRepository for job lookups.
        host_repo: HostRepository for credential resolution.
        retention_days: Days before a staging DB is considered abandoned.

    Returns:
        List of CleanupCandidate instances (only jobs with matching DBs).
    """
    credentials = host_repo.get_host_credentials(dbhost)
    cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)

    # Get terminal jobs older than retention period for this host
    old_terminal_jobs = job_repo.get_old_terminal_jobs(
        dbhost=dbhost,
        cutoff_date=cutoff_date,
    )

    candidates = []
    for job in old_terminal_jobs:
        # Check if the staging database still exists on the target server
        staging_name = job.staging_name
        if not staging_name:
            continue

        db_exists = _database_exists(credentials, staging_name)

        # Parse the staging name to get components
        parsed = _parse_staging_name(staging_name)
        if not parsed:
            continue

        target, job_prefix = parsed
        job_status = (
            job.status.value if hasattr(job.status, "value") else str(job.status)
        )

        candidate = CleanupCandidate(
            database_name=staging_name,
            target_name=target,
            job_id_prefix=job_prefix,
            dbhost=dbhost,
            matched_job_id=job.id,
            job_status=job_status,
            job_completed_at=job_repo.get_job_completion_time(job.id),
            db_exists=db_exists,
        )
        candidates.append(candidate)

    return candidates


def cleanup_from_jobs(
    dbhost: str,
    job_repo: JobRepository,
    host_repo: HostRepository,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> CleanupResult:
    """Clean up staging databases based on job records.

    For each eligible job:
    1. Check if staging database exists on target server
    2. If exists: drop it and verify deletion
    3. If confirmed gone: archive/update the job record
    4. Log all actions to job_events

    Args:
        dbhost: Hostname to clean up.
        job_repo: JobRepository for job lookups and event logging.
        host_repo: HostRepository for credential resolution.
        retention_days: Days before a staging DB is considered abandoned.
        dry_run: If True, don't actually drop databases or update records.

    Returns:
        CleanupResult with counts and any errors.
    """
    result = CleanupResult(dbhost=dbhost)

    try:
        candidates = find_cleanup_candidates_from_jobs(
            dbhost=dbhost,
            job_repo=job_repo,
            host_repo=host_repo,
            retention_days=retention_days,
        )
    except Exception as e:
        result.errors.append(f"Failed to find candidates: {e}")
        return result

    result.jobs_processed = len(candidates)
    credentials = host_repo.get_host_credentials(dbhost)

    for candidate in candidates:
        # Skip superseded jobs - they have no database (was replaced by newer restore)
        if candidate.job_status == 'superseded':
            logger.info(
                "Skipping superseded job %s: database was replaced by newer restore",
                candidate.matched_job_id,
            )
            result.databases_skipped += 1
            continue

        # Safety check: verify no active jobs for this target
        if job_repo.has_active_jobs_for_target(candidate.target_name, dbhost):
            logger.warning(
                "Skipping %s: active job for target", candidate.database_name
            )
            result.databases_skipped += 1
            continue

        if not candidate.db_exists:
            # Database already gone - just archive the job
            logger.info(
                "Staging DB %s already gone for job %s",
                candidate.database_name,
                candidate.matched_job_id,
            )
            result.databases_not_found += 1

            if not dry_run:
                # Log that we processed this job even though DB was gone
                job_repo.append_job_event(
                    job_id=candidate.matched_job_id,
                    event_type="staging_cleanup_verified",
                    detail="Staging database already removed",
                )
                job_repo.mark_job_staging_cleaned(candidate.matched_job_id)
                result.jobs_archived += 1

            continue

        if dry_run:
            logger.info("[DRY RUN] Would drop: %s", candidate.database_name)
            result.databases_skipped += 1
            continue

        # Step 1: Drop the database
        try:
            dropped = _drop_database(credentials, candidate.database_name)
        except Exception as e:
            result.errors.append(f"Failed to drop {candidate.database_name}: {e}")
            continue

        # Step 2: Verify deletion
        if not dropped:
            result.errors.append(
                f"Drop command succeeded but {candidate.database_name} still exists"
            )
            continue

        result.databases_dropped += 1
        result.dropped_names.append(candidate.database_name)

        # Step 3: Archive the job record
        try:
            job_repo.append_job_event(
                job_id=candidate.matched_job_id,
                event_type="staging_scheduled_cleanup",
                detail=f"Dropped by scheduled cleanup after {retention_days} days",
            )
            job_repo.mark_job_staging_cleaned(candidate.matched_job_id)
            result.jobs_archived += 1
        except Exception as e:
            # Non-fatal - DB is already dropped
            result.errors.append(
                f"Failed to archive job {candidate.matched_job_id}: {e}"
            )

    return result


def cleanup_specific_databases(
    database_names: list[str],
    job_repo: JobRepository,
    host_repo: HostRepository,
    dry_run: bool = False,
) -> CleanupResult:
    """Clean up specific staging databases by name (admin-initiated).

    For each database name:
    1. Find the matching job record by staging_name
    2. Verify no active jobs exist for that target (safety check)
    3. Drop the database and verify deletion
    4. Update job record with staging_cleaned_at

    Args:
        database_names: List of staging database names to drop.
        job_repo: JobRepository for job lookups and updates.
        host_repo: HostRepository for credential resolution.
        dry_run: If True, don't actually drop databases.

    Returns:
        CleanupResult with counts and any errors.
    """
    from pulldb.domain.models import Job

    if not database_names:
        return CleanupResult(dbhost="none")

    # Group databases by dbhost for efficient credential resolution
    # First, find all matching jobs to determine hosts
    jobs_by_db: dict[str, Job] = {}
    for db_name in database_names:
        # Parse to get target and job prefix
        parsed = _parse_staging_name(db_name)
        if not parsed:
            continue
        target, job_prefix = parsed

        # Find matching job - need to search across all hosts
        # For now, iterate through enabled hosts
        hosts = list(host_repo.list_hosts()) if hasattr(host_repo, "list_hosts") else []
        for host in hosts:
            if not getattr(host, "enabled", True):
                continue
            job = job_repo.find_job_by_staging_prefix(
                target=target,
                dbhost=host.hostname,
                job_id_prefix=job_prefix,
            )
            if job and job.staging_name == db_name:
                jobs_by_db[db_name] = job
                break

    if not jobs_by_db:
        result = CleanupResult(dbhost="none")
        result.errors.append("No matching jobs found for specified databases")
        return result

    # Group jobs by dbhost to fetch correct credentials for each host
    jobs_by_host: dict[str, dict[str, Job]] = {}
    for db_name, job in jobs_by_db.items():
        job_host = job.dbhost
        if job_host not in jobs_by_host:
            jobs_by_host[job_host] = {}
        jobs_by_host[job_host][db_name] = job

    # Determine result dbhost label
    if len(jobs_by_host) == 1:
        result_dbhost = next(iter(jobs_by_host.keys()))
    else:
        result_dbhost = f"multiple ({len(jobs_by_host)} hosts)"

    result = CleanupResult(dbhost=result_dbhost)
    result.jobs_processed = len(jobs_by_db)

    # Process each host with its own credentials
    for dbhost, host_jobs in jobs_by_host.items():
        try:
            credentials = host_repo.get_host_credentials(dbhost)
        except Exception as e:
            result.errors.append(f"Failed to get credentials for {dbhost}: {e}")
            result.databases_skipped += len(host_jobs)
            continue

        for db_name, job in host_jobs.items():
            # Safety check: verify no active jobs for this target
            if job_repo.has_active_jobs_for_target(job.target, job.dbhost):
                logger.warning(
                    "Skipping %s: active job exists for target %s",
                    db_name,
                    job.target,
                )
                result.databases_skipped += 1
                continue

            # Check if database exists
            try:
                exists = _database_exists(credentials, db_name)
            except Exception as e:
                result.errors.append(f"Failed to check existence of {db_name}: {e}")
                continue

            if not exists:
                logger.info("Database %s already gone for job %s", db_name, job.id)
                result.databases_not_found += 1
                # Still mark the job as cleaned
                if not dry_run:
                    try:
                        job_repo.append_job_event(
                            job_id=job.id,
                            event_type="staging_cleanup_verified",
                            detail="Staging database already removed (admin cleanup)",
                        )
                        job_repo.mark_job_staging_cleaned(job.id)
                        result.jobs_archived += 1
                    except Exception as e:
                        result.errors.append(f"Failed to archive job {job.id}: {e}")
                continue

            if dry_run:
                logger.info("[DRY RUN] Would drop: %s", db_name)
                result.databases_skipped += 1
                continue

            # Drop the database
            try:
                dropped = _drop_database(credentials, db_name)
            except Exception as e:
                result.errors.append(f"Failed to drop {db_name}: {e}")
                continue

            if not dropped:
                result.errors.append(f"Drop succeeded but {db_name} still exists")
                continue

            result.databases_dropped += 1
            result.dropped_names.append(db_name)

            # Archive the job record
            try:
                job_repo.append_job_event(
                    job_id=job.id,
                    event_type="staging_admin_cleanup",
                    detail="Dropped by admin cleanup action",
                )
                job_repo.mark_job_staging_cleaned(job.id)
                result.jobs_archived += 1
            except Exception as e:
                result.errors.append(f"Failed to archive job {job.id}: {e}")

    return result


# =============================================================================
# Orphan Detection (Report only - NEVER auto-delete)
# =============================================================================

# Hostname that simulates connection failure in simulation mode
SIMULATION_FAILING_HOST = "mysql-staging-03.example.com"


def _detect_orphaned_databases_simulation(dbhost: str) -> OrphanReport | str:
    """Simulation mode orphan detection.

    Returns mock orphan data from SimulationState, or an error string
    for hosts configured to fail (mysql-staging-03).

    Args:
        dbhost: Hostname to scan.

    Returns:
        OrphanReport with mock orphans, or error string for failing hosts.
    """
    from pulldb.simulation.core.state import get_simulation_state

    # Simulate connection failure for staging-03
    if dbhost == SIMULATION_FAILING_HOST:
        return f"Connection refused to {dbhost}"

    state = get_simulation_state()
    report = OrphanReport(
        dbhost=dbhost,
        scanned_at=datetime.now(UTC),
    )

    with state.lock:
        # Get databases for this host, excluding any that have been deleted this session
        host_dbs = state.staging_databases.get(dbhost, set())

        for db_name in host_dbs:
            # Skip if deleted this session
            if (dbhost, db_name) in state.deleted_orphans:
                continue

            parsed = _parse_staging_name(db_name)
            if not parsed:
                continue

            target, job_prefix = parsed
            
            # Get mock size from orphan_sizes dict, or generate deterministic size
            size_mb = state.orphan_sizes.get((dbhost, db_name))
            if size_mb is None:
                # Generate deterministic size based on db_name hash (10-500 MB range)
                size_mb = 10.0 + (hash(db_name) % 490)

            orphan = OrphanCandidate(
                database_name=db_name,
                target_name=target,
                job_id_prefix=job_prefix,
                dbhost=dbhost,
                size_mb=size_mb,
            )
            report.orphans.append(orphan)
            logger.info(
                "[SIMULATION] Detected orphan database: %s on %s (%.2f MB)",
                db_name,
                dbhost,
                size_mb,
            )

    return report


def _get_orphan_metadata_simulation(dbhost: str, db_name: str) -> OrphanMetadata | None:
    """Simulation mode orphan metadata retrieval.
    
    Returns mock metadata for orphan databases.
    """
    from pulldb.simulation.core.state import get_simulation_state
    
    state = get_simulation_state()
    
    with state.lock:
        # Check if this orphan exists
        host_dbs = state.staging_databases.get(dbhost, set())
        if db_name not in host_dbs:
            return None
        if (dbhost, db_name) in state.deleted_orphans:
            return None
        
        # Get mock metadata from orphan_metadata dict
        meta_dict = state.orphan_metadata.get((dbhost, db_name))
        if meta_dict:
            # Convert dict to OrphanMetadata (handle ISO date string)
            restored_at = meta_dict.get("restored_at")
            if isinstance(restored_at, str):
                restored_at = datetime.fromisoformat(restored_at.replace("Z", "+00:00"))
            
            return OrphanMetadata(
                job_id=meta_dict.get("job_id"),
                restored_by=meta_dict.get("restored_by"),
                restored_at=restored_at,
                target_database=meta_dict.get("target_database"),
                backup_filename=meta_dict.get("backup_filename"),
                restore_duration_seconds=float(meta_dict["restore_duration_seconds"])
                    if meta_dict.get("restore_duration_seconds") else None,
            )
        
        # No seeded metadata - return None (simulates no pulldb table)
        return None


def detect_orphaned_databases(
    dbhost: str,
    job_repo: JobRepository,
    host_repo: HostRepository,
) -> OrphanReport | str:
    """Detect databases matching staging pattern but with no job record.

    Identifies staging databases (pattern: {target}_{job_id_prefix}) that have
    no corresponding job record. These may be from failed restores that were
    orphaned before completion, or jobs that were manually deleted.

    These databases are NEVER auto-deleted. This function generates a report
    for admin review. Admins can then manually verify and delete selected
    databases using the admin deletion API.

    Args:
        dbhost: Hostname to scan.
        job_repo: JobRepository for job lookups.
        host_repo: HostRepository for credential resolution.

    Returns:
        OrphanReport with list of orphaned databases for admin review,
        or error string if connection failed.
    """
    # Simulation mode: return mock data
    if is_simulation_mode():
        return _detect_orphaned_databases_simulation(dbhost)

    report = OrphanReport(
        dbhost=dbhost,
        scanned_at=datetime.now(UTC),
    )

    try:
        credentials = host_repo.get_host_credentials(dbhost)
        all_databases = _list_databases(credentials)
    except Exception as e:
        logger.error("Failed to list databases on %s: %s", dbhost, e)
        return f"Failed to connect: {e}"

    for db_name in all_databases:
        parsed = _parse_staging_name(db_name)
        if not parsed:
            continue

        target, job_prefix = parsed

        # Check if a matching job exists
        job = job_repo.find_job_by_staging_prefix(
            target=target,
            dbhost=dbhost,
            job_id_prefix=job_prefix,
        )

        if job is None:
            # No matching job - this is an orphan (staging db with no job record)
            # Could be from early restore failure before pullDB table was created
            size_mb = _get_database_size_mb(credentials, db_name)
            
            orphan = OrphanCandidate(
                database_name=db_name,
                target_name=target,
                job_id_prefix=job_prefix,
                dbhost=dbhost,
                size_mb=size_mb,
            )
            report.orphans.append(orphan)
            logger.info(
                "Detected orphan database: %s on %s (no matching job record, %.2f MB)",
                db_name,
                dbhost,
                size_mb or 0,
            )

    return report


def fetch_orphan_metadata(
    dbhost: str,
    db_name: str,
    host_repo: HostRepository,
) -> OrphanMetadata | None:
    """Fetch metadata from pullDB table inside an orphan database.
    
    This is called on-demand when user clicks the details icon.
    
    Args:
        dbhost: Hostname where database exists.
        db_name: Name of the orphan database.
        host_repo: HostRepository for credential resolution.
        
    Returns:
        OrphanMetadata if available, None if pullDB table missing or error.
    """
    if is_simulation_mode():
        return _get_orphan_metadata_simulation(dbhost, db_name)
    
    try:
        credentials = host_repo.get_host_credentials(dbhost)
        return get_orphan_metadata(credentials, db_name)
    except Exception as e:
        logger.error("Failed to fetch metadata for %s on %s: %s", db_name, dbhost, e)
        return None


def _admin_delete_orphan_databases_simulation(
    dbhost: str,
    database_names: list[str],
    admin_user: str,
) -> dict[str, bool]:
    """Simulation mode orphan deletion.

    Tracks deleted databases in SimulationState so subsequent scans
    no longer show them as orphans.

    Args:
        dbhost: Hostname where databases exist.
        database_names: List of database names to delete.
        admin_user: Username of admin performing the deletion.

    Returns:
        Dict mapping database name to success (True) or failure (False).
    """
    from pulldb.simulation.core.state import get_simulation_state

    state = get_simulation_state()
    results: dict[str, bool] = {}

    with state.lock:
        for db_name in database_names:
            # Validate it matches staging pattern
            if not _parse_staging_name(db_name):
                logger.warning(
                    "[SIMULATION] Admin deletion rejected: %s doesn't match staging pattern",
                    db_name,
                )
                results[db_name] = False
                continue

            # Check if database exists in simulation state
            host_dbs = state.staging_databases.get(dbhost, set())
            if db_name not in host_dbs:
                logger.info("[SIMULATION] Database %s already doesn't exist", db_name)
                results[db_name] = True
                continue

            # Mark as deleted (will be filtered from future scans)
            state.deleted_orphans.add((dbhost, db_name))
            logger.info(
                "[SIMULATION] Admin %s deleted orphan database: %s on %s",
                admin_user,
                db_name,
                dbhost,
            )
            results[db_name] = True

    return results


def admin_delete_orphan_databases(
    dbhost: str,
    database_names: list[str],
    host_repo: HostRepository,
    admin_user: str,
) -> dict[str, bool]:
    """Admin-initiated deletion of orphan databases.

    This is for databases that have been reviewed by an admin and confirmed
    safe to delete. Each deletion is logged with the admin who approved it.

    Args:
        dbhost: Hostname where databases exist.
        database_names: List of database names to delete.
        host_repo: HostRepository for credential resolution.
        admin_user: Username of admin performing the deletion.

    Returns:
        Dict mapping database name to success (True) or failure (False).
    """
    # Simulation mode: track in SimulationState
    if is_simulation_mode():
        return _admin_delete_orphan_databases_simulation(dbhost, database_names, admin_user)

    credentials = host_repo.get_host_credentials(dbhost)
    results: dict[str, bool] = {}

    for db_name in database_names:
        # Validate it matches staging pattern (extra safety)
        if not _parse_staging_name(db_name):
            logger.warning(
                "Admin deletion rejected: %s doesn't match staging pattern",
                db_name,
            )
            results[db_name] = False
            continue

        # Check database exists
        if not _database_exists(credentials, db_name):
            logger.info("Database %s already doesn't exist", db_name)
            results[db_name] = True
            continue

        try:
            dropped = _drop_database(credentials, db_name)
            if dropped:
                logger.info("Admin %s deleted orphan database: %s", admin_user, db_name)
                results[db_name] = True
            else:
                results[db_name] = False
        except Exception as e:
            logger.error("Failed to delete %s: %s", db_name, e)
            results[db_name] = False

    return results


# =============================================================================
# Main Cleanup Orchestration
# =============================================================================


def run_scheduled_cleanup(
    job_repo: JobRepository,
    host_repo: HostRepository,
    retention_days: int | None = None,
    dry_run: bool = False,
    include_orphan_report: bool = True,
    settings_repo: SettingsRepository | None = None,
) -> ScheduledCleanupSummary:
    """Run scheduled cleanup across all enabled database hosts.

    This performs job-based cleanup (safe) and optionally generates orphan
    reports (for admin review).

    Args:
        job_repo: JobRepository for job lookups.
        host_repo: HostRepository for host enumeration.
        retention_days: Days before a staging DB is considered abandoned.
            If None, uses settings_repo or DEFAULT_RETENTION_DAYS.
        dry_run: If True, don't actually drop databases.
        include_orphan_report: If True, also detect orphan databases.
        settings_repo: Optional SettingsRepository for configurable retention.

    Returns:
        ScheduledCleanupSummary with overall results and orphan reports.
    """
    # Resolve retention days from settings if not provided
    if retention_days is None:
        if settings_repo is not None:
            retention_days = settings_repo.get_staging_retention_days()
        else:
            retention_days = DEFAULT_RETENTION_DAYS

    # If retention is 0, cleanup is disabled
    if retention_days == 0:
        logger.info("Staging cleanup disabled (retention_days=0)")
        return ScheduledCleanupSummary(
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            retention_days=0,
        )

    summary = ScheduledCleanupSummary(
        started_at=datetime.now(UTC),
        retention_days=retention_days,
    )

    # Get all enabled hosts
    hosts = host_repo.get_enabled_hosts()
    summary.hosts_scanned = len(hosts)

    for host in hosts:
        logger.info("Processing host: %s", host.hostname)

        # Job-based cleanup (safe)
        result = cleanup_from_jobs(
            dbhost=host.hostname,
            job_repo=job_repo,
            host_repo=host_repo,
            retention_days=retention_days,
            dry_run=dry_run,
        )

        summary.per_host_results.append(result)
        summary.total_jobs_processed += result.jobs_processed
        summary.total_dropped += result.databases_dropped
        summary.total_not_found += result.databases_not_found
        summary.total_skipped += result.databases_skipped
        summary.total_archived += result.jobs_archived
        summary.total_errors += len(result.errors)

        # Orphan detection (report only, no deletion)
        if include_orphan_report:
            orphan_result = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=job_repo,
                host_repo=host_repo,
            )
            # Handle both OrphanReport and error string returns
            if isinstance(orphan_result, OrphanReport) and orphan_result.orphans:
                summary.orphan_reports.append(orphan_result)

    summary.completed_at = datetime.now(UTC)

    # Emit metrics
    emit_counter(
        "staging_cleanup_databases_dropped_total",
        summary.total_dropped,
        MetricLabels(phase="cleanup"),
    )
    emit_counter(
        "staging_cleanup_jobs_archived_total",
        summary.total_archived,
        MetricLabels(phase="cleanup"),
    )
    emit_counter(
        "staging_cleanup_errors_total",
        summary.total_errors,
        MetricLabels(phase="cleanup"),
    )
    emit_gauge(
        "staging_cleanup_orphans_detected",
        float(sum(len(r.orphans) for r in summary.orphan_reports)),
        MetricLabels(phase="cleanup"),
    )

    logger.info(
        "Scheduled cleanup complete",
        extra={
            "hosts_scanned": summary.hosts_scanned,
            "total_dropped": summary.total_dropped,
            "total_archived": summary.total_archived,
            "orphan_count": sum(len(r.orphans) for r in summary.orphan_reports),
        },
    )

    return summary


# =============================================================================
# User Orphan Detection (databases from deleted users)
# =============================================================================


# Pattern for user databases: starts with 6-char user_code, followed by customer name
# Optionally has _hex12 suffix for staging databases
# Examples: jdoesacme, jdoesacme_abc123def456
# NOTE: The user_code is exactly 6 lowercase letters, but we can't reliably extract
# it from the name alone due to no delimiter. We use startswith() checks instead.
USER_DB_PATTERN = re.compile(r"^([a-z]{6})([a-z]+)(_[0-9a-f]{12})?$", re.IGNORECASE)


@dataclass
class UserOrphanCandidate:
    """A database that appears to belong to a deleted user.

    User_code was extracted from database name but doesn't exist in auth_users.
    """

    database_name: str
    extracted_user_code: str
    dbhost: str
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    size_mb: float | None = None
    restored_at: datetime | None = None  # From pullDB metadata table
    restored_by: str | None = None  # From pullDB metadata table


@dataclass
class UserOrphanReport:
    """Report of databases belonging to deleted users."""

    dbhost: str
    scanned_at: datetime
    orphans: list[UserOrphanCandidate] = field(default_factory=list)
    error: str | None = None


def _extract_user_code(db_name: str) -> str | None:
    """Extract user_code from a database name.

    User codes are 6 lowercase alphabetic characters that prefix database names.
    The database name must match the pullDB naming pattern to be considered valid.

    Args:
        db_name: Database name to parse.

    Returns:
        First 6 chars (lowercase) if the name matches pullDB pattern, None otherwise.
    """
    # Must match the user database pattern first
    if not _looks_like_user_database(db_name):
        return None
    
    # Extract first 6 characters (we know they're valid letters from the pattern)
    return db_name[:6].lower()


def _looks_like_user_database(db_name: str) -> bool:
    """Check if a database name looks like a pullDB user database.

    Returns True if the name matches the pattern of user databases:
    - At least 7 characters (6 user_code + 1 customer)
    - First 6 characters are letters (the user_code)
    - Remaining characters are alphanumeric (customer name + optional staging suffix)

    Args:
        db_name: Database name to check.

    Returns:
        True if it looks like a user database name.
    """
    return USER_DB_PATTERN.match(db_name) is not None


def get_all_user_codes(user_repo: UserRepository) -> frozenset[str]:
    """Get all user_codes from the auth_users table.

    Args:
        user_repo: UserRepository for user lookups.

    Returns:
        Frozenset of all active user codes (lowercase).
    """
    users = user_repo.list_users()
    return frozenset(u.user_code.lower() for u in users if u.user_code)


def scan_databases_for_user_code(
    user_code: str,
    host_repo: HostRepository,
    specific_hosts: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Scan hosts for databases belonging to a specific user_code.

    Used by force-delete preview to find all databases for a user being deleted.

    Args:
        user_code: The 6-char user code to search for.
        host_repo: HostRepository for credential resolution.
        specific_hosts: Optional list of hostnames to scan. If None, scans all enabled hosts.

    Returns:
        List of (dbhost, database_name) tuples.
    """
    if is_simulation_mode():
        return _scan_databases_for_user_code_simulation(user_code, host_repo, specific_hosts)

    results: list[tuple[str, str]] = []
    user_code_lower = user_code.lower()

    # Get hosts to scan
    if specific_hosts:
        hosts_to_scan = specific_hosts
    else:
        hosts = host_repo.get_enabled_hosts()
        hosts_to_scan = [h.hostname for h in hosts]

    for hostname in hosts_to_scan:
        try:
            credentials = host_repo.get_host_credentials(hostname)
            all_databases = _list_databases(credentials)

            for db_name in all_databases:
                # Skip protected databases
                if db_name.lower() in PROTECTED_DATABASES:
                    continue

                # Check if database belongs to this user
                extracted = _extract_user_code(db_name)
                if extracted and extracted.lower() == user_code_lower:
                    results.append((hostname, db_name))

        except Exception as e:
            logger.warning(f"Failed to scan host {hostname} for user databases: {e}")
            continue

    return results


def _scan_databases_for_user_code_simulation(
    user_code: str,
    host_repo: HostRepository,
    specific_hosts: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Simulation mode database scan for user_code."""
    from pulldb.simulation.core.state import get_simulation_state

    state = get_simulation_state()
    results: list[tuple[str, str]] = []
    user_code_lower = user_code.lower()

    # Get hosts to scan
    if specific_hosts:
        hosts_to_scan = specific_hosts
    else:
        hosts = host_repo.get_enabled_hosts()
        hosts_to_scan = [h.hostname for h in hosts]

    with state.lock:
        for hostname in hosts_to_scan:
            host_dbs = state.staging_databases.get(hostname, set())
            for db_name in host_dbs:
                if (hostname, db_name) in state.deleted_orphans:
                    continue
                extracted = _extract_user_code(db_name)
                if extracted and extracted.lower() == user_code_lower:
                    results.append((hostname, db_name))

    return results


def detect_user_orphaned_databases(
    dbhost: str,
    host_repo: HostRepository,
    valid_user_codes: frozenset[str],
) -> UserOrphanReport | str:
    """Detect databases belonging to users that no longer exist.

    Scans a host for databases that match the user_code pattern but whose
    extracted user_code is not in the valid_user_codes set (from auth_users).

    Args:
        dbhost: Hostname to scan.
        host_repo: HostRepository for credential resolution.
        valid_user_codes: Set of all existing user codes from auth_users.

    Returns:
        UserOrphanReport with orphaned databases, or error string if connection failed.
    """
    if is_simulation_mode():
        return _detect_user_orphaned_databases_simulation(dbhost, valid_user_codes)

    report = UserOrphanReport(
        dbhost=dbhost,
        scanned_at=datetime.now(UTC),
    )

    try:
        credentials = host_repo.get_host_credentials(dbhost)
        all_databases = _list_databases(credentials)
    except Exception as e:
        logger.error("Failed to list databases on %s: %s", dbhost, e)
        return f"Failed to connect: {e}"

    for db_name in all_databases:
        # Skip protected databases
        if db_name.lower() in PROTECTED_DATABASES:
            continue

        # Try to extract user_code
        extracted_code = _extract_user_code(db_name)
        if not extracted_code:
            continue

        # Check if user_code exists
        if extracted_code.lower() not in valid_user_codes:
            # User doesn't exist - verify this is a pullDB-managed database
            # by checking for the pullDB marker table
            if not _has_pulldb_table(credentials, db_name):
                logger.debug(
                    "Skipping %s on %s: no pullDB marker table (not pullDB-managed)",
                    db_name,
                    dbhost,
                )
                continue

            # Confirmed pullDB-managed orphan - get metadata
            size_mb = _get_database_size_mb(credentials, db_name)
            metadata = get_orphan_metadata(credentials, db_name)
            restored_at = metadata.restored_at if metadata else None
            restored_by = metadata.restored_by if metadata else None

            orphan = UserOrphanCandidate(
                database_name=db_name,
                extracted_user_code=extracted_code,
                dbhost=dbhost,
                size_mb=size_mb,
                restored_at=restored_at,
                restored_by=restored_by,
            )
            report.orphans.append(orphan)
            logger.info(
                "Detected user-orphan database: %s on %s (user_code '%s' not in system, %.2f MB)",
                db_name,
                dbhost,
                extracted_code,
                size_mb or 0,
            )

    return report


def _detect_user_orphaned_databases_simulation(
    dbhost: str,
    valid_user_codes: frozenset[str],
) -> UserOrphanReport:
    """Simulation mode user orphan detection."""
    from pulldb.simulation.core.state import get_simulation_state

    state = get_simulation_state()
    report = UserOrphanReport(
        dbhost=dbhost,
        scanned_at=datetime.now(UTC),
    )

    # Simulate connection failure for staging-03
    if dbhost == SIMULATION_FAILING_HOST:
        report.error = f"Connection refused to {dbhost}"
        return report

    with state.lock:
        host_dbs = state.staging_databases.get(dbhost, set())

        for db_name in host_dbs:
            if (dbhost, db_name) in state.deleted_orphans:
                continue

            extracted_code = _extract_user_code(db_name)
            if not extracted_code:
                continue

            if extracted_code.lower() not in valid_user_codes:
                # In simulation, assume all synthetic databases are pullDB-managed
                # (real mode checks for pullDB marker table)
                size_mb = state.orphan_sizes.get((dbhost, db_name))
                if size_mb is None:
                    size_mb = 10.0 + (hash(db_name) % 490)

                orphan = UserOrphanCandidate(
                    database_name=db_name,
                    extracted_user_code=extracted_code,
                    dbhost=dbhost,
                    size_mb=size_mb,
                )
                report.orphans.append(orphan)

    return report


def admin_delete_user_orphan_databases(
    dbhost: str,
    database_names: list[str],
    host_repo: HostRepository,
    admin_user: str,
) -> dict[str, bool]:
    """Delete user orphan databases (admin-initiated).

    Unlike staging orphan deletion, this drops databases that match the user_code
    pattern but have no matching user in the system.

    Args:
        dbhost: Hostname where databases exist.
        database_names: List of database names to delete.
        host_repo: HostRepository for credential resolution.
        admin_user: Username of admin performing the deletion.

    Returns:
        Dict mapping database name to success (True) or failure (False).
    """
    if is_simulation_mode():
        return _admin_delete_user_orphan_databases_simulation(
            dbhost, database_names, admin_user
        )

    results: dict[str, bool] = {}

    try:
        credentials = host_repo.get_host_credentials(dbhost)
    except Exception as e:
        logger.error("Failed to get credentials for %s: %s", dbhost, e)
        return {db: False for db in database_names}

    for db_name in database_names:
        # Validate it matches user database pattern
        if not _extract_user_code(db_name):
            logger.warning(
                "Admin deletion rejected: %s doesn't match user database pattern",
                db_name,
            )
            results[db_name] = False
            continue

        # Check it's not a protected database
        if db_name.lower() in PROTECTED_DATABASES:
            logger.error("Attempted to delete protected database: %s", db_name)
            results[db_name] = False
            continue

        try:
            # Check if database exists
            if not _database_exists(credentials, db_name):
                logger.info("Database %s already doesn't exist", db_name)
                results[db_name] = True
                continue

            # Drop the database
            conn = mysql.connector.connect(
                host=credentials.host,
                port=credentials.port,
                user=credentials.username,
                password=credentials.password,
                connect_timeout=30,
                autocommit=True,
            )
            try:
                cursor = conn.cursor()
                cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                logger.info(
                    "Admin %s deleted user-orphan database: %s on %s",
                    admin_user,
                    db_name,
                    dbhost,
                )
            finally:
                conn.close()

            # Verify deletion
            if _database_exists(credentials, db_name):
                logger.error("Database %s still exists after DROP", db_name)
                results[db_name] = False
            else:
                results[db_name] = True

        except Exception as e:
            logger.error("Failed to delete %s: %s", db_name, e)
            results[db_name] = False

    return results


def _admin_delete_user_orphan_databases_simulation(
    dbhost: str,
    database_names: list[str],
    admin_user: str,
) -> dict[str, bool]:
    """Simulation mode user orphan deletion."""
    from pulldb.simulation.core.state import get_simulation_state

    state = get_simulation_state()
    results: dict[str, bool] = {}

    with state.lock:
        for db_name in database_names:
            if not _extract_user_code(db_name):
                results[db_name] = False
                continue

            host_dbs = state.staging_databases.get(dbhost, set())
            if db_name not in host_dbs:
                results[db_name] = True
                continue

            state.deleted_orphans.add((dbhost, db_name))
            logger.info(
                "[SIMULATION] Admin %s deleted user-orphan database: %s on %s",
                admin_user,
                db_name,
                dbhost,
            )
            results[db_name] = True

    return results


# Legacy function for backwards compatibility
def cleanup_host_staging(
    dbhost: str,
    job_repo: JobRepository,
    host_repo: HostRepository,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> CleanupResult:
    """Clean up orphaned staging databases on a specific host.

    DEPRECATED: Use cleanup_from_jobs() for new code.

    This is kept for API compatibility but now uses the safer job-based
    approach internally.
    """
    return cleanup_from_jobs(
        dbhost=dbhost,
        job_repo=job_repo,
        host_repo=host_repo,
        retention_days=retention_days,
        dry_run=dry_run,
    )


# Legacy function for backwards compatibility
def find_orphaned_staging(
    dbhost: str,
    job_repo: JobRepository,
    host_repo: HostRepository,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> list[CleanupCandidate]:
    """Find orphaned staging databases on a specific host.

    DEPRECATED: Use find_cleanup_candidates_from_jobs() for new code.
    """
    return find_cleanup_candidates_from_jobs(
        dbhost=dbhost,
        job_repo=job_repo,
        host_repo=host_repo,
        retention_days=retention_days,
    )


# =============================================================================
# Retention-Based Cleanup (Database Expiration System)
# =============================================================================


@dataclass
class RetentionCleanupResult:
    """Result of retention-based database cleanup."""

    started_at: datetime
    completed_at: datetime | None = None
    grace_days: int = 7
    candidates_found: int = 0
    databases_dropped: int = 0
    databases_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    dropped_jobs: list[str] = field(default_factory=list)


def run_retention_cleanup(
    job_repo: "JobRepository",
    host_repo: "HostRepository",
    settings_repo: "SettingsRepository",
    dry_run: bool = False,
) -> RetentionCleanupResult:
    """Run retention-based cleanup of expired databases.

    Finds complete jobs that are:
    - Past expiration date + grace period
    - Not locked
    - Database not already dropped

    For each candidate, drops the actual database on the target host and
    marks the job as db_dropped.

    Args:
        job_repo: Job repository.
        host_repo: Host repository for credentials.
        settings_repo: Settings repository for grace_days config.
        dry_run: If True, don't actually drop databases.

    Returns:
        RetentionCleanupResult with counts and details.
    """
    from pulldb.domain.models import Job as JobModel

    started_at = datetime.now(UTC)
    grace_days = settings_repo.get_cleanup_grace_days()

    result = RetentionCleanupResult(
        started_at=started_at,
        grace_days=grace_days,
    )

    # Get all cleanup candidates
    candidates = job_repo.get_expired_cleanup_candidates(grace_days)
    result.candidates_found = len(candidates)

    if not candidates:
        logger.info(
            "No retention cleanup candidates found (grace_days=%d)", grace_days
        )
        result.completed_at = datetime.now(UTC)
        return result

    logger.info(
        "Starting retention cleanup: candidates=%d, grace_days=%d, dry_run=%s",
        len(candidates),
        grace_days,
        dry_run,
    )

    # Group candidates by host for efficient processing
    by_host: dict[str, list[JobModel]] = {}
    for job in candidates:
        if job.dbhost not in by_host:
            by_host[job.dbhost] = []
        by_host[job.dbhost].append(job)

    # Process each host
    for dbhost, jobs in by_host.items():
        try:
            _process_retention_cleanup_host(
                dbhost=dbhost,
                jobs=jobs,
                job_repo=job_repo,
                host_repo=host_repo,
                result=result,
                dry_run=dry_run,
            )
        except Exception as e:
            error_msg = f"Error processing host {dbhost}: {e}"
            logger.exception(error_msg)
            result.errors.append(error_msg)

    result.completed_at = datetime.now(UTC)

    duration = (result.completed_at - result.started_at).total_seconds()
    logger.info(
        "Retention cleanup complete: candidates=%d, dropped=%d, skipped=%d, "
        "errors=%d, duration=%.2fs",
        result.candidates_found,
        result.databases_dropped,
        result.databases_skipped,
        len(result.errors),
        duration,
    )

    return result


def _process_retention_cleanup_host(
    dbhost: str,
    jobs: list["Job"],
    job_repo: "JobRepository",
    host_repo: "HostRepository",
    result: RetentionCleanupResult,
    dry_run: bool,
) -> None:
    """Process retention cleanup for a single host.

    Args:
        dbhost: Database host to process.
        jobs: Jobs with databases on this host.
        job_repo: Job repository.
        host_repo: Host repository for credentials.
        result: Result object to update.
        dry_run: If True, don't actually drop databases.
    """
    # Get connection to target host
    try:
        host = host_repo.get_host_by_hostname(dbhost)
        if not host:
            error_msg = f"Host {dbhost} not found in db_hosts"
            logger.error(error_msg)
            result.errors.append(error_msg)
            result.databases_skipped += len(jobs)
            return

        creds = host_repo.get_host_credentials(dbhost)

    except Exception as e:
        error_msg = f"Error getting credentials for {dbhost}: {e}"
        logger.exception(error_msg)
        result.errors.append(error_msg)
        result.databases_skipped += len(jobs)
        return

    # Connect and process jobs
    try:
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.username,
            password=creds.password,
        )
        cursor = conn.cursor()

        for job in jobs:
            try:
                _drop_job_database(
                    job=job,
                    cursor=cursor,
                    job_repo=job_repo,
                    result=result,
                    dry_run=dry_run,
                )
            except Exception as e:
                error_msg = f"Error dropping database for job {job.id}: {e}"
                logger.exception(error_msg)
                result.errors.append(error_msg)
                result.databases_skipped += 1

        conn.close()

    except mysql.connector.Error as e:
        error_msg = f"MySQL connection error for {dbhost}: {e}"
        logger.exception(error_msg)
        result.errors.append(error_msg)
        result.databases_skipped += len(jobs)


def _drop_job_database(
    job: "Job",
    cursor: "mysql.connector.cursor.MySQLCursor",
    job_repo: "JobRepository",
    result: RetentionCleanupResult,
    dry_run: bool,
) -> None:
    """Drop the database for a single job.

    Args:
        job: Job whose database to drop.
        cursor: MySQL cursor.
        job_repo: Job repository.
        result: Result object to update.
        dry_run: If True, don't actually drop.
    """
    # The target name is the actual database name after rename
    db_name = job.target

    # Validate it's safe to drop - skip protected databases
    if db_name.lower() in PROTECTED_DATABASES:
        logger.warning(
            "Skipping protected database %s for job %s", db_name, job.id
        )
        result.databases_skipped += 1
        return

    # DEFENSE-IN-DEPTH: Double-check no deployed job exists for this target
    # This should never trigger since get_expired_cleanup_candidates filters,
    # but provides an extra safety layer.
    # FAIL-SAFE: If protection check throws, SKIP this database (don't drop it)
    try:
        protection = is_target_database_protected(db_name, job.dbhost, job_repo)
        if not protection.can_drop:
            logger.warning(
                "SAFETY: Skipping retention cleanup for %s on %s - %s (job %s). "
                "This indicates a potential bug in get_expired_cleanup_candidates.",
                db_name,
                job.dbhost,
                protection.reason,
                job.id,
            )
            result.databases_skipped += 1
            result.errors.append(
                f"Safety check blocked drop of {db_name}: {protection.reason}"
            )
            return
    except Exception as e:
        logger.error(
            "FAIL-SAFE: Protection check threw exception for %s on %s (job %s): %s. "
            "Skipping this database to prevent potential data loss.",
            db_name,
            job.dbhost,
            job.id,
            e,
        )
        result.databases_skipped += 1
        result.errors.append(
            f"Protection check failed for {db_name}: {e}"
        )
        return

    if dry_run:
        logger.info(
            "[DRY RUN] Would drop database %s on %s (job %s)",
            db_name,
            job.dbhost,
            job.id,
        )
        result.databases_dropped += 1
        result.dropped_jobs.append(job.id)
        return

    # Drop the database
    try:
        # Use backticks for identifier quoting
        cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        logger.info(
            "Dropped expired database %s on %s (job %s)",
            db_name,
            job.dbhost,
            job.id,
        )

        # Mark job as db_dropped
        job_repo.mark_db_dropped(job.id)
        job_repo.append_job_event(
            job.id,
            "retention_cleanup",
            f"Database {db_name} dropped (expired + grace period)",
        )

        result.databases_dropped += 1
        result.dropped_jobs.append(job.id)

    except mysql.connector.Error as e:
        error_msg = f"Failed to drop {db_name} on {job.dbhost}: {e}"
        logger.exception(error_msg)
        result.errors.append(error_msg)
        result.databases_skipped += 1
