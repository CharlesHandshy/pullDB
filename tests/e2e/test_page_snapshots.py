"""Comprehensive Playwright snapshot tests for every UI page.

This test suite:
1. Visits every UI endpoint in the application
2. Takes screenshots for visual verification
3. Analyzes page content for CSS/HTML rendering errors
4. Reports issues found on each page

Run with: pytest tests/e2e/test_page_snapshots.py -v --headed
Run with screenshots: pytest tests/e2e/test_page_snapshots.py -v --screenshot=on

Screenshots are saved to: tests/e2e/screenshots/
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page


# =============================================================================
# Page Definitions - Every UI endpoint in pullDB
# =============================================================================

@dataclass
class PageDefinition:
    """Definition of a page to test."""
    url: str
    name: str
    requires_auth: bool = True
    role: str = "user"  # user, manager, admin
    description: str = ""


# All pages organized by feature area
PAGES: dict[str, list[PageDefinition]] = {
    "auth": [
        PageDefinition("/web/login", "Login Page", requires_auth=False, description="Login form"),
        PageDefinition("/web/auth/profile", "Profile Page", description="User profile and settings"),
        PageDefinition("/web/change-password", "Change Password", description="Forced password change"),
    ],
    "dashboard": [
        PageDefinition("/web/dashboard", "Dashboard", description="Main dashboard"),
    ],
    "jobs": [
        PageDefinition("/web/jobs", "Jobs List", description="Active and history jobs"),
        PageDefinition("/web/jobs?view=active", "Jobs Active Tab", description="Active jobs filter"),
        PageDefinition("/web/jobs?view=history", "Jobs History Tab", description="Job history"),
        PageDefinition("/web/jobs/job-001", "Job Detail - Queued", description="Queued job details"),
        PageDefinition("/web/jobs/job-002", "Job Detail - Running", description="Running job details"),
        PageDefinition("/web/jobs/job-003", "Job Detail - Complete", role="admin", description="Completed job"),
        PageDefinition("/web/jobs/job-004", "Job Detail - Failed", description="Failed job details"),
    ],
    "restore": [
        PageDefinition("/web/restore", "New Restore", description="Create new restore job"),
    ],
    "manager": [
        PageDefinition("/web/manager", "Manager Dashboard", role="admin", description="Team management"),
    ],
    "admin": [
        PageDefinition("/web/admin", "Admin Dashboard", role="admin", description="System overview"),
        PageDefinition("/web/admin/styleguide", "Style Guide", role="admin", description="Component library"),
        PageDefinition("/web/admin/users", "Users Management", role="admin", description="User administration"),
        PageDefinition("/web/admin/hosts", "Hosts Management", role="admin", description="Database hosts"),
        PageDefinition("/web/admin/settings", "System Settings", role="admin", description="Configuration"),
        PageDefinition("/web/admin/prune-logs/preview", "Prune Logs", role="admin", description="Log cleanup"),
        PageDefinition("/web/admin/cleanup-staging/preview", "Cleanup Staging", role="admin", description="DB cleanup"),
        PageDefinition("/web/admin/orphans/preview", "Orphan Databases", role="admin", description="Orphan cleanup"),
    ],
    "audit": [
        PageDefinition("/web/admin/audit", "Audit Logs", role="admin", description="System audit trail"),
    ],
    "errors": [
        PageDefinition("/web/nonexistent-page-404", "404 Error Page", description="Not found page"),
    ],
}


# =============================================================================
# Page Analysis - Detect rendering issues
# =============================================================================

@dataclass
class PageIssue:
    """An issue found on a page."""
    severity: str  # error, warning, info
    category: str  # css, html, js, content
    message: str
    selector: str = ""


@dataclass 
class PageAnalysis:
    """Analysis results for a page."""
    url: str
    name: str
    status_code: int | None = None
    load_time_ms: float = 0
    screenshot_path: str = ""
    issues: list[PageIssue] = field(default_factory=list)
    content_checks: dict = field(default_factory=dict)
    
    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)
    
    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)


def analyze_page(page: Page, page_def: PageDefinition) -> PageAnalysis:
    """Analyze a page for rendering issues."""
    analysis = PageAnalysis(url=page_def.url, name=page_def.name)
    
    content = page.content().lower()
    
    # Check for server errors
    if "internal server error" in content:
        analysis.issues.append(PageIssue(
            severity="error",
            category="server",
            message="Internal server error returned"
        ))
    
    if "traceback" in content:
        analysis.issues.append(PageIssue(
            severity="error",
            category="server", 
            message="Python traceback visible on page"
        ))
    
    # Check for common HTML/template errors
    if "jinja2" in content and "error" in content:
        analysis.issues.append(PageIssue(
            severity="error",
            category="template",
            message="Jinja2 template error"
        ))
    
    if "undefined" in content and ("variable" in content or "is not defined" in content):
        analysis.issues.append(PageIssue(
            severity="error",
            category="template",
            message="Undefined variable in template"
        ))
    
    # Check for broken images
    images = page.locator("img").all()
    for img in images:
        src = img.get_attribute("src")
        if src:
            natural_width = img.evaluate("el => el.naturalWidth")
            if natural_width == 0:
                analysis.issues.append(PageIssue(
                    severity="warning",
                    category="image",
                    message=f"Broken image: {src}",
                    selector=f"img[src='{src}']"
                ))
    
    # Check for empty body (CSS/HTML not rendering)
    body = page.locator("body")
    body_text = body.inner_text().strip() if body.count() > 0 else ""
    
    if len(body_text) < 50 and "login" not in page_def.url:
        visible_elements = page.locator("body *:visible").count()
        if visible_elements < 5:
            analysis.issues.append(PageIssue(
                severity="warning",
                category="content",
                message=f"Page appears mostly empty ({visible_elements} visible elements)"
            ))
    
    # Check for JSON response instead of HTML (skip expected 404 pages)
    is_expected_error_page = "404" in page_def.name or "Error" in page_def.name
    if content.strip().startswith("{") or content.strip().startswith("["):
        if "<!doctype" not in content and "<html" not in content:
            if not is_expected_error_page:
                analysis.issues.append(PageIssue(
                    severity="error",
                    category="content",
                    message="Page returned JSON instead of HTML"
                ))
    
    # Check for FastAPI error responses (skip expected 404 pages)
    if '"detail"' in content and len(body_text) < 200:
        match = re.search(r'"detail"\s*:\s*"([^"]+)"', page.content())
        if match and not is_expected_error_page:
            analysis.issues.append(PageIssue(
                severity="error",
                category="api",
                message=f"API error response: {match.group(1)}"
            ))
    
    # Check page has basic structure
    has_head = page.locator("head").count() > 0
    has_body = page.locator("body").count() > 0
    
    if not has_head or not has_body:
        analysis.issues.append(PageIssue(
            severity="error",
            category="html",
            message="Page missing basic HTML structure (head/body)"
        ))
    
    analysis.content_checks["has_head"] = has_head
    analysis.content_checks["has_body"] = has_body
    analysis.content_checks["body_text_length"] = len(body_text)
    
    return analysis


# =============================================================================
# Screenshot directory setup
# =============================================================================

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


@pytest.fixture(scope="session", autouse=True)
def setup_screenshot_dir():
    """Create screenshot directory if it doesn't exist."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    for feature in PAGES.keys():
        (SCREENSHOT_DIR / feature).mkdir(exist_ok=True)
    yield


