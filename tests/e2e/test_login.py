"""Playwright tests for the login page.

Tests the login functionality including:
- Page display
- Form validation
- Successful login
- Failed login scenarios
- Logout
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


class TestLoginPageDisplay:
    """Tests for login page display and structure."""

    def test_login_page_loads(self, page: Page, base_url: str) -> None:
        """Login page should load successfully."""
        page.goto(f"{base_url}/web/login")

        # Should have pullDB branding
        assert "pullDB" in page.title() or page.locator("text=pullDB").is_visible()

    def test_login_form_elements(self, page: Page, base_url: str) -> None:
        """Login form should have username, password, and submit."""
        page.goto(f"{base_url}/web/login")

        # Check form elements exist
        assert page.locator('input[name="username"]').is_visible()
        assert page.locator('input[name="password"]').is_visible()
        assert page.locator('button[type="submit"]').is_visible()

    def test_password_field_masked(self, page: Page, base_url: str) -> None:
        """Password field should be masked."""
        page.goto(f"{base_url}/web/login")

        password_input = page.locator('input[name="password"]')
        assert password_input.get_attribute("type") == "password"

    def test_username_field_has_autofocus(self, page: Page, base_url: str) -> None:
        """Username field should have focus on page load."""
        page.goto(f"{base_url}/web/login")

        # Check if username field has autofocus attribute
        username = page.locator('input[name="username"]')
        autofocus = username.get_attribute("autofocus")
        # autofocus can be "autofocus", "", or None depending on browser
        assert autofocus is not None or username.is_focused()


class TestSuccessfulLogin:
    """Tests for successful login flow."""

    def test_login_with_valid_credentials(self, page: Page, base_url: str) -> None:
        """User can log in with valid credentials."""
        page.goto(f"{base_url}/web/login")

        # Fill in credentials
        page.fill('input[name="username"]', "testuser")
        page.fill('input[name="password"]', "testpass123")

        # Submit form
        page.click('button[type="submit"]')

        # Should redirect to dashboard
        page.wait_for_url(f"{base_url}/web/dashboard")
        assert "/web/dashboard" in page.url

    def test_login_sets_session_cookie(self, page: Page, base_url: str) -> None:
        """Successful login should set session cookie."""
        page.goto(f"{base_url}/web/login")

        page.fill('input[name="username"]', "testuser")
        page.fill('input[name="password"]', "testpass123")
        page.click('button[type="submit"]')

        page.wait_for_url(f"{base_url}/web/dashboard")

        # Check for session cookie
        cookies = page.context.cookies()
        session_cookies = [c for c in cookies if c["name"] == "session_token"]
        assert len(session_cookies) == 1

    def test_logged_in_user_redirected_from_login(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Already logged in user visiting login should redirect to dashboard."""
        logged_in_page.goto(f"{base_url}/web/login")

        # Should redirect to dashboard
        assert "/web/dashboard" in logged_in_page.url


class TestFailedLogin:
    """Tests for failed login scenarios."""

    def test_login_with_wrong_password(self, page: Page, base_url: str) -> None:
        """Wrong password should show error."""
        page.goto(f"{base_url}/web/login")

        page.fill('input[name="username"]', "testuser")
        page.fill('input[name="password"]', "wrongpassword")
        page.click('button[type="submit"]')

        # Should stay on login page with error
        assert "/web/login" in page.url
        assert page.locator("text=Invalid username or password").is_visible()

    def test_login_with_nonexistent_user(self, page: Page, base_url: str) -> None:
        """Nonexistent user should show error."""
        page.goto(f"{base_url}/web/login")

        page.fill('input[name="username"]', "nouser")
        page.fill('input[name="password"]', "somepass")
        page.click('button[type="submit"]')

        # Should stay on login page with error
        assert "/web/login" in page.url
        assert page.locator("text=Invalid username or password").is_visible()

    def test_login_with_disabled_account(self, page: Page, base_url: str) -> None:
        """Disabled account should show appropriate error."""
        page.goto(f"{base_url}/web/login")

        page.fill('input[name="username"]', "disabled")
        page.fill('input[name="password"]', "testpass123")
        page.click('button[type="submit"]')

        # Should stay on login page with disabled message
        assert "/web/login" in page.url
        assert page.locator("text=disabled").is_visible()


class TestLogout:
    """Tests for logout functionality."""

    def test_logout_redirects_to_login(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Clicking logout should redirect to login page."""
        # Click logout link
        logged_in_page.click("text=Logout")

        # Should redirect to login
        logged_in_page.wait_for_url(f"{base_url}/web/login")

    def test_logout_clears_session_cookie(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Logout should clear session cookie."""
        logged_in_page.click("text=Logout")
        logged_in_page.wait_for_url(f"{base_url}/web/login")

        # Session cookie should be gone
        cookies = logged_in_page.context.cookies()
        session_cookies = [c for c in cookies if c["name"] == "session_token"]
        # Either no cookie or empty value
        assert len(session_cookies) == 0 or session_cookies[0].get("value") == ""

    def test_accessing_protected_page_after_logout(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Accessing protected page after logout should redirect to login."""
        logged_in_page.click("text=Logout")
        logged_in_page.wait_for_url(f"{base_url}/web/login")

        # Try to access dashboard
        logged_in_page.goto(f"{base_url}/web/dashboard")

        # Should redirect to login
        assert "/web/login" in logged_in_page.url


class TestProtectedRoutes:
    """Tests for unauthenticated access to protected routes."""

    def test_dashboard_requires_login(self, page: Page, base_url: str) -> None:
        """Dashboard should redirect to login if not authenticated."""
        page.goto(f"{base_url}/web/dashboard")
        assert "/web/login" in page.url

    def test_job_detail_requires_login(self, page: Page, base_url: str) -> None:
        """Job detail should redirect to login if not authenticated."""
        page.goto(f"{base_url}/web/jobs/job-001")
        assert "/web/login" in page.url
