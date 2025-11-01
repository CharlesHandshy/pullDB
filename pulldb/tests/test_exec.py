"""Tests for infra.exec.run_command utility."""

from __future__ import annotations

# ruff: noqa: I001  # import layout stable for test clarity
from typing import Any, NoReturn
import subprocess
import sys

import pytest

from pulldb.infra.exec import CommandExecutionError, CommandTimeoutError, run_command

NON_ZERO_EXIT_CODE = 3
TRUNCATION_SAFETY_MAX = 210_000


def _python_exe() -> str:
    return sys.executable


def test_run_command_success() -> None:
    result = run_command([_python_exe(), "-c", "print('hello')"])
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.duration_seconds >= 0


def test_run_command_nonzero_exit() -> None:
    result = run_command(
        [_python_exe(), "-c", f"import sys; sys.exit({NON_ZERO_EXIT_CODE})"]
    )
    assert result.exit_code == NON_ZERO_EXIT_CODE
    assert result.stderr == ""  # No stderr emitted


def test_run_command_timeout() -> None:
    with pytest.raises(CommandTimeoutError):
        run_command([_python_exe(), "-c", "import time; time.sleep(2)"], timeout=0.3)


def test_run_command_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate failure to start process by patching Popen to raise."""

    class BoomError(Exception):
        """Synthetic error to simulate process spawn failure."""

    original_popen = subprocess.Popen

    def fake_popen(*_a: Any, **_k: Any) -> NoReturn:  # Match Popen signature loosely
        raise BoomError("ENOENT")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(CommandExecutionError):
        run_command(["does-not-exist-xyz123"], timeout=0.1)
    monkeypatch.setattr(subprocess, "Popen", original_popen)


def test_truncation_limits() -> None:
    # Generate large output inside the subprocess to avoid oversized argv
    result = run_command(
        [
            _python_exe(),
            "-c",
            "import sys; sys.stdout.write('x'*300000)",
        ]
    )
    assert result.stdout.startswith("<truncated>")
    assert len(result.stdout) < TRUNCATION_SAFETY_MAX  # safety margin
