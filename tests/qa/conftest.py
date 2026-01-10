"""
QA Test Fixtures for pullDB

This module provides pytest fixtures for QA testing across:
- API endpoints (httpx client)
- CLI commands (subprocess)
- Web UI (Playwright)
- Database (MySQL connection)

Usage:
    pytest tests/qa/ -v --html=qa-report.html
"""

import hashlib
import hmac as hmac_module
import os
import subprocess
from datetime import datetime, timezone
from typing import Generator

import pytest


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# API runs on port 8080, Web UI runs on port 8000
API_BASE_URL = os.getenv("PULLDB_QA_API_URL", "http://localhost:8080")
VENV_PATH = os.getenv("PULLDB_VENV", "/home/charleshandshy/Projects/pullDB/venv")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test API credentials (set in environment or use defaults for QA)
QA_API_KEY = os.getenv("PULLDB_QA_API_KEY", "qa-test-key")
QA_API_SECRET = os.getenv("PULLDB_QA_API_SECRET", "qa-test-secret")


def _sign_request(method: str, path: str, body: bytes | None, secret: str) -> dict[str, str]:
    """Generate HMAC signature headers for authenticated requests.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path (e.g., /api/jobs/active)
        body: Request body bytes or None
        secret: API secret key
        
    Returns:
        Dict with X-API-Key, X-Timestamp, X-Signature headers
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Hash the body (or empty string)
    if body:
        body_hash = hashlib.sha256(body).hexdigest()
    else:
        body_hash = hashlib.sha256(b"").hexdigest()
    
    # Build string to sign (must match server)
    string_to_sign = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}"
    
    # Compute signature
    signature = hmac_module.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    
    return {
        "X-API-Key": QA_API_KEY,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


class AuthenticatedHTTPClient:
    """HTTP client wrapper that adds HMAC authentication headers."""
    
    def __init__(self, base_client, api_key: str, api_secret: str):
        self._client = base_client
        self._api_key = api_key
        self._api_secret = api_secret
    
    def _add_auth_headers(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> dict:
        """Add authentication headers to request."""
        auth_headers = _sign_request(method, path, body, self._api_secret)
        auth_headers["X-API-Key"] = self._api_key
        if headers:
            auth_headers.update(headers)
        return auth_headers
    
    def get(self, path: str, **kwargs):
        """GET request with authentication."""
        headers = self._add_auth_headers("GET", path, None, kwargs.pop("headers", None))
        return self._client.get(path, headers=headers, **kwargs)
    
    def post(self, path: str, **kwargs):
        """POST request with authentication."""
        import json as json_module
        body = None
        if "json" in kwargs:
            body = json_module.dumps(kwargs["json"]).encode("utf-8")
        elif "content" in kwargs:
            body = kwargs["content"] if isinstance(kwargs["content"], bytes) else kwargs["content"].encode("utf-8")
        headers = self._add_auth_headers("POST", path, body, kwargs.pop("headers", None))
        return self._client.post(path, headers=headers, **kwargs)
    
    def put(self, path: str, **kwargs):
        """PUT request with authentication."""
        import json as json_module
        body = None
        if "json" in kwargs:
            body = json_module.dumps(kwargs["json"]).encode("utf-8")
        headers = self._add_auth_headers("PUT", path, body, kwargs.pop("headers", None))
        return self._client.put(path, headers=headers, **kwargs)
    
    def delete(self, path: str, **kwargs):
        """DELETE request with authentication."""
        headers = self._add_auth_headers("DELETE", path, None, kwargs.pop("headers", None))
        return self._client.delete(path, headers=headers, **kwargs)


# ---------------------------------------------------------------------------
# API Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Base URL for API requests."""
    return API_BASE_URL


