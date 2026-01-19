"""Integration tests for permissions and User model integration.

Phase 4: Validates that the User model correctly integrates with the
permissions system (RBAC).
"""

from __future__ import annotations

"""HCA Layer: tests."""

from datetime import UTC, datetime

import pytest

from pulldb.domain.models import User, UserRole
from pulldb.domain.permissions import (
    can_manage_config,
    can_manage_users,
    can_submit_for_user,
    can_view_all_jobs,
    can_view_job,
)


class TestPermissionsIntegration:
    """Tests for permissions integration with User model."""

    @pytest.fixture
    def admin_user(self) -> User:
        """Create an admin user."""
        return User(
            user_id="admin-1",
            username="admin",
            user_code="admin",
            is_admin=True,
            role=UserRole.ADMIN,
            created_at=datetime.now(UTC),
        )

    @pytest.fixture
    def manager_user(self) -> User:
        """Create a manager user."""
        return User(
            user_id="manager-1",
            username="manager",
            user_code="manage",
            is_admin=False,
            role=UserRole.MANAGER,
            created_at=datetime.now(UTC),
        )

    @pytest.fixture
    def regular_user(self) -> User:
        """Create a regular user."""
        return User(
            user_id="user-1",
            username="user",
            user_code="user",
            is_admin=False,
            role=UserRole.USER,
            created_at=datetime.now(UTC),
        )

    @pytest.fixture
    def disabled_user(self) -> User:
        """Create a disabled user."""
        return User(
            user_id="disabled-1",
            username="disabled",
            user_code="disabl",
            is_admin=False,
            role=UserRole.USER,
            created_at=datetime.now(UTC),
            disabled_at=datetime.now(UTC),
        )

    def test_is_admin_true_gives_admin_permissions(self, admin_user: User) -> None:
        """User with is_admin=True should have admin permissions."""
        assert can_manage_users(admin_user)
        assert can_manage_config(admin_user)
        assert can_view_all_jobs(admin_user)
        assert can_submit_for_user(admin_user, "other_user")

    def test_role_admin_gives_admin_permissions(self, admin_user: User) -> None:
        """User with role=ADMIN should have admin permissions."""
        # Even if is_admin was False (though model enforces consistency usually)
        # permissions module checks role OR is_admin
        user = User(
            user_id="admin-2",
            username="admin2",
            user_code="admin2",
            is_admin=False,  # Explicitly false to test role check
            role=UserRole.ADMIN,
            created_at=datetime.now(UTC),
        )
        assert can_manage_users(user)
        assert can_manage_config(user)

    def test_role_manager_permissions(self, manager_user: User) -> None:
        """User with role=MANAGER should have manager permissions."""
        # Managers can manage users (they create managed users)
        assert can_manage_users(manager_user)
        assert can_view_all_jobs(manager_user)
        # Managers cannot manage config
        assert not can_manage_config(manager_user)

    def test_role_user_permissions(self, regular_user: User) -> None:
        """User with role=USER should have limited permissions."""
        assert not can_manage_users(regular_user)
        assert not can_manage_config(regular_user)
        assert not can_view_all_jobs(regular_user)

        # Can view own jobs
        assert can_view_job(regular_user, regular_user.user_id)
        # Cannot view other's jobs
        assert not can_view_job(regular_user, "other-id")

    def test_disabled_user_permissions(self, disabled_user: User) -> None:
        """Disabled user permissions behavior."""
        # Permissions module is pure RBAC and does not check disabled status.
        # Disabled status is enforced at the API/Auth layer.
        # So a disabled user technically still has the permissions of their role,
        # but they can't login to use them.
        assert not can_manage_users(disabled_user)
        assert can_view_job(disabled_user, disabled_user.user_id)

    def test_can_submit_for_user_logic(
        self, admin_user: User, manager_user: User, regular_user: User
    ) -> None:
        """Test logic for submitting jobs on behalf of others."""
        # Create a target user (not managed by anyone)
        target_user = User(
            user_id="target-user-id",
            username="target",
            user_code="target",
            is_admin=False,
            role=UserRole.USER,
            created_at=datetime.now(UTC),
        )
        # Create a user managed by the manager
        managed_user = User(
            user_id="managed-user-id",
            username="managed",
            user_code="manage",
            is_admin=False,
            role=UserRole.USER,
            created_at=datetime.now(UTC),
            manager_id="manager-1",  # Managed by manager_user
        )

        # Admin can submit for anyone
        assert can_submit_for_user(admin_user, target_user)

        # Manager can submit for users they manage
        assert can_submit_for_user(manager_user, managed_user)
        # Manager cannot submit for unmanaged users
        assert not can_submit_for_user(manager_user, target_user)
        # Manager can submit for themselves
        assert can_submit_for_user(manager_user, manager_user)

        # Regular user can only submit for themselves
        assert can_submit_for_user(regular_user, regular_user)
        assert not can_submit_for_user(regular_user, target_user)
