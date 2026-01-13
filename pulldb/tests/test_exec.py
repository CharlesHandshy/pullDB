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


# --- Tests for redact_sensitive_data ---

from pulldb.infra.exec import redact_sensitive_data


class TestRedactSensitiveData:
    """Tests for password and secret redaction."""

    def test_redacts_password_flag(self) -> None:
        """Redacts --password=xxx from myloader commands."""
        cmd = "/opt/myloader --password=A2o5#nrrgWxv21Y1VqeZ%eVv --host=db.example.com"
        result = redact_sensitive_data(cmd)
        assert "A2o5#" not in result
        assert "[REDACTED]" in result
        assert "--host=db.example.com" in result

    def test_redacts_password_flag_with_space(self) -> None:
        """Redacts --password xxx with space separator."""
        cmd = "mysql --password secret123 --host db.example.com"
        result = redact_sensitive_data(cmd)
        assert "secret123" not in result
        assert "[REDACTED]" in result

    def test_redacts_short_p_flag(self) -> None:
        """Redacts -p password short form."""
        cmd = "mysql -p MyS3cretP@ss -h localhost"
        result = redact_sensitive_data(cmd)
        assert "MyS3cretP@ss" not in result
        assert "-h localhost" in result

    def test_redacts_connection_string_password(self) -> None:
        """Redacts password from connection string."""
        conn = "mysql://admin:SuperSecret123@db.example.com:3306/mydb"
        result = redact_sensitive_data(conn)
        assert "SuperSecret123" not in result
        assert "mysql://admin:[REDACTED]@db.example.com" in result

    def test_redacts_aws_secret_key(self) -> None:
        """Redacts AWS secret access key."""
        text = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY1"
        result = redact_sensitive_data(text)
        assert "wJalrXUtnFEMI" not in result
        assert "[REDACTED]" in result

    def test_redacts_generic_password_assignment(self) -> None:
        """Redacts password=xxx format."""
        text = "Connecting with password=hunter2 to database"
        result = redact_sensitive_data(text)
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_preserves_non_sensitive_content(self) -> None:
        """Does not modify text without credentials."""
        text = "Restored 1000 rows from backup_daily_2026-01-13.tar"
        result = redact_sensitive_data(text)
        assert result == text

    def test_handles_multiline_logs(self) -> None:
        """Redacts passwords in multiline myloader verbose output."""
        log = """** (myloader:12345): Message
** (myloader:12345): Opening connection with password=secret123
** (myloader:12345): Tables restored: 50"""
        result = redact_sensitive_data(log)
        assert "secret123" not in result
        assert "Tables restored: 50" in result

    def test_empty_string(self) -> None:
        """Handles empty string input."""
        assert redact_sensitive_data("") == ""

    def test_redacts_multiple_passwords_same_line(self) -> None:
        """Redacts multiple password occurrences."""
        text = "--password=pass1 --pass=pass2"
        result = redact_sensitive_data(text)
        assert "pass1" not in result
        assert "pass2" not in result
        assert result.count("[REDACTED]") == 2
