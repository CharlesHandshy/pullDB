"""Unit tests for Domain Models.

Phase 4: Validates UserRole enum and User model updates.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from pulldb.domain.models import User, UserDetail, UserRole


class TestUserRole:
    """Tests for UserRole enum."""

    def test_userrole_values(self) -> None:
        """Enum should have correct values."""
        assert UserRole.USER.value == "user"
        assert UserRole.MANAGER.value == "manager"
        assert UserRole.ADMIN.value == "admin"

    def test_userrole_from_string(self) -> None:
        """Should convert string to enum."""
        assert UserRole("user") == UserRole.USER
        assert UserRole("manager") == UserRole.MANAGER
        assert UserRole("admin") == UserRole.ADMIN

    def test_userrole_invalid(self) -> None:
        """Should raise ValueError for invalid role."""
        with pytest.raises(ValueError):
            UserRole("invalid")


class TestUserModel:
    """Tests for User model."""

    def test_user_requires_role(self) -> None:
        """User should require role field."""
        # Since User is a dataclass with no default for role,
        # missing it should raise TypeError
        with pytest.raises(TypeError):
            User(  # type: ignore
                user_id="123",
                username="test",
                user_code="test",
                is_admin=False,
                # role is missing
                created_at=datetime.now(UTC),
                disabled_at=None,
            )

    def test_user_role_in_dict(self) -> None:
        """to_dict should include role."""
        user = User(
            user_id="123",
            username="test",
            user_code="test",
            is_admin=False,
            role=UserRole.MANAGER,
            created_at=datetime.now(UTC),
            disabled_at=None,
        )
        data = asdict(user)
        assert data["role"] == UserRole.MANAGER
        # It might be serialized as enum object, not string.
        assert data["role"].value == "manager"

    def test_user_detail_includes_role(self) -> None:
        """UserDetail should include role via nested user."""
        user = User(
            user_id="123",
            username="test",
            user_code="test",
            is_admin=False,
            role=UserRole.ADMIN,
            created_at=datetime.now(UTC),
            disabled_at=None,
        )
        detail = UserDetail(
            user=user,
            total_jobs=10,
            complete_jobs=8,
            failed_jobs=0,
            active_jobs=2,
        )
        assert detail.user.role == UserRole.ADMIN
