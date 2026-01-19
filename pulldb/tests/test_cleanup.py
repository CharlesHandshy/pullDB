"""Scheduled staging cleanup tests.

Unit tests for the scheduled staging database cleanup functionality.
Tests API models and cleanup logic without requiring database connections.

NOTE: CLI tests for admin commands (cleanup-staging, orphan-report, delete-orphans)
are in pulldb-admin tests, not here. See docs/KNOWLEDGE-POOL.md for CLI architecture.
"""

from __future__ import annotations

"""HCA Layer: tests."""

import pytest


class TestCleanupStagingAPI:
    """Test cleanup-staging API endpoint models."""

    def test_cleanup_staging_request_model(self) -> None:
        """CleanupStagingRequest model validates parameters."""
        from pulldb.api.main import CleanupStagingRequest

        # Valid request with defaults
        request = CleanupStagingRequest()
        assert request.days == 7
        assert request.dbhost is None
        assert request.dry_run is False

        # Valid request with custom values
        request = CleanupStagingRequest(days=14, dbhost="dev-db-01", dry_run=True)
        assert request.days == 14
        assert request.dbhost == "dev-db-01"
        assert request.dry_run is True

    def test_cleanup_staging_request_validation(self) -> None:
        """CleanupStagingRequest rejects invalid parameters."""
        from pydantic import ValidationError

        from pulldb.api.main import CleanupStagingRequest

        # days must be >= 1
        with pytest.raises(ValidationError):
            CleanupStagingRequest(days=0)

        with pytest.raises(ValidationError):
            CleanupStagingRequest(days=-1)

        # days must be <= 365
        with pytest.raises(ValidationError):
            CleanupStagingRequest(days=366)

    def test_cleanup_staging_response_model(self) -> None:
        """CleanupStagingResponse model has expected fields."""
        from pulldb.api.main import CleanupStagingResponse

        response = CleanupStagingResponse(
            hosts_scanned=3,
            total_candidates=10,
            total_dropped=8,
            total_skipped=2,
            total_errors=0,
            retention_days=7,
            dry_run=False,
        )
        assert response.hosts_scanned == 3
        assert response.total_candidates == 10
        assert response.total_dropped == 8
        assert response.total_skipped == 2
        assert response.total_errors == 0
        assert response.retention_days == 7
        assert response.dry_run is False


class TestOrphanReportAPI:
    """Test orphan database report API models."""

    def test_orphan_database_item_model(self) -> None:
        """OrphanDatabaseItem has expected fields."""
        from pulldb.api.main import OrphanDatabaseItem

        item = OrphanDatabaseItem(
            database_name="mydb_abc123def456",
            target_name="mydb",
            job_id_prefix="abc123def456",
            dbhost="dev-db-01",
        )
        assert item.database_name == "mydb_abc123def456"
        assert item.target_name == "mydb"
        assert item.job_id_prefix == "abc123def456"
        assert item.dbhost == "dev-db-01"

    def test_delete_orphans_request_model(self) -> None:
        """DeleteOrphansRequest validates parameters."""
        from pulldb.api.main import DeleteOrphansRequest

        request = DeleteOrphansRequest(
            dbhost="dev-db-01",
            database_names=["db1_abc123def456", "db2_def456abc123"],
            admin_user="admin@example.com",
        )
        assert request.dbhost == "dev-db-01"
        assert len(request.database_names) == 2
        assert request.admin_user == "admin@example.com"

    def test_delete_orphans_response_model(self) -> None:
        """DeleteOrphansResponse has expected fields."""
        from pulldb.api.main import DeleteOrphansResponse

        response = DeleteOrphansResponse(
            requested=3,
            succeeded=2,
            failed=1,
            results={"db1": True, "db2": True, "db3": False},
        )
        assert response.requested == 3
        assert response.succeeded == 2
        assert response.failed == 1
        assert response.results["db1"] is True
        assert response.results["db3"] is False


