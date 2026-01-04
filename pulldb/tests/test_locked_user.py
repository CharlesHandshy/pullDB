"""Tests for locked user functionality.

Tests that locked users cannot be modified through repository methods
and cannot authenticate via web or API.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pulldb.domain.errors import LockedUserError
from pulldb.domain.models import User, UserRole
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedAuthRepository,
    SimulatedUserRepository,
)
from pulldb.simulation.core.state import reset_simulation


@pytest.fixture(autouse=True)
def clean_state():
    """Reset simulation state before each test."""
    reset_simulation()
    yield
    reset_simulation()


@pytest.fixture
def user_repo() -> SimulatedUserRepository:
    """Create a simulated user repository."""
    return SimulatedUserRepository()


@pytest.fixture
def auth_repo() -> SimulatedAuthRepository:
    """Create a simulated auth repository."""
    return SimulatedAuthRepository()


@pytest.fixture
def locked_user(user_repo: SimulatedUserRepository) -> User:
    """Create a locked user for testing."""
    from dataclasses import replace
    from pulldb.simulation.core.state import get_simulation_state
    
    # Create a regular user first
    user = user_repo.create_user("locked_test", "LCKTST")
    
    # Lock them by setting locked_at
    state = get_simulation_state()
    with state.lock:
        locked = replace(user, locked_at=datetime.now(UTC))
        state.users[user.user_id] = locked
        if user.user_code in state.users_by_code:
            state.users_by_code[user.user_code] = locked
    
    return locked


@pytest.fixture
def unlocked_user(user_repo: SimulatedUserRepository) -> User:
    """Create an unlocked user for testing."""
    return user_repo.create_user("unlocked_test", "UNLKTST")


class TestLockedUserError:
    """Tests for LockedUserError exception."""

    def test_locked_user_error_message(self) -> None:
        """LockedUserError includes username and action."""
        err = LockedUserError("testuser", "modify")
        assert "testuser" in str(err)
        assert "modify" in str(err)

    def test_locked_user_error_attributes(self) -> None:
        """LockedUserError stores username and action attributes."""
        err = LockedUserError("testuser", "delete")
        assert err.username == "testuser"
        assert err.action == "delete"


class TestUserModelLockedProperty:
    """Tests for User.locked property."""

    def test_user_locked_when_locked_at_set(self) -> None:
        """User.locked returns True when locked_at is set."""
        user = User(
            user_id="test-id",
            username="test",
            user_code="TSTCD",
            is_admin=False,
            role=UserRole.USER,
            created_at=datetime.now(UTC),
            locked_at=datetime.now(UTC),
        )
        assert user.locked is True

    def test_user_not_locked_when_locked_at_none(self) -> None:
        """User.locked returns False when locked_at is None."""
        user = User(
            user_id="test-id",
            username="test",
            user_code="TSTCD",
            is_admin=False,
            role=UserRole.USER,
            created_at=datetime.now(UTC),
            locked_at=None,
        )
        assert user.locked is False


class TestServiceRole:
    """Tests for SERVICE role permissions."""

    def test_service_role_value(self) -> None:
        """SERVICE role has value 'service'."""
        assert UserRole.SERVICE.value == "service"

    def test_service_role_is_manager_or_above(self) -> None:
        """SERVICE role is considered manager-or-above."""
        user = User(
            user_id="test-id",
            username="pulldb_service",
            user_code="SBCACC",
            is_admin=True,
            role=UserRole.SERVICE,
            created_at=datetime.now(UTC),
        )
        assert user.is_manager_or_above is True

    def test_service_role_can_view_all_jobs(self) -> None:
        """SERVICE role can view all jobs."""
        user = User(
            user_id="test-id",
            username="pulldb_service",
            user_code="SBCACC",
            is_admin=True,
            role=UserRole.SERVICE,
            created_at=datetime.now(UTC),
        )
        assert user.can_view_all_jobs is True

    def test_service_role_can_create_users(self) -> None:
        """SERVICE role can create users."""
        user = User(
            user_id="test-id",
            username="pulldb_service",
            user_code="SBCACC",
            is_admin=True,
            role=UserRole.SERVICE,
            created_at=datetime.now(UTC),
        )
        assert user.can_create_users is True


class TestSimulatedUserRepositoryLockedGuards:
    """Tests for locked user guards in SimulatedUserRepository."""

    def test_enable_user_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """enable_user raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.enable_user(locked_user.username)
        assert exc_info.value.username == locked_user.username
        assert "enable" in exc_info.value.action

    def test_disable_user_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """disable_user raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.disable_user(locked_user.username)
        assert exc_info.value.username == locked_user.username
        assert "disable" in exc_info.value.action

    def test_enable_user_by_id_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """enable_user_by_id raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.enable_user_by_id(locked_user.user_id)
        assert exc_info.value.username == locked_user.username

    def test_disable_user_by_id_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """disable_user_by_id raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.disable_user_by_id(locked_user.user_id)
        assert exc_info.value.username == locked_user.username

    def test_set_user_manager_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """set_user_manager raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.set_user_manager(locked_user.user_id, None)
        assert exc_info.value.username == locked_user.username

    def test_update_user_role_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """update_user_role raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.update_user_role(locked_user.user_id, UserRole.ADMIN)
        assert exc_info.value.username == locked_user.username

    def test_delete_user_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """delete_user raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.delete_user(locked_user.user_id)
        assert exc_info.value.username == locked_user.username

    def test_update_user_max_active_jobs_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """update_user_max_active_jobs raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.update_user_max_active_jobs(locked_user.user_id, 10)
        assert exc_info.value.username == locked_user.username

    def test_bulk_disable_users_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User, unlocked_user: User
    ) -> None:
        """bulk_disable_users raises LockedUserError if any user is locked."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.bulk_disable_users([unlocked_user.user_id, locked_user.user_id])
        assert exc_info.value.username == locked_user.username

    def test_bulk_enable_users_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User, unlocked_user: User
    ) -> None:
        """bulk_enable_users raises LockedUserError if any user is locked."""
        # First disable the unlocked user
        user_repo.disable_user(unlocked_user.username)
        
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.bulk_enable_users([unlocked_user.user_id, locked_user.user_id])
        assert exc_info.value.username == locked_user.username

    def test_bulk_reassign_users_raises_for_locked(
        self, user_repo: SimulatedUserRepository, locked_user: User, unlocked_user: User
    ) -> None:
        """bulk_reassign_users raises LockedUserError if any user is locked."""
        with pytest.raises(LockedUserError) as exc_info:
            user_repo.bulk_reassign_users([unlocked_user.user_id, locked_user.user_id], None)
        assert exc_info.value.username == locked_user.username


