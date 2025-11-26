"""Structured logging for pullDB.

Provides JSON-formatted logging with consistent field injection for job context,
phase tracking, and operational visibility. All log statements include timestamps,
severity, and optional structured fields (job_id, target, phase).

Example:
    >>> logger = get_logger("pulldb.worker")
    >>> logger.info("Job started", extra={"job_id": "123", "phase": "download"})
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from typing import Any, cast

# Context variable to track the active task name (e.g., job ID)
current_task_name: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "task_name", default=None
)


class JSONFormatter(logging.Formatter):
    """JSON log formatter with structured fields.

    Converts log records to single-line JSON for parsing by log aggregation
    systems (Datadog, CloudWatch, etc.). Includes timestamp, level, logger name,
    message, and any extra fields passed via the `extra` parameter.

    Attributes:
        None (inherits from logging.Formatter)
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string.

        Args:
            record: LogRecord to format.

        Returns:
            Single-line JSON string with structured log data.
        """
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Merge extra fields (job_id, target, phase, etc.)
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
            }:
                log_data[key] = value

        return json.dumps(log_data)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Get or create a structured JSON logger.

    Creates a logger with JSON formatting that writes to stdout. Repeated calls
    with the same name return the same logger instance (Python logging behavior).

    Args:
        name: Logger name (typically module path like 'pulldb.worker.restore').
        level: Minimum log level (default: INFO).

    Returns:
        Configured Logger instance with JSON formatter.

    Example:
        >>> logger = get_logger("pulldb.worker")
        >>> logger.info("Starting restore", extra={"job_id": "abc123"})
        {"timestamp": "2025-11-01 10:30:00", "level": "INFO", ...}
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured (prevent duplicate handlers)
    if not logger.handlers:
        logger.setLevel(level)

        # Console handler with JSON formatting
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

        # Prevent propagation to root logger (avoid duplicate logs)
        logger.propagate = False

    return logger


def _task_name_log_record_factory(
    original_factory: Any,
) -> Any:
    """Create a log record factory that injects the current task name."""

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = cast(logging.LogRecord, original_factory(*args, **kwargs))
        task_name = current_task_name.get()
        # Only override if we have a value, otherwise leave as is (None or asyncio task)
        if task_name is not None:
            record.taskName = task_name
        return record

    return factory


# Install the log record factory to inject task names
logging.setLogRecordFactory(
    _task_name_log_record_factory(logging.getLogRecordFactory())
)
