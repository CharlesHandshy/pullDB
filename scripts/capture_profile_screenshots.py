#!/usr/bin/env python3
"""
Capture Profile page screenshots for help documentation.

Screenshots to capture:
- overview.png: Profile page default view
- force-password-change.png: Forced password change page  
- password-form.png: Password change form section
- api-keys.png: API keys section
- create-key-modal.png: API key creation (click button to show modal flow)
- maintenance-modal.png: Database maintenance acknowledgment page

Usage:
    python scripts/capture_profile_screenshots.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
except ImportError:
    print("ERROR: playwright not installed. Run:")
    print("  pip install playwright")
    print("  playwright install chromium")
    sys.exit(1)

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Viewport for help screenshots
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720

# Base URL for dev server
BASE_URL = "http://localhost:8111"

# Output directories
OUTPUT_BASE = PROJECT_ROOT / "pulldb" / "web" / "static" / "help" / "screenshots"

# User credentials
USER_CREDENTIALS = {
    "username": "devuser",
    "password": "PullDB_Dev2025!",
}


async def login(page: Page, base_url: str) -> bool:
    """Login as devuser."""
    await page.goto(f"{base_url}/web/login")
    await page.wait_for_load_state("networkidle")
    
    await page.fill('input[name="username"]', USER_CREDENTIALS["username"])
    await page.fill('input[name="password"]', USER_CREDENTIALS["password"])
    await page.click('button[type="submit"]')
    
    await page.wait_for_load_state("networkidle")
    return "/login" not in page.url


async def set_theme(page: Page, theme: str) -> None:
    """Set the page theme (light or dark)."""
    await page.evaluate(f"""
        localStorage.setItem('theme', '{theme}');
        document.documentElement.setAttribute('data-theme', '{theme}');
    """)
    await asyncio.sleep(0.3)


async def capture_profile_overview(page: Page, output_dir: Path, theme: str) -> bool:
    """Capture profile overview screenshot."""
    print(f"  Capturing: overview.png ({theme})")
    
    await page.goto(f"{BASE_URL}/web/auth/profile")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    output_path = output_dir / theme / "profile" / "overview.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    await page.screenshot(path=str(output_path))
    print(f"    ✓ Saved: {output_path.relative_to(PROJECT_ROOT)}")
    return True


async def capture_force_password_change(page: Page, output_dir: Path, theme: str) -> bool:
    """Capture forced password change page screenshot."""
    print(f"  Capturing: force-password-change.png ({theme})")
    
    # Navigate to the change-password page (simulating forced redirect)
    await page.goto(f"{BASE_URL}/web/change-password")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    output_path = output_dir / theme / "profile" / "force-password-change.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    await page.screenshot(path=str(output_path))
    print(f"    ✓ Saved: {output_path.relative_to(PROJECT_ROOT)}")
    return True


async def capture_password_form(page: Page, output_dir: Path, theme: str) -> bool:
    """Capture password change form section on profile page."""
    print(f"  Capturing: password-form.png ({theme})")
    
    await page.goto(f"{BASE_URL}/web/auth/profile")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    
    # Scroll to the Change Password card
    password_section = page.locator("text=Change Password").first
    if await password_section.count() > 0:
        await password_section.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
    
    output_path = output_dir / theme / "profile" / "password-form.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    await page.screenshot(path=str(output_path))
    print(f"    ✓ Saved: {output_path.relative_to(PROJECT_ROOT)}")
    return True


async def capture_api_keys(page: Page, output_dir: Path, theme: str) -> bool:
    """Capture API keys section on profile page."""
    print(f"  Capturing: api-keys.png ({theme})")
    
    await page.goto(f"{BASE_URL}/web/auth/profile")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    
    # Scroll to the CLI Credentials card (which contains API keys)
    api_section = page.locator("text=CLI Credentials").first
    if await api_section.count() > 0:
        await api_section.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
    
    output_path = output_dir / theme / "profile" / "api-keys.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    await page.screenshot(path=str(output_path))
    print(f"    ✓ Saved: {output_path.relative_to(PROJECT_ROOT)}")
    return True


async def capture_create_key_modal(page: Page, output_dir: Path, theme: str) -> bool:
    """Capture API key creation - shows the form/button area.
    
    Note: The actual API key generation triggers a file download, not a modal.
    We capture the form area showing the generate button.
    """
    print(f"  Capturing: create-key-modal.png ({theme})")
    
    await page.goto(f"{BASE_URL}/web/auth/profile")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    
    # Scroll to the CLI Credentials section with the generate button
    api_section = page.locator("text=CLI Credentials").first
    if await api_section.count() > 0:
        await api_section.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
    
    # Find and highlight the generate button area
    generate_btn = page.locator("button:has-text('Generate')")
    if await generate_btn.count() > 0:
        await generate_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
    
    output_path = output_dir / theme / "profile" / "create-key-modal.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    await page.screenshot(path=str(output_path))
    print(f"    ✓ Saved: {output_path.relative_to(PROJECT_ROOT)}")
    return True


async def capture_maintenance_modal(page: Page, output_dir: Path, theme: str) -> bool:
    """Capture database maintenance acknowledgment page."""
    print(f"  Capturing: maintenance-modal.png ({theme})")
    
    # Navigate directly to the maintenance page
    await page.goto(f"{BASE_URL}/web/maintenance")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    output_path = output_dir / theme / "profile" / "maintenance-modal.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    await page.screenshot(path=str(output_path))
    print(f"    ✓ Saved: {output_path.relative_to(PROJECT_ROOT)}")
    return True


async def capture_all_profile_screenshots() -> None:
    """Capture all profile screenshots for both themes."""
    print("=" * 60)
    print("Profile Screenshots Capture")
    print("=" * 60)
    
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
            
            # Login
            print("\nLogging in as devuser...")
            if not await login(page, BASE_URL):
                print("  ERROR: Login failed!")
                await context.close()
                continue
            print("  ✓ Login successful")
            
            # Capture screenshots
            print(f"\nCapturing profile screenshots ({theme}):")
            
            capture_funcs = [
                capture_profile_overview,
                capture_force_password_change,
                capture_password_form,
                capture_api_keys,
                capture_create_key_modal,
                capture_maintenance_modal,
            ]
            
            for capture_func in capture_funcs:
                try:
                    if await capture_func(page, OUTPUT_BASE, theme):
                        total_success += 1
                    else:
                        total_failed += 1
                except Exception as e:
                    print(f"    ERROR: {e}")
                    total_failed += 1
            
            await context.close()
        
        await browser.close()
    
    print(f"\n{'='*60}")
    print(f"Complete! Success: {total_success}, Failed: {total_failed}")
    print(f"Screenshots saved to: {OUTPUT_BASE.relative_to(PROJECT_ROOT)}/")
    print("="*60)


def main() -> int:
    """Main entry point."""
    asyncio.run(capture_all_profile_screenshots())
    return 0


if __name__ == "__main__":
    sys.exit(main())
