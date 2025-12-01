"""Pytest fixtures for Playwright end-to-end tests.

This module provides fixtures for running the FastAPI web app in a test server
and driving it with Playwright for browser-based testing.
"""

from __future__ import annotations

import secrets
import socket
import threading
import time
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Generator
from unittest.mock import MagicMock

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import Page

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext


def find_free_port() -> int:
    """Find an available port on localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


# =============================================================================
# Mock Data
# =============================================================================


def create_mock_user(
    user_id: int = 1,
    username: str = "testuser",
    role: str = "developer",
    disabled: bool = False,
) -> MagicMock:
    """Create a mock User object."""
    user = MagicMock()
    user.user_id = user_id
    user.username = username
    user.role = role
    user.disabled_at = "2024-01-01" if disabled else None
    return user


def create_mock_job(
    job_id: str = "job-001",
    target: str = "dev-db",
    status: str = "pending",
    owner_user_id: int = 1,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_detail: str | None = None,
    worker_id: str | None = None,
) -> MagicMock:
    """Create a mock Job object."""
    job = MagicMock()
    job.job_id = job_id
    job.target = target
    job.status = status
    job.owner_user_id = owner_user_id
    job.created_at = created_at or datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    job.started_at = started_at
    job.finished_at = finished_at
    job.submitted_at = job.created_at  # alias for template compatibility
    job.error_detail = error_detail
    job.worker_id = worker_id
    return job


def create_mock_event(
    event_id: int = 1,
    job_id: str = "job-001",
    event_type: str = "created",
    message: str = "Job created",
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock JobEvent object."""
    event = MagicMock()
    event.event_id = event_id
    event.job_id = job_id
    event.event_type = event_type
    event.message = message
    event.created_at = created_at or datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    return event


# =============================================================================
# Mock Repositories
# =============================================================================


class MockUserRepo:
    """Mock user repository for testing."""

    def __init__(self) -> None:
        self.users = {
            "testuser": create_mock_user(1, "testuser", "developer"),
            "admin": create_mock_user(2, "admin", "admin"),
            "disabled": create_mock_user(3, "disabled", "developer", disabled=True),
        }

    def get_user_by_username(self, username: str) -> MagicMock | None:
        return self.users.get(username)

    def get_user_by_id(self, user_id: int) -> MagicMock | None:
        for user in self.users.values():
            if user.user_id == user_id:
                return user
        return None


class MockAuthRepo:
    """Mock auth repository for testing."""

    def __init__(self) -> None:
        self.sessions: dict[str, int] = {}
        # password = "testpass123" - generated with hash_password()
        self.password_hashes = {
            1: "$2b$12$mfPL.PHDhJKCXPV4OZawlO8lNwTjarJ8CGzR8s4A9K9vuAR2csbTe",
            2: "$2b$12$mfPL.PHDhJKCXPV4OZawlO8lNwTjarJ8CGzR8s4A9K9vuAR2csbTe",
            3: "$2b$12$mfPL.PHDhJKCXPV4OZawlO8lNwTjarJ8CGzR8s4A9K9vuAR2csbTe",
        }

    def get_password_hash(self, user_id: int) -> str | None:
        return self.password_hashes.get(user_id)

    def validate_session(self, token: str) -> int | None:
        return self.sessions.get(token)

    def create_session(
        self,
        user_id: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[int, str]:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = user_id
        return (1, token)

    def invalidate_session_by_token(self, token: str) -> bool:
        if token in self.sessions:
            del self.sessions[token]
            return True
        return False


class MockJobRepo:
    """Mock job repository for testing."""

    def __init__(self) -> None:
        self.jobs = [
            create_mock_job("job-001", "dev-db", "pending", 1),
            create_mock_job(
                "job-002", "staging-db", "running", 1,
                started_at=datetime(2024, 1, 15, 10, 5, 0, tzinfo=UTC),
                worker_id="worker-1",
            ),
            create_mock_job(
                "job-003", "prod-copy", "completed", 2,
                started_at=datetime(2024, 1, 15, 9, 0, 0, tzinfo=UTC),
                finished_at=datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC),
                worker_id="worker-2",
            ),
            create_mock_job(
                "job-004", "test-db", "failed", 1,
                started_at=datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC),
                finished_at=datetime(2024, 1, 15, 8, 15, 0, tzinfo=UTC),
                error_detail="Download failed: connection timeout",
                worker_id="worker-1",
            ),
        ]
        self.events = {
            "job-001": [
                create_mock_event(1, "job-001", "created", "Job created"),
            ],
            "job-002": [
                create_mock_event(2, "job-002", "created", "Job created"),
                create_mock_event(3, "job-002", "claimed", "Claimed by worker-1"),
                create_mock_event(4, "job-002", "downloading", "Downloading..."),
            ],
            "job-003": [
                create_mock_event(5, "job-003", "created", "Job created"),
                create_mock_event(6, "job-003", "completed", "Restore complete"),
            ],
            "job-004": [
                create_mock_event(7, "job-004", "created", "Job created"),
                create_mock_event(8, "job-004", "failed", "Download timeout"),
            ],
        }

    def get_job_by_id(self, job_id: str) -> MagicMock | None:
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        return None

    def get_active_jobs(self) -> list[MagicMock]:
        return [j for j in self.jobs if j.status in ("pending", "running")]

    def get_recent_jobs(
        self,
        limit: int = 50,
        statuses: list[str] | None = None,
    ) -> list[MagicMock]:
        jobs = self.jobs
        if statuses:
            jobs = [j for j in jobs if j.status in statuses]
        return jobs[:limit]

    def get_job_events(
        self,
        job_id: str,
        since_id: int | None = None,
    ) -> list[MagicMock]:
        events = self.events.get(job_id, [])
        if since_id:
            events = [e for e in events if e.event_id > since_id]
        return events


