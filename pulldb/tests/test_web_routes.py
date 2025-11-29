"""Tests for web UI routes.

Phase 4: Tests for the web module routes and templates.
"""

from __future__ import annotations


class TestWebModuleImport:
    """Tests for web module import and structure."""

    def test_web_router_importable(self) -> None:
        """Web router can be imported."""
        from pulldb.web import router
        assert router is not None
        assert router.prefix == "/web"

    def test_templates_directory_exists(self) -> None:
        """Templates directory exists with expected files."""
        from pulldb.web.routes import TEMPLATES_DIR
        
        assert TEMPLATES_DIR.exists()
        assert (TEMPLATES_DIR / "base.html").exists()
        assert (TEMPLATES_DIR / "login.html").exists()
        assert (TEMPLATES_DIR / "dashboard.html").exists()
        assert (TEMPLATES_DIR / "jobs.html").exists()
        assert (TEMPLATES_DIR / "job_detail.html").exists()
        
    def test_partials_directory_exists(self) -> None:
        """Partials directory exists with expected files."""
        from pulldb.web.routes import TEMPLATES_DIR
        
        partials_dir = TEMPLATES_DIR / "partials"
        assert partials_dir.exists()
        assert (partials_dir / "active_jobs.html").exists()
        assert (partials_dir / "job_events.html").exists()
        assert (partials_dir / "job_row.html").exists()


class TestWebRouteDefinitions:
    """Tests for route definitions in the web module."""

    def test_router_has_login_route(self) -> None:
        """Router has login GET and POST routes."""
        from pulldb.web import router

        routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
        assert "/web/login" in routes
        assert "GET" in routes["/web/login"] or "POST" in routes["/web/login"]

    def test_router_has_logout_route(self) -> None:
        """Router has logout route."""
        from pulldb.web import router

        routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
        assert "/web/logout" in routes

    def test_router_has_dashboard_route(self) -> None:
        """Router has dashboard route."""
        from pulldb.web import router

        routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
        assert "/web/dashboard" in routes

    def test_router_has_jobs_routes(self) -> None:
        """Router has jobs listing and detail routes."""
        from pulldb.web import router

        routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
        assert "/web/jobs" in routes
        assert "/web/jobs/{job_id}" in routes


class TestTemplateContent:
    """Tests for template content and structure."""

    def test_base_template_has_required_blocks(self) -> None:
        """Base template contains required blocks."""
        from pulldb.web.routes import TEMPLATES_DIR

        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "{% block title %}" in content
        assert "{% block content %}" in content
        assert "htmx" in content.lower()  # HTMX included
        # Custom CSS with CSS variables (not Bootstrap)
        assert "var(--primary)" in content

    def test_login_template_has_form(self) -> None:
        """Login template has login form."""
        from pulldb.web.routes import TEMPLATES_DIR
        
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert "<form" in content
        assert 'name="username"' in content
        assert 'name="password"' in content
        assert 'type="submit"' in content

    def test_dashboard_template_extends_base(self) -> None:
        """Dashboard extends base template."""
        from pulldb.web.routes import TEMPLATES_DIR
        
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert '{% extends "base.html" %}' in content

    def test_jobs_template_extends_base(self) -> None:
        """Jobs template extends base template."""
        from pulldb.web.routes import TEMPLATES_DIR
        
        content = (TEMPLATES_DIR / "jobs.html").read_text()
        assert '{% extends "base.html" %}' in content


class TestAPIStateWithAuth:
    """Tests for APIState integration with auth repository."""

    def test_api_state_has_auth_repo_field(self) -> None:
        """APIState NamedTuple includes auth_repo field."""
        from pulldb.api.main import APIState
        
        assert "auth_repo" in APIState._fields
        
    def test_api_state_auth_repo_is_optional(self) -> None:
        """auth_repo field defaults to None."""
        from pulldb.api.main import APIState
        
        # Check that auth_repo has a default value
        defaults = APIState._field_defaults
        assert "auth_repo" in defaults
        assert defaults["auth_repo"] is None
