#!/usr/bin/env python3
"""Capture style guide screenshots using Playwright.

This script:
1. Starts the pullDB web server (simulation mode)
2. Logs in as admin
3. Navigates to /web/admin/styleguide
4. Captures full page and section screenshots
5. Saves to docs/screenshots/

Usage:
    python scripts/capture_styleguide.py

Requirements:
    pip install playwright httpx
    playwright install chromium
"""
# Script file - type annotations for playwright are optional

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from playwright.async_api import Page

async_playwright_func = None
try:
    from playwright.async_api import async_playwright as _async_pw
    async_playwright_func = _async_pw
except ImportError:
    pass

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Section IDs to capture
SECTIONS = [
    ("colors", "Color Palette"),
    ("typography", "Typography"),
    ("spacing", "Spacing Scale"),
    ("buttons", "Buttons"),
    ("badges", "Badges"),
    ("cards", "Cards"),
    ("tables", "Tables"),
    ("forms", "Forms"),
    ("alerts", "Alerts"),
    ("empty-states", "Empty States"),
]


async def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Wait for server to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code in (200, 302, 303):
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


def start_server() -> subprocess.Popen[bytes]:
    """Start the pullDB server in simulation mode."""
    env = os.environ.copy()
    env["PULLDB_SIMULATION"] = "true"
    env["PULLDB_WEB_SECRET_KEY"] = "test-secret-key-for-screenshots"

    cmd = [
        sys.executable,
        "-m", "uvicorn",
        "pulldb.api.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def capture_section(
    page: Page, output_dir: Path, section_id: str, name: str
) -> None:
    """Capture a single section screenshot."""
    print(f"Capturing {name}...")
    try:
        element = await page.query_selector(f"#{section_id}")
        if element:
            await element.screenshot(
                path=str(output_dir / f"styleguide-{section_id}.png")
            )
        else:
            print(f"  Warning: Section #{section_id} not found")
    except Exception as e:
        print(f"  Warning: Could not capture {name}: {e}")


async def capture_all_screenshots(
    page: Page, output_dir: Path, base_url: str
) -> None:
    """Capture all screenshots from the style guide page."""
    # Login
    print("Logging in...")
    await page.goto(f"{base_url}/web/login")
    await page.fill('input[name="username"]', "admin")
    await page.fill('input[name="password"]', "admin")
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")

    # Navigate to style guide
    print("Navigating to style guide...")
    await page.goto(f"{base_url}/web/admin/styleguide")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1)  # Let animations settle

    # Full page
    print("Capturing full page...")
    await page.screenshot(path=str(output_dir / "styleguide-full.png"), full_page=True)

    # Individual sections
    for section_id, section_name in SECTIONS:
        await capture_section(page, output_dir, section_id, section_name)

    # Mobile viewport
    print("Capturing mobile view...")
    await page.set_viewport_size({"width": 375, "height": 812})
    mobile_path = str(output_dir / "styleguide-mobile.png")
    await page.screenshot(path=mobile_path, full_page=True)

    # Tablet viewport
    print("Capturing tablet view...")
    await page.set_viewport_size({"width": 768, "height": 1024})
    tablet_path = str(output_dir / "styleguide-tablet.png")
    await page.screenshot(path=tablet_path, full_page=True)


async def capture_screenshots() -> None:
    """Main capture function."""
    if async_playwright_func is None:
        print("ERROR: playwright not installed. Run:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    output_dir = PROJECT_ROOT / "docs" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = "http://localhost:8000"

    print("Starting pullDB server in simulation mode...")
    server_proc = start_server()

    try:
        print("Waiting for server to start...")
        if not await wait_for_server(f"{base_url}/health"):
            print("ERROR: Server failed to start")
            server_proc.terminate()
            sys.exit(1)

        print("Server started successfully")

        async with async_playwright_func() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()

            await capture_all_screenshots(page, output_dir, base_url)

            await browser.close()

        print(f"\n✓ Screenshots saved to {output_dir}/")
        print("\nFiles created:")
        for f in sorted(output_dir.glob("styleguide-*.png")):
            size = f.stat().st_size / 1024
            print(f"  {f.name} ({size:.1f} KB)")

    finally:
        print("\nStopping server...")
        server_proc.terminate()
        server_proc.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(capture_screenshots())

