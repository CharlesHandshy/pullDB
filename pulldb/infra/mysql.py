"""MySQL infrastructure for pullDB.

Implements connection pooling and repository pattern for database access.
All database operations are encapsulated in repository classes to enforce
business rules and provide clean abstractions.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from typing import Any, ClassVar, cast
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import mysql.connector
from mysql.connector import errorcode
from mysql.connector import errors as mysql_errors
from mysql.connector.abstracts import MySQLConnectionAbstract
from mysql.connector.pooling import PooledMySQLConnection

from pulldb.domain.errors import LockedUserError
from pulldb.domain.models import (
    AdminTask,
    AdminTaskStatus,
    AdminTaskType,
    DBHost,
    DisallowedUser,
    Job,
    JobEvent,
    JobStatus,
    MaintenanceItems,
    User,
    UserDetail,
    UserRole,
    UserSummary,
)
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials
from pulldb.infra.timeouts import DEFAULT_MYSQL_CONNECT_TIMEOUT_WORKER


logger = logging.getLogger(__name__)

# Type aliases for MySQL cursor results with dictionary=True
# These help Pylance understand the actual runtime types
DictRow = dict[str, Any]
TupleRow = tuple[Any, ...]


def _dict_row(row: Any) -> DictRow | None:
    """Cast fetchone() result to DictRow for cursors with dictionary=True.
    
    mysql-connector-python type stubs don't narrow the return type when
    dictionary=True is passed. This helper provides type safety for the
    actual runtime behavior.
    """
    return cast(DictRow | None, row)


def _dict_rows(rows: Any) -> list[DictRow]:
    """Cast fetchall() result to list[DictRow] for cursors with dictionary=True."""
    return cast(list[DictRow], rows)


class TypedDictCursor:
    """Wrapper around MySQL cursor with proper type annotations for dictionary mode.
    
    mysql-connector-python's type stubs use generic RowType/RowItemType that don't
    narrow when dictionary=True. This wrapper provides correctly typed fetchone()
    and fetchall() methods for dictionary cursors.
    
    Usage:
        with pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()  # Returns dict[str, Any] | None
            if row:
                username = row.get("username")  # Type-safe access
    """
    
    def __init__(self, cursor: Any) -> None:
        """Wrap a MySQL cursor created with dictionary=True."""
        self._cursor = cursor
    
    def execute(self, query: str, params: Any = None) -> None:
        """Execute a query with optional parameters."""
        if params is None:
            self._cursor.execute(query)
        else:
            self._cursor.execute(query, params)
    
    def executemany(self, query: str, params: list[Any]) -> None:
        """Execute a query with multiple parameter sets."""
        self._cursor.executemany(query, params)
    
    def fetchone(self) -> DictRow | None:
        """Fetch one row as a dictionary."""
        return cast(DictRow | None, self._cursor.fetchone())
    
    def fetchall(self) -> list[DictRow]:
        """Fetch all rows as dictionaries."""
        return cast(list[DictRow], self._cursor.fetchall())
    
    def fetchmany(self, size: int = 1) -> list[DictRow]:
        """Fetch many rows as dictionaries."""
        return cast(list[DictRow], self._cursor.fetchmany(size))
    
    @property
    def rowcount(self) -> int:
        """Number of rows affected by the last execute."""
        return cast(int, self._cursor.rowcount)
    
    @property
    def lastrowid(self) -> int | None:
        """Last auto-incremented ID."""
        return cast(int | None, self._cursor.lastrowid)
    
    def close(self) -> None:
        """Close the cursor."""
        self._cursor.close()
    
    def __enter__(self) -> "TypedDictCursor":
        """Context manager entry."""
        return self
    
    def __exit__(self, *args: Any) -> None:
        """Context manager exit - closes cursor."""
        self.close()


class TypedTupleCursor:
    """Wrapper around MySQL cursor with proper type annotations for tuple mode.
    
    For cursors created without dictionary=True, rows are tuples.
    This wrapper provides correctly typed fetchone() and fetchall() methods.
    Also exposes nextset() for multi-statement query support.
    """
    
    def __init__(self, cursor: Any) -> None:
        """Wrap a MySQL cursor (without dictionary=True)."""
        self._cursor = cursor
    
    def execute(self, query: str, params: Any = None) -> None:
        """Execute a query with optional parameters."""
        if params is None:
            self._cursor.execute(query)
        else:
            self._cursor.execute(query, params)
    
    def executemany(self, query: str, params: list[Any]) -> None:
        """Execute a query with multiple parameter sets."""
        self._cursor.executemany(query, params)
    
    def fetchone(self) -> TupleRow | None:
        """Fetch one row as a tuple."""
        return cast(TupleRow | None, self._cursor.fetchone())
    
    def fetchall(self) -> list[TupleRow]:
        """Fetch all rows as tuples."""
        return cast(list[TupleRow], self._cursor.fetchall())
    
    def fetchmany(self, size: int = 1) -> list[TupleRow]:
        """Fetch many rows as tuples."""
        return cast(list[TupleRow], self._cursor.fetchmany(size))
    
    @property
    def rowcount(self) -> int:
        """Number of rows affected by the last execute."""
        return cast(int, self._cursor.rowcount)
    
    @property
    def lastrowid(self) -> int | None:
        """Last auto-incremented ID."""
        return cast(int | None, self._cursor.lastrowid)
    
    def nextset(self) -> bool | None:
        """Move to next result set (for multi-statement queries)."""
        return cast(bool | None, self._cursor.nextset())
    
    def close(self) -> None:
        """Close the cursor."""
        self._cursor.close()
    
    def __enter__(self) -> "TypedTupleCursor":
        """Context manager entry."""
        return self
    
    def __exit__(self, *args: Any) -> None:
        """Context manager exit - closes cursor."""
        self.close()


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


class MySQLPool:
    """Very small wrapper around mysql.connector.connect for early prototype.

    Will be replaced with a real pooled implementation and per-host connections.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize MySQL connection pool.

        Args:
            **kwargs: Connection parameters passed to mysql.connector.connect().
        """
        self._kwargs = kwargs

    @contextmanager
    def connection(self) -> Iterator[PooledMySQLConnection | MySQLConnectionAbstract]:
        """Get a database connection from the pool.

        Yields:
            MySQL connection object with automatic cleanup.
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[PooledMySQLConnection | MySQLConnectionAbstract]:
        """Get a database connection with explicit transaction control.

        Disables autocommit for manual transaction management. Commits on
        successful exit, rolls back on exception. Used for atomic operations
        like job claiming in multi-worker environments.

        Yields:
            MySQL connection object with autocommit disabled.

        Example:
            >>> with pool.transaction() as conn:
            ...     cursor = TypedTupleCursor(conn.cursor())
            ...     cursor.execute("SELECT ... FOR UPDATE")
            ...     cursor.execute("UPDATE ...")
            ...     # Commits automatically on exit
        """
        conn = mysql.connector.connect(**self._kwargs)
        conn.autocommit = False  # type: ignore[union-attr]
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def dict_cursor(self) -> Iterator[TypedDictCursor]:
        """Get a typed dictionary cursor with automatic cleanup.
        
        This is the preferred way to query when you need to access columns by name.
        The cursor's fetchone() returns dict[str, Any] | None with proper typing.
        
        Yields:
            TypedDictCursor with properly typed fetch methods.
            
        Example:
            >>> with pool.dict_cursor() as cursor:
            ...     cursor.execute("SELECT id, name FROM users")
            ...     row = cursor.fetchone()
            ...     if row:
            ...         print(row.get("name"))  # Type-safe access
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            raw_cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor = TypedDictCursor(raw_cursor)
            try:
                yield cursor
            finally:
                cursor.close()
        finally:
            conn.close()

    @contextmanager
    def tuple_cursor(self) -> Iterator[TypedTupleCursor]:
        """Get a typed tuple cursor with automatic cleanup.
        
        This is for queries where positional access is acceptable.
        The cursor's fetchone() returns tuple[Any, ...] | None with proper typing.
        
        Yields:
            TypedTupleCursor with properly typed fetch methods.
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            raw_cursor = TypedTupleCursor(conn.cursor())
            cursor = TypedTupleCursor(raw_cursor)
            try:
                yield cursor
            finally:
                cursor.close()
        finally:
            conn.close()


