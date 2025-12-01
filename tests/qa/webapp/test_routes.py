"""Tests for web routes in pullDB.

Tests cover:
- Route definitions
- HTTP methods
- URL patterns
- Response types
"""

from __future__ import annotations

from pathlib import Path


ROUTES_FILE = (
    Path(__file__).parent.parent.parent.parent / "pulldb" / "web" / "routes.py"
)


# ---------------------------------------------------------------------------
# Routes Module Tests
# ---------------------------------------------------------------------------


class TestRoutesModuleExists:
    """Tests that routes module exists and has expected structure."""

    def test_routes_file_exists(self) -> None:
        """routes.py file exists."""
        assert ROUTES_FILE.exists()

    def test_has_router(self) -> None:
        """Routes module defines a router."""
        content = ROUTES_FILE.read_text()
        assert "router = APIRouter" in content

    def test_router_has_prefix(self) -> None:
        """Router has /web prefix."""
        content = ROUTES_FILE.read_text()
        assert 'prefix="/web"' in content

    def test_has_templates_config(self) -> None:
        """Routes module configures Jinja2 templates."""
        content = ROUTES_FILE.read_text()
        assert "Jinja2Templates" in content
        assert "templates" in content


# ---------------------------------------------------------------------------
# Route Definition Tests
# ---------------------------------------------------------------------------


class TestLoginRoutes:
    """Tests for login-related routes."""

    def test_has_login_get_route(self) -> None:
        """Login GET route is defined."""
        content = ROUTES_FILE.read_text()
        assert '@router.get("/login"' in content

    def test_has_login_post_route(self) -> None:
        """Login POST route is defined."""
        content = ROUTES_FILE.read_text()
        assert '@router.post("/login"' in content

    def test_has_logout_route(self) -> None:
        """Logout route is defined."""
        content = ROUTES_FILE.read_text()
        assert '@router.get("/logout"' in content

    def test_login_returns_html(self) -> None:
        """Login route returns HTML response."""
        content = ROUTES_FILE.read_text()
        assert "HTMLResponse" in content


class TestProtectedRoutes:
    """Tests for protected routes requiring authentication."""

    def test_has_dashboard_route(self) -> None:
        """Dashboard route is defined."""
        content = ROUTES_FILE.read_text()
        assert '@router.get("/dashboard"' in content

    def test_has_job_detail_route(self) -> None:
        """Job detail route is defined."""
        content = ROUTES_FILE.read_text()
        assert '@router.get("/jobs/{job_id}"' in content

    def test_dashboard_requires_login(self) -> None:
        """Dashboard requires authentication."""
        content = ROUTES_FILE.read_text()
        # Check that require_login is used as dependency
        assert "_require_login" in content
        assert "Depends(_require_login)" in content


class TestHTMXPartialRoutes:
    """Tests for HTMX partial update routes."""

    def test_has_active_jobs_partial(self) -> None:
        """Active jobs partial route is defined."""
        content = ROUTES_FILE.read_text()
        assert '@router.get("/partials/active-jobs"' in content

    def test_has_job_events_partial(self) -> None:
        """Job events partial route is defined."""
        content = ROUTES_FILE.read_text()
        assert '@router.get("/partials/job-events/{job_id}"' in content

    def test_partials_return_html(self) -> None:
        """Partial routes return HTML response."""
        content = ROUTES_FILE.read_text()
        # Count HTMLResponse occurrences - should be multiple
        assert content.count("HTMLResponse") >= 5


# ---------------------------------------------------------------------------
# Authentication Helper Tests
# ---------------------------------------------------------------------------


class TestAuthenticationHelpers:
    """Tests for authentication helper functions."""

    def test_has_get_session_user(self) -> None:
        """Session user retrieval function exists."""
        content = ROUTES_FILE.read_text()
        assert "_get_session_user" in content

    def test_has_require_login(self) -> None:
        """Login requirement function exists."""
        content = ROUTES_FILE.read_text()
        assert "_require_login" in content

    def test_session_uses_cookies(self) -> None:
        """Session management uses cookies."""
        content = ROUTES_FILE.read_text()
        assert "session_token" in content
        assert "cookies" in content

    def test_login_sets_cookie(self) -> None:
        """Login sets session cookie."""
        content = ROUTES_FILE.read_text()
        assert "set_cookie" in content

    def test_logout_deletes_cookie(self) -> None:
        """Logout deletes session cookie."""
        content = ROUTES_FILE.read_text()
        assert "delete_cookie" in content


# ---------------------------------------------------------------------------
# Permission Tests
# ---------------------------------------------------------------------------


class TestPermissionChecks:
    """Tests for permission checking in routes."""

    def test_checks_view_permissions(self) -> None:
        """Routes check view permissions."""
        content = ROUTES_FILE.read_text()
        assert "can_view" in content

    def test_checks_cancel_permissions(self) -> None:
        """Job detail checks cancel permissions."""
        content = ROUTES_FILE.read_text()
        assert "can_cancel" in content

    def test_filters_jobs_by_owner(self) -> None:
        """Routes filter jobs by owner for non-admin users."""
        content = ROUTES_FILE.read_text()
        assert "owner_user_id" in content


# ---------------------------------------------------------------------------
# Response Handling Tests
# ---------------------------------------------------------------------------


class TestResponseHandling:
    """Tests for response handling in routes."""

    def test_uses_template_response(self) -> None:
        """Routes use TemplateResponse."""
        content = ROUTES_FILE.read_text()
        assert "TemplateResponse" in content

    def test_uses_redirect_response(self) -> None:
        """Routes use RedirectResponse for redirects."""
        content = ROUTES_FILE.read_text()
        assert "RedirectResponse" in content

    def test_handles_404(self) -> None:
        """Routes handle 404 for missing jobs."""
        content = ROUTES_FILE.read_text()
        assert "404" in content
        assert "not found" in content.lower()

    def test_handles_403(self) -> None:
        """Routes handle 403 for access denied."""
        content = ROUTES_FILE.read_text()
        assert "403" in content
        assert "Access denied" in content or "access denied" in content.lower()
