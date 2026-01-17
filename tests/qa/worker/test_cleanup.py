"""Tests for pulldb.worker.cleanup module.

Tests scheduled cleanup operations:
- Cleanup candidate identification
- Orphan detection
- Database dropping with verification
- Cleanup summary aggregation
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.cleanup import (
    DEFAULT_RETENTION_DAYS,
    STAGING_PATTERN,
    CleanupCandidate,
    CleanupResult,
    JobDeleteResult,
    OrphanCandidate,
    OrphanReport,
    ScheduledCleanupSummary,
    _database_exists,
    _drop_database,
    _list_databases,
    _parse_staging_name,
    delete_job_databases,
)


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

SAMPLE_DBHOST = "db-host-1.example.com"
SAMPLE_TARGET = "charleqatemplate"
SAMPLE_JOB_ID_PREFIX = "75777a4c3dd9"


# ---------------------------------------------------------------------------
# _parse_staging_name Tests
# ---------------------------------------------------------------------------


class TestParseStagingName:
    """Tests for _parse_staging_name function."""

    def test_parses_valid_staging_name(self) -> None:
        """Parses valid staging database name."""
        result = _parse_staging_name("charleqatemplate_abcdef123456")
        assert result == ("charleqatemplate", "abcdef123456")

    def test_returns_none_for_non_staging(self) -> None:
        """Returns None for non-staging database names."""
        assert _parse_staging_name("mysql") is None
        assert _parse_staging_name("information_schema") is None
        assert _parse_staging_name("charleqatemplate") is None

    def test_returns_none_for_wrong_suffix_length(self) -> None:
        """Returns None for wrong suffix length."""
        assert _parse_staging_name("target_abc123") is None  # too short
        assert _parse_staging_name("target_abcdef1234567") is None  # too long

    def test_returns_none_for_non_hex_suffix(self) -> None:
        """Returns None for non-hexadecimal suffix."""
        assert _parse_staging_name("target_ghijklmnopqr") is None

    def test_handles_underscore_in_target(self) -> None:
        """Handles target names containing underscores."""
        result = _parse_staging_name("my_target_db_abcdef123456")
        assert result == ("my_target_db", "abcdef123456")


# ---------------------------------------------------------------------------
# STAGING_PATTERN Tests
# ---------------------------------------------------------------------------


class TestStagingPattern:
    """Tests for STAGING_PATTERN regex."""

    def test_matches_valid_staging_names(self) -> None:
        """Pattern matches valid staging database names."""
        assert STAGING_PATTERN.match("target_abcdef123456")
        assert STAGING_PATTERN.match("charleqatemplate_75777a4c3dd9")
        assert STAGING_PATTERN.match("a_000000000000")

    def test_no_match_for_invalid_names(self) -> None:
        """Pattern doesn't match invalid names."""
        assert not STAGING_PATTERN.match("mysql")
        assert not STAGING_PATTERN.match("target")
        assert not STAGING_PATTERN.match("target_abc")
        assert not STAGING_PATTERN.match("target_ghijklmnopqr")


# ---------------------------------------------------------------------------
# CleanupCandidate Tests
# ---------------------------------------------------------------------------


class TestCleanupCandidate:
    """Tests for CleanupCandidate dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """CleanupCandidate can be created with required fields."""
        candidate = CleanupCandidate(
            database_name="charleqatemplate_abcdef123456",
            target_name="charleqatemplate",
            job_id_prefix="abcdef123456",
            dbhost=SAMPLE_DBHOST,
            matched_job_id="abcdef12-3456-7890-abcd-ef1234567890",
            job_status="COMPLETED",
        )
        assert candidate.database_name == "charleqatemplate_abcdef123456"
        assert candidate.db_exists is False  # default
        assert candidate.db_dropped is False  # default

    def test_optional_fields(self) -> None:
        """CleanupCandidate has optional fields."""
        candidate = CleanupCandidate(
            database_name="test_aaaaaaaaaaaa",
            target_name="test",
            job_id_prefix="aaaaaaaaaaaa",
            dbhost=SAMPLE_DBHOST,
            matched_job_id="aaaa-bbbb",
            job_status="COMPLETED",
            job_completed_at=datetime.now(UTC),
            db_exists=True,
            db_dropped=True,
            job_archived=True,
        )
        assert candidate.db_exists is True
        assert candidate.db_dropped is True
        assert candidate.job_archived is True


# ---------------------------------------------------------------------------
# OrphanCandidate Tests
# ---------------------------------------------------------------------------


class TestOrphanCandidate:
    """Tests for OrphanCandidate dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """OrphanCandidate can be created with required fields."""
        orphan = OrphanCandidate(
            database_name="orphan_abcdef123456",
            target_name="orphan",
            job_id_prefix="abcdef123456",
            dbhost=SAMPLE_DBHOST,
        )
        assert orphan.database_name == "orphan_abcdef123456"
        assert orphan.discovered_at is not None


