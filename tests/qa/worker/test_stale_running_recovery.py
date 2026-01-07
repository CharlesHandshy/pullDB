"""Tests for stale running job recovery feature.

Tests the functionality for recovering jobs stuck in 'running' status
when the worker dies mid-restore:
- get_candidate_stale_running_job() for finding stale candidates
- is_staging_db_active() for process list verification
- mark_stale_running_failed() for marking stale jobs as failed
- execute_stale_running_cleanup() for the full cleanup workflow
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

from pulldb.domain.models import Job, JobStatus
from pulldb.worker.cleanup import (
    StaleRunningCleanupResult,
    execute_stale_running_cleanup,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_job_repo():
    """Create a mock job repository with stale running constants."""
    repo = MagicMock()
    repo.STALE_RUNNING_TIMEOUT_MINUTES = 15
    repo.STALE_RUNNING_PROCESS_CHECK_COUNT = 3
    repo.STALE_RUNNING_PROCESS_CHECK_DELAY_SECONDS = 2.0
    repo.mark_stale_running_failed = MagicMock(return_value=True)
    return repo


@pytest.fixture
def mock_host_repo():
    """Create a mock host repository."""
    repo = MagicMock()
    repo.is_staging_db_active = MagicMock(return_value=False)
    repo.get_host_credentials = MagicMock()
    return repo


@pytest.fixture
def sample_running_job():
    """Create a sample job in running status that appears stale."""
    return Job(
        id="test-job-123456789012",
        owner_user_id="user-123",
        owner_username="testuser",
        owner_user_code="TS0001",
        target="TS0001customer_db",
        staging_name="TS0001customer_db_abcdef123456",  # Valid hex pattern
        dbhost="mysql-host-1",
        status=JobStatus.RUNNING,
        submitted_at=datetime.now(UTC) - timedelta(hours=2),
        started_at=datetime.now(UTC) - timedelta(minutes=30),  # Started 30 min ago
        completed_at=None,
        options_json=None,
        retry_count=0,
        error_detail=None,
        worker_id="dead-worker-123",
    )


# =============================================================================
# StaleRunningCleanupResult Tests
# =============================================================================


class TestStaleRunningCleanupResult:
    """Tests for StaleRunningCleanupResult dataclass."""

    def test_default_values(self):
        """Test default field values."""
        result = StaleRunningCleanupResult(job_id="job-123", was_actually_stale=False)
        assert result.job_id == "job-123"
        assert result.was_actually_stale is False
        assert result.staging_dropped is False
        assert result.marked_failed is False
        assert result.error is None

    def test_all_fields(self):
        """Test all fields can be set."""
        result = StaleRunningCleanupResult(
            job_id="job-456",
            was_actually_stale=True,
            staging_dropped=True,
            marked_failed=True,
            error="some error",
        )
        assert result.was_actually_stale is True
        assert result.staging_dropped is True
        assert result.marked_failed is True
        assert result.error == "some error"


# =============================================================================
# execute_stale_running_cleanup Tests
# =============================================================================


class TestExecuteStaleRunningCleanup:
    """Tests for execute_stale_running_cleanup function."""

    def test_skips_job_with_active_processes(
        self, mock_job_repo, mock_host_repo, sample_running_job
    ):
        """Test that cleanup is skipped when process list shows activity."""
        # Job has active processes
        mock_host_repo.is_staging_db_active.return_value = True

        result = execute_stale_running_cleanup(
            sample_running_job, mock_job_repo, mock_host_repo, worker_id="worker-1"
        )

        assert result.was_actually_stale is False
        assert result.marked_failed is False
        mock_job_repo.mark_stale_running_failed.assert_not_called()

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup._drop_database")
    def test_cleans_up_when_no_active_processes(
        self,
        mock_drop_db,
        mock_db_exists,
        mock_job_repo,
        mock_host_repo,
        sample_running_job,
    ):
        """Test full cleanup when no active processes found."""
        # No active processes
        mock_host_repo.is_staging_db_active.return_value = False
        mock_db_exists.return_value = True
        mock_drop_db.return_value = True

        result = execute_stale_running_cleanup(
            sample_running_job, mock_job_repo, mock_host_repo, worker_id="worker-1"
        )

        assert result.was_actually_stale is True
        assert result.staging_dropped is True
        assert result.marked_failed is True
        mock_job_repo.mark_stale_running_failed.assert_called_once_with(
            job_id=sample_running_job.id,
            worker_id="worker-1",
            error_detail="Worker died during restore (stale job recovery)",
        )

    @patch("pulldb.worker.cleanup._database_exists")
    def test_handles_missing_staging_database(
        self,
        mock_db_exists,
        mock_job_repo,
        mock_host_repo,
        sample_running_job,
    ):
        """Test cleanup when staging database doesn't exist."""
        mock_host_repo.is_staging_db_active.return_value = False
        mock_db_exists.return_value = False  # Staging DB already gone

        result = execute_stale_running_cleanup(
            sample_running_job, mock_job_repo, mock_host_repo, worker_id="worker-1"
        )

        assert result.was_actually_stale is True
        assert result.staging_dropped is False  # Nothing to drop
        assert result.marked_failed is True
        mock_job_repo.mark_stale_running_failed.assert_called_once()

    def test_handles_process_check_failure(
        self, mock_job_repo, mock_host_repo, sample_running_job
    ):
        """Test handling when process list check fails."""
        mock_host_repo.is_staging_db_active.side_effect = Exception("Connection failed")

        result = execute_stale_running_cleanup(
            sample_running_job, mock_job_repo, mock_host_repo, worker_id="worker-1"
        )

        # Should NOT mark as failed - we couldn't verify
        assert result.was_actually_stale is False
        assert result.error is not None
        assert "Connection failed" in result.error
        mock_job_repo.mark_stale_running_failed.assert_not_called()

    @patch("pulldb.worker.cleanup._database_exists")
    @patch("pulldb.worker.cleanup._drop_database")
    def test_continues_if_staging_drop_fails(
        self,
        mock_drop_db,
        mock_db_exists,
        mock_job_repo,
        mock_host_repo,
        sample_running_job,
    ):
        """Test that job is still marked failed even if staging drop fails."""
        mock_host_repo.is_staging_db_active.return_value = False
        mock_db_exists.return_value = True
        mock_drop_db.return_value = False  # Drop failed

        result = execute_stale_running_cleanup(
            sample_running_job, mock_job_repo, mock_host_repo, worker_id="worker-1"
        )

        # Should still mark as failed
        assert result.was_actually_stale is True
        assert result.staging_dropped is False
        assert result.marked_failed is True
        mock_job_repo.mark_stale_running_failed.assert_called_once()

    @patch("pulldb.worker.cleanup._database_exists")
    def test_marks_failed_returns_false_if_already_transitioned(
        self,
        mock_db_exists,
        mock_job_repo,
        mock_host_repo,
        sample_running_job,
    ):
        """Test handling when job has already transitioned to another state."""
        mock_host_repo.is_staging_db_active.return_value = False
        mock_db_exists.return_value = False
        mock_job_repo.mark_stale_running_failed.return_value = False  # Already transitioned

        result = execute_stale_running_cleanup(
            sample_running_job, mock_job_repo, mock_host_repo, worker_id="worker-1"
        )

        assert result.was_actually_stale is True
        assert result.marked_failed is False


