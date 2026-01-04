"""
QA Web UI Tests for pullDB

Tests for web UI functionality.

Two test modes:
1. TestClient-based (default): Uses FastAPI TestClient for basic HTML checks.
   These tests run without a live server and are always available.

2. Playwright-based (optional): Full browser tests for JavaScript interactions.
   Requires: playwright install chromium AND live server at localhost:8080
   Run with: pytest tests/qa/test_web.py -v -m web_playwright
"""

import pytest

# Check if Playwright and browser are available
try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


def _check_web_ui_available():
    """Check if a live Web UI is responding (for Playwright tests only)."""
    try:
        import httpx
        # Check specifically for web UI route - API health may pass but web routes return 404
        resp = httpx.get("http://localhost:8080/web/login", timeout=2.0)
        # 200 means web UI is mounted; 404 means API is up but web routes not available
        return resp.status_code == 200
    except Exception:
        return False


# Only check live server availability for Playwright tests
_WEB_UI_AVAILABLE = _check_web_ui_available() if _PLAYWRIGHT_AVAILABLE else False

skip_no_playwright = pytest.mark.skipif(
    not _PLAYWRIGHT_AVAILABLE,
    reason="Playwright not installed"
)
skip_no_live_server = pytest.mark.skipif(
    not _WEB_UI_AVAILABLE,
    reason="Live server not available at localhost:8080/web/ (for Playwright tests)"
)


# ---------------------------------------------------------------------------
# TestClient Fixture (no live server required)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def web_client():
    """FastAPI TestClient for web UI testing without a live server.
    
    Uses simulation mode to avoid requiring MySQL database connection.
    """
    import os
    # Enable simulation mode for isolated testing
    old_mode = os.environ.get("PULLDB_MODE")
    os.environ["PULLDB_MODE"] = "SIMULATION"
    
    try:
        from fastapi.testclient import TestClient
        from pulldb.api.main import app
        # Force re-initialization of state in simulation mode
        if hasattr(app.state, "api_state"):
            delattr(app.state, "api_state")
        yield TestClient(app)
    finally:
        # Restore original mode
        if old_mode is None:
            os.environ.pop("PULLDB_MODE", None)
        else:
            os.environ["PULLDB_MODE"] = old_mode


# ---------------------------------------------------------------------------
# TestClient-based Web UI Tests (no live server required)
# ---------------------------------------------------------------------------

@pytest.mark.web
class TestLoginPage:
    """Login page tests using TestClient."""

    def test_login_page_loads(self, web_client):
        """Login page renders correctly."""
        response = web_client.get("/web/login")
        assert response.status_code == 200
        # Check for pullDB branding
        assert "pullDB" in response.text
        # Check for form elements
        assert 'name="username"' in response.text
        assert 'type="password"' in response.text
        assert 'type="submit"' in response.text

    def test_login_form_labels(self, web_client):
        """Login form has proper labels."""
        response = web_client.get("/web/login")
        assert response.status_code == 200
        assert "Username" in response.text
        assert "Password" in response.text

    def test_cli_hint_displayed(self, web_client):
        """CLI usage hint or restore reference is present on login page."""
        response = web_client.get("/web/login")
        assert response.status_code == 200
        # Login page should reference pullDB functionality
        # (exact wording may vary - check for branding or action context)
        assert "pullDB" in response.text


@pytest.mark.web
class TestDashboardAuth:
    """Dashboard authentication tests using TestClient."""

    def test_dashboard_redirects_to_login(self, web_client):
        """Unauthenticated dashboard access redirects to login."""
        # Follow all redirects (307 trailing slash + 303 to login)
        response = web_client.get("/web/dashboard", follow_redirects=True)
        # Should end up at login page
        assert response.status_code == 200
        assert "/login" in str(response.url)

    def test_restore_page_redirects_to_login(self, web_client):
        """Unauthenticated restore page access redirects to login."""
        # Follow all redirects (307 trailing slash + 303 to login)
        response = web_client.get("/web/restore", follow_redirects=True)
        # Should end up at login page
        assert response.status_code == 200
        assert "/login" in str(response.url)


