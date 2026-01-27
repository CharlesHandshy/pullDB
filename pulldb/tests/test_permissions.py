"""Tests for RBAC permission checks.

Phase 4: Verifies role-based access control logic.
"""

from __future__ import annotations

"""HCA Layer: tests."""

from datetime import UTC, datetime

import pytest

from pulldb.domain.models import User, UserRole
from pulldb.domain.permissions import (
    can_cancel_job,
    can_manage_config,
    can_manage_users,
    can_submit_for_user,
    can_view_all_jobs,
    can_view_job,
    require_role,
)


def _make_user(
    role: UserRole = UserRole.USER,
    user_id: str = "user-123",
    username: str = "testuser",
) -> User:
    """Create a test user with specified role."""
    return User(
        user_id=user_id,
        username=username,
        user_code="testus",
        role=role,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


class TestCanViewJob:
    """Tests for can_view_job permission."""

    def test_admin_can_view_any_job(self) -> None:
        """Admin can view jobs owned by anyone."""
        admin = _make_user(UserRole.ADMIN)
        assert can_view_job(admin, "other-user-id") is True

    def test_manager_can_view_any_job(self) -> None:
        """Manager can view jobs owned by anyone."""
        manager = _make_user(UserRole.MANAGER)
        assert can_view_job(manager, "other-user-id") is True

    def test_user_can_view_own_job(self) -> None:
        """User can view their own jobs."""
        user = _make_user(UserRole.USER, user_id="user-123")
        assert can_view_job(user, "user-123") is True

    def test_user_cannot_view_other_job(self) -> None:
        """User cannot view jobs owned by others."""
        user = _make_user(UserRole.USER, user_id="user-123")
        assert can_view_job(user, "other-user-id") is False


class TestCanCancelJob:
    """Tests for can_cancel_job permission."""

    def test_admin_can_cancel_any_job(self) -> None:
        """Admin can cancel any job."""
        admin = _make_user(UserRole.ADMIN)
        assert can_cancel_job(admin, "other-user-id") is True

    def test_manager_can_cancel_managed_user_job(self) -> None:
        """Manager can cancel jobs owned by users they manage."""
        manager = _make_user(UserRole.MANAGER, user_id="manager-123")
        # Job owner is managed by this manager
        assert can_cancel_job(manager, "managed-user-id", job_owner_manager_id="manager-123") is True

    def test_manager_cannot_cancel_unmanaged_user_job(self) -> None:
        """Manager cannot cancel jobs owned by users they don't manage."""
        manager = _make_user(UserRole.MANAGER, user_id="manager-123")
        # Job owner is not managed by this manager
        assert can_cancel_job(manager, "other-user-id", job_owner_manager_id=None) is False
        assert can_cancel_job(manager, "other-user-id", job_owner_manager_id="different-manager") is False

    def test_user_can_cancel_own_job(self) -> None:
        """User can cancel their own job."""
        user = _make_user(UserRole.USER, user_id="user-123")
        assert can_cancel_job(user, "user-123") is True

    def test_user_cannot_cancel_other_job(self) -> None:
        """User cannot cancel jobs owned by others."""
        user = _make_user(UserRole.USER, user_id="user-123")
        assert can_cancel_job(user, "other-user-id") is False


class TestCanSubmitForUser:
    """Tests for can_submit_for_user permission."""

    def test_admin_can_submit_for_anyone(self) -> None:
        """Admin can submit jobs for any user."""
        admin = _make_user(UserRole.ADMIN, user_id="admin-123")
        target = _make_user(UserRole.USER, user_id="other-user-id", username="other")
        assert can_submit_for_user(admin, target) is True

    def test_manager_can_submit_for_managed_user(self) -> None:
        """Manager can submit jobs for users they manage."""
        manager = _make_user(UserRole.MANAGER, user_id="manager-123")
        # Create a user managed by this manager
        managed_user = User(
            user_id="managed-user-id",
            username="managed",
            user_code="manage",
            role=UserRole.USER,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            manager_id="manager-123",  # Managed by the manager
        )
        assert can_submit_for_user(manager, managed_user) is True

    def test_manager_can_submit_for_self(self) -> None:
        """Manager can submit jobs for themselves."""
        manager = _make_user(UserRole.MANAGER, user_id="manager-123")
        assert can_submit_for_user(manager, manager) is True

    def test_manager_cannot_submit_for_unmanaged_user(self) -> None:
        """Manager cannot submit for users they don't manage."""
        manager = _make_user(UserRole.MANAGER, user_id="manager-123")
        other_user = _make_user(UserRole.USER, user_id="other-user-id", username="other")
        assert can_submit_for_user(manager, other_user) is False

    def test_user_can_submit_for_self(self) -> None:
        """User can submit jobs for themselves."""
        user = _make_user(UserRole.USER, user_id="user-123")
        assert can_submit_for_user(user, user) is True

    def test_user_cannot_submit_for_others(self) -> None:
        """User cannot submit jobs for others."""
        user = _make_user(UserRole.USER, user_id="user-123")
        other = _make_user(UserRole.USER, user_id="other-user-id", username="other")
        assert can_submit_for_user(user, other) is False


class TestCanManageUsers:
    """Tests for can_manage_users permission."""

    def test_admin_can_manage_users(self) -> None:
        """Admin can manage users."""
        admin = _make_user(UserRole.ADMIN)
        assert can_manage_users(admin) is True

    def test_manager_can_manage_users(self) -> None:
        """Manager can manage users (creates managed users)."""
        manager = _make_user(UserRole.MANAGER)
        assert can_manage_users(manager) is True

    def test_user_cannot_manage_users(self) -> None:
        """Regular user cannot manage users."""
        user = _make_user(UserRole.USER)
        assert can_manage_users(user) is False


class TestCanManageConfig:
    """Tests for can_manage_config permission."""

    def test_admin_can_manage_config(self) -> None:
        """Admin can manage config."""
        admin = _make_user(UserRole.ADMIN)
        assert can_manage_config(admin) is True

    def test_manager_cannot_manage_config(self) -> None:
        """Manager cannot manage config."""
        manager = _make_user(UserRole.MANAGER)
        assert can_manage_config(manager) is False

    def test_user_cannot_manage_config(self) -> None:
        """Regular user cannot manage config."""
        user = _make_user(UserRole.USER)
        assert can_manage_config(user) is False


class TestCanViewAllJobs:
    """Tests for can_view_all_jobs permission."""

    def test_admin_can_view_all_jobs(self) -> None:
        """Admin can view all jobs."""
        admin = _make_user(UserRole.ADMIN)
        assert can_view_all_jobs(admin) is True

    def test_manager_can_view_all_jobs(self) -> None:
        """Manager can view all jobs."""
        manager = _make_user(UserRole.MANAGER)
        assert can_view_all_jobs(manager) is True

    def test_user_cannot_view_all_jobs(self) -> None:
        """Regular user cannot view all jobs."""
        user = _make_user(UserRole.USER)
        assert can_view_all_jobs(user) is False


class TestRequireRole:
    """Tests for require_role helper."""

    def test_require_role_passes_for_matching_role(self) -> None:
        """Should not raise when user has required role."""
        admin = _make_user(UserRole.ADMIN)
        require_role(admin, UserRole.ADMIN)  # Should not raise

    def test_require_role_passes_for_any_matching(self) -> None:
        """Should not raise when user has any of required roles."""
        manager = _make_user(UserRole.MANAGER)
        require_role(manager, UserRole.MANAGER, UserRole.ADMIN)  # Should not raise

    def test_require_role_raises_for_missing_role(self) -> None:
        """Should raise PermissionError when user lacks required role."""
        user = _make_user(UserRole.USER, username="testuser")
        with pytest.raises(PermissionError) as exc_info:
            require_role(user, UserRole.ADMIN)
        assert "admin" in str(exc_info.value)
        assert "testuser" in str(exc_info.value)

    def test_require_role_raises_for_all_missing(self) -> None:
        """Should raise when user lacks all required roles."""
        user = _make_user(UserRole.USER)
        with pytest.raises(PermissionError) as exc_info:
            require_role(user, UserRole.MANAGER, UserRole.ADMIN)
        assert "manager, admin" in str(exc_info.value)
