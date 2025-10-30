"""Structured logging placeholder.

Will be expanded in Milestone 8.
"""
from __future__ import annotations

import logging
import json
from pathlib import Path


def build_logger(name: str = "pulldb", log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler: logging.Handler
        if log_file:
            handler = logging.FileHandler(log_file)
        else:
            handler = logging.StreamHandler()

        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
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
