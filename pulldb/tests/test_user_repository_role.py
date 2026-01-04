"""Tests for UserRepository role field handling.

Phase 4: Validates role field is properly stored and retrieved.
Requires database fixtures from conftest.py.
"""

from __future__ import annotations

import uuid
from typing import Any

from pulldb.domain.models import UserRole
from pulldb.infra.mysql import UserRepository


class TestUserRepositoryRoleField:
    """Tests for role field in UserRepository operations."""

    def _create_user_direct(
        self, mysql_pool: Any, user_id: str, username: str, role: str = "user"
    ) -> None:
        """Create a user directly in database with specific role."""
        # Use first 6 chars of user_id for unique user_code
        user_code = user_id[:6]
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auth_users 
                    (user_id, username, user_code, is_admin, role, created_at)
                VALUES (%s, %s, %s, FALSE, %s, UTC_TIMESTAMP(6))
                """,
                (user_id, username, user_code, role),
            )
            conn.commit()

    def _cleanup_user(self, mysql_pool: Any, user_id: str) -> None:
        """Remove test user and related data."""
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
            cursor.execute(
                "DELETE FROM auth_credentials WHERE user_id = %s", (user_id,)
            )
            cursor.execute("DELETE FROM auth_users WHERE user_id = %s", (user_id,))
            conn.commit()

    def test_get_user_by_id_returns_role(self, mysql_pool: Any) -> None:
        """get_user_by_id returns user with role field populated."""
        repo = UserRepository(mysql_pool)
        user_id = str(uuid.uuid4())
        username = f"roletest_{user_id[:8]}"

        try:
            self._create_user_direct(mysql_pool, user_id, username, "manager")
            user = repo.get_user_by_id(user_id)

            assert user is not None
            assert user.role == UserRole.MANAGER
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_get_user_by_username_returns_role(self, mysql_pool: Any) -> None:
        """get_user_by_username returns user with role field populated."""
        repo = UserRepository(mysql_pool)
        user_id = str(uuid.uuid4())
        username = f"roletest_{user_id[:8]}"

        try:
            self._create_user_direct(mysql_pool, user_id, username, "admin")
            user = repo.get_user_by_username(username)

            assert user is not None
            assert user.role == UserRole.ADMIN
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_create_user_defaults_to_user_role(self, mysql_pool: Any) -> None:
        """create_user sets role to 'user' by default."""
        repo = UserRepository(mysql_pool)
        user_id = str(uuid.uuid4())
        username = f"newuser_{user_id[:8]}"

        # Need to use get_or_create to get unique user_code
        try:
            user = repo.get_or_create_user(username)

            assert user is not None
            assert user.role == UserRole.USER
        finally:
            self._cleanup_user(mysql_pool, user.user_id)

    def test_role_field_all_values(self, mysql_pool: Any) -> None:
        """Role values USER, MANAGER, ADMIN can be stored and retrieved.
        
        Note: SERVICE role is also valid but not tested here as it's
        primarily for system accounts and tested in test_locked_user.py.
        """
        repo = UserRepository(mysql_pool)
        test_cases = [
            ("user", UserRole.USER),
            ("manager", UserRole.MANAGER),
            ("admin", UserRole.ADMIN),
        ]

        for role_str, expected_role in test_cases:
            user_id = str(uuid.uuid4())
            username = f"roletest_{user_id[:8]}"

            try:
                self._create_user_direct(mysql_pool, user_id, username, role_str)
                user = repo.get_user_by_id(user_id)

                assert user is not None, f"Failed for role {role_str}"
                assert (
                    user.role == expected_role
                ), f"Expected {expected_role}, got {user.role}"
            finally:
                self._cleanup_user(mysql_pool, user_id)

    def test_is_admin_synced_with_role(self, mysql_pool: Any) -> None:
        """is_admin field is independent of role field."""
        repo = UserRepository(mysql_pool)
        user_id = str(uuid.uuid4())
        username = f"admintest_{user_id[:8]}"

        try:
            # Create user with admin role
            with mysql_pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO auth_users 
                        (user_id, username, user_code, is_admin, role, created_at)
                    VALUES (%s, %s, %s, TRUE, 'admin', UTC_TIMESTAMP(6))
                    """,
                    (user_id, username, username[:6]),
                )
                conn.commit()

            user = repo.get_user_by_id(user_id)

            assert user is not None
            assert user.is_admin is True
            assert user.role == UserRole.ADMIN
        finally:
            self._cleanup_user(mysql_pool, user_id)

    def test_user_model_properties(self, mysql_pool: Any) -> None:
        """User model role properties work correctly."""
        repo = UserRepository(mysql_pool)

        # Create three users with different roles
        users_to_cleanup = []

        try:
            for role in ["user", "manager", "admin"]:
                user_id = str(uuid.uuid4())
                username = f"proptest_{role}_{user_id[:6]}"
                self._create_user_direct(mysql_pool, user_id, username, role)
                users_to_cleanup.append(user_id)

            # Test USER
            user = repo.get_user_by_id(users_to_cleanup[0])
            assert user is not None
            assert user.is_manager_or_above is False
            assert user.can_view_all_jobs is False
            assert user.can_manage_users is False

            # Test MANAGER
            manager = repo.get_user_by_id(users_to_cleanup[1])
            assert manager is not None
            assert manager.is_manager_or_above is True
            assert manager.can_view_all_jobs is True
            assert manager.can_manage_users is False

            # Test ADMIN
            admin = repo.get_user_by_id(users_to_cleanup[2])
            assert admin is not None
            assert admin.is_manager_or_above is True
            assert admin.can_view_all_jobs is True
            assert admin.can_manage_users is True

        finally:
            for user_id in users_to_cleanup:
                self._cleanup_user(mysql_pool, user_id)