# =============================================================================
# Mock API State
# =============================================================================


class MockAPIState:
    """Mock API state with all repositories."""

    def __init__(self) -> None:
        self.user_repo = MockUserRepo()
        self.auth_repo = MockAuthRepo()
        self.job_repo = MockJobRepo()


# =============================================================================
# Test Application
# =============================================================================


def create_test_app() -> FastAPI:
    """Create a FastAPI app configured for testing."""
    from pulldb.web.routes import router as web_router

    app = FastAPI(title="pullDB Test")

    # Store mock state
    app.state.api_state = MockAPIState()

    # Include web router
    app.include_router(web_router)

    return app


def _mock_get_api_state() -> MockAPIState:
    """Override for get_api_state that returns our mock."""
    # This gets the app from the thread-local storage
    import pulldb.api.main as api_main

    return api_main._test_api_state  # type: ignore[attr-defined]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Configure browser context for tests."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def test_server() -> Generator[str, None, None]:
    """Start a test server with the web app."""
    import pulldb.api.main as api_main

    # Create test app and store state globally for the mock
    app = create_test_app()
    api_main._test_api_state = app.state.api_state  # type: ignore[attr-defined]

    # Patch get_api_state to use our mock
    original_get_api_state = api_main.get_api_state
    api_main.get_api_state = _mock_get_api_state  # type: ignore[assignment]

    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Configure uvicorn
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)

    # Run server in background thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    for _ in range(50):
        try:
            with closing(socket.create_connection(("127.0.0.1", port), timeout=0.1)):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Test server failed to start")

    yield base_url

    # Cleanup
    server.should_exit = True
    api_main.get_api_state = original_get_api_state


@pytest.fixture(scope="session")
def base_url(test_server: str) -> str:
    """Get the base URL of the test server."""
    return test_server


@pytest.fixture
def page(context: "BrowserContext", base_url: str) -> Generator[Page, None, None]:
    """Create a new page for each test."""
    page = context.new_page()
    yield page
    page.close()


@pytest.fixture
def logged_in_page(page: Page, base_url: str) -> Page:
    """Get a page that is already logged in as testuser."""
    # Go to login page
    page.goto(f"{base_url}/web/login")

    # Fill in credentials
    page.fill('input[name="username"]', "testuser")
    page.fill('input[name="password"]', "testpass123")

    # Submit form
    page.click('button[type="submit"]')

    # Wait for redirect to dashboard
    page.wait_for_url(f"{base_url}/web/dashboard")

    return page


@pytest.fixture
def admin_page(page: Page, base_url: str) -> Page:
    """Get a page logged in as admin user."""
    page.goto(f"{base_url}/web/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "testpass123")
    page.click('button[type="submit"]')
    page.wait_for_url(f"{base_url}/web/dashboard")
    return page

