"""
Category 3: Hosts Command Tests

Tests for:
- pulldb-admin hosts list
- pulldb-admin hosts add
- pulldb-admin hosts enable
- pulldb-admin hosts disable
- Output formats (table, JSON)
- Error handling

Test Count: 16 tests
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from pulldb.cli.admin import cli

from .conftest import (
    SAMPLE_DBHOST,
    assert_contains,
    assert_error,
    assert_success,
    assert_valid_json,
    configure_cursor_for_query,
    configure_cursor_for_update,
)


# ---------------------------------------------------------------------------
# Hosts List Command
# ---------------------------------------------------------------------------


class TestHostsList:
    """Tests for hosts list command."""

    def test_hosts_list_basic(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_host_columns: list[str],
        host_row_factory,
    ) -> None:
        """pulldb-admin hosts list shows hosts."""
        rows = [host_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_host_columns)

        result = runner.invoke(cli, ["hosts", "list"])
        assert_success(result)
        assert_contains(result, "HOSTNAME", "MAX_CONCURRENT", "ENABLED")

    def test_hosts_list_empty(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_host_columns: list[str],
    ) -> None:
        """pulldb-admin hosts list with no hosts shows message."""
        configure_cursor_for_query(mock_mysql_pool, [], sample_host_columns)

        result = runner.invoke(cli, ["hosts", "list"])
        assert_success(result)
        assert_contains(result, "No database hosts")

    def test_hosts_list_multiple(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_host_columns: list[str],
        host_row_factory,
    ) -> None:
        """pulldb-admin hosts list shows multiple hosts."""
        rows = [
            host_row_factory(hostname="mysql-stg-01.example.com"),
            host_row_factory(hostname="mysql-stg-02.example.com", max_concurrent=4),
            host_row_factory(hostname="mysql-prd-01.example.com", enabled=False),
        ]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_host_columns)

        result = runner.invoke(cli, ["hosts", "list"])
        assert_success(result)
        assert_contains(result, "mysql-stg-01", "mysql-stg-02", "mysql-prd-01")

    def test_hosts_list_json_output(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_host_columns: list[str],
        host_row_factory,
    ) -> None:
        """pulldb-admin hosts list --json outputs JSON."""
        rows = [host_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_host_columns)

        result = runner.invoke(cli, ["hosts", "list", "--json"])
        assert_success(result)
        data = assert_valid_json(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["hostname"] == SAMPLE_DBHOST

    def test_hosts_list_shows_summary(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_host_columns: list[str],
        host_row_factory,
    ) -> None:
        """pulldb-admin hosts list shows enabled count."""
        rows = [
            host_row_factory(enabled=True),
            host_row_factory(hostname="host2.example.com", enabled=False),
        ]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_host_columns)

        result = runner.invoke(cli, ["hosts", "list"])
        assert_success(result)
        assert_contains(result, "Total:", "enabled")


# ---------------------------------------------------------------------------
# Hosts Enable/Disable Commands
# ---------------------------------------------------------------------------


class TestHostsEnableDisable:
    """Tests for hosts enable/disable commands."""

    def test_hosts_enable(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin hosts enable <hostname> enables host."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(cli, ["hosts", "enable", SAMPLE_DBHOST])
        assert_success(result)
        assert_contains(result, "enabled")

    def test_hosts_enable_not_found(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin hosts enable unknown host shows error."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=0)

        result = runner.invoke(cli, ["hosts", "enable", "nonexistent.example.com"])
        assert_error(result)
        assert_contains(result, "not found")

    def test_hosts_disable(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin hosts disable <hostname> disables host."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(cli, ["hosts", "disable", SAMPLE_DBHOST])
        assert_success(result)
        assert_contains(result, "disabled")

    def test_hosts_disable_not_found(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin hosts disable unknown host shows error."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=0)

        result = runner.invoke(cli, ["hosts", "disable", "nonexistent.example.com"])
        assert_error(result)
        assert_contains(result, "not found")


# ---------------------------------------------------------------------------
# Hosts Add Command
# ---------------------------------------------------------------------------


class TestHostsAdd:
    """Tests for hosts add command."""

    def test_hosts_add_basic(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin hosts add <hostname> adds host."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(cli, ["hosts", "add", "new-host.example.com"])
        assert_success(result)
        assert_contains(result, "added")

    def test_hosts_add_with_options(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin hosts add with max-concurrent and credential-ref."""
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(
            cli,
            [
                "hosts", "add", "new-host.example.com",
                "--max-concurrent", "4",
                "--credential-ref", "aws-secretsmanager:/pulldb/mysql/new-host",
            ],
        )
        assert_success(result)
        assert_contains(result, "added")

    def test_hosts_add_duplicate(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin hosts add duplicate shows error."""
        # Simulate duplicate key error
        mock_mysql_pool._mock_cursor.execute.side_effect = Exception(
            "Duplicate entry 'existing-host' for key 'PRIMARY'"
        )

        result = runner.invoke(cli, ["hosts", "add", "existing-host.example.com"])
        assert_error(result)
        assert_contains(result, "already exists")


# ---------------------------------------------------------------------------
# Hosts Help
# ---------------------------------------------------------------------------


class TestHostsHelp:
    """Tests for hosts command help."""

    def test_hosts_list_help(self, runner: CliRunner) -> None:
        """pulldb-admin hosts list --help shows options."""
        result = runner.invoke(cli, ["hosts", "list", "--help"])
        assert_success(result)
        assert_contains(result, "--json")

    def test_hosts_add_help(self, runner: CliRunner) -> None:
        """pulldb-admin hosts add --help shows options."""
        result = runner.invoke(cli, ["hosts", "add", "--help"])
        assert_success(result)
        assert_contains(result, "HOSTNAME", "--max-concurrent", "--credential-ref")

    def test_hosts_enable_help(self, runner: CliRunner) -> None:
        """pulldb-admin hosts enable --help shows usage."""
        result = runner.invoke(cli, ["hosts", "enable", "--help"])
        assert_success(result)
        assert_contains(result, "HOSTNAME")
