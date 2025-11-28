"""MySQL infrastructure for pullDB.

Implements connection pooling and repository pattern for database access.
All database operations are encapsulated in repository classes to enforce
business rules and provide clean abstractions.
"""

from __future__ import annotations

import json
import logging
import typing as t
import uuid
import warnings
from contextlib import contextmanager
from datetime import datetime

import mysql.connector
from mysql.connector import errorcode
from mysql.connector import errors as mysql_errors

from pulldb.domain.models import DBHost, Job, JobEvent, JobStatus, User
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials


logger = logging.getLogger(__name__)


_ACTIVE_JOBS_VIEW_QUERY = """
SELECT id, owner_user_id, owner_username, owner_user_code, target,
    status, submitted_at, started_at
FROM active_jobs
ORDER BY submitted_at ASC
"""

_ACTIVE_JOBS_TABLE_QUERY = """
SELECT id, owner_user_id, owner_username, owner_user_code, target,
    status, submitted_at, started_at
FROM jobs
WHERE status IN ('queued','running')
ORDER BY submitted_at ASC
"""


class MySQLPool:
    """Very small wrapper around mysql.connector.connect for early prototype.

    Will be replaced with a real pooled implementation and per-host connections.
    """

    def __init__(self, **kwargs: t.Any) -> None:
        """Initialize MySQL connection pool.

        Args:
            **kwargs: Connection parameters passed to mysql.connector.connect().
        """
        self._kwargs = kwargs

    @contextmanager
    def connection(self) -> t.Iterator[t.Any]:
        """Get a database connection from the pool.

        Yields:
            MySQL connection object.
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> t.Iterator[t.Any]:
        """Get a database connection with explicit transaction control.

        Disables autocommit for manual transaction management. Commits on
        successful exit, rolls back on exception. Used for atomic operations
        like job claiming in multi-worker environments.

        Yields:
            MySQL connection object with autocommit disabled.

        Example:
            >>> with pool.transaction() as conn:
            ...     cursor = conn.cursor()
            ...     cursor.execute("SELECT ... FOR UPDATE")
            ...     cursor.execute("UPDATE ...")
            ...     # Commits automatically on exit
        """
        conn = mysql.connector.connect(**self._kwargs)
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def build_default_pool(host: str, user: str, password: str, database: str) -> MySQLPool:
    """Build a MySQL connection pool with default configuration.

    Args:
        host: MySQL server hostname.
        user: MySQL username.
        password: MySQL password.
        database: Database name.

    Returns:
        Configured MySQLPool instance.
    """
    return MySQLPool(host=host, user=user, password=password, database=database)


class JobRepository:
    """Repository for job queue operations.

    Manages job lifecycle in MySQL coordination database. Handles job creation,
    status transitions, event logging, and queue queries. Enforces business rules
    like per-target exclusivity via database constraints.

    Example:
        >>> pool = MySQLPool(host="localhost", user="root", database="pulldb")
        >>> repo = JobRepository(pool)
        >>> job_id = repo.enqueue_job(job)
        >>> claimed = repo.claim_next_job(worker_id="worker-1:1234")
        >>> if claimed:
        ...     process(claimed)  # Job is already 'running'
    """

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
            mysql.connector.IntegrityError: If target already has active job.
        """
        job_id = job.id if job.id else str(uuid.uuid4())

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO jobs
                    (id, owner_user_id, owner_username, owner_user_code, target,
                     staging_name, dbhost, status, submitted_at, options_json,
                     retry_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), %s, %s)
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
                    ),
                )
                conn.commit()
                return job_id
            except mysql.connector.IntegrityError as e:
                if "idx_jobs_active_target" in str(e):
                    raise ValueError(
                        f"Target '{job.target}' on host '{job.dbhost}' "
                        f"already has an active job"
                    ) from e
                raise

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
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail
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

        This is the PREFERRED method for worker job acquisition. The older
        get_next_queued_job() + mark_job_running() pattern is NOT safe for
        multi-worker deployments.

        Args:
            worker_id: Optional identifier of claiming worker (for debugging).
                       Format: "hostname:pid" or similar unique identifier.

        Returns:
            Claimed job (now in 'running' status) or None if queue empty.

        Example:
            >>> job = repo.claim_next_job(worker_id="worker-1:12345")
            >>> if job:
            ...     # Job is already 'running' - safe to process
            ...     process(job)
        """
        with self.pool.transaction() as conn:
            cursor = conn.cursor(dictionary=True)

            # SELECT with FOR UPDATE SKIP LOCKED:
            # - FOR UPDATE: Locks the row until transaction commits
            # - SKIP LOCKED: If row already locked by another worker, skip it
            # This prevents blocking and ensures each job claimed by exactly one worker
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail
                FROM jobs
                WHERE status = 'queued'
                ORDER BY submitted_at ASC
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
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'running', started_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (job_id,),
            )

            # Log worker claim if worker_id provided
            if worker_id:
                logger.debug(
                    "Job claimed by worker",
                    extra={"job_id": job_id, "worker_id": worker_id},
                )

            # Transaction commits on context manager exit
            # Return job with status still showing 'queued' from SELECT
            # (status is updated in DB but our row dict has old value)
            job = self._row_to_job(row)
            # Return a new Job with updated status
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
                started_at=job.started_at,  # Will be set by DB
                completed_at=job.completed_at,
                options_json=job.options_json,
                retry_count=job.retry_count,
                error_detail=job.error_detail,
            )

    def get_job_by_id(self, job_id: str) -> Job | None:
        """Get job by ID.

        Args:
            job_id: UUID of job.

        Returns:
            Job or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

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
            cursor = conn.cursor()
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

    def mark_job_complete(self, job_id: str) -> None:
        """Mark job as complete and set completed_at timestamp.

        Called by worker when job successfully finishes. Updates status to
        'complete' and records completion time.

        Args:
            job_id: UUID of job.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'complete', completed_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (job_id,),
            )
            conn.commit()

    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail.

        Called by worker when job execution fails. Updates status to 'failed',
        records completion time, and stores error message.

        Args:
            job_id: UUID of job.
            error: Error message describing failure.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed', completed_at = UTC_TIMESTAMP(6),
                    error_detail = %s
                WHERE id = %s
                """,
                (error, job_id),
            )
            conn.commit()

    def request_cancellation(self, job_id: str) -> bool:
        """Request cancellation of a job.

        Sets cancel_requested_at timestamp to signal worker to stop processing.
        Only jobs in 'queued' or 'running' status can be canceled.

        Args:
            job_id: UUID of job to cancel.

        Returns:
            True if cancellation was requested, False if job not in cancelable state.

        Raises:
            ValueError: If job not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET cancel_requested_at = UTC_TIMESTAMP(6)
                WHERE id = %s AND status IN ('queued', 'running')
                  AND cancel_requested_at IS NULL
                """,
                (job_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_job_canceled(self, job_id: str, reason: str | None = None) -> None:
        """Mark job as canceled and set completed_at timestamp.

        Called by worker when it detects cancellation request and stops processing.
        Updates status to 'canceled' and records completion time.

        Args:
            job_id: UUID of job.
            reason: Optional reason for cancellation (stored in error_detail).
        """
        error_detail = reason or "Canceled by user request"
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'canceled', completed_at = UTC_TIMESTAMP(6),
                    error_detail = %s
                WHERE id = %s
                """,
                (error_detail, job_id),
            )
            conn.commit()

    def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job.

        Called by worker during long operations to check if it should stop.

        Args:
            job_id: UUID of job.

        Returns:
            True if cancel_requested_at is set, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT cancel_requested_at IS NOT NULL as is_requested
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            return bool(row and row[0])

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running).

        Uses active_jobs view for efficient querying. Jobs returned in
        submission order (oldest first).

        Returns:
            List of active jobs ordered by submitted_at.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            rows = self._fetch_active_job_rows(cursor)
            return [self._row_to_active_job(row) for row in rows]

    def get_recent_jobs(
        self, limit: int = 100, statuses: list[str] | None = None
    ) -> list[Job]:
        """Get recent jobs (active + completed) with operation status.

        Returns jobs ordered by submission time (newest first).
        Includes current_operation derived from latest job event.

        Args:
            limit: Maximum number of jobs to return.
            statuses: Optional list of status strings to filter by.

        Returns:
            List of jobs with populated current_operation.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)

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

            params: list[t.Any] = []
            if statuses:
                placeholders = ", ".join(["%s"] * len(statuses))
                query += f" WHERE j.status IN ({placeholders})"
                params.extend(statuses)

            query += " ORDER BY j.submitted_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

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
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail
                FROM jobs j
                WHERE j.status IN ('complete', 'failed', 'canceled')
            """

            params: list[t.Any] = []

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

    def _fetch_active_job_rows(self, cursor: t.Any) -> list[dict[str, t.Any]]:
        """Fetch active jobs using view when available.

        Older coordination databases might be missing the active_jobs view,
        so we fall back to a direct jobs table query on error 1146.
        """
        if self._active_jobs_view_available:
            try:
                cursor.execute(_ACTIVE_JOBS_VIEW_QUERY)
                return t.cast(list[dict[str, t.Any]], cursor.fetchall())
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
        return t.cast(list[dict[str, t.Any]], cursor.fetchall())

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
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail
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
            cursor = conn.cursor()
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
            cursor = conn.cursor()
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
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE status IN ('queued', 'running')
                """
            )
            row = cursor.fetchone()
            return row[0] if row else 0

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
            cursor = conn.cursor()
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
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT id, job_id, event_type, detail, logged_at
                FROM job_events
                WHERE job_id = %s
            """
            params: list[t.Any] = [job_id]

            if since_id is not None:
                query += " AND id > %s"
                params.append(since_id)

            query += " ORDER BY id ASC"  # Use ID for stable ordering

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job_event(row) for row in rows]

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
            retention_days: Days to retain events. Must be >= 1.

        Returns:
            Number of events deleted.

        Raises:
            ValueError: If retention_days < 1.
        """
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            # Only prune events for terminal jobs (completed/failed/canceled)
            cursor.execute(
                """
                DELETE je FROM job_events je
                INNER JOIN jobs j ON je.job_id = j.id
                WHERE je.logged_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                  AND j.status IN ('completed', 'failed', 'canceled')
                """,
                (retention_days,),
            )
            deleted_count = cursor.rowcount
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
            cursor = conn.cursor(dictionary=True)
            # Match job ID starting with the prefix
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code,
                       target, staging_name, dbhost, status, submitted_at,
                       started_at, completed_at, options_json, retry_count,
                       error_detail, source
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
            cursor = conn.cursor(dictionary=True)
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
        """Check if there are any active (queued/running) jobs for a target.

        Used as a safety check before scheduled cleanup drops staging databases.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            True if active jobs exist, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE target = %s AND dbhost = %s
                  AND status IN ('queued', 'running')
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
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.source
                FROM jobs j
                WHERE j.dbhost = %s
                  AND j.status IN ('completed', 'failed', 'canceled')
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
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET staging_cleaned_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (job_id,),
            )
            conn.commit()

    def _row_to_job(self, row: dict[str, t.Any]) -> Job:
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
            current_operation=self._derive_operation(row),
        )

    def _derive_operation(self, row: dict[str, t.Any]) -> str | None:
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

        return event_type.replace("_", " ").capitalize()

    def _row_to_active_job(self, row: dict[str, t.Any]) -> Job:
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
            staging_name="",  # Not in view
            dbhost="",  # Not in view
            status=JobStatus(row["status"]),
            submitted_at=row["submitted_at"],
            started_at=row.get("started_at"),
            completed_at=None,
            options_json=None,
            retry_count=0,
            error_detail=None,
        )

    def _row_to_job_event(self, row: dict[str, t.Any]) -> JobEvent:
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


class UserRepository:
    """Repository for user operations.

    Manages user creation, lookup, and user_code generation with collision
    handling. The user_code is a critical identifier used in database naming.

    Example:
        >>> repo = UserRepository(pool)
        >>> user = repo.get_or_create_user("jdoe")
        >>> print(user.user_code)  # "jdoejd" (first 6 letters)
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize UserRepository with connection pool.

        Args:
            pool: MySQL connection pool for database access.
        """
        self.pool = pool

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username.

        Args:
            username: Username to look up.

        Returns:
            User instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, created_at,
                       disabled_at
                FROM auth_users
                WHERE username = %s
                """,
                (username,),
            )
            row = cursor.fetchone()
            return self._row_to_user(row) if row else None

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by user_id.

        Args:
            user_id: User UUID to look up.

        Returns:
            User instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, created_at,
                       disabled_at
                FROM auth_users
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            return self._row_to_user(row) if row else None

    def create_user(self, username: str, user_code: str) -> User:
        """Create new user with generated UUID.

        Args:
            username: Username for new user.
            user_code: Generated user code (6 characters).

        Returns:
            Newly created User instance.

        Raises:
            ValueError: If username or user_code already exists.
        """
        user_id = str(uuid.uuid4())

        try:
            with self.pool.connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    """
                    INSERT INTO auth_users
                        (user_id, username, user_code, is_admin, created_at)
                    VALUES (%s, %s, %s, FALSE, UTC_TIMESTAMP(6))
                    """,
                    (user_id, username, user_code),
                )
                conn.commit()

                # Fetch the created user
                cursor.execute(
                    """
                    SELECT user_id, username, user_code, is_admin,
                           created_at, disabled_at
                    FROM auth_users
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError(
                        f"Failed to retrieve user after creation: {user_id}"
                    )
                return self._row_to_user(row)

        except mysql.connector.IntegrityError as e:
            if "username" in str(e):
                raise ValueError(f"Username '{username}' already exists") from e
            if "user_code" in str(e):
                raise ValueError(f"User code '{user_code}' already exists") from e
            raise

    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create new one with generated user_code.

        This method handles the complete user lifecycle:
        1. Check if user exists
        2. If not, generate unique user_code
        3. Create new user
        4. Return user (existing or new)

        Args:
            username: Username to get or create.

        Returns:
            User instance (existing or newly created).

        Raises:
            ValueError: If user_code cannot be generated or username invalid.
        """
        # Try to get existing user
        user = self.get_user_by_username(username)
        if user:
            return user

        # Generate unique user_code and create new user
        user_code = self.generate_user_code(username)
        return self.create_user(username, user_code)

    def generate_user_code(self, username: str) -> str:
        """Generate unique 6-character user code from username.

        Algorithm:
        1. Extract first 6 alphabetic characters (lowercase, letters only)
        2. Check if code is unique in database
        3. If collision, replace 6th char with next unused letter from username
        4. If still collision, try 5th char, then 4th char (max 3 adjustments)
        5. Fail if unique code cannot be generated

        Examples:
            "jdoe" → ValueError (< 6 letters)
            "johndoe" → "johndo"
            "johndoe" (collision) → "johned" (try 6th position)
            "johndoe" (collision) → "johnoe" (try 5th position)
            "johndoe" (collision) → "johode" (try 4th position)

        Args:
            username: Username to generate code from.

        Returns:
            Unique 6-character code (lowercase letters only).

        Raises:
            ValueError: If unique code cannot be generated or username has
                < 6 letters.
        """
        user_letters_required = 6  # Magic number constant for user_code length
        # Step 1: Extract letters only, lowercase
        letters = [c.lower() for c in username if c.isalpha()]

        if len(letters) < user_letters_required:
            raise ValueError(
                f"Username '{username}' has insufficient letters "
                f"(need {user_letters_required}+, found {len(letters)})"
            )

        # Step 2: Try first 6 letters
        base_code = "".join(letters[:6])
        if not self.check_user_code_exists(base_code):
            return base_code

        # Step 3: Collision handling - try positions 5, 4, 3 (max 3 adjustments)
        # Positions tried for collision resolution (6th, then 5th, then 4th char)
        for position in [5, 4, 3]:
            # Get unused letters after position
            used_letters = set(base_code[: position + 1])
            available = [c for c in letters[position + 1 :] if c not in used_letters]

            for replacement in available:
                candidate = (
                    base_code[:position] + replacement + base_code[position + 1 :]
                )
                if not self.check_user_code_exists(candidate):
                    return candidate

        # Step 4: All collision strategies exhausted
        raise ValueError(
            f"Cannot generate unique user_code for '{username}' "
            "(collision limit exceeded after 3 adjustments)"
        )

    def check_user_code_exists(self, user_code: str) -> bool:
        """Check if user_code already exists in database.

        Args:
            user_code: 6-character code to check.

        Returns:
            True if code exists, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM auth_users WHERE user_code = %s",
                (user_code,),
            )
            result = cursor.fetchone()
            if result is None:
                return False
            count: int = result[0]
            return count > 0

    def _row_to_user(self, row: dict[str, t.Any]) -> User:
        """Convert database row to User dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            User instance with all fields populated.
        """
        return User(
            user_id=row["user_id"],
            username=row["username"],
            user_code=row["user_code"],
            is_admin=bool(row["is_admin"]),
            created_at=row["created_at"],
            disabled_at=row.get("disabled_at"),
        )


class HostRepository:
    """Repository for database host operations.

    Manages host configuration and credential resolution for target MySQL
    servers. Integrates with AWS Secrets Manager for secure credential
    storage.

    Example:
        >>> resolver = CredentialResolver()
        >>> repo = HostRepository(pool, resolver)
        >>> host = repo.get_host_by_hostname("localhost")
        >>> creds = repo.get_host_credentials("localhost")
        >>> # username is empty - caller sets it per-service
        >>> # via PULLDB_API_MYSQL_USER or PULLDB_WORKER_MYSQL_USER
        >>> print(creds.host)  # From Secrets Manager
    """

    def __init__(
        self, pool: MySQLPool, credential_resolver: CredentialResolver
    ) -> None:
        """Initialize HostRepository with pool and credential resolver.

        Args:
            pool: MySQL connection pool for coordination database access.
            credential_resolver: Resolver for AWS credential references.
        """
        self.pool = pool
        self.credential_resolver = credential_resolver

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        """Get host configuration by hostname.

        Args:
            hostname: Hostname to look up (e.g., "localhost").

        Returns:
            DBHost instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, credential_ref, max_concurrent_restores,
                       enabled, created_at
                FROM db_hosts
                WHERE hostname = %s
                """,
                (hostname,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled database hosts.

        Returns:
            List of enabled DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, credential_ref, max_concurrent_restores,
                       enabled, created_at
                FROM db_hosts
                WHERE enabled = TRUE
                ORDER BY hostname ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

    def get_host_credentials(self, hostname: str) -> MySQLCredentials:
        """Get resolved MySQL credentials for host.

        Looks up the host configuration, then resolves its credential_ref
        using the CredentialResolver (AWS Secrets Manager or SSM).

        Args:
            hostname: Hostname to get credentials for.

        Returns:
            Resolved MySQLCredentials instance.

        Raises:
            ValueError: If host not found or disabled.
            CredentialResolutionError: If credentials cannot be resolved
                from AWS Secrets Manager or SSM Parameter Store.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")
        if not host.enabled:
            raise ValueError(f"Host '{hostname}' is disabled")

        # Delegate to CredentialResolver (from Milestone 1.4)
        return self.credential_resolver.resolve(host.credential_ref)

    def check_host_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for new restore job.

        Compares count of running jobs against max_concurrent_restores limit.

        Args:
            hostname: Hostname to check capacity for.

        Returns:
            True if host has capacity (running < max), False otherwise.

        Raises:
            ValueError: If host not found.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE dbhost = %s AND status = 'running'
                """,
                (hostname,),
            )
            result = cursor.fetchone()
            if result is None:
                running_count: int = 0
            else:
                running_count = result[0]

            return running_count < host.max_concurrent_restores

    def _row_to_dbhost(self, row: dict[str, t.Any]) -> DBHost:
        """Convert database row to DBHost dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            DBHost instance with all fields populated.
        """
        return DBHost(
            id=row["id"],
            hostname=row["hostname"],
            credential_ref=row["credential_ref"],
            max_concurrent_restores=row["max_concurrent_restores"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )


class SettingsRepository:
    """Repository for settings operations.

    Manages configuration settings stored in the database. Settings supplement
    environment variables and provide runtime configuration that can be updated
    without redeployment.

    Example:
        >>> repo = SettingsRepository(pool)
        >>> default_host = repo.get_setting("default_dbhost")
        >>> print(default_host)  # "localhost"
        >>> all_settings = repo.get_all_settings()
        >>> print(all_settings["s3_bucket_path"])
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize SettingsRepository with connection pool.

        Args:
            pool: MySQL connection pool for coordination database access.
        """
        self.pool = pool

    def get_setting(self, key: str) -> str | None:
        """Get setting value by key.

        Args:
            key: Setting key to look up.

        Returns:
            Setting value if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT setting_value
                FROM settings
                WHERE setting_key = %s
                """,
                (key,),
            )
            row = cursor.fetchone()
            return row["setting_value"] if row else None

    def get_setting_required(self, key: str) -> str:
        """Get required setting value.

        Args:
            key: Setting key to look up.

        Returns:
            Setting value.

        Raises:
            ValueError: If setting not found.
        """
        value = self.get_setting(key)
        if value is None:
            raise ValueError(f"Required setting '{key}' not found")
        return value

    def get_max_active_jobs_per_user(self) -> int:
        """Get maximum active jobs allowed per user.

        Returns:
            Maximum concurrent active jobs per user. 0 means unlimited.
        """
        value = self.get_setting("max_active_jobs_per_user")
        if value is None:
            return 0  # Default: unlimited
        try:
            return int(value)
        except ValueError:
            return 0  # Default: unlimited if setting is invalid

    def get_max_active_jobs_global(self) -> int:
        """Get maximum active jobs allowed system-wide.

        Returns:
            Maximum concurrent active jobs globally. 0 means unlimited.
        """
        value = self.get_setting("max_active_jobs_global")
        if value is None:
            return 0  # Default: unlimited
        try:
            return int(value)
        except ValueError:
            return 0  # Default: unlimited if setting is invalid

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Set setting value (INSERT or UPDATE).

        Uses INSERT ... ON DUPLICATE KEY UPDATE to handle both new settings
        and updates to existing settings in a single operation.

        Args:
            key: Setting key.
            value: Setting value.
            description: Optional description of setting purpose.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            if description is not None:
                cursor.execute(
                    """
                    INSERT INTO settings
                        (setting_key, setting_value, description, updated_at)
                    VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        description = VALUES(description),
                        updated_at = UTC_TIMESTAMP(6)
                    """,
                    (key, value, description),
                )
            else:
                # Don't update description if not provided
                cursor.execute(
                    """
                    INSERT INTO settings
                        (setting_key, setting_value, updated_at)
                    VALUES (%s, %s, UTC_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        updated_at = UTC_TIMESTAMP(6)
                    """,
                    (key, value),
                )
            conn.commit()

    def get_all_settings(self) -> dict[str, str]:
        """Get all settings as dictionary.

        Returns:
            Dictionary mapping setting keys to values.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT setting_key, setting_value
                FROM settings
                ORDER BY setting_key ASC
                """
            )
            rows = cursor.fetchall()
            return {row["setting_key"]: row["setting_value"] for row in rows}

    def delete_setting(self, key: str) -> bool:
        """Delete a setting from the database.

        Args:
            key: Setting key to delete.

        Returns:
            True if setting was deleted, False if it didn't exist.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM settings
                WHERE setting_key = %s
                """,
                (key,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_all_settings_with_metadata(self) -> list[dict[str, str | None]]:
        """Get all settings with their metadata (description, updated_at).

        Returns:
            List of dicts with keys: setting_key, setting_value, description, updated_at
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT setting_key, setting_value, description, updated_at
                FROM settings
                ORDER BY setting_key ASC
                """
            )
            return list(cursor.fetchall())
