#!/usr/bin/env python3
"""
Capture Jobs page screenshots for help documentation.

This script captures all 12 Jobs-related screenshots in both light and dark themes.

Usage:
    python3 scripts/capture_jobs_screenshots.py
    
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

# Job IDs from screenshot fixtures
JOB_IDS = {
    "queued": "screenshot-queued-0005",
    "running": "screenshot-67pct-0001",  # 67% progress
    "downloading": "screenshot-downloading-0006",
    "restoring": "screenshot-restoring-0007",
    "failed": "screenshot-failed-0003",
    "canceling": "screenshot-canceling-0002",
}


async def login(page: Page, username: str = "devuser", password: str = "PullDB_Dev2025!") -> bool:
    """Login to the web UI."""
    await page.goto(f"{BASE_URL}/web/login")
    await page.wait_for_load_state("networkidle")
    
    # Fill login form
    await page.fill('input[name="username"]', username)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    
    # Wait for redirect
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(0.5)
    
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


async def capture_jobs_list_active(page: Page, theme: str) -> bool:
    """Capture jobs list with active tab."""
    await page.goto(f"{BASE_URL}/web/jobs?view=active")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "list-active.png"
    return await capture(page, output, "Jobs list - Active tab")


async def capture_jobs_list_empty(page: Page, theme: str) -> bool:
    """Capture jobs list with empty state (filter to show no results)."""
    # Navigate to jobs list and use a filter that returns no results
    await page.goto(f"{BASE_URL}/web/jobs?view=active&status=CANCELED")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "list-empty.png"
    return await capture(page, output, "Jobs list - Empty state")


async def capture_jobs_list_history(page: Page, theme: str) -> bool:
    """Capture jobs list with history tab."""
    await page.goto(f"{BASE_URL}/web/jobs?view=history")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "list-history.png"
    return await capture(page, output, "Jobs list - History tab")


async def capture_jobs_filters_open(page: Page, theme: str) -> bool:
    """Capture jobs list with filters panel open."""
    await page.goto(f"{BASE_URL}/web/jobs")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    
    # Try to click filters toggle button
    try:
        filter_btn = page.locator('[data-action="toggle-filters"], .filter-toggle, #filterToggle, button:has-text("Filters")')
        if await filter_btn.count() > 0:
            await filter_btn.first.click()
            await asyncio.sleep(0.3)
    except Exception:
        pass  # Filters may already be visible or structured differently
    
    await asyncio.sleep(0.3)
    output = OUTPUT_BASE / theme / "jobs" / "filters-open.png"
    return await capture(page, output, "Jobs list - Filters open")


async def capture_job_detail_queued(page: Page, theme: str) -> bool:
    """Capture job detail page for QUEUED job."""
    job_id = JOB_IDS["queued"]
    await page.goto(f"{BASE_URL}/web/jobs/{job_id}")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "detail-queued.png"
    return await capture(page, output, "Job detail - QUEUED")


async def capture_job_detail_running(page: Page, theme: str) -> bool:
    """Capture job detail page for RUNNING job (67% progress)."""
    job_id = JOB_IDS["running"]
    await page.goto(f"{BASE_URL}/web/jobs/{job_id}")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "detail-running.png"
    return await capture(page, output, "Job detail - RUNNING (67%)")


async def capture_job_detail_download_progress(page: Page, theme: str) -> bool:
    """Capture job detail page showing download progress."""
    job_id = JOB_IDS["downloading"]
    await page.goto(f"{BASE_URL}/web/jobs/{job_id}")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "detail-download-progress.png"
    return await capture(page, output, "Job detail - Download progress")


async def capture_job_detail_restore_progress(page: Page, theme: str) -> bool:
    """Capture job detail page showing restore progress."""
    job_id = JOB_IDS["restoring"]
    await page.goto(f"{BASE_URL}/web/jobs/{job_id}")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "detail-restore-progress.png"
    return await capture(page, output, "Job detail - Restore progress")


async def capture_job_detail_complete(page: Page, theme: str) -> bool:
    """Capture job detail page for COMPLETE job.
    
    NOTE: The screenshot scenario doesn't include a COMPLETE job.
    We'll navigate to history and find one, or show a placeholder.
    """
    # Try to find a completed job from history
    await page.goto(f"{BASE_URL}/web/jobs?view=history&status=COMPLETE")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # Try to click on the first completed job in the table
    try:
        job_link = page.locator('a[href*="/web/jobs/"][href*="complete"], table tbody tr:first-child a, .job-row:first-child a')
        if await job_link.count() > 0:
            href = await job_link.first.get_attribute('href')
            if href:
                await page.goto(f"{BASE_URL}{href}")
                await page.wait_for_load_state("networkidle")
                await set_theme(page, theme)
                await asyncio.sleep(0.5)
    except Exception:
        pass
    
    output = OUTPUT_BASE / theme / "jobs" / "detail-complete.png"
    return await capture(page, output, "Job detail - COMPLETE")


async def capture_job_detail_failed(page: Page, theme: str) -> bool:
    """Capture job detail page for FAILED job."""
    job_id = JOB_IDS["failed"]
    await page.goto(f"{BASE_URL}/web/jobs/{job_id}")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "detail-failed.png"
    return await capture(page, output, "Job detail - FAILED")


async def capture_job_detail_canceling(page: Page, theme: str) -> bool:
    """Capture job detail page for CANCELING job."""
    job_id = JOB_IDS["canceling"]
    await page.goto(f"{BASE_URL}/web/jobs/{job_id}")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    output = OUTPUT_BASE / theme / "jobs" / "detail-canceling.png"
    return await capture(page, output, "Job detail - CANCELING")


async def capture_jobs_bulk_actions(page: Page, theme: str) -> bool:
    """Capture jobs list with multiple jobs selected showing bulk actions."""
    await page.goto(f"{BASE_URL}/web/jobs?view=history")
    await page.wait_for_load_state("networkidle")
    await set_theme(page, theme)
    await asyncio.sleep(0.5)
    
    # Try to select multiple checkboxes
    try:
        checkboxes = page.locator('input[type="checkbox"][name*="job"], input[type="checkbox"].job-checkbox, table tbody input[type="checkbox"]')
        count = await checkboxes.count()
        for i in range(min(3, count)):
            await checkboxes.nth(i).check()
            await asyncio.sleep(0.1)
    except Exception:
        pass
    
    await asyncio.sleep(0.3)
    output = OUTPUT_BASE / theme / "jobs" / "bulk-actions.png"
    return await capture(page, output, "Jobs list - Bulk actions")


async def main() -> int:
    """Main capture function."""
    print("=" * 60)
    print("Capturing Jobs Page Screenshots")
    print("=" * 60)
    
    # All capture functions in order
    capture_funcs = [
        capture_jobs_list_active,
        capture_jobs_list_empty,
        capture_jobs_list_history,
        capture_jobs_filters_open,
        capture_job_detail_queued,
        capture_job_detail_running,
        capture_job_detail_download_progress,
        capture_job_detail_restore_progress,
        capture_job_detail_complete,
        capture_job_detail_failed,
        capture_job_detail_canceling,
        capture_jobs_bulk_actions,
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
            for func in capture_funcs:
                try:
                    if await func(page, theme):
                        total_success += 1
                    else:
                        total_failed += 1
                except Exception as e:
                    print(f"  ✗ Error in {func.__name__}: {e}")
                    total_failed += 1
            
            await context.close()
        
        await browser.close()
    
    print(f"\n{'='*60}")
    print(f"Complete! Success: {total_success}, Failed: {total_failed}")
    print(f"Output directory: pulldb/web/static/help/screenshots/")
    print("=" * 60)
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
