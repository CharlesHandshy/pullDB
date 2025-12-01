"""
Category 4: Users Command Tests

Tests for:
- pulldb-admin users list
- pulldb-admin users enable
- pulldb-admin users disable
- pulldb-admin users show
- Output formats (table, JSON)
- Error handling

Test Count: 18 tests
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from pulldb.cli.admin import cli

from .conftest import (
    SAMPLE_USER_CODE,
    SAMPLE_USERNAME,
    assert_contains,
    assert_error,
    assert_success,
    assert_valid_json,
    configure_cursor_for_query,
    configure_cursor_for_update,
    configure_cursor_fetchone,
)


# ---------------------------------------------------------------------------
# Users List Command
# ---------------------------------------------------------------------------


class TestUsersList:
    """Tests for users list command."""

    def test_users_list_basic(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_columns: list[str],
        user_row_factory,
    ) -> None:
        """pulldb-admin users list shows users."""
        rows = [user_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_user_columns)

        result = runner.invoke(cli, ["users", "list"])
        assert_success(result)
        assert_contains(result, "USERNAME", "USER_CODE", "ADMIN")

    def test_users_list_empty(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_columns: list[str],
    ) -> None:
        """pulldb-admin users list with no users shows message."""
        configure_cursor_for_query(mock_mysql_pool, [], sample_user_columns)

        result = runner.invoke(cli, ["users", "list"])
        assert_success(result)
        assert_contains(result, "No users")

    def test_users_list_multiple(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_columns: list[str],
        user_row_factory,
    ) -> None:
        """pulldb-admin users list shows multiple users."""
        rows = [
            user_row_factory(username="alice", user_code="alice1"),
            user_row_factory(user_id=2, username="bob", user_code="bob123", is_admin=True),
            user_row_factory(user_id=3, username="carol", user_code="carol1", disabled=True),
        ]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_user_columns)

        result = runner.invoke(cli, ["users", "list"])
        assert_success(result)
        assert_contains(result, "alice", "bob", "carol")

    def test_users_list_json_output(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_columns: list[str],
        user_row_factory,
    ) -> None:
        """pulldb-admin users list --json outputs JSON."""
        rows = [user_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_user_columns)

        result = runner.invoke(cli, ["users", "list", "--json"])
        assert_success(result)
        data = assert_valid_json(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["username"] == SAMPLE_USERNAME

    def test_users_list_shows_summary(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_columns: list[str],
        user_row_factory,
    ) -> None:
        """pulldb-admin users list shows total count."""
        rows = [
            user_row_factory(),
            user_row_factory(user_id=2, username="user2", user_code="user2x"),
        ]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_user_columns)

        result = runner.invoke(cli, ["users", "list"])
        assert_success(result)
        assert_contains(result, "Total:", "2")


# ---------------------------------------------------------------------------
# Users Enable/Disable Commands
# ---------------------------------------------------------------------------


class TestUsersEnableDisable:
    """Tests for users enable/disable commands."""

    def test_users_enable(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin users enable <username> enables user."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(cli, ["users", "enable", SAMPLE_USERNAME])
        assert_success(result)
        assert_contains(result, "enabled")

    def test_users_enable_not_found(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin users enable unknown user shows error."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=0)

        result = runner.invoke(cli, ["users", "enable", "nonexistent"])
        assert_error(result)
        assert_contains(result, "not found")

    def test_users_disable(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin users disable <username> disables user."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(cli, ["users", "disable", SAMPLE_USERNAME])
        assert_success(result)
        assert_contains(result, "disabled")

    def test_users_disable_not_found(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin users disable unknown user shows error."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=0)

        result = runner.invoke(cli, ["users", "disable", "nonexistent"])
        assert_error(result)
        assert_contains(result, "not found")


# ---------------------------------------------------------------------------
# Users Show Command
# ---------------------------------------------------------------------------


class TestUsersShow:
    """Tests for users show command."""

    def test_users_show_basic(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_detail_columns: list[str],
        user_detail_row_factory,
    ) -> None:
        """pulldb-admin users show <username> shows user details."""
        row = user_detail_row_factory()
        configure_cursor_fetchone(mock_mysql_pool, row, sample_user_detail_columns)

        result = runner.invoke(cli, ["users", "show", SAMPLE_USERNAME])
        assert_success(result)
        assert_contains(result, "User:", SAMPLE_USERNAME)
        assert_contains(result, "User Code:", SAMPLE_USER_CODE)

    def test_users_show_job_stats(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_detail_columns: list[str],
        user_detail_row_factory,
    ) -> None:
        """pulldb-admin users show displays job statistics."""
        row = user_detail_row_factory(
            total_jobs=25,
            complete_jobs=20,
            failed_jobs=3,
            active_jobs=2,
        )
        configure_cursor_fetchone(mock_mysql_pool, row, sample_user_detail_columns)

        result = runner.invoke(cli, ["users", "show", SAMPLE_USERNAME])
        assert_success(result)
        assert_contains(result, "Job Statistics")
        assert_contains(result, "Total Jobs:", "25")
        assert_contains(result, "Complete:", "20")
        assert_contains(result, "Failed:", "3")
        assert_contains(result, "Active:", "2")

    def test_users_show_admin_status(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_detail_columns: list[str],
        user_detail_row_factory,
    ) -> None:
        """pulldb-admin users show displays admin status."""
        row = user_detail_row_factory(is_admin=True)
        configure_cursor_fetchone(mock_mysql_pool, row, sample_user_detail_columns)

        result = runner.invoke(cli, ["users", "show", SAMPLE_USERNAME])
        assert_success(result)
        assert_contains(result, "Admin:", "Yes")

    def test_users_show_disabled_status(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_user_detail_columns: list[str],
        user_detail_row_factory,
    ) -> None:
        """pulldb-admin users show displays disabled status."""
        row = user_detail_row_factory(disabled=True)
        configure_cursor_fetchone(mock_mysql_pool, row, sample_user_detail_columns)

        result = runner.invoke(cli, ["users", "show", SAMPLE_USERNAME])
        assert_success(result)
        assert_contains(result, "Disabled:", "Yes")

    def test_users_show_not_found(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin users show unknown user shows error."""
        configure_cursor_fetchone(mock_mysql_pool, None)

        result = runner.invoke(cli, ["users", "show", "nonexistent"])
        assert_error(result)
        assert_contains(result, "not found")


# ---------------------------------------------------------------------------
# Users Help
# ---------------------------------------------------------------------------


class TestUsersHelp:
    """Tests for users command help."""

    def test_users_list_help(self, runner: CliRunner) -> None:
        """pulldb-admin users list --help shows options."""
        result = runner.invoke(cli, ["users", "list", "--help"])
        assert_success(result)
        assert_contains(result, "--json")

    def test_users_show_help(self, runner: CliRunner) -> None:
        """pulldb-admin users show --help shows usage."""
        result = runner.invoke(cli, ["users", "show", "--help"])
        assert_success(result)
        assert_contains(result, "USERNAME")

    def test_users_enable_help(self, runner: CliRunner) -> None:
        """pulldb-admin users enable --help shows usage."""
        result = runner.invoke(cli, ["users", "enable", "--help"])
        assert_success(result)
        assert_contains(result, "USERNAME")