# =============================================================================
# Login helpers
# =============================================================================

def login_as(page: Page, base_url: str, role: str) -> bool:
    """Login as specified role. Returns True if successful."""
    credentials = {
        "user": ("testuser", "testpass123"),
        "manager": ("testuser", "testpass123"),
        "admin": ("admin", "testpass123"),
    }
    
    username, password = credentials.get(role, ("testuser", "testpass123"))
    
    # First logout if we're logged in
    page.goto(f"{base_url}/web/logout")
    page.wait_for_load_state("networkidle")
    
    # Now login
    page.goto(f"{base_url}/web/login")
    page.wait_for_load_state("networkidle")
    
    # Check if we're on login page
    if "/login" not in page.url:
        # Already redirected, try again
        page.goto(f"{base_url}/web/login")
        page.wait_for_load_state("networkidle")
    
    # Fill login form
    username_field = page.locator('input[name="username"]')
    if username_field.count() > 0:
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
    
    return "/login" not in page.url


# =============================================================================
# Full site crawl test
# =============================================================================

class TestFullSiteCrawl:
    """Crawl entire site and generate comprehensive report."""
    
    def test_crawl_all_pages(self, page: Page, base_url: str):
        """Crawl all pages and generate analysis report."""
        import time
        
        all_analyses: list[PageAnalysis] = []
        errors_found: list[tuple[str, str, PageIssue]] = []
        
        all_pages = [(f, p) for f, pages in PAGES.items() for p in pages]
        current_role = None
        
        for feature, page_def in all_pages:
            # Login if needed
            if page_def.requires_auth:
                if current_role != page_def.role:
                    login_as(page, base_url, page_def.role)
                    current_role = page_def.role
            
            # Visit page
            start = time.time()
            try:
                response = page.goto(f"{base_url}{page_def.url}")
                page.wait_for_load_state("networkidle")
            except Exception as e:
                analysis = PageAnalysis(url=page_def.url, name=page_def.name)
                analysis.issues.append(PageIssue("error", "navigation", f"Failed: {e}"))
                all_analyses.append(analysis)
                continue
            
            load_time = (time.time() - start) * 1000
            
            # Analyze
            analysis = analyze_page(page, page_def)
            analysis.load_time_ms = load_time
            analysis.status_code = response.status if response else None
            
            # Screenshot
            safe_name = re.sub(r'[^\w\-]', '_', page_def.name.lower())
            screenshot_path = SCREENSHOT_DIR / feature / f"{safe_name}.png"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
                analysis.screenshot_path = str(screenshot_path)
            except Exception:
                pass
            
            all_analyses.append(analysis)
            
            for issue in analysis.issues:
                if issue.severity == "error":
                    errors_found.append((feature, page_def.name, issue))
        
        # Generate report
        report_path = SCREENSHOT_DIR / "crawl_report.json"
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_pages": len(all_analyses),
            "pages_with_errors": sum(1 for a in all_analyses if a.has_errors),
            "pages_with_warnings": sum(1 for a in all_analyses if a.has_warnings),
            "pages": [
                {
                    "url": a.url,
                    "name": a.name,
                    "status_code": a.status_code,
                    "load_time_ms": round(a.load_time_ms, 2),
                    "screenshot": a.screenshot_path,
                    "issues": [{"severity": i.severity, "category": i.category, "message": i.message} for i in a.issues],
                    "checks": a.content_checks
                }
                for a in all_analyses
            ]
        }
        
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"\n{'='*60}")
        print(f"CRAWL REPORT: {len(all_analyses)} pages tested")
        print(f"{'='*60}")
        print(f"Pages with errors: {report['pages_with_errors']}")
        print(f"Pages with warnings: {report['pages_with_warnings']}")
        print(f"Report saved to: {report_path}")
        
        if errors_found:
            print(f"\n{'='*60}")
            print("ERRORS FOUND:")
            print(f"{'='*60}")
            for feature, name, issue in errors_found:
                print(f"  [{feature}] {name}: {issue.category} - {issue.message}")
            
            error_summary = "\n".join(f"  - [{f}] {n}: {i.message}" for f, n, i in errors_found)
            pytest.fail(f"Found {len(errors_found)} errors:\n{error_summary}")


