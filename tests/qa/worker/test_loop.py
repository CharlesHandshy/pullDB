"""Tests for pulldb.worker.loop module.

Tests polling loop operations:
- Worker ID generation
- Job claiming and execution
- Backoff behavior
- Graceful shutdown
"""

from __future__ import annotations

import socket
import time
from unittest.mock import MagicMock, call, patch

import pytest

from pulldb.domain.models import Job, JobStatus
from pulldb.worker.loop import (
    BACKOFF_MULTIPLIER,
    MAX_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS,
    get_worker_id,
    run_poll_loop,
)


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"


# ---------------------------------------------------------------------------
# get_worker_id Tests
# ---------------------------------------------------------------------------


class TestGetWorkerId:
    """Tests for get_worker_id function."""

    def test_returns_hostname_pid_format(self) -> None:
        """Worker ID uses hostname:pid format."""
        worker_id = get_worker_id()
        assert ":" in worker_id
        parts = worker_id.split(":")
        assert len(parts) == 2
        # Second part should be numeric (PID)
        assert parts[1].isdigit()

    def test_uses_actual_hostname(self) -> None:
        """Uses actual hostname from socket."""
        worker_id = get_worker_id()
        hostname = socket.gethostname()
        assert worker_id.startswith(hostname + ":")

    def test_uses_current_pid(self) -> None:
        """Uses current process PID."""
        import os

        worker_id = get_worker_id()
        pid = str(os.getpid())
        assert worker_id.endswith(":" + pid)


# ---------------------------------------------------------------------------
# run_poll_loop Tests
# ---------------------------------------------------------------------------


class TestRunPollLoop:
    """Tests for run_poll_loop function."""

    @pytest.fixture
    def mock_job_repo(self) -> MagicMock:
        """Create mock job repository."""
        mock = MagicMock()
        mock.claim_next_job.return_value = None
        mock.add_job_event.return_value = None
        return mock

    @pytest.fixture
    def mock_executor(self) -> MagicMock:
        """Create mock job executor."""
        return MagicMock()

    def test_respects_max_iterations(
        self, mock_job_repo: MagicMock, mock_executor: MagicMock
    ) -> None:
        """Loop stops after max_iterations."""
        run_poll_loop(
            mock_job_repo,
            mock_executor,
            max_iterations=5,
            poll_interval=0.001,
        )

        # claim_next_job should be called 5 times
        assert mock_job_repo.claim_next_job.call_count == 5

    def test_respects_should_stop_callback(
        self, mock_job_repo: MagicMock, mock_executor: MagicMock
    ) -> None:
        """Loop stops when should_stop returns True."""
        call_count = [0]

        def should_stop() -> bool:
            call_count[0] += 1
            return call_count[0] >= 3

        run_poll_loop(
            mock_job_repo,
            mock_executor,
            should_stop=should_stop,
            poll_interval=0.001,
        )

        # Should have stopped after ~3 iterations
        assert mock_job_repo.claim_next_job.call_count <= 3

    def test_executes_claimed_job(
        self, mock_job_repo: MagicMock, mock_executor: MagicMock
    ) -> None:
        """Executor is called for claimed jobs."""
        from datetime import UTC, datetime

        mock_job = MagicMock(spec=Job)
        mock_job.id = SAMPLE_JOB_ID
        mock_job.target = "testdb"
        mock_job.owner_username = "testuser"
        mock_job.status = JobStatus.RUNNING

        # Return job on first call, None on second
        mock_job_repo.claim_next_job.side_effect = [mock_job, None]

        run_poll_loop(
            mock_job_repo,
            mock_executor,
            max_iterations=2,
            poll_interval=0.001,
        )

        mock_executor.assert_called_once_with(mock_job)

    def test_uses_provided_worker_id(
        self, mock_job_repo: MagicMock, mock_executor: MagicMock
    ) -> None:
        """Uses custom worker_id when provided."""
        run_poll_loop(
            mock_job_repo,
            mock_executor,
            max_iterations=1,
            worker_id="custom-worker-1",
            poll_interval=0.001,
        )

        mock_job_repo.claim_next_job.assert_called_with(worker_id="custom-worker-1")

    def test_generates_worker_id_when_not_provided(
        self, mock_job_repo: MagicMock, mock_executor: MagicMock
    ) -> None:
        """Generates worker_id when not provided."""
        run_poll_loop(
            mock_job_repo,
            mock_executor,
            max_iterations=1,
            poll_interval=0.001,
        )

        call_args = mock_job_repo.claim_next_job.call_args
        worker_id = call_args.kwargs["worker_id"]
        assert ":" in worker_id  # hostname:pid format

    def test_continues_on_executor_exception(
        self, mock_job_repo: MagicMock
    ) -> None:
        """Loop continues when executor raises exception."""
        from datetime import UTC, datetime

        mock_job = MagicMock(spec=Job)
        mock_job.id = SAMPLE_JOB_ID
        mock_job.target = "testdb"
        mock_job.owner_username = "testuser"

        # Return job twice
        mock_job_repo.claim_next_job.side_effect = [mock_job, mock_job, None]

        failing_executor = MagicMock(side_effect=Exception("Test error"))

        run_poll_loop(
            mock_job_repo,
            failing_executor,
            max_iterations=3,
            poll_interval=0.001,
        )

        # Should have attempted execution twice despite errors
        assert failing_executor.call_count == 2


# ---------------------------------------------------------------------------
# Backoff Behavior Tests
# ---------------------------------------------------------------------------


class TestBackoffBehavior:
    """Tests for exponential backoff when queue is empty."""

    @pytest.fixture
    def mock_job_repo(self) -> MagicMock:
        """Create mock job repository returning no jobs."""
        mock = MagicMock()
        mock.claim_next_job.return_value = None
        return mock

    def test_initial_poll_interval(self, mock_job_repo: MagicMock) -> None:
        """Uses specified poll_interval initially."""
        mock_executor = MagicMock()

        # We can't easily measure actual sleep time, but we can verify
        # the loop runs with the expected parameters
        run_poll_loop(
            mock_job_repo,
            mock_executor,
            max_iterations=1,
            poll_interval=MIN_POLL_INTERVAL_SECONDS,
        )

        assert mock_job_repo.claim_next_job.call_count == 1

    def test_backoff_constants_defined(self) -> None:
        """Backoff constants have expected values."""
        assert MIN_POLL_INTERVAL_SECONDS == 1.0
        assert MAX_POLL_INTERVAL_SECONDS == 30.0
        assert BACKOFF_MULTIPLIER == 2.0


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for poll loop."""

    def test_empty_poll_loop(self) -> None:
        """Poll loop with zero iterations does nothing."""
        mock_repo = MagicMock()
        mock_executor = MagicMock()

        run_poll_loop(
            mock_repo,
            mock_executor,
            max_iterations=0,
        )

        mock_repo.claim_next_job.assert_not_called()
        mock_executor.assert_not_called()

    def test_should_stop_checked_before_first_iteration(self) -> None:
        """should_stop is checked before first poll."""
        mock_repo = MagicMock()
        mock_executor = MagicMock()

        run_poll_loop(
            mock_repo,
            mock_executor,
            should_stop=lambda: True,
        )

        mock_repo.claim_next_job.assert_not_called()
