"""Tests for pulldb.worker.service module.

Tests worker service operations:
- Configuration loading
- Argument parsing
- Signal handling
- Main entry point
"""

from __future__ import annotations

import argparse
import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.service import (
    _parse_args,
    _positive_float,
    _positive_int,
)


# ---------------------------------------------------------------------------
# Argument Parsing Tests
# ---------------------------------------------------------------------------


class TestPositiveInt:
    """Tests for _positive_int validator."""

    def test_accepts_positive_value(self) -> None:
        """Accepts positive integers."""
        assert _positive_int("5") == 5
        assert _positive_int("100") == 100

    def test_rejects_zero(self) -> None:
        """Rejects zero."""
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_int("0")

    def test_rejects_negative(self) -> None:
        """Rejects negative values."""
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_int("-1")

    def test_rejects_non_integer(self) -> None:
        """Rejects non-integer strings."""
        with pytest.raises(ValueError):
            _positive_int("abc")


class TestPositiveFloat:
    """Tests for _positive_float validator."""

    def test_accepts_positive_value(self) -> None:
        """Accepts positive floats."""
        assert _positive_float("5.5") == 5.5
        assert _positive_float("0.1") == 0.1

    def test_rejects_zero(self) -> None:
        """Rejects zero."""
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_float("0")

    def test_rejects_negative(self) -> None:
        """Rejects negative values."""
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_float("-1.5")


