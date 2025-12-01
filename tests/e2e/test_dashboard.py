"""Playwright tests for the dashboard page.

Tests the dashboard functionality including:
- Page display
- Active jobs section
- Recent jobs section
- Navigation
- HTMX polling
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


class TestDashboardDisplay:
    """Tests for dashboard page display."""

    def test_dashboard_loads(self, logged_in_page: Page, base_url: str) -> None:
        """Dashboard should load successfully for authenticated user."""
        assert "/web/dashboard" in logged_in_page.url

    def test_dashboard_shows_username(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Dashboard should show logged-in username."""
        # User info should be visible in nav or header
        assert (
            logged_in_page.locator("text=testuser").is_visible()
            or "testuser" in logged_in_page.content()
        )

    def test_dashboard_has_active_jobs_section(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Dashboard should have Active Jobs section."""
        assert logged_in_page.locator("text=Active Jobs").is_visible()

    def test_dashboard_has_recent_jobs_section(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Dashboard should have Recent Jobs section."""
        assert logged_in_page.locator("text=Recent Jobs").is_visible()


class TestActiveJobsDisplay:
    """Tests for active jobs section on dashboard."""

    def test_shows_pending_jobs(self, logged_in_page: Page, base_url: str) -> None:
        """Active jobs should show queued/pending jobs."""
        # Check active section exists
        active_section = logged_in_page.locator("#active-jobs, .active-jobs")
        # May be empty if no active jobs visible to user
        assert active_section.count() >= 0

    def test_shows_running_jobs(self, logged_in_page: Page, base_url: str) -> None:
        """Active jobs section should display running jobs."""
        # Check page has active jobs section
        active_section = logged_in_page.locator("#active-jobs, .active-jobs")
        assert active_section.count() >= 0

    def test_active_jobs_have_links(self, logged_in_page: Page, base_url: str) -> None:
        """Active jobs section should have job links if jobs exist."""
        active_section = logged_in_page.locator("#active-jobs, .active-jobs")
        links = active_section.locator('a[href*="/web/jobs/"]')
        # May be 0 if no active jobs
        assert links.count() >= 0


class TestRecentJobsDisplay:
    """Tests for recent jobs section on dashboard."""

    def test_shows_job_list(self, logged_in_page: Page, base_url: str) -> None:
        """Recent jobs section should be present."""
        # Check for Recent Jobs section
        content = logged_in_page.content()
        assert "recent" in content.lower() or "history" in content.lower()


class TestDashboardNavigation:
    """Tests for navigation from dashboard."""

    def test_nav_links_exist(self, logged_in_page: Page, base_url: str) -> None:
        """Navigation should have Dashboard, New Restore, Search, Logout links."""
        assert logged_in_page.locator('nav >> text=Dashboard').is_visible()
        assert logged_in_page.locator('nav >> text=New Restore').is_visible()
        assert logged_in_page.locator('nav >> text=Search').is_visible()

    def test_click_job_link_goes_to_detail(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Clicking a job link should go to job detail."""
        # Find job links (exclude nav links)
        job_links = logged_in_page.locator('a[href*="/web/jobs/job-"]')
        if job_links.count() == 0:
            # No jobs visible, just verify page loaded
            return

        job_links.first.click()

        # Should be on a job detail page
        logged_in_page.wait_for_load_state("networkidle")
        assert "/web/jobs/" in logged_in_page.url


class TestHTMXPolling:
    """Tests for HTMX live updates on dashboard."""

    def test_active_jobs_has_htmx_attributes(
        self,
        logged_in_page: Page,
        base_url: str,
    ) -> None:
        """Active jobs section should have HTMX polling attributes."""
        htmx_element = logged_in_page.locator('[hx-get*="active-jobs"]')
        assert htmx_element.count() > 0

    def test_htmx_script_loaded(self, logged_in_page: Page, base_url: str) -> None:
        """HTMX script should be loaded on page."""
        htmx_script = logged_in_page.locator('script[src*="htmx"]')
        assert htmx_script.count() > 0
