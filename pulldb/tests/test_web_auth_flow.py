"""Integration tests for Web UI authentication flow using Simulation Mode.

This test suite validates the full login/logout lifecycle using the
SimulatedAuthRepository we implemented. It replaces the need for manual
browser testing for regression checks.
"""

from __future__ import annotations

import os
from typing import Generator
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from pulldb.api.main import app
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
        # Force re-initialization of API state
        app.state.api_state = None
        yield


@pytest.fixture
def client() -> TestClient:
    """Get TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def test_user() -> dict[str, str]:
    """Create a test user with password in the simulation."""
    username = "auth_test_user"
    password = "secure_password_123"
    
    # Create user in repo
    user_repo = SimulatedUserRepository()
    user = user_repo.create_user(username, "authtest")
    
    # Set password in auth repo
    from pulldb.auth.password import hash_password
    auth_repo = SimulatedAuthRepository()
    auth_repo.set_password_hash(user.user_id, hash_password(password))
    
    return {"username": username, "password": password, "user_id": user.user_id}


class TestWebAuthFlow:
    """Tests for the web authentication flow."""

    def test_login_page_loads(self, client: TestClient) -> None:
        """Login page should load successfully."""
        response = client.get("/web/login")
        assert response.status_code == 200
        assert "Sign in" in response.text
        assert "username" in response.text
        assert "password" in response.text

    def test_login_success(self, client: TestClient, test_user: dict[str, str]) -> None:
        """Valid credentials should log the user in."""
        response = client.post(
            "/web/login",
            data={
                "username": test_user["username"],
                "password": test_user["password"],
            },
            follow_redirects=False,
        )
        
        # Should redirect to dashboard
        assert response.status_code == 303
        assert response.headers["location"] == "/web/dashboard"
        
        # Should set session cookie
        assert "session_token" in response.cookies

    def test_login_failure_bad_password(self, client: TestClient, test_user: dict[str, str]) -> None:
        """Invalid password should show error."""
        response = client.post(
            "/web/login",
            data={
                "username": test_user["username"],
                "password": "wrong_password",
            },
        )
        
        assert response.status_code == 401
        assert "Invalid username or password" in response.text
        assert "session_token" not in response.cookies

    def test_login_failure_unknown_user(self, client: TestClient) -> None:
        """Unknown user should show error."""
        response = client.post(
            "/web/login",
            data={
                "username": "nonexistent_user",
                "password": "any_password",
            },
        )
        
        assert response.status_code == 401
        assert "Invalid username or password" in response.text

    def test_dashboard_requires_auth(self, client: TestClient) -> None:
        """Dashboard should redirect to login if not authenticated."""
        response = client.get("/web/dashboard", follow_redirects=False)
        
        assert response.status_code == 303
        assert response.headers["location"] == "/web/login"

    def test_dashboard_access_with_session(self, client: TestClient, test_user: dict[str, str]) -> None:
        """Dashboard should be accessible with valid session."""
        # Login first
        login_response = client.post(
            "/web/login",
            data={
                "username": test_user["username"],
                "password": test_user["password"],
            },
            follow_redirects=False,
        )
        session_token = login_response.cookies["session_token"]
        
        # Access dashboard
        response = client.get(
            "/web/dashboard",
            cookies={"session_token": session_token},
        )
        
        assert response.status_code == 200
        assert "Dashboard" in response.text
        assert test_user["username"] in response.text

    def test_logout_clears_session(self, client: TestClient, test_user: dict[str, str]) -> None:
        """Logout should invalidate session and clear cookie."""
        # Login first
        login_response = client.post(
            "/web/login",
            data={
                "username": test_user["username"],
                "password": test_user["password"],
            },
            follow_redirects=False,
        )
        session_token = login_response.cookies["session_token"]
        
        # Verify session exists in state
        state = get_simulation_state()
        with state.lock:
            assert len(state.sessions) == 1
        
        # Logout
        response = client.get(
            "/web/logout",
            cookies={"session_token": session_token},
            follow_redirects=False,
        )
        
        # Should redirect to login
        assert response.status_code == 303
        assert response.headers["location"] == "/web/login"
        
        # Cookie should be cleared (expired)
        # Note: TestClient handles cookie clearing by setting max-age=0 or similar
        # We check if the session is gone from the server state
        with state.lock:
            assert len(state.sessions) == 0

    def test_login_redirects_if_already_authenticated(self, client: TestClient, test_user: dict[str, str]) -> None:
        """Login page should redirect to dashboard if already logged in."""
        # Login first
        login_response = client.post(
            "/web/login",
            data={
                "username": test_user["username"],
                "password": test_user["password"],
            },
            follow_redirects=False,
        )
        session_token = login_response.cookies["session_token"]
        
        # Visit login page again
        response = client.get(
            "/web/login",
            cookies={"session_token": session_token},
            follow_redirects=False,
        )
        
        assert response.status_code == 303
        assert response.headers["location"] == "/web/dashboard"
