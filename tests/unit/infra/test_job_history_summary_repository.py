"""Unit tests for JobHistorySummaryRepository.

Tests the job history summary repository including:
- insert() validation and behavior
- categorize_error() classification
- delete_by_* methods
- count_matching() and get_stats()

HCA Layer: tests (validation of shared/infra layer)
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from pulldb.infra.mysql import JobHistorySummaryRepository


class TestCategorizeError:
    """Tests for JobHistorySummaryRepository.categorize_error()."""

    def test_categorize_error_none_returns_uncategorized(self) -> None:
        """None error_detail returns 'uncategorized'."""
        result = JobHistorySummaryRepository.categorize_error(None)
        assert result == "uncategorized"

    def test_categorize_error_empty_string_returns_uncategorized(self) -> None:
        """Empty string returns 'uncategorized'."""
        result = JobHistorySummaryRepository.categorize_error("")
        assert result == "uncategorized"

    def test_categorize_error_mysql_keywords(self) -> None:
        """MySQL-related errors are categorized as mysql_error."""
        test_cases = [
            "MySQL connection refused",
            "database error: connection failed",
            "Access denied for user 'root'",
            "mysql.connector.errors.InterfaceError",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            assert result == "mysql_error", f"Expected mysql_error for: {error}"

    def test_categorize_error_mysql_timeout_is_mysql_error(self) -> None:
        """MySQL timeout should be mysql_error, not download_timeout.

        This tests the priority ordering fix - mysql errors are checked
        before generic timeout keywords.
        """
        result = JobHistorySummaryRepository.categorize_error(
            "MySQL connection timeout"
        )
        assert result == "mysql_error"

        result = JobHistorySummaryRepository.categorize_error("mysql read timed out")
        assert result == "mysql_error"

    def test_categorize_error_download_timeout(self) -> None:
        """Download timeout errors without mysql keywords."""
        test_cases = [
            "S3 download timeout after 300s",
            "Connection timed out to remote host",
            "Deadline exceeded waiting for response",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            msg = f"Expected download_timeout for: {error}"
            assert result == "download_timeout", msg

    def test_categorize_error_download_failed(self) -> None:
        """Download failure errors."""
        test_cases = [
            "S3 download failed: network error",
            "Connection reset by peer during download",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            assert result == "download_failed", f"Expected download_failed for: {error}"

    def test_categorize_error_extraction_failed(self) -> None:
        """Extraction failure errors."""
        test_cases = [
            "Extraction failed: corrupted archive",
            "Failed to unpack tarball",
            "Decompress error: invalid gzip header",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            msg = f"Expected extraction_failed for: {error}"
            assert result == "extraction_failed", msg

    def test_categorize_error_disk_full(self) -> None:
        """Disk space errors."""
        test_cases = [
            "No space left on device",
            "Disk full: cannot write to /tmp",
            "Quota exceeded for user",
            "OSError: [Errno 28] ENOSPC",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            assert result == "disk_full", f"Expected disk_full for: {error}"

    def test_categorize_error_s3_access_denied(self) -> None:
        """S3 access errors."""
        test_cases = [
            "AccessDenied: bucket policy prevents access",
            "403 Forbidden: insufficient permissions",
            "Invalid credentials for S3 bucket",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            msg = f"Expected s3_access_denied for: {error}"
            assert result == "s3_access_denied", msg

    def test_categorize_error_canceled_by_user(self) -> None:
        """User cancellation errors."""
        test_cases = [
            "Job canceled by user request",
            "Aborted by user at checkpoint",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            msg = f"Expected canceled_by_user for: {error}"
            assert result == "canceled_by_user", msg

    def test_categorize_error_worker_crash(self) -> None:
        """Worker crash errors."""
        test_cases = [
            "Worker process crashed unexpectedly",
            "Segfault in myloader process",
            "Process killed by OOM killer",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            assert result == "worker_crash", f"Expected worker_crash for: {error}"

    def test_categorize_error_unknown_returns_uncategorized(self) -> None:
        """Unknown errors return 'uncategorized'."""
        test_cases = [
            "Some random error message",
            "Unexpected exception occurred",
            "ValueError: invalid argument",
        ]
        for error in test_cases:
            result = JobHistorySummaryRepository.categorize_error(error)
            assert result == "uncategorized", f"Expected uncategorized for: {error}"

    def test_categorize_error_case_insensitive(self) -> None:
        """Error categorization is case-insensitive."""
        result = JobHistorySummaryRepository.categorize_error("MYSQL ERROR")
        assert result == "mysql_error"
        result = JobHistorySummaryRepository.categorize_error("TIMEOUT")
        assert result == "download_timeout"
        result = JobHistorySummaryRepository.categorize_error("No Space")
        assert result == "disk_full"


class TestValidation:
    """Tests for input validation in JobHistorySummaryRepository."""

    def test_valid_statuses_constant(self) -> None:
        """VALID_STATUSES matches schema ENUM."""
        expected = {"complete", "failed", "canceled"}
        assert expected == JobHistorySummaryRepository.VALID_STATUSES

    def test_valid_error_categories_constant(self) -> None:
        """VALID_ERROR_CATEGORIES matches schema ENUM."""
        expected = {
            "download_timeout", "download_failed", "extraction_failed",
            "mysql_error", "disk_full", "s3_access_denied",
            "canceled_by_user", "worker_crash", "uncategorized",
        }
        assert expected == JobHistorySummaryRepository.VALID_ERROR_CATEGORIES


class TestInsert:
    """Tests for JobHistorySummaryRepository.insert()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create mock MySQL pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> JobHistorySummaryRepository:
        """Create repository with mock pool."""
        return JobHistorySummaryRepository(mock_pool)

    @pytest.fixture
    def valid_insert_kwargs(self) -> dict:
        """Valid kwargs for insert()."""
        return {
            "job_id": "test-job-123",
            "owner_user_id": "user-456",
            "owner_username": "testuser",
            "dbhost": "mysql-prod.example.com",
            "target": "mydb",
            "custom_target": False,
            "submitted_at": datetime.now(UTC),
            "started_at": datetime.now(UTC),
            "completed_at": datetime.now(UTC),
            "final_status": "complete",
            "error_category": None,
        }

    def test_insert_valid_complete_status(
        self, repo: JobHistorySummaryRepository, valid_insert_kwargs: dict
    ) -> None:
        """Insert with valid 'complete' status succeeds."""
        valid_insert_kwargs["final_status"] = "complete"
        result = repo.insert(**valid_insert_kwargs)
        assert result is True

    def test_insert_valid_failed_status(
        self, repo: JobHistorySummaryRepository, valid_insert_kwargs: dict
    ) -> None:
        """Insert with valid 'failed' status succeeds."""
        valid_insert_kwargs["final_status"] = "failed"
        valid_insert_kwargs["error_category"] = "mysql_error"
        result = repo.insert(**valid_insert_kwargs)
        assert result is True

    def test_insert_valid_canceled_status(
        self, repo: JobHistorySummaryRepository, valid_insert_kwargs: dict
    ) -> None:
        """Insert with valid 'canceled' status succeeds."""
        valid_insert_kwargs["final_status"] = "canceled"
        valid_insert_kwargs["error_category"] = "canceled_by_user"
        result = repo.insert(**valid_insert_kwargs)
        assert result is True

    def test_insert_invalid_status_returns_false(
        self, repo: JobHistorySummaryRepository, valid_insert_kwargs: dict
    ) -> None:
        """Insert with invalid status returns False without DB call."""
        valid_insert_kwargs["final_status"] = "invalid_status"
        result = repo.insert(**valid_insert_kwargs)
        assert result is False

    def test_insert_invalid_error_category_returns_false(
        self, repo: JobHistorySummaryRepository, valid_insert_kwargs: dict
    ) -> None:
        """Insert with invalid error_category returns False without DB call."""
        valid_insert_kwargs["error_category"] = "invalid_category"
        result = repo.insert(**valid_insert_kwargs)
        assert result is False

    def test_insert_none_error_category_allowed(
        self, repo: JobHistorySummaryRepository, valid_insert_kwargs: dict
    ) -> None:
        """Insert with None error_category is allowed."""
        valid_insert_kwargs["error_category"] = None
        result = repo.insert(**valid_insert_kwargs)
        assert result is True

    def test_insert_all_valid_error_categories(
        self, repo: JobHistorySummaryRepository, valid_insert_kwargs: dict
    ) -> None:
        """All valid error categories can be inserted."""
        valid_insert_kwargs["final_status"] = "failed"
        for category in JobHistorySummaryRepository.VALID_ERROR_CATEGORIES:
            valid_insert_kwargs["error_category"] = category
            result = repo.insert(**valid_insert_kwargs)
            assert result is True, f"Failed for category: {category}"


