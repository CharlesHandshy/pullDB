"""
Category 5: Cleanup Command Tests

Tests for:
- pulldb-admin cleanup --dry-run
- pulldb-admin cleanup --execute
- Orphan detection and cleanup
- Host filtering
- Age filtering
- Error handling

Test Count: 14 tests
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from pulldb.cli.admin import cli

from .conftest import (
    SAMPLE_DBHOST,
    SAMPLE_JOB_ID,
    SAMPLE_STAGING_NAME,
    assert_contains,
    assert_error,
    assert_success,
    configure_cursor_for_query,
    configure_cursor_for_update,
)


# ---------------------------------------------------------------------------
# Cleanup Dry Run
# ---------------------------------------------------------------------------


class TestCleanupDryRun:
    """Tests for cleanup --dry-run."""

    def test_cleanup_dry_run_finds_orphans(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
        orphan_row_factory,
    ) -> None:
        """pulldb-admin cleanup --dry-run shows orphaned databases."""
        rows = [orphan_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_orphan_columns)

        result = runner.invoke(cli, ["cleanup", "--dry-run"])
        assert_success(result)
        assert_contains(result, "DRY RUN", "Orphaned", SAMPLE_STAGING_NAME)

    def test_cleanup_dry_run_no_orphans(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
    ) -> None:
        """pulldb-admin cleanup --dry-run with no orphans."""
        configure_cursor_for_query(mock_mysql_pool, [], sample_orphan_columns)

        result = runner.invoke(cli, ["cleanup", "--dry-run"])
        assert_success(result)
        assert_contains(result, "No orphaned")

    def test_cleanup_dry_run_multiple_hosts(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
        orphan_row_factory,
    ) -> None:
        """pulldb-admin cleanup --dry-run groups by host."""
        rows = [
            orphan_row_factory(dbhost="mysql-stg-01.example.com"),
            orphan_row_factory(
                job_id="abcd1234-5678-90ab-cdef-1234567890ab",
                staging_name="test_abcd12345678",
                dbhost="mysql-stg-02.example.com",
            ),
        ]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_orphan_columns)

        result = runner.invoke(cli, ["cleanup", "--dry-run"])
        assert_success(result)
        assert_contains(result, "mysql-stg-01", "mysql-stg-02")

    def test_cleanup_dry_run_shows_summary(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
        orphan_row_factory,
    ) -> None:
        """pulldb-admin cleanup --dry-run shows summary."""
        rows = [orphan_row_factory(), orphan_row_factory(
            job_id="abcd1234-5678-90ab-cdef-1234567890ab",
            staging_name="test_abcd12345678",
        )]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_orphan_columns)

        result = runner.invoke(cli, ["cleanup", "--dry-run"])
        assert_success(result)
        assert_contains(result, "Summary", "Staging databases:", "2")


# ---------------------------------------------------------------------------
# Cleanup Execute
# ---------------------------------------------------------------------------


class TestCleanupExecute:
    """Tests for cleanup --execute."""

    def test_cleanup_execute_cleans_orphans(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
        orphan_row_factory,
    ) -> None:
        """pulldb-admin cleanup --execute cleans orphans."""
        rows = [orphan_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_orphan_columns)
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(cli, ["cleanup", "--execute"])
        assert_success(result)
        assert_contains(result, "Executing cleanup", "Marked cleaned")

    def test_cleanup_execute_no_orphans(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
    ) -> None:
        """pulldb-admin cleanup --execute with nothing to clean."""
        configure_cursor_for_query(mock_mysql_pool, [], sample_orphan_columns)

        result = runner.invoke(cli, ["cleanup", "--execute"])
        assert_success(result)
        assert_contains(result, "No orphaned")

    def test_cleanup_execute_shows_results(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
        orphan_row_factory,
    ) -> None:
        """pulldb-admin cleanup --execute shows cleaned count."""
        rows = [
            orphan_row_factory(),
            orphan_row_factory(
                job_id="abcd1234-5678-90ab-cdef-1234567890ab",
                staging_name="test_abcd12345678",
            ),
        ]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_orphan_columns)
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(cli, ["cleanup", "--execute"])
        assert_success(result)
        assert_contains(result, "Cleanup Complete", "Cleaned:")


# ---------------------------------------------------------------------------
# Cleanup Options
# ---------------------------------------------------------------------------


class TestCleanupOptions:
    """Tests for cleanup command options."""

    def test_cleanup_requires_mode(self, runner: CliRunner) -> None:
        """pulldb-admin cleanup without --dry-run or --execute errors."""
        result = runner.invoke(cli, ["cleanup"])
        assert_error(result, 2)
        assert_contains(result, "--dry-run", "--execute")

    def test_cleanup_mutually_exclusive(self, runner: CliRunner) -> None:
        """pulldb-admin cleanup --dry-run --execute errors."""
        result = runner.invoke(cli, ["cleanup", "--dry-run", "--execute"])
        assert_error(result, 2)

    def test_cleanup_dbhost_filter(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
        orphan_row_factory,
    ) -> None:
        """pulldb-admin cleanup --dbhost filters by host."""
        rows = [orphan_row_factory(dbhost=SAMPLE_DBHOST)]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_orphan_columns)

        result = runner.invoke(
            cli, ["cleanup", "--dry-run", "--dbhost", SAMPLE_DBHOST]
        )
        assert_success(result)

    def test_cleanup_older_than_filter(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_orphan_columns: list[str],
        orphan_row_factory,
    ) -> None:
        """pulldb-admin cleanup --older-than filters by age."""
        rows = [orphan_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_orphan_columns)

        result = runner.invoke(cli, ["cleanup", "--dry-run", "--older-than", "48"])
        assert_success(result)


# ---------------------------------------------------------------------------
# Cleanup Help
# ---------------------------------------------------------------------------


class TestCleanupHelp:
    """Tests for cleanup command help."""

    def test_cleanup_help(self, runner: CliRunner) -> None:
        """pulldb-admin cleanup --help shows options."""
        result = runner.invoke(cli, ["cleanup", "--help"])
        assert_success(result)
        assert_contains(
            result, "--dry-run", "--execute", "--dbhost", "--older-than"
        )