# =============================================================================
# CSS/HTML diagnostics
# =============================================================================

class TestCSSHTMLDiagnostics:
    """Detailed CSS and HTML diagnostics."""
    
    def test_css_loading(self, page: Page, base_url: str):
        """Test that all CSS files load correctly."""
        login_as(page, base_url, "admin")
        page.goto(f"{base_url}/web/admin/styleguide")
        page.wait_for_load_state("networkidle")
        
        stylesheets = page.locator('link[rel="stylesheet"]').all()
        css_issues = []
        
        for sheet in stylesheets:
            href = sheet.get_attribute("href")
            if href:
                css_url = f"{base_url}{href}" if href.startswith("/") else href
                response = page.request.get(css_url)
                if response.status != 200:
                    css_issues.append(f"CSS failed: {href} (status {response.status})")
                elif len(response.body()) == 0:
                    css_issues.append(f"CSS empty: {href}")
        
        if css_issues:
            pytest.fail(f"CSS loading issues:\n" + "\n".join(css_issues))
    
    def test_html_structure(self, page: Page, base_url: str):
        """Test HTML structure of key pages."""
        login_as(page, base_url, "admin")
        
        pages_to_check = ["/web/dashboard", "/web/jobs", "/web/admin", "/web/admin/users"]
        structure_issues = []
        
        for url in pages_to_check:
            page.goto(f"{base_url}{url}")
            page.wait_for_load_state("networkidle")
            content = page.content()
            
            if "<!doctype html>" not in content.lower():
                structure_issues.append(f"{url}: Missing DOCTYPE")
            if "<html" not in content.lower():
                structure_issues.append(f"{url}: Missing <html>")
            if "<head" not in content.lower():
                structure_issues.append(f"{url}: Missing <head>")
            if "<body" not in content.lower():
                structure_issues.append(f"{url}: Missing <body>")
        
        if structure_issues:
            pytest.fail(f"HTML structure issues:\n" + "\n".join(structure_issues))
    
    def test_no_raw_template_output(self, page: Page, base_url: str):
        """Ensure no raw template syntax is visible."""
        login_as(page, base_url, "admin")
        
        pages_to_check = ["/web/dashboard", "/web/jobs", "/web/restore", "/web/admin", "/web/admin/users"]
        template_issues = []
        template_patterns = [r"\{\{[^}]+\}\}", r"\{%[^%]+%\}"]
        
        for url in pages_to_check:
            page.goto(f"{base_url}{url}")
            page.wait_for_load_state("networkidle")
            body_text = page.locator("body").inner_text()
            
            for pattern in template_patterns:
                matches = re.findall(pattern, body_text)
                if matches:
                    template_issues.append(f"{url}: Unrendered template: {matches[:3]}")
        
        if template_issues:
            pytest.fail(f"Template rendering issues:\n" + "\n".join(template_issues))
