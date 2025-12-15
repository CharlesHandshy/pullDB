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

import os
import subprocess
from typing import Generator

import pytest


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE_URL = os.getenv("PULLDB_QA_API_URL", "http://localhost:8000")
VENV_PATH = os.getenv("PULLDB_VENV", "/home/charleshandshy/Projects/pullDB/venv")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# API Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Base URL for API requests."""
    return API_BASE_URL


@pytest.fixture(scope="session")
def api_client(api_base_url: str) -> Generator:
    """HTTP client for API testing."""
    import httpx
    
    with httpx.Client(base_url=api_base_url, timeout=30.0) as client:
        yield client


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
    """A known completed job ID for testing."""
    return "75777a4c-3dd9-48dd-b39c-62d8b35934da"


@pytest.fixture
def sample_user_code() -> str:
    """A known user code for testing."""
    return "charle"


@pytest.fixture
def sample_search_term() -> str:
    """A known search term that returns results."""
    return "action"


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "smoke: Quick smoke tests (< 1 min)")
    config.addinivalue_line("markers", "api: API endpoint tests")
    config.addinivalue_line("markers", "cli: CLI command tests")
    config.addinivalue_line("markers", "web: Web UI tests (requires Playwright)")
    config.addinivalue_line("markers", "db: Database tests (requires MySQL)")
    config.addinivalue_line("markers", "slow: Slow tests (> 30 seconds)")
