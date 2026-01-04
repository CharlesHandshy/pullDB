"""Tests for template structure and content.

Tests cover:
- Template file existence
- Login page rendering
- Base template structure
- Dashboard template structure
- Job detail template structure

Updated to match HCA-based template structure:
- features/auth/login.html
- features/dashboard/dashboard.html
- features/jobs/details.html
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Template Paths (HCA Structure)
# ---------------------------------------------------------------------------

TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent.parent / "pulldb" / "web" / "templates"
)

# HCA paths
LOGIN_TEMPLATE = TEMPLATES_DIR / "features" / "auth" / "login.html"
DASHBOARD_TEMPLATE = TEMPLATES_DIR / "features" / "dashboard" / "dashboard.html"
JOB_DETAIL_TEMPLATE = TEMPLATES_DIR / "features" / "jobs" / "details.html"
BASE_TEMPLATE = TEMPLATES_DIR / "base.html"
BASE_AUTH_TEMPLATE = TEMPLATES_DIR / "base_auth.html"


# ---------------------------------------------------------------------------
# Template Existence Tests
# ---------------------------------------------------------------------------


class TestTemplatesExist:
    """Tests that required template files exist."""

    def test_base_html_exists(self) -> None:
        """base.html template exists."""
        assert BASE_TEMPLATE.exists()

    def test_base_auth_html_exists(self) -> None:
        """base_auth.html template exists for login pages."""
        assert BASE_AUTH_TEMPLATE.exists()

    def test_login_html_exists(self) -> None:
        """login.html template exists in features/auth/."""
        assert LOGIN_TEMPLATE.exists()

    def test_dashboard_html_exists(self) -> None:
        """dashboard.html template exists in features/dashboard/."""
        assert DASHBOARD_TEMPLATE.exists()

    def test_job_detail_html_exists(self) -> None:
        """Job details template exists in features/jobs/."""
        assert JOB_DETAIL_TEMPLATE.exists()

    def test_partials_dir_exists(self) -> None:
        """partials directory exists."""
        assert (TEMPLATES_DIR / "partials").is_dir()

    def test_features_dir_exists(self) -> None:
        """features directory exists (HCA structure)."""
        assert (TEMPLATES_DIR / "features").is_dir()

    def test_widgets_dir_exists(self) -> None:
        """widgets directory exists (HCA structure)."""
        assert (TEMPLATES_DIR / "widgets").is_dir()


# ---------------------------------------------------------------------------
# Login Template Content Tests
# ---------------------------------------------------------------------------


class TestLoginTemplateContent:
    """Tests for login.html template content."""

    def test_has_title(self) -> None:
        """Login page has correct title."""
        content = LOGIN_TEMPLATE.read_text()
        assert "Login - pullDB" in content

    def test_has_form(self) -> None:
        """Login page has login form."""
        content = LOGIN_TEMPLATE.read_text()
        assert "<form" in content
        assert 'method="post"' in content.lower()

    def test_has_username_field(self) -> None:
        """Login page has username input field."""
        content = LOGIN_TEMPLATE.read_text()
        assert 'name="username"' in content
        assert 'type="text"' in content

    def test_has_password_field(self) -> None:
        """Login page has password input field."""
        content = LOGIN_TEMPLATE.read_text()
        assert 'name="password"' in content
        assert 'type="password"' in content

    def test_has_submit_button(self) -> None:
        """Login page has submit button."""
        content = LOGIN_TEMPLATE.read_text()
        assert 'type="submit"' in content

    def test_has_error_display(self) -> None:
        """Login page can display error messages."""
        content = LOGIN_TEMPLATE.read_text()
        assert "error" in content.lower()

    def test_has_pulldb_branding(self) -> None:
        """Login page shows pullDB branding."""
        content = LOGIN_TEMPLATE.read_text()
        assert "pullDB" in content

    def test_extends_base_auth(self) -> None:
        """Login template extends base_auth.html."""
        content = LOGIN_TEMPLATE.read_text()
        assert '{% extends "base_auth.html" %}' in content


# ---------------------------------------------------------------------------
# Base Template Content Tests
# ---------------------------------------------------------------------------


class TestBaseTemplateContent:
    """Tests for base.html template content."""

    def test_has_doctype(self) -> None:
        """Base template has HTML5 doctype."""
        content = BASE_TEMPLATE.read_text()
        assert "<!DOCTYPE html>" in content

    def test_has_htmx(self) -> None:
        """Base template includes HTMX library."""
        content = BASE_TEMPLATE.read_text()
        assert "htmx" in content.lower()

    def test_has_navigation(self) -> None:
        """Base template has header navigation."""
        content = BASE_TEMPLATE.read_text()
        assert "app-header" in content or "<header" in content

    def test_has_logout_link(self) -> None:
        """Base template has logout functionality."""
        content = BASE_TEMPLATE.read_text()
        # Check sidebar includes or base navigation
        assert "logout" in content.lower() or "sidebar" in content.lower()

    def test_has_content_block(self) -> None:
        """Base template has content block for inheritance."""
        content = BASE_TEMPLATE.read_text()
        assert "{% block content %}" in content

    def test_has_title_block(self) -> None:
        """Base template has title block."""
        content = BASE_TEMPLATE.read_text()
        assert "{% block title %}" in content

    def test_has_responsive_meta(self) -> None:
        """Base template has viewport meta for responsive design."""
        content = BASE_TEMPLATE.read_text()
        assert 'name="viewport"' in content

    def test_has_theme_support(self) -> None:
        """Base template supports dark/light theme."""
        content = BASE_TEMPLATE.read_text()
        assert "data-theme" in content
        assert "theme-toggle" in content


# ---------------------------------------------------------------------------
# Dashboard Template Content Tests
# ---------------------------------------------------------------------------


class TestDashboardTemplateContent:
    """Tests for dashboard.html template content."""

    def test_extends_base(self) -> None:
        """Dashboard extends base template."""
        content = DASHBOARD_TEMPLATE.read_text()
        assert '{% extends "base.html" %}' in content

    def test_has_title_block(self) -> None:
        """Dashboard sets page title."""
        content = DASHBOARD_TEMPLATE.read_text()
        assert "{% block title %}" in content
        assert "Dashboard" in content

    def test_has_htmx_polling(self) -> None:
        """Dashboard has HTMX polling for live updates."""
        content = DASHBOARD_TEMPLATE.read_text()
        assert "hx-get" in content
        assert "hx-trigger" in content

    def test_has_welcome_message(self) -> None:
        """Dashboard shows welcome message with username."""
        content = DASHBOARD_TEMPLATE.read_text()
        assert "user.username" in content or "Welcome" in content

    def test_has_role_based_content(self) -> None:
        """Dashboard supports role-based content (admin, manager, user)."""
        content = DASHBOARD_TEMPLATE.read_text()
        assert "dashboard_type" in content or "admin_dashboard" in content.lower()


# ---------------------------------------------------------------------------
# Job Detail Template Content Tests
# ---------------------------------------------------------------------------


class TestJobDetailTemplateContent:
    """Tests for job details template content."""

    def test_extends_base(self) -> None:
        """Job detail extends base template."""
        content = JOB_DETAIL_TEMPLATE.read_text()
        assert '{% extends "base.html" %}' in content

    def test_shows_job_id(self) -> None:
        """Job detail shows job ID."""
        content = JOB_DETAIL_TEMPLATE.read_text()
        assert "job.id" in content

    def test_shows_status(self) -> None:
        """Job detail shows job status."""
        content = JOB_DETAIL_TEMPLATE.read_text()
        assert "job.status" in content

    def test_shows_status_badge(self) -> None:
        """Job detail uses status badges."""
        content = JOB_DETAIL_TEMPLATE.read_text()
        assert "badge" in content

    def test_has_htmx_polling_for_active_jobs(self) -> None:
        """Job detail has HTMX polling for running jobs."""
        content = JOB_DETAIL_TEMPLATE.read_text()
        assert "hx-get" in content
        assert "hx-trigger" in content

    def test_shows_phase_progress(self) -> None:
        """Job detail shows phase progress stepper."""
        content = JOB_DETAIL_TEMPLATE.read_text()
        assert "phase" in content.lower()

    def test_has_cancel_support(self) -> None:
        """Job detail supports cancellation."""
        content = JOB_DETAIL_TEMPLATE.read_text()
        assert "cancel" in content.lower()


# ---------------------------------------------------------------------------
# Feature Directory Structure Tests
# ---------------------------------------------------------------------------


class TestFeatureDirectoryStructure:
    """Tests for HCA-based feature directory structure."""

    def test_auth_feature_exists(self) -> None:
        """features/auth directory exists."""
        assert (TEMPLATES_DIR / "features" / "auth").is_dir()

    def test_dashboard_feature_exists(self) -> None:
        """features/dashboard directory exists."""
        assert (TEMPLATES_DIR / "features" / "dashboard").is_dir()

    def test_jobs_feature_exists(self) -> None:
        """features/jobs directory exists."""
        assert (TEMPLATES_DIR / "features" / "jobs").is_dir()

    def test_restore_feature_exists(self) -> None:
        """features/restore directory exists."""
        assert (TEMPLATES_DIR / "features" / "restore").is_dir()

    def test_admin_feature_exists(self) -> None:
        """features/admin directory exists."""
        assert (TEMPLATES_DIR / "features" / "admin").is_dir()

    def test_errors_feature_exists(self) -> None:
        """features/errors directory exists."""
        assert (TEMPLATES_DIR / "features" / "errors").is_dir()
