#!/usr/bin/env python3
"""
Capture Admin page screenshots for help documentation.

This script captures 23 admin screenshots in both light and dark themes (46 total).

Screenshots:
  User Management:
    1. users-list.png - /web/admin/users - User list table
    2. user-edit.png - /web/admin/users/<id>/edit - User edit form (action modal)
    3. user-add.png - /web/admin/users/add - New user creation form (modal)
    4. user-created-password.png - After creating user, generated password display
    5. user-hosts-modal.png - Host assignment checkbox modal
    6. user-api-keys-modal.png - User's API keys modal
    7. user-force-delete.png - Force delete with database selection

  Host Management:
    8. hosts-list.png - /web/admin/hosts - Database hosts list
    9. host-detail.png - /web/admin/hosts/<id> - Host detail page
    10. host-add.png - /web/admin/hosts/add - New host form (modal)
    11. host-delete-modal.png - Host deletion confirmation modal

  API Key Management:
    12. api-keys.png - /web/admin/api-keys - System-wide API key overview
    13. api-key-approval.png - Pending API key approval queue (same page, filter to pending)

  System Settings:
    14. settings.png - /web/admin/settings - System settings page
    15. settings-danger-confirm.png - Dangerous setting change warning modal

  Maintenance:
    16. maintenance.png - /web/admin/maintenance (prune/cleanup/orphans hub)
    17. prune-logs.png - Log pruning preview
    18. cleanup-staging.png - Staging cleanup preview
    19. orphans.png - Orphan database management

  Audit & Security:
    20. audit-log.png - /web/admin/audit - Audit log browser
    21. locked-dbs.png - Locked database management
    22. disallowed-users.png - Disallowed usernames management
    23. overview.png - /web/admin - Admin dashboard overview

Usage:
    python scripts/capture_admin_screenshots.py

Prerequisites:
    - Dev server running: python scripts/dev_server.py --scenario screenshots
    - Playwright installed: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright, Page
except ImportError:
    print("ERROR: playwright not installed. Run:")
    print("  pip install playwright")
    print("  playwright install chromium")
    sys.exit(1)


PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_BASE = PROJECT_ROOT / "pulldb" / "web" / "static" / "help" / "screenshots"
BASE_URL = "http://localhost:8111"

# Viewport for consistent screenshots
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720

# Login credentials for dev server (admin user)
DEV_USERNAME = "devadmin"
DEV_PASSWORD = "PullDB_Dev2025!"


async def login(page: Page, username: str = DEV_USERNAME, password: str = DEV_PASSWORD) -> bool:
    """Login to the web UI as admin."""
    await page.goto(f"{BASE_URL}/web/login")
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(0.3)
    
    # Fill login form
    await page.fill('input[name="username"]', username)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    
    # Wait for redirect
    try:
        await page.wait_for_url("**/dashboard/**", timeout=5000)
    except Exception:
        await asyncio.sleep(1.0)
    
    # Check we're logged in
    return "/login" not in page.url


async def set_theme(page: Page, theme: str) -> None:
    """Set the page theme (light or dark)."""
    await page.evaluate(f"""
        localStorage.setItem('theme', '{theme}');
        document.documentElement.setAttribute('data-theme', '{theme}');
    """)
    await asyncio.sleep(0.15)


async def capture(page: Page, output_path: Path, description: str) -> bool:
    """Capture a screenshot to the specified path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(output_path))
        rel_path = output_path.relative_to(PROJECT_ROOT)
        print(f"  ✓ {rel_path} - {description}")
        return True
    except Exception as e:
        print(f"  ✗ Failed: {description} - {e}")
        return False


# =============================================================================
# User Management Screenshots
# =============================================================================

