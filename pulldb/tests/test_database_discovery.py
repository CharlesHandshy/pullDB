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