class TestDeleteMethods:
    """Tests for JobHistorySummaryRepository delete methods."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create mock MySQL pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 5
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> JobHistorySummaryRepository:
        """Create repository with mock pool."""
        return JobHistorySummaryRepository(mock_pool)

    def test_delete_by_ids_empty_list_returns_zero(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """delete_by_ids with empty list returns 0 without DB call."""
        result = repo.delete_by_ids([])
        assert result == 0

    def test_delete_by_ids_returns_rowcount(
        self, repo: JobHistorySummaryRepository, mock_pool: MagicMock
    ) -> None:
        """delete_by_ids returns sum of cursor.rowcount across batches."""
        # With rowcount=5 and 3 IDs (single batch), returns 5
        result = repo.delete_by_ids(["job1", "job2", "job3"])
        assert result == 5  # Mock rowcount for single batch

    def test_delete_by_date_requires_boundary(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """delete_by_date raises ValueError if no boundary provided."""
        with pytest.raises(ValueError, match="At least one date boundary required"):
            repo.delete_by_date(before=None, after=None)

    def test_delete_by_user_requires_identifier(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """delete_by_user raises ValueError if no user identifier provided."""
        with pytest.raises(ValueError, match="user_id or username required"):
            repo.delete_by_user(user_id=None, username=None)

    def test_delete_by_status_validates_status(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """delete_by_status raises ValueError for invalid status."""
        with pytest.raises(ValueError, match="Invalid status"):
            repo.delete_by_status(status="invalid")

    def test_delete_by_status_accepts_valid_statuses(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """delete_by_status accepts valid status values (batched delete)."""
        for status in ["complete", "failed", "canceled"]:
            result = repo.delete_by_status(status=status)
            # Returns 5 on first batch, then 0 terminates loop
            assert result == 5


class TestReadMethodValidation:
    """Tests for status validation in count_matching and get_records."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create mock MySQL pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (10,)
        cursor.fetchall.return_value = []
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> JobHistorySummaryRepository:
        """Create repository with mock pool."""
        return JobHistorySummaryRepository(mock_pool)

    def test_count_matching_invalid_status_returns_zero(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """count_matching with invalid status returns 0."""
        result = repo.count_matching(status="invalid_status")
        assert result == 0

    def test_count_matching_valid_status_queries_db(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """count_matching with valid status queries database."""
        result = repo.count_matching(status="complete")
        assert result == 10  # Mock fetchone returns (10,)

    def test_get_records_invalid_status_returns_empty(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """get_records with invalid status returns empty list."""
        result = repo.get_records(status="invalid_status")
        assert result == []

    def test_get_records_valid_status_queries_db(
        self, repo: JobHistorySummaryRepository
    ) -> None:
        """get_records with valid status queries database."""
        result = repo.get_records(status="failed")
        assert result == []  # Mock fetchall returns []
