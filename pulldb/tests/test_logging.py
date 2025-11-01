"""Tests for structured logging module."""

from __future__ import annotations

import json
import logging

import pytest

from pulldb.infra.logging import JSONFormatter, get_logger


def test_json_formatter_basic_fields() -> None:
    """JSONFormatter includes timestamp, level, logger, message."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "INFO"
    assert data["logger"] == "test.logger"
    assert data["message"] == "Test message"
    assert "timestamp" in data


def test_json_formatter_extra_fields() -> None:
    """JSONFormatter merges extra fields from LogRecord."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Job started",
        args=(),
        exc_info=None,
    )
    # Add extra fields as attributes
    record.job_id = "abc123"  # type: ignore[attr-defined]
    record.phase = "download"  # type: ignore[attr-defined]

    output = formatter.format(record)
    data = json.loads(output)

    assert data["job_id"] == "abc123"
    assert data["phase"] == "download"


def test_json_formatter_exception_info() -> None:
    """JSONFormatter includes exception traceback when present."""
    formatter = JSONFormatter()

    try:
        raise ValueError("Test error")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Operation failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    output = formatter.format(record)
    data = json.loads(output)

    assert "exception" in data
    assert "ValueError: Test error" in data["exception"]
    assert "Traceback" in data["exception"]


def test_get_logger_creates_logger() -> None:
    """get_logger returns configured Logger instance."""
    logger = get_logger("pulldb.test")

    assert isinstance(logger, logging.Logger)
    assert logger.name == "pulldb.test"
    assert logger.level == logging.INFO


def test_get_logger_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    """get_logger produces JSON-formatted output."""
    logger = get_logger("pulldb.test.output")
    logger.info("Test log message", extra={"job_id": "test123"})

    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())

    assert data["level"] == "INFO"
    assert data["message"] == "Test log message"
    assert data["job_id"] == "test123"


def test_get_logger_idempotent() -> None:
    """get_logger returns same instance for same name."""
    logger1 = get_logger("pulldb.idempotent")
    logger2 = get_logger("pulldb.idempotent")

    assert logger1 is logger2


def test_get_logger_no_propagation() -> None:
    """get_logger disables propagation to prevent duplicate logs."""
    logger = get_logger("pulldb.no_propagate")

    assert logger.propagate is False


def test_get_logger_custom_level() -> None:
    """get_logger accepts custom log level."""
    logger = get_logger("pulldb.debug", level=logging.DEBUG)

    assert logger.level == logging.DEBUG
