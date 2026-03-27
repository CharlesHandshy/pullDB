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

HCA Layer: shared
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from pulldb.domain.models import CommandResult


STDOUT_LIMIT = 200_000  # 200 KB safety cap
STDERR_LIMIT = 200_000

# Patterns for sensitive data redaction (case-insensitive)
_SENSITIVE_PATTERNS = [
    # CLI flags: --password=xxx, -p xxx, --pass=xxx
    re.compile(r"(--password[=\s])([^\s'\"]+)", re.IGNORECASE),
    re.compile(r"(--pass[=\s])([^\s'\"]+)", re.IGNORECASE),
    re.compile(r"(-p\s+)([^\s]+)", re.IGNORECASE),
    # Connection strings: mysql://user:password@host
    re.compile(r"(://[^:]+:)([^@]+)(@)", re.IGNORECASE),
    # AWS secret keys (40 chars, alphanumeric with + and /)
    re.compile(r"(aws_secret_access_key[=:\s]+)([A-Za-z0-9+/]{40})", re.IGNORECASE),
    # Generic password assignments: password=xxx, passwd=xxx
    re.compile(r"(password[=:\s]+)([^\s,;'\"]+)", re.IGNORECASE),
    re.compile(r"(passwd[=:\s]+)([^\s,;'\"]+)", re.IGNORECASE),
]


def redact_sensitive_data(text: str) -> str:
    """Redact passwords and secrets from text for safe logging.

    Applies multiple regex patterns to catch common credential formats:
      - CLI flags: --password=xxx, -p xxx
      - Connection strings: mysql://user:password@host
      - AWS secrets: aws_secret_access_key=xxx
      - Generic: password=xxx, passwd=xxx

    Args:
        text: Raw text potentially containing credentials.

    Returns:
        Text with sensitive values replaced by [REDACTED].
    """
    result = text
    for pattern in _SENSITIVE_PATTERNS:
        # Replace group 2 (the actual secret) with [REDACTED]
        result = pattern.sub(r"\1[REDACTED]\3" if pattern.groups == 3 else r"\1[REDACTED]", result)
    return result


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
        exit_code=proc.returncode if proc.returncode is not None else 0,
        started_at=start,
        completed_at=completed,
        duration_seconds=duration,
        stdout=stdout,
        stderr=stderr,
    )


class CommandAbortedError(Exception):
    """Raised when a command is aborted via abort_check callback.

    This indicates controlled termination due to job cancellation or
    external failure (e.g., stale recovery marked job as failed).
    """

    def __init__(
        self, command: Sequence[str], stdout: str
    ) -> None:
        self.command = list(command)
        self.partial_stdout = stdout
        super().__init__(f"Command aborted: {' '.join(command)}")


def run_command_streaming(
    command: Sequence[str],
    line_callback: Callable[[str], None],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    cwd: str | None = None,
    abort_check: Callable[[], bool] | None = None,
    abort_check_interval: int = 100,
) -> CommandResult:
    """Execute command, streaming merged stdout/stderr to callback.

    Args:
        command: Sequence of program + arguments.
        line_callback: Function called with each line of output (decoded).
        env: Optional environment variable overrides.
        timeout: Optional timeout in seconds.
        cwd: Optional working directory.
        abort_check: Optional callback that returns True if command should abort.
            Checked every abort_check_interval lines. Use to stop long-running
            commands when the job is cancelled or marked failed externally.
        abort_check_interval: How often to call abort_check (default every 100 lines).

    Returns:
        CommandResult with captured stdout (stderr will be empty as it is merged).
        Output is truncated to STDOUT_LIMIT (keeping tail).

    Raises:
        CommandAbortedError: If abort_check returns True during execution.
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
    line_count = 0

    try:
        if proc.stdout:
            for line in proc.stdout:
                line_callback(line)
                line_count += 1

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

                # Check for abort (job cancelled or marked failed externally)
                if abort_check and line_count % abort_check_interval == 0:
                    if abort_check():
                        proc.kill()
                        stdout_str = "".join(captured_buffer)
                        raise CommandAbortedError(
                            command, _truncate_str(stdout_str, STDOUT_LIMIT)
                        )

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
        exit_code=proc.returncode if proc.returncode is not None else 0,
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
        line_callback: Callable[[str], None],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
        abort_check: Callable[[], bool] | None = None,
        abort_check_interval: int = 100,
    ) -> CommandResult:
        """Execute command, streaming merged stdout/stderr to callback."""
        return run_command_streaming(
            command, line_callback, env=env, timeout=timeout, cwd=cwd,
            abort_check=abort_check, abort_check_interval=abort_check_interval
        )