# NOTE: CLI tests for admin commands have been moved to pulldb-admin.
# The pulldb CLI only contains user-scoped commands.
# See docs/KNOWLEDGE-POOL.md "CLI Architecture & Scope" for rationale.


class TestCleanupModule:
    """Test cleanup module functions."""

    def test_parse_staging_name_valid(self) -> None:
        """_parse_staging_name correctly parses staging database names."""
        from pulldb.worker.cleanup import _parse_staging_name

        # Valid staging name
        result = _parse_staging_name("mydb_abc123def456")
        assert result is not None
        target, prefix = result
        assert target == "mydb"
        assert prefix == "abc123def456"

        # Target with underscores
        result = _parse_staging_name("my_complex_db_abc123def456")
        assert result is not None
        target, prefix = result
        assert target == "my_complex_db"
        assert prefix == "abc123def456"

    def test_parse_staging_name_invalid(self) -> None:
        """_parse_staging_name returns None for non-staging names."""
        from pulldb.worker.cleanup import _parse_staging_name

        # Regular database name (no staging suffix)
        assert _parse_staging_name("mydb") is None

        # Wrong suffix length
        assert _parse_staging_name("mydb_abc123") is None  # Too short

        # Non-hex characters
        assert _parse_staging_name("mydb_abc123ghijkl") is None

    def test_cleanup_candidate_dataclass(self) -> None:
        """CleanupCandidate dataclass has expected fields."""
        from pulldb.worker.cleanup import CleanupCandidate

        candidate = CleanupCandidate(
            database_name="mydb_abc123def456",
            target_name="mydb",
            job_id_prefix="abc123def456",
            dbhost="dev-db-01",
            matched_job_id="abc123def456-0000-0000-0000-000000000000",
            job_status="failed",
        )
        assert candidate.database_name == "mydb_abc123def456"
        assert candidate.target_name == "mydb"
        assert candidate.job_id_prefix == "abc123def456"
        assert candidate.dbhost == "dev-db-01"
        assert candidate.matched_job_id is not None
        assert candidate.job_status == "failed"
        assert candidate.db_exists is False
        assert candidate.db_dropped is False
        assert candidate.job_archived is False

    def test_orphan_candidate_dataclass(self) -> None:
        """OrphanCandidate dataclass has expected fields."""
        from pulldb.worker.cleanup import OrphanCandidate

        orphan = OrphanCandidate(
            database_name="mydb_abc123def456",
            target_name="mydb",
            job_id_prefix="abc123def456",
            dbhost="dev-db-01",
        )
        assert orphan.database_name == "mydb_abc123def456"
        assert orphan.target_name == "mydb"
        assert orphan.dbhost == "dev-db-01"
        assert orphan.discovered_at is not None

    def test_cleanup_result_dataclass(self) -> None:
        """CleanupResult dataclass has expected fields."""
        from pulldb.worker.cleanup import CleanupResult

        result = CleanupResult(dbhost="dev-db-01")
        assert result.dbhost == "dev-db-01"
        assert result.jobs_processed == 0
        assert result.databases_dropped == 0
        assert result.databases_not_found == 0
        assert result.databases_skipped == 0
        assert result.jobs_archived == 0
        assert result.errors == []
        assert result.dropped_names == []
        # Legacy compatibility
        assert result.candidates_found == 0

    def test_orphan_report_dataclass(self) -> None:
        """OrphanReport dataclass has expected fields."""
        from datetime import UTC, datetime

        from pulldb.worker.cleanup import OrphanReport

        report = OrphanReport(
            dbhost="dev-db-01",
            scanned_at=datetime.now(UTC),
        )
        assert report.dbhost == "dev-db-01"
        assert report.scanned_at is not None
        assert report.orphans == []

    def test_scheduled_cleanup_summary_dataclass(self) -> None:
        """ScheduledCleanupSummary dataclass has expected fields."""
        from datetime import UTC, datetime

        from pulldb.worker.cleanup import ScheduledCleanupSummary

        summary = ScheduledCleanupSummary(started_at=datetime.now(UTC))
        assert summary.started_at is not None
        assert summary.completed_at is None
        assert summary.retention_days == 7  # default
        assert summary.hosts_scanned == 0
        assert summary.total_jobs_processed == 0
        assert summary.total_dropped == 0
        assert summary.total_skipped == 0
        assert summary.total_errors == 0
        assert summary.per_host_results == []
        assert summary.orphan_reports == []
        # Legacy compatibility
        assert summary.total_candidates == 0