class TestSimulatedUserRepositoryUnlockedOperations:
    """Tests that unlocked users can still be modified."""

    def test_enable_user_succeeds_for_unlocked(
        self, user_repo: SimulatedUserRepository, unlocked_user: User
    ) -> None:
        """enable_user works for unlocked users."""
        user_repo.disable_user(unlocked_user.username)
        user_repo.enable_user(unlocked_user.username)  # Should not raise
        user = user_repo.get_user_by_username(unlocked_user.username)
        assert user is not None
        assert user.disabled_at is None

    def test_disable_user_succeeds_for_unlocked(
        self, user_repo: SimulatedUserRepository, unlocked_user: User
    ) -> None:
        """disable_user works for unlocked users."""
        user_repo.disable_user(unlocked_user.username)  # Should not raise
        user = user_repo.get_user_by_username(unlocked_user.username)
        assert user is not None
        assert user.disabled_at is not None

    def test_update_user_role_succeeds_for_unlocked(
        self, user_repo: SimulatedUserRepository, unlocked_user: User
    ) -> None:
        """update_user_role works for unlocked users."""
        user_repo.update_user_role(unlocked_user.user_id, UserRole.MANAGER)
        user = user_repo.get_user_by_id(unlocked_user.user_id)
        assert user is not None
        assert user.role == UserRole.MANAGER


class TestSimulatedAuthRepositoryLockedGuards:
    """Tests for locked user guards in SimulatedAuthRepository."""

    def test_set_password_hash_raises_for_locked(
        self, auth_repo: SimulatedAuthRepository, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """set_password_hash raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            auth_repo.set_password_hash(locked_user.user_id, "hashed_password")
        assert exc_info.value.username == locked_user.username

    def test_mark_password_reset_raises_for_locked(
        self, auth_repo: SimulatedAuthRepository, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """mark_password_reset raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            auth_repo.mark_password_reset(locked_user.user_id)
        assert exc_info.value.username == locked_user.username

    def test_clear_password_reset_raises_for_locked(
        self, auth_repo: SimulatedAuthRepository, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """clear_password_reset raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            auth_repo.clear_password_reset(locked_user.user_id)
        assert exc_info.value.username == locked_user.username

    def test_set_user_hosts_raises_for_locked(
        self, auth_repo: SimulatedAuthRepository, user_repo: SimulatedUserRepository, locked_user: User
    ) -> None:
        """set_user_hosts raises LockedUserError for locked user."""
        with pytest.raises(LockedUserError) as exc_info:
            auth_repo.set_user_hosts(locked_user.user_id, ["host-1"], "host-1")
        assert exc_info.value.username == locked_user.username


class TestSimulatedAuthRepositoryUnlockedOperations:
    """Tests that unlocked users auth operations still work."""

    def test_set_password_hash_succeeds_for_unlocked(
        self, auth_repo: SimulatedAuthRepository, unlocked_user: User
    ) -> None:
        """set_password_hash works for unlocked users."""
        auth_repo.set_password_hash(unlocked_user.user_id, "hashed_password")
        stored_hash = auth_repo.get_password_hash(unlocked_user.user_id)
        assert stored_hash == "hashed_password"

    def test_mark_password_reset_succeeds_for_unlocked(
        self, auth_repo: SimulatedAuthRepository, unlocked_user: User
    ) -> None:
        """mark_password_reset works for unlocked users."""
        auth_repo.mark_password_reset(unlocked_user.user_id)
        assert auth_repo.is_password_reset_required(unlocked_user.user_id) is True

    def test_set_user_hosts_succeeds_for_unlocked(
        self, auth_repo: SimulatedAuthRepository, unlocked_user: User
    ) -> None:
        """set_user_hosts works for unlocked users."""
        auth_repo.set_user_hosts(unlocked_user.user_id, ["host-1"], "host-1")
        # No exception means success
