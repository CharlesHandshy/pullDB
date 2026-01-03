"""Integration tests for API authentication integration using Simulation Mode.

Phase 4: Validates that the API service correctly integrates the authentication
components and enforces security controls.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from pulldb.api.main import app, get_api_state
from pulldb.simulation import (
    SimulatedAuthRepository,
    reset_simulation,
)


@pytest.fixture(autouse=True)
def simulation_mode() -> Generator[None, None, None]:
    """Force simulation mode for these tests."""
    with mock.patch.dict(os.environ, {"PULLDB_MODE": "SIMULATION"}):
        reset_simulation()
        # Force re-initialization of API state
        app.state.api_state = None
        yield


@pytest.fixture
def client() -> TestClient:
    """Get TestClient for the app."""
    return TestClient(app)


class TestAPIAuthIntegration:
    """Tests for API authentication integration."""

    def test_api_state_includes_auth_repo(self, client: TestClient) -> None:
        """API state should include auth repository in simulation mode."""
        # Trigger state initialization
        client.get("/api/health")
        
        state = get_api_state()
        assert state.auth_repo is not None
        assert isinstance(state.auth_repo, SimulatedAuthRepository)

    def test_web_router_mounted(self, client: TestClient) -> None:
        """Web router should be mounted and accessible."""
        # Check if routes are registered
        routes = {r.path for r in app.routes}
        assert "/web/login" in routes
        assert "/web/dashboard/" in routes  # Note: trailing slash
        
        # Check if endpoint is reachable
        response = client.get("/web/login")
        assert response.status_code == 200

    def test_login_endpoint_accepts_valid(self, client: TestClient) -> None:
        """Login endpoint should accept valid credentials."""
        # Seed a user first
        from pulldb.auth.password import hash_password
        from pulldb.simulation import SimulatedAuthRepository, SimulatedUserRepository

        user_repo = SimulatedUserRepository()
        user = user_repo.create_user("api_test_user", "apitest")

        auth_repo = SimulatedAuthRepository()
        auth_repo.set_password_hash(user.user_id, hash_password("api_password"))

        response = client.post(
            "/web/login",
            data={
                "username": "api_test_user",
                "password": "api_password",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/web/dashboard/"

    def test_login_endpoint_rejects_invalid(self, client: TestClient) -> None:
        """Login endpoint should reject invalid credentials."""
        # Seed a user first
        from pulldb.auth.password import hash_password
        from pulldb.simulation import SimulatedAuthRepository, SimulatedUserRepository

        user_repo = SimulatedUserRepository()
        user = user_repo.create_user("api_test_user_2", "apitest2")

        auth_repo = SimulatedAuthRepository()
        auth_repo.set_password_hash(user.user_id, hash_password("api_password"))

        response = client.post(
            "/web/login",
            data={
                "username": "api_test_user_2",
                "password": "wrong_password",
            },
        )

        assert response.status_code == 401
        assert "Invalid username or password" in response.text

    def test_session_cookie_set(self, client: TestClient) -> None:
        """Login should set session_token cookie with correct attributes."""
        # Seed a user first
        from pulldb.auth.password import hash_password
        from pulldb.simulation import SimulatedAuthRepository, SimulatedUserRepository

        user_repo = SimulatedUserRepository()
        user = user_repo.create_user("cookie_test_user", "cookiet")

        auth_repo = SimulatedAuthRepository()
        auth_repo.set_password_hash(user.user_id, hash_password("cookie_password"))

        response = client.post(
            "/web/login",
            data={
                "username": "cookie_test_user",
                "password": "cookie_password",
            },
            follow_redirects=False,
        )

        assert "session_token" in response.cookies
        # Note: TestClient doesn't easily expose cookie attributes like HttpOnly
        # but we can verify the cookie is present and has a value
        assert len(response.cookies["session_token"]) > 0

    def test_dashboard_requires_auth(self, client: TestClient) -> None:
        """Dashboard endpoint should require authentication."""
        # Request with trailing slash to hit actual route (not redirect)
        response = client.get("/web/dashboard/", follow_redirects=False)
        
        assert response.status_code == 303
        assert response.headers["location"] == "/web/login"
