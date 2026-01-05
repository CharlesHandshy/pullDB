"""Tests for stale deleting job recovery feature.

Tests the new functionality for recovering jobs stuck in 'deleting' status:
- mark_job_deleting() with retry tracking
- claim_stale_deleting_job() for worker recovery
- mark_job_delete_failed() for permanent failures
- execute_delete_job() for delete workflow
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pulldb.domain.models import Job, JobStatus
from pulldb.worker.cleanup import (
    DeleteJobResult,
    MAX_DELETE_RETRY_COUNT,
    execute_delete_job,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_job_repo():
    """Create a mock job repository."""
    repo = MagicMock()
    repo.append_job_event = MagicMock()
    repo.mark_job_deleted = MagicMock()
    repo.mark_job_delete_failed = MagicMock()
    return repo


@pytest.fixture
def mock_host_repo():
    """Create a mock host repository."""
    repo = MagicMock()
    return repo


@pytest.fixture
def sample_deleting_job():
    """Create a sample job in deleting status."""
    return Job(
        id="test-job-123456789012",
        owner_user_id="user-123",
        owner_username="testuser",
        owner_user_code="TS0001",
        target="TS0001customer_db",
        staging_name="TS0001customer_db_test12345678",
        dbhost="mysql-host-1",
        status=JobStatus.DELETING,
        submitted_at=datetime.now(UTC) - timedelta(hours=1),
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        completed_at=None,
        options_json=None,
        retry_count=1,
        error_detail=None,
        worker_id=None,
    )


# =============================================================================
# DeleteJobResult Tests
# =============================================================================


class TestDeleteJobResult:
    """Tests for DeleteJobResult dataclass."""

    def test_default_values(self):
        """Test default field values."""
        result = DeleteJobResult(job_id="job-123", success=False)
        assert result.job_id == "job-123"
        assert result.success is False
        assert result.databases_already_gone is False
        assert result.retry_count == 0
        assert result.error is None

    def test_all_fields(self):
        """Test all fields can be set."""
        result = DeleteJobResult(
            job_id="job-456",
            success=True,
            databases_already_gone=True,
            retry_count=3,
            error="some error",
        )
        assert result.success is True
        assert result.databases_already_gone is True
        assert result.retry_count == 3
        assert result.error == "some error"


# =============================================================================
# execute_delete_job Tests
# =============================================================================


class TestExecuteDeleteJob:
    """Tests for execute_delete_job function."""

    def test_credentials_failure_under_max_retries(
        self, mock_job_repo, mock_host_repo, sample_deleting_job
    ):
        """Test handling of credential failure when under max retries."""
        mock_host_repo.get_host_credentials.side_effect = Exception("Auth failed")
        
        result = execute_delete_job(sample_deleting_job, mock_job_repo, mock_host_repo)
        
        assert result.success is False
        assert "Auth failed" in result.error
        # Should NOT call mark_job_delete_failed (retry_count=1 < 5)
        mock_job_repo.mark_job_delete_failed.assert_not_called()

    def test_credentials_failure_at_max_retries(
        self, mock_job_repo, mock_host_repo, sample_deleting_job
    ):
        """Test handling of credential failure when at max retries."""
        job_at_max = replace(sample_deleting_job, retry_count=MAX_DELETE_RETRY_COUNT)
        mock_host_repo.get_host_credentials.side_effect = Exception("Auth failed")
        
        result = execute_delete_job(job_at_max, mock_job_repo, mock_host_repo)
        
        assert result.success is False
        # SHOULD call mark_job_delete_failed (retry_count >= 5)
        mock_job_repo.mark_job_delete_failed.assert_called_once()

    @patch("pulldb.worker.cleanup._database_exists")
    def test_databases_already_gone(
        self, mock_db_exists, mock_job_repo, mock_host_repo, sample_deleting_job
    ):
        """Test handling when both databases are already deleted."""
        mock_host_repo.get_host_credentials.return_value = MagicMock()
        mock_db_exists.return_value = False  # Both DBs don't exist
        
        result = execute_delete_job(sample_deleting_job, mock_job_repo, mock_host_repo)
        
        assert result.success is True
        assert result.databases_already_gone is True
        # Should log delete_skipped event
        mock_job_repo.append_job_event.assert_called_once()
        call_args = mock_job_repo.append_job_event.call_args
        assert call_args[0][1] == "delete_skipped"
        # Should mark as deleted
        mock_job_repo.mark_job_deleted.assert_called_once()

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup.delete_job_databases")
    def test_successful_delete(
        self,
        mock_delete_dbs,
        mock_db_exists,
        mock_job_repo,
        mock_host_repo,
        sample_deleting_job,
    ):
        """Test successful database deletion."""
        mock_host_repo.get_host_credentials.return_value = MagicMock()
        mock_db_exists.return_value = True  # DBs exist
        mock_delete_dbs.return_value = MagicMock(
            error=None,
            staging_dropped=True,
            target_dropped=True,
        )
        
        result = execute_delete_job(sample_deleting_job, mock_job_repo, mock_host_repo)
        
        assert result.success is True
        assert result.databases_already_gone is False
        mock_job_repo.mark_job_deleted.assert_called_once()

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup.delete_job_databases")
    def test_delete_failure_under_max_retries(
        self,
        mock_delete_dbs,
        mock_db_exists,
        mock_job_repo,
        mock_host_repo,
        sample_deleting_job,
    ):
        """Test delete failure when under max retries."""
        mock_host_repo.get_host_credentials.return_value = MagicMock()
        mock_db_exists.return_value = True
        mock_delete_dbs.return_value = MagicMock(
            error="Protection check failed",
            staging_dropped=False,
            target_dropped=False,
        )
        
        result = execute_delete_job(sample_deleting_job, mock_job_repo, mock_host_repo)
        
        assert result.success is False
        assert "Protection check failed" in result.error
        # Should NOT mark as failed (under max retries)
        mock_job_repo.mark_job_delete_failed.assert_not_called()
        mock_job_repo.mark_job_deleted.assert_not_called()

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup.delete_job_databases")
    def test_delete_failure_at_max_retries(
        self,
        mock_delete_dbs,
        mock_db_exists,
        mock_job_repo,
        mock_host_repo,
        sample_deleting_job,
    ):
        """Test delete failure when at max retries."""
        job_at_max = replace(sample_deleting_job, retry_count=MAX_DELETE_RETRY_COUNT)
        mock_host_repo.get_host_credentials.return_value = MagicMock()
        mock_db_exists.return_value = True
        mock_delete_dbs.return_value = MagicMock(
            error="Drop failed",
            staging_dropped=False,
            target_dropped=False,
        )
        
        result = execute_delete_job(job_at_max, mock_job_repo, mock_host_repo)
        
        assert result.success is False
        # SHOULD mark as failed
        mock_job_repo.mark_job_delete_failed.assert_called_once()


# =============================================================================
# Mock Repository Method Tests (using simulation adapter)
# =============================================================================


class TestMockJobRepositoryDeleteMethods:
    """Tests for mock repository delete methods."""

    def _create_test_job(self, repo, job_id: str = "test-job-12345678901234567890") -> str:
        """Helper to create a test job via enqueue_job."""
        job = Job(
            id=job_id,
            owner_user_id="user-1",
            owner_username="testuser",
            owner_user_code="TS0001",
            target="TS0001test",
            staging_name="TS0001test_abc123456789",
            dbhost="host1",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
            options_json=None,
            retry_count=0,
            error_detail=None,
            worker_id=None,
        )
        return repo.enqueue_job(job)

    def test_mark_job_deleting_increments_retry_count(self):
        """Test that mark_job_deleting increments retry_count."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        # Reset state for clean test
        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create a job
        job_id = self._create_test_job(repo)

        # Initial retry_count should be 0
        job = repo.get_job_by_id(job_id)
        assert job.retry_count == 0

        # Mark as deleting
        repo.mark_job_deleting(job_id)
        job = repo.get_job_by_id(job_id)
        
        assert job.status == JobStatus.DELETING
        assert job.retry_count == 1
        assert job.started_at is not None
        assert job.worker_id is None

    def test_claim_stale_deleting_job_finds_stale_jobs(self):
        """Test that claim_stale_deleting_job finds jobs older than timeout."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        # Reset state for clean test
        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create a job and mark as deleting
        job_id = self._create_test_job(repo)
        repo.mark_job_deleting(job_id)

        # Manually backdate started_at to make it stale
        job = state.jobs[job_id]
        stale_time = datetime.now(UTC) - timedelta(minutes=10)
        state.jobs[job_id] = replace(job, started_at=stale_time)

        # Should find the stale job
        claimed = repo.claim_stale_deleting_job(
            worker_id="worker-1",
            stale_timeout_minutes=5,
        )
        
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.retry_count == 2  # Incremented from 1
        assert claimed.worker_id == "worker-1"

    def test_claim_stale_deleting_job_respects_max_retry(self):
        """Test that claim_stale_deleting_job respects max retry count."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        # Reset state for clean test
        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create job
        job_id = self._create_test_job(repo)
        
        # Manually set to deleting with max retries
        job = state.jobs[job_id]
        stale_time = datetime.now(UTC) - timedelta(minutes=10)
        state.jobs[job_id] = replace(
            job,
            status=JobStatus.DELETING,
            started_at=stale_time,
            retry_count=5,  # At max
        )

        # Should NOT find the job (at max retries)
        claimed = repo.claim_stale_deleting_job(
            worker_id="worker-1",
            stale_timeout_minutes=5,
            max_retry_count=5,
        )
        
        assert claimed is None

    def test_mark_job_delete_failed_sets_failed_status(self):
        """Test that mark_job_delete_failed sets status to failed."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import reset_simulation

        # Reset state for clean test
        reset_simulation()
        repo = SimulatedJobRepository()

        job_id = self._create_test_job(repo)
        repo.mark_job_deleting(job_id)
        repo.mark_job_delete_failed(job_id, "Test error")
        
        job = repo.get_job_by_id(job_id)
        assert job.status == JobStatus.FAILED
        assert job.error_detail == "Test error"

    def test_claim_stale_deleting_skips_superseded_jobs(self):
        """Test that claim_stale_deleting_job skips jobs superseded by newer jobs."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        # Reset state for clean test
        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create an older job and mark as stale deleting
        old_job_id = self._create_test_job(repo, job_id="old-job-12345678901234567890")
        old_job = state.jobs[old_job_id]
        old_time = datetime.now(UTC) - timedelta(hours=1)
        stale_time = datetime.now(UTC) - timedelta(minutes=10)
        state.jobs[old_job_id] = replace(
            old_job,
            status=JobStatus.DELETING,
            submitted_at=old_time,
            started_at=stale_time,
            retry_count=1,
        )

        # Create a newer job for SAME target+owner (supersedes old job)
        new_job = Job(
            id="new-job-12345678901234567890",
            owner_user_id="user-1",
            owner_username="testuser",
            owner_user_code="TS0001",  # Same owner
            target="TS0001test",        # Same target
            staging_name="TS0001test_def123456789",
            dbhost="host1",
            status=JobStatus.COMPLETE,
            submitted_at=datetime.now(UTC),  # Newer
            started_at=None,
            completed_at=None,
            options_json=None,
            retry_count=0,
            error_detail=None,
            worker_id=None,
        )
        repo.enqueue_job(new_job)

        # Should NOT claim the old job (superseded by newer job)
        claimed = repo.claim_stale_deleting_job(
            worker_id="worker-1",
            stale_timeout_minutes=5,
        )
        
        assert claimed is None, "Should not claim superseded jobs"

    def test_claim_stale_deleting_claims_newest_for_target(self):
        """Test that claim_stale_deleting_job DOES claim if it's the newest for target."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        # Reset state for clean test
        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create a job and mark as stale deleting
        job_id = self._create_test_job(repo)
        job = state.jobs[job_id]
        stale_time = datetime.now(UTC) - timedelta(minutes=10)
        state.jobs[job_id] = replace(
            job,
            status=JobStatus.DELETING,
            started_at=stale_time,
            retry_count=1,
        )

        # Create another job for DIFFERENT target (doesn't supersede)
        other_job = Job(
            id="other-job-1234567890123456789",
            owner_user_id="user-1",
            owner_username="testuser",
            owner_user_code="TS0001",
            target="TS0001other",  # Different target!
            staging_name="TS0001other_xyz123456789",
            dbhost="host1",
            status=JobStatus.COMPLETE,
            submitted_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
            options_json=None,
            retry_count=0,
            error_detail=None,
            worker_id=None,
        )
        repo.enqueue_job(other_job)

        # SHOULD claim - it's still the newest for its target
        claimed = repo.claim_stale_deleting_job(
            worker_id="worker-1",
            stale_timeout_minutes=5,
        )
        
        assert claimed is not None, "Should claim job that's newest for its target"
        assert claimed.id == job_id
