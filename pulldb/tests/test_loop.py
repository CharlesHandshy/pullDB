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
def mock_job_executor() -> MagicMock:
    """Provide a mock job executor callable."""
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
        dbhost="dev-db-01",
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(),
    )


def _make_running_job(job: Job) -> Job:
    """Create copy of job with RUNNING status (as returned by claim_next_job)."""
    return Job(
        id=job.id,
        owner_user_id=job.owner_user_id,
        owner_username=job.owner_username,
        owner_user_code=job.owner_user_code,
        target=job.target,
        staging_name=job.staging_name,
        dbhost=job.dbhost,
        status=JobStatus.RUNNING,
        submitted_at=job.submitted_at,
    )


def test_poll_loop_processes_job(
    mock_job_repo: MagicMock,
    mock_job_executor: MagicMock,
    sample_job: Job,
) -> None:
    """Poll loop claims job and executes it."""
    # claim_next_job returns job with RUNNING status (already transitioned)
    running_job = _make_running_job(sample_job)
    mock_job_repo.claim_next_job.side_effect = [running_job, None]

    # Run one iteration
    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=1)

    # Verify job was claimed
    assert mock_job_repo.claim_next_job.call_count == 1

    # Verify running event was emitted
    mock_job_repo.append_event.assert_called_once()
    call_args = mock_job_repo.append_event.call_args
    assert call_args[1]["job_id"] == sample_job.id
    assert call_args[1]["event_type"] == "running"
    mock_job_executor.assert_called_once_with(running_job)


def test_poll_loop_empty_queue_backs_off(
    mock_job_repo: MagicMock, mock_job_executor: MagicMock
) -> None:
    """Poll loop applies exponential backoff when queue is empty."""
    # Always return None (empty queue)
    mock_job_repo.claim_next_job.return_value = None

    # Run multiple iterations to trigger backoff
    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=3)

    # Should have polled 3 times
    assert mock_job_repo.claim_next_job.call_count == 3

    # Should not have executed any jobs
    mock_job_executor.assert_not_called()


@pytest.mark.timeout(60)  # Takes ~32s due to backoff sleeps across 5 iterations
def test_poll_loop_respects_max_iterations(
    mock_job_repo: MagicMock, mock_job_executor: MagicMock
) -> None:
    """Poll loop stops after max_iterations reached."""
    mock_job_repo.claim_next_job.return_value = None

    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=5)

    assert mock_job_repo.claim_next_job.call_count == 5


def test_poll_loop_handles_transition_error(
    mock_job_repo: MagicMock,
    mock_job_executor: MagicMock,
    sample_job: Job,
) -> None:
    """Poll loop logs and continues after job claim failure."""
    # First claim raises error, second returns None
    mock_job_repo.claim_next_job.side_effect = [Exception("Database error"), None]

    # Should not raise - loop catches and logs error, then continues
    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=2)

    # Should have polled twice (once with error, once empty)
    assert mock_job_repo.claim_next_job.call_count == 2


def test_poll_loop_continues_after_poll_error(
    mock_job_repo: MagicMock, mock_job_executor: MagicMock
) -> None:
    """Poll loop continues after unexpected error during poll."""
    # First call raises error, second succeeds
    mock_job_repo.claim_next_job.side_effect = [
        Exception("Connection lost"),
        None,
    ]

    # Should not raise - loop catches and continues
    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=2)

    # Should have attempted poll twice
    assert mock_job_repo.claim_next_job.call_count == 2


def test_poll_loop_resets_backoff_after_job(
    mock_job_repo: MagicMock,
    mock_job_executor: MagicMock,
    sample_job: Job,
) -> None:
    """Poll loop resets backoff interval after finding a job."""
    running_job = _make_running_job(sample_job)
    # Empty queue, then job, then empty again
    mock_job_repo.claim_next_job.side_effect = [None, running_job, None]

    run_poll_loop(
        mock_job_repo,
        mock_job_executor,
        max_iterations=3,
        poll_interval=MIN_POLL_INTERVAL_SECONDS,
    )

    # Job should have been executed (already running from claim)
    mock_job_executor.assert_called_once_with(running_job)


def test_poll_loop_emits_correct_event_detail(
    mock_job_repo: MagicMock,
    mock_job_executor: MagicMock,
    sample_job: Job,
) -> None:
    """Poll loop emits event with correct job details."""
    running_job = _make_running_job(sample_job)
    mock_job_repo.claim_next_job.return_value = running_job

    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=1)

    # Check event detail includes target
    call_args = mock_job_repo.append_event.call_args
    detail = call_args[1]["detail"]
    assert sample_job.target in detail
    assert "Job started by worker" in detail


def test_poll_loop_multiple_jobs(
    mock_job_repo: MagicMock,
    mock_job_executor: MagicMock,
    sample_job: Job,
) -> None:
    """Poll loop processes multiple jobs in sequence."""
    job2 = Job(
        id="def456",
        owner_user_id="user-uuid",
        owner_username="testuser",
        owner_user_code="testus",
        target="testuscustomer2",
        staging_name="testuscustomer2_def456789012",
        dbhost="dev-db-01",
        status=JobStatus.QUEUED,
        submitted_at=sample_job.submitted_at,
    )

    running_job1 = _make_running_job(sample_job)
    running_job2 = _make_running_job(job2)

    # Return two jobs (as running), then None
    mock_job_repo.claim_next_job.side_effect = [running_job1, running_job2, None]

    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=3)

    # Two events should be emitted and executor invoked twice
    assert mock_job_repo.append_event.call_count == 2
    assert mock_job_executor.call_count == 2


def test_poll_loop_handles_job_executor_failure(
    mock_job_repo: MagicMock,
    mock_job_executor: MagicMock,
    sample_job: Job,
) -> None:
    """Poll loop logs executor failures and continues looping."""
    running_job = _make_running_job(sample_job)
    mock_job_repo.claim_next_job.side_effect = [running_job, None]
    mock_job_executor.side_effect = RuntimeError("boom")

    run_poll_loop(mock_job_repo, mock_job_executor, max_iterations=2)

    mock_job_executor.assert_called_once_with(running_job)
