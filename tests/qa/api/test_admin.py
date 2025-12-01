"""
Category 6: Admin Endpoint Tests

Tests for:
- POST /api/admin/prune-logs
- POST /api/admin/cleanup-staging
- GET /api/admin/orphan-databases
- POST /api/admin/delete-orphans

Test Count: 16 tests
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from .conftest import (
    SAMPLE_DBHOST,
    assert_contains,
    assert_error,
    assert_success,
)


# ---------------------------------------------------------------------------
# Prune Logs
# ---------------------------------------------------------------------------


class TestPruneLogs:
    """Tests for prune-logs admin endpoint."""

    def test_prune_logs_dry_run(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/prune-logs dry run returns count."""
        # Mock the pool connection for dry run query
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (42,)
        mock_api_state._mock_job_repo.pool.connection.return_value.__enter__ = (
            MagicMock(return_value=MagicMock(cursor=MagicMock(return_value=mock_cursor)))
        )

        response = client.post(
            "/api/admin/prune-logs",
            json={"days": 90, "dry_run": True},
        )
        data = assert_success(response)
        assert_contains(data, "deleted", "would_delete", "retention_days", "dry_run")
        assert data["dry_run"] is True

    def test_prune_logs_execute(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/prune-logs execute deletes events."""
        mock_api_state._mock_job_repo.prune_job_events.return_value = 100

        response = client.post(
            "/api/admin/prune-logs",
            json={"days": 90, "dry_run": False},
        )
        data = assert_success(response)
        assert data["dry_run"] is False
        assert data["deleted"] == 100

    def test_prune_logs_default_days(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/prune-logs uses default 90 days."""
        mock_api_state._mock_job_repo.prune_job_events.return_value = 0

        response = client.post("/api/admin/prune-logs", json={})
        data = assert_success(response)
        assert data["retention_days"] == 90


# ---------------------------------------------------------------------------
# Cleanup Staging
# ---------------------------------------------------------------------------


class TestCleanupStaging:
    """Tests for cleanup-staging admin endpoint."""

    def test_cleanup_staging_dry_run(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/cleanup-staging dry run."""
        with patch("pulldb.worker.cleanup.run_scheduled_cleanup") as mock_cleanup:
            mock_summary = MagicMock()
            mock_summary.hosts_scanned = 2
            mock_summary.total_candidates = 5
            mock_summary.total_dropped = 0
            mock_summary.total_skipped = 5
            mock_summary.total_errors = 0
            mock_cleanup.return_value = mock_summary

            response = client.post(
                "/api/admin/cleanup-staging",
                json={"days": 7, "dry_run": True},
            )
            data = assert_success(response)
            assert_contains(
                data, "hosts_scanned", "total_candidates", "total_dropped", "dry_run"
            )
            assert data["dry_run"] is True

    def test_cleanup_staging_execute(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/cleanup-staging execute."""
        with patch("pulldb.worker.cleanup.run_scheduled_cleanup") as mock_cleanup:
            mock_summary = MagicMock()
            mock_summary.hosts_scanned = 2
            mock_summary.total_candidates = 5
            mock_summary.total_dropped = 5
            mock_summary.total_skipped = 0
            mock_summary.total_errors = 0
            mock_cleanup.return_value = mock_summary

            response = client.post(
                "/api/admin/cleanup-staging",
                json={"days": 7, "dry_run": False},
            )
            data = assert_success(response)
            assert data["total_dropped"] == 5

    def test_cleanup_staging_specific_host(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/cleanup-staging for specific host."""
        with patch("pulldb.worker.cleanup.cleanup_host_staging") as mock_cleanup:
            mock_result = MagicMock()
            mock_result.candidates_found = 3
            mock_result.databases_dropped = 3
            mock_result.databases_skipped = 0
            mock_result.errors = []
            mock_cleanup.return_value = mock_result

            response = client.post(
                "/api/admin/cleanup-staging",
                json={"days": 7, "dbhost": SAMPLE_DBHOST, "dry_run": False},
            )
            data = assert_success(response)
            assert data["hosts_scanned"] == 1


# ---------------------------------------------------------------------------
# Orphan Databases
# ---------------------------------------------------------------------------


class TestOrphanDatabases:
    """Tests for orphan-databases admin endpoint."""

    def test_get_orphan_databases(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/admin/orphan-databases returns report."""
        with patch("pulldb.worker.cleanup.detect_orphaned_databases") as mock_detect:
            mock_report = MagicMock()
            mock_report.scanned_at = MagicMock()
            mock_report.scanned_at.isoformat.return_value = "2025-01-15T10:00:00"
            mock_report.orphans = []
            mock_detect.return_value = mock_report

            mock_api_state._mock_host_repo.get_enabled_hosts.return_value = []

            response = client.get("/api/admin/orphan-databases")
            data = assert_success(response)
            assert_contains(data, "hosts_scanned", "total_orphans", "reports")

    def test_get_orphan_databases_specific_host(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/admin/orphan-databases?dbhost=xxx for specific host."""
        with patch("pulldb.worker.cleanup.detect_orphaned_databases") as mock_detect:
            mock_report = MagicMock()
            mock_report.scanned_at = MagicMock()
            mock_report.scanned_at.isoformat.return_value = "2025-01-15T10:00:00"
            mock_report.orphans = []
            mock_detect.return_value = mock_report

            response = client.get(
                "/api/admin/orphan-databases", params={"dbhost": SAMPLE_DBHOST}
            )
            data = assert_success(response)
            assert data["hosts_scanned"] == 1


# ---------------------------------------------------------------------------
# Delete Orphans
# ---------------------------------------------------------------------------


class TestDeleteOrphans:
    """Tests for delete-orphans admin endpoint."""

    def test_delete_orphans(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/delete-orphans deletes specified databases."""
        patch_path = "pulldb.worker.cleanup.admin_delete_orphan_databases"
        with patch(patch_path) as mock_delete:
            mock_delete.return_value = {"orphan_db_1": True, "orphan_db_2": True}

            response = client.post(
                "/api/admin/delete-orphans",
                json={
                    "dbhost": SAMPLE_DBHOST,
                    "database_names": ["orphan_db_1", "orphan_db_2"],
                    "admin_user": "admin",
                },
            )
            data = assert_success(response)
            assert_contains(data, "requested", "succeeded", "failed", "results")
            assert data["succeeded"] == 2
            assert data["failed"] == 0

    def test_delete_orphans_partial_failure(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/admin/delete-orphans with some failures."""
        patch_path = "pulldb.worker.cleanup.admin_delete_orphan_databases"
        with patch(patch_path) as mock_delete:
            mock_delete.return_value = {"orphan_db_1": True, "orphan_db_2": False}

            response = client.post(
                "/api/admin/delete-orphans",
                json={
                    "dbhost": SAMPLE_DBHOST,
                    "database_names": ["orphan_db_1", "orphan_db_2"],
                    "admin_user": "admin",
                },
            )
            data = assert_success(response)
            assert data["succeeded"] == 1
            assert data["failed"] == 1

    def test_delete_orphans_requires_admin_user(
        self, client: TestClient
    ) -> None:
        """POST /api/admin/delete-orphans requires admin_user field."""
        response = client.post(
            "/api/admin/delete-orphans",
            json={
                "dbhost": SAMPLE_DBHOST,
                "database_names": ["orphan_db_1"],
            },
        )
        assert response.status_code == 422
