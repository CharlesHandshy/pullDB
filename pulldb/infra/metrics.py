"""Metrics emission for pullDB.

Provides structured logging-based metrics for operational observability.
Designed for easy migration to CloudWatch/Prometheus later while maintaining
simple file-based logging for prototype phase.

Metrics categories:
- Counters: Total counts (jobs_enqueued, jobs_completed, jobs_failed)
- Gauges: Point-in-time values (queue_depth, active_restores)
- Timers: Duration (restore_duration_seconds, download_duration_seconds)
- Events: Significant occurrences with context (disk_capacity_insufficient,
  myloader_error)

All metrics are emitted as structured JSON log events with metric_type field
for easy filtering and aggregation.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.metrics")


@dataclass
class MetricLabels:
    """Common label dimensions for metrics.

    Attributes:
        job_id: UUID of associated job (optional).
        target: Target database name (optional).
        phase: Workflow phase (e.g., download, restore, post_sql).
        status: Result status (e.g., success, failed, timeout).
    """

    job_id: str | None = None
    target: str | None = None
    phase: str | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Convert labels to dict for logging extra field.

        Returns:
            Dictionary with non-None label values.
        """
        return {k: v for k, v in self.__dict__.items() if v is not None}


def emit_counter(name: str, value: int = 1, labels: MetricLabels | None = None) -> None:
    """Emit counter metric (monotonically increasing count).

    Examples:
        jobs_enqueued_total
        restore_attempts_total
        disk_capacity_errors_total

    Args:
        name: Metric name (use snake_case with _total suffix).
        value: Increment amount (default 1).
        labels: Optional label dimensions.
    """
    extra = {"metric_type": "counter", "metric_name": name, "metric_value": value}
    if labels:
        extra.update(labels.to_dict())
    logger.info(f"counter: {name} += {value}", extra=extra)


def emit_gauge(name: str, value: float, labels: MetricLabels | None = None) -> None:
    """Emit gauge metric (point-in-time measurement).

    Examples:
        queue_depth
        active_restores
        disk_free_gb

    Args:
        name: Metric name (use snake_case).
        value: Current value.
        labels: Optional label dimensions.
    """
    extra = {"metric_type": "gauge", "metric_name": name, "metric_value": value}
    if labels:
        extra.update(labels.to_dict())
    logger.info(f"gauge: {name} = {value}", extra=extra)


def emit_timer(
    name: str, duration_seconds: float, labels: MetricLabels | None = None
) -> None:
    """Emit timer metric (duration measurement).

    Examples:
        restore_duration_seconds
        download_duration_seconds
        myloader_duration_seconds

    Args:
        name: Metric name (use snake_case with _duration_seconds suffix).
        duration_seconds: Duration in seconds (float for sub-second precision).
        labels: Optional label dimensions.
    """
    extra = {
        "metric_type": "timer",
        "metric_name": name,
        "metric_value": duration_seconds,
    }
    if labels:
        extra.update(labels.to_dict())
    logger.info(
        f"timer: {name} = {duration_seconds:.3f}s",
        extra=extra,
    )


@contextmanager
def time_operation(name: str, labels: MetricLabels | None = None) -> Iterator[None]:
    """Context manager for timing operations.

    Automatically emits timer metric when context exits. Use for wrapping
    operations you want to measure.

    Example:
        with time_operation("restore_duration_seconds", labels):
            perform_restore()

    Args:
        name: Metric name for timer.
        labels: Optional label dimensions.

    Yields:
        None (context manager doesn't provide value).
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        emit_timer(name, duration, labels)


def emit_event(name: str, message: str, labels: MetricLabels | None = None) -> None:
    """Emit event metric (significant occurrence with context).

    Use for notable events that aren't pure counters/gauges/timers but carry
    operational significance (errors, warnings, state changes).

    Examples:
        disk_capacity_insufficient
        myloader_nonzero_exit
        post_sql_failure

    Args:
        name: Event name (use snake_case).
        message: Human-readable event description.
        labels: Optional label dimensions.
    """
    extra = {"metric_type": "event", "metric_name": name, "event_message": message}
    if labels:
        extra.update(labels.to_dict())
    logger.warning(f"event: {name} - {message}", extra=extra)


__all__ = [
    "MetricLabels",
    "emit_counter",
    "emit_event",
    "emit_gauge",
    "emit_timer",
    "time_operation",
]
