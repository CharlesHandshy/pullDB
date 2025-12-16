"""Pytest fixtures for Playwright end-to-end tests.

This module provides fixtures for running the FastAPI web app in a test server
and driving it with Playwright for browser-based testing.

Uses the unified pulldb.simulation infrastructure to ensure e2e tests use
the same mock implementations as dev server and PULLDB_MODE=SIMULATION.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Generator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import Page


if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext


# =============================================================================
# Ensure SIMULATION mode is set early
# =============================================================================

# Set before any pulldb imports
os.environ["PULLDB_MODE"] = "SIMULATION"


def find_free_port() -> int:
    """Find an available port on localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


# =============================================================================
# E2E Test API State (Using Simulation Infrastructure)
# =============================================================================


class E2EAPIState:
    """API state for e2e tests using unified simulation infrastructure.

    This mirrors DevAPIState but is optimized for e2e test scenarios.
    Uses pulldb.simulation module to ensure e2e tests use the same
    mock implementations as dev server.
    """

    def __init__(self) -> None:
        from pulldb.api.main import _initialize_simulation_state
        from pulldb.simulation import get_simulation_state, reset_simulation

        # Reset and seed simulation state
        reset_simulation()
        state = get_simulation_state()

        # Seed test data suitable for e2e tests
        self._seed_e2e_data(state)

        # Seed auth credentials for test users
        self._seed_auth_credentials(state)

        # Get APIState from simulation infrastructure
        api_state = _initialize_simulation_state()

        # Expose repos for compatibility
        self.config = api_state.config
        self.job_repo = api_state.job_repo
        self.user_repo = api_state.user_repo
        self.host_repo = api_state.host_repo
        self.settings_repo = api_state.settings_repo
        self.auth_repo = api_state.auth_repo
        self.audit_repo = api_state.audit_repo

    def _seed_e2e_data(self, state) -> None:
        """Seed data for e2e tests.

        Creates users, hosts, and jobs that match the original e2e test
        expectations for compatibility.
        """
        from pulldb.domain.models import (
            DBHost,
            Job,
            JobEvent,
            JobStatus,
            User,
            UserRole,
        )

        # Create test users (matching original e2e expectations)
        users_data = [
            ("usr-001", "testuser", "tstusr", UserRole.USER, False),
            ("usr-002", "admin", "admin", UserRole.ADMIN, False),
            ("usr-003", "disabled", "dsbusr", UserRole.USER, True),
            ("usr-004", "devadmin", "devadm", UserRole.ADMIN, False),
        ]

        with state.lock:
            for user_id, username, user_code, role, disabled in users_data:
                user = User(
                    user_id=user_id,
                    username=username,
                    user_code=user_code,
                    is_admin=(role == UserRole.ADMIN),
                    role=role,
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                    manager_id=None,
                    disabled_at=datetime(2024, 1, 1, tzinfo=UTC) if disabled else None,
                    allowed_hosts=None,
                    default_host=None,
                )
                state.users[user_id] = user
                state.users_by_code[user_code] = user

        # Create test hosts (using sequential readable UUIDs)
        hosts_data = [
            ("00000000-0000-0000-0000-000000000001", "db-prod-01", "prod-01", 3, 10, True),
            ("00000000-0000-0000-0000-000000000002", "db-staging-01", "staging-01", 2, 10, True),
        ]

        with state.lock:
            for host_id, hostname, alias, max_running, max_active, enabled in hosts_data:
                host = DBHost(
                    id=host_id,
                    hostname=hostname,
                    host_alias=alias,
                    credential_ref=f"mock/mysql/{alias}",
                    max_running_jobs=max_running,
                    max_active_jobs=max_active,
                    enabled=enabled,
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                )
                state.hosts[hostname] = host
                # Also index by alias if the state supports it
                # (hosts_by_alias was removed, lookup by hostname is canonical)

        # Create test jobs (matching original e2e expectations)
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        jobs_data = [
            # (job_id, target, status, owner_user_id, owner_username, owner_code,
            #  started_at, completed_at, error_detail, worker_id)
            (
                "job-001",
                "tstusr_devdb",
                JobStatus.QUEUED,
                "usr-001",
                "testuser",
                "tstusr",
                None,
                None,
                None,
                None,
            ),
            (
                "job-002",
                "tstusr_stagingdb",
                JobStatus.RUNNING,
                "usr-001",
                "testuser",
                "tstusr",
                base_time + timedelta(minutes=5),
                None,
                None,
                "worker-1",
            ),
            (
                "job-003",
                "admin_prodcopy",
                JobStatus.COMPLETE,
                "usr-002",
                "admin",
                "admin",
                base_time - timedelta(hours=1),
                base_time - timedelta(minutes=30),
                None,
                "worker-2",
            ),
            (
                "job-004",
                "tstusr_testdb",
                JobStatus.FAILED,
                "usr-001",
                "testuser",
                "tstusr",
                base_time - timedelta(hours=2),
                base_time - timedelta(hours=1, minutes=45),
                "Download failed: connection timeout",
                "worker-1",
            ),
        ]

        with state.lock:
            for (
                job_id,
                target,
                status,
                owner_id,
                owner_name,
                owner_code,
                started,
                completed,
                error,
                worker,
            ) in jobs_data:
                job = Job(
                    id=job_id,
                    owner_user_id=owner_id,
                    owner_username=owner_name,
                    owner_user_code=owner_code,
                    target=target,
                    staging_name=(
                        f"{target}_{job_id.replace('job-', '').ljust(12, '0')}"
                    ),
                    dbhost="db-staging-01",
                    status=status,
                    submitted_at=base_time,
                    started_at=started,
                    completed_at=completed,
                    options_json={},
                    retry_count=0,
                    error_detail=error,
                    worker_id=worker,
                    current_operation=None,
                )
                state.jobs[job_id] = job

            # Add job events
            event_id = 1
            for job_id in ["job-001", "job-002", "job-003", "job-004"]:
                event = JobEvent(
                    id=event_id,
                    job_id=job_id,
                    event_type="created",
                    detail="Job created",
                    logged_at=base_time,
                )
                state.job_events.append(event)
                event_id += 1

            # Additional events for running job
            state.job_events.append(
                JobEvent(
                    id=event_id,
                    job_id="job-002",
                    event_type="claimed",
                    detail="Claimed by worker-1",
                    logged_at=base_time + timedelta(minutes=5),
                )
            )
            event_id += 1
            state.job_events.append(
                JobEvent(
                    id=event_id,
                    job_id="job-002",
                    event_type="downloading",
                    detail="Downloading...",
                    logged_at=base_time + timedelta(minutes=6),
                )
            )

    def _seed_auth_credentials(self, state) -> None:
        """Seed auth credentials for test users.

        Password: testpass123 (bcrypt hash)
        """
        # Pre-computed bcrypt hash for "testpass123"
        test_hash = "$2b$12$mfPL.PHDhJKCXPV4OZawlO8lNwTjarJ8CGzR8s4A9K9vuAR2csbTe"

        with state.lock:
            for user_id in ["usr-001", "usr-002", "usr-003", "usr-004"]:
                state.auth_credentials[user_id] = {
                    "password_hash": test_hash,
                    "totp_secret": None,
                    "failed_attempts": 0,
                    "locked_until": None,
                }