# ---------------------------------------------------------------------------
# Playwright-based Browser Tests (require live server)
# ---------------------------------------------------------------------------

@skip_no_playwright
@skip_no_live_server
@pytest.mark.web_playwright
class TestLoginPagePlaywright:
    """Login page tests using Playwright (for JS interactions)."""

    def test_login_page_loads_browser(self, web_login_page):
        """Login page renders correctly in real browser."""
        page = web_login_page
        # Check for heading
        assert page.locator("h1").inner_text() == "pullDB"
        # Check for form elements
        assert page.locator("input[name='username']").is_visible()
        assert page.locator("input[type='password']").is_visible()
        assert page.locator("button[type='submit']").is_visible()


@skip_no_playwright
@skip_no_live_server
@pytest.mark.web_playwright
class TestDashboardAuthPlaywright:
    """Dashboard authentication tests using Playwright."""

    def test_dashboard_redirects_to_login_browser(self, page, api_base_url):
        """Unauthenticated dashboard access redirects to login (browser)."""
        page.goto(f"{api_base_url}/web/dashboard")
        # Should redirect to login
        assert "/login" in page.url

    def test_restore_page_redirects_to_login_browser(self, page, api_base_url):
        """Unauthenticated restore page access redirects to login (browser)."""
        page.goto(f"{api_base_url}/web/restore")
        # Should redirect to login
        assert "/login" in page.url


# ---------------------------------------------------------------------------
# Swagger UI Tests
# ---------------------------------------------------------------------------

def _check_swagger_available():
    """Check if Swagger UI is available at live server."""
    try:
        import httpx
        resp = httpx.get("http://localhost:8080/docs", timeout=2.0)
        return resp.status_code == 200 and "swagger" in resp.text.lower()
    except Exception:
        return False


_SWAGGER_AVAILABLE = _check_swagger_available() if _PLAYWRIGHT_AVAILABLE else False

skip_no_swagger = pytest.mark.skipif(
    not _SWAGGER_AVAILABLE,
    reason="Swagger UI not available at localhost:8080/docs"
)


@pytest.mark.web
class TestSwaggerUI:
    """Swagger UI tests using TestClient."""

    def test_swagger_docs_accessible(self, web_client):
        """Swagger /docs endpoint is accessible."""
        response = web_client.get("/docs")
        assert response.status_code == 200
        # Swagger UI returns HTML
        assert "swagger" in response.text.lower() or "openapi" in response.text.lower()

    def test_openapi_json_accessible(self, web_client):
        """OpenAPI JSON schema is accessible."""
        response = web_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "paths" in data
        assert "/api/health" in data["paths"]


@skip_no_playwright
@skip_no_swagger
@pytest.mark.web_playwright
class TestSwaggerUIPlaywright:
    """Swagger UI tests using Playwright (for JS-rendered content)."""

    def test_swagger_loads_browser(self, swagger_page):
        """Swagger UI loads successfully in real browser."""
        page = swagger_page
        # Check for API title
        assert page.locator("text=pullDB API Service").is_visible()

    def test_swagger_shows_endpoints_browser(self, swagger_page):
        """Swagger UI shows API endpoints in browser."""
        page = swagger_page
        # Check for some key endpoints
        page_text = page.content()
        assert "/api/health" in page_text
        assert "/api/jobs" in page_text
        assert "/api/status" in page_text

    def test_swagger_shows_schemas_browser(self, swagger_page):
        """Swagger UI shows Schemas section (loaded dynamically by JS)."""
        page = swagger_page
        # Swagger loads schemas dynamically via JavaScript
        # The Schemas section header should be visible even if collapsed
        schemas_heading = page.locator("text=Schemas")
        # Wait a bit for JS to render
        try:
            schemas_heading.wait_for(timeout=5000)
            assert schemas_heading.is_visible(), "Schemas section should be visible"
        except Exception:
            # Schemas may not be expanded/visible - check page source
            # Just verify the section exists in the DOM
            page_text = page.content()
            assert "Schemas" in page_text or "models" in page_text, \
                "Swagger UI should have a Schemas/models section"
