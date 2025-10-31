"""MySQL infrastructure for pullDB.

Implements connection pooling and repository pattern for database access.
All database operations are encapsulated in repository classes to enforce
business rules and provide clean abstractions.
"""

from __future__ import annotations

import typing as t
import uuid
from contextlib import contextmanager

import mysql.connector

from pulldb.domain.models import Job, JobEvent, JobStatus


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
        >>> next_job = repo.get_next_queued_job()
        >>> repo.mark_job_running(next_job.id)
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize repository with connection pool.

        Args:
            pool: MySQL connection pool for coordination database.
        """
        self.pool = pool

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
                        job.options_json,
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

        Returns oldest queued job by submitted_at timestamp. Used by worker
        to poll for work.

        Returns:
            Next queued job or None if queue empty.
        """
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

        Called by worker when it begins processing a job. Updates status from
        'queued' to 'running' and records start time.

        Args:
            job_id: UUID of job.

        Raises:
            ValueError: If job not found or not in queued status.
        """
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
                raise ValueError(
                    f"Job {job_id} not found or not in queued status"
                )
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

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running).

        Uses active_jobs view for efficient querying. Jobs returned in
        submission order (oldest first).

        Returns:
            List of active jobs ordered by submitted_at.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       status, submitted_at, started_at
                FROM active_jobs
                ORDER BY submitted_at ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_active_job(row) for row in rows]

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

    def get_job_events(self, job_id: str) -> list[JobEvent]:
        """Get all events for a job.

        Returns events in chronological order for job history display.

        Args:
            job_id: UUID of job.

        Returns:
            List of events ordered by logged_at.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, job_id, event_type, detail, logged_at
                FROM job_events
                WHERE job_id = %s
                ORDER BY logged_at ASC
                """,
                (job_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job_event(row) for row in rows]

    def _row_to_job(self, row: dict[str, t.Any]) -> Job:
        """Convert MySQL row to Job dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            Job instance with all fields populated.
        """
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
            options_json=row.get("options_json"),
            retry_count=row.get("retry_count", 0),
            error_detail=row.get("error_detail"),
        )

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

