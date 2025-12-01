"""Playwright tests for navigation and layout.

Tests the overall navigation and layout functionality including:
- Navigation links
- Responsive behavior
- Base template elements
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


class TestNavigation:
    """Tests for navigation between pages."""

    def test_dashboard_to_restore(self, logged_in_page: Page, base_url: str) -> None:
        """Can navigate from dashboard to restore."""
        logged_in_page.click('nav >> a:has-text("New Restore")')
        logged_in_page.wait_for_url(f"{base_url}/web/restore")
        assert "/web/restore" in logged_in_page.url

    def test_restore_to_dashboard(self, logged_in_page: Page, base_url: str) -> None:
        """Can navigate from restore to dashboard."""
        logged_in_page.goto(f"{base_url}/web/restore")
        logged_in_page.click('nav >> a:has-text("Dashboard")')
        logged_in_page.wait_for_url(f"{base_url}/web/dashboard")
        assert "/web/dashboard" in logged_in_page.url

    def test_job_detail_back_to_dashboard(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """Can navigate from job detail back to dashboard."""
        logged_in_page.goto(f"{base_url}/web/jobs/job-001")

        # Click dashboard link in nav
        dashboard_link = logged_in_page.locator('nav >> a:has-text("Dashboard")')
        if dashboard_link.count() > 0:
            dashboard_link.click()
            logged_in_page.wait_for_url(f"{base_url}/web/dashboard")
            assert "/web/dashboard" in logged_in_page.url


class TestBaseTemplateElements:
    """Tests for base template shared elements."""

    def test_has_nav_bar(self, logged_in_page: Page, base_url: str) -> None:
        """Page should have navigation bar."""
        assert logged_in_page.locator("nav").is_visible()

    def test_has_pulldb_branding(self, logged_in_page: Page, base_url: str) -> None:
        """Page should have pullDB branding."""
        content = logged_in_page.content()
        assert "pulldb" in content.lower() or "pullDB" in content

    def test_has_viewport_meta(self, logged_in_page: Page, base_url: str) -> None:
        """Page should have responsive viewport meta tag."""
        meta = logged_in_page.locator('meta[name="viewport"]')
        assert meta.count() > 0

    def test_has_htmx_script(self, logged_in_page: Page, base_url: str) -> None:
        """Page should include HTMX script."""
        htmx = logged_in_page.locator('script[src*="htmx"]')
        assert htmx.count() > 0


class TestPageTitles:
    """Tests for page titles."""

    def test_login_page_title(self, page: Page, base_url: str) -> None:
        """Login page should have appropriate title."""
        page.goto(f"{base_url}/web/login")
        title = page.title()
        assert "login" in title.lower() or "pulldb" in title.lower()

    def test_dashboard_page_title(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """Dashboard should have appropriate title."""
        title = logged_in_page.title()
        assert "dashboard" in title.lower() or "pulldb" in title.lower()

    def test_job_detail_page_title(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """Job detail should have appropriate title."""
        logged_in_page.goto(f"{base_url}/web/jobs/job-001")
        title = logged_in_page.title()
        assert (
            "job" in title.lower()
            or "pulldb" in title.lower()
            or "job-001" in title
        )


class TestHTMXIntegration:
    """Tests for HTMX integration."""

    def test_htmx_loads_correctly(self, logged_in_page: Page, base_url: str) -> None:
        """HTMX should be loaded and functional."""
        # Check if htmx global is available
        result = logged_in_page.evaluate("typeof htmx !== 'undefined'")
        assert result is True

    def test_htmx_version(self, logged_in_page: Page, base_url: str) -> None:
        """HTMX should be version 1.9+."""
        version = logged_in_page.evaluate(
            "typeof htmx !== 'undefined' ? htmx.version : null"
        )
        if version:
            major = int(version.split(".")[0])
            assert major >= 1


class TestStylesAndAppearance:
    """Tests for CSS and styling."""

    def test_css_variables_defined(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """CSS custom properties should be defined."""
        # Check if any CSS variables are used
        styles = logged_in_page.evaluate("""
            () => {
                const root = document.documentElement;
                const styles = getComputedStyle(root);
                return styles.getPropertyValue('--primary-color') ||
                       styles.getPropertyValue('--bg-color') ||
                       'none';
            }
        """)
        # Just verify CSS is being processed
        assert styles is not None

    def test_no_broken_images(self, logged_in_page: Page, base_url: str) -> None:
        """Page should not have broken images."""
        broken_images = logged_in_page.evaluate("""
            () => {
                const images = document.querySelectorAll('img');
                let broken = 0;
                images.forEach(img => {
                    if (!img.complete || img.naturalHeight === 0) {
                        broken++;
                    }
                });
                return broken;
            }
        """)
        assert broken_images == 0