def build_default_pool(
    host: str,
    user: str,
    password: str,
    database: str,
    unix_socket: str | None = None,
) -> MySQLPool:
    """Build a MySQL connection pool with default configuration.

    Args:
        host: MySQL server hostname.
        user: MySQL username.
        password: MySQL password.
        database: Database name.
        unix_socket: Optional Unix socket path (overrides host/port if provided).

    Returns:
        Configured MySQLPool instance.
    """
    kwargs: dict[str, Any] = {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
    }
    if unix_socket:
        kwargs["unix_socket"] = unix_socket
    return MySQLPool(**kwargs)


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
            mysql.connector.IntegrityError: If target already has active job.
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
                     retry_count, custom_target)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), %s, %s, %s)
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail, worker_id,
                       staging_cleaned_at, cancel_requested_at, can_cancel,
                       expires_at, locked_at, locked_by, db_dropped_at,
                       superseded_at, superseded_by_job_id
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
                       superseded_at, superseded_by_job_id
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
        the max_retention_months setting, and clears the worker processing lock.

        IMPORTANT: Only updates if job is still in 'running' status. This
        prevents race conditions where stale recovery marks a job as failed
        but the restore completes and tries to mark it deployed.

        Note:
            The worker_id column is intentionally retained after deployment
            for debugging purposes (to identify which worker processed the job).
            The expires_at is calculated as completed_at + max_retention_months
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
            # Get max_retention_months from settings (default 6)
            cursor.execute(
                """SELECT COALESCE(
                    (SELECT CAST(setting_value AS UNSIGNED) FROM settings 
                     WHERE setting_key = 'max_retention_months'),
                    6
                ) AS retention_months"""
            )
            row = cursor.fetchone()
            retention_months = row[0] if row else 6
            
            # Only update if still in running status - prevents overwriting
            # 'failed' status set by stale recovery
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'deployed', 
                    completed_at = UTC_TIMESTAMP(6),
                    expires_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s MONTH),
                    locked_at = NULL,
                    locked_by = NULL
                WHERE id = %s AND status = 'running'
                """,
                (retention_months, job_id),
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
        cancellation request, and releases the worker lock.

        Note:
            The worker_id column is intentionally retained after failure
            for debugging purposes (to identify which worker processed the job).
            The cancel_requested_at is cleared since the job has reached a
            terminal state and the cancellation is no longer relevant.
            The locked_at/locked_by/can_cancel fields are cleared since
            failed jobs should be deletable and no longer need protection.

        Args:
            job_id: UUID of job.
            error: Error message describing failure.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed', completed_at = UTC_TIMESTAMP(6),
                    error_detail = %s, cancel_requested_at = NULL,
                    locked_at = NULL, locked_by = NULL, can_cancel = TRUE
                WHERE id = %s
                """,
                (error, job_id),
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
        Updates status to 'canceled' and records completion time.

        Args:
            job_id: UUID of job.
            reason: Optional reason for cancellation (stored in error_detail).
        """
        error_detail = reason or "Canceled by user request"
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            # IMPORTANT: Only recover jobs that are the NEWEST for their target.
            # Older superseded jobs have already had their DBs cleaned up by the
            # newer job's restore process, so retrying deletion is pointless.
            # Also handle legacy jobs with NULL started_at (treat as stale).
            cursor.execute(
                """
                SELECT j.id, j.owner_user_id, j.owner_username, j.owner_user_code,
                       j.target, j.staging_name, j.dbhost, j.status, j.submitted_at,
                       j.started_at, j.completed_at, j.options_json, j.retry_count,
                       j.error_detail, j.worker_id
                FROM jobs j
                WHERE j.status = 'deleting'
                  AND (j.started_at IS NULL 
                       OR j.started_at < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL %s MINUTE))
                  AND j.retry_count < %s
                  AND NOT EXISTS (
                      SELECT 1 FROM jobs j2
                      WHERE j2.target = j.target
                        AND j2.owner_user_code = j.owner_user_code
                        AND j2.submitted_at > j.submitted_at
                  )
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
                       j.error_detail, j.worker_id
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
                       j.can_cancel, j.cancel_requested_at
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
                       j.can_cancel, j.cancel_requested_at
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
                       can_cancel, cancel_requested_at
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
                       superseded_at, superseded_by_job_id
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
                       superseded_at, superseded_by_job_id
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
                       superseded_at, superseded_by_job_id
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
                       superseded_at, superseded_by_job_id
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
                       superseded_at, superseded_by_job_id
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
                       superseded_at, superseded_by_job_id
                FROM jobs
                WHERE owner_user_id = %s
                  AND status = 'deployed'
                  AND db_dropped_at IS NULL
                  AND superseded_at IS NULL
                  AND (
                      expires_at < UTC_TIMESTAMP() + INTERVAL %s DAY
                      OR (locked_at IS NOT NULL AND expires_at < UTC_TIMESTAMP())
                  )
                ORDER BY expires_at ASC
                """,
                (user_id, notice_days),
            )
            rows = cursor.fetchall()

        expired: list[Job] = []
        expiring: list[Job] = []
        locked: list[Job] = []

        for row in rows:
            job = self._row_to_job(row)
            if job.is_locked and job.is_expired:
                locked.append(job)
            elif job.is_expired:
                expired.append(job)
            elif job.is_expiring(notice_days):
                expiring.append(job)

        return MaintenanceItems(expired=expired, expiring=expiring, locked=locked)

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
                       superseded_at, superseded_by_job_id
                FROM jobs
                WHERE status = 'deployed'
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
                       superseded_at, superseded_by_job_id
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
                       superseded_at, superseded_by_job_id
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, max_active_jobs, locked_at
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, max_active_jobs, locked_at
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, max_active_jobs, locked_at
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
                cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
                           created_at, disabled_at, manager_id, locked_at
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
        import hashlib
        
        user_letters_required = 6  # Magic number constant for user_code length
        # Step 1: Extract letters only, lowercase
        letters = [c.lower() for c in username if c.isalpha()]

        # Step 1b: If fewer than 6 letters, pad with hash-based suffix
        if len(letters) < user_letters_required:
            # Generate deterministic padding from username hash
            username_hash = hashlib.sha256(username.lower().encode()).hexdigest()
            # Use only lowercase letters from hash (convert hex to letters a-p)
            hash_letters = ''.join(
                chr(ord('a') + int(c, 16) % 16) for c in username_hash
            )
            needed = user_letters_required - len(letters)
            letters.extend(list(hash_letters[:needed]))

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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked_by_username(username, "enable")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked_by_username(username, "disable")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "enable")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "disable")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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

    # =========================================================================
    # Maintenance Acknowledgment Methods
    # =========================================================================

    def get_last_maintenance_ack(self, user_id: str) -> datetime | None:
        """Get last maintenance acknowledgment date for a user.

        Args:
            user_id: User UUID.

        Returns:
            Date of last acknowledgment, or None if never acknowledged.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                "SELECT last_maintenance_ack FROM auth_users WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return row["last_maintenance_ack"] if row else None

    def set_last_maintenance_ack(self, user_id: str, ack_date: datetime) -> None:
        """Set last maintenance acknowledgment date for a user.

        Args:
            user_id: User UUID.
            ack_date: Date to record (typically today's date).
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "UPDATE auth_users SET last_maintenance_ack = %s WHERE user_id = %s",
                (ack_date, user_id),
            )
            conn.commit()

    def needs_maintenance_ack(self, user_id: str) -> bool:
        """Check if user needs to acknowledge maintenance modal today.

        Args:
            user_id: User UUID.

        Returns:
            True if user hasn't acknowledged today, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT last_maintenance_ack 
                FROM auth_users 
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False  # User not found
            
            last_ack = row["last_maintenance_ack"]
            if last_ack is None:
                return True  # Never acknowledged
            
            # Compare dates (not timestamps)
            from datetime import date
            today = date.today()
            if isinstance(last_ack, datetime):
                last_ack_date = last_ack.date()
            else:
                last_ack_date = last_ack
            
            return last_ack_date < today

    def _row_to_user(self, row: dict[str, Any]) -> User:
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
            last_maintenance_ack=row.get("last_maintenance_ack"),
            locked_at=row.get("locked_at"),
        )

    def _check_user_not_locked(self, user_id: str, action: str) -> None:
        """Raise LockedUserError if user is locked.

        Must be called before any user modification operation.

        Args:
            user_id: UUID of the user to check.
            action: Description of blocked action (e.g., "enable", "delete").

        Raises:
            LockedUserError: If user is locked.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "SELECT username, locked_at FROM auth_users WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            if row and row[1] is not None:  # locked_at is not null
                logger.warning("Blocked attempt to %s locked user: %s", action, row[0])
                raise LockedUserError(row[0], action)

    def _check_user_not_locked_by_username(self, username: str, action: str) -> None:
        """Raise LockedUserError if user is locked (by username lookup).

        For methods that take username instead of user_id.

        Args:
            username: Username of the user to check.
            action: Description of blocked action.

        Raises:
            LockedUserError: If user is locked.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "SELECT username, locked_at FROM auth_users WHERE username = %s",
                (username,),
            )
            row = cursor.fetchone()
            if row and row[1] is not None:
                logger.warning("Blocked attempt to %s locked user: %s", action, row[0])
                raise LockedUserError(row[0], action)

    def get_users_managed_by(self, manager_id: str) -> list[User]:
        """Get all users managed by a specific manager.

        Args:
            manager_id: User ID of the manager.

        Returns:
            List of User instances managed by this manager.
            Excludes SERVICE role accounts and locked users.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, locked_at
                FROM auth_users
                WHERE manager_id = %s
                  AND role != 'service'
                  AND locked_at IS NULL
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "change manager for")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "change role for")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "change job limit for")
        if max_active_jobs is not None and max_active_jobs < 0:
            raise ValueError("max_active_jobs cannot be negative")

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            search_pattern = f"%{query}%"
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, locked_at
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
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "delete")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            
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
            count_row = cursor.fetchone()
            job_count = count_row[0] if count_row else 0
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

        Raises:
            LockedUserError: If any user is locked.
        """
        if not user_ids:
            return 0
        # Check for locked users first
        for uid in user_ids:
            self._check_user_not_locked(uid, "disable")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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

        Raises:
            LockedUserError: If any user is locked.
        """
        if not user_ids:
            return 0
        # Check for locked users first
        for uid in user_ids:
            self._check_user_not_locked(uid, "enable")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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

        Raises:
            LockedUserError: If any user is locked.
        """
        if not user_ids:
            return 0
        # Check for locked users first
        for uid in user_ids:
            self._check_user_not_locked(uid, "reassign manager for")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
        """Get all users with manager or admin role who can manage other users.

        SERVICE role users are excluded - system accounts cannot be managers.

        Returns:
            List of users who can manage other users.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, role, created_at,
                       disabled_at, manager_id, locked_at
                FROM auth_users
                WHERE role IN ('manager', 'admin')
                AND disabled_at IS NULL
                AND locked_at IS NULL
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
        context: dict[str, Any] | None = None,
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

        audit_id = str(uuid.uuid4())
        context_json = json.dumps(context) if context else None

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
    ) -> list[dict[str, Any]]:
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

        conditions = []
        params: list[Any] = []

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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
        params: list[Any] = []

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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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

    def get_host_credentials_for_maintenance(self, hostname: str) -> MySQLCredentials:
        """Get resolved MySQL credentials for maintenance operations.

        Similar to get_host_credentials but allows disabled hosts.
        Use for cleanup, deletion, and staging operations that need
        to work on disabled hosts.

        Args:
            hostname: Hostname to get credentials for.

        Returns:
            Resolved MySQLCredentials instance.

        Raises:
            ValueError: If host not found (deleted from db_hosts).
            CredentialResolutionError: If credentials cannot be resolved
                from AWS Secrets Manager or SSM Parameter Store.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")
        # NO enabled check - maintenance operations need access to disabled hosts

        # Delegate to CredentialResolver
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
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
        self,
        hostname: str,
        max_concurrent: int,
        credential_ref: str | None,
        *,
        host_id: str | None = None,
        host_alias: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Add a new database host.

        Args:
            hostname: Hostname of the database server.
            max_concurrent: Maximum concurrent running jobs allowed.
            credential_ref: AWS Secrets Manager reference.
            host_id: Optional UUID (generated if not provided).
            host_alias: Optional short alias for the host.
            max_running_jobs: Optional max running jobs (uses max_concurrent if not set).
            max_active_jobs: Optional max active jobs (defaults to 10).

        Raises:
            ValueError: If host already exists.
        """
        import uuid
        if host_id is None:
            host_id = str(uuid.uuid4())
        if max_active_jobs is None:
            max_active_jobs = 10
        # Use max_concurrent as fallback for max_running_jobs
        actual_max_running = max_running_jobs if max_running_jobs is not None else max_concurrent

        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO db_hosts 
                            (id, hostname, host_alias, max_running_jobs, max_active_jobs, 
                             enabled, credential_ref)
                        VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                        """,
                        (host_id, hostname, host_alias, actual_max_running, max_active_jobs, 
                         credential_ref),
                    )
                    conn.commit()
        except mysql.connector.IntegrityError as e:
            if "Duplicate" in str(e):
                raise ValueError(f"Host already exists: {hostname}") from e
            raise

    def delete_host(self, hostname: str) -> None:
        """Delete a database host by hostname.

        Args:
            hostname: Hostname to delete.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM db_hosts WHERE hostname = %s",
                (hostname,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def enable_host(self, hostname: str) -> None:
        """Enable a database host.

        Args:
            hostname: Hostname to enable.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
        params: list[Any] = []

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
            cursor = TypedTupleCursor(conn.cursor())
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

    def is_staging_db_active(
        self,
        hostname: str,
        staging_name: str,
        check_count: int = 3,
        check_delay_seconds: float = 2.0,
    ) -> bool:
        """Check if a staging database has active MySQL processes.

        Performs multiple SHOW PROCESSLIST checks to verify if a restore is
        still actively running on the staging database. This prevents false
        positives from treating long-running restores as stale jobs.

        The check runs `check_count` times with `check_delay_seconds` between
        each check. Returns True if ANY check finds activity, False only if
        ALL checks find no activity.

        Args:
            hostname: Database host to check.
            staging_name: Staging database name to look for in processlist.
            check_count: Number of times to check (default 3).
            check_delay_seconds: Delay between checks in seconds (default 2.0).

        Returns:
            True if any process is using the staging database, False otherwise.

        Raises:
            ValueError: If host not found or disabled.
            mysql.connector.Error: If connection fails.
        """
        import time

        credentials = self.get_host_credentials(hostname)

        conn = mysql.connector.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.username,
            password=credentials.password,
            connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_WORKER,
        )
        try:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            for i in range(check_count):
                cursor.execute("SHOW PROCESSLIST")
                rows: list[dict[str, Any]] = cursor.fetchall()  # type: ignore[assignment]

                # Check if any process is using the staging database
                for row in rows:
                    if row.get("db") == staging_name:
                        logger.info(
                            "Active process found on staging database",
                            extra={
                                "staging_name": staging_name,
                                "hostname": hostname,
                                "process_id": row.get("Id"),
                                "process_user": row.get("User"),
                                "process_command": row.get("Command"),
                                "check_attempt": i + 1,
                            },
                        )
                        return True

                # Delay before next check (except on last iteration)
                if i < check_count - 1:
                    time.sleep(check_delay_seconds)

            # No activity found in any check
            logger.info(
                "No active processes found on staging database",
                extra={
                    "staging_name": staging_name,
                    "hostname": hostname,
                    "checks_performed": check_count,
                },
            )
            return False

        finally:
            conn.close()

    def _row_to_dbhost(self, row: dict[str, Any]) -> DBHost:
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

    def get(self, key: str) -> str | None:
        """Alias for get_setting().

        Args:
            key: Setting key to look up.

        Returns:
            Setting value if found, None otherwise.
        """
        return self.get_setting(key)

    def get_setting(self, key: str) -> str | None:
        """Get setting value by key.

        Args:
            key: Setting key to look up.

        Returns:
            Setting value if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                DELETE FROM settings
                WHERE setting_key = %s
                """,
                (key,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def get_all_settings_with_metadata(self) -> list[dict[str, str | None]]:
        """Get all settings with their metadata (description, updated_at).

        Returns:
            List of dicts with keys: setting_key, setting_value, description, updated_at
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT setting_key, setting_value, description, updated_at
                FROM settings
                ORDER BY setting_key ASC
                """
            )
            return list(cursor.fetchall())

    # -------------------------------------------------------------------------
    # Database Retention Settings
    # -------------------------------------------------------------------------

    def get_max_retention_months(self) -> int:
        """Get maximum retention months for database expiration.

        Returns:
            Maximum months a database can be retained (1-12). Default: 6.
        """
        value = self.get_setting("max_retention_months")
        if value is None:
            return 6  # Default: 6 months
        try:
            return max(1, min(12, int(value)))  # Clamp to 1-12
        except ValueError:
            return 6

    def get_max_retention_increment(self) -> int:
        """Get increment step for retention dropdown options.

        Returns:
            Step size in months (1-5). Default: 3.
        """
        value = self.get_setting("max_retention_increment")
        if value is None:
            return 3  # Default: 3 months
        try:
            return max(1, min(5, int(value)))  # Clamp to 1-5
        except ValueError:
            return 3

    def get_expiring_notice_days(self) -> int:
        """Get days before expiry to show warning notice.

        Returns:
            Number of days. Default: 7.
        """
        value = self.get_setting("expiring_notice_days")
        if value is None:
            return 7
        try:
            return max(0, int(value))
        except ValueError:
            return 7

    def get_cleanup_grace_days(self) -> int:
        """Get days after expiry before automatic cleanup.

        Returns:
            Number of days. Default: 7.
        """
        value = self.get_setting("cleanup_grace_days")
        if value is None:
            return 7
        try:
            return max(0, int(value))
        except ValueError:
            return 7

    def get_jobs_refresh_interval(self) -> int:
        """Get auto-refresh interval for jobs page in seconds.

        Returns:
            Interval in seconds. Default: 5. 0 means disabled.
        """
        value = self.get_setting("jobs_refresh_interval_seconds")
        if value is None:
            return 5  # Default: 5 seconds
        try:
            return max(0, min(60, int(value)))  # Clamp to 0-60
        except ValueError:
            return 5

    def get_retention_options(
        self, include_now: bool = False
    ) -> list[tuple[str, str]]:
        """Get retention dropdown options based on current settings.

        Generates options starting with 1 month, then stepping by increment
        up to the maximum retention months.

        Args:
            include_now: Whether to include "Now" (immediate removal) option.

        Returns:
            List of (value, label) tuples for dropdown options.
            Value is string: "now", or number of months as string ("1", "3", etc.)
        """
        max_months = self.get_max_retention_months()
        increment = self.get_max_retention_increment()

        options: list[tuple[str, str]] = []

        if include_now:
            options.append(("now", "Now"))

        # Always include 1 month as first option
        if 1 <= max_months:
            options.append(("1", "+1 month"))

        # Then step by increment
        months = increment
        while months <= max_months:
            if months != 1:  # Don't duplicate 1
                label = f"+{months} months"
                options.append((str(months), label))
            months += increment

        return options


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
            cursor = TypedTupleCursor(conn.cursor())
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

    def create_bulk_delete_task(
        self,
        requested_by: str,
        job_infos: list[dict],
        hard_delete: bool = False,
        skip_database_drops: bool = False,
    ) -> str:
        """Create a bulk delete jobs task.

        Convenience method for creating BULK_DELETE_JOBS tasks with the
        required parameter structure.

        Args:
            requested_by: User ID of user requesting the deletion.
            job_infos: List of job info dicts with keys:
                - job_id: Job UUID
                - staging_name: Staging database name
                - target: Target database name  
                - owner_user_code: Owner's user code
                - owner_user_id: Owner's user ID
                - owner_manager_id: Owner's manager ID (for permission verification)
                - dbhost: Database host
            hard_delete: If True, permanently delete job records after dropping DBs.
            skip_database_drops: If True, skip database drop operations (for inaccessible hosts).

        Returns:
            Task ID.
        """
        parameters = {
            "job_infos": job_infos,
            "hard_delete": hard_delete,
            "skip_database_drops": skip_database_drops,
            "total_jobs": len(job_infos),
        }
        return self.create_task(
            task_type=AdminTaskType.BULK_DELETE_JOBS,
            requested_by=requested_by,
            parameters=parameters,
        )

    def get_task(self, task_id: str) -> AdminTask | None:
        """Get an admin task by ID.

        Args:
            task_id: Task UUID.

        Returns:
            AdminTask instance or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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


# =============================================================================
# Disallowed Users Repository
# =============================================================================


class DisallowedUserRepository:
    """Repository for managing disallowed usernames.

    Works alongside hardcoded list in pulldb/domain/validation.py.
    Database entries extend the hardcoded list.
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize repository with connection pool."""
        self.pool = pool

    def get_all(self) -> list[DisallowedUser]:
        """Get all disallowed usernames from database.

        Returns:
            List of DisallowedUser entries, sorted by username.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT username, reason, is_hardcoded, created_at, created_by
                FROM disallowed_users
                ORDER BY username ASC
                """
            )
            rows = cursor.fetchall()
            return [
                DisallowedUser(
                    username=row["username"],
                    reason=row.get("reason"),
                    is_hardcoded=bool(row.get("is_hardcoded")),
                    created_at=row.get("created_at"),
                    created_by=row.get("created_by"),
                )
                for row in rows
            ]

    def exists(self, username: str) -> bool:
        """Check if username is in database disallowed list.

        Args:
            username: Username to check (case-insensitive).

        Returns:
            True if username is disallowed in database.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "SELECT 1 FROM disallowed_users WHERE username = %s",
                (username.lower(),),
            )
            return cursor.fetchone() is not None

    def add(
        self,
        username: str,
        reason: str | None = None,
        created_by: str | None = None,
    ) -> bool:
        """Add a username to the disallowed list.

        Args:
            username: Username to disallow (stored lowercase).
            reason: Optional reason for disallowing.
            created_by: User ID who added this entry.

        Returns:
            True if added, False if already exists.
        """
        try:
            with self.pool.connection() as conn:
                cursor = TypedTupleCursor(conn.cursor())
                cursor.execute(
                    """
                    INSERT INTO disallowed_users (username, reason, is_hardcoded, created_by)
                    VALUES (%s, %s, FALSE, %s)
                    """,
                    (username.lower(), reason, created_by),
                )
                conn.commit()
                return True
        except mysql_errors.IntegrityError:
            # Duplicate key - user already in disallowed list
            logger.debug("Disallowed user '%s' already exists", username)
            return False
        except mysql_errors.Error as e:
            # Other MySQL errors - log with more detail
            logger.warning(
                "Failed to add disallowed user '%s': %s",
                username,
                e,
                exc_info=True,
            )
            return False

    def remove(self, username: str) -> tuple[bool, str]:
        """Remove a username from the disallowed list.

        Only non-hardcoded entries can be removed.

        Args:
            username: Username to remove.

        Returns:
            Tuple of (success, message).
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            # Check if exists and if hardcoded
            cursor.execute(
                "SELECT is_hardcoded FROM disallowed_users WHERE username = %s",
                (username.lower(),),
            )
            row = cursor.fetchone()

            if not row:
                return False, f"Username '{username}' is not in the disallowed list"

            if row["is_hardcoded"]:
                return False, f"Username '{username}' is a hardcoded entry and cannot be removed"

            # Delete non-hardcoded entry
            cursor.execute(
                "DELETE FROM disallowed_users WHERE username = %s AND is_hardcoded = FALSE",
                (username.lower(),),
            )
            conn.commit()

            if cursor.rowcount > 0:
                return True, f"Username '{username}' removed from disallowed list"
            return False, f"Could not remove username '{username}'"

    def is_disallowed(self, username: str) -> tuple[bool, str | None]:
        """Check if username is disallowed (hardcoded OR database).

        This is the primary validation method - checks both sources.

        Args:
            username: Username to check (case-insensitive).

        Returns:
            Tuple of (is_disallowed, reason).
        """
        from pulldb.domain.validation import (
            DISALLOWED_USERS_HARDCODED,
            MIN_USERNAME_LENGTH,
        )

        username_lower = username.lower()

        # Check length first
        if len(username_lower) < MIN_USERNAME_LENGTH:
            return True, f"Username must be at least {MIN_USERNAME_LENGTH} characters"

        # Check hardcoded list
        if username_lower in DISALLOWED_USERS_HARDCODED:
            return True, "Reserved system name"

        # Check database list
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                "SELECT reason FROM disallowed_users WHERE username = %s",
                (username_lower,),
            )
            row = cursor.fetchone()
            if row:
                return True, row.get("reason") or "Username not allowed"

        return False, None
