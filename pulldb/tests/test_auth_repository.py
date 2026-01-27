"""Tests for AuthRepository.

Phase 4: Tests for password hash storage and session management.
Requires database fixtures from conftest.py.
"""

from __future__ import annotations

"""HCA Layer: tests."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pulldb.auth.password import hash_password
from pulldb.auth.repository import AuthRepository


class TestAuthRepositoryPassword:
    """Tests for password hash storage."""

    def test_get_password_hash_no_credentials(self, mysql_pool: Any) -> None:
        """get_password_hash returns None when no credentials exist."""
        repo = AuthRepository(mysql_pool)
        result = repo.get_password_hash("nonexistent-user-id")
        assert result is None

    def test_set_and_get_password_hash(self, mysql_pool: Any) -> None:
        """set_password_hash stores hash and get retrieves it."""
        repo = AuthRepository(mysql_pool)
        user_id = str(uuid.uuid4())
        password_hash = hash_password("test_password")

        # Create user first (needed for FK constraint)
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auth_users (user_id, username, user_code, role, created_at)
                VALUES (%s, %s, %s, 'user', UTC_TIMESTAMP(6))
                """,
                (user_id, f"testuser_{user_id[:8]}", user_id[:6]),
            )
            conn.commit()

        try:
            repo.set_password_hash(user_id, password_hash)
            retrieved = repo.get_password_hash(user_id)
            assert retrieved == password_hash
        finally:
            # Cleanup
            with mysql_pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM auth_credentials WHERE user_id = %s", (user_id,)
                )
                cursor.execute("DELETE FROM auth_users WHERE user_id = %s", (user_id,))
                conn.commit()

    def test_set_password_hash_updates_existing(self, mysql_pool: Any) -> None:
        """set_password_hash updates if credentials already exist."""
        repo = AuthRepository(mysql_pool)
        user_id = str(uuid.uuid4())
        hash1 = hash_password("password1")
        hash2 = hash_password("password2")

        # Create user first
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auth_users (user_id, username, user_code, role, created_at)
                VALUES (%s, %s, %s, 'user', UTC_TIMESTAMP(6))
                """,
                (user_id, f"testuser_{user_id[:8]}", user_id[:6]),
            )
            conn.commit()

        try:
            repo.set_password_hash(user_id, hash1)
            assert repo.get_password_hash(user_id) == hash1

            repo.set_password_hash(user_id, hash2)
            assert repo.get_password_hash(user_id) == hash2
        finally:
            with mysql_pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM auth_credentials WHERE user_id = %s", (user_id,)
                )
                cursor.execute("DELETE FROM auth_users WHERE user_id = %s", (user_id,))
                conn.commit()

    def test_has_password(self, mysql_pool: Any) -> None:
        """has_password returns True when password is set."""
        repo = AuthRepository(mysql_pool)
        user_id = str(uuid.uuid4())

        # Create user first
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auth_users (user_id, username, user_code, role, created_at)
                VALUES (%s, %s, %s, 'user', UTC_TIMESTAMP(6))
                """,
                (user_id, f"testuser_{user_id[:8]}", user_id[:6]),
            )
            conn.commit()

        try:
            assert repo.has_password(user_id) is False
            repo.set_password_hash(user_id, hash_password("test"))
            assert repo.has_password(user_id) is True
        finally:
            with mysql_pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM auth_credentials WHERE user_id = %s", (user_id,)
                )
                cursor.execute("DELETE FROM auth_users WHERE user_id = %s", (user_id,))
                conn.commit()


