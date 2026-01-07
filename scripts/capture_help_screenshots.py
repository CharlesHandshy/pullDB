#!/usr/bin/env python3
"""
Capture help documentation screenshots using Playwright.

This script:
1. Starts the pullDB web server in dev_mocks simulation mode
2. Authenticates as different user roles (USER, MANAGER, ADMIN)
3. Captures screenshots at 1280x720 viewport
4. Handles both light and dark themes
5. Saves to pulldb/web/help/screenshots/

Usage:
    python scripts/capture_help_screenshots.py
    python scripts/capture_help_screenshots.py --theme dark
    python scripts/capture_help_screenshots.py --role admin --theme light

Requirements:
    pip install playwright httpx
    playwright install chromium
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

async_playwright_func = None
try:
    from playwright.async_api import async_playwright as _async_pw
    async_playwright_func = _async_pw
except ImportError:
    pass

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Viewport for help screenshots
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720

# User credentials for different roles
USER_CREDENTIALS = {
    "user": {"username": "user", "password": "user"},
    "manager": {"username": "manager", "password": "manager"},
    "admin": {"username": "admin", "password": "admin"},
}


@dataclass
class ScreenshotSpec:
    """Specification for a screenshot to capture."""
    
    route: str
    filename: str
    role: str = "user"
    wait_selector: str | None = None
    description: str = ""


# Screenshots to capture organized by category
SCREENSHOT_SPECS: list[ScreenshotSpec] = [
    # Common pages
    ScreenshotSpec(
        route="/web/login",
        filename="common/login.png",
        role="user",
        description="Login page",
    ),
    
    # Dashboard
    ScreenshotSpec(
        route="/web/dashboard",
        filename="dashboard/overview.png",
        role="user",
        wait_selector=".stats-bar",
        description="User dashboard overview",
    ),
    
    # Restore pages
    ScreenshotSpec(
        route="/web/restore",
        filename="restore/form.png",
        role="user",
        wait_selector="form",
        description="Restore request form",
    ),
    
    # Jobs pages
    ScreenshotSpec(
        route="/web/jobs",
        filename="jobs/list.png",
        role="user",
        wait_selector=".job-table, .empty-state",
        description="Jobs list view",
    ),
    
    # Profile page
    ScreenshotSpec(
        route="/web/profile",
        filename="profile/settings.png",
        role="user",
        description="User profile settings",
    ),
    
    # Manager pages
    ScreenshotSpec(
        route="/web/manager",
        filename="manager/dashboard.png",
        role="manager",
        description="Manager dashboard",
    ),
    
    # Admin pages
    ScreenshotSpec(
        route="/web/admin/users",
        filename="admin/users.png",
        role="admin",
        wait_selector=".user-table, .admin-content",
        description="Admin user management",
    ),
    ScreenshotSpec(
        route="/web/admin/styleguide",
        filename="admin/styleguide.png",
        role="admin",
        description="Admin style guide",
    ),
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
    """Start the pullDB server in dev_mocks simulation mode."""
    env = os.environ.copy()
    env["PULLDB_SIMULATION"] = "dev_mocks"
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


async def login(page: Page, base_url: str, role: str) -> bool:
    """
    Login as specified role.
    
    Args:
        page: Playwright page
        base_url: Server base URL
        role: User role (user, manager, admin)
    
    Returns:
        True if login successful
    """
    creds = USER_CREDENTIALS.get(role, USER_CREDENTIALS["user"])
    
    await page.goto(f"{base_url}/web/login")
    await page.wait_for_load_state("networkidle")
    
    # Fill login form
    await page.fill('input[name="username"]', creds["username"])
    await page.fill('input[name="password"]', creds["password"])
    await page.click('button[type="submit"]')
    
    # Wait for redirect
    await page.wait_for_load_state("networkidle")
    
    # Check we're logged in (not still on login page)
    return "/login" not in page.url


async def set_theme(page: Page, theme: str) -> None:
    """
    Set the page theme (light or dark).
    
    Args:
        page: Playwright page
        theme: Theme name ('light' or 'dark')
    """
    # Set theme via localStorage and data attribute
    await page.evaluate(f"""
        localStorage.setItem('theme', '{theme}');
        document.documentElement.setAttribute('data-theme', '{theme}');
    """)
    
    # Small delay for CSS transitions
    await asyncio.sleep(0.2)


async def screenshot(
    page: Page,
    base_url: str,
    output_dir: Path,
    spec: ScreenshotSpec,
    theme: str,
) -> bool:
    """
    Capture a single screenshot.
    
    Args:
        page: Playwright page
        base_url: Server base URL
        output_dir: Base output directory
        spec: Screenshot specification
        theme: Theme to use
    
    Returns:
        True if screenshot captured successfully
    """
    print(f"  Capturing: {spec.filename} ({spec.description})")
    
    # Navigate to the route
    try:
        await page.goto(f"{base_url}{spec.route}")
        await page.wait_for_load_state("networkidle")
    except Exception as e:
        print(f"    Warning: Navigation failed: {e}")
        return False
    
    # Set theme
    await set_theme(page, theme)
    
    # Wait for specific selector if provided
    if spec.wait_selector:
        try:
            await page.wait_for_selector(spec.wait_selector, timeout=5000)
        except Exception:
            print(f"    Warning: Selector '{spec.wait_selector}' not found")
    
    # Additional settle time
    await asyncio.sleep(0.5)
    
    # Determine output path
    output_path = output_dir / theme / spec.filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Capture screenshot
    try:
        await page.screenshot(path=str(output_path))
        print(f"    ✓ Saved: {output_path.relative_to(PROJECT_ROOT)}")
        return True
    except Exception as e:
        print(f"    Error: {e}")
        return False


async def capture_screenshots_for_role(
    context: BrowserContext,
    base_url: str,
    output_dir: Path,
    role: str,
    theme: str,
) -> tuple[int, int]:
    """
    Capture all screenshots for a specific role.
    
    Args:
        context: Browser context
        base_url: Server URL
        output_dir: Output directory
        role: User role
        theme: Theme to capture
    
    Returns:
        Tuple of (success_count, fail_count)
    """
    page = await context.new_page()
    await page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
    
    success = 0
    failed = 0
    
    # Get specs for this role
    specs = [s for s in SCREENSHOT_SPECS if s.role == role]
    
    if not specs:
        await page.close()
        return 0, 0
    
    print(f"\nCapturing as {role.upper()} ({theme} theme):")
    
    # Login for this role (skip for login page itself)
    if role != "user" or any(s.route != "/web/login" for s in specs):
        if not await login(page, base_url, role):
            print(f"  Warning: Login failed for {role}")
    
    # Capture each screenshot
    for spec in specs:
        # For login page, don't need to be logged in
        if spec.route == "/web/login":
            # Logout first if logged in
            try:
                await page.goto(f"{base_url}/web/logout")
            except Exception:
                pass
        
        if await screenshot(page, base_url, output_dir, spec, theme):
            success += 1
        else:
            failed += 1
    
    await page.close()
    return success, failed


async def capture_all_screenshots(
    themes: list[str] | None = None,
    roles: list[str] | None = None,
) -> None:
    """
    Main capture function.
    
    Args:
        themes: List of themes to capture (default: both)
        roles: List of roles to capture (default: all)
    """
    if async_playwright_func is None:
        print("ERROR: playwright not installed. Run:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)
    
    if themes is None:
        themes = ["light", "dark"]
    if roles is None:
        roles = list(USER_CREDENTIALS.keys())
    
    output_dir = PROJECT_ROOT / "pulldb" / "web" / "help" / "screenshots"
    base_url = "http://localhost:8000"
    
    print("Starting pullDB server in dev_mocks mode...")
    server_proc = start_server()
    
    try:
        print("Waiting for server to start...")
        if not await wait_for_server(f"{base_url}/health"):
            print("ERROR: Server failed to start")
            server_proc.terminate()
            sys.exit(1)
        
        print("Server started successfully")
        
        total_success = 0
        total_failed = 0
        
        async with async_playwright_func() as p:
            browser = await p.chromium.launch()
            
            for theme in themes:
                print(f"\n{'='*60}")
                print(f"Theme: {theme.upper()}")
                print("="*60)
                
                for role in roles:
                    context = await browser.new_context(
                        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                    )
                    
                    success, failed = await capture_screenshots_for_role(
                        context, base_url, output_dir, role, theme
                    )
                    
                    total_success += success
                    total_failed += failed
                    
                    await context.close()
            
            await browser.close()
        
        print(f"\n{'='*60}")
        print(f"Complete! Success: {total_success}, Failed: {total_failed}")
        print(f"Screenshots saved to: {output_dir.relative_to(PROJECT_ROOT)}/")
        
    finally:
        print("\nStopping server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Capture help documentation screenshots",
    )
    parser.add_argument(
        "--theme",
        choices=["light", "dark", "both"],
        default="both",
        help="Theme to capture (default: both)",
    )
    parser.add_argument(
        "--role",
        choices=["user", "manager", "admin", "all"],
        default="all",
        help="Role to capture screenshots for (default: all)",
    )
    
    args = parser.parse_args()
    
    # Determine themes
    if args.theme == "both":
        themes = ["light", "dark"]
    else:
        themes = [args.theme]
    
    # Determine roles
    if args.role == "all":
        roles = list(USER_CREDENTIALS.keys())
    else:
        roles = [args.role]
    
    asyncio.run(capture_all_screenshots(themes=themes, roles=roles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
