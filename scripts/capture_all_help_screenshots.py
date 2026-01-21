#!/usr/bin/env python3
"""
Comprehensive Help Screenshot Capture Script
=============================================

Captures all screenshots needed for pullDB Web UI help documentation.
Generates both light and dark mode versions for theme-aware display.

This script captures screenshots for:
- Common pages (login, sidebar, error pages)
- Dashboard views (user, manager, admin)
- Restore workflow (all 4 steps)
- Jobs list and detail views
- Profile and API key management
- Manager interface
- Admin panel (users, hosts, settings, maintenance)
- Feature requests

Usage:
    # Capture all screenshots (requires server at localhost:8111)
    python scripts/capture_all_help_screenshots.py
    
    # Capture specific category
    python scripts/capture_all_help_screenshots.py --category common
    python scripts/capture_all_help_screenshots.py --category admin
    
    # Specify server URL
    python scripts/capture_all_help_screenshots.py --url http://localhost:8111

Requirements:
    - pip install playwright
    - playwright install chromium
    - pullDB dev server running in simulation mode
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from playwright.async_api import Page, Browser

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: playwright not installed")
    print("Run: pip install playwright && playwright install chromium")
    sys.exit(1)


# Paths
PROJECT_ROOT = Path(__file__).parent.parent
SCREENSHOTS_BASE = PROJECT_ROOT / "pulldb" / "web" / "static" / "help" / "screenshots"
ANNOTATED_LIGHT = SCREENSHOTS_BASE / "annotated" / "light"
ANNOTATED_DARK = SCREENSHOTS_BASE / "annotated" / "dark"
RAW_LIGHT = SCREENSHOTS_BASE / "light"
RAW_DARK = SCREENSHOTS_BASE / "dark"

# Viewport
VIEWPORT = {"width": 1280, "height": 720}

# Credentials for different roles
CREDENTIALS = {
    "user": {"username": "devuser", "password": "PullDB_Dev2025!"},
    "manager": {"username": "devmanager", "password": "PullDB_Dev2025!"},
    "admin": {"username": "devadmin", "password": "PullDB_Dev2025!"},
}


class ScreenshotCapturer:
    """Captures screenshots for help documentation."""
    
    def __init__(self, base_url: str, headless: bool = True):
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.current_theme = "light"
        self.current_user: Optional[str] = None
        
    async def setup(self) -> None:
        """Initialize browser."""
        pw = await async_playwright().start()
        self.browser = await pw.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page(viewport=VIEWPORT)
        
    async def teardown(self) -> None:
        """Clean up browser."""
        if self.browser:
            await self.browser.close()
            
    async def login(self, role: str) -> bool:
        """Login as specified role."""
        if self.current_user == role:
            return True
            
        creds = CREDENTIALS.get(role, CREDENTIALS["user"])
        
        await self.page.goto(f"{self.base_url}/web/login")
        await self.page.wait_for_load_state("networkidle")
        
        # Fill credentials
        username_input = await self.page.query_selector('input[placeholder*="username"], input[name="username"]')
        if username_input:
            await username_input.fill(creds["username"])
        password_input = await self.page.query_selector('input[type="password"]')
        if password_input:
            await password_input.fill(creds["password"])
            
        # Submit
        submit = await self.page.query_selector('button[type="submit"], button:has-text("Sign In")')
        if submit:
            await submit.click()
            await self.page.wait_for_load_state("networkidle")
            
        # Handle maintenance modal
        await self._handle_maintenance_modal()
        
        self.current_user = role
        return "/login" not in self.page.url
        
    async def logout(self) -> None:
        """Logout current user."""
        await self.page.goto(f"{self.base_url}/web/logout")
        await self.page.wait_for_load_state("networkidle")
        self.current_user = None
        
    async def _handle_maintenance_modal(self) -> None:
        """Dismiss maintenance acknowledgment modal if present."""
        try:
            ack = await self.page.query_selector('button:has-text("Acknowledge")')
            if ack:
                await ack.click()
                await self.page.wait_for_load_state("networkidle")
        except Exception:
            pass
            
    async def set_theme(self, theme: str) -> None:
        """Set light or dark theme."""
        if theme == self.current_theme:
            return
            
        toggle = await self.page.query_selector('button:has-text("Toggle dark mode")')
        if toggle:
            await toggle.click()
            await asyncio.sleep(0.3)  # Theme transition
            self.current_theme = theme
            
    async def _save_screenshot(self, category: str, name: str, annotated: bool = True) -> None:
        """Save screenshot to appropriate directory."""
        # Get base directory
        if annotated:
            light_dir = ANNOTATED_LIGHT / category
            dark_dir = ANNOTATED_DARK / category
        else:
            light_dir = RAW_LIGHT / category
            dark_dir = RAW_DARK / category
            
        # Ensure directories exist
        light_dir.mkdir(parents=True, exist_ok=True)
        dark_dir.mkdir(parents=True, exist_ok=True)
        
        # Save light version
        await self.set_theme("light")
        await self.page.screenshot(path=str(light_dir / name))
        print(f"  ✓ {category}/{name} (light)")
        
        # Save dark version
        await self.set_theme("dark")
        await self.page.screenshot(path=str(dark_dir / name))
        print(f"  ✓ {category}/{name} (dark)")
        
    async def navigate(self, path: str) -> None:
        """Navigate to a path and wait for load."""
        await self.page.goto(f"{self.base_url}{path}")
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(0.3)  # Settle time
        
    # ================================================================
    # COMMON SCREENSHOTS
    # ================================================================
    
    async def capture_common(self) -> None:
        """Capture common UI screenshots."""
        print("\n📷 COMMON SCREENSHOTS")
        print("-" * 40)
        
        # Login page (must be logged out)
        await self.logout()
        await self.navigate("/web/login")
        await self._save_screenshot("common", "login.png")
        
        # Login error
        username = await self.page.query_selector('input[placeholder*="username"]')
        if username:
            await username.fill("baduser")
        password = await self.page.query_selector('input[type="password"]')
        if password:
            await password.fill("wrongpassword")
        submit = await self.page.query_selector('button:has-text("Sign In")')
        if submit:
            await submit.click()
            await asyncio.sleep(1)
        await self._save_screenshot("common", "login-error.png")
        
        # Login and get main UI elements
        await self.login("user")
        await self.navigate("/web/dashboard")
        
        # Sidebar expanded
        await self._save_screenshot("common", "sidebar-expanded.png")
        
        # Sidebar collapsed
        toggle = await self.page.query_selector('button:has-text("Toggle sidebar")')
        if toggle:
            await toggle.click()
            await asyncio.sleep(0.3)
            await self._save_screenshot("common", "sidebar-collapsed.png")
            await toggle.click()  # Re-expand
            await asyncio.sleep(0.3)
            
        # 404 error page (non-annotated)
        await self.navigate("/web/nonexistent-page-404")
        await self._save_screenshot("common", "404.png", annotated=False)
        
        # 403 error page (non-annotated)
        await self.logout()
        await self.login("user")
        await self.navigate("/web/admin")  # Should get 403
        await self._save_screenshot("common", "403.png", annotated=False)
        
    # ================================================================
    # DASHBOARD SCREENSHOTS
    # ================================================================
    
    async def capture_dashboard(self) -> None:
        """Capture dashboard screenshots for all roles."""
        print("\n📷 DASHBOARD SCREENSHOTS")
        print("-" * 40)
        
        # User view
        await self.logout()
        await self.login("user")
        await self.navigate("/web/dashboard")
        await self._save_screenshot("dashboard", "user-view.png")
        await self._save_screenshot("dashboard", "stats-cards.png")
        await self._save_screenshot("dashboard", "recent-jobs.png")
        
        # Manager view
        await self.logout()
        await self.login("manager")
        await self.navigate("/web/dashboard")
        await self._save_screenshot("dashboard", "manager-view.png")
        
        # Admin view
        await self.logout()
        await self.login("admin")
        await self.navigate("/web/dashboard")
        await self._save_screenshot("dashboard", "admin-view.png")
        
    # ================================================================
    # RESTORE WORKFLOW SCREENSHOTS
    # ================================================================
    
    async def capture_restore(self) -> None:
        """Capture restore workflow screenshots."""
        print("\n📷 RESTORE WORKFLOW SCREENSHOTS")
        print("-" * 40)
        
        await self.logout()
        await self.login("user")
        await self.navigate("/web/restore")
        
        # Step 1: Customer search
        search = await self.page.query_selector('input[placeholder*="Search"], input[type="search"]')
        if search:
            await search.fill("tech")
            await asyncio.sleep(0.5)
            await self._save_screenshot("restore", "step1-customer.png")
            
            # No results
            await search.fill("zzzznonexistent")
            await asyncio.sleep(0.5)
            await self._save_screenshot("restore", "step1-no-results.png")
            
        # Note: Steps 2-4 require interacting with actual restore flow
        # These may need manual capture or more complex automation
        print("  ℹ Steps 2-4 may require manual capture if simulation data is limited")
        
    # ================================================================
    # JOBS SCREENSHOTS
    # ================================================================
    
    async def capture_jobs(self) -> None:
        """Capture jobs list and detail screenshots."""
        print("\n📷 JOBS SCREENSHOTS")
        print("-" * 40)
        
        await self.logout()
        await self.login("user")
        
        # Active jobs list
        await self.navigate("/web/jobs")
        await self._save_screenshot("jobs", "list-active.png")
        
        # Filters open - use page navigation instead of toggle
        try:
            filter_btn = await self.page.query_selector('button:has-text("Filter")')
            if filter_btn:
                await filter_btn.click()
                await asyncio.sleep(0.5)
                await self._save_screenshot("jobs", "filters-open.png")
        except Exception as e:
            print(f"  ⚠ Skipping filters-open: {e}")
            
        # History view
        await self.navigate("/web/jobs?view=history")
        await self._save_screenshot("jobs", "list-history.png")
        
        # Empty state
        await self.navigate("/web/jobs?status=nonexistent")
        await self._save_screenshot("jobs", "list-empty.png")
        
        # Job details - find a running job
        await self.navigate("/web/jobs")
        try:
            job_link = await self.page.query_selector('a[href*="/web/jobs/"]')
            if job_link:
                await job_link.click()
                await self.page.wait_for_load_state("networkidle")
                await self._save_screenshot("jobs", "detail-running.png")
        except Exception as e:
            print(f"  ⚠ Skipping job detail: {e}")
            
    # ================================================================
    # PROFILE SCREENSHOTS
    # ================================================================
    
    async def capture_profile(self) -> None:
        """Capture profile screenshots."""
        print("\n📷 PROFILE SCREENSHOTS")
        print("-" * 40)
        
        await self.logout()
        await self.login("user")
        
        # Profile overview
        await self.navigate("/web/auth/profile")
        await self._save_screenshot("profile", "overview.png")
        
        # Password tab
        pwd_tab = await self.page.query_selector('a:has-text("Password"), button:has-text("Password")')
        if pwd_tab:
            await pwd_tab.click()
            await asyncio.sleep(0.3)
            await self._save_screenshot("profile", "password-form.png")
            
        # API keys tab
        api_tab = await self.page.query_selector('a:has-text("API Key"), button:has-text("API Key")')
        if api_tab:
            await api_tab.click()
            await asyncio.sleep(0.3)
            await self._save_screenshot("profile", "api-keys.png")
            
        # Create key modal
        create_btn = await self.page.query_selector('button:has-text("Create"), button:has-text("New Key")')
        if create_btn:
            await create_btn.click()
            await asyncio.sleep(0.3)
            await self._save_screenshot("profile", "create-key-modal.png")
            
    # ================================================================
    # MANAGER SCREENSHOTS
    # ================================================================
    
    async def capture_manager(self) -> None:
        """Capture manager interface screenshots."""
        print("\n📷 MANAGER SCREENSHOTS")
        print("-" * 40)
        
        await self.logout()
        await self.login("manager")
        
        # Manager overview
        await self.navigate("/web/manager")
        await self._save_screenshot("manager", "overview.png")
        
        # Team list
        team_link = await self.page.query_selector('a:has-text("Team"), a[href*="team"]')
        if team_link:
            await team_link.click()
            await self.page.wait_for_load_state("networkidle")
            await self._save_screenshot("manager", "team-list.png")
            
    # ================================================================
    # ADMIN SCREENSHOTS
    # ================================================================
    
    async def capture_admin(self) -> None:
        """Capture admin panel screenshots."""
        print("\n📷 ADMIN SCREENSHOTS")
        print("-" * 40)
        
        await self.logout()
        await self.login("admin")
        
        # Admin overview
        await self.navigate("/web/admin")
        await self._save_screenshot("admin", "overview.png")
        
        # Users management
        await self.navigate("/web/admin/users")
        await self._save_screenshot("admin", "users-list.png")
        
        # Add user form
        add_btn = await self.page.query_selector('button:has-text("Add User"), a:has-text("Add User")')
        if add_btn:
            await add_btn.click()
            await self.page.wait_for_load_state("networkidle")
            await self._save_screenshot("admin", "user-add.png")
            await self.page.go_back()
            
        # Edit user
        edit_btn = await self.page.query_selector('button:has-text("Edit"), a[href*="edit"]')
        if edit_btn:
            await edit_btn.click()
            await self.page.wait_for_load_state("networkidle")
            await self._save_screenshot("admin", "user-edit.png")
            await self.page.go_back()
            
        # Hosts
        await self.navigate("/web/admin/hosts")
        await self._save_screenshot("admin", "hosts-list.png")
        
        # Host detail
        host_link = await self.page.query_selector('a[href*="/admin/hosts/"]')
        if host_link:
            await host_link.click()
            await self.page.wait_for_load_state("networkidle")
            await self._save_screenshot("admin", "host-detail.png")
            
        # Add host
        await self.navigate("/web/admin/hosts/add")
        await self._save_screenshot("admin", "host-add.png")
        
        # API Keys
        await self.navigate("/web/admin/api-keys")
        await self._save_screenshot("admin", "api-keys.png")
        
        # Settings
        await self.navigate("/web/admin/settings")
        await self._save_screenshot("admin", "settings.png")
        
        # Maintenance
        await self.navigate("/web/admin/maintenance")
        await self._save_screenshot("admin", "maintenance.png")
        
        # Audit log
        await self.navigate("/web/admin/audit")
        await self._save_screenshot("admin", "audit-log.png")
        
        # Locked databases
        await self.navigate("/web/admin/locked-databases")
        await self._save_screenshot("admin", "locked-dbs.png")
        
        # Orphan databases
        await self.navigate("/web/admin/orphans")
        await self._save_screenshot("admin", "orphans.png")
        
        # Disallowed users
        await self.navigate("/web/admin/disallowed-users")
        await self._save_screenshot("admin", "disallowed-users.png")
        
        # Cleanup staging
        await self.navigate("/web/admin/cleanup")
        await self._save_screenshot("admin", "cleanup-staging.png")
        
        # Prune logs
        await self.navigate("/web/admin/logs")
        await self._save_screenshot("admin", "prune-logs.png")
        
    # ================================================================
    # REQUESTS SCREENSHOTS
    # ================================================================
    
    async def capture_requests(self) -> None:
        """Capture feature requests screenshots."""
        print("\n📷 REQUESTS SCREENSHOTS")
        print("-" * 40)
        
        await self.logout()
        await self.login("user")
        
        await self.navigate("/web/requests")
        await self._save_screenshot("requests", "feature-requests.png", annotated=False)
        
    # ================================================================
    # CAPTURE ALL
    # ================================================================
    
    async def capture_all(self, category: Optional[str] = None) -> None:
        """Capture all screenshots or specific category."""
        print("=" * 60)
        print("🎬 pullDB Help Screenshot Capture")
        print("=" * 60)
        print(f"Server: {self.base_url}")
        print(f"Output: {SCREENSHOTS_BASE.relative_to(PROJECT_ROOT)}")
        print("=" * 60)
        
        await self.setup()
        
        try:
            categories = {
                "common": self.capture_common,
                "dashboard": self.capture_dashboard,
                "restore": self.capture_restore,
                "jobs": self.capture_jobs,
                "profile": self.capture_profile,
                "manager": self.capture_manager,
                "admin": self.capture_admin,
                "requests": self.capture_requests,
            }
            
            if category:
                if category in categories:
                    await categories[category]()
                else:
                    print(f"Unknown category: {category}")
                    print(f"Available: {', '.join(categories.keys())}")
            else:
                for cat_name, cat_func in categories.items():
                    await cat_func()
                    
            print("\n" + "=" * 60)
            print("✅ Screenshot capture complete!")
            print("=" * 60)
            
        finally:
            await self.teardown()


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Capture help documentation screenshots"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8111",
        help="Base URL of pullDB server (default: http://localhost:8111)"
    )
    parser.add_argument(
        "--category",
        choices=["common", "dashboard", "restore", "jobs", "profile", 
                 "manager", "admin", "requests"],
        help="Capture only specific category"
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode for debugging"
    )
    args = parser.parse_args()
    
    capturer = ScreenshotCapturer(
        base_url=args.url,
        headless=not args.no_headless
    )
    await capturer.capture_all(category=args.category)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
