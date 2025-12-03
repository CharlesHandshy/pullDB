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
import time
import typing as t
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pulldb.domain.models import CommandResult


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


def _truncate(data: bytes, limit: int) -> str:
    if len(data) <= limit:
        return data.decode(errors="replace")
    # Keep last portion (tail) since it usually contains the error
    tail = data[-limit:]
    return "<truncated>..." + tail.decode(errors="replace")


def _truncate_str(data: str, limit: int) -> str:
    if len(data) <= limit:
        return data
    return "<truncated>..." + data[-limit:]


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


def run_command_streaming(
    command: Sequence[str],
    line_callback: t.Callable[[str], None],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    cwd: str | None = None,
) -> CommandResult:
    """Execute command, streaming merged stdout/stderr to callback.

    Args:
        command: Sequence of program + arguments.
        line_callback: Function called with each line of output (decoded).
        env: Optional environment variable overrides.
        timeout: Optional timeout in seconds.
        cwd: Optional working directory.

    Returns:
        CommandResult with captured stdout (stderr will be empty as it is merged).
        Output is truncated to STDOUT_LIMIT (keeping tail).
    """
    start = datetime.now(UTC)
    # We keep a buffer of the last N chars to return in CommandResult
    # We don't store everything to avoid memory issues with huge logs
    captured_buffer: list[str] = []
    current_buffer_size = 0

    try:
        proc = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            env=None if env is None else {**env},
            cwd=cwd,
            text=True,
            bufsize=1,  # Line buffered
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        raise CommandExecutionError(
            f"Failed to start command: {' '.join(command)} ({e})"
        ) from e

    deadline = start.timestamp() + timeout if timeout else None

    try:
        if proc.stdout:
            for line in proc.stdout:
                line_callback(line)

                # Buffer management for result
                captured_buffer.append(line)
                current_buffer_size += len(line)

                # Simple pruning if buffer gets too large (2x limit)
                if current_buffer_size > STDOUT_LIMIT * 2:
                    # Keep only enough lines to satisfy limit
                    # This is approximate but efficient
                    while current_buffer_size > STDOUT_LIMIT * 1.5:
                        removed = captured_buffer.pop(0)
                        current_buffer_size -= len(removed)

                if deadline and time.time() > deadline:
                    proc.kill()
                    raise subprocess.TimeoutExpired(command, timeout or -1)

        proc.wait(timeout=(deadline - time.time()) if deadline else None)

    except subprocess.TimeoutExpired as te:
        proc.kill()
        stdout_str = "".join(captured_buffer)
        raise CommandTimeoutError(
            command,
            timeout if timeout is not None else -1,
            _truncate_str(stdout_str, STDOUT_LIMIT),
            "",
        ) from te

    completed = datetime.now(UTC)
    duration = (completed - start).total_seconds()

    stdout_str = "".join(captured_buffer)

    return CommandResult(
        command=list(command),
        exit_code=proc.returncode or 0,
        started_at=start,
        completed_at=completed,
        duration_seconds=duration,
        stdout=_truncate_str(stdout_str, STDOUT_LIMIT),
        stderr="",  # Merged into stdout
    )


class SubprocessExecutor:
    """Executor implementation using subprocess."""

    def run_command(self, command: list[str], env: dict[str, str] | None = None) -> int:
        """Run command and return exit code."""
        result = run_command(command, env=env)
        return result.exit_code

    def run_command_streaming(
        self,
        command: Sequence[str],
        line_callback: t.Callable[[str], None],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        """Execute command, streaming merged stdout/stderr to callback."""
        return run_command_streaming(
            command, line_callback, env=env, timeout=timeout, cwd=cwd
        )
