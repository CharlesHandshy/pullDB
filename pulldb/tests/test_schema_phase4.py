"""Tests for Phase 4 schema migrations.

Validates that migrations 070, 071, 072 were applied correctly.
Requires database fixtures from conftest.py.
"""

from __future__ import annotations

"""HCA Layer: tests."""

from typing import Any


class TestAuthUsersRoleMigration:
    """Tests for 070_auth_users_role.sql migration."""

    def test_role_column_exists(self, mysql_pool: Any) -> None:
        """auth_users table has role column."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'auth_users'
                  AND COLUMN_NAME = 'role'
                """
            )
            row = cursor.fetchone()
            assert row is not None, "role column should exist in auth_users"
            assert row["DATA_TYPE"] == "enum"

    def test_role_enum_values(self, mysql_pool: Any) -> None:
        """role column has correct enum values."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT COLUMN_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'auth_users'
                  AND COLUMN_NAME = 'role'
                """
            )
            row = cursor.fetchone()
            assert row is not None
            column_type = row["COLUMN_TYPE"]
            # COLUMN_TYPE looks like: enum('user','manager','admin')
            assert "'user'" in column_type
            assert "'manager'" in column_type
            assert "'admin'" in column_type

    def test_role_has_default_user(self, mysql_pool: Any) -> None:
        """role column defaults to 'user'."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'auth_users'
                  AND COLUMN_NAME = 'role'
                """
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["COLUMN_DEFAULT"] == "user"


class TestAuthCredentialsMigration:
    """Tests for 071_auth_credentials.sql migration."""

    def test_auth_credentials_table_exists(self, mysql_pool: Any) -> None:
        """auth_credentials table exists."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'auth_credentials'
                """
            )
            count = cursor.fetchone()[0]
            assert count == 1, "auth_credentials table should exist"

    def test_auth_credentials_columns(self, mysql_pool: Any) -> None:
        """auth_credentials has required columns."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'auth_credentials'
                ORDER BY ORDINAL_POSITION
                """
            )
            columns = [row["COLUMN_NAME"] for row in cursor.fetchall()]
            expected = [
                "user_id",
                "password_hash",
                "totp_secret",
                "totp_enabled",
                "created_at",
                "updated_at",
            ]
            for col in expected:
                assert col in columns, f"{col} column should exist"

    def test_auth_credentials_fk_cascade(self, mysql_pool: Any) -> None:
        """auth_credentials has CASCADE delete FK to auth_users."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT DELETE_RULE
                FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
                WHERE CONSTRAINT_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'auth_credentials'
                  AND REFERENCED_TABLE_NAME = 'auth_users'
                """
            )
            row = cursor.fetchone()
            assert row is not None, "FK constraint should exist"
            assert row["DELETE_RULE"] == "CASCADE"


class TestSessionsMigration:
    """Tests for 072_sessions.sql migration."""

    def test_sessions_table_exists(self, mysql_pool: Any) -> None:
        """sessions table exists."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'sessions'
                """
            )
            count = cursor.fetchone()[0]
            assert count == 1, "sessions table should exist"

    def test_sessions_columns(self, mysql_pool: Any) -> None:
        """sessions has required columns."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'sessions'
                ORDER BY ORDINAL_POSITION
                """
            )
            columns = [row["COLUMN_NAME"] for row in cursor.fetchall()]
            expected = [
                "session_id",
                "user_id",
                "token_hash",
                "created_at",
                "expires_at",
                "last_activity",
                "ip_address",
                "user_agent",
            ]
            for col in expected:
                assert col in columns, f"{col} column should exist"

    def test_sessions_has_user_index(self, mysql_pool: Any) -> None:
        """sessions table has user_id index."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT INDEX_NAME
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'sessions'
                  AND COLUMN_NAME = 'user_id'
                """
            )
            row = cursor.fetchone()
            assert row is not None, "user_id index should exist"

    def test_sessions_has_token_index(self, mysql_pool: Any) -> None:
        """sessions table has token_hash index."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT INDEX_NAME
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'sessions'
                  AND COLUMN_NAME = 'token_hash'
                """
            )
            row = cursor.fetchone()
            assert row is not None, "token_hash index should exist"

    def test_sessions_fk_cascade(self, mysql_pool: Any) -> None:
        """sessions has CASCADE delete FK to auth_users."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT DELETE_RULE
                FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
                WHERE CONSTRAINT_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'sessions'
                  AND REFERENCED_TABLE_NAME = 'auth_users'
                """
            )
            row = cursor.fetchone()
            assert row is not None, "FK constraint should exist"
            assert row["DELETE_RULE"] == "CASCADE"
