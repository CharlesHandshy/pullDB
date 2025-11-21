"""Utilities for normalizing worker subprocess log output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


_LOG_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    ^\*\*                                  # log prefix
    (?:\s*\([^)]+\))?                     # optional binary info e.g. (myloader-0.19...)
    (?::)?                                  # optional colon after prefix
    \s*(?P<severity>Message|WARNING|ERROR)  # severity token
    (?:\s*\*\*)?                          # optional closing ** (seen on warnings)
    :\s*(?P<time>\d{2}:\d{2}:\d{2}\.\d{3}) # timestamp HH:MM:SS.mmm
    :\s*(?P<body>.+)$                      # remainder
    """,
    re.VERBOSE,
)

_THREAD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:S-Thread|Thread)\s+(?P<thread>\d+)"
)

_TABLE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"`(?P<schema>[A-Za-z0-9_]+)`\.`(?P<table>[^`]+)`"
)

_PROGRESS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\[\s*(?P<pct>\d+)%\s*\]\s*\|\s*Tables:\s*(?P<processed>\d+)/(\d+)"
)

_PHASE_RULES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"Starting import"), "thread-start"),
    (re.compile(r"connected using"), "thread-connect"),
    (re.compile(r"shutting down"), "thread-stop"),
    (re.compile(r"Fast index creation"), "index"),
    (re.compile(r"Dropping table|Creating table"), "table-schema"),
    (re.compile(r"dumping data for"), "table-data"),
    (re.compile(r"\[\s*\d+%\s*\]"), "table-data"),
    (re.compile(r"Executing set session"), "session"),
    (re.compile(r"Finished (?:dump|restore)"), "complete"),
    (re.compile(r"Queue count"), "queue"),
)


@dataclass(slots=True, frozen=True)
class NormalizedLogEvent:
    """Structured representation of a parsed subprocess log line."""

    tool: str
    version: str
    severity: str
    phase: str
    time: str | None
    thread: int | None
    schema: str | None
    table: str | None
    table_pct: int | None
    tables_processed: tuple[int, int] | None
    message: str
    raw: str


def _detect_phase(body: str, severity: str) -> str:
    for pattern, phase in _PHASE_RULES:
        if pattern.search(body):
            return phase
    return "warning" if severity == "warning" else "message"


def _extract_thread(body: str) -> int | None:
    match = _THREAD_PATTERN.search(body)
    return int(match.group("thread")) if match else None


def _extract_table(body: str) -> tuple[str | None, str | None]:
    match = _TABLE_PATTERN.search(body)
    if not match:
        return None, None
    return match.group("schema"), match.group("table")


def _extract_progress(body: str) -> tuple[int | None, tuple[int, int] | None]:
    match = _PROGRESS_PATTERN.search(body)
    if not match:
        return None, None
    pct = int(match.group("pct"))
    processed = int(match.group("processed"))
    total = int(match.group(3))
    return pct, (processed, total)


def normalize_myloader_line(line: str, *, version: str) -> NormalizedLogEvent | None:
    """Normalize a single myloader log line into structured data."""
    stripped = line.strip()
    match = _LOG_PATTERN.match(stripped)
    if not match:
        return None

    severity_token = match.group("severity")
    severity = {
        "Message": "info",
        "WARNING": "warning",
        "ERROR": "error",
    }.get(severity_token, "info")
    time_value = match.group("time")
    body = match.group("body").strip()

    thread = _extract_thread(body)
    schema, table = _extract_table(body)
    table_pct, tables_processed = _extract_progress(body)
    phase = _detect_phase(body, severity)

    return NormalizedLogEvent(
        tool="myloader",
        version=version,
        severity=severity,
        phase=phase,
        time=time_value,
        thread=thread,
        schema=schema,
        table=table,
        table_pct=table_pct,
        tables_processed=tables_processed,
        message=body,
        raw=line,
    )


__all__ = ["NormalizedLogEvent", "normalize_myloader_line"]
