"""Authentication repository for password and session management.

Phase 4: Handles password verification, session creation/validation,
and 2FA verification. Separate from UserRepository to maintain
single responsibility.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from pulldb.infra.mysql import MySQLPool


class AuthRepository:
    """Repository for authentication operations.

    Handles password verification, session creation/validation,
    and 2FA verification. Separate from UserRepository to maintain
    single responsibility.

    Example:
        >>> repo = AuthRepository(pool)
        >>> repo.set_password_hash(user_id, hashed_password)
        >>> session_id, token = repo.create_session(user_id)
        >>> user_id = repo.validate_session(token)
    """

    # Session token length in bytes (generates 64 hex chars)
    TOKEN_BYTES = 32

    # Default session TTL
    DEFAULT_SESSION_TTL_HOURS = 24

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize AuthRepository with connection pool.

        Args:
            pool: MySQL connection pool for database access.
        """
        self.pool = pool

    def get_password_hash(self, user_id: str) -> str | None:
        """Get stored password hash for user.

        Args:
            user_id: UUID of the user.

        Returns:
            Password hash if set, None if no password configured.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT password_hash FROM auth_credentials WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            if row and row.get("password_hash"):
                return str(row["password_hash"])
            return None

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        """Set password hash for user.

        Creates or updates the auth_credentials record for the user.

        Args:
            user_id: UUID of the user.
            password_hash: Bcrypt hash of the password.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            # Use INSERT ... ON DUPLICATE KEY UPDATE for upsert
            cursor.execute(
                """
                INSERT INTO auth_credentials
                    (user_id, password_hash, created_at, updated_at)
                VALUES (%s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE
                    password_hash = VALUES(password_hash),
                    updated_at = UTC_TIMESTAMP(6)
                """,
                (user_id, password_hash),
            )
            conn.commit()

    def has_password(self, user_id: str) -> bool:
        """Check if user has a password set.

        Args:
            user_id: UUID of the user.

        Returns:
            True if password is set, False otherwise.
        """
        return self.get_password_hash(user_id) is not None

    # =========================================================================
    # Password Reset Methods
    # =========================================================================

    def mark_password_reset(self, user_id: str) -> None:
        """Mark a user's password for reset.

        When marked, the user must reset their password via CLI
        (pulldb --setpass) before they can log in again.

        Args:
            user_id: UUID of the user.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auth_credentials
                    (user_id, password_reset_at, created_at, updated_at)
                VALUES (%s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE
                    password_reset_at = UTC_TIMESTAMP(6),
                    updated_at = UTC_TIMESTAMP(6)
                """,
                (user_id,),
            )
            conn.commit()

    def clear_password_reset(self, user_id: str) -> None:
        """Clear the password reset flag after user sets new password.

        Called after successful password change via CLI.

        Args:
            user_id: UUID of the user.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE auth_credentials
                SET password_reset_at = NULL,
                    updated_at = UTC_TIMESTAMP(6)
                WHERE user_id = %s
                """,
                (user_id,),
            )
            conn.commit()

    def is_password_reset_required(self, user_id: str) -> bool:
        """Check if user must reset their password.

        Args:
            user_id: UUID of the user.

        Returns:
            True if password reset is required, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT password_reset_at FROM auth_credentials WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return bool(row and row.get("password_reset_at"))

    def get_password_reset_at(self, user_id: str) -> datetime | None:
        """Get timestamp when password reset was requested.

        Args:
            user_id: UUID of the user.

        Returns:
            Datetime when reset was requested, None if not required.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT password_reset_at FROM auth_credentials WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            if row and row.get("password_reset_at"):
                reset_at = row["password_reset_at"]
                if isinstance(reset_at, datetime):
                    return reset_at
            return None

    def get_totp_secret(self, user_id: str) -> str | None:
        """Get TOTP secret for user.

        Args:
            user_id: UUID of the user.

        Returns:
            Base32-encoded TOTP secret if enabled, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT totp_secret FROM auth_credentials
                WHERE user_id = %s AND totp_enabled = TRUE
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if row and row.get("totp_secret"):
                return str(row["totp_secret"])
            return None

    def set_totp_secret(self, user_id: str, totp_secret: str) -> None:
        """Set and enable TOTP for user.

        Args:
            user_id: UUID of the user.
            totp_secret: Base32-encoded TOTP secret.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auth_credentials
                    (user_id, totp_secret, totp_enabled, created_at, updated_at)
                VALUES (%s, %s, TRUE, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE
                    totp_secret = VALUES(totp_secret),
                    totp_enabled = TRUE,
                    updated_at = UTC_TIMESTAMP(6)
                """,
                (user_id, totp_secret),
            )
            conn.commit()

    def disable_totp(self, user_id: str) -> None:
        """Disable TOTP for user.

        Args:
            user_id: UUID of the user.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE auth_credentials
                SET totp_enabled = FALSE,
                    totp_secret = NULL,
                    updated_at = UTC_TIMESTAMP(6)
                WHERE user_id = %s
                """,
                (user_id,),
            )
            conn.commit()

    def is_totp_enabled(self, user_id: str) -> bool:
        """Check if TOTP is enabled for user.

        Args:
            user_id: UUID of the user.

        Returns:
            True if TOTP is enabled, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT totp_enabled FROM auth_credentials WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return bool(row and row.get("totp_enabled"))

    def create_session(
        self,
        user_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        ttl_hours: int | None = None,
    ) -> tuple[str, str]:
        """Create new session for user.

        Generates a cryptographically secure session token and stores
        its hash in the database.

        Args:
            user_id: UUID of the user.
            ip_address: Client IP address (optional).
            user_agent: Client user agent string (optional).
            ttl_hours: Session time-to-live in hours (default: 24).

        Returns:
            Tuple of (session_id, session_token). The token should be
            returned to the client; only its hash is stored.
        """
        if ttl_hours is None:
            ttl_hours = self.DEFAULT_SESSION_TTL_HOURS

        session_id = str(uuid.uuid4())
        token = secrets.token_hex(self.TOKEN_BYTES)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessions
                    (session_id, user_id, token_hash, created_at,
                     expires_at, last_activity, ip_address, user_agent)
                VALUES
                    (%s, %s, %s, UTC_TIMESTAMP(6), %s, UTC_TIMESTAMP(6), %s, %s)
                """,
                (session_id, user_id, token_hash, expires_at, ip_address, user_agent),
            )
            conn.commit()

        return session_id, token

    def validate_session(self, session_token: str) -> str | None:
        """Validate session token and return user_id.

        Checks token hash against database and verifies expiration.
        Updates last_activity on successful validation.

        Args:
            session_token: The session token to validate.

        Returns:
            user_id if session is valid, None otherwise.
        """
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()

        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT session_id, user_id, expires_at
                FROM sessions
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Check expiration
            # MySQL returns naive datetime, treat as UTC
            expires_at = row["expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC):
                # Session expired, clean it up
                cursor.execute(
                    "DELETE FROM sessions WHERE session_id = %s",
                    (row["session_id"],),
                )
                conn.commit()
                return None

            # Update last activity
            cursor.execute(
                """
                UPDATE sessions
                SET last_activity = UTC_TIMESTAMP(6)
                WHERE session_id = %s
                """,
                (row["session_id"],),
            )
            conn.commit()

            return str(row["user_id"])

    def invalidate_session(self, session_id: str) -> None:
        """Invalidate a session (logout).

        Args:
            session_id: UUID of the session to invalidate.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE session_id = %s",
                (session_id,),
            )
            conn.commit()

    def invalidate_session_by_token(self, session_token: str) -> bool:
        """Invalidate a session by its token.

        Args:
            session_token: The session token to invalidate.

        Returns:
            True if a session was invalidated, False if not found.
        """
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE token_hash = %s",
                (token_hash,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def invalidate_all_user_sessions(self, user_id: str) -> int:
        """Invalidate all sessions for user.

        Useful for security events like password change or
        account compromise.

        Args:
            user_id: UUID of the user.

        Returns:
            Number of sessions invalidated.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE user_id = %s",
                (user_id,),
            )
            conn.commit()
            return cursor.rowcount

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions from database.

        Should be called periodically to clean up old sessions.

        Returns:
            Number of sessions removed.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE expires_at < UTC_TIMESTAMP(6)"
            )
            conn.commit()
            return cursor.rowcount

    def get_user_session_count(self, user_id: str) -> int:
        """Get count of active sessions for user.

        Args:
            user_id: UUID of the user.

        Returns:
            Number of active (non-expired) sessions.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM sessions
                WHERE user_id = %s AND expires_at > UTC_TIMESTAMP(6)
                """,
                (user_id,),
            )
            result = cursor.fetchone()
            return int(result[0]) if result else 0

    # =========================================================================
    # User Host Assignment Methods
    # =========================================================================

    def get_user_hosts(self, user_id: str) -> list[tuple[str, str, bool]]:
        """Get database hosts assigned to a user.

        Args:
            user_id: UUID of the user.

        Returns:
            List of (host_id, hostname, is_default) tuples.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT uh.host_id, h.hostname, h.host_alias, uh.is_default
                FROM user_hosts uh
                JOIN db_hosts h ON h.id = uh.host_id
                WHERE uh.user_id = %s
                ORDER BY uh.is_default DESC, h.hostname ASC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [
                (row["host_id"], row["host_alias"] or row["hostname"], row["is_default"])
                for row in rows
            ]

    def set_user_hosts(
        self,
        user_id: str,
        host_ids: list[str],
        default_host_id: str | None,
        assigned_by: str | None = None,
    ) -> None:
        """Set database hosts for a user (replaces all existing assignments).

        Args:
            user_id: UUID of the user.
            host_ids: List of host IDs to assign.
            default_host_id: Host ID to mark as default (must be in host_ids).
            assigned_by: UUID of admin making the assignment.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Delete existing assignments
            cursor.execute(
                "DELETE FROM user_hosts WHERE user_id = %s",
                (user_id,),
            )

            # Insert new assignments
            if host_ids:
                # Auto-default: if only one host, it becomes the default
                if len(host_ids) == 1:
                    default_host_id = host_ids[0]
                for host_id in host_ids:
                    is_default = host_id == default_host_id
                    cursor.execute(
                        """
                        INSERT INTO user_hosts 
                            (user_id, host_id, is_default, assigned_at, assigned_by)
                        VALUES (%s, %s, %s, UTC_TIMESTAMP(6), %s)
                        """,
                        (user_id, host_id, is_default, assigned_by),
                    )

            conn.commit()

    def get_user_default_host(self, user_id: str) -> str | None:
        """Get the default host hostname for a user.

        Args:
            user_id: UUID of the user.

        Returns:
            Canonical hostname of default host, or None if no default set.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT h.hostname
                FROM user_hosts uh
                JOIN db_hosts h ON h.id = uh.host_id
                WHERE uh.user_id = %s AND uh.is_default = TRUE
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return row["hostname"]
            return None

    def get_user_allowed_hosts(self, user_id: str) -> list[str]:
        """Get list of canonical hostnames a user is allowed to access.

        Args:
            user_id: UUID of the user.

        Returns:
            List of canonical hostnames the user can access.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT h.hostname
                FROM user_hosts uh
                JOIN db_hosts h ON h.id = uh.host_id
                WHERE uh.user_id = %s
                ORDER BY h.hostname ASC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [row["hostname"] for row in rows]