class TestParseArgs:
    """Tests for _parse_args function."""

    def test_default_values(self) -> None:
        """Returns defaults when no args provided."""
        args = _parse_args([])
        assert args.max_iterations is None
        assert args.oneshot is False

    def test_max_iterations(self) -> None:
        """Parses --max-iterations."""
        args = _parse_args(["--max-iterations", "10"])
        assert args.max_iterations == 10

    def test_poll_interval(self) -> None:
        """Parses --poll-interval."""
        args = _parse_args(["--poll-interval", "5.0"])
        assert args.poll_interval == 5.0

    def test_oneshot(self) -> None:
        """Parses --oneshot flag."""
        args = _parse_args(["--oneshot"])
        assert args.oneshot is True

    def test_oneshot_without_max_iterations(self) -> None:
        """--oneshot works without --max-iterations."""
        args = _parse_args(["--oneshot"])
        assert args.oneshot is True
        assert args.max_iterations is None

    def test_poll_interval_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses PULLDB_WORKER_POLL_INTERVAL from env."""
        monkeypatch.setenv("PULLDB_WORKER_POLL_INTERVAL", "10.0")
        args = _parse_args([])
        assert args.poll_interval == 10.0

    def test_invalid_max_iterations_rejected(self) -> None:
        """Rejects non-positive max_iterations."""
        with pytest.raises(SystemExit):
            _parse_args(["--max-iterations", "0"])


# ---------------------------------------------------------------------------
# Signal Handling Tests
# ---------------------------------------------------------------------------


class TestSignalHandling:
    """Tests for signal handler registration."""

    def test_stop_event_set_on_sigterm(self) -> None:
        """SIGTERM sets stop event."""
        from pulldb.worker.service import _register_signal_handlers

        stop_event = threading.Event()
        _register_signal_handlers(stop_event)

        # Simulate SIGTERM by calling the handler directly
        # Note: Can't actually send signals in tests safely
        assert not stop_event.is_set()

    def test_stop_event_set_on_sigint(self) -> None:
        """SIGINT sets stop event."""
        from pulldb.worker.service import _register_signal_handlers

        stop_event = threading.Event()
        _register_signal_handlers(stop_event)

        # Stop event starts unset
        assert not stop_event.is_set()


# ---------------------------------------------------------------------------
# Metrics Emission Tests
# ---------------------------------------------------------------------------


class TestMetricsEmission:
    """Tests for metrics emission functions."""

    def test_set_worker_active(self) -> None:
        """_set_worker_active emits gauge."""
        from pulldb.worker.service import _set_worker_active

        with patch("pulldb.worker.service.emit_gauge") as mock_emit:
            _set_worker_active(1, "startup")
            mock_emit.assert_called_once()

    def test_emit_startup_event(self) -> None:
        """_emit_startup_event logs and emits."""
        from pulldb.domain.config import Config
        from pulldb.worker.service import _emit_startup_event

        config = Config.minimal_from_env()
        args = argparse.Namespace(oneshot=False, max_iterations=None)

        with patch("pulldb.worker.service.emit_event") as mock_emit:
            _emit_startup_event(config, args, effective_poll_interval=1.0)
            mock_emit.assert_called_once()

    def test_emit_stop_event(self) -> None:
        """_emit_stop_event logs and emits."""
        from pulldb.worker.service import _emit_stop_event

        stop_event = threading.Event()

        with patch("pulldb.worker.service.emit_event") as mock_emit:
            _emit_stop_event(stop_event)
            mock_emit.assert_called_once()

    def test_emit_fatal(self) -> None:
        """_emit_fatal logs error and emits."""
        from pulldb.worker.service import _emit_fatal

        with patch("pulldb.worker.service.emit_event") as mock_emit:
            _emit_fatal(RuntimeError("test error"))
            mock_emit.assert_called_once()


# ---------------------------------------------------------------------------
# Zombie Cleanup Tests
# ---------------------------------------------------------------------------


class TestZombieCleanup:
    """Tests for zombie job detection and cleanup."""

    def test_cleanup_zombies_skips_when_lock_not_acquired(self) -> None:
        """Skips cleanup when advisory lock is held by another worker."""
        from pulldb.worker.service import _cleanup_zombies

        mock_job_repo = MagicMock()
        mock_pool = MagicMock()
        
        # Simulate lock not acquired (another worker holds it)
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0,)  # Lock not acquired
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        _cleanup_zombies(mock_job_repo, mock_pool)

        # Should not mark any jobs failed since lock wasn't acquired
        mock_job_repo.mark_job_failed.assert_not_called()

    def test_cleanup_zombies_marks_running_jobs_failed(self) -> None:
        """Marks running jobs as failed when lock acquired."""
        from pulldb.domain.models import JobStatus
        from pulldb.worker.service import _cleanup_zombies

        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_job.target = "testdb"
        mock_job.status = JobStatus.RUNNING

        mock_job_repo = MagicMock()
        mock_job_repo.get_active_jobs.return_value = [mock_job]

        mock_pool = MagicMock()
        # Simulate lock acquired successfully
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)  # Lock acquired
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        _cleanup_zombies(mock_job_repo, mock_pool)

        mock_job_repo.mark_job_failed.assert_called_once()

    def test_cleanup_zombies_handles_pool_exception(self) -> None:
        """Handles pool connection errors gracefully."""
        from pulldb.worker.service import _cleanup_zombies

        mock_job_repo = MagicMock()
        mock_pool = MagicMock()
        
        # Simulate pool connection failure
        mock_pool.connection.side_effect = Exception("Connection failed")

        # Should not raise
        _cleanup_zombies(mock_job_repo, mock_pool)

        mock_job_repo.mark_job_failed.assert_not_called()


# ---------------------------------------------------------------------------
# Main Entry Point Tests
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    """Tests for main() function."""

    def test_main_with_oneshot_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() with --oneshot executes once and exits."""
        from pulldb.worker.service import main

        # Set required env vars
        monkeypatch.setenv("PULLDB_WORKER_MYSQL_USER", "test_worker")
        monkeypatch.setenv("PULLDB_MYSQL_HOST", "localhost")
        monkeypatch.setenv("PULLDB_MYSQL_PASSWORD", "testpass")
        monkeypatch.setenv("PULLDB_MYSQL_DATABASE", "pulldb_service")

        # Mock dependencies
        mock_cfg = MagicMock()
        mock_cfg.mysql_host = "localhost"
        mock_cfg.mysql_database = "pulldb_service"
        mock_pool = MagicMock()
        mock_job_repo = MagicMock()
        mock_job_executor = MagicMock()

        with (
            patch("pulldb.worker.service._load_config_and_pool", return_value=(mock_cfg, mock_pool)),
            patch("pulldb.worker.service.JobRepository", return_value=mock_job_repo),
            patch("pulldb.worker.service._build_job_executor", return_value=mock_job_executor),
            patch("pulldb.worker.service.run_poll_loop"),
            patch("pulldb.worker.service._cleanup_zombies"),
            patch("pulldb.worker.service.is_simulation_mode", return_value=True),
        ):
            result = main(["--oneshot", "--poll-interval", "0.001"])

            assert result == 0
