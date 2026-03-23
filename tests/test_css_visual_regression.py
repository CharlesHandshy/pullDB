"""
Visual Regression Tests for pullDB Web UI
=========================================

Uses Playwright to capture screenshots of critical pages in both light and dark mode,
comparing against baseline images stored in S3 artifact bucket.

Usage:
    # Run tests (downloads baselines from S3, compares)
    pytest tests/test_css_visual_regression.py -v

    # Update baselines (captures new screenshots, uploads to S3)
    pytest tests/test_css_visual_regression.py -v --update-baselines

Environment Variables:
    VISUAL_THRESHOLD: Pixel diff tolerance (default: 0 for strict, set to 0.001 for 0.1%)
    PULLDB_TEST_BASE_URL: Base URL for the app (default: http://127.0.0.1:8000)
    AWS_VISUAL_BASELINE_BUCKET: S3 bucket for baseline storage
    PULLDB_TEST_USERNAME: Test user username (default: admin)
    PULLDB_TEST_PASSWORD: Test user password (default: admin)

HCA Layer: tests (visual regression suite)
"""

import os
import pytest
from pathlib import Path
from typing import Generator

# Guard: only run this test file when explicitly configured.
# Prevents accidental S3 access in CI or local dev environments.
pytestmark = pytest.mark.visual_regression

# Playwright imports - will fail gracefully if not installed
try:
    from playwright.sync_api import Page, sync_playwright, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Page = None
    Browser = None


# Configuration
BASE_URL = os.environ.get("PULLDB_TEST_BASE_URL", "http://127.0.0.1:8000")
VISUAL_THRESHOLD = float(os.environ.get("VISUAL_THRESHOLD", "0"))  # 0 = strict
TEST_USERNAME = os.environ.get("PULLDB_TEST_USERNAME", "admin")
TEST_PASSWORD = os.environ.get("PULLDB_TEST_PASSWORD", "admin")
# S3_BUCKET is intentionally None when the env var is not set.
# This prevents accidental writes/reads to real S3 in unguarded environments.
S3_BUCKET = os.environ.get("AWS_VISUAL_BASELINE_BUCKET")

# Local directories
SCREENSHOTS_DIR = Path(__file__).parent / "visual_screenshots"
DIFF_DIR = Path(__file__).parent / "visual_diffs"


# Critical pages to test (path, name for screenshot)
CRITICAL_PAGES = [
    ("/web/auth/login", "login"),
    ("/web/dashboard", "dashboard"),
    ("/web/restore", "restore"),
    ("/web/jobs", "jobs_list"),
    ("/web/admin", "admin"),
    ("/web/auth/profile", "profile"),
]


def pytest_addoption(parser):
    """Add --update-baselines flag to pytest."""
    parser.addoption(
        "--update-baselines",
        action="store_true",
        default=False,
        help="Capture new baseline screenshots and upload to S3",
    )


@pytest.fixture(scope="session")
def update_baselines(request) -> bool:
    """Get the --update-baselines flag value."""
    return request.config.getoption("--update-baselines")


@pytest.fixture(scope="session")
def browser() -> Generator[Browser, None, None]:
    """Create a Playwright browser instance."""
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not installed. Run: pip install playwright && playwright install chromium")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def page(browser: Browser) -> Generator[Page, None, None]:
    """Create a new page for each test."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        device_scale_factor=1,
    )
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="function")
def authenticated_page(page: Page) -> Page:
    """Login and return authenticated page."""
    # Navigate to login
    page.goto(f"{BASE_URL}/web/auth/login")
    page.wait_for_load_state("networkidle")
    
    # Fill credentials and submit
    page.fill('input[name="username"]', TEST_USERNAME)
    page.fill('input[name="password"]', TEST_PASSWORD)
    page.click('button[type="submit"]')
    
    # Wait for redirect to dashboard
    page.wait_for_url(f"{BASE_URL}/web/dashboard", timeout=10000)
    page.wait_for_load_state("networkidle")
    
    return page


def download_baseline(page_name: str, theme: str) -> Path | None:
    """Download baseline image from S3.

    Returns local path if downloaded, None if not found.

    Raises:
        pytest.skip.Exception: If AWS_VISUAL_BASELINE_BUCKET is not set.
    """
    if not S3_BUCKET:
        pytest.skip(
            "AWS_VISUAL_BASELINE_BUCKET env var not set — skipping S3 baseline download. "
            "Set this variable to run visual regression tests."
        )

    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3")
    key = f"baselines/{page_name}_{theme}.png"
    local_path = SCREENSHOTS_DIR / f"baseline_{page_name}_{theme}.png"
    
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        s3.download_file(S3_BUCKET, key, str(local_path))
        return local_path
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return None
        raise


def upload_baseline(page_name: str, theme: str, local_path: Path) -> None:
    """Upload baseline image to S3.

    Raises:
        pytest.skip.Exception: If AWS_VISUAL_BASELINE_BUCKET is not set.
    """
    if not S3_BUCKET:
        pytest.skip(
            "AWS_VISUAL_BASELINE_BUCKET env var not set — skipping S3 baseline upload. "
            "Set this variable to update visual regression baselines."
        )

    import boto3

    s3 = boto3.client("s3")
    key = f"baselines/{page_name}_{theme}.png"

    s3.upload_file(
        str(local_path),
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": "image/png"},
    )
    print(f"  Uploaded baseline: s3://{S3_BUCKET}/{key}")


def capture_screenshot(page: Page, page_name: str, theme: str) -> Path:
    """Capture a screenshot of the current page."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS_DIR / f"current_{page_name}_{theme}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def compare_images(baseline: Path, current: Path, page_name: str, theme: str) -> tuple[bool, float]:
    """Compare two images and return (match, diff_ratio).
    
    Uses pixelmatch-style comparison. Returns True if images match within threshold.
    """
    from PIL import Image
    import numpy as np
    
    img1 = np.array(Image.open(baseline).convert("RGB"))
    img2 = np.array(Image.open(current).convert("RGB"))
    
    # Handle size differences
    if img1.shape != img2.shape:
        # Images are different sizes - definitely don't match
        return False, 1.0
    
    # Calculate pixel difference
    diff = np.abs(img1.astype(float) - img2.astype(float))
    diff_pixels = np.sum(diff > 0) / 3  # Count pixels with any channel difference
    total_pixels = img1.shape[0] * img1.shape[1]
    diff_ratio = diff_pixels / total_pixels
    
    # Save diff image if there are differences
    if diff_ratio > 0:
        DIFF_DIR.mkdir(parents=True, exist_ok=True)
        diff_img = Image.fromarray(np.clip(diff * 10, 0, 255).astype(np.uint8))
        diff_img.save(DIFF_DIR / f"diff_{page_name}_{theme}.png")
    
    matches = diff_ratio <= VISUAL_THRESHOLD
    return matches, diff_ratio


