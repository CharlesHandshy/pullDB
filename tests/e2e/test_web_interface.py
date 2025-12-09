"""End-to-end tests for the Web2 interface using Playwright."""

import re

from playwright.sync_api import Page, expect


def test_web_login_flow(page: Page, base_url: str) -> None:
    """Test the login flow."""
    page.goto(f"{base_url}/web/auth/login")

    # Check login page elements
    expect(page.get_by_role("heading", name="Login to pullDB")).to_be_visible()

    # Fill in credentials
    page.get_by_label("Username").fill("testuser")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In").click()

    # Should redirect to dashboard
    expect(page).to_have_url(re.compile(r".*/web/dashboard"))
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()


def test_web_dashboard_stats(page: Page, base_url: str) -> None:
    """Test that the dashboard displays stats."""
    # Login first
    page.goto(f"{base_url}/web/auth/login")
    page.get_by_label("Username").fill("testuser")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In").click()

    # Check stats
    expect(page.get_by_text("Active Jobs")).to_be_visible()
    expect(page.get_by_text("Completed Today")).to_be_visible()
    expect(page.get_by_text("Failed Jobs")).to_be_visible()


def test_web_jobs_list(page: Page, base_url: str) -> None:
    """Test the jobs list page."""
    # Login first
    page.goto(f"{base_url}/web/auth/login")
    page.get_by_label("Username").fill("testuser")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In").click()

    # Navigate to jobs
    page.get_by_role("link", name="Jobs").click()
    expect(page).to_have_url(re.compile(r".*/web/jobs"))

    # Check job list
    expect(page.get_by_role("heading", name="Jobs")).to_be_visible()
    expect(page.get_by_text("job-001")).to_be_visible()
    expect(page.get_by_text("job-002")).to_be_visible()

    # Check status badges
    expect(page.locator("span.badge", has_text="pending")).to_be_visible()
    expect(page.locator("span.badge", has_text="running")).to_be_visible()


def test_web_new_job_flow(page: Page, base_url: str) -> None:
    """Test creating a new job (Restore)."""
    # Login first
    page.goto(f"{base_url}/web/auth/login")
    page.get_by_label("Username").fill("testuser")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In").click()

    # Navigate to new job page (Restore)
    page.get_by_role("link", name="Restore").click()
    expect(page).to_have_url(re.compile(r".*/web/restore"))

    # Check restore page elements
    expect(page.get_by_role("heading", name="New Restore Job")).to_be_visible()

    # Note: The restore form is complex, so we just check page load for now
    expect(page.get_by_label("Customer Name")).to_be_visible()


def test_web_job_details(page: Page, base_url: str) -> None:
    """Test the job details page."""
    # Login first
    page.goto(f"{base_url}/web/auth/login")
    page.get_by_label("Username").fill("testuser")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In").click()

    # Navigate to jobs
    page.get_by_role("link", name="Jobs").click()

    # Click view on first job
    page.get_by_role("link", name="View").first.click()

    # Check details page
    expect(page).to_have_url(re.compile(r".*/web/jobs/.*"))
    expect(page.get_by_text("Job Details")).to_be_visible()
    expect(page.get_by_text("Target Database")).to_be_visible()


def test_web_admin_access(page: Page, base_url: str) -> None:
    """Test admin page access."""
    # Login as admin
    page.goto(f"{base_url}/web/auth/login")
    page.get_by_label("Username").fill("admin")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In").click()

    # Navigate to admin (if link exists in sidebar for admin)
    # Or go directly
    page.goto(f"{base_url}/web/admin")

    # Check admin page
    expect(page.get_by_role("heading", name="Administration")).to_be_visible()
    expect(page.get_by_text("Users", exact=True)).to_be_visible()
    expect(page.get_by_text("Hosts", exact=True)).to_be_visible()



def test_web_devadmin_login(page: Page, base_url: str) -> None:
    """Test login as devadmin."""
    page.goto(f"{base_url}/web/auth/login")
    
    page.get_by_label("Username").fill("devadmin")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In").click()
    
    # Should redirect to dashboard
    expect(page).to_have_url(re.compile(r".*/web/dashboard"))
    
    # Should have admin access
    page.goto(f"{base_url}/web/admin")
    expect(page.get_by_role("heading", name="Administration")).to_be_visible()

def test_old_web_login_devadmin(page: Page, base_url: str) -> None:
    """Test login as devadmin on old web interface."""
    page.goto(f"{base_url}/web/login")
    
    page.fill('input[name="username"]', "devadmin")
    page.fill('input[name="password"]', "testpass123") # MockAuthRepo in conftest uses testpass123 hash for all users
    page.click('button[type="submit"]')
    
    # Should redirect to old dashboard
    expect(page).to_have_url(re.compile(r".*/web/dashboard"))
    
    # Should be able to access new admin page too (shared session)
    page.goto(f"{base_url}/web/admin")
    expect(page.get_by_role("heading", name="Administration")).to_be_visible()
