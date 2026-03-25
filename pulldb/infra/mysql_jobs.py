"""MySQL job repository for pullDB.

Implements the JobRepository class handling all job queue operations:
CRUD, status transitions, event logging, locking, cleanup, and queries.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import json
import logging
import uuid
import warnings
from datetime import UTC, datetime
from typing import Any, ClassVar, cast

from mysql.connector import errorcode
from mysql.connector import errors as mysql_errors

from pulldb.infra.mysql_settings import SettingsRepository as _SettingsRepo

from pulldb.domain.models import (
    Job,
    JobEvent,
    JobStatus,
    MaintenanceItems,
)
from pulldb.infra.mysql_pool import (
    MySQLPool,
    TypedDictCursor,
    TypedTupleCursor,
)

logger = logging.getLogger(__name__)

_ACTIVE_JOBS_VIEW_QUERY = """
SELECT id, owner_user_id, owner_username, owner_user_code, target,
    staging_name, dbhost, status, submitted_at, started_at, can_cancel
FROM active_jobs
ORDER BY submitted_at ASC
"""

_ACTIVE_JOBS_TABLE_QUERY = """
SELECT id, owner_user_id, owner_username, owner_user_code, target,
    staging_name, dbhost, status, submitted_at, started_at, can_cancel
FROM jobs
WHERE status IN ('queued','running')
ORDER BY submitted_at ASC
"""


class JobRepository:
    """Repository for job queue operations.

    Manages job lifecycle in MySQL coordination database (pulldb_service). 
    Handles job creation, status transitions, event logging, and queue queries. 
    Enforces business rules like per-target exclusivity via database constraints.
    
    Note: "Coordination database" refers to the concept of the database that 
    coordinates pullDB operations. The actual database name is 'pulldb_service',
    set via PULLDB_MYSQL_DATABASE environment variable.

    Example:
        >>> pool = MySQLPool(host="localhost", user="root", database="pulldb_service")
        >>> repo = JobRepository(pool)
        >>> job_id = repo.enqueue_job(job)
        >>> claimed = repo.claim_next_job(worker_id="worker-1:1234")
        >>> if claimed:
        ...     process(claimed)  # Job is already 'running'
    """

    # Constants for stale running job recovery
    # Higher than delete timeout (5 min) because restores take longer
    STALE_RUNNING_TIMEOUT_MINUTES: ClassVar[int] = 15
    # Number of process list checks before declaring a job stale
    STALE_RUNNING_PROCESS_CHECK_COUNT: ClassVar[int] = 3
    # Delay between process list checks (seconds)
    STALE_RUNNING_PROCESS_CHECK_DELAY_SECONDS: ClassVar[float] = 2.0

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize repository with connection pool.

        Args:
            pool: MySQL connection pool for coordination database.
        """
        self.pool = pool
        self._active_jobs_view_available = True

    def enqueue_job(self, job: Job) -> str:
        """Insert new job into queue.

        Generates UUID for job if not provided. Job enters 'queued' status and
        waits for worker to pick it up. Per-target exclusivity is enforced by
        unique constraint on active_target_key.

        Args:
            job: Job to enqueue (may have empty id, will be generated).

        Returns:
            job_id: UUID of enqueued job.

        Raises:
            mysql_errors.IntegrityError: If target already has active job.
        """
        job_id = job.id if job.id else str(uuid.uuid4())

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            try:
                cursor.execute(
                    """
                    INSERT INTO jobs
                    (id, owner_user_id, owner_username, owner_user_code, target,
                     staging_name, dbhost, status, submitted_at, options_json,
                     retry_count, custom_target, origin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), %s, %s, %s, %s)
                    """,
                    (
                        job_id,
                        job.owner_user_id,
                        job.owner_username,
                        job.owner_user_code,
                        job.target,
                        job.staging_name,
                        job.dbhost,
                        job.status.value,
                        json.dumps(job.options_json) if job.options_json else None,
                        job.retry_count,
                        1 if job.custom_target else 0,
                        job.origin,
                    ),
                )
                conn.commit()
                # Emit queued event as first lifecycle event
                self.append_job_event(job_id, "queued", "Job submitted")
                return job_id
            except mysql_errors.IntegrityError as e:
                if "idx_jobs_active_target" in str(e):
                    raise ValueError(
                        f"Target '{job.target}' on host '{job.dbhost}' "
                        f"already has an active job"
                    ) from e
                raise

    def create_claimed_job(
        self,
        *,
        job_id: str,
        owner_user_id: str,
        owner_username: str,
        owner_user_code: str,
        target: str,
        dbhost: str,
        origin: str,
    ) -> str:
        """Create a synthetic deployed job for an externally-managed database.

        Used by Database Discovery to record that a database on a target host
        is now tracked by pullDB, without going through the restore pipeline.
        The job is inserted directly into 'deployed' status.

        The staging_name is set to '{target}_claimed' as a sentinel value —
        no staging database is ever created for claimed jobs.

        Args:
            job_id: Pre-generated UUID for the job.
            owner_user_id: UUID of the user who owns this database.
            owner_username: Username of the owner.
            owner_user_code: 6-char user code of the owner.
            target: Database name on the target host.
            dbhost: Target MySQL host where the database lives.
            origin: How the job was created ('claim' or 'assign').

        Returns:
            job_id of the created job.

        Raises:
            ValueError: If target already has a deployed job (atomic check),
                or if origin is not 'claim' or 'assign'.
        """
        if origin not in ("claim", "assign"):
            raise ValueError(f"origin must be 'claim' or 'assign', got '{origin}'")

        retention_days = _SettingsRepo(self.pool).get_default_retention_days()
        staging_name = f"{target}_claimed"

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            # Use INSERT ... SELECT with NOT EXISTS to atomically prevent
            # duplicate deployed jobs for the same target+host. The
            # active_target_key virtual column only covers queued/running/
            # canceling status, so deployed jobs have no unique constraint.
            # This atomic pattern eliminates the TOCTOU gap between the
            # application-level has_any_deployed_job_for_target() check and
            # the INSERT.
            cursor.execute(
                """
                INSERT INTO jobs
                (id, owner_user_id, owner_username, owner_user_code, target,
                 staging_name, dbhost, status, submitted_at, completed_at,
                 expires_at, options_json, retry_count, custom_target,
                 can_cancel, origin)
                SELECT %s, %s, %s, %s, %s, %s, %s, 'deployed',
                    UTC_TIMESTAMP(6), UTC_TIMESTAMP(6),
                    DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s DAY),
                    NULL, 0, 0, FALSE, %s
                FROM DUAL
                WHERE NOT EXISTS (
                    SELECT 1 FROM jobs
                    WHERE target = %s AND dbhost = %s
                      AND status = 'deployed'
                      AND superseded_at IS NULL
                      AND db_dropped_at IS NULL
                )
                """,
                (
                    job_id,
                    owner_user_id,
                    owner_username,
                    owner_user_code,
                    target,
                    staging_name,
                    dbhost,
                    retention_days,
                    origin,
                    target,
                    dbhost,
                ),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                raise ValueError(
                    f"Target '{target}' on host '{dbhost}' "
                    f"already has a deployed job"
                )
            conn.commit()
            self.append_job_event(
                job_id,
                "claimed" if origin == "claim" else "assigned",
                f"Database tracked via discovery ({origin})",
            )
            return job_id

    def get_next_queued_job(self) -> Job | None:
        """Get next queued job in FIFO order.

        .. deprecated:: 0.0.5
            Use :meth:`claim_next_job` instead. This method does not lock the job
            and is NOT safe for multi-worker deployments.

        Returns oldest queued job by submitted_at timestamp.

        Returns:
            Next queued job or None if queue empty.
        """
        warnings.warn(
            "get_next_queued_job() is deprecated and unsafe for multi-worker. "
            "Use claim_next_job() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id,
                       can_cancel, cancel_requested_at
                FROM jobs
                WHERE status = 'queued'
                ORDER BY submitted_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def claim_next_job(self, worker_id: str | None = None) -> Job | None:
        """Atomically claim next queued job for processing.

        Uses SELECT FOR UPDATE SKIP LOCKED to safely claim jobs when multiple
        workers are running. The job is marked as 'running' within the same
        transaction, ensuring no two workers can claim the same job.

        Only claims jobs where the target host has running capacity
        (running jobs < max_running_jobs). This ensures per-host concurrency
        limits are enforced at the worker level.

        This is the PREFERRED method for worker job acquisition. The older
        get_next_queued_job() + mark_job_running() pattern is NOT safe for
        multi-worker deployments.

        Args:
            worker_id: Optional identifier of claiming worker. Persisted to
                       the jobs.worker_id column for debugging/monitoring.
                       Format: "hostname:pid" or similar unique identifier.

        Returns:
            Claimed job (now in 'running' status) or None if queue empty
            or all hosts at running capacity.

        Example:
            >>> job = repo.claim_next_job(worker_id="worker-1:12345")
            >>> if job:
            ...     # Job is already 'running' - safe to process
            ...     process(job)
        """
        if _SettingsRepo(self.pool).is_maintenance_mode_enabled():
            return None

        with self.pool.transaction() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # SELECT with FOR UPDATE SKIP LOCKED:
            # - FOR UPDATE: Locks the row until transaction commits
            # - SKIP LOCKED: If row already locked by another worker, skip it
            # - JOIN with db_hosts to enforce per-host running capacity
            # - Subquery counts running jobs per host
            # This prevents blocking and ensures each job claimed by exactly one worker
            cursor.execute(
                """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code, j.target,
                       j.staging_name, j.dbhost, j.status, j.submitted_at, j.started_at,
                       j.completed_at, j.options_json, j.retry_count, j.error_detail, j.worker_id,
                       j.custom_target, j.origin
                FROM jobs j
                JOIN db_hosts h ON j.dbhost = h.hostname
                WHERE j.status = 'queued'
                  AND h.enabled = TRUE
                  AND (
                    SELECT COUNT(*) FROM jobs j2 
                    WHERE j2.dbhost = j.dbhost AND j2.status = 'running'
                  ) < h.max_running_jobs
                ORDER BY j.submitted_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
            row = cursor.fetchone()

            if not row:
                return None

            job_id = row["id"]

            # Update to running within same transaction
            # This is atomic with the SELECT FOR UPDATE
            # worker_id is persisted for debugging/monitoring in multi-daemon deployments
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    started_at = UTC_TIMESTAMP(6),
                    worker_id = %s
                WHERE id = %s
                """,
                (worker_id, job_id),
            )

            # Log worker claim if worker_id provided
            if worker_id:
                logger.debug(
                    "Job claimed by worker",
                    extra={"job_id": job_id, "worker_id": worker_id},
                )

            # Transaction commits on context manager exit
            # Return job with updated status and started_at
            # Use current time as approximation since DB sets it in UPDATE
            job = self._row_to_job(row)
            now = datetime.now(UTC).replace(tzinfo=None)
            return Job(
                id=job.id,
                owner_user_id=job.owner_user_id,
                owner_username=job.owner_username,
                owner_user_code=job.owner_user_code,
                target=job.target,
                staging_name=job.staging_name,
                dbhost=job.dbhost,
                status=JobStatus.RUNNING,  # Reflect the updated status
                submitted_at=job.submitted_at,
                started_at=now,  # Approximate; DB sets via UTC_TIMESTAMP(6)
                completed_at=job.completed_at,
                options_json=job.options_json,
                retry_count=job.retry_count,
                error_detail=job.error_detail,
                worker_id=worker_id,  # Reflect the worker that claimed this job
                custom_target=job.custom_target,
                origin=job.origin,
            )

    def get_job_by_id(self, job_id: str) -> Job | None:
        """Get job by ID.

        Args:
            job_id: UUID of job.

        Returns:
            Job or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id,
                       staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def find_jobs_by_prefix(self, prefix: str, limit: int = 10) -> list[Job]:
        """Find jobs by ID prefix.

        Supports short job ID prefixes (minimum 8 characters) for user
        convenience. Returns matching jobs ordered by submission time
        (newest first).

        Args:
            prefix: Job ID prefix (minimum 8 characters recommended).
            limit: Maximum number of results to return.

        Returns:
            List of matching jobs, empty if none found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            # Use LIKE for prefix matching - escape any special characters
            safe_prefix = prefix.replace("%", r"\%").replace("_", r"\_")
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id,
                       staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE id LIKE %s
                ORDER BY submitted_at DESC
                LIMIT %s
                """,
                (f"{safe_prefix}%", limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows if row]

    def search_jobs(
        self, query: str, limit: int = 50, exact: bool = False
    ) -> list[Job]:
        """Search jobs by query string.

        Searches across job ID, target database name, owner username, and
        user code. For queries of 4 characters, uses prefix matching.
        For queries longer than 4 characters, uses exact matching by default.

        Args:
            query: Search string (minimum 4 characters).
            limit: Maximum number of results to return.
            exact: If True, require exact match. If False, use LIKE prefix match.

        Returns:
            List of matching jobs ordered by submission time (newest first).
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            # Escape special SQL LIKE characters
            safe_query = query.replace("%", r"\%").replace("_", r"\_")

            if exact:
                # Exact match on any searchable field
                cursor.execute(
                    """
                    SELECT id, owner_user_id, owner_username, owner_user_code, target,
                           staging_name, dbhost, status, submitted_at, started_at,
                           completed_at, options_json, retry_count, error_detail, worker_id,
                           can_cancel, cancel_requested_at
                    FROM jobs
                    WHERE id = %s
                       OR target = %s
                       OR owner_username = %s
                       OR owner_user_code = %s
                    ORDER BY submitted_at DESC
                    LIMIT %s
                    """,
                    (query, query, query, query, limit),
                )
            else:
                # Prefix match using LIKE
                pattern = f"{safe_query}%"
                cursor.execute(
                    """
                    SELECT id, owner_user_id, owner_username, owner_user_code, target,
                           staging_name, dbhost, status, submitted_at, started_at,
                           completed_at, options_json, retry_count, error_detail, worker_id,
                           can_cancel, cancel_requested_at
                    FROM jobs
                    WHERE id LIKE %s
                       OR target LIKE %s
                       OR owner_username LIKE %s
                       OR owner_user_code LIKE %s
                    ORDER BY submitted_at DESC
                    LIMIT %s
                    """,
                    (pattern, pattern, pattern, pattern, limit),
                )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows if row]

    def get_last_job_by_user_code(self, user_code: str) -> Job | None:
        """Get the most recent job submitted by a user.

        Args:
            user_code: The user code to look up jobs for.

        Returns:
            The most recent job for the user, or None if no jobs found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id,
                       can_cancel, cancel_requested_at
                FROM jobs
                WHERE owner_user_code = %s
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (user_code,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_job(row)

    def mark_job_running(self, job_id: str) -> None:
        """Mark job as running and set started_at timestamp.

        .. deprecated:: 0.0.5
            Use :meth:`claim_next_job` instead, which atomically claims and
            marks the job as running in a single transaction.

        Args:
            job_id: UUID of job.

        Raises:
            ValueError: If job not found or not in queued status.
        """
        warnings.warn(
            "mark_job_running() is deprecated. Use claim_next_job() instead, "
            "which atomically claims and transitions the job.",
            DeprecationWarning,
            stacklevel=2,
        )
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'running', started_at = UTC_TIMESTAMP(6)
                WHERE id = %s AND status = 'queued'
                """,
                (job_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Job {job_id} not found or not in queued status")
            conn.commit()

    def mark_job_deployed(self, job_id: str) -> bool:
        """Mark job as deployed and set completed_at timestamp.

        Called by worker when job successfully finishes. Updates status to
        'deployed', records completion time, sets expires_at based on
        the default_retention_days setting (default: 7 days = 1 week), 
        and clears the worker processing lock.

        IMPORTANT: Only updates if job is still in 'running' status. This
        prevents race conditions where stale recovery marks a job as failed
        but the restore completes and tries to mark it deployed.

        Note:
            The worker_id column is intentionally retained after deployment
            for debugging purposes (to identify which worker processed the job).
            The expires_at is calculated as completed_at + default_retention_days
            using the current setting value.
            The locked_at/locked_by fields are cleared since the database is now
            available for user actions.

        Args:
            job_id: UUID of job.

        Returns:
            True if job was successfully marked deployed, False if job was
            no longer in 'running' status (e.g., marked failed by stale recovery).
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            # Get default_retention_days via SettingsRepository (validated accessor)
            retention_days = _SettingsRepo(self.pool).get_default_retention_days()

            # Only update if still in running status - prevents overwriting
            # 'failed' status set by stale recovery
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'deployed', 
                    completed_at = UTC_TIMESTAMP(6),
                    expires_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s DAY),
                    locked_at = NULL,
                    locked_by = NULL
                WHERE id = %s AND status = 'running'
                """,
                (retention_days, job_id),
            )
            updated = bool(cursor.rowcount > 0)
            conn.commit()
            
            if not updated:
                logger.warning(
                    "Failed to mark job deployed - job no longer in running status",
                    extra={"job_id": job_id},
                )
            
            return updated

    def mark_job_user_completed(self, job_id: str) -> None:
        """Mark deployed job as user-completed, moving to History.

        Called when user marks a deployed database as complete (done using it).
        Changes status from 'deployed' to 'complete' which moves the job
        to the History view. Also sets completed_at timestamp.

        Args:
            job_id: UUID of job.

        Raises:
            ValueError: If job not found or not in deployed status.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'complete', completed_at = UTC_TIMESTAMP(6)
                WHERE id = %s AND status = 'deployed'
                """,
                (job_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Job {job_id} not found or not in deployed status")
            conn.commit()

    def mark_job_expired(self, job_id: str) -> bool:
        """Mark deployed job as expired when retention period has passed.

        Called by frontend when it detects a deployed job with expires_at in the past.
        Changes status from 'deployed' to 'expired' which moves the job
        to the History view (cleanup window).

        Args:
            job_id: UUID of job.

        Returns:
            True if job was updated, False if not found or not eligible.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'expired'
                WHERE id = %s 
                  AND status = 'deployed'
                  AND expires_at IS NOT NULL
                  AND expires_at <= UTC_TIMESTAMP()
                """,
                (job_id,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def mark_jobs_expired_batch(self, job_ids: list[str]) -> int:
        """Mark multiple deployed jobs as expired in a single transaction.

        Args:
            job_ids: List of job UUIDs to check and mark as expired.

        Returns:
            Number of jobs that were updated.
        """
        if not job_ids:
            return 0
            
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            placeholders = ", ".join(["%s"] * len(job_ids))
            cursor.execute(
                f"""
                UPDATE jobs
                SET status = 'expired'
                WHERE id IN ({placeholders})
                  AND status = 'deployed'
                  AND expires_at IS NOT NULL
                  AND expires_at <= UTC_TIMESTAMP()
                """,
                tuple(job_ids),
            )
            conn.commit()
            return int(cursor.rowcount)

    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail.

        Called by worker when job execution fails. Updates status to 'failed',
        records completion time, stores error message, clears any pending
        cancellation request, releases the worker lock, and sets expires_at
        based on default_retention_days so failed jobs don't accumulate
        indefinitely in History.

        Note:
            The worker_id column is intentionally retained after failure
            for debugging purposes (to identify which worker processed the job).
            The cancel_requested_at is cleared since the job has reached a
            terminal state and the cancellation is no longer relevant.
            The locked_at/locked_by/can_cancel fields are cleared since
            failed jobs should be deletable and no longer need protection.
            The expires_at is set to completed_at + default_retention_days
            to prevent indefinite accumulation of failed job records.

        Args:
            job_id: UUID of job.
            error: Error message describing failure.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            retention_days = _SettingsRepo(self.pool).get_default_retention_days()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed', completed_at = UTC_TIMESTAMP(6),
                    expires_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s DAY),
                    error_detail = %s, cancel_requested_at = NULL,
                    locked_at = NULL, locked_by = NULL, can_cancel = TRUE
                WHERE id = %s
                """,
                (retention_days, error, job_id),
            )
            conn.commit()

    def update_job_options(self, job_id: str, options: dict) -> None:
        """Update a job's options_json field.

        Used to add audit trail information (e.g., resubmit_of_job_id).

        Args:
            job_id: UUID of job to update.
            options: New options dictionary to store.
        """
        import json
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET options_json = %s
                WHERE id = %s
                """,
                (json.dumps(options), job_id),
            )
            conn.commit()

    def has_restore_started(self, job_id: str) -> bool:
        """Check if myloader restore has started for a job.

        Used to determine if cancellation is still possible. Once myloader
        starts, the job cannot be safely canceled (myloader cannot be killed
        without risking database corruption or long rollback).

        Args:
            job_id: UUID of job to check.

        Returns:
            True if restore_started event exists, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT 1 FROM job_events
                WHERE job_id = %s AND event_type = 'restore_started'
                LIMIT 1
                """,
                (job_id,),
            )
            return cursor.fetchone() is not None

    def mark_job_canceling(self, job_id: str) -> bool:
        """Transition a running job to canceling state.

        Sets status to 'canceling' to indicate cancellation is in progress.
        Worker will detect this and stop at next checkpoint.

        Args:
            job_id: UUID of job.

        Returns:
            True if status was updated, False if job not in running state.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'canceling', cancel_requested_at = UTC_TIMESTAMP(6)
                WHERE id = %s AND status = 'running'
                """,
                (job_id,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def request_cancellation(self, job_id: str) -> bool:
        """Request cancellation of a job.

        Sets cancel_requested_at timestamp to signal worker to stop processing.
        Only jobs that meet all criteria can be canceled:
        - Status is 'queued' or 'running'
        - can_cancel is TRUE (not yet in restore phase)
        - No cancellation already requested

        Args:
            job_id: UUID of job to cancel.

        Returns:
            True if cancellation was requested, False if job not in cancelable state
            (either wrong status, already in restore phase, or already canceling).

        Raises:
            ValueError: If job not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET cancel_requested_at = UTC_TIMESTAMP(6)
                WHERE id = %s 
                  AND status IN ('queued', 'running')
                  AND can_cancel = TRUE
                  AND cancel_requested_at IS NULL
                """,
                (job_id,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def mark_job_canceled(self, job_id: str, reason: str | None = None) -> None:
        """Mark job as canceled and set completed_at timestamp.

        Called by worker when it detects cancellation request and stops processing.
        Updates status to 'canceled', records completion time, and sets expires_at
        based on default_retention_days so canceled jobs don't accumulate
        indefinitely in History.

        Args:
            job_id: UUID of job.
            reason: Optional reason for cancellation (stored in error_detail).
        """
        error_detail = reason or "Canceled by user request"
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            retention_days = _SettingsRepo(self.pool).get_default_retention_days()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'canceled', completed_at = UTC_TIMESTAMP(6),
                    expires_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s DAY),
                    error_detail = %s
                WHERE id = %s
                """,
                (retention_days, error_detail, job_id),
            )
            conn.commit()

    def mark_job_deleting(self, job_id: str) -> None:
        """Mark job as deleting (async delete in progress).

        Sets status to 'deleting' to indicate database deletion is in progress.
        Used by bulk delete task and single delete before dropping databases.

        Also sets:
        - started_at: Timestamp for stale detection (worker recovery)
        - worker_id: Cleared to allow worker to claim stale deleting jobs
        - retry_count: Incremented to track delete attempts (max 5)

        Args:
            job_id: UUID of job.
        """

        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Get current retry_count before incrementing
            cursor.execute(
                "SELECT retry_count FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
            current_retry = row["retry_count"] if row else 0
            new_retry = current_retry + 1

            cursor.execute(
                """
                UPDATE jobs
                SET status = 'deleting',
                    started_at = UTC_TIMESTAMP(6),
                    worker_id = NULL,
                    retry_count = %s
                WHERE id = %s
                """,
                (new_retry, job_id),
            )

            # Log delete_started event with attempt number
            detail = json.dumps({"attempt": new_retry})
            cursor.execute(
                """
                INSERT INTO job_events
                (job_id, event_type, detail, logged_at)
                VALUES (%s, 'delete_started', %s, UTC_TIMESTAMP(6))
                """,
                (job_id, detail),
            )

            conn.commit()

    def mark_job_deleted(self, job_id: str, detail: str | None = None) -> None:
        """Mark job as deleted (soft delete complete).

        User-initiated deletion. Updates status to 'deleted' and sets
        completed_at if not already set. Used after databases are dropped.

        Args:
            job_id: UUID of job.
            detail: Optional detail about the deletion (stored in error_detail).
        """
        error_detail = detail or "Databases deleted by user"
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'deleted',
                    completed_at = COALESCE(completed_at, UTC_TIMESTAMP(6)),
                    error_detail = %s
                WHERE id = %s
                """,
                (error_detail, job_id),
            )
            conn.commit()

    def claim_stale_deleting_job(
        self,
        worker_id: str | None = None,
        stale_timeout_minutes: int = 5,
        max_retry_count: int = 5,
    ) -> Job | None:
        """Atomically claim a stale job stuck in 'deleting' status.

        Jobs enter 'deleting' status when database deletion starts. If the
        process crashes or times out, the job gets stuck. This method allows
        workers to reclaim and retry stale deleting jobs.

        Uses SELECT FOR UPDATE SKIP LOCKED for safe multi-worker operation.

        Args:
            worker_id: Optional identifier of claiming worker.
            stale_timeout_minutes: Minutes before a deleting job is considered stale.
            max_retry_count: Maximum retry attempts before permanent failure.

        Returns:
            Claimed job (still in 'deleting' status) or None if no stale jobs.
        """

        with self.pool.transaction() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Find stale deleting jobs that haven't exceeded retry limit.
            # IMPORTANT: Only skip jobs that were EXPLICITLY marked as superseded
            # (superseded_by_job_id IS NOT NULL). The old NOT EXISTS check was too
            # aggressive - it blocked recovery of legitimate zombie jobs just because
            # a newer job for the same target existed, even if that newer job didn't
            # actually supersede this one during its restore process.
            # Also handle legacy jobs with NULL started_at (treat as stale).
            cursor.execute(
                """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.worker_id, j.custom_target, j.origin
                FROM jobs j
                WHERE j.status = 'deleting'
                  AND (j.started_at IS NULL 
                       OR j.started_at < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL %s MINUTE))
                  AND j.retry_count < %s
                  AND j.superseded_by_job_id IS NULL
                ORDER BY j.started_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (stale_timeout_minutes, max_retry_count),
            )
            row = cursor.fetchone()

            if not row:
                return None

            job_id = row["id"]
            new_retry = row["retry_count"] + 1

            logger.warning(
                "Reclaiming stale deleting job",
                extra={
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "retry_count": new_retry,
                    "previous_started_at": row["started_at"],
                },
            )

            # Update to refresh started_at and assign worker
            cursor.execute(
                """
                UPDATE jobs
                SET started_at = UTC_TIMESTAMP(6),
                    worker_id = %s,
                    retry_count = %s
                WHERE id = %s
                """,
                (worker_id, new_retry, job_id),
            )

            # Log delete_retry event
            detail = json.dumps({
                "attempt": new_retry,
                "reclaimed_by": worker_id,
                "stale_since": row["started_at"].isoformat() if row["started_at"] else None,
            })
            cursor.execute(
                """
                INSERT INTO job_events
                (job_id, event_type, detail, logged_at)
                VALUES (%s, 'delete_retry', %s, UTC_TIMESTAMP(6))
                """,
                (job_id, detail),
            )

            # Transaction commits on context manager exit
            job = self._row_to_job(row)
            return Job(
                id=job.id,
                owner_user_id=job.owner_user_id,
                owner_username=job.owner_username,
                owner_user_code=job.owner_user_code,
                target=job.target,
                staging_name=job.staging_name,
                dbhost=job.dbhost,
                status=JobStatus.DELETING,
                submitted_at=job.submitted_at,
                started_at=datetime.now(UTC).replace(tzinfo=None),
                completed_at=job.completed_at,
                options_json=job.options_json,
                retry_count=new_retry,
                error_detail=job.error_detail,
                worker_id=worker_id,
                custom_target=job.custom_target,
                origin=job.origin,
            )

    def mark_job_delete_failed(
        self, job_id: str, error_detail: str | None = None
    ) -> None:
        """Mark job as failed after exhausting delete retry attempts.

        Called when a job has been stuck in 'deleting' and has exceeded
        the maximum retry count (5 attempts). Sets status to 'failed'
        with an appropriate error message.

        Args:
            job_id: UUID of job.
            error_detail: Optional error detail (defaults to retry exhaustion message).
        """

        detail = error_detail or "Delete failed after 5 attempts"
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    completed_at = COALESCE(completed_at, UTC_TIMESTAMP(6)),
                    error_detail = %s
                WHERE id = %s
                """,
                (detail, job_id),
            )

            # Log delete_failed event
            event_detail = json.dumps({"reason": detail})
            cursor.execute(
                """
                INSERT INTO job_events
                (job_id, event_type, detail, logged_at)
                VALUES (%s, 'delete_failed', %s, UTC_TIMESTAMP(6))
                """,
                (job_id, event_detail),
            )

            conn.commit()

    # Constants for zombie deleting job detection
    # Jobs stuck in 'deleting' for longer than this are considered zombies
    ZOMBIE_DELETING_TIMEOUT_HOURS: ClassVar[int] = 24

    def get_zombie_deleting_jobs(
        self,
        zombie_timeout_hours: int | None = None,
    ) -> list[Job]:
        """Find jobs stuck in 'deleting' status for an extended period (zombies).

        Unlike stale deleting jobs (5 min timeout, auto-retry), zombie jobs have
        been stuck for 24+ hours and likely need manual intervention. This can
        happen when:
        - Host was deleted and job can't be retried
        - Database was already cleaned up by another job
        - Max retry count exceeded but status stuck
        - Worker crashed during deletion and never recovered

        Args:
            zombie_timeout_hours: Hours stuck in deleting before considered zombie.
                Defaults to ZOMBIE_DELETING_TIMEOUT_HOURS (24).

        Returns:
            List of zombie jobs in 'deleting' status.
        """
        if zombie_timeout_hours is None:
            zombie_timeout_hours = self.ZOMBIE_DELETING_TIMEOUT_HOURS

        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            cursor.execute(
                """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.worker_id, j.custom_target, j.origin
                FROM jobs j
                WHERE j.status = 'deleting'
                  AND j.started_at < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL %s HOUR)
                ORDER BY j.started_at ASC
                """,
                (zombie_timeout_hours,),
            )

            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def force_complete_delete(
        self,
        job_id: str,
        reason: str,
        admin_username: str | None = None,
    ) -> bool:
        """Force-complete a stuck deleting job without database verification.

        Used for zombie jobs where:
        - Host is unavailable/deleted
        - Databases were already cleaned up
        - Job needs to be cleared from the queue

        This marks the job as 'deleted' without attempting to drop databases.

        Args:
            job_id: UUID of job to force-complete.
            reason: Reason for force-completion (logged in event).
            admin_username: Admin who initiated the action (for audit).

        Returns:
            True if job was updated, False if job not found or wrong status.
        """
        with self.pool.transaction() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Verify job exists and is in deleting or failed status
            cursor.execute(
                "SELECT id, status FROM jobs WHERE id = %s FOR UPDATE",
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return False

            if row["status"] not in ("deleting", "failed"):
                return False

            # Update to deleted status
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'deleted',
                    completed_at = COALESCE(completed_at, UTC_TIMESTAMP(6)),
                    db_dropped_at = UTC_TIMESTAMP(6),
                    error_detail = NULL
                WHERE id = %s
                """,
                (job_id,),
            )

            # Log force_deleted event with reason
            event_detail = json.dumps({
                "reason": reason,
                "admin": admin_username or "system",
                "previous_status": row["status"],
            })
            cursor.execute(
                """
                INSERT INTO job_events
                (job_id, event_type, detail, logged_at)
                VALUES (%s, 'force_deleted', %s, UTC_TIMESTAMP(6))
                """,
                (job_id, event_detail),
            )

            # Transaction commits on context manager exit
            return True

    def get_candidate_stale_running_job(
        self,
        stale_timeout_minutes: int | None = None,
    ) -> Job | None:
        """Find a candidate stale running job without claiming it.

        Jobs in 'running' status that have had no recent activity (job_events)
        for longer than the timeout may be from crashed workers. This method
        finds such jobs for verification before marking them as failed.

        IMPORTANT: Staleness is determined by the most recent job_event, NOT
        by started_at. This prevents false positives during long downloads
        where progress events are being logged regularly.

        Uses SELECT FOR UPDATE SKIP LOCKED to prevent multiple workers from
        checking the same job simultaneously. The lock is held only briefly
        during this check.

        Does NOT update the job - use confirm_stale_running_job() after
        verifying the job is actually stale (via process list check).

        Args:
            stale_timeout_minutes: Minutes since last activity before a running
                job is considered potentially stale. Defaults to
                STALE_RUNNING_TIMEOUT_MINUTES.

        Returns:
            Job candidate that may be stale, or None if no candidates.
        """
        if stale_timeout_minutes is None:
            stale_timeout_minutes = self.STALE_RUNNING_TIMEOUT_MINUTES

        with self.pool.transaction() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Find running jobs with no recent activity (based on job_events).
            # IMPORTANT: Only recover jobs that are the NEWEST for their target.
            # Older superseded jobs should not be recovered.
            #
            # We check COALESCE(last_event.logged_at, j.started_at) to handle
            # edge cases where a job has no events yet (use started_at as fallback).
            cursor.execute(
                """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.worker_id, j.custom_target, j.origin
                FROM jobs j
                LEFT JOIN (
                    SELECT job_id, MAX(logged_at) AS last_logged_at
                    FROM job_events
                    GROUP BY job_id
                ) last_event ON last_event.job_id = j.id
                WHERE j.status = 'running'
                  AND j.started_at IS NOT NULL
                  AND COALESCE(last_event.last_logged_at, j.started_at)
                      < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL %s MINUTE)
                  AND NOT EXISTS (
                      SELECT 1 FROM jobs j2
                      WHERE j2.target = j.target
                        AND j2.owner_user_code = j.owner_user_code
                        AND j2.submitted_at > j.submitted_at
                  )
                ORDER BY COALESCE(last_event.last_logged_at, j.started_at) ASC
                LIMIT 1
                FOR UPDATE OF j SKIP LOCKED
                """,
                (stale_timeout_minutes,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            logger.info(
                "Found candidate stale running job",
                extra={
                    "job_id": row["id"],
                    "target": row["target"],
                    "started_at": row["started_at"],
                    "worker_id": row["worker_id"],
                    "stale_timeout_minutes": stale_timeout_minutes,
                },
            )

            # Return job without modifying it
            # Transaction commits on context manager exit, releasing lock
            return self._row_to_job(row)

    def mark_stale_running_failed(
        self,
        job_id: str,
        worker_id: str | None = None,
        error_detail: str | None = None,
    ) -> bool:
        """Mark a stale running job as failed after verification.

        Called after confirming (via process list check) that a running job
        is actually stale and not just a long-running restore. Transitions
        the job from 'running' to 'failed' and logs the recovery event.

        Args:
            job_id: UUID of job to mark as failed.
            worker_id: ID of worker performing the recovery.
            error_detail: Optional custom error detail. Defaults to standard
                stale recovery message.

        Returns:
            True if job was marked failed, False if job not found or already
            transitioned to another state.
        """

        detail = error_detail or "Worker died during restore (stale job recovery)"

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())

            # Only update if still in 'running' status (prevent race conditions)
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    completed_at = UTC_TIMESTAMP(6),
                    error_detail = %s,
                    worker_id = COALESCE(%s, worker_id)
                WHERE id = %s AND status = 'running'
                """,
                (detail, worker_id, job_id),
            )

            if cursor.rowcount == 0:
                logger.warning(
                    "Stale running job already transitioned",
                    extra={"job_id": job_id, "worker_id": worker_id},
                )
                conn.commit()
                return False

            # Log stale_running_recovery event
            event_detail = json.dumps({
                "reason": "stale_job_recovery",
                "recovered_by": worker_id,
                "error_detail": detail,
            })
            cursor.execute(
                """
                INSERT INTO job_events
                (job_id, event_type, detail, logged_at)
                VALUES (%s, 'stale_running_recovery', %s, UTC_TIMESTAMP(6))
                """,
                (job_id, event_detail),
            )

            conn.commit()

            logger.warning(
                "Marked stale running job as failed",
                extra={
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "error_detail": detail,
                },
            )
            return True

    def hard_delete_job(self, job_id: str) -> bool:
        """Hard delete a job record and its events.

        Permanently removes the job and all associated job_events from the
        database. This should only be called AFTER logging to audit_logs
        for compliance. The audit log preserves the deletion record.

        Args:
            job_id: UUID of job to delete.

        Returns:
            True if job was deleted, False if job not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            # Delete job_events first (FK constraint)
            cursor.execute(
                "DELETE FROM job_events WHERE job_id = %s",
                (job_id,),
            )
            # Delete the job record
            cursor.execute(
                "DELETE FROM jobs WHERE id = %s",
                (job_id,),
            )
            deleted = bool(cursor.rowcount > 0)
            conn.commit()
            return deleted

    def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job.

        Called by worker during long operations to check if it should stop.
        Checks both the cancel_requested_at timestamp and the 'canceling' status.

        Args:
            job_id: UUID of job.

        Returns:
            True if cancellation requested or job is in canceling state.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT (cancel_requested_at IS NOT NULL OR status = 'canceling') as is_requested
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            return bool(row and row[0])

    def should_abort_job(self, job_id: str) -> bool:
        """Check if a job should be aborted.

        Called by worker during long operations (download, restore) to check
        if the job should stop. Returns True if:
        - Cancellation was requested (cancel_requested_at IS NOT NULL)
        - Job is in 'canceling' status
        - Job is no longer in 'running' status (e.g., marked failed by stale recovery)

        This prevents the scenario where stale recovery marks a job as failed
        but the download continues running, wasting resources.

        Args:
            job_id: UUID of job.

        Returns:
            True if job should abort immediately.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT status, cancel_requested_at IS NOT NULL AS cancel_requested
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                # Job doesn't exist - abort
                return True
            status, cancel_requested = row
            # Abort if cancelled OR not in running state
            return bool(cancel_requested) or status not in ("running", "canceling")

    def get_cancel_requested_at(self, job_id: str) -> datetime | None:
        """Get the timestamp when cancellation was requested for a job.

        Used by web UI to show when a cancellation was requested.

        Args:
            job_id: UUID of job.

        Returns:
            Datetime when cancellation was requested, or None if not requested.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                "SELECT cancel_requested_at FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
            return row["cancel_requested_at"] if row else None

    def get_current_operation(self, job_id: str) -> str | None:
        """Get user-friendly current operation string for a job.

        Queries the latest job event and derives a human-readable operation
        string (e.g., "Downloading(45%)", "Restoring", "Queued").

        Args:
            job_id: UUID of job.

        Returns:
            Human-readable operation string, or None if job not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT j.status,
                       je.event_type AS last_event_type,
                       je.detail AS last_event_detail
                FROM jobs j
                LEFT JOIN (
                    SELECT job_id, event_type, detail
                    FROM job_events
                    WHERE job_id = %s
                    ORDER BY logged_at DESC
                    LIMIT 1
                ) je ON je.job_id = j.id
                WHERE j.id = %s
                """,
                (job_id, job_id),
            )
            row = cursor.fetchone()
            return self._derive_operation(row) if row else None

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running).

        Uses active_jobs view for efficient querying. Jobs returned in
        submission order (oldest first).

        Returns:
            List of active jobs ordered by submitted_at.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            rows = self._fetch_active_job_rows(cursor)
            return [self._row_to_active_job(row) for row in rows]

    def get_recent_jobs(
        self, limit: int = 100, offset: int = 0, statuses: list[str] | None = None
    ) -> list[Job]:
        """Get recent jobs (active + completed) with operation status.

        Returns jobs ordered by submission time (newest first).
        Includes current_operation derived from latest job event.

        Args:
            limit: Maximum number of jobs to return.
            offset: Number of jobs to skip.
            statuses: Optional list of status strings to filter by.

        Returns:
            List of jobs with populated current_operation.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            query = """
                WITH LatestEvents AS (
                    SELECT job_id, event_type, detail,
                           ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY logged_at DESC) as rn
                    FROM job_events
                )
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail,
                       le.event_type as last_event_type,
                       le.detail as last_event_detail
                FROM jobs j
                LEFT JOIN LatestEvents le ON j.id = le.job_id AND le.rn = 1
            """

            params: list[Any] = []
            if statuses:
                placeholders = ", ".join(["%s"] * len(statuses))
                query += f" WHERE j.status IN ({placeholders})"
                params.extend(statuses)

            query += " ORDER BY j.submitted_at DESC LIMIT %s OFFSET %s"
            params.append(limit)
            params.append(offset)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_user_last_job(self, user_code: str) -> Job | None:
        """Get the most recently submitted job for a user.

        Returns the user's last submitted job regardless of status.

        Args:
            user_code: The 6-character user code.

        Returns:
            The most recent Job, or None if no jobs found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code,
                       target, staging_name, dbhost, status, submitted_at,
                       started_at, completed_at, options_json, retry_count,
                       error_detail, worker_id, can_cancel, cancel_requested_at
                FROM jobs
                WHERE owner_user_code = %s
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (user_code,),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def get_job_history(
        self,
        limit: int = 100,
        retention_days: int | None = None,
        user_code: str | None = None,
        target: str | None = None,
        dbhost: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """Get historical jobs (completed, failed, canceled) with optional filtering.

        Returns jobs ordered by completion time (newest first). Only includes
        jobs that have completed (not queued or running).

        Args:
            limit: Maximum number of jobs to return.
            retention_days: Only return jobs completed within N days. None = no limit.
            user_code: Filter by owner_user_code.
            target: Filter by target database name.
            dbhost: Filter by database host.
            status: Filter by specific status (complete, failed, canceled).

        Returns:
            List of historical jobs with populated fields including error_detail.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            query = """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail
                FROM jobs j
                WHERE j.status IN ('complete', 'failed', 'canceled')
            """

            params: list[Any] = []

            # Retention filter
            if retention_days is not None:
                query += (
                    " AND j.completed_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)"
                )
                params.append(retention_days)

            # User filter
            if user_code:
                query += " AND j.owner_user_code = %s"
                params.append(user_code)

            # Target filter
            if target:
                query += " AND j.target = %s"
                params.append(target)

            # Dbhost filter
            if dbhost:
                query += " AND j.dbhost = %s"
                params.append(dbhost)

            # Status filter (within historical statuses)
            if status and status in ("complete", "failed", "canceled"):
                query += " AND j.status = %s"
                params.append(status)

            query += " ORDER BY j.completed_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_owned_databases(
        self,
        limit: int = 100,
        user_code: str | None = None,
        target: str | None = None,
        dbhost: str | None = None,
    ) -> list[Job]:
        """Get databases user currently owns (Active view).

        Returns jobs that represent currently owned databases:
        - Queued/running/canceling jobs (in progress)
        - Deployed jobs (database live, user actively working with it)

        Per retention-cleanup plan: "Shows all databases user currently owns
        (not cleaned up, not superseded)"

        Args:
            limit: Maximum number of jobs to return.
            user_code: Filter by owner_user_code.
            target: Filter by target database name.
            dbhost: Filter by database host.

        Returns:
            List of jobs representing owned databases, newest first.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Active (in-progress) OR deployed (not expired)
            # Note: Frontend checks for expired jobs and updates their status
            query = """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.expires_at, j.locked_at, j.locked_by,
                       j.db_dropped_at, j.superseded_at, j.superseded_by_job_id,
                       j.can_cancel, j.cancel_requested_at, j.custom_target, j.origin
                FROM jobs j
                WHERE (
                    j.status IN ('queued', 'running', 'canceling', 'deployed')
                )
            """

            params: list[Any] = []

            # User filter
            if user_code:
                query += " AND j.owner_user_code = %s"
                params.append(user_code)

            # Target filter
            if target:
                query += " AND j.target = %s"
                params.append(target)

            # Dbhost filter
            if dbhost:
                query += " AND j.dbhost = %s"
                params.append(dbhost)

            query += " ORDER BY j.submitted_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_job_history_v2(
        self,
        limit: int = 100,
        retention_days: int | None = None,
        user_code: str | None = None,
        target: str | None = None,
        dbhost: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """Get historical jobs (History view).

        Returns jobs that are no longer "active" databases:
        - Failed, canceled, deleted, deleting jobs
        - Complete jobs where database was dropped or superseded

        Per retention-cleanup plan: "Contains removed, failed, canceled,
        superseded jobs"

        Args:
            limit: Maximum number of jobs to return.
            retention_days: Only return jobs completed within N days.
            user_code: Filter by owner_user_code.
            target: Filter by target database name.
            dbhost: Filter by database host.
            status: Filter by specific status.

        Returns:
            List of historical jobs, newest first.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Failed/canceled/deleted/expired/complete/superseded jobs go to History
            query = """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.expires_at, j.locked_at, j.locked_by,
                       j.db_dropped_at, j.superseded_at, j.superseded_by_job_id,
                       j.can_cancel, j.cancel_requested_at, j.custom_target, j.origin
                FROM jobs j
                WHERE j.status IN ('failed', 'canceled', 'deleted', 'deleting', 'expired', 'complete', 'superseded')
            """

            params: list[Any] = []

            # Retention filter
            if retention_days is not None:
                query += (
                    " AND j.completed_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)"
                )
                params.append(retention_days)

            # User filter
            if user_code:
                query += " AND j.owner_user_code = %s"
                params.append(user_code)

            # Target filter
            if target:
                query += " AND j.target = %s"
                params.append(target)

            # Dbhost filter
            if dbhost:
                query += " AND j.dbhost = %s"
                params.append(dbhost)

            # Status filter
            if status and status in ("failed", "canceled", "deleted", "deleting", "complete"):
                query += " AND j.status = %s"
                params.append(status)

            query += " ORDER BY COALESCE(j.completed_at, j.submitted_at) DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def list_jobs(
        self,
        limit: int = 20,
        active_only: bool = False,
        user_filter: str | None = None,
        dbhost: str | None = None,
        status_filter: str | None = None,
    ) -> list[Job]:
        """List jobs with flexible filtering for Admin CLI.

        Args:
            limit: Maximum number of jobs to return.
            active_only: If True, only return queued/running jobs.
            user_filter: Filter by username or user_code (partial match).
            dbhost: Filter by target database host.
            status_filter: Filter by specific status.

        Returns:
            List of matching jobs ordered by submission time (newest first).
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            query = """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id,
                       can_cancel, cancel_requested_at,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, staging_cleaned_at,
                       custom_target, origin
                FROM jobs
                WHERE 1=1
            """
            params: list[Any] = []

            if active_only:
                query += " AND status IN ('queued', 'running')"
            elif status_filter:
                query += " AND status = %s"
                params.append(status_filter)

            if user_filter:
                query += " AND (owner_username LIKE %s OR owner_user_code LIKE %s)"
                params.extend([f"%{user_filter}%", f"%{user_filter}%"])

            if dbhost:
                query += " AND dbhost = %s"
                params.append(dbhost)

            query += " ORDER BY submitted_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def _fetch_active_job_rows(self, cursor: Any) -> list[dict[str, Any]]:
        """Fetch active jobs using view when available.

        Older coordination databases might be missing the active_jobs view,
        so we fall back to a direct jobs table query on error 1146.
        """
        if self._active_jobs_view_available:
            try:
                cursor.execute(_ACTIVE_JOBS_VIEW_QUERY)
                return cast(list[dict[str, Any]], cursor.fetchall())
            except mysql_errors.ProgrammingError as exc:
                if getattr(exc, "errno", None) == errorcode.ER_NO_SUCH_TABLE:
                    self._active_jobs_view_available = False
                    logger.warning(
                        "active_jobs view missing (errno %s); falling back to jobs table query",
                        getattr(exc, "errno", "unknown"),
                    )
                else:  # pragma: no cover - unexpected MySQL programming error
                    raise

        cursor.execute(_ACTIVE_JOBS_TABLE_QUERY)
        return cast(list[dict[str, Any]], cursor.fetchall())

    def get_jobs_by_user(self, user_id: str) -> list[Job]:
        """Get all jobs for a user.

        Returns jobs in reverse chronological order (newest first) for user
        job history queries.

        Args:
            user_id: User UUID.

        Returns:
            List of jobs ordered by submitted_at DESC.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id,
                       can_cancel, cancel_requested_at
                FROM jobs
                WHERE owner_user_id = %s
                ORDER BY submitted_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def check_target_exclusivity(self, target: str, dbhost: str) -> bool:
        """Check if target can accept new job (no active jobs).

        Verifies no jobs in 'queued' or 'running' status exist for the
        target/dbhost combination. Used by CLI before enqueueing.

        Args:
            target: Target database name.
            dbhost: Target host.

        Returns:
            True if no active jobs for target, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) as count
                FROM jobs
                WHERE target = %s AND dbhost = %s
                  AND status IN ('queued', 'running')
                """,
                (target, dbhost),
            )
            row = cursor.fetchone()
            return row[0] == 0 if row else True

    def count_active_jobs_for_user(self, user_id: str) -> int:
        """Count active jobs (queued or running) for a specific user.

        Used for per-user concurrency limit enforcement.

        Args:
            user_id: User UUID.

        Returns:
            Count of active jobs for the user.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE owner_user_id = %s AND status IN ('queued', 'running')
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def count_all_active_jobs(self) -> int:
        """Count all active jobs (queued or running) system-wide.

        Used for global concurrency limit enforcement.

        Returns:
            Total count of active jobs across all users.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE status IN ('queued', 'running')
                """
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def count_active_jobs_for_host(self, hostname: str) -> int:
        """Count active jobs (queued or running) for a specific host.

        Used for per-host active job limit enforcement at API layer.

        Args:
            hostname: Database host to count jobs for.

        Returns:
            Count of active jobs for the host.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE dbhost = %s AND status IN ('queued', 'running')
                """,
                (hostname,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def count_running_jobs_for_host(self, hostname: str) -> int:
        """Count running jobs for a specific host.

        Used for per-host running job limit enforcement at worker layer.

        Args:
            hostname: Database host to count jobs for.

        Returns:
            Count of running jobs for the host.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE dbhost = %s AND status = 'running'
                """,
                (hostname,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def count_jobs_by_host(self, hostname: str) -> int:
        """Count total jobs (all statuses) for a specific host.

        Used for admin dashboard to show total restores per host.

        Args:
            hostname: Database host to count jobs for.

        Returns:
            Total count of all jobs for the host.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE dbhost = %s
                """,
                (hostname,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def count_jobs_by_user(self, user_code: str) -> int:
        """Count total jobs (all statuses) for a specific user.

        Args:
            user_code: User code to count jobs for.

        Returns:
            Total count of all jobs for the user.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE owner_user_code = %s
                """,
                (user_code,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_user_target_databases(self, user_id: str) -> list[dict[str, str]]:
        """Get unique target databases created by a user.

        Returns distinct (target, dbhost) pairs from the user's job history.

        Args:
            user_id: User ID to look up databases for.

        Returns:
            List of dicts with 'name' (target) and 'host' (dbhost) keys.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT DISTINCT target, dbhost
                FROM jobs
                WHERE owner_user_id = %s
                ORDER BY target, dbhost
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [{"name": row["target"], "host": row["dbhost"]} for row in rows]

    def get_cleanup_candidates(
        self,
        retention_days: int = 7,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get jobs with completed staging databases eligible for cleanup.

        Returns jobs that completed more than retention_days ago and still
        have staging databases that haven't been cleaned up.

        Args:
            retention_days: Only include jobs completed before this many days ago.
            offset: Pagination offset.
            limit: Maximum rows to return.

        Returns:
            Dict with 'rows' list and 'total_count' integer.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            # Count total candidates
            cursor.execute(
                """
                SELECT COUNT(*) as cnt FROM jobs
                WHERE status IN ('completed', 'failed', 'canceled')
                  AND completed_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                  AND staging_name IS NOT NULL
                  AND staging_cleaned_at IS NULL
                """,
                (retention_days,),
            )
            count_row = cursor.fetchone()
            total_count = count_row["cnt"] if count_row else 0

            # Get paginated rows
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, target, staging_name,
                       dbhost, status, completed_at
                FROM jobs
                WHERE status IN ('completed', 'failed', 'canceled')
                  AND completed_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                  AND staging_name IS NOT NULL
                  AND staging_cleaned_at IS NULL
                ORDER BY completed_at ASC
                LIMIT %s OFFSET %s
                """,
                (retention_days, limit, offset),
            )
            rows = cursor.fetchall()
            # Convert datetime objects for JSON serialization
            for row in rows:
                if row.get("completed_at"):
                    row["completed_at"] = row["completed_at"].isoformat()
            return {"rows": rows, "total_count": total_count}

    def append_job_event(
        self, job_id: str, event_type: str, detail: str | None = None
    ) -> None:
        """Append event to job audit log.

        Records significant events during job execution for troubleshooting
        and progress tracking. Events are timestamped with microsecond precision.

        Common event types:
        - queued: Job submitted
        - running: Job started
        - failed: Job failed
        - complete: Job completed
        - staging_auto_cleanup: Orphaned staging dropped
        - download_started: S3 download initiated
        - restore_started: myloader execution started

        Args:
            job_id: UUID of job.
            event_type: Type of event.
            detail: Optional detail message or JSON payload.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                INSERT INTO job_events
                (job_id, event_type, detail, logged_at)
                VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                """,
                (job_id, event_type, detail),
            )
            conn.commit()

    def get_job_events(
        self, job_id: str, since_id: int | None = None
    ) -> list[JobEvent]:
        """Get all events for a job, optionally since a specific event ID.

        Returns events in chronological order for job history display.

        Args:
            job_id: UUID of job.
            since_id: Optional event ID to fetch events after (exclusive).

        Returns:
            List of events ordered by logged_at.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            query = """
                SELECT id, job_id, event_type, detail, logged_at
                FROM job_events
                WHERE job_id = %s
            """
            params: list[Any] = [job_id]

            if since_id is not None:
                query += " AND id > %s"
                params.append(since_id)

            query += " ORDER BY id ASC"  # Use ID for stable ordering

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job_event(row) for row in rows]

    def get_job_events_paginated(
        self,
        job_id: str,
        limit: int = 50,
        cursor: int | None = None,
        direction: str = "older",
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch paginated events for a job.

        Supports cursor-based pagination for efficient scrolling through
        large event histories. Events are returned in descending order
        (newest first) for "older" direction, ascending for "newer".

        Args:
            job_id: Job UUID.
            limit: Max events to return.
            cursor: Event ID for pagination (None = latest events).
            direction: "older" (id < cursor) or "newer" (id > cursor).

        Returns:
            Tuple of (events, total_count) where events is a list of dicts
            with keys: id, event_type, logged_at, detail.
        """
        with self.pool.connection() as conn:
            # Get total count
            count_cursor = TypedTupleCursor(conn.cursor())
            count_cursor.execute(
                "SELECT COUNT(*) FROM job_events WHERE job_id = %s",
                (job_id,),
            )
            count_row = count_cursor.fetchone()
            total_count = count_row[0] if count_row else 0

            # Build events query
            dict_cursor = TypedDictCursor(conn.cursor(dictionary=True))

            if cursor is None:
                # No cursor: get newest events
                dict_cursor.execute(
                    """
                    SELECT id, event_type, detail, logged_at
                    FROM job_events
                    WHERE job_id = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (job_id, limit),
                )
            elif direction == "newer":
                # Get events newer than cursor (id > cursor)
                dict_cursor.execute(
                    """
                    SELECT id, event_type, detail, logged_at
                    FROM job_events
                    WHERE job_id = %s AND id > %s
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (job_id, cursor, limit),
                )
            else:
                # Default: older direction (id < cursor)
                dict_cursor.execute(
                    """
                    SELECT id, event_type, detail, logged_at
                    FROM job_events
                    WHERE job_id = %s AND id < %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (job_id, cursor, limit),
                )

            rows = dict_cursor.fetchall()

            # Convert to event dicts
            # Format timestamp: use Z for UTC, handle timezone-aware datetimes
            def _format_ts(dt: datetime) -> str:
                iso = dt.isoformat()
                return iso.replace("+00:00", "Z") if iso.endswith("+00:00") else iso + "Z"

            def _parse_detail(detail: str | None) -> dict | None:
                """Parse detail as JSON, falling back to message dict for plain text."""
                if not detail:
                    return None
                # Try JSON first
                if detail.startswith('{'):
                    try:
                        return json.loads(detail)
                    except json.JSONDecodeError:
                        pass
                # Plain text - wrap in message dict for consistent structure
                return {"message": detail}

            events = [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "logged_at": _format_ts(row["logged_at"]),
                    "detail": _parse_detail(row["detail"]),
                }
                for row in rows
            ]

            return events, total_count

    def get_job_events_by_offset(
        self,
        job_id: str,
        limit: int = 50,
        offset: int = 0,
        order: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch events for a job by position offset.

        Used for scrollbar jump navigation where cursor-based pagination
        isn't possible.

        Args:
            job_id: Job UUID.
            limit: Max events to return.
            offset: Position offset (0 = first event in specified order).
            order: "desc" for newest-first, "asc" for oldest-first (chronological).

        Returns:
            Tuple of (events, total_count) where events is a list of dicts
            with keys: id, event_type, logged_at, detail.
        """
        with self.pool.connection() as conn:
            # Get total count
            count_cursor = TypedTupleCursor(conn.cursor())
            count_cursor.execute(
                "SELECT COUNT(*) FROM job_events WHERE job_id = %s",
                (job_id,),
            )
            count_row = count_cursor.fetchone()
            total_count = count_row[0] if count_row else 0

            # Get events at offset with specified order
            order_clause = "DESC" if order.lower() == "desc" else "ASC"
            dict_cursor = TypedDictCursor(conn.cursor(dictionary=True))
            dict_cursor.execute(
                f"""
                SELECT id, event_type, detail, logged_at
                FROM job_events
                WHERE job_id = %s
                ORDER BY id {order_clause}
                LIMIT %s OFFSET %s
                """,
                (job_id, limit, offset),
            )

            rows = dict_cursor.fetchall()

            # Format timestamp
            def _format_ts(dt: datetime) -> str:
                iso = dt.isoformat()
                return iso.replace("+00:00", "Z") if iso.endswith("+00:00") else iso + "Z"

            def _parse_detail(detail: str | None) -> dict | None:
                """Parse detail as JSON, falling back to message dict for plain text."""
                if not detail:
                    return None
                # Try JSON first
                if detail.startswith('{'):
                    try:
                        return json.loads(detail)
                    except json.JSONDecodeError:
                        pass
                # Plain text - wrap in message dict for consistent structure
                return {"message": detail}

            events = [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "logged_at": _format_ts(row["logged_at"]),
                    "detail": _parse_detail(row["detail"]),
                }
                for row in rows
            ]

            return events, total_count

    def prune_job_events(self, retention_days: int = 90) -> int:
        """Delete job events older than retention period.

        Pruning strategy:
        - Keep events for retention_days (default 90 days)
        - Only delete events for jobs in terminal states (completed/failed/canceled)
        - Events for running/queued jobs are never pruned

        Expected volume per job:
        - Typical job: 4-8 events (queued, running, download_*, restore_*, complete)
        - Failed job: 3-5 events (queued, running, phase events, failed)
        - With ~100 jobs/month, expect ~600-800 events/month
        - At 90-day retention: ~2000-2500 events max

        Args:
            retention_days: Days to retain events. Must be >= 0.
                Use 0 to delete all events for terminal jobs.

        Returns:
            Number of events deleted.

        Raises:
            ValueError: If retention_days < 0.
        """
        if retention_days < 0:
            raise ValueError("retention_days must be >= 0")

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            # Only prune events for terminal jobs (complete/failed/canceled)
            cursor.execute(
                """
                DELETE je FROM job_events je
                INNER JOIN jobs j ON je.job_id = j.id
                WHERE je.logged_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                  AND j.status IN ('complete', 'failed', 'canceled')
                """,
                (retention_days,),
            )
            deleted_count = int(cursor.rowcount)
            conn.commit()
            return deleted_count

    def get_prune_candidates(
        self,
        retention_days: int = 90,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Get paginated list of jobs with events that would be pruned.

        Returns dict with:
        - rows: list of job summaries with event counts
        - totalCount: total jobs affected
        - totalEvents: total events that would be deleted

        Args:
            retention_days: Days to retain events. Events older are candidates.
            offset: Pagination offset.
            limit: Maximum rows to return.

        Returns:
            Dict with rows (job summaries), totalCount, and totalEvents.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Get total counts first
            cursor.execute(
                """
                SELECT COUNT(DISTINCT je.job_id) as total_jobs,
                       COUNT(*) as total_events
                FROM job_events je
                INNER JOIN jobs j ON je.job_id = j.id
                WHERE je.logged_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                  AND j.status IN ('complete', 'failed', 'canceled')
                """,
                (retention_days,),
            )
            totals = cursor.fetchone()
            total_count = totals["total_jobs"] if totals else 0
            total_events = totals["total_events"] if totals else 0

            # Get paginated job summaries
            cursor.execute(
                """
                SELECT je.job_id,
                       j.target,
                       j.owner_user_code as user_code,
                       j.status,
                       COUNT(*) as event_count,
                       MIN(je.logged_at) as oldest_event,
                       MAX(je.logged_at) as newest_event
                FROM job_events je
                INNER JOIN jobs j ON je.job_id = j.id
                WHERE je.logged_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                  AND j.status IN ('complete', 'failed', 'canceled')
                GROUP BY je.job_id, j.target, j.owner_user_code, j.status
                ORDER BY oldest_event ASC
                LIMIT %s OFFSET %s
                """,
                (retention_days, limit, offset),
            )
            rows = cursor.fetchall()

            # Format rows for consistency with mock
            formatted_rows = []
            for row in rows:
                formatted_rows.append({
                    "job_id": row["job_id"],
                    "target": row["target"],
                    "user_code": row["user_code"],
                    "status": row["status"],
                    "event_count": row["event_count"],
                    "oldest_event": row["oldest_event"].isoformat()
                    if row["oldest_event"]
                    else None,
                    "newest_event": row["newest_event"].isoformat()
                    if row["newest_event"]
                    else None,
                })

            return {
                "rows": formatted_rows,
                "totalCount": total_count,
                "totalEvents": total_events,
            }

    def prune_job_events_by_ids(self, job_ids: list[str]) -> int:
        """Prune all events for specific job IDs. Returns count deleted.

        This removes ALL events for the specified jobs, regardless of age.
        Used by the prune-logs UI when user selects specific jobs to purge.

        Only deletes events for jobs in terminal states for safety.

        Args:
            job_ids: List of job UUIDs to delete events for.

        Returns:
            Number of events deleted.
        """
        if not job_ids:
            return 0

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            # Use parameterized IN clause
            placeholders = ", ".join(["%s"] * len(job_ids))
            cursor.execute(
                f"""
                DELETE je FROM job_events je
                INNER JOIN jobs j ON je.job_id = j.id
                WHERE je.job_id IN ({placeholders})
                  AND j.status IN ('complete', 'failed', 'canceled')
                """,
                tuple(job_ids),
            )
            deleted_count = int(cursor.rowcount)
            conn.commit()
            return deleted_count

    def prune_job_events_excluding(
        self,
        retention_days: int = 90,
        exclude_job_ids: list[str] | None = None,
    ) -> int:
        """Prune old job events, excluding specified job IDs. Returns count deleted.

        Deletes events older than retention_days for terminal jobs,
        EXCEPT for jobs in the exclude list.

        Args:
            retention_days: Days to retain events.
            exclude_job_ids: Job IDs to exclude from pruning.

        Returns:
            Number of events deleted.
        """
        exclude_job_ids = exclude_job_ids or []

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())

            if exclude_job_ids:
                # Use NOT IN with parameterized query
                placeholders = ", ".join(["%s"] * len(exclude_job_ids))
                cursor.execute(
                    f"""
                    DELETE je FROM job_events je
                    INNER JOIN jobs j ON je.job_id = j.id
                    WHERE je.logged_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                      AND j.status IN ('complete', 'failed', 'canceled')
                      AND je.job_id NOT IN ({placeholders})
                    """,
                    (retention_days, *exclude_job_ids),
                )
            else:
                # No exclusions - same as regular prune
                cursor.execute(
                    """
                    DELETE je FROM job_events je
                    INNER JOIN jobs j ON je.job_id = j.id
                    WHERE je.logged_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                      AND j.status IN ('complete', 'failed', 'canceled')
                    """,
                    (retention_days,),
                )

            deleted_count = int(cursor.rowcount)
            conn.commit()
            return deleted_count

    def find_job_by_staging_prefix(
        self, target: str, dbhost: str, job_id_prefix: str
    ) -> Job | None:
        """Find a job by its staging database prefix.

        Used by scheduled cleanup to match staging databases to jobs.

        Args:
            target: Target database name.
            dbhost: Database host.
            job_id_prefix: First 12 characters of job UUID.

        Returns:
            Job if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            # Match job ID starting with the prefix
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code,
                       target, staging_name, dbhost, status, submitted_at,
                       started_at, completed_at, options_json, retry_count,
                       error_detail, worker_id, can_cancel, cancel_requested_at
                FROM jobs
                WHERE target = %s AND dbhost = %s AND id LIKE %s
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (target, dbhost, f"{job_id_prefix}%"),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def get_job_completion_time(self, job_id: str) -> datetime | None:
        """Get the completion time of a job from events.

        Looks for the last terminal event (complete, failed, canceled).

        Args:
            job_id: Job UUID.

        Returns:
            Datetime of completion, or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT logged_at
                FROM job_events
                WHERE job_id = %s
                  AND event_type IN ('complete', 'failed', 'canceled')
                ORDER BY id DESC
                LIMIT 1
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            return row["logged_at"] if row else None

    def has_active_jobs_for_target(self, target: str, dbhost: str) -> bool:
        """Check if there are any active jobs for a target.

        Active jobs include queued, running, and canceling states.
        Jobs in 'canceling' state are still active because the worker
        is cleaning up (myloader may still be running).

        Used as a safety check before allowing new job submission and before
        scheduled cleanup drops staging databases.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            True if active jobs exist, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE target = %s AND dbhost = %s
                  AND status IN ('queued', 'running', 'canceling')
                """,
                (target, dbhost),
            )
            row = cursor.fetchone()
            return row[0] > 0 if row else False

    def get_old_terminal_jobs(self, dbhost: str, cutoff_date: datetime) -> list[Job]:
        """Get terminal jobs older than cutoff date for a specific host.

        Used by scheduled cleanup to find jobs whose staging databases
        may need cleanup.

        Args:
            dbhost: Database host to filter by.
            cutoff_date: Only return jobs completed before this date.

        Returns:
            List of Job instances in terminal state older than cutoff.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.worker_id, j.staging_cleaned_at
                FROM jobs j
                WHERE j.dbhost = %s
                  AND j.status IN ('complete', 'failed', 'canceled')
                  AND j.staging_name IS NOT NULL
                  AND j.staging_cleaned_at IS NULL
                  AND j.completed_at < %s
                ORDER BY j.completed_at ASC
                """,
                (dbhost, cutoff_date),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def mark_job_staging_cleaned(self, job_id: str) -> None:
        """Mark a job's staging database as cleaned.

        Sets staging_cleaned_at timestamp to track that cleanup was performed.
        This prevents re-processing the same job in future cleanup runs.

        Args:
            job_id: UUID of job to mark as cleaned.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET staging_cleaned_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (job_id,),
            )
            conn.commit()

    def _row_to_job(self, row: dict[str, Any]) -> Job:
        """Convert MySQL row to Job dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            Job instance with all fields populated.
        """
        # Deserialize options_json if present (MySQL connector returns JSON as string)
        options_json = row.get("options_json")
        if options_json:
            if isinstance(options_json, str):
                try:
                    parsed = json.loads(options_json)
                    if isinstance(parsed, dict):
                        options_json = parsed
                    else:
                        logger.warning(
                            "Job %s has invalid options_json type: %s",
                            row["id"],
                            type(parsed),
                        )
                        options_json = None
                except json.JSONDecodeError:
                    logger.warning(
                        "Job %s has malformed options_json: %s",
                        row["id"],
                        options_json,
                    )
                    options_json = None
            elif not isinstance(options_json, dict):
                logger.warning(
                    "Job %s has unexpected options_json type: %s",
                    row["id"],
                    type(options_json),
                )
                options_json = None

        return Job(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            owner_username=row["owner_username"],
            owner_user_code=row["owner_user_code"],
            target=row["target"],
            staging_name=row["staging_name"],
            dbhost=row["dbhost"],
            status=JobStatus(row["status"]),
            submitted_at=row["submitted_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            options_json=options_json,
            retry_count=row.get("retry_count", 0),
            error_detail=row.get("error_detail"),
            worker_id=row.get("worker_id"),
            staging_cleaned_at=row.get("staging_cleaned_at"),
            current_operation=self._derive_operation(row),
            cancel_requested_at=row.get("cancel_requested_at"),
            can_cancel=row.get("can_cancel", True),
            # Custom target tracking
            custom_target=bool(row.get("custom_target", 0)),
            # Job origin tracking (Database Discovery)
            origin=row.get("origin", "restore"),
            # Retention & lifecycle fields
            expires_at=row.get("expires_at"),
            locked_at=row.get("locked_at"),
            locked_by=row.get("locked_by"),
            db_dropped_at=row.get("db_dropped_at"),
            superseded_at=row.get("superseded_at"),
            superseded_by_job_id=row.get("superseded_by_job_id"),
        )

    def _derive_operation(self, row: dict[str, Any]) -> str | None:
        """Derive user-friendly operation string from job status and last event."""
        status = row.get("status")
        if status == "complete":
            return "Success"

        event_type = row.get("last_event_type")

        if not event_type:
            if status == "queued":
                return "Queued"
            if status == "running":
                return "Initializing"
            if status == "failed":
                return "Failed"
            return None

        if event_type == "download_progress":
            detail_json = row.get("last_event_detail")
            if detail_json:
                try:
                    detail = json.loads(detail_json)
                    downloaded = detail.get("downloaded_bytes", 0)
                    total = detail.get("total_bytes", 1)
                    if total > 0:
                        percent = int((downloaded / total) * 100)
                        return f"Downloading({percent}%)"
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass
            return "Downloading"

        if event_type == "backup_selected":
            return "Downloading"
        if event_type == "download_started":
            return "Downloading"
        if event_type == "download_failed":
            return "Downloading"
        if event_type == "download_complete":
            return "Extracting"
        if event_type == "extraction_failed":
            return "Extracting"
        if event_type == "extraction_complete":
            return "Restoring"
        if event_type == "restore_started":
            return "Restoring"
        if event_type == "restore_complete":
            return "Success"
        if event_type == "restore_failed":
            return "Restoring"

        # Fallback: convert event_type like "download_started" to "Download started"
        return str(event_type).replace("_", " ").capitalize()

    def find_orphaned_staging_databases(
        self, older_than_hours: int, dbhost: str | None = None
    ) -> list[Job]:
        """Find jobs with uncleaned staging databases.

        Args:
            older_than_hours: Minimum age of finished_at in hours.
            dbhost: Optional filter by database host.

        Returns:
            List of Job instances representing orphaned staging databases.
        """
        query = """
            SELECT
                id, owner_user_id, owner_username, owner_user_code, target,
                staging_name, dbhost, status, submitted_at, started_at,
                completed_at, options_json, retry_count,
                error_detail, staging_cleaned_at
            FROM jobs
            WHERE staging_name IS NOT NULL
              AND staging_cleaned_at IS NULL
              AND status IN ('complete', 'failed', 'canceled')
              AND completed_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """
        params: list[Any] = [older_than_hours]

        if dbhost:
            query += " AND dbhost = %s"
            params.append(dbhost)

        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def mark_staging_cleaned(self, job_id: str) -> None:
        """Mark staging database as cleaned.

        Args:
            job_id: Job ID to update.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "UPDATE jobs SET staging_cleaned_at = NOW() WHERE id = %s",
                (job_id,),
            )
            conn.commit()

    # =========================================================================
    # Database Retention & Lifecycle Methods
    # =========================================================================

    def set_job_expiration(self, job_id: str, expires_at: datetime) -> None:
        """Set expiration date for a job's database.

        Args:
            job_id: Job ID to update.
            expires_at: New expiration timestamp.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "UPDATE jobs SET expires_at = %s WHERE id = %s",
                (expires_at, job_id),
            )
            conn.commit()

    def lock_job(self, job_id: str, locked_by: str) -> bool:
        """Lock a job's database to protect from cleanup and overwrites.

        Args:
            job_id: Job ID to lock.
            locked_by: Username of user locking the database.

        Returns:
            True if lock was set, False if job not found or already locked.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs 
                SET locked_at = UTC_TIMESTAMP(6), locked_by = %s
                WHERE id = %s AND locked_at IS NULL
                """,
                (locked_by, job_id),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def unlock_job(self, job_id: str) -> bool:
        """Unlock a job's database.

        Args:
            job_id: Job ID to unlock.

        Returns:
            True if unlocked, False if job not found or wasn't locked.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs 
                SET locked_at = NULL, locked_by = NULL
                WHERE id = %s AND locked_at IS NOT NULL
                """,
                (job_id,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def lock_for_restore(self, job_id: str, worker_id: str) -> bool:
        """Lock job for restore phase, preventing further cancellation.

        This is the critical gate before myloader starts. It atomically:
        1. Verifies can_cancel=TRUE AND cancel_requested_at IS NULL
        2. Sets can_cancel=FALSE, locked_at, locked_by

        The lock prevents both service and user interruption during Loading
        through Complete. The lock is cleared by mark_job_deployed() once
        the job reaches Deployed status.

        If a cancellation was requested between the last checkpoint and this
        call, the method returns False and the job should abort cleanly.

        Args:
            job_id: UUID of the job to lock.
            worker_id: Identifier of the worker locking the job.

        Returns:
            True if lock was acquired successfully (proceed with restore).
            False if job was already canceled or cancel was requested (abort job).
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs 
                SET can_cancel = FALSE,
                    locked_at = UTC_TIMESTAMP(6),
                    locked_by = %s
                WHERE id = %s 
                  AND can_cancel = TRUE 
                  AND cancel_requested_at IS NULL
                """,
                (f"worker:{worker_id}", job_id),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def mark_db_dropped(self, job_id: str) -> None:
        """Mark that the actual database was dropped from target host.

        Args:
            job_id: Job ID to mark.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "UPDATE jobs SET db_dropped_at = UTC_TIMESTAMP(6) WHERE id = %s",
                (job_id,),
            )
            conn.commit()

    def get_deployed_jobs_for_host(self, dbhost: str) -> list[Job]:
        """Get all deployed jobs for a specific database host.

        Returns active deployed databases: not superseded, not dropped.
        Used by database discovery to determine which databases on a host
        are managed by pullDB.

        Args:
            dbhost: Database host to get deployed jobs for.

        Returns:
            List of deployed Job instances on this host.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE dbhost = %s
                  AND status = 'deployed'
                  AND superseded_at IS NULL
                  AND db_dropped_at IS NULL
                ORDER BY target ASC, submitted_at DESC
                """,
                (dbhost,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_deployed_job_for_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Get the deployed job for a target+host+user if one exists.

        Used to check if a database already exists before allowing a new restore.
        A deployed job means the database is live and in use.

        Args:
            target: Target database name.
            dbhost: Database host.
            owner_user_id: User ID who owns the job.

        Returns:
            Deployed Job if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE target = %s 
                  AND dbhost = %s 
                  AND owner_user_id = %s
                  AND status = 'deployed'
                  AND superseded_at IS NULL
                  AND db_dropped_at IS NULL
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (target, dbhost, owner_user_id),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def has_any_deployed_job_for_target(
        self, target: str, dbhost: str
    ) -> Job | None:
        """Check if ANY user has a deployed job for target+host.

        Unlike get_deployed_job_for_target() which is user-scoped, this checks
        across ALL users. Used for deletion safety - we must never drop a
        database that ANY user has deployed.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            Deployed Job if found (any user), None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE target = %s 
                  AND dbhost = %s 
                  AND status = 'deployed'
                  AND superseded_at IS NULL
                  AND db_dropped_at IS NULL
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (target, dbhost),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def get_in_progress_job_for_target(
        self, target: str, dbhost: str
    ) -> Job | None:
        """Get any in-progress (queued/running) job for target+host.

        Used by resubmit validation to prevent duplicate concurrent restores
        to the same database. Checks across ALL users.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            In-progress Job if found (any user), None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE target = %s 
                  AND dbhost = %s 
                  AND status IN ('queued', 'running', 'canceling')
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (target, dbhost),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def has_any_locked_job_for_target(
        self, target: str, dbhost: str
    ) -> Job | None:
        """Check if ANY user has a locked job for target+host.

        Used for deletion safety - we should not drop a database that
        has been explicitly locked by any user.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            Locked Job if found (any user), None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE target = %s 
                  AND dbhost = %s 
                  AND locked_at IS NOT NULL
                  AND db_dropped_at IS NULL
                ORDER BY locked_at DESC
                LIMIT 1
                """,
                (target, dbhost),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def get_latest_completed_job_for_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Get the most recent completed job for a target+host+user.

        Used for supersession - finding the job to mark as superseded when
        a new restore to the same target is submitted.

        Args:
            target: Target database name.
            dbhost: Database host.
            owner_user_id: User ID who owns the job.

        Returns:
            Most recent completed Job if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE target = %s 
                  AND dbhost = %s 
                  AND owner_user_id = %s
                  AND status = 'complete'
                  AND superseded_at IS NULL
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (target, dbhost, owner_user_id),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def supersede_job(self, job_id: str, superseded_by_job_id: str) -> None:
        """Mark a job as superseded by a newer restore to the same target.

        Sets status to 'superseded', records superseded_at timestamp,
        and sets expires_at to 7 days from now (cleanup window for the record).
        Note: Superseded jobs have no database to drop - it was replaced.

        Args:
            job_id: Job ID being superseded.
            superseded_by_job_id: Job ID of the new restore.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs 
                SET superseded_at = UTC_TIMESTAMP(6), 
                    superseded_by_job_id = %s,
                    status = 'superseded',
                    expires_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL 7 DAY),
                    db_dropped_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (superseded_by_job_id, job_id),
            )
            conn.commit()

    def get_locked_by_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Find a locked job for a specific target+host+user combination.

        Used to check if a new restore should be blocked due to existing lock.

        Args:
            target: Target database name.
            dbhost: Database host.
            owner_user_id: User ID who owns the job.

        Returns:
            Locked Job if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE target = %s 
                  AND dbhost = %s 
                  AND owner_user_id = %s
                  AND locked_at IS NOT NULL
                  AND db_dropped_at IS NULL
                  AND superseded_at IS NULL
                LIMIT 1
                """,
                (target, dbhost, owner_user_id),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def get_maintenance_items(
        self, user_id: str, notice_days: int, grace_days: int
    ) -> MaintenanceItems:
        """Get maintenance items for a user's daily modal.

        Returns jobs grouped by maintenance status: expired, expiring, locked.

        Args:
            user_id: User ID to get items for.
            notice_days: Days before expiry to show in "expiring" section.
            grace_days: Not used in query but available for reference.

        Returns:
            MaintenanceItems with expired, expiring, and locked job lists.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            # Query all potentially relevant jobs in one query
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE owner_user_id = %s
                  AND status = 'deployed'
                  AND db_dropped_at IS NULL
                  AND superseded_at IS NULL
                  AND locked_at IS NULL
                  AND expires_at < UTC_TIMESTAMP() + INTERVAL %s DAY
                ORDER BY expires_at ASC
                """,
                (user_id, notice_days),
            )
            rows = cursor.fetchall()

        expired: list[Job] = []
        expiring: list[Job] = []

        for row in rows:
            job = self._row_to_job(row)
            if job.is_expired:
                expired.append(job)
            elif job.is_expiring(notice_days):
                expiring.append(job)

        return MaintenanceItems(expired=expired, expiring=expiring, locked=[])

    def get_expired_cleanup_candidates(self, grace_days: int) -> list[Job]:
        """Get jobs eligible for automatic database cleanup.

        Returns deployed jobs that are:
        - Past expiration + grace period
        - Not locked
        - Database not already dropped
        - Not superseded

        Args:
            grace_days: Additional days after expiry before cleanup.

        Returns:
            List of jobs whose databases can be dropped.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE status IN ('deployed', 'expired')
                  AND locked_at IS NULL
                  AND db_dropped_at IS NULL
                  AND superseded_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at < UTC_TIMESTAMP() - INTERVAL %s DAY
                ORDER BY expires_at ASC
                """,
                (grace_days,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_expired_terminal_job_candidates(self, grace_days: int) -> list[Job]:
        """Get failed/canceled jobs eligible for automatic record cleanup.

        Returns terminal jobs (failed, canceled) that are:
        - Past expiration + grace period
        - Have expires_at set

        Unlike deployed jobs, these have no live database to drop — this
        query is used to find stale records for purging from History.

        Args:
            grace_days: Additional days after expiry before cleanup.

        Returns:
            List of failed/canceled jobs past their expiration + grace period.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE status IN ('failed', 'canceled')
                  AND expires_at IS NOT NULL
                  AND expires_at < UTC_TIMESTAMP() - INTERVAL %s DAY
                ORDER BY expires_at ASC
                """,
                (grace_days,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def purge_terminal_job(self, job_id: str) -> None:
        """Mark a failed/canceled job as deleted (record cleanup).

        Sets status to 'deleted' with a detail indicating automatic purge.
        This is a soft delete — the row remains for audit but leaves the
        active History view.

        Args:
            job_id: UUID of the terminal job to purge.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'deleted',
                    error_detail = CONCAT(
                        COALESCE(error_detail, ''),
                        ' [auto-purged: expired terminal job]'
                    )
                WHERE id = %s
                  AND status IN ('failed', 'canceled')
                """,
                (job_id,),
            )
            conn.commit()

    def get_all_locked_databases(self) -> list[Job]:
        """Get all locked databases across all users (manager report).

        Returns:
            List of locked jobs ordered by user, then lock date.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE locked_at IS NOT NULL
                  AND db_dropped_at IS NULL
                ORDER BY owner_username ASC, locked_at ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_user_active_databases(self, user_id: str) -> list[Job]:
        """Get all active (non-dropped, non-superseded) databases for a user.

        Used for the Active Jobs view showing databases the user owns.

        Args:
            user_id: User ID to get databases for.

        Returns:
            List of jobs representing active databases.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail,
                       worker_id, staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id, custom_target, origin
                FROM jobs
                WHERE owner_user_id = %s
                  AND status = 'complete'
                  AND db_dropped_at IS NULL
                  AND superseded_at IS NULL
                ORDER BY 
                    CASE 
                        WHEN locked_at IS NOT NULL THEN 0
                        WHEN expires_at < UTC_TIMESTAMP() + INTERVAL 7 DAY THEN 1
                        ELSE 2
                    END,
                    expires_at ASC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def _row_to_active_job(self, row: dict[str, Any]) -> Job:
        """Convert active_jobs view row to Job dataclass.

        The active_jobs view returns fewer fields than the full jobs table.
        This helper populates only available fields and leaves others as None.

        Args:
            row: Dictionary from active_jobs view query.

        Returns:
            Job instance with partial fields (view subset).
        """
        return Job(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            owner_username=row["owner_username"],
            owner_user_code=row["owner_user_code"],
            target=row["target"],
            staging_name=row.get("staging_name", ""),
            dbhost=row.get("dbhost", ""),
            status=JobStatus(row["status"]),
            submitted_at=row["submitted_at"],
            started_at=row.get("started_at"),
            completed_at=None,
            options_json=None,
            retry_count=0,
            error_detail=None,
            can_cancel=bool(row.get("can_cancel", True)),
        )

    def _row_to_job_event(self, row: dict[str, Any]) -> JobEvent:
        """Convert MySQL row to JobEvent dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            JobEvent instance with all fields populated.
        """
        return JobEvent(
            id=row["id"],
            job_id=row["job_id"],
            event_type=row["event_type"],
            detail=row.get("detail"),
            logged_at=row["logged_at"],
        )


