#!/usr/bin/env python3
"""
Capture Manager page screenshots for help documentation.

This script captures 4 manager screenshots in both light and dark themes (8 total).

Screenshots:
    1. overview.png - Manager dashboard with team stats
    2. team-list.png - Team member list with indicators
    3. reset-password.png - Password reset confirmation dialog
    4. temp-password-modal.png - Temporary password assignment modal

Usage:
    python scripts/capture_manager_screenshots.py

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

# Login credentials for dev server (manager user)
DEV_USERNAME = "devmanager"
DEV_PASSWORD = "PullDB_Dev2025!"


async def login(page: Page, username: str = DEV_USERNAME, password: str = DEV_PASSWORD) -> bool:
    """Login to the web UI as manager."""
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
# Manager Page Screenshots
# =============================================================================

async def capture_overview(page: Page, theme: str) -> bool:
    """Capture manager dashboard overview."""
    await page.goto(f"{BASE_URL}/web/manager")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.8)  # Wait for LazyTable to load
    
    output = OUTPUT_BASE / theme / "manager" / "overview.png"
    return await capture(page, output, "Manager dashboard with team stats")


async def capture_team_list(page: Page, theme: str) -> bool:
    """Capture team member list with indicators."""
    await page.goto(f"{BASE_URL}/web/manager")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.8)  # Wait for LazyTable to load
    
    # Scroll to make sure the team table is visible and has content
    team_container = page.locator('#team-table-container')
    if await team_container.count() > 0:
        await team_container.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "manager" / "team-list.png"
    return await capture(page, output, "Team member list with indicators")


async def capture_reset_password(page: Page, theme: str) -> bool:
    """Capture password reset confirmation dialog."""
    await page.goto(f"{BASE_URL}/web/manager")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.8)
    
    # Find and click the reset password button (key icon) for a team member
    # The button has data-action="reset-password"
    reset_btn = page.locator('button[data-action="reset-password"]').first
    if await reset_btn.count() > 0:
        await reset_btn.click()
        await asyncio.sleep(0.5)  # Wait for confirmation dialog to appear
    else:
        print(f"    Note: No reset password button found for {theme} theme")
    
    output = OUTPUT_BASE / theme / "manager" / "reset-password.png"
    return await capture(page, output, "Password reset confirmation dialog")


async def capture_temp_password_modal(page: Page, theme: str) -> bool:
    """Capture temporary password assignment modal."""
    await page.goto(f"{BASE_URL}/web/manager")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.8)
    
    # Find and click the assign temp password button (lock icon) for a team member
    # The button has data-action="assign-temp-password"
    temp_btn = page.locator('button[data-action="assign-temp-password"]').first
    if await temp_btn.count() > 0:
        await temp_btn.click()
        await asyncio.sleep(0.5)  # Wait for confirmation dialog to appear
        
        # Click "Assign Password" in the confirmation dialog
        # The showConfirm uses okText: 'Assign Password'
        confirm_btn = page.locator('button:has-text("Assign Password")')
        if await confirm_btn.count() > 0:
            await confirm_btn.click()
            await asyncio.sleep(0.5)  # Wait for temp password modal to appear
    else:
        print(f"    Note: No assign temp password button found for {theme} theme")
    
    output = OUTPUT_BASE / theme / "manager" / "temp-password-modal.png"
    return await capture(page, output, "Temporary password assignment modal")


# =============================================================================
# Main Capture Functions
# =============================================================================

CAPTURE_FUNCTIONS = [
    ("overview", capture_overview),
    ("team-list", capture_team_list),
    ("reset-password", capture_reset_password),
    ("temp-password-modal", capture_temp_password_modal),
]


async def capture_all_manager_screenshots(themes: list[str] | None = None) -> tuple[int, int]:
    """Capture all manager screenshots for specified themes.
    
    Args:
        themes: List of themes to capture. Defaults to ["light", "dark"].
        
    Returns:
        Tuple of (success_count, failed_count)
    """
    if themes is None:
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
            
            # Login as manager
            print(f"\nLogging in as {DEV_USERNAME}...")
            if not await login(page):
                print("  ERROR: Login failed!")
                await context.close()
                total_failed += len(CAPTURE_FUNCTIONS)
                continue
            print("  ✓ Login successful")
            
            # Capture screenshots
            print(f"\nCapturing manager screenshots ({theme}):")
            
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


def verify_screenshots() -> tuple[int, list[Path]]:
    """Verify all expected screenshots exist."""
    expected_files = []
    for theme in ["light", "dark"]:
        for name, _ in CAPTURE_FUNCTIONS:
            expected_files.append(OUTPUT_BASE / theme / "manager" / f"{name}.png")
    
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
    success, failed = asyncio.run(capture_all_manager_screenshots())
    
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
    
    print(f"\nScreenshots saved to: {OUTPUT_BASE.relative_to(PROJECT_ROOT)}/*/manager/")
    print("="*60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
