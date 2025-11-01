"""Tests for worker polling loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pulldb.domain.models import Job, JobStatus
from pulldb.worker.loop import (
    MIN_POLL_INTERVAL_SECONDS,
    run_poll_loop,
)


@pytest.fixture
def mock_job_repo() -> MagicMock:
    """Create mock JobRepository for testing."""
    return MagicMock()


@pytest.fixture
def sample_job() -> Job:
    """Create sample job for testing."""
    from datetime import datetime

    return Job(
        id="abc123",
        owner_user_id="user-uuid",
        owner_username="testuser",
        owner_user_code="testus",
        target="testuscustomer",
        staging_name="testuscustomer_abc123456789",
        dbhost="db-mysql-db4-dev",
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(),
    )


def test_poll_loop_processes_job(mock_job_repo: MagicMock, sample_job: Job) -> None:
    """Poll loop fetches job and transitions to running."""
    mock_job_repo.get_next_queued_job.side_effect = [sample_job, None]

    # Run one iteration
    run_poll_loop(mock_job_repo, max_iterations=1)

    # Verify job was fetched
    assert mock_job_repo.get_next_queued_job.call_count == 1

    # Verify job was transitioned to running
    mock_job_repo.mark_job_running.assert_called_once_with(sample_job.id)

    # Verify running event was emitted
    mock_job_repo.append_event.assert_called_once()
    call_args = mock_job_repo.append_event.call_args
    assert call_args[1]["job_id"] == sample_job.id
    assert call_args[1]["event_type"] == "running"


def test_poll_loop_empty_queue_backs_off(mock_job_repo: MagicMock) -> None:
    """Poll loop applies exponential backoff when queue is empty."""
    # Always return None (empty queue)
    mock_job_repo.get_next_queued_job.return_value = None

    # Run multiple iterations to trigger backoff
    run_poll_loop(mock_job_repo, max_iterations=3)

    # Should have polled 3 times
    assert mock_job_repo.get_next_queued_job.call_count == 3

    # Should not have called mark_running (no jobs)
    mock_job_repo.mark_job_running.assert_not_called()


def test_poll_loop_respects_max_iterations(mock_job_repo: MagicMock) -> None:
    """Poll loop stops after max_iterations reached."""
    mock_job_repo.get_next_queued_job.return_value = None

    run_poll_loop(mock_job_repo, max_iterations=5)

    assert mock_job_repo.get_next_queued_job.call_count == 5


def test_poll_loop_handles_transition_error(
    mock_job_repo: MagicMock, sample_job: Job
) -> None:
    """Poll loop logs and continues after job transition failure."""
    mock_job_repo.get_next_queued_job.side_effect = [sample_job, None]
    mock_job_repo.mark_job_running.side_effect = Exception("Database error")

    # Should not raise - loop catches and logs error, then continues
    run_poll_loop(mock_job_repo, max_iterations=2)

    # Should have attempted transition
    mock_job_repo.mark_job_running.assert_called_once_with(sample_job.id)

    # Should have polled twice (once with error, once empty)
    assert mock_job_repo.get_next_queued_job.call_count == 2


def test_poll_loop_continues_after_poll_error(mock_job_repo: MagicMock) -> None:
    """Poll loop continues after unexpected error during poll."""
    # First call raises error, second succeeds
    mock_job_repo.get_next_queued_job.side_effect = [
        Exception("Connection lost"),
        None,
    ]

    # Should not raise - loop catches and continues
    run_poll_loop(mock_job_repo, max_iterations=2)

    # Should have attempted poll twice
    assert mock_job_repo.get_next_queued_job.call_count == 2


def test_poll_loop_resets_backoff_after_job(
    mock_job_repo: MagicMock, sample_job: Job
) -> None:
    """Poll loop resets backoff interval after finding a job."""
    # Empty queue, then job, then empty again
    mock_job_repo.get_next_queued_job.side_effect = [None, sample_job, None]

    run_poll_loop(
        mock_job_repo,
        max_iterations=3,
        poll_interval=MIN_POLL_INTERVAL_SECONDS,
    )

    # Job should have been transitioned
    mock_job_repo.mark_job_running.assert_called_once_with(sample_job.id)


def test_poll_loop_emits_correct_event_detail(
    mock_job_repo: MagicMock, sample_job: Job
) -> None:
    """Poll loop emits event with correct job details."""
    mock_job_repo.get_next_queued_job.return_value = sample_job

    run_poll_loop(mock_job_repo, max_iterations=1)

    # Check event detail includes target
    call_args = mock_job_repo.append_event.call_args
    detail = call_args[1]["detail"]
    assert sample_job.target in detail
    assert "Job started by worker" in detail


def test_poll_loop_multiple_jobs(mock_job_repo: MagicMock, sample_job: Job) -> None:
    """Poll loop processes multiple jobs in sequence."""
    job2 = Job(
        id="def456",
        owner_user_id="user-uuid",
        owner_username="testuser",
        owner_user_code="testus",
        target="testuscustomer2",
        staging_name="testuscustomer2_def456789012",
        dbhost="db-mysql-db4-dev",
        status=JobStatus.QUEUED,
        submitted_at=sample_job.submitted_at,
    )

    # Return two jobs, then None
    mock_job_repo.get_next_queued_job.side_effect = [sample_job, job2, None]

    run_poll_loop(mock_job_repo, max_iterations=3)

    # Both jobs should be transitioned
    assert mock_job_repo.mark_job_running.call_count == 2
    mock_job_repo.mark_job_running.assert_any_call(sample_job.id)
    mock_job_repo.mark_job_running.assert_any_call(job2.id)

    # Two events should be emitted
    assert mock_job_repo.append_event.call_count == 2