def set_theme(page: Page, theme: str) -> None:
    """Set the page theme (light or dark)."""
    page.evaluate(f'document.documentElement.setAttribute("data-theme", "{theme}")')
    # Give CSS time to apply
    page.wait_for_timeout(100)


class TestVisualRegression:
    """Visual regression tests for critical pages."""
    
    @pytest.mark.parametrize("page_path,page_name", CRITICAL_PAGES)
    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_page_visual(
        self,
        page: Page,
        authenticated_page: Page,
        page_path: str,
        page_name: str,
        theme: str,
        update_baselines: bool,
    ):
        """Test visual appearance of a page in given theme."""
        # Use authenticated page for protected routes, regular page for login
        test_page = page if page_name == "login" else authenticated_page
        
        # Navigate to the page
        test_page.goto(f"{BASE_URL}{page_path}")
        test_page.wait_for_load_state("networkidle")
        
        # Set theme
        set_theme(test_page, theme)
        
        # Capture current screenshot
        current = capture_screenshot(test_page, page_name, theme)
        
        if update_baselines:
            # Upload as new baseline
            upload_baseline(page_name, theme, current)
            pytest.skip(f"Baseline updated for {page_name} ({theme})")
            return
        
        # Download baseline for comparison
        baseline = download_baseline(page_name, theme)
        
        if baseline is None:
            pytest.fail(
                f"No baseline found for {page_name} ({theme}). "
                f"Run with --update-baselines to create initial baselines."
            )
        
        # Compare images
        matches, diff_ratio = compare_images(baseline, current, page_name, theme)
        
        if not matches:
            pytest.fail(
                f"Visual regression detected for {page_name} ({theme})!\n"
                f"Diff ratio: {diff_ratio:.4%} (threshold: {VISUAL_THRESHOLD:.4%})\n"
                f"Diff image saved to: {DIFF_DIR / f'diff_{page_name}_{theme}.png'}"
            )


class TestCSSLoading:
    """Tests to verify CSS files load correctly."""
    
    def test_manifest_loads(self, page: Page):
        """Verify the HCA manifest CSS loads without 404."""
        response = page.goto(f"{BASE_URL}/static/css/shared/manifest.css")
        assert response.status == 200, "manifest.css should load successfully"
    
    def test_no_404_css(self, authenticated_page: Page):
        """Verify no CSS files return 404 on dashboard load."""
        # Collect all network requests
        failed_css = []
        
        def handle_response(response):
            if response.url.endswith(".css") and response.status >= 400:
                failed_css.append((response.url, response.status))
        
        authenticated_page.on("response", handle_response)
        
        # Navigate to dashboard (triggers all CSS loads)
        authenticated_page.goto(f"{BASE_URL}/web/dashboard")
        authenticated_page.wait_for_load_state("networkidle")
        
        assert len(failed_css) == 0, f"CSS files failed to load: {failed_css}"
    
    @pytest.mark.parametrize("css_file", [
        "/static/css/shared/design-tokens.css",
        "/static/css/shared/reset.css",
        "/static/css/shared/utilities.css",
        "/static/css/shared/layout.css",
        "/static/css/entities/badge.css",
        "/static/css/entities/avatar.css",
        "/static/css/entities/card.css",
        "/static/css/features/buttons.css",
        "/static/css/features/forms.css",
        "/static/css/features/tables.css",
        "/static/css/features/dashboard.css",
        "/static/css/widgets/sidebar.css",
    ])
    def test_hca_css_file_loads(self, page: Page, css_file: str):
        """Verify each HCA CSS file loads successfully."""
        response = page.goto(f"{BASE_URL}{css_file}")
        assert response.status == 200, f"{css_file} should load successfully"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
