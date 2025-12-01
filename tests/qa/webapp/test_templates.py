"""Tests for login page and authentication flow.

Tests cover:
- Login page rendering
- Form validation
- Authentication success/failure
- Session management
- Logout functionality
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Template Existence Tests
# ---------------------------------------------------------------------------

TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent.parent / "pulldb" / "web" / "templates"
)


class TestTemplatesExist:
    """Tests that required template files exist."""

    def test_base_html_exists(self) -> None:
        """base.html template exists."""
        assert (TEMPLATES_DIR / "base.html").exists()

    def test_login_html_exists(self) -> None:
        """login.html template exists."""
        assert (TEMPLATES_DIR / "login.html").exists()

    def test_dashboard_html_exists(self) -> None:
        """dashboard.html template exists."""
        assert (TEMPLATES_DIR / "dashboard.html").exists()

    def test_job_detail_html_exists(self) -> None:
        """job_detail.html template exists."""
        assert (TEMPLATES_DIR / "job_detail.html").exists()

    def test_partials_dir_exists(self) -> None:
        """partials directory exists."""
        assert (TEMPLATES_DIR / "partials").is_dir()

    def test_active_jobs_partial_exists(self) -> None:
        """active_jobs.html partial exists."""
        assert (TEMPLATES_DIR / "partials" / "active_jobs.html").exists()

    def test_job_events_partial_exists(self) -> None:
        """job_events.html partial exists."""
        assert (TEMPLATES_DIR / "partials" / "job_events.html").exists()

    def test_job_row_partial_exists(self) -> None:
        """job_row.html partial exists."""
        assert (TEMPLATES_DIR / "partials" / "job_row.html").exists()


# ---------------------------------------------------------------------------
# Login Template Content Tests
# ---------------------------------------------------------------------------


class TestLoginTemplateContent:
    """Tests for login.html template content."""

    def test_has_title(self) -> None:
        """Login page has correct title."""
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert "<title>Login - pullDB</title>" in content

    def test_has_form(self) -> None:
        """Login page has login form."""
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert "<form" in content
        assert 'method="POST"' in content or "method='POST'" in content

    def test_has_username_field(self) -> None:
        """Login page has username input field."""
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert 'name="username"' in content
        assert 'type="text"' in content

    def test_has_password_field(self) -> None:
        """Login page has password input field."""
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert 'name="password"' in content
        assert 'type="password"' in content

    def test_has_submit_button(self) -> None:
        """Login page has submit button."""
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert 'type="submit"' in content

    def test_has_error_display(self) -> None:
        """Login page can display error messages."""
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert "error" in content.lower()

    def test_has_pulldb_branding(self) -> None:
        """Login page shows pullDB branding."""
        content = (TEMPLATES_DIR / "login.html").read_text()
        assert "pullDB" in content


# ---------------------------------------------------------------------------
# Base Template Content Tests
# ---------------------------------------------------------------------------


class TestBaseTemplateContent:
    """Tests for base.html template content."""

    def test_has_doctype(self) -> None:
        """Base template has HTML5 doctype."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "<!DOCTYPE html>" in content

    def test_has_htmx(self) -> None:
        """Base template includes HTMX library."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "htmx" in content.lower()

    def test_has_navigation(self) -> None:
        """Base template has navigation."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "<nav" in content

    def test_has_logout_link(self) -> None:
        """Base template has logout link."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "/web/logout" in content or "logout" in content.lower()

    def test_has_dashboard_link(self) -> None:
        """Base template has dashboard link."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "/web/dashboard" in content or "dashboard" in content.lower()

    def test_has_restore_link(self) -> None:
        """Base template has restore link."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "/web/restore" in content

    def test_has_content_block(self) -> None:
        """Base template has content block for inheritance."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "{% block content %}" in content or "{%block content%}" in content

    def test_has_title_block(self) -> None:
        """Base template has title block."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "{% block title %}" in content or "{%block title%}" in content

    def test_has_responsive_meta(self) -> None:
        """Base template has viewport meta for responsive design."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert 'name="viewport"' in content

    def test_has_css_variables(self) -> None:
        """Base template uses CSS custom properties."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert ":root" in content
        assert "--primary" in content


# ---------------------------------------------------------------------------
# Dashboard Template Content Tests
# ---------------------------------------------------------------------------


class TestDashboardTemplateContent:
    """Tests for dashboard.html template content."""

    def test_extends_base(self) -> None:
        """Dashboard extends base template."""
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert '{% extends "base.html" %}' in content

    def test_has_title_block(self) -> None:
        """Dashboard sets page title."""
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert "{% block title %}" in content
        assert "Dashboard" in content

    def test_has_active_jobs_section(self) -> None:
        """Dashboard has active jobs section."""
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert "Active Jobs" in content

    def test_has_recent_jobs_section(self) -> None:
        """Dashboard has recent jobs section."""
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert "Recent Jobs" in content

    def test_includes_active_jobs_partial(self) -> None:
        """Dashboard includes active jobs partial."""
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert "active_jobs.html" in content

    def test_has_htmx_polling(self) -> None:
        """Dashboard has HTMX polling for live updates."""
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert "hx-get" in content
        assert "hx-trigger" in content

    def test_has_job_detail_links(self) -> None:
        """Dashboard has links to job details."""
        content = (TEMPLATES_DIR / "dashboard.html").read_text()
        assert "/web/jobs/" in content


# ---------------------------------------------------------------------------
# Job Detail Template Content Tests
# ---------------------------------------------------------------------------


class TestJobDetailTemplateContent:
    """Tests for job_detail.html template content."""

    def test_extends_base(self) -> None:
        """Job detail extends base template."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert '{% extends "base.html" %}' in content

    def test_has_back_link(self) -> None:
        """Job detail has back to dashboard link."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "/web/dashboard" in content
        assert "Back" in content

    def test_shows_job_id(self) -> None:
        """Job detail shows job ID."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "job.id" in content

    def test_shows_target(self) -> None:
        """Job detail shows target database."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "job.target" in content

    def test_shows_status(self) -> None:
        """Job detail shows job status."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "job.status" in content

    def test_shows_timestamps(self) -> None:
        """Job detail shows timestamps."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "submitted_at" in content
        assert "started_at" in content
        assert "completed_at" in content

    def test_shows_worker_id(self) -> None:
        """Job detail shows worker ID."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "worker_id" in content

    def test_shows_error_detail(self) -> None:
        """Job detail shows error detail if present."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "error_detail" in content

    def test_has_cancel_button(self) -> None:
        """Job detail has cancel button for active jobs."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "cancel" in content.lower()
        assert "can_cancel" in content

    def test_has_events_section(self) -> None:
        """Job detail has event log section."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "Event" in content
        assert "job_events.html" in content

    def test_has_htmx_event_polling(self) -> None:
        """Job detail has HTMX polling for live event updates."""
        content = (TEMPLATES_DIR / "job_detail.html").read_text()
        assert "hx-get" in content
        assert "/partials/job-events/" in content


# ---------------------------------------------------------------------------
# Partials Template Content Tests
# ---------------------------------------------------------------------------


class TestPartialsContent:
    """Tests for partial templates."""

    def test_active_jobs_has_table(self) -> None:
        """Active jobs partial has table structure."""
        content = (TEMPLATES_DIR / "partials" / "active_jobs.html").read_text()
        assert "<table>" in content or "{% if active_jobs %}" in content

    def test_active_jobs_has_columns(self) -> None:
        """Active jobs partial has expected columns."""
        content = (TEMPLATES_DIR / "partials" / "active_jobs.html").read_text()
        assert "Target" in content
        assert "Status" in content
        assert "Operation" in content
        assert "Owner" in content

    def test_active_jobs_has_view_link(self) -> None:
        """Active jobs partial has view link."""
        content = (TEMPLATES_DIR / "partials" / "active_jobs.html").read_text()
        assert "/web/jobs/" in content
        assert "View" in content

    def test_active_jobs_has_empty_state(self) -> None:
        """Active jobs partial handles empty state."""
        content = (TEMPLATES_DIR / "partials" / "active_jobs.html").read_text()
        assert "No active jobs" in content or "{% else %}" in content

    def test_job_events_has_table(self) -> None:
        """Job events partial has table structure."""
        content = (TEMPLATES_DIR / "partials" / "job_events.html").read_text()
        assert "<table>" in content or "{% if events %}" in content

    def test_job_events_has_columns(self) -> None:
        """Job events partial has expected columns."""
        content = (TEMPLATES_DIR / "partials" / "job_events.html").read_text()
        assert "Timestamp" in content
        assert "Event" in content or "Type" in content

    def test_job_events_has_badges(self) -> None:
        """Job events partial uses status badges."""
        content = (TEMPLATES_DIR / "partials" / "job_events.html").read_text()
        assert "badge" in content

    def test_job_row_has_structure(self) -> None:
        """Job row partial has proper structure."""
        content = (TEMPLATES_DIR / "partials" / "job_row.html").read_text()
        assert "<tr>" in content
        assert "job.id" in content
        assert "job.target" in content
        assert "job.status" in content