async def capture_users_list(page: Page, theme: str) -> bool:
    """Capture users list page."""
    await page.goto(f"{BASE_URL}/web/admin/users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(1.0)  # Wait for lazy table to load
    
    output = OUTPUT_BASE / theme / "admin" / "users-list.png"
    return await capture(page, output, "Users list table")


async def capture_user_edit(page: Page, theme: str) -> bool:
    """Capture user edit - showing role dropdown open."""
    await page.goto(f"{BASE_URL}/web/admin/users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(1.0)  # Wait for lazy table to load
    
    # Click on a role combobox to show inline editing
    role_select = page.locator('td combobox').first
    if await role_select.count() > 0:
        await role_select.click()
        await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "admin" / "user-edit.png"
    return await capture(page, output, "User edit/role dropdown")


async def capture_user_add(page: Page, theme: str) -> bool:
    """Capture add user modal."""
    await page.goto(f"{BASE_URL}/web/admin/users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(1.0)  # Wait for lazy table to load
    
    # Click Add User button to open modal
    add_btn = page.locator('button:has-text("Add new user")').first
    if await add_btn.count() > 0:
        await add_btn.click()
        await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "user-add.png"
    return await capture(page, output, "Add user form modal")


async def capture_user_created_password(page: Page, theme: str) -> bool:
    """Capture the password display after creating a user.
    
    Since we don't want to actually create users, we'll capture the add user
    form in a filled state to show the workflow.
    """
    await page.goto(f"{BASE_URL}/web/admin/users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(1.0)  # Wait for lazy table
    
    # Click Add User button
    add_btn = page.locator('button:has-text("Add new user")').first
    if await add_btn.count() > 0:
        await add_btn.click()
        await asyncio.sleep(0.5)
        
        # Try to fill form if visible
        username_input = page.locator('input#new-username').first
        if await username_input.count() > 0:
            await username_input.fill("screenshot_test_user")
            await asyncio.sleep(0.2)
    
    output = OUTPUT_BASE / theme / "admin" / "user-created-password.png"
    return await capture(page, output, "User creation form (filled)")


async def capture_user_hosts_modal(page: Page, theme: str) -> bool:
    """Capture host assignment modal for a user."""
    await page.goto(f"{BASE_URL}/web/admin/users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(1.0)  # Wait for lazy table
    
    # Find hosts button for devmanager (second user row)
    hosts_btn = page.locator('button[title*="Manage database hosts for devmanager"]').first
    if await hosts_btn.count() > 0:
        await hosts_btn.click()
        await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "user-hosts-modal.png"
    return await capture(page, output, "User host assignment modal")


async def capture_user_api_keys_modal(page: Page, theme: str) -> bool:
    """Capture user's API keys modal."""
    await page.goto(f"{BASE_URL}/web/admin/users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(1.0)  # Wait for lazy table
    
    # Find API keys button for devmanager
    api_btn = page.locator('button[title*="Manage API keys for devmanager"]').first
    if await api_btn.count() > 0:
        await api_btn.click()
        await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "user-api-keys-modal.png"
    return await capture(page, output, "User API keys modal")


async def capture_user_force_delete(page: Page, theme: str) -> bool:
    """Capture force delete dialog."""
    await page.goto(f"{BASE_URL}/web/admin/users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(1.0)  # Wait for lazy table
    
    # Click delete button for devuser
    del_btn = page.locator('button[title*="Delete user devuser"]').first
    if await del_btn.count() > 0:
        await del_btn.click()
        await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "user-force-delete.png"
    return await capture(page, output, "Force delete with database selection")


# =============================================================================
# Host Management Screenshots
# =============================================================================

async def capture_hosts_list(page: Page, theme: str) -> bool:
    """Capture hosts list page."""
    await page.goto(f"{BASE_URL}/web/admin/hosts")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "hosts-list.png"
    return await capture(page, output, "Database hosts list")


async def capture_host_detail(page: Page, theme: str) -> bool:
    """Capture host detail page."""
    await page.goto(f"{BASE_URL}/web/admin/hosts")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # Click on first host row to go to detail
    host_link = page.locator('table tbody tr td a').first
    if await host_link.count() > 0:
        await host_link.click()
        await page.wait_for_load_state("networkidle")
        await set_theme(page, theme)
        await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "admin" / "host-detail.png"
    return await capture(page, output, "Host detail page")


async def capture_host_add(page: Page, theme: str) -> bool:
    """Capture add host form/modal."""
    await page.goto(f"{BASE_URL}/web/admin/hosts")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # Look for the Add Host button specifically - avoid the provision button
    # Try several selector strategies
    add_btn = page.locator('#add-host-btn, a[href*="add"]:has-text("Add"), button:has-text("Register New Host")').first
    if await add_btn.count() > 0:
        await add_btn.click()
        await asyncio.sleep(0.5)
    else:
        # Fallback: scroll to find the registration form section
        form_section = page.locator('text=Register New Host, text=Add New Host, #host-form').first
        if await form_section.count() > 0:
            await form_section.scroll_into_view_if_needed()
            await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "admin" / "host-add.png"
    return await capture(page, output, "Add host form")


async def capture_host_delete_modal(page: Page, theme: str) -> bool:
    """Capture host deletion confirmation modal."""
    # First go to a host detail page
    await page.goto(f"{BASE_URL}/web/admin/hosts")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # Click on first host to go to detail
    host_link = page.locator('table tbody tr td a').first
    if await host_link.count() > 0:
        await host_link.click()
        await page.wait_for_load_state("networkidle")
        await set_theme(page, theme)
        await asyncio.sleep(0.3)
    
    # Look for delete button
    delete_btn = page.locator('button:has-text("Delete"), a:has-text("Delete Host")').first
    if await delete_btn.count() > 0:
        await delete_btn.click()
        await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "host-delete-modal.png"
    return await capture(page, output, "Host deletion confirmation modal")


# =============================================================================
# API Key Management Screenshots
# =============================================================================

async def capture_api_keys(page: Page, theme: str) -> bool:
    """Capture API keys overview page."""
    await page.goto(f"{BASE_URL}/web/admin/api-keys")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "api-keys.png"
    return await capture(page, output, "System-wide API key overview")


async def capture_api_key_approval(page: Page, theme: str) -> bool:
    """Capture pending API key approval queue."""
    await page.goto(f"{BASE_URL}/web/admin/api-keys")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # Try to filter to pending keys if there's a filter
    pending_filter = page.locator('text=Pending, button:has-text("Pending")').first
    if await pending_filter.count() > 0:
        await pending_filter.click()
        await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "admin" / "api-key-approval.png"
    return await capture(page, output, "Pending API key approval queue")


# =============================================================================
# System Settings Screenshots
# =============================================================================

async def capture_settings(page: Page, theme: str) -> bool:
    """Capture system settings page."""
    await page.goto(f"{BASE_URL}/web/admin/settings")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "settings.png"
    return await capture(page, output, "System settings page")


async def capture_settings_danger_confirm(page: Page, theme: str) -> bool:
    """Capture dangerous setting change warning modal or danger zone section."""
    await page.goto(f"{BASE_URL}/web/admin/settings")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # First, scroll down to see the danger zone section
    danger_section = page.locator('text=Danger Zone, text=Dangerous Settings, .danger-zone, .card-danger').first
    if await danger_section.count() > 0:
        await danger_section.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
    else:
        # If no danger zone, scroll to bottom of page
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.3)
    
    # Try to find and click a visible dangerous setting that triggers a confirmation
    edit_btn = page.locator('button.btn-danger:visible, button.btn-warning:visible, button:has-text("Reset"):visible').first
    if await edit_btn.count() > 0:
        await edit_btn.click()
        await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "settings-danger-confirm.png"
    return await capture(page, output, "Dangerous setting change warning modal")


# =============================================================================
# Maintenance Screenshots
# =============================================================================

async def capture_maintenance(page: Page, theme: str) -> bool:
    """Capture maintenance tools hub (admin overview with maintenance links)."""
    await page.goto(f"{BASE_URL}/web/admin")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # Scroll to maintenance section if present
    maint_section = page.locator('text=Maintenance, text=Cleanup, text=Prune').first
    if await maint_section.count() > 0:
        await maint_section.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
    
    output = OUTPUT_BASE / theme / "admin" / "maintenance.png"
    return await capture(page, output, "Maintenance tools section")


async def capture_prune_logs(page: Page, theme: str) -> bool:
    """Capture log pruning preview page."""
    await page.goto(f"{BASE_URL}/web/admin/prune-logs/preview")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "prune-logs.png"
    return await capture(page, output, "Log pruning preview")


async def capture_cleanup_staging(page: Page, theme: str) -> bool:
    """Capture staging cleanup preview page."""
    await page.goto(f"{BASE_URL}/web/admin/cleanup-staging/preview")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "cleanup-staging.png"
    return await capture(page, output, "Staging cleanup preview")


async def capture_orphans(page: Page, theme: str) -> bool:
    """Capture orphan database management page."""
    await page.goto(f"{BASE_URL}/web/admin/orphans/preview")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "orphans.png"
    return await capture(page, output, "Orphan database management")


# =============================================================================
# Audit & Security Screenshots
# =============================================================================

async def capture_audit_log(page: Page, theme: str) -> bool:
    """Capture audit log browser."""
    await page.goto(f"{BASE_URL}/web/admin/audit")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "audit-log.png"
    return await capture(page, output, "Audit log browser")


async def capture_locked_dbs(page: Page, theme: str) -> bool:
    """Capture locked database management page."""
    await page.goto(f"{BASE_URL}/web/admin/locked-databases")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "locked-dbs.png"
    return await capture(page, output, "Locked database management")


async def capture_disallowed_users(page: Page, theme: str) -> bool:
    """Capture disallowed usernames management page."""
    await page.goto(f"{BASE_URL}/web/admin/disallowed-users")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "disallowed-users.png"
    return await capture(page, output, "Disallowed usernames management")


async def capture_overview(page: Page, theme: str) -> bool:
    """Capture admin dashboard overview."""
    await page.goto(f"{BASE_URL}/web/admin")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "admin" / "overview.png"
    return await capture(page, output, "Admin dashboard overview")


# =============================================================================
# Main Capture Orchestration
# =============================================================================

CAPTURE_FUNCTIONS = [
    # User Management
    ("users-list", capture_users_list),
    ("user-edit", capture_user_edit),
    ("user-add", capture_user_add),
    ("user-created-password", capture_user_created_password),
    ("user-hosts-modal", capture_user_hosts_modal),
    ("user-api-keys-modal", capture_user_api_keys_modal),
    ("user-force-delete", capture_user_force_delete),
    # Host Management
    ("hosts-list", capture_hosts_list),
    ("host-detail", capture_host_detail),
    ("host-add", capture_host_add),
    ("host-delete-modal", capture_host_delete_modal),
    # API Key Management
    ("api-keys", capture_api_keys),
    ("api-key-approval", capture_api_key_approval),
    # System Settings
    ("settings", capture_settings),
    ("settings-danger-confirm", capture_settings_danger_confirm),
    # Maintenance
    ("maintenance", capture_maintenance),
    ("prune-logs", capture_prune_logs),
    ("cleanup-staging", capture_cleanup_staging),
    ("orphans", capture_orphans),
    # Audit & Security
    ("audit-log", capture_audit_log),
    ("locked-dbs", capture_locked_dbs),
    ("disallowed-users", capture_disallowed_users),
    ("overview", capture_overview),
]


async def capture_all_admin_screenshots() -> tuple[int, int]:
    """Capture all admin screenshots for both themes."""
    print("=" * 60)
    print("Admin Screenshots Capture")
    print("=" * 60)
    print(f"Target: {len(CAPTURE_FUNCTIONS)} screenshots × 2 themes = {len(CAPTURE_FUNCTIONS) * 2} total")
    
    themes = ["light", "dark"]
    total_success = 0
    total_failed = 0
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        for theme in themes:
            print(f"\n{'='*40}")
            print(f"Theme: {theme.upper()}")
            print("="*40)
            
            context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            )
            page = await context.new_page()
            
            # Login as admin
            print(f"\nLogging in as {DEV_USERNAME}...")
            if not await login(page):
                print("  ERROR: Login failed!")
                await context.close()
                total_failed += len(CAPTURE_FUNCTIONS)
                continue
            print("  ✓ Login successful")
            
            # Capture screenshots
            print(f"\nCapturing admin screenshots ({theme}):")
            
            for name, capture_func in CAPTURE_FUNCTIONS:
                try:
                    if await capture_func(page, theme):
                        total_success += 1
                    else:
                        total_failed += 1
                except Exception as e:
                    print(f"  ✗ {name}: {e}")
                    total_failed += 1
            
            await context.close()
        
        await browser.close()
    
    return total_success, total_failed


def verify_screenshots() -> tuple[int, int]:
    """Verify all expected screenshots exist."""
    expected_files = []
    for theme in ["light", "dark"]:
        for name, _ in CAPTURE_FUNCTIONS:
            expected_files.append(OUTPUT_BASE / theme / "admin" / f"{name}.png")
    
    found = 0
    missing = []
    for path in expected_files:
        if path.exists():
            found += 1
        else:
            missing.append(path)
    
    return found, missing


def main() -> int:
    """Main entry point."""
    success, failed = asyncio.run(capture_all_admin_screenshots())
    
    print(f"\n{'='*60}")
    print("CAPTURE SUMMARY")
    print("="*60)
    print(f"Captured: {success}")
    print(f"Failed: {failed}")
    
    # Verify files
    found, missing = verify_screenshots()
    print(f"\nVerification: {found}/{len(CAPTURE_FUNCTIONS) * 2} files exist")
    
    if missing:
        print(f"\nMissing files:")
        for path in missing[:10]:
            print(f"  - {path.relative_to(PROJECT_ROOT)}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")
    
    print(f"\nScreenshots saved to: {OUTPUT_BASE.relative_to(PROJECT_ROOT)}/*/admin/")
    print("="*60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
