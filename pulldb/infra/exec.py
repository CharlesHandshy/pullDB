"""Subprocess execution utilities for pullDB.

Provides a thin, testable wrapper around ``subprocess.run`` capturing
stdout, stderr, exit code, and timing. Designed for use by restore
workflow (myloader execution) but generic enough for reuse.

FAIL HARD Design:
  * Callers decide how to interpret non-zero exit codes (no silent retries)
  * Truncation limits applied to stdout/stderr to avoid unbounded memory
  * Timeout raises ``CommandTimeoutError`` with partial output captured

This module intentionally keeps no logging side-effects; caller handles
structured logging so job context (job_id, phase) remains consistent.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime


STDOUT_LIMIT = 200_000  # 200 KB safety cap
STDERR_LIMIT = 200_000


class CommandExecutionError(Exception):
    """Raised when command execution fails at the OS level.

    This does NOT represent a non-zero exit code (that is returned to
    the caller). It represents inability to start process (e.g. ENOENT)
    or internal Python failure.
    """

    pass


class CommandTimeoutError(Exception):
    """Raised when a command exceeds the provided timeout.

    Captures partial stdout/stderr collected before termination to aid
    diagnostics while preventing silent hangs.
    """

    def __init__(
        self, command: Sequence[str], timeout_seconds: float, stdout: str, stderr: str
    ) -> None:
        """Initialize timeout error with captured partial output.

        Args:
            command: Command sequence attempted.
            timeout_seconds: Threshold in seconds that was exceeded.
            stdout: Partial/truncated stdout captured before kill.
            stderr: Partial/truncated stderr captured before kill.
        """
        self.command = list(command)
        self.timeout_seconds = timeout_seconds
        self.partial_stdout = stdout
        self.partial_stderr = stderr
        super().__init__(
            f"Command timed out after {timeout_seconds}s: {' '.join(command)}"
        )


@dataclass(slots=True)
class CommandResult:
    """Captured results of a subprocess execution."""

    command: list[str]
    exit_code: int
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    stdout: str
    stderr: str


def _truncate(data: bytes, limit: int) -> str:
    if len(data) <= limit:
        return data.decode(errors="replace")
    # Keep last portion (tail) since it usually contains the error
    tail = data[-limit:]
    return "<truncated>..." + tail.decode(errors="replace")


def run_command(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    cwd: str | None = None,
) -> CommandResult:
    """Execute a command returning structured result.

    Args:
        command: Sequence of program + arguments.
        env: Optional environment variable overrides (merged onto process env).
        timeout: Optional timeout in seconds; on timeout a CommandTimeoutError
            is raised with partial output.
        cwd: Optional working directory.

    Returns:
        CommandResult with captured data.

    Raises:
        CommandExecutionError: Process could not be started.
        CommandTimeoutError: Execution exceeded timeout.
    """
    start = datetime.now(UTC)
    try:
        proc = subprocess.Popen(  # args are sequence, no shell
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=None if env is None else {**env},
            cwd=cwd,
            text=False,
        )
    except Exception as e:  # pragma: no cover - hard to simulate
        raise CommandExecutionError(
            f"Failed to start command: {' '.join(command)} ({e})"
        ) from e

    try:
        stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as te:  # pragma: no cover - tested logically
        # Kill process and capture any remaining output
        proc.kill()
        stdout_bytes, stderr_bytes = proc.communicate()
        raise CommandTimeoutError(
            command,
            timeout if timeout is not None else -1,
            _truncate(stdout_bytes, STDOUT_LIMIT),
            _truncate(stderr_bytes, STDERR_LIMIT),
        ) from te

    completed = datetime.now(UTC)
    duration = (completed - start).total_seconds()

    stdout = _truncate(stdout_bytes or b"", STDOUT_LIMIT)
    stderr = _truncate(stderr_bytes or b"", STDERR_LIMIT)

    return CommandResult(
        command=list(command),
        exit_code=proc.returncode or 0,
        started_at=start,
        completed_at=completed,
        duration_seconds=duration,
        stdout=stdout,
        stderr=stderr,
    )
