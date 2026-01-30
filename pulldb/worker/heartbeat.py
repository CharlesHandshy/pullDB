"""Async heartbeat mechanism for long-running worker operations.

Prevents stale job detection from killing active workers during
long-running operations like metadata synthesis, myloader restore, etc.

The stale job detection query looks for jobs where MAX(job_events.logged_at)
is older than STALE_RUNNING_TIMEOUT_MINUTES (15 minutes). By emitting
heartbeat events every 60 seconds, we ensure the worker is never mistakenly
declared dead.

Example:
    >>> def emit_heartbeat():
    ...     job_repo.append_job_event(job_id, "heartbeat", "Worker alive")
    ...
    >>> with HeartbeatContext(emit_heartbeat, interval_seconds=60) as hb:
    ...     do_long_running_work()
    >>> # Heartbeat automatically stopped on exit

HCA Layer: features
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType

from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.worker.heartbeat")

# Default interval: 60 seconds gives 15x safety margin with 15-minute stale timeout
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0


class HeartbeatThread(threading.Thread):
    """Background thread that emits heartbeat events at regular intervals.

    The thread runs as a daemon, so it will be automatically terminated
    if the main process exits. Use stop() + join() for graceful shutdown.

    Supports optional suppression via should_emit_fn callback - when provided,
    heartbeat is skipped if the callback returns False. This allows suppressing
    redundant heartbeats when meaningful progress events are being emitted.

    Attributes:
        heartbeat_fn: Function called on each heartbeat interval.
        interval: Seconds between heartbeat emissions.
        should_emit_fn: Optional callback that returns False to suppress heartbeat.
    """

    def __init__(
        self,
        heartbeat_fn: Callable[[], None],
        interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        name: str = "heartbeat",
        should_emit_fn: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize heartbeat thread.

        Args:
            heartbeat_fn: Function to call on each heartbeat (e.g., emit event).
                Should be safe to call from a background thread.
            interval_seconds: Seconds between heartbeats (default 60).
            name: Thread name for debugging.
            should_emit_fn: Optional callback returning True if heartbeat should
                be emitted. When None or returns True, heartbeat is emitted.
                When returns False, heartbeat is skipped (suppressed).
        """
        super().__init__(name=name, daemon=True)
        self.heartbeat_fn = heartbeat_fn
        self.interval = interval_seconds
        self.should_emit_fn = should_emit_fn
        self._stop_event = threading.Event()
        self._is_active = False
        self._heartbeat_count = 0
        self._suppressed_count = 0

    def run(self) -> None:
        """Background loop that emits heartbeats until stopped.

        Catches and logs exceptions from heartbeat_fn to prevent
        thread crashes. Heartbeat emission is best-effort.

        If should_emit_fn is provided and returns False, the heartbeat
        is skipped for that interval (suppressed due to meaningful activity).
        """
        self._is_active = True
        logger.debug(
            "Heartbeat thread started",
            extra={"interval_seconds": self.interval},
        )

        while not self._stop_event.wait(self.interval):
            try:
                # Check if heartbeat should be suppressed
                if self.should_emit_fn is not None and not self.should_emit_fn():
                    self._suppressed_count += 1
                    logger.debug(
                        "Heartbeat suppressed (meaningful activity)",
                        extra={"suppressed_count": self._suppressed_count},
                    )
                    continue

                self.heartbeat_fn()
                self._heartbeat_count += 1
                logger.debug(
                    "Heartbeat emitted",
                    extra={"heartbeat_count": self._heartbeat_count},
                )
            except Exception as e:
                # Log but don't crash - heartbeat is best-effort
                logger.warning(
                    "Heartbeat emission failed",
                    extra={"error": str(e)},
                    exc_info=True,
                )

        logger.debug(
            "Heartbeat thread stopped",
            extra={
                "total_heartbeats": self._heartbeat_count,
                "suppressed": self._suppressed_count,
            },
        )

    def stop(self) -> None:
        """Signal the thread to stop.

        Call join() after stop() to wait for clean shutdown.
        """
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        """Check if heartbeat thread is actively running."""
        return self._is_active and not self._stop_event.is_set()

    @property
    def heartbeat_count(self) -> int:
        """Number of successful heartbeats emitted."""
        return self._heartbeat_count

    @property
    def suppressed_count(self) -> int:
        """Number of heartbeats suppressed due to meaningful activity."""
        return self._suppressed_count


class HeartbeatContext:
    """Context manager for automatic heartbeat lifecycle.

    Starts a heartbeat thread on entry and ensures clean shutdown on exit,
    even if an exception occurs during the wrapped operation.

    Example:
        >>> with HeartbeatContext(emit_fn, interval_seconds=60) as hb:
        ...     do_long_running_work()
        >>> print(f"Emitted {hb.heartbeat_count} heartbeats")
    """

    def __init__(
        self,
        heartbeat_fn: Callable[[], None],
        interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        should_emit_fn: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize heartbeat context.

        Args:
            heartbeat_fn: Function to call on each heartbeat.
            interval_seconds: Seconds between heartbeats (default 60).
            should_emit_fn: Optional callback returning True if heartbeat should
                be emitted. When None or returns True, heartbeat is emitted.
                Use this to suppress heartbeats during meaningful activity.
        """
        self.heartbeat_fn = heartbeat_fn
        self.interval = interval_seconds
        self.should_emit_fn = should_emit_fn
        self._thread: HeartbeatThread | None = None

    def __enter__(self) -> HeartbeatContext:
        """Start heartbeat thread."""
        self._thread = HeartbeatThread(
            self.heartbeat_fn,
            interval_seconds=self.interval,
            should_emit_fn=self.should_emit_fn,
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Stop heartbeat thread and wait for clean shutdown."""
        if self._thread:
            self._thread.stop()
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("Heartbeat thread did not stop cleanly within timeout")

    @property
    def heartbeat_count(self) -> int:
        """Number of successful heartbeats emitted."""
        if self._thread:
            return self._thread.heartbeat_count
        return 0