@pytest.fixture(scope="session")
def api_client(api_base_url: str) -> Generator:
    """HTTP client for API testing (unauthenticated)."""
    import httpx
    
    with httpx.Client(base_url=api_base_url, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def authenticated_api_client(api_base_url: str) -> Generator:
    """HTTP client with HMAC authentication for protected endpoints.
    
    Uses PULLDB_QA_API_KEY and PULLDB_QA_API_SECRET environment variables
    for authentication. Falls back to test defaults if not set.
    
    Note: For QA tests against a real server, the API must be configured
    to accept the same API key/secret (via PULLDB_API_KEY env var or
    api_keys table in database).
    """
    import httpx
    
    with httpx.Client(base_url=api_base_url, timeout=30.0) as client:
        yield AuthenticatedHTTPClient(client, QA_API_KEY, QA_API_SECRET)


@pytest.fixture
def api_health(api_client) -> dict:
    """Get API health status."""
    response = api_client.get("/api/health")
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# CLI Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def cli_env() -> dict:
    """Environment variables for CLI commands."""
    env = os.environ.copy()
    # Ensure venv is activated
    env["PATH"] = f"{VENV_PATH}/bin:" + env.get("PATH", "")
    env["VIRTUAL_ENV"] = VENV_PATH
    return env


@pytest.fixture
def cli_runner(cli_env: dict):
    """Execute pulldb CLI commands."""
    
    def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run a pulldb command and return result."""
        cmd = ["pulldb"] + args
        result = subprocess.run(
            cmd,
            env=cli_env,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result
    
    return run


@pytest.fixture
def require_registered_user(cli_runner):
    """Skip test if user is not registered with pullDB.
    
    QA CLI tests require a registered user to run commands.
    Use this fixture to skip tests gracefully when running in
    development environments without user registration.
    """
    # Run a simple command to check registration status
    result = cli_runner(["history", "--limit", "1"], check=False)
    if "not registered" in result.stdout or "must register" in result.stdout.lower():
        pytest.skip("User not registered - CLI tests require registered user")


# ---------------------------------------------------------------------------
# Browser Fixtures (Playwright)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser():
    """Playwright browser instance."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser, api_base_url: str):
    """Browser page for web UI testing."""
    context = browser.new_context()
    page = context.new_page()
    yield page
    page.close()
    context.close()


@pytest.fixture
def web_login_page(page, api_base_url: str):
    """Navigate to login page."""
    page.goto(f"{api_base_url}/web/login")
    return page


@pytest.fixture
def swagger_page(page, api_base_url: str):
    """Navigate to Swagger UI."""
    page.goto(f"{api_base_url}/docs")
    page.wait_for_selector("text=pullDB API Service", timeout=10000)
    return page


# ---------------------------------------------------------------------------
# Database Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_config() -> dict:
    """Database configuration from environment.

    Uses standard PULLDB_MYSQL_* vars for shared config,
    with only PULLDB_API_MYSQL_USER being service-specific
    (per least-privilege pattern).
    """
    return {
        "host": os.getenv("PULLDB_MYSQL_HOST", "localhost"),
        "port": int(os.getenv("PULLDB_MYSQL_PORT", "3306")),
        "user": os.getenv("PULLDB_API_MYSQL_USER", "pulldb_api"),
        "database": os.getenv("PULLDB_MYSQL_DATABASE", "pulldb_service"),
    }


@pytest.fixture(scope="session")
def db_connection(db_config: dict):
    """MySQL database connection."""
    try:
        import mysql.connector
    except ImportError:
        pytest.skip("mysql-connector-python not installed")

    # Try to get password from environment or .env file
    password = os.getenv("PULLDB_MYSQL_PASSWORD")
    if not password:
        # Attempt to load from .env
        env_file = os.path.join(PROJECT_ROOT, ".env")
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    if line.startswith("PULLDB_MYSQL_PASSWORD="):
                        password = line.split("=", 1)[1].strip()
                        break

    if not password:
        pytest.skip("MySQL password not configured (set PULLDB_MYSQL_PASSWORD)")

    conn = mysql.connector.connect(
        host=db_config["host"],
        port=db_config["port"],
        user=db_config["user"],
        password=password,
        database=db_config["database"],
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Test Data Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_job_id() -> str:
    """A known completed job ID for testing.
    
    Note: CLI tests in test_cli.py define their own fixtures
    with mocked API responses. This fixture is for other QA tests
    that use real API calls.
    """
    return "75777a4c-3dd9-48dd-b39c-62d8b35934da"


@pytest.fixture
def sample_user_code() -> str:
    """A known user code for testing."""
    return "charle"


@pytest.fixture
def sample_search_term() -> str:
    """A known search term that returns results.
    
    Note: CLI tests in test_cli.py define their own fixtures
    with mocked API responses. This fixture is for other QA tests
    that use real API calls.
    """
    return "action"


# ---------------------------------------------------------------------------
# Mock Fixtures for API Tests (no real database required)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_job_repo(sample_job_id):
    """Mock job repository with test data for isolated API tests."""
    from unittest.mock import Mock
    from datetime import datetime, timezone
    from pulldb.domain.models import Job, JobStatus
    
    repo = Mock()
    
    # Create a mock job object
    mock_job = Mock(spec=Job)
    mock_job.id = sample_job_id
    mock_job.target = "test_database"
    mock_job.status = JobStatus.COMPLETE
    mock_job.owner_user_code = "testuser"
    mock_job.submitted_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Configure repository methods
    repo.get_job_by_id.return_value = mock_job
    repo.find_jobs_by_prefix.return_value = [mock_job]
    
    # Mock event for profile endpoint - detail must be JSON string
    import json
    mock_event = Mock()
    mock_event.event_type = "restore_profile"
    mock_event.detail = json.dumps({
        "job_id": sample_job_id,
        "started_at": "2025-01-01T12:00:00+00:00",
        "completed_at": "2025-01-01T12:02:00+00:00",
        "total_duration_seconds": 120.0,
        "total_bytes": 1024000,
        "phases": {},
        "phase_breakdown": {},
    })
    repo.get_job_events.return_value = [mock_event]
    
    return repo


@pytest.fixture
def mock_api_state(mock_job_repo):
    """Mock API state with injected mock repositories."""
    from unittest.mock import Mock
    
    state = Mock()
    state.job_repo = mock_job_repo
    return state


@pytest.fixture
def mock_auth_user():
    """Mock authenticated user for dependency override."""
    from pulldb.domain.models import User, UserRole
    from datetime import datetime, timezone
    
    return User(
        user_id="qa-test-user-id",
        username="qa-test-user",
        user_code="qatest",
        is_admin=True,
        role=UserRole.ADMIN,  # Admin for full access
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def api_client_with_mocks(mock_api_state, mock_auth_user):
    """FastAPI TestClient with mocked dependencies (no real DB required).
    
    This fixture overrides both the API state and authentication dependencies
    so tests can run without real database or authentication configuration.
    """
    from fastapi.testclient import TestClient
    from pulldb.api.main import app, get_api_state
    from pulldb.api.auth import get_authenticated_user, get_admin_user, get_manager_user
    
    # Override state dependency
    app.dependency_overrides[get_api_state] = lambda: mock_api_state
    
    # Override authentication dependencies to return mock user
    app.dependency_overrides[get_authenticated_user] = lambda: mock_auth_user
    app.dependency_overrides[get_admin_user] = lambda: mock_auth_user
    app.dependency_overrides[get_manager_user] = lambda: mock_auth_user
    
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "smoke: Quick smoke tests (< 1 min)")
    config.addinivalue_line("markers", "api: API endpoint tests")
    config.addinivalue_line("markers", "cli: CLI command tests")
    config.addinivalue_line("markers", "web: Web UI tests (TestClient-based, no live server required)")
    config.addinivalue_line("markers", "web_playwright: Web UI tests requiring Playwright + live server")
    config.addinivalue_line("markers", "db: Database tests (requires MySQL)")
    config.addinivalue_line("markers", "slow: Slow tests (> 30 seconds)")