# =============================================================================
# Test Application
# =============================================================================


def create_test_app() -> FastAPI:
    """Create a FastAPI app configured for testing."""
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    from pulldb.web import router as web_router

    app = FastAPI(title="pullDB Test")

    # Store mock state using simulation infrastructure
    app.state.api_state = E2EAPIState()

    # Include web routers
    app.include_router(web_router)

    # Mount static files in the same way as dev_server.py
    base_dir = Path(__file__).parent.parent.parent
    
    # Mount widgets directory first (must be before /static)
    widgets_dir = base_dir / "pulldb" / "web" / "static" / "widgets"
    if widgets_dir.exists():
        app.mount("/static/widgets", StaticFiles(directory=str(widgets_dir)), name="widgets")
    
    # Mount images from pulldb/images
    images_dir = base_dir / "pulldb" / "images"
    if images_dir.exists():
        app.mount("/static/images", StaticFiles(directory=str(images_dir)), name="static-images")

    # Mount static files (CSS, JS, etc.) - unified location
    static_dir = base_dir / "pulldb" / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


def _mock_get_api_state() -> E2EAPIState:
    """Override for get_api_state that returns our mock."""
    import pulldb.api.main as api_main

    return api_main._test_api_state  # type: ignore[attr-defined]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_simulation_mode() -> Generator[None, None, None]:
    """Ensure tests run in simulation mode."""
    os.environ["PULLDB_MODE"] = "SIMULATION"
    yield
    if "PULLDB_MODE" in os.environ:
        del os.environ["PULLDB_MODE"]


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
def page(context: BrowserContext, base_url: str) -> Generator[Page, None, None]:
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
