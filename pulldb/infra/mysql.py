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
from datetime import UTC, datetime

import mysql.connector
from mysql.connector import errorcode
from mysql.connector import errors as mysql_errors

from pulldb.domain.models import (
    AdminTask,
    AdminTaskStatus,
    AdminTaskType,
    DBHost,
    Job,
    JobEvent,
    JobStatus,
    User,
    UserDetail,
    UserRole,
    UserSummary,
)
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials


logger = logging.getLogger(__name__)


_ACTIVE_JOBS_VIEW_QUERY = """
SELECT id, owner_user_id, owner_username, owner_user_code, target,
    staging_name, dbhost, status, submitted_at, started_at
FROM active_jobs
ORDER BY submitted_at ASC
"""

_ACTIVE_JOBS_TABLE_QUERY = """
SELECT id, owner_user_id, owner_username, owner_user_code, target,
    staging_name, dbhost, status, submitted_at, started_at
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
                # Emit queued event as first lifecycle event
                self.append_job_event(job_id, "queued", "Job submitted")
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
                       completed_at, options_json, retry_count, error_detail, worker_id
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
        with self.pool.transaction() as conn:
            cursor = conn.cursor(dictionary=True)

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
                       j.completed_at, j.options_json, j.retry_count, j.error_detail, j.worker_id
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
                       completed_at, options_json, retry_count, error_detail, worker_id
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
            cursor = conn.cursor(dictionary=True)
            # Use LIKE for prefix matching - escape any special characters
            safe_prefix = prefix.replace("%", r"\%").replace("_", r"\_")
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id
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
            cursor = conn.cursor(dictionary=True)
            # Escape special SQL LIKE characters
            safe_query = query.replace("%", r"\%").replace("_", r"\_")

            if exact:
                # Exact match on any searchable field
                cursor.execute(
                    """
                    SELECT id, owner_user_id, owner_username, owner_user_code, target,
                           staging_name, dbhost, status, submitted_at, started_at,
                           completed_at, options_json, retry_count, error_detail, worker_id
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
                           completed_at, options_json, retry_count, error_detail, worker_id
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
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id
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

        Note:
            The worker_id column is intentionally retained after completion
            for debugging purposes (to identify which worker processed the job).

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
        records completion time, stores error message, and clears any pending
        cancellation request.

        Note:
            The worker_id column is intentionally retained after failure
            for debugging purposes (to identify which worker processed the job).
            The cancel_requested_at is cleared since the job has reached a
            terminal state and the cancellation is no longer relevant.

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
                    error_detail = %s, cancel_requested_at = NULL
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

    def get_cancel_requested_at(self, job_id: str) -> datetime | None:
        """Get the timestamp when cancellation was requested for a job.

        Used by web UI to show when a cancellation was requested.

        Args:
            job_id: UUID of job.

        Returns:
            Datetime when cancellation was requested, or None if not requested.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT cancel_requested_at FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
            return row["cancel_requested_at"] if row else None

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
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code,
                       target, staging_name, dbhost, status, submitted_at,
                       started_at, completed_at, options_json, retry_count,
                       error_detail, worker_id
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
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id
                FROM jobs
                WHERE 1=1
            """
            params: list[t.Any] = []

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
                       completed_at, options_json, retry_count, error_detail, worker_id
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

    def count_active_jobs_for_host(self, hostname: str) -> int:
        """Count active jobs (queued or running) for a specific host.

        Used for per-host active job limit enforcement at API layer.

        Args:
            hostname: Database host to count jobs for.

        Returns:
            Count of active jobs for the host.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
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
            cursor = conn.cursor()
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
            cursor = conn.cursor()
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
            cursor = conn.cursor()
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
            cursor = conn.cursor(dictionary=True)
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
    ) -> dict[str, t.Any]:
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
            cursor = conn.cursor(dictionary=True)
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
            cursor = conn.cursor()
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
            deleted_count = cursor.rowcount
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
            cursor = conn.cursor(dictionary=True)

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
            cursor = conn.cursor()
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
            deleted_count = cursor.rowcount
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
            cursor = conn.cursor()

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
                       error_detail, worker_id
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
            worker_id=row.get("worker_id"),
            staging_cleaned_at=row.get("staging_cleaned_at"),
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
                completed_at, finished_at, options_json, retry_count,
                error_detail, staging_cleaned_at
            FROM jobs
            WHERE staging_name IS NOT NULL
              AND staging_cleaned_at IS NULL
              AND status IN ('complete', 'failed', 'canceled')
              AND finished_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """
        params: list[t.Any] = [older_than_hours]

        if dbhost:
            query += " AND dbhost = %s"
            params.append(dbhost)

        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def mark_staging_cleaned(self, job_id: str) -> None:
        """Mark staging database as cleaned.

        Args:
            job_id: Job ID to update.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE jobs SET staging_cleaned_at = NOW() WHERE id = %s",
                (job_id,),
            )
            conn.commit()

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
            staging_name=row.get("staging_name", ""),
            dbhost=row.get("dbhost", ""),
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
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, max_active_jobs
                FROM auth_users
                WHERE username = %s
                """,
                (username,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Fetch allowed hosts and default host from user_hosts table
            user_id = row["user_id"]
            cursor.execute(
                """
                SELECT h.hostname, h.host_alias, uh.is_default
                FROM user_hosts uh
                JOIN db_hosts h ON h.id = uh.host_id
                WHERE uh.user_id = %s
                ORDER BY uh.is_default DESC, h.hostname ASC
                """,
                (user_id,),
            )
            host_rows = cursor.fetchall()

            allowed_hosts: list[str] = []
            default_host: str | None = None
            for hr in host_rows:
                # allowed_hosts stores canonical hostnames for authorization checks
                allowed_hosts.append(hr["hostname"])
                if hr["is_default"]:
                    # default_host stores canonical hostname for consistency
                    default_host = hr["hostname"]

            row["allowed_hosts"] = allowed_hosts if allowed_hosts else None
            row["default_host"] = default_host

            return self._row_to_user(row)

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
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, max_active_jobs
                FROM auth_users
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Fetch allowed hosts and default host from user_hosts table
            cursor.execute(
                """
                SELECT h.hostname, h.host_alias, uh.is_default
                FROM user_hosts uh
                JOIN db_hosts h ON h.id = uh.host_id
                WHERE uh.user_id = %s
                ORDER BY uh.is_default DESC, h.hostname ASC
                """,
                (user_id,),
            )
            host_rows = cursor.fetchall()

            allowed_hosts: list[str] = []
            default_host: str | None = None
            for hr in host_rows:
                # allowed_hosts stores canonical hostnames for authorization checks
                allowed_hosts.append(hr["hostname"])
                if hr["is_default"]:
                    # default_host stores canonical hostname for consistency
                    default_host = hr["hostname"]

            row["allowed_hosts"] = allowed_hosts if allowed_hosts else None
            row["default_host"] = default_host

            return self._row_to_user(row)

    def list_users(self) -> list[User]:
        """Get all users.

        Returns:
            List of User instances.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, max_active_jobs
                FROM auth_users
                ORDER BY username
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_user(row) for row in rows]

    def create_user(self, username: str, user_code: str, manager_id: str | None = None) -> User:
        """Create new user with generated UUID.

        Args:
            username: Username for new user.
            user_code: Generated user code (6 characters).
            manager_id: Optional user_id of the manager who manages this user.

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
                        (user_id, username, user_code, is_admin, role, created_at, manager_id)
                    VALUES (%s, %s, %s, FALSE, 'user', UTC_TIMESTAMP(6), %s)
                    """,
                    (user_id, username, user_code, manager_id),
                )
                conn.commit()

                # Fetch the created user
                cursor.execute(
                    """
                    SELECT user_id, username, user_code, is_admin, role,
                           created_at, disabled_at, manager_id
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

    def create_user_with_code(self, username: str) -> User:
        """Create new user with auto-generated user_code.

        Unlike get_or_create_user, this method does NOT check for existing users.
        It always attempts to create a new user. Use this for explicit registration
        where you've already verified the user doesn't exist.

        Args:
            username: Username for the new user.

        Returns:
            Newly created User instance.

        Raises:
            ValueError: If user_code cannot be generated, username invalid,
                or user already exists.
        """
        user_code = self.generate_user_code(username)
        return self.create_user(username, user_code)

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

    def get_users_with_job_counts(self) -> list[UserSummary]:
        """Get users with active job counts.

        Returns:
            List of UserSummary instances.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    u.user_id, u.username, u.user_code, u.is_admin, u.role,
                    u.created_at, u.disabled_at, u.manager_id,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_user_id = u.user_id AND j.status IN ('queued', 'running')) as active_jobs
                FROM auth_users u
                ORDER BY u.username
                """
            )
            rows = cursor.fetchall()
            
            summaries = []
            for row in rows:
                user = self._row_to_user(row)
                summaries.append(UserSummary(user=user, active_jobs_count=row["active_jobs"]))
            return summaries

    def enable_user(self, username: str) -> None:
        """Enable a user.

        Args:
            username: Username to enable.

        Raises:
            ValueError: If user not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE auth_users SET disabled_at = NULL WHERE username = %s",
                (username,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {username}")

    def disable_user(self, username: str) -> None:
        """Disable a user.

        Args:
            username: Username to disable.

        Raises:
            ValueError: If user not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE auth_users SET disabled_at = UTC_TIMESTAMP(6) WHERE username = %s",
                (username,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {username}")

    def enable_user_by_id(self, user_id: str) -> None:
        """Enable a user by user_id.

        Args:
            user_id: User UUID to enable.

        Raises:
            ValueError: If user not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE auth_users SET disabled_at = NULL WHERE user_id = %s",
                (user_id,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {user_id}")

    def disable_user_by_id(self, user_id: str) -> None:
        """Disable a user by user_id.

        Args:
            user_id: User UUID to disable.

        Raises:
            ValueError: If user not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE auth_users SET disabled_at = UTC_TIMESTAMP(6) WHERE user_id = %s",
                (user_id,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {user_id}")

    def get_user_detail(self, username: str) -> UserDetail | None:
        """Get detailed user statistics.

        Args:
            username: Username to look up.

        Returns:
            UserDetail instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    u.user_id, u.username, u.user_code, u.is_admin, u.role,
                    u.created_at, u.disabled_at, u.manager_id,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_user_id = u.user_id) as total_jobs,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_user_id = u.user_id AND j.status = 'complete') as complete_jobs,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_user_id = u.user_id AND j.status = 'failed') as failed_jobs,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_user_id = u.user_id AND j.status IN ('queued', 'running')) as active_jobs
                FROM auth_users u
                WHERE u.username = %s
                """,
                (username,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            user = self._row_to_user(row)
            return UserDetail(
                user=user,
                total_jobs=row["total_jobs"],
                complete_jobs=row["complete_jobs"],
                failed_jobs=row["failed_jobs"],
                active_jobs=row["active_jobs"],
            )

    def _row_to_user(self, row: dict[str, t.Any]) -> User:
        """Convert database row to User dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            User instance with all fields populated.
        """
        # Handle role field with backward compatibility
        # If role column doesn't exist yet (pre-migration), derive from is_admin
        role_value = row.get("role")
        if role_value:
            role = UserRole(role_value)
        elif row.get("is_admin"):
            role = UserRole.ADMIN
        else:
            role = UserRole.USER

        return User(
            user_id=row["user_id"],
            username=row["username"],
            user_code=row["user_code"],
            is_admin=bool(row["is_admin"]),
            role=role,
            created_at=row["created_at"],
            manager_id=row.get("manager_id"),
            disabled_at=row.get("disabled_at"),
            max_active_jobs=row.get("max_active_jobs"),
            allowed_hosts=row.get("allowed_hosts"),
            default_host=row.get("default_host"),
        )

    def get_users_managed_by(self, manager_id: str) -> list[User]:
        """Get all users managed by a specific manager.

        Args:
            manager_id: User ID of the manager.

        Returns:
            List of User instances managed by this manager.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id
                FROM auth_users
                WHERE manager_id = %s
                ORDER BY username
                """,
                (manager_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_user(row) for row in rows]

    def set_user_manager(self, user_id: str, manager_id: str | None) -> None:
        """Set or remove the manager for a user.

        Args:
            user_id: User ID of the user to update.
            manager_id: User ID of the new manager, or None to remove.

        Raises:
            ValueError: If user not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE auth_users SET manager_id = %s WHERE user_id = %s",
                (manager_id, user_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {user_id}")

    def update_user_role(self, user_id: str, role: UserRole) -> None:
        """Update a user's role.

        Args:
            user_id: User ID to update.
            role: New role for the user.

        Raises:
            ValueError: If user not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE auth_users SET role = %s, is_admin = %s WHERE user_id = %s",
                (role.value, role == UserRole.ADMIN, user_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {user_id}")

    def update_user_max_active_jobs(self, user_id: str, max_active_jobs: int | None) -> None:
        """Update a user's max active jobs limit.

        Args:
            user_id: User ID to update.
            max_active_jobs: New limit (None=system default, 0=unlimited, N>0=specific limit).

        Raises:
            ValueError: If user not found or limit invalid.
        """
        if max_active_jobs is not None and max_active_jobs < 0:
            raise ValueError("max_active_jobs cannot be negative")

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE auth_users SET max_active_jobs = %s WHERE user_id = %s",
                (max_active_jobs, user_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {user_id}")

    def search_users(self, query: str, limit: int = 15) -> list[User]:
        """Search for users by username, user_code, or role.

        Searches for partial matches in username and user_code.
        Used by searchable dropdown components.

        Args:
            query: Search string (minimum 3 characters recommended).
            limit: Maximum number of results to return.

        Returns:
            List of matching User instances, ordered by username.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            search_pattern = f"%{query}%"
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id
                FROM auth_users
                WHERE (username LIKE %s OR user_code LIKE %s)
                AND disabled_at IS NULL
                ORDER BY
                    CASE WHEN username LIKE %s THEN 0 ELSE 1 END,
                    username
                LIMIT %s
                """,
                (search_pattern, search_pattern, f"{query}%", limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_user(row) for row in rows]

    # =========================================================================
    # User Deletion (Admin only)
    # =========================================================================

    def delete_user(self, user_id: str) -> dict[str, int]:
        """Delete a user and all related records.

        Deletes the user and handles related data:
        - sessions, auth_credentials, user_hosts: Deleted via CASCADE
        - manager relationships: Sets manager_id to NULL for managed users
        - audit_logs: Preserved (no FK constraint by design)

        IMPORTANT: Users with ANY jobs (active or historical) cannot be deleted.
        This preserves job history integrity. Use disable_user() instead for
        users with job history.

        Args:
            user_id: User UUID to delete.

        Returns:
            Dict with counts of affected records.

        Raises:
            ValueError: If user not found or has any jobs.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            
            # Step 1: Verify user exists
            cursor.execute(
                "SELECT username FROM auth_users WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"User not found: {user_id}")
            
            # Step 2: Check for ANY jobs (cannot delete user with job history)
            cursor.execute(
                "SELECT COUNT(*) FROM jobs WHERE owner_user_id = %s",
                (user_id,),
            )
            job_count = cursor.fetchone()[0]
            if job_count > 0:
                raise ValueError(
                    f"Cannot delete user with {job_count} job(s) in history. "
                    "Use 'disable user' instead to preserve job history."
                )
            
            # Step 3: Clear manager_id for users managed by this user
            cursor.execute(
                "UPDATE auth_users SET manager_id = NULL WHERE manager_id = %s",
                (user_id,),
            )
            managed_users_updated = cursor.rowcount
            
            # Step 4: Delete user (cascades to sessions, credentials, user_hosts)
            cursor.execute(
                "DELETE FROM auth_users WHERE user_id = %s",
                (user_id,),
            )
            
            conn.commit()
            
            return {
                "managed_users_updated": managed_users_updated,
                "user_deleted": 1,
            }

    # =========================================================================
    # Bulk Operations (Admin only)
    # =========================================================================

    def bulk_disable_users(self, user_ids: list[str]) -> int:
        """Disable multiple users at once.

        Args:
            user_ids: List of user IDs to disable.

        Returns:
            Number of users actually disabled.
        """
        if not user_ids:
            return 0
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            placeholders = ", ".join(["%s"] * len(user_ids))
            cursor.execute(
                f"""
                UPDATE auth_users
                SET disabled_at = UTC_TIMESTAMP(6)
                WHERE user_id IN ({placeholders})
                AND disabled_at IS NULL
                """,
                tuple(user_ids),
            )
            conn.commit()
            return int(cursor.rowcount)

    def bulk_enable_users(self, user_ids: list[str]) -> int:
        """Enable multiple users at once.

        Args:
            user_ids: List of user IDs to enable.

        Returns:
            Number of users actually enabled.
        """
        if not user_ids:
            return 0
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            placeholders = ", ".join(["%s"] * len(user_ids))
            cursor.execute(
                f"""
                UPDATE auth_users
                SET disabled_at = NULL
                WHERE user_id IN ({placeholders})
                AND disabled_at IS NOT NULL
                """,
                tuple(user_ids),
            )
            conn.commit()
            return int(cursor.rowcount)

    def bulk_reassign_users(self, user_ids: list[str], new_manager_id: str | None) -> int:
        """Reassign multiple users to a new manager.

        Args:
            user_ids: List of user IDs to reassign.
            new_manager_id: User ID of the new manager, or None for unmanaged.

        Returns:
            Number of users actually reassigned.
        """
        if not user_ids:
            return 0
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            placeholders = ", ".join(["%s"] * len(user_ids))
            cursor.execute(
                f"""
                UPDATE auth_users
                SET manager_id = %s
                WHERE user_id IN ({placeholders})
                """,
                (new_manager_id, *user_ids),
            )
            conn.commit()
            return int(cursor.rowcount)

    def get_all_managers(self) -> list[User]:
        """Get all users with manager or admin role.

        Returns:
            List of users who can manage other users.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id
                FROM auth_users
                WHERE role IN ('manager', 'admin')
                AND disabled_at IS NULL
                ORDER BY username
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_user(row) for row in rows]


class AuditRepository:
    """Repository for audit log operations.

    Records manager/admin actions for transparency and compliance.
    All users can view audit logs.
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize audit repository.

        Args:
            pool: MySQL connection pool.
        """
        self.pool = pool

    def log_action(
        self,
        actor_user_id: str,
        action: str,
        target_user_id: str | None = None,
        detail: str | None = None,
        context: dict[str, t.Any] | None = None,
    ) -> str:
        """Record an audit log entry.

        Args:
            actor_user_id: User ID of who performed the action.
            action: Action type (e.g., 'submit_for_user', 'create_user', 'cancel_job').
            target_user_id: User ID of the user affected (if applicable).
            detail: Human-readable detail of the action.
            context: Additional JSON context data.

        Returns:
            Audit log ID.
        """
        import json

        audit_id = str(uuid.uuid4())
        context_json = json.dumps(context) if context else None

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO audit_logs
                    (audit_id, actor_user_id, target_user_id, action, detail, context_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
                """,
                (audit_id, actor_user_id, target_user_id, action, detail, context_json),
            )
            conn.commit()
        return audit_id

    def get_audit_logs(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, t.Any]]:
        """Retrieve audit log entries with optional filtering.

        Args:
            actor_user_id: Filter by actor (who did the action).
            target_user_id: Filter by target user (who was affected).
            action: Filter by action type.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of audit log dictionaries with user details.
        """
        import json

        conditions = []
        params: list[t.Any] = []

        if actor_user_id:
            conditions.append("a.actor_user_id = %s")
            params.append(actor_user_id)
        if target_user_id:
            conditions.append("a.target_user_id = %s")
            params.append(target_user_id)
        if action:
            conditions.append("a.action = %s")
            params.append(action)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT 
                    a.audit_id, a.actor_user_id, a.target_user_id, a.action,
                    a.detail, a.context_json, a.created_at,
                    actor.username as actor_username,
                    target.username as target_username
                FROM audit_logs a
                LEFT JOIN auth_users actor ON a.actor_user_id = actor.user_id
                LEFT JOIN auth_users target ON a.target_user_id = target.user_id
                WHERE {where_clause}
                ORDER BY a.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cursor.fetchall()

            # Parse context_json for each row
            results = []
            for row in rows:
                result = dict(row)
                if result.get("context_json"):
                    result["context"] = json.loads(result["context_json"])
                else:
                    result["context"] = {}
                del result["context_json"]
                results.append(result)
            return results

    def get_audit_logs_count(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
    ) -> int:
        """Count audit log entries with optional filtering.

        Args:
            actor_user_id: Filter by actor (who did the action).
            target_user_id: Filter by target user (who was affected).
            action: Filter by action type.

        Returns:
            Count of matching audit log entries.
        """
        conditions = []
        params: list[t.Any] = []

        if actor_user_id:
            conditions.append("actor_user_id = %s")
            params.append(actor_user_id)
        if target_user_id:
            conditions.append("target_user_id = %s")
            params.append(target_user_id)
        if action:
            conditions.append("action = %s")
            params.append(action)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM audit_logs WHERE {where_clause}",
                params,
            )
            result = cursor.fetchone()
            return int(result[0]) if result else 0


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
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE hostname = %s
                """,
                (hostname,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def get_host_by_id(self, host_id: str) -> DBHost | None:
        """Get host configuration by ID.

        Args:
            host_id: UUID string of the host.

        Returns:
            DBHost instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE id = %s
                """,
                (host_id,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def get_host_by_alias(self, alias: str) -> DBHost | None:
        """Get host configuration by alias.

        Args:
            alias: Host alias to look up (e.g., "dev-db-01").

        Returns:
            DBHost instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE host_alias = %s
                """,
                (alias,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def resolve_hostname(self, name: str) -> str | None:
        """Resolve a hostname or alias to the canonical hostname.

        Looks up by hostname first, then by alias if not found.
        This allows users to use short aliases like "dev-db-01" instead
        of full FQDNs like "dev-db-01.example.com".

        Args:
            name: Hostname or alias to resolve.

        Returns:
            Canonical hostname if found, None otherwise.
        """
        # Try exact hostname match first
        host = self.get_host_by_hostname(name)
        if host:
            return host.hostname

        # Try alias match
        host = self.get_host_by_alias(name)
        if host:
            return host.hostname

        return None

    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled database hosts.

        Returns:
            List of enabled DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE enabled = TRUE
                ORDER BY hostname ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

    def get_all_hosts(self) -> list[DBHost]:
        """Get all database hosts.

        Returns:
            List of DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                ORDER BY hostname ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

    def list_hosts(self) -> list[DBHost]:
        """Get all hosts (alias for get_all_hosts).

        Provided for API consistency with SimulatedHostRepository.

        Returns:
            List of all DBHost instances.
        """
        return self.get_all_hosts()

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

    def check_host_running_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for running jobs (worker enforcement).

        Compares count of running jobs against max_running_jobs limit.

        Args:
            hostname: Hostname to check capacity for.

        Returns:
            True if host has capacity (running < max_running_jobs), False otherwise.

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

            return running_count < host.max_running_jobs

    def check_host_active_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for active jobs (API enforcement).

        Compares count of active jobs (queued + running) against max_active_jobs limit.

        Args:
            hostname: Hostname to check capacity for.

        Returns:
            True if host has capacity (active < max_active_jobs), False otherwise.

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
                WHERE dbhost = %s AND status IN ('queued', 'running')
                """,
                (hostname,),
            )
            result = cursor.fetchone()
            if result is None:
                active_count: int = 0
            else:
                active_count = result[0]

            return active_count < host.max_active_jobs

    def update_host_limits(
        self, hostname: str, max_active_jobs: int, max_running_jobs: int
    ) -> None:
        """Update job limits for a host.

        Args:
            hostname: Hostname to update.
            max_active_jobs: Maximum active (queued + running) jobs.
            max_running_jobs: Maximum concurrent running jobs.

        Raises:
            ValueError: If host not found or limits invalid.
        """
        if max_active_jobs < 0:
            raise ValueError("max_active_jobs cannot be negative")
        if max_running_jobs < 1:
            raise ValueError("max_running_jobs must be at least 1")
        if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
            raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE db_hosts 
                SET max_active_jobs = %s, max_running_jobs = %s 
                WHERE hostname = %s
                """,
                (max_active_jobs, max_running_jobs, hostname),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def add_host(
        self, hostname: str, max_concurrent: int, credential_ref: str | None
    ) -> None:
        """Add a new database host.

        Args:
            hostname: Hostname of the database server.
            max_concurrent: Maximum concurrent jobs allowed.
            credential_ref: AWS Secrets Manager reference.

        Raises:
            ValueError: If host already exists.
        """
        import uuid
        host_id = str(uuid.uuid4())
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO db_hosts (id, hostname, max_running_jobs, enabled, credential_ref)
                        VALUES (%s, %s, %s, TRUE, %s)
                        """,
                        (host_id, hostname, max_concurrent, credential_ref),
                    )
                    conn.commit()
        except mysql.connector.IntegrityError as e:
            if "Duplicate" in str(e):
                raise ValueError(f"Host already exists: {hostname}") from e
            raise

    def enable_host(self, hostname: str) -> None:
        """Enable a database host.

        Args:
            hostname: Hostname to enable.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE db_hosts SET enabled = TRUE WHERE hostname = %s",
                (hostname,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def disable_host(self, hostname: str) -> None:
        """Disable a database host.

        Args:
            hostname: Hostname to disable.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE db_hosts SET enabled = FALSE WHERE hostname = %s",
                (hostname,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def hard_delete_host(self, host_id: str) -> None:
        """Permanently delete a database host record.

        WARNING: This is a hard delete - the record cannot be recovered.
        Use this only after cleaning up associated resources (MySQL user, AWS secret).
        
        Args:
            host_id: UUID of host to delete.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM db_hosts WHERE id = %s",
                (host_id,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {host_id}")

    def search_hosts(self, query: str, limit: int = 10) -> list[DBHost]:
        """Search for hosts by hostname or alias.

        Used by searchable dropdown components.

        Args:
            query: Search string (minimum 3 characters recommended).
            limit: Maximum number of results to return.

        Returns:
            List of matching DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            search_pattern = f"%{query}%"
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE hostname LIKE %s OR host_alias LIKE %s
                ORDER BY
                    CASE WHEN hostname LIKE %s THEN 0 ELSE 1 END,
                    hostname
                LIMIT %s
                """,
                (search_pattern, search_pattern, f"{query}%", limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

    def update_host_config(
        self,
        host_id: str,
        *,
        host_alias: str | None = None,
        credential_ref: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Update host configuration by ID.

        Updates only the fields that are explicitly provided (non-None).

        Args:
            host_id: UUID string of the host to update.
            host_alias: New alias (use empty string to clear, None to skip).
            credential_ref: New credential reference (None to skip).
            max_running_jobs: New max running jobs (None to skip).
            max_active_jobs: New max active jobs (None to skip).

        Raises:
            ValueError: If host not found or limits invalid.
        """
        updates = []
        params: list[t.Any] = []

        if host_alias is not None:
            updates.append("host_alias = %s")
            params.append(host_alias or None)  # Empty string -> NULL
        if credential_ref is not None:
            updates.append("credential_ref = %s")
            params.append(credential_ref)
        if max_running_jobs is not None:
            if max_running_jobs < 1:
                raise ValueError("max_running_jobs must be at least 1")
            updates.append("max_running_jobs = %s")
            params.append(max_running_jobs)
        if max_active_jobs is not None:
            if max_active_jobs < 0:
                raise ValueError("max_active_jobs cannot be negative")
            updates.append("max_active_jobs = %s")
            params.append(max_active_jobs)

        if not updates:
            return  # Nothing to update

        # Validate running <= active if both are being updated (and active > 0)
        if max_running_jobs is not None and max_active_jobs is not None:
            if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
                raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        params.append(host_id)

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE db_hosts SET {', '.join(updates)} WHERE id = %s",
                tuple(params),
            )
            conn.commit()
            # rowcount == 0 can mean either "host not found" OR "no values changed"
            # MySQL default is to return affected rows, not matched rows
            # If rowcount is 0, verify the host actually exists before reporting error
            if cursor.rowcount == 0:
                cursor.execute("SELECT 1 FROM db_hosts WHERE id = %s", (host_id,))
                if cursor.fetchone() is None:
                    raise ValueError(f"Host not found: {host_id}")

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
            host_alias=row.get("host_alias"),
            credential_ref=row["credential_ref"],
            max_running_jobs=row["max_running_jobs"],
            max_active_jobs=row["max_active_jobs"],
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

    def get_staging_retention_days(self) -> int:
        """Get number of days before staging databases are eligible for cleanup.

        Returns:
            Retention days. 7 is the default. 0 means cleanup is disabled.
        """
        value = self.get_setting("staging_retention_days")
        if value is None:
            return 7  # Default: 7 days
        try:
            return max(0, int(value))  # Ensure non-negative
        except ValueError:
            return 7  # Default: 7 days if setting is invalid

    def get_job_log_retention_days(self) -> int:
        """Get number of days before job logs are eligible for pruning.

        Returns:
            Retention days. 30 is the default. 0 means pruning is disabled.
        """
        value = self.get_setting("job_log_retention_days")
        if value is None:
            return 30  # Default: 30 days
        try:
            return max(0, int(value))  # Ensure non-negative
        except ValueError:
            return 30  # Default: 30 days if setting is invalid

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


class AdminTaskRepository:
    """Repository for admin background task operations.

    Manages async admin tasks like force-deleting users with database cleanup.
    Supports claiming with orphan recovery (reclaims stale running tasks).
    Enforces max 1 concurrent task per type via unique index.
    """

    # Default timeout for reclaiming orphaned running tasks (minutes)
    DEFAULT_STALE_TIMEOUT_MINUTES = 10

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize admin task repository.

        Args:
            pool: MySQL connection pool.
        """
        self.pool = pool

    def create_task(
        self,
        task_type: AdminTaskType,
        requested_by: str,
        target_user_id: str | None = None,
        parameters: dict | None = None,
    ) -> str:
        """Create a new admin task.

        Args:
            task_type: Type of task to create.
            requested_by: User ID of admin requesting the task.
            target_user_id: Target user ID (for user-related tasks).
            parameters: Task parameters (e.g., databases_to_drop).

        Returns:
            Task ID.

        Raises:
            ValueError: If a task of the same type is already running.
        """
        task_id = str(uuid.uuid4())
        parameters_json = json.dumps(parameters) if parameters else None

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO admin_tasks
                        (task_id, task_type, status, requested_by, target_user_id,
                         parameters_json, created_at)
                    VALUES (%s, %s, 'pending', %s, %s, %s, UTC_TIMESTAMP(6))
                    """,
                    (task_id, task_type.value, requested_by, target_user_id, parameters_json),
                )
                conn.commit()
                return task_id
            except mysql.connector.IntegrityError as e:
                if "idx_admin_tasks_single_running" in str(e):
                    raise ValueError(
                        f"A {task_type.value} task is already running. "
                        "Please wait for it to complete."
                    ) from e
                raise

    def get_task(self, task_id: str) -> AdminTask | None:
        """Get an admin task by ID.

        Args:
            task_id: Task UUID.

        Returns:
            AdminTask instance or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT task_id, task_type, status, requested_by, target_user_id,
                       parameters_json, result_json, created_at, started_at,
                       completed_at, error_detail, worker_id
                FROM admin_tasks
                WHERE task_id = %s
                """,
                (task_id,),
            )
            row = cursor.fetchone()
            return self._row_to_task(row) if row else None

    def claim_next_task(
        self,
        worker_id: str | None = None,
        stale_timeout_minutes: int = DEFAULT_STALE_TIMEOUT_MINUTES,
    ) -> AdminTask | None:
        """Atomically claim next pending task or reclaim a stale running task.

        Uses SELECT FOR UPDATE SKIP LOCKED to safely claim tasks when multiple
        workers are running. Also reclaims running tasks older than timeout
        (orphan recovery for crashed workers).

        Args:
            worker_id: Optional worker identifier (hostname:pid).
            stale_timeout_minutes: Minutes before a running task is considered stale.

        Returns:
            Claimed task (now in 'running' status) or None if no tasks available.
        """
        with self.pool.transaction() as conn:
            cursor = conn.cursor(dictionary=True)

            # First try pending tasks (FIFO order)
            cursor.execute(
                """
                SELECT task_id, task_type, status, requested_by, target_user_id,
                       parameters_json, result_json, created_at, started_at,
                       completed_at, error_detail, worker_id
                FROM admin_tasks
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
            )
            row = cursor.fetchone()

            # If no pending tasks, try to reclaim stale running tasks
            if not row:
                cursor.execute(
                    """
                    SELECT task_id, task_type, status, requested_by, target_user_id,
                           parameters_json, result_json, created_at, started_at,
                           completed_at, error_detail, worker_id
                    FROM admin_tasks
                    WHERE status = 'running'
                      AND started_at < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL %s MINUTE)
                    ORDER BY started_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    (stale_timeout_minutes,),
                )
                row = cursor.fetchone()
                if row:
                    logger.warning(
                        f"Reclaiming stale admin task {row['task_id']} "
                        f"(was claimed by {row['worker_id']})"
                    )

            if not row:
                return None

            task_id = row["task_id"]

            # Update to running
            cursor.execute(
                """
                UPDATE admin_tasks
                SET status = 'running',
                    started_at = UTC_TIMESTAMP(6),
                    worker_id = %s
                WHERE task_id = %s
                """,
                (worker_id, task_id),
            )

            # Return task with updated status
            task = self._row_to_task(row)
            now = datetime.now(UTC).replace(tzinfo=None)
            return AdminTask(
                task_id=task.task_id,
                task_type=task.task_type,
                status=AdminTaskStatus.RUNNING,
                requested_by=task.requested_by,
                target_user_id=task.target_user_id,
                parameters_json=task.parameters_json,
                result_json=task.result_json,
                created_at=task.created_at,
                started_at=now,
                completed_at=task.completed_at,
                error_detail=task.error_detail,
                worker_id=worker_id,
            )

    def complete_task(self, task_id: str, result: dict | None = None) -> None:
        """Mark a task as complete.

        Args:
            task_id: Task UUID.
            result: Result data to store as JSON.
        """
        result_json = json.dumps(result) if result else None
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE admin_tasks
                SET status = 'complete',
                    completed_at = UTC_TIMESTAMP(6),
                    result_json = %s
                WHERE task_id = %s
                """,
                (result_json, task_id),
            )
            conn.commit()

    def fail_task(self, task_id: str, error: str, result: dict | None = None) -> None:
        """Mark a task as failed.

        Args:
            task_id: Task UUID.
            error: Error message.
            result: Partial result data (e.g., some databases dropped before failure).
        """
        result_json = json.dumps(result) if result else None
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE admin_tasks
                SET status = 'failed',
                    completed_at = UTC_TIMESTAMP(6),
                    error_detail = %s,
                    result_json = %s
                WHERE task_id = %s
                """,
                (error, result_json, task_id),
            )
            conn.commit()

    def update_task_result(self, task_id: str, result: dict) -> None:
        """Update task result while running (for progress tracking).

        Args:
            task_id: Task UUID.
            result: Result data to store as JSON.
        """
        result_json = json.dumps(result)
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE admin_tasks
                SET result_json = %s
                WHERE task_id = %s
                """,
                (result_json, task_id),
            )
            conn.commit()

    def get_tasks_by_status(
        self,
        status: AdminTaskStatus,
        limit: int = 100,
    ) -> list[AdminTask]:
        """Get tasks by status.

        Args:
            status: Task status to filter by.
            limit: Maximum number of results.

        Returns:
            List of AdminTask instances.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT task_id, task_type, status, requested_by, target_user_id,
                       parameters_json, result_json, created_at, started_at,
                       completed_at, error_detail, worker_id
                FROM admin_tasks
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (status.value, limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_recent_tasks(self, limit: int = 50) -> list[AdminTask]:
        """Get recent tasks across all statuses.

        Args:
            limit: Maximum number of results.

        Returns:
            List of AdminTask instances, newest first.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT task_id, task_type, status, requested_by, target_user_id,
                       parameters_json, result_json, created_at, started_at,
                       completed_at, error_detail, worker_id
                FROM admin_tasks
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def _row_to_task(self, row: dict) -> AdminTask:
        """Convert database row to AdminTask instance."""
        parameters = None
        if row.get("parameters_json"):
            if isinstance(row["parameters_json"], str):
                parameters = json.loads(row["parameters_json"])
            else:
                parameters = row["parameters_json"]

        result = None
        if row.get("result_json"):
            if isinstance(row["result_json"], str):
                result = json.loads(row["result_json"])
            else:
                result = row["result_json"]

        return AdminTask(
            task_id=row["task_id"],
            task_type=AdminTaskType(row["task_type"]),
            status=AdminTaskStatus(row["status"]),
            requested_by=row["requested_by"],
            target_user_id=row.get("target_user_id"),
            parameters_json=parameters,
            result_json=result,
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            error_detail=row.get("error_detail"),
            worker_id=row.get("worker_id"),
        )