# ---------------------------------------------------------------------------
# CleanupResult Tests
# ---------------------------------------------------------------------------


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_default_values(self) -> None:
        """CleanupResult has sensible defaults."""
        result = CleanupResult(dbhost=SAMPLE_DBHOST)
        assert result.jobs_processed == 0
        assert result.databases_dropped == 0
        assert result.errors == []
        assert result.dropped_names == []

    def test_candidates_found_alias(self) -> None:
        """candidates_found is alias for jobs_processed."""
        result = CleanupResult(dbhost=SAMPLE_DBHOST, jobs_processed=5)
        assert result.candidates_found == 5


# ---------------------------------------------------------------------------
# OrphanReport Tests
# ---------------------------------------------------------------------------


class TestOrphanReport:
    """Tests for OrphanReport dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """OrphanReport can be created with required fields."""
        report = OrphanReport(
            dbhost=SAMPLE_DBHOST,
            scanned_at=datetime.now(UTC),
        )
        assert report.dbhost == SAMPLE_DBHOST
        assert report.orphans == []


# ---------------------------------------------------------------------------
# ScheduledCleanupSummary Tests
# ---------------------------------------------------------------------------


class TestScheduledCleanupSummary:
    """Tests for ScheduledCleanupSummary dataclass."""

    def test_default_values(self) -> None:
        """ScheduledCleanupSummary has sensible defaults."""
        summary = ScheduledCleanupSummary(started_at=datetime.now(UTC))
        assert summary.retention_days == DEFAULT_RETENTION_DAYS
        assert summary.hosts_scanned == 0
        assert summary.total_dropped == 0
        assert summary.per_host_results == []

    def test_total_candidates_alias(self) -> None:
        """total_candidates is alias for total_jobs_processed."""
        summary = ScheduledCleanupSummary(
            started_at=datetime.now(UTC),
            total_jobs_processed=10,
        )
        assert summary.total_candidates == 10


# ---------------------------------------------------------------------------
# Database Operations Tests
# ---------------------------------------------------------------------------


class TestListDatabases:
    """Tests for _list_databases function."""

    def test_returns_database_list(self) -> None:
        """Returns list of database names from MySQL."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("mysql",),
            ("information_schema",),
            ("testdb",),
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_credentials = MagicMock()
        mock_credentials.host = SAMPLE_DBHOST
        mock_credentials.port = 3306
        mock_credentials.username = "user"
        mock_credentials.password = "pass"

        with patch("mysql.connector.connect", return_value=mock_conn):
            result = _list_databases(mock_credentials)

        assert result == ["mysql", "information_schema", "testdb"]
        mock_conn.close.assert_called_once()


class TestDatabaseExists:
    """Tests for _database_exists function."""

    def test_returns_true_when_exists(self) -> None:
        """Returns True when database exists."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("mysql",),
            ("testdb",),
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_credentials = MagicMock()
        mock_credentials.host = SAMPLE_DBHOST
        mock_credentials.port = 3306
        mock_credentials.username = "user"
        mock_credentials.password = "pass"

        with patch("mysql.connector.connect", return_value=mock_conn):
            result = _database_exists(mock_credentials, "testdb")

        assert result is True

    def test_returns_false_when_not_exists(self) -> None:
        """Returns False when database doesn't exist."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("mysql",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_credentials = MagicMock()
        mock_credentials.host = SAMPLE_DBHOST
        mock_credentials.port = 3306
        mock_credentials.username = "user"
        mock_credentials.password = "pass"

        with patch("mysql.connector.connect", return_value=mock_conn):
            result = _database_exists(mock_credentials, "nonexistent")

        assert result is False


