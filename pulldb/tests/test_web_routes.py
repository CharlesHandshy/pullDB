"""Tests for web UI routes.

Phase 4: Tests for the web module routes and templates.
HCA: Updated to use new HCA structure imports.
"""

from __future__ import annotations


class TestWebModuleImport:
    """Tests for web module import and structure."""

    def test_web_router_importable(self) -> None:
        """Web router can be imported."""
        from pulldb.web import router
        assert router is not None

    def test_templates_directory_exists(self) -> None:
        """Templates directory exists with expected files."""
        from pulldb.web import TEMPLATES_DIR

        assert TEMPLATES_DIR.exists()
        assert (TEMPLATES_DIR / "base.html").exists()
        assert (TEMPLATES_DIR / "login.html").exists()
        assert (TEMPLATES_DIR / "dashboard.html").exists()
        # Note: jobs.html was renamed to job_detail.html
        assert (TEMPLATES_DIR / "job_detail.html").exists()

    def test_partials_directory_exists(self) -> None:
        """Partials directory exists with expected files."""
        from pulldb.web import TEMPLATES_DIR

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
        # Dashboard uses prefix /web/dashboard, so the root is /web/dashboard/
        assert "/web/dashboard/" in routes or "/web/dashboard" in routes

    def test_router_has_job_detail_route(self) -> None:
        """Router has job detail route."""
        from pulldb.web import router

        routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
        assert "/web/jobs/{job_id}" in routes


class TestTemplateContent:
    """Tests for template content and structure."""

    def test_base_template_has_required_blocks(self) -> None:
        """Base template contains required blocks."""
        from pulldb.web import TEMPLATES_DIR

        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "{% block title %}" in content
        assert "{% block content %}" in content or "{% block public_content %}" in content
        assert "htmx" in content.lower()  # HTMX included
        # Custom design system CSS
        assert "design-system.css" in content

    def test_login_template_has_form(self) -> None:
        """Login template has login form."""
        from pulldb.web import TEMPLATES_DIR

        content = (TEMPLATES_DIR / "login.html").read_text()
        assert "<form" in content
        assert 'name="username"' in content
        assert 'name="password"' in content
        assert 'type="submit"' in content

    def test_dashboard_template_extends_base(self) -> None:
        """Dashboard extends base template."""
        from pulldb.web import TEMPLATES_DIR

        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert '{% extends "base.html" %}' in content

    def test_job_detail_template_extends_base(self) -> None:
        """Job detail template extends base template."""
        from pulldb.web import TEMPLATES_DIR

        content = (TEMPLATES_DIR / "job_detail.html").read_text()
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


class TestHCAStructure:
    """Tests for HCA (Hierarchical Containment Architecture) compliance."""
    
    def test_router_registry_importable(self) -> None:
        """Router registry can be imported."""
        from pulldb.web.router_registry import main_router
        assert main_router is not None
    
    def test_all_feature_routers_importable(self) -> None:
        """All feature routers can be imported."""
        from pulldb.web.features.auth.routes import router as auth_router
        from pulldb.web.features.dashboard.routes import router as dashboard_router
        from pulldb.web.features.jobs.routes import router as jobs_router
        from pulldb.web.features.restore.routes import router as restore_router
        from pulldb.web.features.admin.routes import router as admin_router
        from pulldb.web.features.manager.routes import router as manager_router
        
        assert auth_router is not None
        assert dashboard_router is not None
        assert jobs_router is not None
        assert restore_router is not None
        assert admin_router is not None
        assert manager_router is not None
    
    def test_feature_modules_have_routes(self) -> None:
        """Each feature module has at least one route."""
        from pulldb.web.features.auth.routes import router as auth_router
        from pulldb.web.features.dashboard.routes import router as dashboard_router
        from pulldb.web.features.jobs.routes import router as jobs_router
        from pulldb.web.features.restore.routes import router as restore_router
        from pulldb.web.features.admin.routes import router as admin_router
        from pulldb.web.features.manager.routes import router as manager_router
        
        assert len(auth_router.routes) >= 1
        assert len(dashboard_router.routes) >= 1
        assert len(jobs_router.routes) >= 1
        assert len(restore_router.routes) >= 1
        assert len(admin_router.routes) >= 1
        assert len(manager_router.routes) >= 1
    
    def test_dependencies_module_has_templates(self) -> None:
        """Dependencies module exports templates."""
        from pulldb.web.dependencies import templates
        assert templates is not None
    
    def test_dependencies_module_has_auth_deps(self) -> None:
        """Dependencies module exports auth dependencies."""
        from pulldb.web.dependencies import (
            get_session_user,
            require_login,
            require_admin,
            AuthenticatedUser,
            AdminUser,
        )
        assert get_session_user is not None
        assert require_login is not None
        assert require_admin is not None
        assert AuthenticatedUser is not None
        assert AdminUser is not None
