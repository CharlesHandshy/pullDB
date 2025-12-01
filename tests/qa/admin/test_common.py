"""
Category 1: Common Admin CLI Behavior Tests

Tests for:
- Help display
- Version display
- Unknown commands/options
- Basic CLI structure

Test Count: 12 tests
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from pulldb.cli.admin import cli

from .conftest import assert_contains, assert_error, assert_success


# ---------------------------------------------------------------------------
# Help and Version
# ---------------------------------------------------------------------------


class TestAdminHelp:
    """Tests for admin CLI help display."""

    def test_admin_help(self, runner: CliRunner) -> None:
        """pulldb-admin --help shows help."""
        result = runner.invoke(cli, ["--help"])
        assert_success(result)
        assert_contains(result, "pullDB Admin", "System administration")

    def test_admin_short_help(self, runner: CliRunner) -> None:
        """pulldb-admin -h shows help."""
        result = runner.invoke(cli, ["-h"])
        # Click doesn't support -h by default, expect error or help
        assert result.exit_code in [0, 2]

    def test_admin_no_args_shows_help(self, runner: CliRunner) -> None:
        """pulldb-admin with no args shows help or command list."""
        result = runner.invoke(cli, [])
        # Should show help or list commands
        assert result.exit_code in [0, 2]

    def test_admin_jobs_help(self, runner: CliRunner) -> None:
        """pulldb-admin jobs --help shows jobs help."""
        result = runner.invoke(cli, ["jobs", "--help"])
        assert_success(result)
        assert_contains(result, "jobs")

    def test_admin_hosts_help(self, runner: CliRunner) -> None:
        """pulldb-admin hosts --help shows hosts help."""
        result = runner.invoke(cli, ["hosts", "--help"])
        assert_success(result)
        assert_contains(result, "hosts")

    def test_admin_users_help(self, runner: CliRunner) -> None:
        """pulldb-admin users --help shows users help."""
        result = runner.invoke(cli, ["users", "--help"])
        assert_success(result)
        assert_contains(result, "users")

    def test_admin_settings_help(self, runner: CliRunner) -> None:
        """pulldb-admin settings --help shows settings help."""
        result = runner.invoke(cli, ["settings", "--help"])
        assert_success(result)
        assert_contains(result, "settings")

    def test_admin_cleanup_help(self, runner: CliRunner) -> None:
        """pulldb-admin cleanup --help shows cleanup help."""
        result = runner.invoke(cli, ["cleanup", "--help"])
        assert_success(result)
        assert_contains(result, "cleanup")


class TestAdminVersion:
    """Tests for admin CLI version display."""

    def test_admin_version(self, runner: CliRunner) -> None:
        """pulldb-admin --version shows version."""
        result = runner.invoke(cli, ["--version"])
        assert_success(result)
        assert_contains(result, "pulldb-admin")

    def test_admin_version_format(self, runner: CliRunner) -> None:
        """pulldb-admin --version shows semantic version."""
        result = runner.invoke(cli, ["--version"])
        assert_success(result)
        # Should contain version number pattern
        import re
        assert re.search(r"\d+\.\d+\.\d+", result.output), f"No version pattern in: {result.output}"


# ---------------------------------------------------------------------------
# Unknown Commands and Options
# ---------------------------------------------------------------------------


class TestAdminUnknownCommands:
    """Tests for handling unknown commands/options."""

    def test_unknown_command(self, runner: CliRunner) -> None:
        """pulldb-admin <unknown> shows error."""
        result = runner.invoke(cli, ["nonexistent"])
        assert_error(result, 2)
        assert_contains(result, "Error")

    def test_unknown_option(self, runner: CliRunner) -> None:
        """pulldb-admin --unknown shows error."""
        result = runner.invoke(cli, ["--unknown-option"])
        assert_error(result, 2)
        assert_contains(result, "Error")