class TestDropDatabase:
    """Tests for _drop_database function."""

    def test_drops_database_successfully(self) -> None:
        """Drops database and returns True when verification confirms drop."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_credentials = MagicMock()
        mock_credentials.host = SAMPLE_DBHOST
        mock_credentials.port = 3306
        mock_credentials.username = "user"
        mock_credentials.password = "pass"

        with (
            patch("mysql.connector.connect", return_value=mock_conn),
            patch(
                "pulldb.worker.cleanup._database_exists", return_value=False
            ) as mock_exists,
        ):
            result = _drop_database(mock_credentials, "testdb_abcdef123456")

        assert result is True
        mock_cursor.execute.assert_called_once_with("DROP DATABASE IF EXISTS `testdb_abcdef123456`")
        mock_exists.assert_called_once_with(mock_credentials, "testdb_abcdef123456")

    def test_returns_false_when_drop_fails(self) -> None:
        """Returns False when verification shows database still exists."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_credentials = MagicMock()
        mock_credentials.host = SAMPLE_DBHOST
        mock_credentials.port = 3306
        mock_credentials.username = "user"
        mock_credentials.password = "pass"

        with (
            patch("mysql.connector.connect", return_value=mock_conn),
            patch(
                "pulldb.worker.cleanup._database_exists", return_value=True
            ) as mock_exists,
        ):
            result = _drop_database(mock_credentials, "testdb_abcdef123456")

        assert result is False
        mock_exists.assert_called_once_with(mock_credentials, "testdb_abcdef123456")


# ---------------------------------------------------------------------------
# delete_job_databases Tests
# ---------------------------------------------------------------------------


class TestDeleteJobDatabases:
    """Tests for delete_job_databases function.
    
    Focus on the custom_target parameter which skips user_code validation.
    """

    @pytest.fixture
    def mock_host_repo(self) -> MagicMock:
        """Create mock host repository."""
        mock_repo = MagicMock()
        mock_creds = MagicMock()
        mock_creds.host = SAMPLE_DBHOST
        mock_creds.port = 3306
        mock_creds.username = "admin"
        mock_creds.password = "secret"
        mock_repo.get_host_credentials_for_maintenance.return_value = mock_creds
        return mock_repo

    def test_rejects_auto_target_without_user_code(
        self, mock_host_repo: MagicMock
    ) -> None:
        """Rejects auto-generated target that doesn't contain owner user_code."""
        # Target "myspecialdb" does NOT contain user_code "charle"
        result = delete_job_databases(
            job_id=SAMPLE_JOB_ID_PREFIX,
            staging_name="myspecialdb_abcdef123456",
            target_name="myspecialdb",  # Does NOT contain "charle"
            owner_user_code="charle",
            dbhost=SAMPLE_DBHOST,
            host_repo=mock_host_repo,
            custom_target=False,  # Auto-generated target
        )

        assert result.error is not None
        assert "does not contain" in result.error
        assert "charle" in result.error

    def test_allows_custom_target_without_user_code(
        self, mock_host_repo: MagicMock
    ) -> None:
        """Allows custom target that doesn't contain owner user_code."""
        with (
            patch("pulldb.worker.cleanup._database_exists", return_value=False),
        ):
            # Target "myspecialdb" does NOT contain user_code "charle"
            # But with custom_target=True, this should be allowed
            result = delete_job_databases(
                job_id=SAMPLE_JOB_ID_PREFIX,
                staging_name="myspecialdb_abcdef123456",
                target_name="myspecialdb",  # Custom target - no user_code prefix
                owner_user_code="charle",
                dbhost=SAMPLE_DBHOST,
                host_repo=mock_host_repo,
                custom_target=True,  # Custom target - skip user_code check
            )

        assert result.error is None  # No error - allowed

    def test_allows_auto_target_with_user_code(
        self, mock_host_repo: MagicMock
    ) -> None:
        """Allows auto-generated target that contains owner user_code."""
        with (
            patch("pulldb.worker.cleanup._database_exists", return_value=False),
        ):
            # Target "charleqatemplate" contains user_code "charle"
            result = delete_job_databases(
                job_id=SAMPLE_JOB_ID_PREFIX,
                staging_name="charleqatemplate_abcdef123456",
                target_name="charleqatemplate",  # Contains "charle"
                owner_user_code="charle",
                dbhost=SAMPLE_DBHOST,
                host_repo=mock_host_repo,
                custom_target=False,  # Auto-generated target
            )

        assert result.error is None  # No error - user_code present

    def test_skip_database_drops_returns_not_existed(
        self, mock_host_repo: MagicMock
    ) -> None:
        """skip_database_drops flag returns without checking databases."""
        result = delete_job_databases(
            job_id=SAMPLE_JOB_ID_PREFIX,
            staging_name="charleqatemplate_abcdef123456",
            target_name="charleqatemplate",
            owner_user_code="charle",
            dbhost=SAMPLE_DBHOST,
            host_repo=mock_host_repo,
            skip_database_drops=True,
        )

        assert result.staging_existed is False
        assert result.target_existed is False
        assert result.error is None
        # Should not call credentials lookup
        mock_host_repo.get_host_credentials_for_maintenance.assert_not_called()