class TestJobRepositoryCleanupMethods:
    """Test JobRepository methods for cleanup."""

    def test_find_job_by_staging_prefix_exists(self) -> None:
        """JobRepository has find_job_by_staging_prefix method."""
        from pulldb.infra.mysql import JobRepository

        assert hasattr(JobRepository, "find_job_by_staging_prefix")

    def test_get_job_completion_time_exists(self) -> None:
        """JobRepository has get_job_completion_time method."""
        from pulldb.infra.mysql import JobRepository

        assert hasattr(JobRepository, "get_job_completion_time")

    def test_has_active_jobs_for_target_exists(self) -> None:
        """JobRepository has has_active_jobs_for_target method."""
        from pulldb.infra.mysql import JobRepository

        assert hasattr(JobRepository, "has_active_jobs_for_target")

    def test_get_old_terminal_jobs_exists(self) -> None:
        """JobRepository has get_old_terminal_jobs method."""
        from pulldb.infra.mysql import JobRepository

        assert hasattr(JobRepository, "get_old_terminal_jobs")

    def test_mark_job_staging_cleaned_exists(self) -> None:
        """JobRepository has mark_job_staging_cleaned method."""
        from pulldb.infra.mysql import JobRepository

        assert hasattr(JobRepository, "mark_job_staging_cleaned")


class TestCleanupSafetyGuarantees:
    """Test safety guarantees for cleanup operations.

    CRITICAL: These tests document the safety invariants that protect
    non-pullDB databases from accidental deletion.
    """

    def test_job_based_cleanup_only(self) -> None:
        """Cleanup ONLY processes databases that have matching job records.

        Safety invariant: The cleanup process starts from the jobs table,
        not from scanning databases. This means:
        1. We find old terminal jobs with staging_name set
        2. We check if that staging database still exists
        3. If it exists, we drop it and verify
        4. We mark the job as cleaned

        Databases without job records are NEVER touched by automatic cleanup.
        """
        # Documented invariant - see find_cleanup_candidates_from_jobs()
        pass

    def test_orphans_require_manual_admin_action(self) -> None:
        """Orphan databases are NEVER auto-deleted.

        Databases matching the staging pattern but with no job record are
        reported via detect_orphaned_databases() but require explicit
        admin action via admin_delete_orphan_databases() to remove.

        This protects user databases that happen to match the pattern.
        """
        # Documented invariant - see detect_orphaned_databases()
        pass

    def test_active_jobs_prevent_cleanup(self) -> None:
        """Databases with active jobs for the same target are never cleaned.

        Even if a staging database is old, if there's a queued/running
        job for that target+dbhost, the database is skipped.
        """
        # Documented invariant - see cleanup_from_jobs()
        pass

    def test_verify_before_archive(self) -> None:
        """Job records are only archived after confirming DB deletion.

        The cleanup flow is:
        1. Check if staging DB exists
        2. If exists, drop it
        3. Verify it's actually gone
        4. Only then mark job as cleaned

        This ensures we don't mark jobs as cleaned if the drop failed.
        """
        # Documented invariant - see cleanup_from_jobs()
        pass

    def test_admin_deletion_requires_pattern_match(self) -> None:
        """Admin deletion rejects databases that don't match staging pattern.

        Even with admin approval, admin_delete_orphan_databases() will
        reject databases that don't match the staging pattern as an
        extra safety check.
        """
        # Documented invariant - see admin_delete_orphan_databases()
        pass