class TestAuthRepositorySessions:
    """Tests for session management."""

    def _create_test_user(self, mysql_pool: Any) -> str:
        """Create a test user and return user_id."""
        user_id = str(uuid.uuid4())
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auth_users (user_id, username, user_code, role, created_at)
                VALUES (%s, %s, %s, 'user', UTC_TIMESTAMP(6))
                """,
                (user_id, f"testuser_{user_id[:8]}", user_id[:6]),
            )
            conn.commit()
        return user_id

    def _cleanup_user(self, mysql_pool: Any, user_id: str) -> None:
        """Clean up test user and related data."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
            cursor.execute(
                "DELETE FROM auth_credentials WHERE user_id = %s", (user_id,)
            )
            cursor.execute("DELETE FROM auth_users WHERE user_id = %s", (user_id,))
            conn.commit()

    def test_create_session_returns_session_and_token(self, mysql_pool: Any) -> None:
        """create_session returns session_id and token."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            session_id, token = repo.create_session(user_id)
            assert session_id is not None
            assert len(session_id) == 36  # UUID format
            assert token is not None
            assert len(token) == 64  # hex of 32 bytes
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_validate_session_returns_user_id(self, mysql_pool: Any) -> None:
        """validate_session returns user_id for valid token."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            _, token = repo.create_session(user_id)
            result = repo.validate_session(token)
            assert result == user_id
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_validate_session_invalid_token(self, mysql_pool: Any) -> None:
        """validate_session returns None for invalid token."""
        repo = AuthRepository(mysql_pool)
        result = repo.validate_session("invalid_token_12345678901234567890")
        assert result is None

    def test_validate_session_expired(self, mysql_pool: Any) -> None:
        """validate_session returns None for expired session."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            # Create session with very short TTL
            session_id, token = repo.create_session(user_id, ttl_hours=0)

            # Manually expire the session
            with mysql_pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE sessions SET expires_at = %s WHERE session_id = %s
                    """,
                    (datetime.now(UTC) - timedelta(hours=1), session_id),
                )
                conn.commit()

            result = repo.validate_session(token)
            assert result is None
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_invalidate_session(self, mysql_pool: Any) -> None:
        """invalidate_session removes session."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            session_id, token = repo.create_session(user_id)
            assert repo.validate_session(token) == user_id

            repo.invalidate_session(session_id)
            assert repo.validate_session(token) is None
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_invalidate_session_by_token(self, mysql_pool: Any) -> None:
        """invalidate_session_by_token removes session by token."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            _, token = repo.create_session(user_id)
            assert repo.validate_session(token) == user_id

            result = repo.invalidate_session_by_token(token)
            assert result is True
            assert repo.validate_session(token) is None
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_invalidate_session_by_token_not_found(self, mysql_pool: Any) -> None:
        """invalidate_session_by_token returns False when not found."""
        repo = AuthRepository(mysql_pool)
        result = repo.invalidate_session_by_token("nonexistent_token")
        assert result is False

    def test_invalidate_all_user_sessions(self, mysql_pool: Any) -> None:
        """invalidate_all_user_sessions removes all user sessions."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            _, token1 = repo.create_session(user_id)
            _, token2 = repo.create_session(user_id)
            _, token3 = repo.create_session(user_id)

            assert repo.validate_session(token1) == user_id
            assert repo.validate_session(token2) == user_id
            assert repo.validate_session(token3) == user_id

            count = repo.invalidate_all_user_sessions(user_id)
            assert count == 3

            assert repo.validate_session(token1) is None
            assert repo.validate_session(token2) is None
            assert repo.validate_session(token3) is None
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_get_user_session_count(self, mysql_pool: Any) -> None:
        """get_user_session_count returns active session count."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            assert repo.get_user_session_count(user_id) == 0

            repo.create_session(user_id)
            assert repo.get_user_session_count(user_id) == 1

            repo.create_session(user_id)
            assert repo.get_user_session_count(user_id) == 2
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_cleanup_expired_sessions(self, mysql_pool: Any) -> None:
        """cleanup_expired_sessions removes expired sessions."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            # Create a session
            session_id, _ = repo.create_session(user_id)

            # Manually expire it
            with mysql_pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE sessions SET expires_at = %s WHERE session_id = %s
                    """,
                    (datetime.now(UTC) - timedelta(hours=1), session_id),
                )
                conn.commit()

            # Run cleanup
            count = repo.cleanup_expired_sessions()
            assert count >= 1

            # Verify session is gone
            assert repo.get_user_session_count(user_id) == 0
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_session_stores_metadata(self, mysql_pool: Any) -> None:
        """create_session stores IP and user agent."""
        repo = AuthRepository(mysql_pool)
        user_id = self._create_test_user(mysql_pool)

        try:
            session_id, _ = repo.create_session(
                user_id, ip_address="192.168.1.1", user_agent="TestBrowser/1.0"
            )

            with mysql_pool.connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT ip_address, user_agent FROM sessions WHERE session_id = %s",
                    (session_id,),
                )
                row = cursor.fetchone()
                assert row is not None
                assert row["ip_address"] == "192.168.1.1"
                assert row["user_agent"] == "TestBrowser/1.0"
        finally:
            self._cleanup_user(mysql_pool, user_id)
