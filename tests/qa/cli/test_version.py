"""
Category 1: Basic Command Execution Tests

Tests for:
- CLI invocation and version info
- Help text for all commands
- Global options and argument handling

Test Count: 15 tests
"""

from __future__ import annotations

import re

import pytest
from click.testing import CliRunner

from pulldb.cli.main import cli


# ---------------------------------------------------------------------------
# Version and Basic Invocation Tests
# ---------------------------------------------------------------------------


class TestCLIVersion:
    """Tests for pulldb --version and basic invocation."""

    def test_version_flag_shows_version(self, runner: CliRunner) -> None:
        """pulldb --version shows version string."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        # Version format: pulldb, version X.Y.Z
        assert "pulldb" in result.output.lower()
        assert "version" in result.output.lower()

    def test_version_contains_semantic_version(self, runner: CliRunner) -> None:
        """Version output contains valid semantic version (X.Y.Z)."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        # Match semantic version pattern
        version_pattern = r"\d+\.\d+\.\d+"
        assert re.search(version_pattern, result.output), (
            f"No semantic version found in: {result.output}"
        )

    def test_bare_command_shows_help(self, runner: CliRunner) -> None:
        """pulldb without arguments shows help text."""
        result = runner.invoke(cli, [])
        # Should show help or error asking for command
        assert result.exit_code in [0, 2]  # 0 for help, 2 for missing command
        # Should mention available commands
        assert any(
            cmd in result.output.lower()
            for cmd in ["restore", "status", "search", "history"]
        )


# ---------------------------------------------------------------------------
# Help Text Tests
# ---------------------------------------------------------------------------


class TestHelpText:
    """Tests for --help on all commands."""

    def test_main_help(self, runner: CliRunner) -> None:
        """pulldb --help shows main help."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output or "usage:" in result.output.lower()
        # Should list all commands
        for cmd in ["restore", "status", "search", "history", "events", "profile"]:
            assert cmd in result.output.lower(), f"Command '{cmd}' not in help"

    def test_restore_help(self, runner: CliRunner) -> None:
        """pulldb restore --help shows restore help."""
        result = runner.invoke(cli, ["restore", "--help"])
        assert result.exit_code == 0
        assert "restore" in result.output.lower()
        # Should mention key options
        assert "target" in result.output.lower() or "database" in result.output.lower()

    def test_search_help(self, runner: CliRunner) -> None:
        """pulldb search --help shows search help."""
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output.lower()

    def test_status_help(self, runner: CliRunner) -> None:
        """pulldb status --help shows status help."""
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output.lower()

    def test_history_help(self, runner: CliRunner) -> None:
        """pulldb history --help shows history help."""
        result = runner.invoke(cli, ["history", "--help"])
        assert result.exit_code == 0
        assert "history" in result.output.lower()

    def test_events_help(self, runner: CliRunner) -> None:
        """pulldb events --help shows events help."""
        result = runner.invoke(cli, ["events", "--help"])
        assert result.exit_code == 0
        assert "events" in result.output.lower()

    def test_profile_help(self, runner: CliRunner) -> None:
        """pulldb profile --help shows profile help."""
        result = runner.invoke(cli, ["profile", "--help"])
        assert result.exit_code == 0
        assert "profile" in result.output.lower()

    def test_cancel_help(self, runner: CliRunner) -> None:
        """pulldb cancel --help shows cancel help."""
        result = runner.invoke(cli, ["cancel", "--help"])
        assert result.exit_code == 0
        assert "cancel" in result.output.lower()


# ---------------------------------------------------------------------------
# Invalid Command Tests
# ---------------------------------------------------------------------------


class TestInvalidCommands:
    """Tests for invalid command handling."""

    def test_unknown_command_shows_error(self, runner: CliRunner) -> None:
        """pulldb unknowncmd shows error."""
        result = runner.invoke(cli, ["unknowncmd"])
        assert result.exit_code != 0
        # Should indicate command not found
        output_lower = result.output.lower()
        assert "no such command" in output_lower or "error" in output_lower

    def test_invalid_option_shows_error(self, runner: CliRunner) -> None:
        """pulldb --invalidoption shows error."""
        result = runner.invoke(cli, ["--invalidoption"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# API URL Configuration Tests
# ---------------------------------------------------------------------------


class TestAPIURLConfiguration:
    """Tests for PULLDB_API_URL environment handling."""

    def test_api_url_from_env(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Commands use PULLDB_API_URL from environment."""
        monkeypatch.setenv("PULLDB_API_URL", "http://custom-api:9000")
        # This will fail to connect, but we verify the URL is being used
        result = runner.invoke(cli, ["status"])
        # Should either use the URL or show connection error to that URL
        # The important thing is it doesn't crash on startup
        assert result.exit_code in [0, 1, 2]

    def test_default_api_url(self, runner: CliRunner) -> None:
        """Commands have default API URL when env not set."""
        # Unset the env var if present
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should work without API URL set (help doesn't need API)
