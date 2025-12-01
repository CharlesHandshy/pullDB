"""Tests for web module initialization and structure.

Tests cover:
- Module exports
- Router configuration
- Template directory structure
"""

from __future__ import annotations

from pathlib import Path


WEB_DIR = Path(__file__).parent.parent.parent.parent / "pulldb" / "web"


# ---------------------------------------------------------------------------
# Module Structure Tests
# ---------------------------------------------------------------------------


class TestWebModuleStructure:
    """Tests for web module file structure."""

    def test_web_dir_exists(self) -> None:
        """Web module directory exists."""
        assert WEB_DIR.is_dir()

    def test_init_exists(self) -> None:
        """__init__.py exists."""
        assert (WEB_DIR / "__init__.py").exists()

    def test_routes_exists(self) -> None:
        """routes.py exists."""
        assert (WEB_DIR / "routes.py").exists()

    def test_templates_dir_exists(self) -> None:
        """templates directory exists."""
        assert (WEB_DIR / "templates").is_dir()


# ---------------------------------------------------------------------------
# Module Exports Tests
# ---------------------------------------------------------------------------


class TestWebModuleExports:
    """Tests for web module exports."""

    def test_exports_router(self) -> None:
        """Web module exports router."""
        content = (WEB_DIR / "__init__.py").read_text()
        assert "router" in content
        assert "__all__" in content

    def test_imports_from_routes(self) -> None:
        """Web module imports router from routes."""
        content = (WEB_DIR / "__init__.py").read_text()
        assert "from pulldb.web.routes import router" in content


# ---------------------------------------------------------------------------
# Template Directory Structure Tests
# ---------------------------------------------------------------------------


class TestTemplateDirectoryStructure:
    """Tests for template directory organization."""

    def test_has_base_template(self) -> None:
        """Base template exists for layout inheritance."""
        assert (WEB_DIR / "templates" / "base.html").exists()

    def test_has_login_template(self) -> None:
        """Login template exists."""
        assert (WEB_DIR / "templates" / "login.html").exists()

    def test_has_dashboard_template(self) -> None:
        """Dashboard template exists."""
        assert (WEB_DIR / "templates" / "dashboard.html").exists()

    def test_has_jobs_template(self) -> None:
        """Jobs list template exists."""
        assert (WEB_DIR / "templates" / "jobs.html").exists()

    def test_has_job_detail_template(self) -> None:
        """Job detail template exists."""
        assert (WEB_DIR / "templates" / "job_detail.html").exists()

    def test_has_partials_directory(self) -> None:
        """Partials directory exists for HTMX fragments."""
        assert (WEB_DIR / "templates" / "partials").is_dir()

    def test_partials_has_active_jobs(self) -> None:
        """Active jobs partial exists."""
        assert (WEB_DIR / "templates" / "partials" / "active_jobs.html").exists()

    def test_partials_has_job_events(self) -> None:
        """Job events partial exists."""
        assert (WEB_DIR / "templates" / "partials" / "job_events.html").exists()

    def test_partials_has_job_row(self) -> None:
        """Job row partial exists."""
        assert (WEB_DIR / "templates" / "partials" / "job_row.html").exists()


# ---------------------------------------------------------------------------
# Template Content Quality Tests
# ---------------------------------------------------------------------------


class TestTemplateQuality:
    """Tests for template content quality."""

    def test_all_templates_valid_html(self) -> None:
        """All templates have valid HTML structure."""
        templates_dir = WEB_DIR / "templates"
        for template in templates_dir.glob("*.html"):
            content = template.read_text()
            # Basic HTML validity checks
            assert (
                "<!DOCTYPE html>" in content or "{% extends" in content
            ), f"{template.name} missing doctype or extends"

    def test_all_templates_have_title(self) -> None:
        """All main templates set page title."""
        for template_name in ["login.html", "dashboard.html", "jobs.html"]:
            content = (WEB_DIR / "templates" / template_name).read_text()
            assert (
                "<title>" in content or "{% block title %}" in content
            ), f"{template_name} missing title"

    def test_templates_use_jinja2_syntax(self) -> None:
        """Templates use Jinja2 syntax correctly."""
        templates_dir = WEB_DIR / "templates"
        for template in templates_dir.glob("*.html"):
            content = template.read_text()
            # Check for common Jinja2 patterns
            has_jinja = any([
                "{{" in content,
                "{%" in content,
                "{% extends" in content,
                "{% block" in content,
                "{% if" in content,
                "{% for" in content,
            ])
            # Partials or main templates should have Jinja
            if template.name != "base.html":
                assert has_jinja, f"{template.name} missing Jinja2 syntax"

    def test_partials_are_fragments(self) -> None:
        """Partial templates are HTML fragments, not full documents."""
        partials_dir = WEB_DIR / "templates" / "partials"
        for partial in partials_dir.glob("*.html"):
            content = partial.read_text()
            # Partials should NOT have doctype or html/head/body tags
            assert "<!DOCTYPE" not in content, f"{partial.name} has doctype"
            assert "<html" not in content, f"{partial.name} has html tag"
            assert "<head>" not in content, f"{partial.name} has head tag"
            assert "<body>" not in content, f"{partial.name} has body tag"
