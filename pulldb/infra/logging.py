"""Structured logging placeholder.

Will be expanded in Milestone 8.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path


def build_logger(name: str = "pulldb", log_file: Path | None = None) -> logging.Logger:
    """Build a structured JSON logger.

    Creates a logger that outputs JSON-formatted log messages. Supports both
    file and console output with optional structured fields (job_id, phase).

    Args:
        name: Logger name, defaults to "pulldb".
        log_file: Optional file path for log output. If None, logs to stderr.

    Returns:
        Configured logger instance with JSON formatting.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler: logging.Handler = (
            logging.FileHandler(log_file) if log_file else logging.StreamHandler()
        )

        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "timestamp": self.formatTime(record),
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "logger": record.name,
                }
                for extra_key in ("job_id", "phase"):
                    if hasattr(record, extra_key):
                        payload[extra_key] = getattr(record, extra_key)
                return json.dumps(payload)

        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger
