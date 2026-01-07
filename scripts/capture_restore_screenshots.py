#!/usr/bin/env python3
"""
Capture Restore Wizard screenshots for help documentation.

This script captures all 6 Restore Wizard screenshots in both light and dark themes (12 total).

Usage:
    python3 scripts/capture_restore_screenshots.py
    
Prerequisites:
    - Dev server running: python3 scripts/dev_server.py --scenario screenshots
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

# Login credentials for dev server
DEV_USERNAME = "devuser"
DEV_PASSWORD = "PullDB_Dev2025!"


async def login(page: Page, username: str = DEV_USERNAME, password: str = DEV_PASSWORD) -> bool:
    """Login to the web UI."""
    await page.goto(f"{BASE_URL}/web/login")
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(0.3)
    
    # Fill login form
    await page.fill('input[name="username"]', username)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    
    # Wait for redirect - use domcontentloaded instead of networkidle for speed
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
    await asyncio.sleep(0.3)


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


async def capture_step1_customer(page: Page, theme: str) -> bool:
    """Capture Step 1: Customer search with autocomplete results showing."""
    await page.goto(f"{BASE_URL}/web/restore")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    # Type in the customer search to trigger autocomplete
    search_input = page.locator('#customer-search')
    await search_input.fill('')  # Clear first
    await search_input.type('acm', delay=100)  # Type slowly to trigger autocomplete
    
    # Wait for autocomplete results to appear
    await asyncio.sleep(0.8)
    
    # Try to wait for results to be visible
    try:
        await page.wait_for_selector('#customer-results:not(:empty)', timeout=3000)
        await asyncio.sleep(0.3)
    except Exception:
        pass  # Results may display differently
    
    output = OUTPUT_BASE / theme / "restore" / "step1-customer.png"
    return await capture(page, output, "Step 1 - Customer search with autocomplete")


async def capture_step1_no_results(page: Page, theme: str) -> bool:
    """Capture Step 1: Customer search showing 'no results' state."""
    await page.goto(f"{BASE_URL}/web/restore")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    # Search for something that won't match
    search_input = page.locator('#customer-search')
    await search_input.fill('')
    await search_input.type('zzzznotfound', delay=50)
    
    # Wait for no results state
    await asyncio.sleep(1.0)
    
    output = OUTPUT_BASE / theme / "restore" / "step1-no-results.png"
    return await capture(page, output, "Step 1 - No results found")


async def capture_step2_backups(page: Page, theme: str) -> bool:
    """Capture Step 2: After selecting a customer, showing backup list."""
    await page.goto(f"{BASE_URL}/web/restore")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    # Search for and select a customer
    search_input = page.locator('#customer-search')
    await search_input.fill('')
    await search_input.type('acm', delay=100)
    await asyncio.sleep(0.8)
    
    # Try to click on the first result in autocomplete
    try:
        # Wait for results and click first one
        first_result = page.locator('#customer-results .search-result-item').first
        if await first_result.count() > 0:
            await first_result.click()
        else:
            # Alternative: try clicking any clickable result
            result = page.locator('#customer-results [data-value], #customer-results button, #customer-results li').first
            if await result.count() > 0:
                await result.click()
    except Exception:
        pass
    
    # Wait for backups to load
    await asyncio.sleep(1.5)
    
    # Re-apply theme after DOM changes
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "restore" / "step2-backups.png"
    return await capture(page, output, "Step 2 - Backup list")


async def capture_step3_options(page: Page, theme: str) -> bool:
    """Capture Step 3: After selecting backup, showing target host and retention options."""
    await page.goto(f"{BASE_URL}/web/restore")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    # Search for and select a customer
    search_input = page.locator('#customer-search')
    await search_input.fill('')
    await search_input.type('acm', delay=100)
    await asyncio.sleep(0.8)
    
    # Click first result
    try:
        first_result = page.locator('#customer-results .search-result-item, #customer-results [data-value], #customer-results button, #customer-results li').first
        if await first_result.count() > 0:
            await first_result.click()
    except Exception:
        pass
    
    # Wait for backups to load
    await asyncio.sleep(1.5)
    
    # Select first backup
    try:
        backup_item = page.locator('#backup-list .backup-item, #backup-list button, #backup-list [data-backup]').first
        if await backup_item.count() > 0:
            await backup_item.click()
    except Exception:
        pass
    
    await asyncio.sleep(0.5)
    
    # Re-apply theme after DOM changes
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    # Scroll to show target configuration section
    try:
        target_section = page.locator('#target-config-title, .restore-section:nth-child(2)')
        if await target_section.count() > 0:
            await target_section.scroll_into_view_if_needed()
    except Exception:
        pass
    
    await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "restore" / "step3-options.png"
    return await capture(page, output, "Step 3 - Target configuration options")


async def capture_step4_confirm(page: Page, theme: str) -> bool:
    """Capture Step 4: Final confirmation summary before submission."""
    await page.goto(f"{BASE_URL}/web/restore")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    # Search for and select a customer
    search_input = page.locator('#customer-search')
    await search_input.fill('')
    await search_input.type('acm', delay=100)
    await asyncio.sleep(0.8)
    
    # Click first result
    try:
        first_result = page.locator('#customer-results .search-result-item, #customer-results [data-value], #customer-results button, #customer-results li').first
        if await first_result.count() > 0:
            await first_result.click()
    except Exception:
        pass
    
    await asyncio.sleep(1.5)
    
    # Select first backup
    try:
        backup_item = page.locator('#backup-list .backup-item, #backup-list button, #backup-list [data-backup]').first
        if await backup_item.count() > 0:
            await backup_item.click()
    except Exception:
        pass
    
    await asyncio.sleep(0.5)
    
    # Select a target host (first available)
    try:
        host_select = page.locator('#dbhost')
        if await host_select.count() > 0:
            options = await host_select.locator('option').all()
            # Select first non-empty option
            for opt in options:
                value = await opt.get_attribute('value')
                if value:
                    await host_select.select_option(value=value)
                    break
    except Exception:
        pass
    
    await asyncio.sleep(0.3)
    
    # Re-apply theme
    await set_theme(page, theme)
    
    # Scroll to show submit button
    try:
        submit_btn = page.locator('#submit-btn, button[type="submit"]')
        if await submit_btn.count() > 0:
            await submit_btn.scroll_into_view_if_needed()
    except Exception:
        pass
    
    await asyncio.sleep(0.3)
    
    output = OUTPUT_BASE / theme / "restore" / "step4-confirm.png"
    return await capture(page, output, "Step 4 - Final confirmation")


async def capture_success_toast(page: Page, theme: str) -> bool:
    """Capture success notification after form submission.
    
    Note: We simulate this by injecting a toast notification since actually
    submitting the form would create a job and redirect.
    """
    await page.goto(f"{BASE_URL}/web/restore")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.3)
    
    # Inject a simulated success toast notification
    await page.evaluate("""
        // Create toast container if it doesn't exist
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            container.style.cssText = 'position: fixed; top: 1rem; right: 1rem; z-index: 9999; display: flex; flex-direction: column; gap: 0.5rem;';
            document.body.appendChild(container);
        }
        
        // Create success toast
        const toast = document.createElement('div');
        toast.className = 'toast toast-success';
        toast.style.cssText = `
            background: var(--color-success, #22c55e);
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 0.5rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-width: 300px;
            font-weight: 500;
        `;
        
        // Add check icon
        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('viewBox', '0 0 24 24');
        icon.setAttribute('width', '20');
        icon.setAttribute('height', '20');
        icon.setAttribute('fill', 'none');
        icon.setAttribute('stroke', 'currentColor');
        icon.setAttribute('stroke-width', '2');
        icon.innerHTML = '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>';
        
        const text = document.createElement('span');
        text.textContent = 'Restore job queued successfully!';
        
        toast.appendChild(icon);
        toast.appendChild(text);
        container.appendChild(toast);
    """)
    
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "restore" / "success-toast.png"
    return await capture(page, output, "Success toast notification")


async def main() -> int:
    """Main capture function."""
    print("=" * 60)
    print("Capturing Restore Wizard Screenshots")
    print("=" * 60)
    
    # All capture functions in order
    capture_funcs = [
        ("step1-customer", capture_step1_customer),
        ("step1-no-results", capture_step1_no_results),
        ("step2-backups", capture_step2_backups),
        ("step3-options", capture_step3_options),
        ("step4-confirm", capture_step4_confirm),
        ("success-toast", capture_success_toast),
    ]
    
    themes = ["light", "dark"]
    total_success = 0
    total_failed = 0
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        for theme in themes:
            print(f"\n{'='*60}")
            print(f"Theme: {theme.upper()}")
            print("=" * 60)
            
            context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
            )
            page = await context.new_page()
            
            # Login
            print("\nLogging in...")
            if not await login(page):
                print("WARNING: Login may have failed, continuing anyway...")
            
            # Capture all screenshots
            for name, func in capture_funcs:
                try:
                    if await func(page, theme):
                        total_success += 1
                    else:
                        total_failed += 1
                except Exception as e:
                    print(f"  ✗ Error in {name}: {e}")
                    total_failed += 1
            
            await context.close()
        
        await browser.close()
    
    print(f"\n{'='*60}")
    print(f"Complete! Success: {total_success}, Failed: {total_failed}")
    print(f"Output directory: pulldb/web/static/help/screenshots/")
    print("=" * 60)
    
    # List created files
    print("\nFiles created:")
    for theme in themes:
        theme_dir = OUTPUT_BASE / theme / "restore"
        if theme_dir.exists():
            for f in sorted(theme_dir.glob("*.png")):
                print(f"  {f.relative_to(PROJECT_ROOT)}")
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
