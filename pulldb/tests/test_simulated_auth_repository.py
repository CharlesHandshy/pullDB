"""Unit tests for SimulatedAuthRepository.

Phase 4: Validates the authentication repository logic in isolation.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from pulldb.simulation import (
    SimulatedAuthRepository,
    SimulatedUserRepository,
    reset_simulation,
)
from pulldb.simulation.core.state import get_simulation_state


@pytest.fixture(autouse=True)
def simulation_mode() -> Generator[None, None, None]:
    """Force simulation mode for these tests."""
    with mock.patch.dict(os.environ, {"PULLDB_MODE": "SIMULATION"}):
        reset_simulation()
        yield


class TestSimulatedAuthRepository:
    """Tests for SimulatedAuthRepository."""

    def test_create_session(self) -> None:
        """Should create a valid session for a user."""
        user_repo = SimulatedUserRepository()
        auth_repo = SimulatedAuthRepository()

        user = user_repo.create_user("testuser", "test")

        session_id, token = auth_repo.create_session(user.user_id)
        assert session_id is not None
        assert token is not None

        # Verify session exists
        user_id = auth_repo.validate_session(token)
        assert user_id == user.user_id

    def test_validate_invalid_session(self) -> None:
        """Should return None for invalid session token."""
        auth_repo = SimulatedAuthRepository()
        assert auth_repo.validate_session("invalid-token") is None

    def test_session_expiry(self) -> None:
        """Should not return user ID for expired session."""
        user_repo = SimulatedUserRepository()
        auth_repo = SimulatedAuthRepository()

        user = user_repo.create_user("testuser", "test")
        _, token = auth_repo.create_session(user.user_id)

        # Manually expire the session in state
        state = get_simulation_state()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with state.lock:
            session = state.sessions[token_hash]
            session["expires_at"] = datetime.now(UTC) - timedelta(minutes=1)

        assert auth_repo.validate_session(token) is None

    def test_delete_session(self) -> None:
        """Should remove session when deleted."""
        user_repo = SimulatedUserRepository()
        auth_repo = SimulatedAuthRepository()

        user = user_repo.create_user("testuser", "test")
        _, token = auth_repo.create_session(user.user_id)

        auth_repo.delete_session(token)
        assert auth_repo.validate_session(token) is None

    def test_delete_user_sessions(self) -> None:
        """Should remove all sessions for a user."""
        user_repo = SimulatedUserRepository()
        auth_repo = SimulatedAuthRepository()

        user = user_repo.create_user("testuser", "test")

        # Create multiple sessions
        _, token1 = auth_repo.create_session(user.user_id)
        _, token2 = auth_repo.create_session(user.user_id)

        assert auth_repo.validate_session(token1) == user.user_id
        assert auth_repo.validate_session(token2) == user.user_id

        count = auth_repo.delete_user_sessions(user.user_id)
        assert count == 2

        assert auth_repo.validate_session(token1) is None
        assert auth_repo.validate_session(token2) is None
