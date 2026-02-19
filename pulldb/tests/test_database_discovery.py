"""Tests for Database Discovery routes and helpers.

HCA Layer: tests

Tests the database discovery page:
- _text_filter_match helper (wildcard/substring matching)
- _get_enriched_databases helper (enrichment, stats, created dates)
- Paginated API endpoint (filtering, sorting, pagination)
- Distinct API endpoint (column validation, cascading filters)
- Route definitions (route existence, correct methods)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from pulldb.domain.models import Job, JobStatus


# =============================================================================
# Fixtures & Factories
# =============================================================================


def _make_job(
    *,
    target: str = "testdb",
    dbhost: str = "db-host-01",
    owner_user_id: str = "user-001",
    owner_user_code: str = "ABC",
    owner_username: str = "alice",
    completed_at: datetime | None = None,
    expires_at: datetime | None = None,
    locked_at: datetime | None = None,
    superseded_at: datetime | None = None,
    db_dropped_at: datetime | None = None,
    submitted_at: datetime | None = None,
) -> Job:
    """Create a Job instance with sensible defaults for testing."""
    return Job(
        id="job-001",
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        owner_user_code=owner_user_code,
        target=target,
        staging_name=f"{target}_aabbccddeeff",
        dbhost=dbhost,
        status=JobStatus.DEPLOYED,
        submitted_at=submitted_at or datetime(2025, 6, 1, tzinfo=timezone.utc),
        completed_at=completed_at,
        expires_at=expires_at,
        locked_at=locked_at,
        superseded_at=superseded_at,
        db_dropped_at=db_dropped_at,
    )


def _mock_state(
    *,
    databases: list[str] | None = None,
    deployed_jobs: list[Job] | None = None,
    created_dates: dict[str, str] | None = None,
    host_enabled: bool = True,
    host_missing: bool = False,
) -> MagicMock:
    """Build a MagicMock state with host_repo / job_repo configured."""
    state = MagicMock()

    if host_missing:
        state.host_repo.get_host_by_hostname.return_value = None
    else:
        host = MagicMock()
        host.enabled = host_enabled
        state.host_repo.get_host_by_hostname.return_value = host

    state.host_repo.list_databases.return_value = databases or []
    state.job_repo.get_deployed_jobs_for_host.return_value = deployed_jobs or []
    state.host_repo.get_database_created_dates.return_value = created_dates or {}

    return state


# =============================================================================
# _text_filter_match tests
# =============================================================================


class TestTextFilterMatch:
    """Tests for _text_filter_match helper."""

    def test_substring_match(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("hello world", ["hello"]) is True

    def test_substring_no_match(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("hello world", ["xyz"]) is False

    def test_wildcard_star(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("my_database_123", ["my_*"]) is True
        assert _text_filter_match("other_db", ["my_*"]) is False

    def test_wildcard_question(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("db1", ["db?"]) is True
        assert _text_filter_match("db12", ["db?"]) is False

    def test_multiple_values_any_match(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("alpha", ["beta", "alpha"]) is True

    def test_empty_values_no_match(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("anything", []) is False

    def test_empty_cell_no_match(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("", ["test"]) is False

    def test_wildcard_full_glob(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _text_filter_match,
        )

        assert _text_filter_match("anything_at_all", ["*"]) is True


# =============================================================================
# _get_enriched_databases tests
# =============================================================================


class TestGetEnrichedDatabases:
    """Tests for _get_enriched_databases helper."""

    def test_returns_empty_for_no_databases(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(databases=[])
        rows, stats = _get_enriched_databases(state, "db-host-01")

        assert rows == []
        assert stats == {"total": 0, "managed": 0, "unmanaged": 0}

    def test_raises_for_missing_host(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(host_missing=True)
        with pytest.raises(ValueError, match="not found"):
            _get_enriched_databases(state, "nonexistent")

    def test_raises_for_disabled_host(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(host_enabled=False)
        with pytest.raises(ValueError, match="disabled"):
            _get_enriched_databases(state, "disabled-host")

    def test_managed_database_enrichment(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        completed = datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc)
        expires = datetime(2025, 8, 1, tzinfo=timezone.utc)
        job = _make_job(
            target="mydb",
            completed_at=completed,
            expires_at=expires,
        )
        state = _mock_state(databases=["mydb"], deployed_jobs=[job])
        rows, stats = _get_enriched_databases(state, "db-host-01")

        assert len(rows) == 1
        row = rows[0]
        assert row["name"] == "mydb"
        assert row["status"] == "Managed"
        assert row["managed"] is True
        assert row["owner_user_code"] == "ABC"
        assert row["deployed_at"] == completed.isoformat()
        assert row["expires_at"] == expires.isoformat()
        assert stats == {"total": 1, "managed": 1, "unmanaged": 0}

    def test_unmanaged_database_enrichment(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(
            databases=["orphan_db"],
            created_dates={"orphan_db": "2025-01-15T10:00:00"},
        )
        rows, stats = _get_enriched_databases(state, "db-host-01")

        assert len(rows) == 1
        row = rows[0]
        assert row["name"] == "orphan_db"
        assert row["status"] == "Unmanaged"
        assert row["managed"] is False
        assert row["owner_user_code"] == ""
        assert row["deployed_at"] == "2025-01-15T10:00:00"
        assert row["expires_at"] is None
        assert stats == {"total": 1, "managed": 0, "unmanaged": 1}

    def test_locked_database_status(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        job = _make_job(
            target="locked_db",
            locked_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
        )
        state = _mock_state(databases=["locked_db"], deployed_jobs=[job])
        rows, _ = _get_enriched_databases(state, "db-host-01")

        assert rows[0]["status"] == "Locked"
        assert rows[0]["locked"] is True

    def test_staging_database_detected(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(databases=["mydb_aabbccddeeff"])
        rows, _ = _get_enriched_databases(state, "db-host-01")

        assert rows[0]["is_staging"] is True

    def test_non_staging_database(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(databases=["regular_db"])
        rows, _ = _get_enriched_databases(state, "db-host-01")

        assert rows[0]["is_staging"] is False

    def test_multi_owner_count(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        job1 = _make_job(
            target="shared_db",
            owner_user_id="user-001",
            owner_user_code="ABC",
        )
        job2 = _make_job(
            target="shared_db",
            owner_user_id="user-002",
            owner_user_code="XYZ",
        )
        state = _mock_state(
            databases=["shared_db"],
            deployed_jobs=[job1, job2],
        )
        rows, stats = _get_enriched_databases(state, "db-host-01")

        assert len(rows) == 1
        assert rows[0]["owner_count"] == 2
        # Only first job's owner shown
        assert rows[0]["owner_user_code"] in ("ABC", "XYZ")
        # Still counts as 1 managed
        assert stats["managed"] == 1

    def test_created_dates_failure_graceful(self) -> None:
        """info_schema failure should NOT block enrichment."""
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(databases=["some_db"])
        state.host_repo.get_database_created_dates.side_effect = Exception("conn refused")
        rows, stats = _get_enriched_databases(state, "db-host-01")

        assert len(rows) == 1
        assert rows[0]["deployed_at"] is None  # graceful fallback
        assert stats["total"] == 1

    def test_mixed_managed_unmanaged(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        job = _make_job(target="managed_db")
        state = _mock_state(
            databases=["managed_db", "unmanaged_db"],
            deployed_jobs=[job],
        )
        rows, stats = _get_enriched_databases(state, "db-host-01")

        assert len(rows) == 2
        assert stats == {"total": 2, "managed": 1, "unmanaged": 1}
        names = {r["name"]: r["managed"] for r in rows}
        assert names["managed_db"] is True
        assert names["unmanaged_db"] is False


# =============================================================================
# Distinct endpoint column validation tests
# =============================================================================


class TestDistinctColumnValidation:
    """Tests for column allowlist in distinct endpoint."""

    def test_valid_columns_accepted(self) -> None:
        """Valid filter columns should be in the allowlist."""
        from pulldb.web.features.admin.database_discovery_routes import (
            api_databases_distinct,
        )

        # Inspect the source to verify the allowlist exists
        import inspect

        source = inspect.getsource(api_databases_distinct)
        assert "_VALID_FILTER_COLUMNS" in source
        assert '"status"' in source
        assert '"name"' in source
        assert '"owner_user_code"' in source


# =============================================================================
# Route definition tests
# =============================================================================


class TestDatabaseDiscoveryRouteDefinitions:
    """Tests for route definitions in the database discovery module."""

    def test_router_importable(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        assert router is not None

    def test_has_page_route(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert "/web/admin/database-discovery" in routes

    def test_has_paginated_route(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert "/web/admin/api/database-discovery/databases/paginated" in routes

    def test_has_distinct_route(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert (
            "/web/admin/api/database-discovery/databases/paginated/distinct"
            in routes
        )

    def test_has_claim_route(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert "/web/admin/api/database-discovery/claim" in routes
        assert "POST" in routes["/web/admin/api/database-discovery/claim"]

    def test_has_assign_route(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert "/web/admin/api/database-discovery/assign" in routes
        assert "POST" in routes["/web/admin/api/database-discovery/assign"]

    def test_has_remove_route(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert "/web/admin/api/database-discovery/remove" in routes
        assert "POST" in routes["/web/admin/api/database-discovery/remove"]

    def test_has_users_route(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert "/web/admin/api/database-discovery/users" in routes

    def test_no_legacy_non_paginated_route(self) -> None:
        """Legacy /databases endpoint was removed (S1 cleanup)."""
        from pulldb.web.features.admin.database_discovery_routes import router

        routes = {
            r.path: r.methods for r in router.routes if hasattr(r, "methods")
        }
        assert "/web/admin/api/database-discovery/databases" not in routes


# =============================================================================
# Template tests
# =============================================================================


class TestDatabaseDiscoveryTemplate:
    """Tests for the database discovery HTML template."""

    def test_template_exists(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        path = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        )
        assert path.exists()

    def test_template_extends_base(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        content = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        ).read_text()
        assert '{% extends "base.html" %}' in content

    def test_template_includes_lazy_table(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        content = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        ).read_text()
        assert "lazy_table.css" in content
        assert "lazy_table.js" in content

    def test_template_has_host_selector(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        content = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        ).read_text()
        assert 'id="host-select"' in content
        assert "onHostSelected" in content

    def test_template_has_table_container(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        content = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        ).read_text()
        assert 'id="db-table-container"' in content
        assert "lazy-table-height-viewport" in content

    def test_template_has_assign_modal(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        content = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        ).read_text()
        assert 'id="assign-modal"' in content
        assert "hideAssignModal" in content

    def test_template_has_stats_bar(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        content = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        ).read_text()
        assert 'id="stat-total"' in content
        assert 'id="stat-managed"' in content
        assert 'id="stat-unmanaged"' in content

    def test_template_has_empty_state(self) -> None:
        from pulldb.web import TEMPLATES_DIR

        content = (
            TEMPLATES_DIR
            / "features"
            / "admin"
            / "database_discovery.html"
        ).read_text()
        assert 'id="db-empty-state"' in content
        assert "Select a Host" in content


# =============================================================================
# JavaScript tests (structural)
# =============================================================================


class TestDatabaseDiscoveryJavaScript:
    """Tests for the database discovery JavaScript file structure."""

    def test_js_file_exists(self) -> None:
        from pathlib import Path

        js_path = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        )
        assert js_path.exists()

    def test_js_has_iife_wrapper(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "(function() {" in content
        assert "})();" in content

    def test_js_has_escape_functions(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "function escapeHtml" in content
        assert "function escapeAttr" in content

    def test_js_has_all_renderers(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "function renderStatus" in content
        assert "function renderDatabaseName" in content
        assert "function renderOwner" in content
        assert "function renderDate" in content
        assert "function renderActions" in content

    def test_js_has_six_columns(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        # Count column definitions by key: entries
        assert "key: 'status'" in content
        assert "key: 'name'" in content
        assert "key: 'owner_user_code'" in content
        assert "key: 'deployed_at'" in content
        assert "key: 'expires_at'" in content
        assert "key: '_actions'" in content

    def test_js_no_staging_column(self) -> None:
        """Staging column was removed — only shown as badge on db name."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "key: 'is_staging'" not in content

    def test_js_uses_user_code_class(self) -> None:
        """renderOwner should use .user-code CSS class, not inline styles."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert 'class="user-code"' in content

    def test_js_action_buttons_have_aria_labels(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert 'aria-label="Claim' in content
        assert 'aria-label="Assign' in content
        assert 'aria-label="Remove' in content

    def test_js_handle_remove_calls_api(self) -> None:
        """handleRemove should call the API, not just show a toast."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "api/database-discovery/remove" in content

    def test_js_url_state_management(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "function getHostFromUrl" in content
        assert "function setHostInUrl" in content

    def test_js_lazy_table_lifecycle(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "new LazyTable" in content
        assert "table.destroy()" in content
        assert "table.refresh()" in content
        assert "table.setFetchUrl" in content
        assert "table.clearAllFilters" in content


# =============================================================================
# Origin (claim/assign) tests
# =============================================================================


class TestOriginInEnrichedData:
    """Tests that _get_enriched_databases includes origin field."""

    def test_managed_database_has_origin_restore(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        job = _make_job(target="mydb")
        state = _mock_state(databases=["mydb"], deployed_jobs=[job])
        rows, _ = _get_enriched_databases(state, "db-host-01")

        assert rows[0]["origin"] == "restore"

    def test_claimed_database_has_origin_claim(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        job = _make_job(target="external_db")
        # Simulate a claimed job by setting origin
        object.__setattr__(job, "origin", "claim")
        state = _mock_state(databases=["external_db"], deployed_jobs=[job])
        rows, _ = _get_enriched_databases(state, "db-host-01")

        assert rows[0]["origin"] == "claim"

    def test_assigned_database_has_origin_assign(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        job = _make_job(target="assigned_db")
        object.__setattr__(job, "origin", "assign")
        state = _mock_state(databases=["assigned_db"], deployed_jobs=[job])
        rows, _ = _get_enriched_databases(state, "db-host-01")

        assert rows[0]["origin"] == "assign"

    def test_unmanaged_database_has_null_origin(self) -> None:
        from pulldb.web.features.admin.database_discovery_routes import (
            _get_enriched_databases,
        )

        state = _mock_state(databases=["orphan_db"])
        rows, _ = _get_enriched_databases(state, "db-host-01")

        assert rows[0]["origin"] is None


class TestOriginBadgeInUI:
    """Tests that origin badge appears in JavaScript renderers."""

    def test_discovery_js_has_origin_badge_rendering(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/static/js/pages/admin-database-discovery.js"
        ).read_text()
        assert "badge-origin-" in content
        assert "row.origin" in content
        assert "Claimed" in content
        assert "Assigned" in content

    def test_discovery_css_has_origin_badge_styles(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/templates/features/admin/database_discovery.html"
        ).read_text()
        assert ".badge-origin-claim" in content
        assert ".badge-origin-assign" in content

    def test_job_header_shows_origin_for_nonrestore(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/templates/partials/job_header.html"
        ).read_text()
        assert "job.origin" in content
        assert "Origin" in content

    def test_jobs_list_active_status_shows_origin_badge(self) -> None:
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/templates/features/jobs/jobs.html"
        ).read_text()
        assert "row.origin" in content
        assert "Claimed" in content
        assert "Assigned" in content


class TestClaimEndpointLogic:
    """Tests for the claim endpoint wiring."""

    def test_claim_endpoint_uses_create_claimed_job(self) -> None:
        """Verify claim endpoint calls create_claimed_job, not just logs."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/features/admin/database_discovery_routes.py"
        ).read_text()
        assert 'create_claimed_job(' in content
        assert 'origin="claim"' in content
        assert 'origin="assign"' in content

    def test_remove_endpoint_checks_origin(self) -> None:
        """Verify remove endpoint only allows claim/assign removal."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/features/admin/database_discovery_routes.py"
        ).read_text()
        assert 'job.origin not in ("claim", "assign")' in content
        assert "hard_delete_job" in content

    def test_remove_endpoint_not_placeholder(self) -> None:
        """Verify remove endpoint is no longer a placeholder."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/features/admin/database_discovery_routes.py"
        ).read_text()
        assert "not yet implemented" not in content
        assert "placeholder" not in content.lower().split("class")[0]  # Only check route code, not class docs


class TestDeleteFlowOriginSafety:
    """Tests that delete flow respects origin for claimed/assigned jobs."""

    def test_single_delete_skips_db_drops_for_claimed(self) -> None:
        """Verify delete route skips database drops for claimed jobs."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/web/features/jobs/routes.py"
        ).read_text()
        assert 'job.origin in ("claim", "assign")' in content
        assert "skip_claimed_assigned" in content
        assert "_job_not_owned_by_pulldb" in content

    def test_bulk_delete_skips_db_drops_for_claimed(self) -> None:
        """Verify bulk delete handler skips database drops for claimed jobs."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/worker/admin_tasks.py"
        ).read_text()
        assert 'job.origin in ("claim", "assign")' in content
        assert "skip_claimed_assigned" in content


class TestCreateClaimedJobMethod:
    """Tests for create_claimed_job in the Job model/interface."""

    def test_job_model_has_origin_field(self) -> None:
        """Job dataclass includes origin field with default 'restore'."""
        job = Job(
            id="test-001",
            owner_user_id="u1",
            owner_username="tester",
            owner_user_code="TST",
            target="mydb",
            staging_name="mydb_stg",
            dbhost="localhost",
            status=JobStatus.DEPLOYED,
            submitted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert job.origin == "restore"

    def test_job_model_accepts_claim_origin(self) -> None:
        """Job dataclass accepts origin='claim'."""
        job = Job(
            id="test-002",
            owner_user_id="u1",
            owner_username="tester",
            owner_user_code="TST",
            target="mydb",
            staging_name="mydb_claimed",
            dbhost="localhost",
            status=JobStatus.DEPLOYED,
            submitted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            origin="claim",
        )
        assert job.origin == "claim"

    def test_interface_has_create_claimed_job(self) -> None:
        """Protocol interface includes create_claimed_job method."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/domain/interfaces.py"
        ).read_text()
        assert "def create_claimed_job(" in content

    def test_mock_has_create_claimed_job(self) -> None:
        """Mock adapter implements create_claimed_job."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/simulation/adapters/mock_mysql.py"
        ).read_text()
        assert "def create_claimed_job(" in content

    def test_migration_exists(self) -> None:
        """Migration script for origin column exists."""
        from pathlib import Path

        migration = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/schema/migrations/012_add_origin_column.sql"
        )
        assert migration.exists()
        content = migration.read_text()
        assert "origin" in content
        assert "ENUM" in content
        assert "'restore'" in content
        assert "'claim'" in content
        assert "'assign'" in content


class TestSupersedeProtection:
    """Tests that claimed/assigned jobs cannot be superseded by restores."""

    def test_enqueue_blocks_supersede_of_claimed_job(self) -> None:
        """Enqueue service blocks superseding claimed jobs before the overwrite check."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/domain/services/enqueue.py"
        ).read_text()
        # Must check origin BEFORE allowing supersede
        assert 'origin", "restore") in ("claim", "assign")' in content
        assert "DatabaseProtectionError" in content
        assert "claimed" in content.lower()

    def test_enqueue_origin_check_before_overwrite_check(self) -> None:
        """Origin check must appear before the overwrite/supersede logic."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/domain/services/enqueue.py"
        ).read_text()
        # The origin check must come before supersede_job call
        origin_pos = content.index('("claim", "assign")')
        supersede_pos = content.index("supersede_job")
        assert origin_pos < supersede_pos, (
            "Origin check must precede supersede_job to prevent orphaning claimed jobs"
        )

    def test_create_claimed_job_uses_atomic_insert(self) -> None:
        """create_claimed_job uses INSERT ... SELECT with NOT EXISTS for atomicity."""
        from pathlib import Path

        content = Path(
            "/home/charleshandshy/Projects/pullDB"
            "/pulldb/infra/mysql_jobs.py"
        ).read_text()
        # Find the create_claimed_job method area
        start = content.index("def create_claimed_job(")
        # Look within 4000 chars of the method signature
        method_area = content[start : start + 4000]
        assert "NOT EXISTS" in method_area, (
            "create_claimed_job must use INSERT ... SELECT with NOT EXISTS "
            "for atomic duplicate prevention"
        )
        assert "cursor.rowcount == 0" in method_area, (
            "create_claimed_job must check rowcount to detect the race condition"
        )

    def test_mock_create_claimed_job_rejects_duplicate(self) -> None:
        """Mock create_claimed_job rejects duplicate deployed jobs for same target."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import SimulationState
        from pulldb.simulation.core.bus import SimulationEventBus

        repo = SimulatedJobRepository.__new__(SimulatedJobRepository)
        repo.state = SimulationState()
        repo._bus = SimulationEventBus()

        # First claim succeeds
        repo.create_claimed_job(
            job_id="job-1",
            owner_user_id="u1",
            owner_username="tester",
            owner_user_code="TST",
            target="mydb",
            dbhost="host-01",
            origin="claim",
        )

        # Second claim to same target+host should fail
        import pytest

        with pytest.raises(ValueError, match="already has a deployed job"):
            repo.create_claimed_job(
                job_id="job-2",
                owner_user_id="u2",
                owner_username="other",
                owner_user_code="OTH",
                target="mydb",
                dbhost="host-01",
                origin="assign",
            )
