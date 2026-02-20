"""Authentication repository for password, session, and API key management.

Handles password verification, session creation/validation, 2FA verification,
and API key lifecycle (create, verify, revoke, encrypt-at-rest migration).
Separate from UserRepository to maintain single responsibility.

HCA Layer: features (pulldb/auth/)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from pulldb.domain.errors import KeyPendingApprovalError, KeyRevokedError, LockedUserError
from pulldb.infra.key_encryption import (
    decrypt_secret,
    encrypt_secret,
    get_encryption_key,
    get_old_encryption_key,
    is_encrypted,
    reencrypt_if_needed,
)
from pulldb.infra.mysql import MySQLPool, TypedDictCursor, TypedTupleCursor

logger = logging.getLogger(__name__)


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

    def _check_user_not_locked(self, user_id: str, action: str) -> None:
        """Raise LockedUserError if user is locked.

        Must be called before any user modification operation.

        Args:
            user_id: UUID of the user to check.
            action: Description of blocked action.

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

    def get_password_hash(self, user_id: str) -> str | None:
        """Get stored password hash for user.

        Args:
            user_id: UUID of the user.

        Returns:
            Password hash if set, None if no password configured.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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

        Raises:
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "set password for")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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

        Raises:
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "force password reset for")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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

        Raises:
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "clear password reset for")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                "SELECT totp_enabled FROM auth_credentials WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return bool(row and row.get("totp_enabled"))

    # =========================================================================
    # API Key Methods (for CLI/programmatic authentication)
    # =========================================================================

    def create_api_key(
        self,
        user_id: str,
        name: str | None = None,
        host_name: str | None = None,
        created_from_ip: str | None = None,
        auto_approve: bool = False,
        approved_by: str | None = None,
    ) -> tuple[str, str]:
        """Create a new API key for a user.

        Generates a key_id and secret, stores the hashed secret in the database,
        and returns both the key_id and plaintext secret. The secret is only
        returned once - it cannot be retrieved later.

        New keys are created active (is_active=TRUE) but unapproved
        (approved_at=NULL) by default. They must be approved by an admin
        before they can be used. The is_active flag is used for revocation.

        Args:
            user_id: UUID of the user.
            name: Optional friendly name for the key (auto-generated if not provided).
            host_name: Hostname where key was requested (auto-detected by CLI).
            created_from_ip: IP address of the request.
            auto_approve: If True, automatically approve the key (for admin-created keys).
            approved_by: User ID of admin approving (required if auto_approve=True).

        Returns:
            Tuple of (key_id, secret) where *secret* is the raw plaintext value
            returned only at creation time.  The secret is stored AES-256-GCM
            encrypted at rest (when ``PULLDB_KEY_ENCRYPTION_KEY`` is configured)
            and is retrievable only via ``get_api_key_secret()`` on the server.
        """
        from pulldb.auth.password import hash_password

        # Generate key_id (public identifier)
        key_id = "key_" + secrets.token_hex(16)

        # Generate secret (private, used for HMAC signing)
        secret = secrets.token_hex(32)

        # Hash the secret for audit purposes
        secret_hash = hash_password(secret)

        # Encrypt the secret at rest (passthrough when key not configured)
        stored_secret = encrypt_secret(secret)

        # Determine approval status
        is_active = auto_approve
        approved_at = "UTC_TIMESTAMP(6)" if auto_approve else None

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            if auto_approve:
                cursor.execute(
                    """
                    INSERT INTO api_keys
                        (key_id, user_id, key_secret_hash, key_secret, name, 
                         host_name, created_from_ip, is_active, approved_at, approved_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, UTC_TIMESTAMP(6), %s, UTC_TIMESTAMP(6))
                    """,
                    (key_id, user_id, secret_hash, stored_secret, name, host_name, created_from_ip, approved_by),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO api_keys
                        (key_id, user_id, key_secret_hash, key_secret, name, 
                         host_name, created_from_ip, is_active, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, UTC_TIMESTAMP(6))
                    """,
                    (key_id, user_id, secret_hash, stored_secret, name, host_name, created_from_ip),
                )
            conn.commit()

        return key_id, secret

    def verify_api_key(self, key_id: str, secret: str) -> str | None:
        """Verify an API key and return the associated user_id.

        Checks that the key exists, is active, and the secret matches.

        Args:
            key_id: The public key identifier.
            secret: The plaintext secret to verify.

        Returns:
            user_id if valid, None if invalid or inactive.
        """
        from pulldb.auth.password import verify_password

        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT user_id, key_secret_hash, is_active, expires_at
                FROM api_keys
                WHERE key_id = %s
                """,
                (key_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Check if active
            if not row.get("is_active"):
                return None

            # Check expiration
            expires_at = row.get("expires_at")
            if expires_at and expires_at < datetime.now(UTC):
                return None

            # Verify secret
            secret_hash = row.get("key_secret_hash")
            if not secret_hash or not verify_password(secret, secret_hash):
                return None

            # Update last_used_at
            cursor.execute(
                "UPDATE api_keys SET last_used_at = UTC_TIMESTAMP(6) WHERE key_id = %s",
                (key_id,),
            )
            conn.commit()

            user_id = row.get("user_id")
            return str(user_id) if user_id is not None else None

    def get_api_key_user(self, key_id: str) -> str | None:
        """Get the user_id associated with an API key.

        Does NOT verify the secret - use verify_api_key for authentication.
        Used for looking up the user after signature verification.

        Args:
            key_id: The public key identifier.

        Returns:
            user_id if key exists, is active, and is approved. None if not found.

        Raises:
            KeyPendingApprovalError: If key exists but is not yet approved.
            KeyRevokedError: If key exists but has been revoked (is_active=False).
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT user_id, is_active, approved_at, expires_at
                FROM api_keys
                WHERE key_id = %s
                """,
                (key_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Check if pending approval (key exists but not approved)
            if row.get("approved_at") is None:
                raise KeyPendingApprovalError(key_id)

            # Check if revoked
            if not row.get("is_active"):
                raise KeyRevokedError(key_id)

            # Check expiration
            expires_at = row.get("expires_at")
            if expires_at and expires_at < datetime.now(UTC):
                return None

            user_id = row.get("user_id")
            return str(user_id) if user_id is not None else None

    def get_api_key_secret_hash(self, key_id: str) -> str | None:
        """Get the secret hash for an API key (for HMAC verification).

        Args:
            key_id: The public key identifier.

        Returns:
            Secret hash if key is active and approved, None otherwise.

        Raises:
            KeyPendingApprovalError: If key exists but is not yet approved.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT key_secret_hash, is_active, approved_at, expires_at
                FROM api_keys
                WHERE key_id = %s
                """,
                (key_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Check if pending approval
            if row.get("approved_at") is None:
                raise KeyPendingApprovalError(key_id)

            if not row.get("is_active"):
                return None

            # Check expiration
            expires_at = row.get("expires_at")
            if expires_at and expires_at < datetime.now(UTC):
                return None

            secret_hash = row.get("key_secret_hash")
            return str(secret_hash) if secret_hash is not None else None

    def get_api_key_secret(self, key_id: str) -> str | None:
        """Get the plaintext secret for an API key (for HMAC verification).

        This is needed because HMAC verification requires the plaintext secret
        to compute the expected signature.

        Args:
            key_id: The public key identifier.

        Returns:
            Plaintext secret if key is active and approved, None if key not found.

        Raises:
            KeyPendingApprovalError: If key exists but is not yet approved.
            KeyRevokedError: If key exists but has been revoked (is_active=False).
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT key_secret, is_active, approved_at, expires_at
                FROM api_keys
                WHERE key_id = %s
                """,
                (key_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Check if pending approval
            if row.get("approved_at") is None:
                raise KeyPendingApprovalError(key_id)

            # Check if revoked
            if not row.get("is_active"):
                raise KeyRevokedError(key_id)

            # Check expiration
            expires_at = row.get("expires_at")
            if expires_at and expires_at < datetime.now(UTC):
                return None

            secret = row.get("key_secret")
            if secret is None:
                return None
            return decrypt_secret(str(secret))

    def migrate_encrypt_existing_keys(self) -> int:
        """Encrypt plaintext ``key_secret`` rows and re-encrypt old-key rows.

        **Normal mode** (only ``PULLDB_KEY_ENCRYPTION_KEY`` set):
        Iterates rows whose ``key_secret`` does not carry the ``aes256gcm:``
        prefix and encrypts them in-place.  Already-encrypted rows are skipped.

        **Rotation mode** (both ``PULLDB_KEY_ENCRYPTION_KEY`` and
        ``PULLDB_KEY_ENCRYPTION_KEY_OLD`` set):
        Iterates *all* non-NULL rows.  Plaintext rows are encrypted.
        Rows encrypted with the old key are transparently re-encrypted with
        the primary key.  Rows already using the primary key are skipped.
        Once this method returns 0 (nothing changed), remove the
        ``PULLDB_KEY_ENCRYPTION_KEY_OLD`` variable to retire the old key.

        This method is idempotent — safe to call multiple times.

        Returns:
            The number of rows updated during this call.

        Raises:
            RuntimeError: If ``PULLDB_KEY_ENCRYPTION_KEY`` is not configured.
        """
        if get_encryption_key() is None:
            raise RuntimeError(
                "Cannot migrate: PULLDB_KEY_ENCRYPTION_KEY is not set. "
                "Configure the encryption key before running migration."
            )

        rotation_mode = get_old_encryption_key() is not None

        _BATCH = 500
        migrated = 0
        with self.pool.connection() as conn:
            read_cursor = TypedDictCursor(conn.cursor(dictionary=True))
            if rotation_mode:
                # Full scan: also re-encrypt rows currently using the old key
                read_cursor.execute(
                    "SELECT key_id, key_secret FROM api_keys "
                    "WHERE key_secret IS NOT NULL"
                )
            else:
                # Fast path: only rows that haven't been encrypted yet
                read_cursor.execute(
                    "SELECT key_id, key_secret FROM api_keys "
                    "WHERE key_secret NOT LIKE 'aes256gcm:%'"
                )
            write_cursor = TypedTupleCursor(conn.cursor())
            while batch := read_cursor.fetchmany(_BATCH):
                for row in batch:
                    key_id = row["key_id"]
                    raw = row["key_secret"]
                    if raw is None:
                        continue
                    raw_str = str(raw)
                    if is_encrypted(raw_str):
                        # Already encrypted — re-encrypt only if using old key
                        new_val, changed = reencrypt_if_needed(raw_str)
                        if not changed:
                            continue
                        updated_val = new_val
                    else:
                        # Plaintext row — encrypt with primary key
                        updated_val = encrypt_secret(raw_str)
                    write_cursor.execute(
                        "UPDATE api_keys SET key_secret = %s WHERE key_id = %s",
                        (updated_val, key_id),
                    )
                    migrated += 1
                conn.commit()  # commit each batch

        if migrated:
            logger.info(
                "migrate_encrypt_existing_keys: updated %d key_secret row(s)%s",
                migrated,
                " (rotation pass)" if rotation_mode else "",
            )

        return migrated

    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key (mark inactive).

        Args:
            key_id: The public key identifier.

        Returns:
            True if key was revoked, False if not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "UPDATE api_keys SET is_active = FALSE WHERE key_id = %s",
                (key_id,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def reactivate_api_key(self, key_id: str) -> bool:
        """Reactivate a revoked API key.

        Only reactivates keys that have been previously approved.
        Keys that were never approved cannot be reactivated - they must
        go through the approval process.

        Args:
            key_id: The public key identifier.

        Returns:
            True if key was reactivated, False if not found or never approved.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE api_keys 
                SET is_active = TRUE 
                WHERE key_id = %s AND approved_at IS NOT NULL
                """,
                (key_id,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def delete_api_key(self, key_id: str) -> bool:
        """Delete a single API key permanently.

        This is a hard delete - the key is removed from the database entirely.
        Use revoke_api_key for soft-delete that can be reactivated.

        Args:
            key_id: The public key identifier to delete.

        Returns:
            True if key was deleted, False if not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM api_keys WHERE key_id = %s",
                (key_id,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def delete_api_keys_for_user(self, user_id: str) -> int:
        """Delete all API keys for a user.

        Used when deleting a user account.

        Args:
            user_id: UUID of the user.

        Returns:
            Number of keys deleted.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM api_keys WHERE user_id = %s",
                (user_id,),
            )
            conn.commit()
            return int(cursor.rowcount)

    def list_api_keys_for_user(self, user_id: str) -> list[dict]:
        """List all API keys for a user.

        Does NOT return the secret - that's only available at creation time.

        Args:
            user_id: UUID of the user.

        Returns:
            List of key info dicts (key_id, name, is_active, created_at, last_used_at).
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT key_id, name, host_name, is_active, approved_at, 
                       created_at, created_from_ip, last_used_at, last_used_ip, expires_at
                FROM api_keys
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())

    # Alias for backward compatibility and clarity
    def get_api_keys_for_user(self, user_id: str) -> list[dict]:
        """Alias for list_api_keys_for_user.
        
        This method name is used by web routes and CLI commands.
        """
        return self.list_api_keys_for_user(user_id)

    def get_pending_api_keys(self) -> list[dict]:
        """Get all API keys pending admin approval.

        Returns keys where approved_at IS NULL, ordered by creation time.

        Returns:
            List of pending key dicts with user info (username, host_name, etc.).
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT k.key_id, k.name, k.host_name, k.created_at, k.created_from_ip,
                       u.username, u.user_id
                FROM api_keys k
                JOIN auth_users u ON k.user_id = u.user_id
                WHERE k.approved_at IS NULL
                ORDER BY k.created_at ASC
                """,
            )
            return list(cursor.fetchall())

    def count_pending_api_keys_by_user(self, user_id: str) -> int:
        """Count pending API keys for a specific user.

        Args:
            user_id: The user ID to check.

        Returns:
            Number of pending keys for this user.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM api_keys
                WHERE user_id = %s AND approved_at IS NULL
                """,
                (user_id,),
            )
            result = cursor.fetchone()
            return result[0] if result else 0

    def approve_api_key(self, key_id: str, approved_by: str) -> bool:
        """Approve an API key (make it active and usable).

        Sets approved_at to current time and is_active to TRUE.

        Args:
            key_id: The public key identifier to approve.
            approved_by: User ID of the admin approving the key.

        Returns:
            True if key was approved, False if not found or already approved.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE api_keys 
                SET approved_at = UTC_TIMESTAMP(6), 
                    approved_by = %s, 
                    is_active = TRUE
                WHERE key_id = %s AND approved_at IS NULL
                """,
                (approved_by, key_id),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def get_api_key_info(self, key_id: str) -> dict | None:
        """Get full info about an API key.

        Args:
            key_id: The public key identifier.

        Returns:
            Dict with key info including username, or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT k.key_id, k.name, k.host_name, k.is_active, k.approved_at,
                       k.approved_by, k.created_at, k.created_from_ip, 
                       k.last_used_at, k.last_used_ip, k.expires_at,
                       u.username, u.user_id, u.user_code
                FROM api_keys k
                JOIN auth_users u ON k.user_id = u.user_id
                WHERE k.key_id = %s
                """,
                (key_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_api_key_last_used(
        self, key_id: str, ip_address: str | None = None
    ) -> None:
        """Update last_used_at and last_used_ip for an API key.

        Called after successful authentication to track key usage.

        Args:
            key_id: The public key identifier.
            ip_address: IP address of the request (optional).
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE api_keys 
                SET last_used_at = UTC_TIMESTAMP(6), last_used_ip = %s
                WHERE key_id = %s
                """,
                (ip_address, key_id),
            )
            conn.commit()

    def delete_expired_pending_keys(self, max_age_days: int = 7) -> int:
        """Delete pending keys that were never approved.

        Removes keys where approved_at IS NULL and created_at is older
        than max_age_days.

        Args:
            max_age_days: Maximum age in days for pending keys (default: 7).

        Returns:
            Number of keys deleted.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                DELETE FROM api_keys
                WHERE approved_at IS NULL
                  AND created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                """,
                (max_age_days,),
            )
            conn.commit()
            return int(cursor.rowcount)

    def get_all_api_keys(
        self, include_inactive: bool = False, user_id: str | None = None
    ) -> list[dict]:
        """Get all API keys with filtering options.

        Args:
            include_inactive: If True, include revoked keys.
            user_id: If provided, filter to keys for this user only.

        Returns:
            List of key info dicts with user details.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            
            conditions = []
            params: list = []
            
            if not include_inactive:
                conditions.append("k.is_active = TRUE")
            
            if user_id:
                conditions.append("k.user_id = %s")
                params.append(user_id)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            
            cursor.execute(
                f"""
                SELECT k.key_id, k.name, k.host_name, k.is_active, k.approved_at,
                       k.created_at, k.created_from_ip, k.last_used_at, k.last_used_ip,
                       u.username, u.user_id, u.user_code
                FROM api_keys k
                JOIN auth_users u ON k.user_id = u.user_id
                {where_clause}
                ORDER BY k.created_at DESC
                """,
                params,
            )
            return list(cursor.fetchall())

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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM sessions WHERE token_hash = %s",
                (token_hash,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

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
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM sessions WHERE user_id = %s",
                (user_id,),
            )
            conn.commit()
            return int(cursor.rowcount)

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions from database.

        Should be called periodically to clean up old sessions.

        Returns:
            Number of sessions removed.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM sessions WHERE expires_at < UTC_TIMESTAMP(6)"
            )
            conn.commit()
            return int(cursor.rowcount)

    def get_user_session_count(self, user_id: str) -> int:
        """Get count of active sessions for user.

        Args:
            user_id: UUID of the user.

        Returns:
            Number of active (non-expired) sessions.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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

        Raises:
            LockedUserError: If user is locked.
        """
        self._check_user_not_locked(user_id, "assign hosts for")
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())

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
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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
                hostname = row["hostname"]
                return str(hostname) if hostname is not None else None
            return None

    def get_user_allowed_hosts(self, user_id: str) -> list[str]:
        """Get list of canonical hostnames a user is allowed to access.

        Args:
            user_id: UUID of the user.

        Returns:
            List of canonical hostnames the user can access.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
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

    def count_users_for_host(self, host_id: str) -> int:
        """Count users assigned to a specific host.

        Used for host deletion preview to show affected users.

        Args:
            host_id: UUID of the host.

        Returns:
            Number of users assigned to this host.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "SELECT COUNT(*) FROM user_hosts WHERE host_id = %s",
                (host_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_users_for_host(self, host_id: str) -> list[dict]:
        """Get users assigned to a specific host.

        Args:
            host_id: UUID of the host.

        Returns:
            List of dicts with user_id, username, is_default for each user.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT u.user_id, u.username, uh.is_default
                FROM user_hosts uh
                JOIN auth_users u ON u.user_id = uh.user_id
                WHERE uh.host_id = %s
                ORDER BY u.username ASC
                """,
                (host_id,),
            )
            return list(cursor.fetchall())
