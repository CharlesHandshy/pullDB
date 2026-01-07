#!/usr/bin/env python3
"""
Capture Common category screenshots for help documentation.

This script captures the 9 common screenshots in both light and dark themes.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

# Configuration
BASE_URL = "http://127.0.0.1:8111"
OUTPUT_DIR = Path(__file__).parent.parent / "pulldb" / "web" / "static" / "help" / "screenshots"
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720

# User credentials
USERS = {
    "user": {"username": "devuser", "password": "PullDB_Dev2025!"},
    "admin": {"username": "devadmin", "password": "PullDB_Dev2025!"},
}

# Screenshot specifications for Common category
SCREENSHOTS = [
    # 1. Login page - empty form
    {
        "filename": "login.png",
        "route": "/web/login",
        "role": None,  # Logged out
        "setup": None,
        "description": "Login page with empty form",
    },
    # 2. Login error - after failed login
    {
        "filename": "login-error.png",
        "route": "/web/login",
        "role": None,
        "setup": "login_error",
        "description": "Login page showing error after failed attempt",
    },
    # 3. Sidebar expanded
    {
        "filename": "sidebar-expanded.png",
        "route": "/web/dashboard",
        "role": "user",
        "setup": "sidebar_open",
        "description": "Dashboard with sidebar expanded",
    },
    # 4. Sidebar collapsed
    {
        "filename": "sidebar-collapsed.png",
        "route": "/web/dashboard",
        "role": "user",
        "setup": "sidebar_collapsed",
        "description": "Dashboard with sidebar collapsed",
    },
    # 5. 404 page
    {
        "filename": "404.png",
        "route": "/web/nonexistent-page-12345",
        "role": "user",
        "setup": None,
        "description": "404 Not Found page",
    },
    # 6. 500 error page
    {
        "filename": "500.png",
        "route": "/web/_dev/error/500",  # Dev server error endpoint
        "role": "user",
        "setup": None,
        "description": "500 Internal Server Error page",
    },
    # 7. 403 forbidden
    {
        "filename": "403.png",
        "route": "/web/admin/users",  # Admin page accessed as regular user
        "role": "user",
        "setup": None,
        "description": "403 Forbidden page (user accessing admin)",
    },
    # 8. Table filter dropdown
    {
        "filename": "table-filter-dropdown.png",
        "route": "/web/admin/users",
        "role": "admin",
        "setup": "open_filter",
        "description": "Admin users table with filter dropdown open",
    },
    # 9. Table sorted
    {
        "filename": "table-sorted.png",
        "route": "/web/jobs",
        "role": "user",
        "setup": "sort_table",
        "description": "Jobs table sorted by column",
    },
]


async def login(page, role):
    """Login as specified role."""
    creds = USERS.get(role)
    if not creds:
        print(f"  Unknown role: {role}")
        return False
    
    await page.goto(f"{BASE_URL}/web/login")
    await page.wait_for_load_state("networkidle")
    
    # Fill login form
    await page.fill('input[name="username"]', creds["username"])
    await page.fill('input[name="password"]', creds["password"])
    await page.click('button[type="submit"]')
    
    # Wait for redirect
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(0.5)
    
    # Check if logged in
    if "/login" in page.url:
        print(f"  WARNING: Login failed for {role}")
        return False
    
    return True


async def logout(page):
    """Logout current user."""
    try:
        await page.goto(f"{BASE_URL}/web/logout")
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass


async def set_theme(page, theme):
    """Set light or dark theme."""
    # First check current theme
    current_theme = await page.evaluate("""
        () => document.documentElement.getAttribute('data-theme') || 'light'
    """)
    
    if current_theme != theme:
        # Use the toggle button if available, it handles all state correctly
        toggle_btn = await page.query_selector('button[title*="dark"], button:has-text("Toggle dark mode"), [data-theme-toggle]')
        if toggle_btn:
            await toggle_btn.click()
            await asyncio.sleep(0.3)
        else:
            # Fallback to direct manipulation
            await page.evaluate(f"""
                localStorage.setItem('theme', '{theme}');
                document.documentElement.setAttribute('data-theme', '{theme}');
            """)
    
    # Verify theme was set
    await page.evaluate(f"""
        localStorage.setItem('theme', '{theme}');
        document.documentElement.setAttribute('data-theme', '{theme}');
    """)
    await asyncio.sleep(0.3)


async def setup_screenshot(page, setup_type):
    """Perform special setup for certain screenshots."""
    if setup_type == "login_error":
        # Submit form with wrong credentials
        await page.fill('input[name="username"]', "wronguser")
        await page.fill('input[name="password"]', "wrongpassword")
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(0.5)
        
    elif setup_type == "sidebar_open":
        # Ensure sidebar is expanded
        try:
            # Look for sidebar toggle and make sure it's expanded
            sidebar = await page.query_selector('[data-sidebar], .sidebar, nav.sidebar')
            if sidebar:
                is_collapsed = await page.evaluate("""
                    () => {
                        const sidebar = document.querySelector('[data-sidebar], .sidebar, nav.sidebar');
                        return sidebar && sidebar.classList.contains('collapsed');
                    }
                """)
                if is_collapsed:
                    toggle = await page.query_selector('[data-sidebar-toggle], .sidebar-toggle')
                    if toggle:
                        await toggle.click()
                        await asyncio.sleep(0.3)
        except Exception as e:
            print(f"    Note: Could not manipulate sidebar: {e}")
            
    elif setup_type == "sidebar_collapsed":
        # Collapse the sidebar
        try:
            await page.evaluate("""
                () => {
                    const sidebar = document.querySelector('[data-sidebar], .sidebar, nav.sidebar');
                    if (sidebar) {
                        sidebar.classList.add('collapsed');
                    }
                    // Also try toggle button
                    const toggle = document.querySelector('[data-sidebar-toggle], .sidebar-toggle');
                    if (toggle && !document.querySelector('.sidebar.collapsed, [data-sidebar].collapsed')) {
                        toggle.click();
                    }
                }
            """)
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"    Note: Could not collapse sidebar: {e}")
            
    elif setup_type == "open_filter":
        # Open filter dropdown on users table
        try:
            # Wait for table to load
            await page.wait_for_selector('table, .data-table', timeout=5000)
            await asyncio.sleep(0.5)
            
            # Look for filter button/dropdown
            filter_btn = await page.query_selector('[data-filter], .filter-button, .filter-dropdown, button:has-text("Filter")')
            if filter_btn:
                await filter_btn.click()
                await asyncio.sleep(0.3)
            else:
                # Try to find any dropdown trigger
                dropdown = await page.query_selector('.dropdown-toggle, [data-dropdown]')
                if dropdown:
                    await dropdown.click()
                    await asyncio.sleep(0.3)
        except Exception as e:
            print(f"    Note: Could not open filter dropdown: {e}")
            
    elif setup_type == "sort_table":
        # Click a column header to sort
        try:
            # Wait for table
            await page.wait_for_selector('table, .data-table', timeout=5000)
            await asyncio.sleep(0.5)
            
            # Find sortable column header
            header = await page.query_selector('th[data-sort], th.sortable, thead th')
            if header:
                await header.click()
                await asyncio.sleep(0.3)
        except Exception as e:
            print(f"    Note: Could not sort table: {e}")


async def capture_screenshot(page, spec, theme, output_base):
    """Capture a single screenshot."""
    filename = spec["filename"]
    route = spec["route"]
    role = spec.get("role")
    setup = spec.get("setup")
    desc = spec.get("description", filename)
    
    print(f"  [{theme}] Capturing: {filename} - {desc}")
    
    # Navigate to route
    try:
        await page.goto(f"{BASE_URL}{route}")
        await page.wait_for_load_state("networkidle")
    except Exception as e:
        print(f"    ERROR: Navigation failed - {e}")
        return False
    
    # Set theme
    await set_theme(page, theme)
    
    # Perform any special setup
    if setup:
        await setup_screenshot(page, setup)
    
    # Give time for any animations
    await asyncio.sleep(0.5)
    
    # Determine output path
    output_path = output_base / theme / "common" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Capture screenshot
    try:
        await page.screenshot(path=str(output_path))
        size = output_path.stat().st_size
        print(f"    ✓ Saved: {output_path.relative_to(output_base.parent.parent.parent.parent.parent)} ({size:,} bytes)")
        return True
    except Exception as e:
        print(f"    ERROR: {e}")
        return False


async def main():
    """Main capture function."""
    print("=" * 60)
    print("  Capturing Common Screenshots")
    print("=" * 60)
    print()
    
    # Ensure output directories exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "light" / "common").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "dark" / "common").mkdir(parents=True, exist_ok=True)
    
    results = {"success": [], "failed": []}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Process screenshots grouped by role to minimize logins
        role_groups = {}
        for spec in SCREENSHOTS:
            role = spec.get("role")
            if role not in role_groups:
                role_groups[role] = []
            role_groups[role].append(spec)
        
        for theme in ["light", "dark"]:
            print(f"\n{'=' * 40}")
            print(f"  Theme: {theme.upper()}")
            print(f"{'=' * 40}")
            
            for role, specs in role_groups.items():
                print(f"\n  Role: {role or 'logged out'}")
                print(f"  {'-' * 30}")
                
                # Create fresh context for each role
                context = await browser.new_context(
                    viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
                )
                page = await context.new_page()
                
                # Login if needed
                if role:
                    logged_in = await login(page, role)
                    if not logged_in:
                        print(f"  Skipping screenshots for role {role} (login failed)")
                        await context.close()
                        for spec in specs:
                            results["failed"].append(f"{theme}/common/{spec['filename']} (login failed)")
                        continue
                
                # Capture screenshots for this role
                for spec in specs:
                    success = await capture_screenshot(page, spec, theme, OUTPUT_DIR)
                    key = f"{theme}/common/{spec['filename']}"
                    if success:
                        results["success"].append(key)
                    else:
                        results["failed"].append(key)
                
                await context.close()
        
        await browser.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"\n  Successful: {len(results['success'])}")
    print(f"  Failed: {len(results['failed'])}")
    
    if results["failed"]:
        print("\n  Failed screenshots:")
        for f in results["failed"]:
            print(f"    - {f}")
    
    print("\n  Files created:")
    for path in sorted(results["success"]):
        full_path = OUTPUT_DIR / path
        if full_path.exists():
            size = full_path.stat().st_size
            print(f"    {path}: {size:,} bytes")
    
    return len(results["failed"]) == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
