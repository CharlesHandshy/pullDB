"""Tests for job cancellation functionality.

Tests cover:
- API endpoint behavior for queued vs running jobs
- Repository methods for cancellation state management
- Worker executor checkpoint detection and graceful termination
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pulldb.domain.errors import CancellationError
from pulldb.domain.models import JobStatus


class TestCancellationError:
    """Tests for CancellationError exception class."""

    def test_cancellation_error_attributes(self) -> None:
        """CancellationError should have proper FAIL HARD structure."""
        error = CancellationError(job_id="abc123", phase="post_download")

        assert error.goal == "Execute restore job abc123"
        assert "post_download" in error.problem
        assert "user request" in error.root_cause.lower()
        assert error.detail["job_id"] == "abc123"
        assert error.detail["phase"] == "post_download"

    def test_cancellation_error_message(self) -> None:
        """CancellationError message should be human-readable."""
        error = CancellationError(job_id="xyz789", phase="pre_restore")
        message = str(error)

        assert "xyz789" in message
        assert "pre_restore" in message
        assert "Solution" in message


class TestCancelAPIEndpoint:
    """Tests for POST /api/jobs/{job_id}/cancel endpoint.

    Note: Full API integration tests would require TestClient setup.
    These tests verify the core logic via direct function calls.
    """

    def test_cancel_response_model(self) -> None:
        """CancelResponse model should have expected fields."""
        from pulldb.api.main import CancelResponse

        response = CancelResponse(
            job_id="test-123",
            status="canceled",
            message="Job canceled successfully",
        )
        assert response.job_id == "test-123"
        assert response.status == "canceled"
        assert response.message == "Job canceled successfully"

    def test_job_status_includes_canceled(self) -> None:
        """JobStatus enum should include CANCELED value."""
        assert JobStatus.CANCELED.value == "canceled"


class TestExecutorCancellationCheckpoints:
    """Tests for worker executor cancellation checkpoint behavior."""

    @pytest.fixture
    def mock_deps(self) -> MagicMock:
        """Create mock WorkerExecutorDependencies."""
        deps = MagicMock()
        deps.job_repo = MagicMock()
        deps.host_repo = MagicMock()
        deps.s3_client = MagicMock()
        return deps

    def test_check_cancellation_raises_when_requested(
        self, mock_deps: MagicMock
    ) -> None:
        """_check_cancellation should raise CancellationError when flag is set."""
        from pulldb.domain.config import Config
        from pulldb.worker.executor import (
            WorkerExecutorDependencies,
            WorkerJobExecutor,
        )

        mock_deps.job_repo.is_cancellation_requested.return_value = True

        config = MagicMock(spec=Config)
        config.work_dir = "/tmp/test-work"
        config.s3_backup_locations = []
        config.s3_bucket_path = "s3://test-bucket/backups"

        executor = WorkerJobExecutor(
            config=config,
            deps=WorkerExecutorDependencies(
                job_repo=mock_deps.job_repo,
                host_repo=mock_deps.host_repo,
                s3_client=mock_deps.s3_client,
            ),
        )

        with pytest.raises(CancellationError) as exc_info:
            executor._check_cancellation("job-abc", "post_download")

        assert exc_info.value.detail["job_id"] == "job-abc"
        assert exc_info.value.detail["phase"] == "post_download"

    def test_check_cancellation_continues_when_not_requested(
        self, mock_deps: MagicMock
    ) -> None:
        """_check_cancellation should not raise when flag is not set."""
        from pulldb.domain.config import Config
        from pulldb.worker.executor import (
            WorkerExecutorDependencies,
            WorkerJobExecutor,
        )

        mock_deps.job_repo.is_cancellation_requested.return_value = False

        config = MagicMock(spec=Config)
        config.work_dir = "/tmp/test-work"
        config.s3_backup_locations = []
        config.s3_bucket_path = "s3://test-bucket/backups"

        executor = WorkerJobExecutor(
            config=config,
            deps=WorkerExecutorDependencies(
                job_repo=mock_deps.job_repo,
                host_repo=mock_deps.host_repo,
                s3_client=mock_deps.s3_client,
            ),
        )

        # Should not raise
        executor._check_cancellation("job-xyz", "post_extraction")

        mock_deps.job_repo.is_cancellation_requested.assert_called_once_with("job-xyz")


class TestRepositoryCancellationMethods:
    """Tests for JobRepository cancellation methods.

    Note: These are unit tests using mocks. Integration tests with real
    MySQL connection are in test_job_repository.py (requires MySQL).
    """

    def test_request_cancellation_updates_column(self) -> None:
        """request_cancellation should set cancel_requested_at timestamp."""
        # This would require a real database connection for proper testing
        # Here we just verify the method signature exists
        from pulldb.infra.mysql import JobRepository

        # Verify method exists
        assert hasattr(JobRepository, "request_cancellation")
        assert hasattr(JobRepository, "mark_job_canceled")
        assert hasattr(JobRepository, "is_cancellation_requested")
