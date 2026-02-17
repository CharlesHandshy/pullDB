"""MySQL user repository for pullDB.

Implements the UserRepository class handling user CRUD operations,
code generation, bulk operations, and user management.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from mysql.connector import errors as mysql_errors

from pulldb.domain.errors import LockedUserError
from pulldb.domain.models import (
    User,
    UserDetail,
    UserRole,
    UserSummary,
)
from pulldb.infra.mysql_pool import (
    MySQLPool,
    TypedDictCursor,
    TypedTupleCursor,
)

logger = logging.getLogger(__name__)

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
                SELECT user_id, username, user_code, role, created_at,
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
                SELECT user_id, username, user_code, role, created_at,
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
                SELECT user_id, username, user_code, role, created_at,
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
                        (user_id, username, user_code, role, created_at, manager_id)
                    VALUES (%s, %s, %s, 'user', UTC_TIMESTAMP(6), %s)
                    """,
                    (user_id, username, user_code, manager_id),
                )
                conn.commit()

                # Fetch the created user
                cursor.execute(
                    """
                    SELECT user_id, username, user_code, role,
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

        except mysql_errors.IntegrityError as e:
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
                    u.user_id, u.username, u.user_code, u.role,
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
                    u.user_id, u.username, u.user_code, u.role,
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
        # Role is the single source of truth for permissions
        role = UserRole(row["role"])

        return User(
            user_id=row["user_id"],
            username=row["username"],
            user_code=row["user_code"],
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
                SELECT user_id, username, user_code, role, created_at,
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
                "UPDATE auth_users SET role = %s WHERE user_id = %s",
                (role.value, user_id),
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
                SELECT user_id, username, user_code, role, created_at,
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
                SELECT user_id, username, user_code, role, created_at,
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


