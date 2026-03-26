"""MySQL admin task and disallowed user repositories for pullDB.

Implements AdminTaskRepository for background admin task management
and DisallowedUserRepository for username disallow list operations.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from mysql.connector import errors as mysql_errors

from pulldb.domain.models import (
    AdminTask,
    AdminTaskStatus,
    AdminTaskType,
    DisallowedUser,
)
from pulldb.infra.mysql_pool import (
    MySQLPool,
    TypedDictCursor,
    TypedTupleCursor,
)

logger = logging.getLogger(__name__)

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
            except mysql_errors.IntegrityError as e:
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
        except mysql_errors.IntegrityError as e:
            if e.errno == 1062:  # ER_DUP_ENTRY — user already in disallowed list
                logger.debug("Disallowed user '%s' already exists", username)
                return False
            raise
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


# =============================================================================
# Job History Summary Repository
# =============================================================================


