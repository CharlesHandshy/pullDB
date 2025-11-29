"""Tests for UserRole enum and User model role field.

Phase 4: Validates role enum values and User model integration.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pulldb.domain.models import User, UserRole


class TestUserRoleEnum:
    """Tests for UserRole enum values and behavior."""

    def test_userrole_has_three_values(self) -> None:
        """UserRole enum has exactly three values."""
        assert len(UserRole) == 3

    def test_userrole_user_value(self) -> None:
        """USER role has value 'user'."""
        assert UserRole.USER.value == "user"

    def test_userrole_manager_value(self) -> None:
        """MANAGER role has value 'manager'."""
        assert UserRole.MANAGER.value == "manager"

    def test_userrole_admin_value(self) -> None:
        """ADMIN role has value 'admin'."""
        assert UserRole.ADMIN.value == "admin"

    def test_userrole_from_string_user(self) -> None:
        """UserRole can be created from 'user' string."""
        role = UserRole("user")
        assert role == UserRole.USER

    def test_userrole_from_string_manager(self) -> None:
        """UserRole can be created from 'manager' string."""
        role = UserRole("manager")
        assert role == UserRole.MANAGER

    def test_userrole_from_string_admin(self) -> None:
        """UserRole can be created from 'admin' string."""
        role = UserRole("admin")
        assert role == UserRole.ADMIN

    def test_userrole_ordering(self) -> None:
        """UserRole enum ordering matches privilege level."""
        roles = list(UserRole)
        assert roles[0] == UserRole.USER
        assert roles[1] == UserRole.MANAGER
        assert roles[2] == UserRole.ADMIN


class TestUserModelRole:
    """Tests for User model role field."""

    def test_user_requires_role(self) -> None:
        """User model requires explicit role (no default)."""
        # Role is required - tests that we can't create user without it
        with pytest.raises(TypeError, match="role"):
            User(  # type: ignore[call-arg]
                user_id="test-123",
                username="testuser",
                user_code="testus",
                is_admin=False,
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
            )

    def test_user_can_set_role(self) -> None:
        """User model accepts explicit role."""
        user = User(
            user_id="test-123",
            username="testuser",
            user_code="testus",
            is_admin=False,
            role=UserRole.MANAGER,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert user.role == UserRole.MANAGER

    def test_user_admin_role(self) -> None:
        """User model accepts ADMIN role."""
        user = User(
            user_id="test-123",
            username="testuser",
            user_code="testus",
            is_admin=True,
            role=UserRole.ADMIN,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert user.role == UserRole.ADMIN
        assert user.is_admin is True

    def test_user_role_from_string(self) -> None:
        """User can be created with role as string value."""
        # This tests that the model accepts enum values
        user = User(
            user_id="test-123",
            username="testuser",
            user_code="testus",
            is_admin=False,
            role=UserRole("manager"),
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert user.role == UserRole.MANAGER

    def test_user_role_comparison(self) -> None:
        """User role can be compared with UserRole enum."""
        user = User(
            user_id="test-123",
            username="testuser",
            user_code="testus",
            is_admin=False,
            role=UserRole.ADMIN,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert user.role == UserRole.ADMIN
        assert user.role != UserRole.USER
        assert user.role != UserRole.MANAGER
