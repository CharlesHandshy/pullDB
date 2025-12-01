"""
QA Web UI Tests for pullDB

Playwright-based browser tests for web UI.
Run with: pytest tests/qa/test_web.py -v -m web
"""

import pytest


@pytest.mark.web
class TestLoginPage:
    """Login page tests."""

    def test_login_page_loads(self, web_login_page):
        """Login page renders correctly."""
        page = web_login_page
        # Check for heading
        assert page.locator("h1").inner_text() == "pullDB"
        # Check for form elements
        assert page.locator("input[name='username']").is_visible()
        assert page.locator("input[type='password']").is_visible()
        assert page.locator("button[type='submit']").is_visible()

    def test_login_form_labels(self, web_login_page):
        """Login form has proper labels."""
        page = web_login_page
        page_text = page.content()
        assert "Username" in page_text
        assert "Password" in page_text

    def test_cli_hint_displayed(self, web_login_page):
        """CLI usage hint is displayed."""
        page = web_login_page
        page_text = page.content()
        assert "pulldb restore" in page_text


@pytest.mark.web
class TestDashboardAuth:
    """Dashboard authentication tests."""

    def test_dashboard_redirects_to_login(self, page, api_base_url):
        """Unauthenticated dashboard access redirects to login."""
        page.goto(f"{api_base_url}/web/dashboard")
        # Should redirect to login
        assert "/login" in page.url

    def test_restore_page_redirects_to_login(self, page, api_base_url):
        """Unauthenticated restore page access redirects to login."""
        page.goto(f"{api_base_url}/web/restore")
        # Should redirect to login
        assert "/login" in page.url


@pytest.mark.web
class TestSwaggerUI:
    """Swagger UI tests."""

    def test_swagger_loads(self, swagger_page):
        """Swagger UI loads successfully."""
        page = swagger_page
        # Check for API title
        assert page.locator("text=pullDB API Service").is_visible()

    def test_swagger_shows_endpoints(self, swagger_page):
        """Swagger UI shows API endpoints."""
        page = swagger_page
        # Check for some key endpoints
        page_text = page.content()
        assert "/api/health" in page_text
        assert "/api/jobs" in page_text
        assert "/api/status" in page_text

    def test_swagger_shows_schemas(self, swagger_page):
        """Swagger UI shows data schemas."""
        page = swagger_page
        # Click to expand schemas section if needed
        schemas_heading = page.locator("text=Schemas")
        if schemas_heading.is_visible():
            schemas_heading.click()
        # Check for some key schemas
        page_text = page.content()
        assert "JobRequest" in page_text or "JobResponse" in page_text
