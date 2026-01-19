"""Event Bus for Simulation Mode.

Provides a pub/sub system for tracing all simulation events.
Enables observability, debugging, and test assertions on event sequences.

HCA Layer: features
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of events emitted by the simulation engine."""

    # Job lifecycle events
    JOB_CREATED = "job.created"
    JOB_CLAIMED = "job.claimed"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    JOB_CANCELED = "job.canceled"

    # S3 events
    S3_LIST_KEYS = "s3.list_keys"
    S3_HEAD_OBJECT = "s3.head_object"
    S3_GET_OBJECT = "s3.get_object"
    S3_ERROR = "s3.error"

    # Executor events
    EXEC_START = "exec.start"
    EXEC_COMPLETE = "exec.complete"
    EXEC_ERROR = "exec.error"

    # Database events
    DB_QUERY = "db.query"
    DB_INSERT = "db.insert"
    DB_UPDATE = "db.update"

    # System events
    STATE_RESET = "state.reset"
    SCENARIO_CHANGED = "scenario.changed"


@dataclass(frozen=True)
class SimulationEvent:
    """An event emitted by the simulation engine."""

    event_type: EventType
    timestamp: datetime
    source: str  # Component that emitted the event (e.g., "MockS3Client")
    data: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None  # Optional job context


EventCallback = Callable[[SimulationEvent], None]


class SimulationEventBus:
    """Thread-safe pub/sub event bus for simulation events.

    Features:
    - Subscribe to specific event types or all events
    - Event history for test assertions
    - Console logging integration
    """

    def __init__(self, max_history: int = 1000) -> None:
        """Initialize the event bus.

        Args:
            max_history: Maximum events to retain in history.
        """
        self._lock = threading.RLock()
        self._subscribers: dict[EventType | None, list[EventCallback]] = {}
        self._history: list[SimulationEvent] = []
        self._max_history = max_history
        self._console_logging = False

    def subscribe(
        self,
        callback: EventCallback,
        event_type: EventType | None = None,
    ) -> Callable[[], None]:
        """Subscribe to events.

        Args:
            callback: Function to call when event occurs.
            event_type: Specific type to subscribe to, or None for all events.

        Returns:
            Unsubscribe function.
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if event_type in self._subscribers:
                    with suppress(ValueError):
                        self._subscribers[event_type].remove(callback)

        return unsubscribe

    def emit(
        self,
        event_type: EventType,
        source: str,
        data: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> SimulationEvent:
        """Emit an event to all subscribers.

        Args:
            event_type: Type of event.
            source: Component emitting the event.
            data: Optional event payload.
            job_id: Optional job context.

        Returns:
            The emitted event.
        """
        event = SimulationEvent(
            event_type=event_type,
            timestamp=datetime.now(UTC),
            source=source,
            data=data or {},
            job_id=job_id,
        )

        with self._lock:
            # Add to history
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]

            # Console logging
            if self._console_logging:
                logger.info(
                    f"[SIM] {event.event_type.value}: {event.source} "
                    f"job={event.job_id} data={event.data}"
                )

            # Notify type-specific subscribers
            for callback in self._subscribers.get(event_type, []):
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Event callback error: {e}", exc_info=True)

            # Notify global subscribers
            for callback in self._subscribers.get(None, []):
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Event callback error: {e}", exc_info=True)

        return event

    def get_history(
        self,
        event_type: EventType | None = None,
        job_id: str | None = None,
        limit: int | None = None,
    ) -> list[SimulationEvent]:
        """Get event history with optional filtering.

        Args:
            event_type: Filter by event type.
            job_id: Filter by job ID.
            limit: Maximum events to return.

        Returns:
            List of matching events, newest first.
        """
        with self._lock:
            events = list(self._history)

        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if job_id is not None:
            events = [e for e in events if e.job_id == job_id]

        events.reverse()  # Newest first
        if limit is not None:
            events = events[:limit]

        return events

    def clear_history(self) -> None:
        """Clear event history."""
        with self._lock:
            self._history.clear()

    def clear_subscribers(self) -> None:
        """Clear all subscribers."""
        with self._lock:
            self._subscribers.clear()

    def enable_console_logging(self, enabled: bool = True) -> None:
        """Enable/disable console logging of events."""
        self._console_logging = enabled

    def wait_for_event(
        self,
        event_type: EventType,
        timeout: float = 5.0,
        predicate: Callable[[SimulationEvent], bool] | None = None,
    ) -> SimulationEvent | None:
        """Wait for a specific event (useful for tests).

        Args:
            event_type: Event type to wait for.
            timeout: Maximum seconds to wait.
            predicate: Optional filter function.

        Returns:
            The matching event, or None if timeout.
        """
        event_received: SimulationEvent | None = None
        received = threading.Event()

        def handler(event: SimulationEvent) -> None:
            nonlocal event_received
            if predicate is None or predicate(event):
                event_received = event
                received.set()

        unsubscribe = self.subscribe(handler, event_type)
        try:
            received.wait(timeout)
            return event_received
        finally:
            unsubscribe()


class _BusHolder:
    """Singleton holder for event bus."""

    bus: SimulationEventBus | None = None
    lock: threading.Lock = threading.Lock()


_holder = _BusHolder()


def get_event_bus() -> SimulationEventBus:
    """Get the global event bus instance."""
    with _holder.lock:
        if _holder.bus is None:
            _holder.bus = SimulationEventBus()
        return _holder.bus


def reset_event_bus() -> None:
    """Reset the event bus (for testing)."""
    with _holder.lock:
        if _holder.bus is not None:
            _holder.bus.clear_history()
            _holder.bus.clear_subscribers()
        _holder.bus = None
