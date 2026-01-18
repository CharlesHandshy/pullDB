"""Unit tests for heartbeat module."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.heartbeat import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    HeartbeatContext,
    HeartbeatThread,
)


class TestHeartbeatThread:
    """Tests for HeartbeatThread class."""

    def test_init_defaults(self) -> None:
        """HeartbeatThread initializes with correct defaults."""
        mock_fn = MagicMock()
        thread = HeartbeatThread(mock_fn)

        assert thread.heartbeat_fn == mock_fn
        assert thread.interval == DEFAULT_HEARTBEAT_INTERVAL_SECONDS
        assert thread.daemon is True
        assert thread.heartbeat_count == 0
        assert not thread.is_running

    def test_init_custom_interval(self) -> None:
        """HeartbeatThread accepts custom interval."""
        mock_fn = MagicMock()
        thread = HeartbeatThread(mock_fn, interval_seconds=30.0)

        assert thread.interval == 30.0

    def test_emits_heartbeats(self) -> None:
        """HeartbeatThread emits heartbeats at specified interval."""
        mock_fn = MagicMock()
        thread = HeartbeatThread(mock_fn, interval_seconds=0.1)

        thread.start()
        time.sleep(0.35)  # Allow for ~3 heartbeats
        thread.stop()
        thread.join(timeout=1)

        # Should have emitted 2-3 heartbeats (timing can vary)
        assert mock_fn.call_count >= 2
        assert thread.heartbeat_count >= 2

    def test_stop_stops_thread(self) -> None:
        """HeartbeatThread stops when stop() is called."""
        mock_fn = MagicMock()
        thread = HeartbeatThread(mock_fn, interval_seconds=0.1)

        thread.start()
        assert thread.is_running
        time.sleep(0.15)

        thread.stop()
        thread.join(timeout=1)

        assert not thread.is_alive()
        assert not thread.is_running

    def test_handles_exception_in_heartbeat_fn(self) -> None:
        """HeartbeatThread continues after exception in heartbeat function."""
        call_count = 0

        def failing_fn() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Test error")

        thread = HeartbeatThread(failing_fn, interval_seconds=0.1)

        thread.start()
        time.sleep(0.35)  # Allow for multiple attempts
        thread.stop()
        thread.join(timeout=1)

        # Should have attempted multiple heartbeats despite first failure
        assert call_count >= 2

    def test_is_daemon_thread(self) -> None:
        """HeartbeatThread is a daemon thread (won't block process exit)."""
        mock_fn = MagicMock()
        thread = HeartbeatThread(mock_fn)

        assert thread.daemon is True


class TestHeartbeatContext:
    """Tests for HeartbeatContext manager."""

    def test_starts_and_stops_thread(self) -> None:
        """HeartbeatContext starts thread on enter and stops on exit."""
        mock_fn = MagicMock()

        with HeartbeatContext(mock_fn, interval_seconds=0.1) as ctx:
            time.sleep(0.15)  # Allow one heartbeat
            assert ctx._thread is not None
            assert ctx._thread.is_alive()

        # After exit, thread should be stopped
        assert not ctx._thread.is_alive()

    def test_emits_heartbeats_during_context(self) -> None:
        """HeartbeatContext emits heartbeats while context is active."""
        mock_fn = MagicMock()

        with HeartbeatContext(mock_fn, interval_seconds=0.1):
            time.sleep(0.25)

        assert mock_fn.call_count >= 2

    def test_stops_on_exception(self) -> None:
        """HeartbeatContext stops thread even if exception raised."""
        mock_fn = MagicMock()

        with pytest.raises(ValueError):
            with HeartbeatContext(mock_fn, interval_seconds=0.1) as ctx:
                time.sleep(0.05)
                raise ValueError("Test error")

        # Thread should still be stopped
        assert not ctx._thread.is_alive()

    def test_heartbeat_count_accessible(self) -> None:
        """HeartbeatContext exposes heartbeat count."""
        mock_fn = MagicMock()

        with HeartbeatContext(mock_fn, interval_seconds=0.1) as ctx:
            time.sleep(0.25)

        assert ctx.heartbeat_count >= 2

    def test_heartbeat_count_zero_before_start(self) -> None:
        """HeartbeatContext returns 0 count before thread starts."""
        mock_fn = MagicMock()
        ctx = HeartbeatContext(mock_fn)

        assert ctx.heartbeat_count == 0


class TestIntegration:
    """Integration tests simulating real usage."""

    def test_heartbeat_keeps_job_alive_pattern(self) -> None:
        """Simulate the pattern used in WorkerJobExecutor."""
        events: list[str] = []

        def emit_heartbeat() -> None:
            events.append("heartbeat")

        def do_work() -> None:
            # Simulate work that takes time
            for i in range(3):
                events.append(f"work_{i}")
                time.sleep(0.1)

        with HeartbeatContext(emit_heartbeat, interval_seconds=0.15):
            do_work()

        # Should have work events and at least one heartbeat
        assert "work_0" in events
        assert "work_1" in events
        assert "work_2" in events
        assert "heartbeat" in events

    def test_concurrent_heartbeat_does_not_interfere(self) -> None:
        """Heartbeat emissions don't interfere with main thread work."""
        results: list[int] = []
        lock = threading.Lock()

        def emit_heartbeat() -> None:
            with lock:
                results.append(-1)  # Marker for heartbeat

        def compute() -> int:
            total = 0
            for i in range(100):
                total += i
                with lock:
                    results.append(i)
                time.sleep(0.001)
            return total

        with HeartbeatContext(emit_heartbeat, interval_seconds=0.05):
            value = compute()

        # Computation should complete correctly
        assert value == sum(range(100))

        # Results should include both work and heartbeats, interleaved
        work_results = [r for r in results if r >= 0]
        heartbeats = [r for r in results if r == -1]

        assert len(work_results) == 100
        assert len(heartbeats) >= 1  # At least one heartbeat during 0.1s work