# =============================================================================
# Mock Repository Method Tests (using simulation adapter)
# =============================================================================


class TestMockJobRepositoryStaleRunningMethods:
    """Tests for mock repository stale running methods."""

    def _create_test_job(
        self, repo, job_id: str = "test-job-12345678901234567890"
    ) -> str:
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

    def test_get_candidate_stale_running_job_finds_stale_jobs(self):
        """Test that get_candidate_stale_running_job finds jobs older than timeout."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create and claim a job (marks it running)
        job_id = self._create_test_job(repo)
        repo.claim_next_job(worker_id="worker-1")

        # Manually backdate started_at to make it stale (20 minutes ago)
        job = state.jobs[job_id]
        stale_time = datetime.now(UTC) - timedelta(minutes=20)
        state.jobs[job_id] = replace(job, started_at=stale_time)

        # Should find the stale job
        candidate = repo.get_candidate_stale_running_job(stale_timeout_minutes=15)

        assert candidate is not None
        assert candidate.id == job_id
        assert candidate.status == JobStatus.RUNNING

    def test_get_candidate_stale_running_job_ignores_fresh_jobs(self):
        """Test that get_candidate_stale_running_job ignores jobs under timeout."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create and claim a job
        job_id = self._create_test_job(repo)
        repo.claim_next_job(worker_id="worker-1")

        # Job started 5 minutes ago (fresh, not stale)
        job = state.jobs[job_id]
        fresh_time = datetime.now(UTC) - timedelta(minutes=5)
        state.jobs[job_id] = replace(job, started_at=fresh_time)

        # Should NOT find the job (under timeout)
        candidate = repo.get_candidate_stale_running_job(stale_timeout_minutes=15)

        assert candidate is None

    def test_get_candidate_stale_running_job_skips_superseded(self):
        """Test that get_candidate_stale_running_job skips superseded jobs."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create old stale running job
        old_job_id = self._create_test_job(repo, job_id="old-job-12345678901234567890")
        old_job = state.jobs[old_job_id]
        old_submitted = datetime.now(UTC) - timedelta(hours=2)
        stale_time = datetime.now(UTC) - timedelta(minutes=30)
        state.jobs[old_job_id] = replace(
            old_job,
            status=JobStatus.RUNNING,
            submitted_at=old_submitted,
            started_at=stale_time,
            worker_id="dead-worker",
        )

        # Create newer job for SAME target+owner (supersedes old job)
        new_job = Job(
            id="new-job-12345678901234567890",
            owner_user_id="user-1",
            owner_username="testuser",
            owner_user_code="TS0001",  # Same owner
            target="TS0001test",  # Same target
            staging_name="TS0001test_def123456789",
            dbhost="host1",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),  # Newer
            started_at=None,
            completed_at=None,
            options_json=None,
            retry_count=0,
            error_detail=None,
            worker_id=None,
        )
        repo.enqueue_job(new_job)

        # Should NOT find the old job (superseded)
        candidate = repo.get_candidate_stale_running_job(stale_timeout_minutes=15)

        assert candidate is None, "Should not find superseded jobs"

    def test_get_candidate_stale_running_job_returns_none_when_empty(self):
        """Test that get_candidate_stale_running_job returns None when no candidates."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import reset_simulation

        reset_simulation()
        repo = SimulatedJobRepository()

        # No jobs at all
        candidate = repo.get_candidate_stale_running_job(stale_timeout_minutes=15)

        assert candidate is None

    def test_mark_stale_running_failed_sets_failed_status(self):
        """Test that mark_stale_running_failed sets status to failed."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create and claim a job
        job_id = self._create_test_job(repo)
        repo.claim_next_job(worker_id="worker-1")

        # Mark as stale failed
        result = repo.mark_stale_running_failed(
            job_id=job_id,
            worker_id="recovery-worker",
            error_detail="Test stale recovery",
        )

        assert result is True
        job = repo.get_job_by_id(job_id)
        assert job.status == JobStatus.FAILED
        assert job.error_detail == "Test stale recovery"

    def test_mark_stale_running_failed_returns_false_if_not_running(self):
        """Test that mark_stale_running_failed returns False if job not running."""
        from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository
        from pulldb.simulation.core.state import get_simulation_state, reset_simulation

        reset_simulation()
        state = get_simulation_state()
        repo = SimulatedJobRepository()

        # Create a job but don't claim it (stays queued)
        job_id = self._create_test_job(repo)

        # Try to mark as stale failed - should fail (not running)
        result = repo.mark_stale_running_failed(
            job_id=job_id,
            worker_id="recovery-worker",
        )

        assert result is False
        job = repo.get_job_by_id(job_id)
        assert job.status == JobStatus.QUEUED  # Unchanged


# =============================================================================
# is_staging_db_active Tests (with mocking)
# =============================================================================


class TestIsStagingDbActive:
    """Tests for HostRepository.is_staging_db_active method."""

    def test_returns_true_when_process_found(self):
        """Test returns True when a process is using the staging database."""
        from unittest.mock import MagicMock, patch

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"Id": 1, "User": "pulldb_worker", "db": "mydb_abc123456789", "Command": "Query"},
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            from pulldb.infra.mysql import HostRepository, MySQLPool
            from pulldb.infra.secrets import CredentialResolver

            mock_pool = MagicMock(spec=MySQLPool)
            mock_resolver = MagicMock(spec=CredentialResolver)
            mock_resolver.resolve.return_value = MagicMock(
                host="localhost", port=3306, username="user", password="pass"
            )

            # Mock get_host_by_hostname to return a valid host
            with patch.object(
                HostRepository,
                "get_host_by_hostname",
                return_value=MagicMock(enabled=True, credential_ref="test-ref"),
            ):
                repo = HostRepository(mock_pool, mock_resolver)
                result = repo.is_staging_db_active(
                    hostname="localhost",
                    staging_name="mydb_abc123456789",
                    check_count=1,
                    check_delay_seconds=0,
                )

        assert result is True

    def test_returns_false_after_all_checks_empty(self):
        """Test returns False after all checks show no processes."""
        from unittest.mock import MagicMock, patch

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"Id": 1, "User": "pulldb_worker", "db": "other_db", "Command": "Sleep"},
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            with patch("time.sleep"):  # Speed up test
                from pulldb.infra.mysql import HostRepository, MySQLPool
                from pulldb.infra.secrets import CredentialResolver

                mock_pool = MagicMock(spec=MySQLPool)
                mock_resolver = MagicMock(spec=CredentialResolver)
                mock_resolver.resolve.return_value = MagicMock(
                    host="localhost", port=3306, username="user", password="pass"
                )

                with patch.object(
                    HostRepository,
                    "get_host_by_hostname",
                    return_value=MagicMock(enabled=True, credential_ref="test-ref"),
                ):
                    repo = HostRepository(mock_pool, mock_resolver)
                    result = repo.is_staging_db_active(
                        hostname="localhost",
                        staging_name="mydb_abc123456789",
                        check_count=3,
                        check_delay_seconds=0.01,
                    )

        assert result is False

    def test_returns_true_on_second_check(self):
        """Test returns True if activity found on any check."""
        from unittest.mock import MagicMock, patch

        mock_cursor = MagicMock()
        # First check: no match, Second check: match found
        mock_cursor.fetchall.side_effect = [
            [{"Id": 1, "User": "user", "db": "other_db", "Command": "Sleep"}],
            [{"Id": 2, "User": "user", "db": "mydb_abc123456789", "Command": "Query"}],
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            with patch("time.sleep"):
                from pulldb.infra.mysql import HostRepository, MySQLPool
                from pulldb.infra.secrets import CredentialResolver

                mock_pool = MagicMock(spec=MySQLPool)
                mock_resolver = MagicMock(spec=CredentialResolver)
                mock_resolver.resolve.return_value = MagicMock(
                    host="localhost", port=3306, username="user", password="pass"
                )

                with patch.object(
                    HostRepository,
                    "get_host_by_hostname",
                    return_value=MagicMock(enabled=True, credential_ref="test-ref"),
                ):
                    repo = HostRepository(mock_pool, mock_resolver)
                    result = repo.is_staging_db_active(
                        hostname="localhost",
                        staging_name="mydb_abc123456789",
                        check_count=3,
                        check_delay_seconds=0.01,
                    )

        assert result is True
