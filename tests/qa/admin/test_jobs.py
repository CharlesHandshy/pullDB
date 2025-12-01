"""
Category 2: Jobs Command Tests

Tests for:
- pulldb-admin jobs list (with filters)
- pulldb-admin jobs cancel
- Output formats (table, JSON)
- Error handling

Test Count: 20 tests
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pulldb.cli.admin import cli

from .conftest import (
    SAMPLE_DBHOST,
    SAMPLE_JOB_ID,
    SAMPLE_JOB_PREFIX,
    SAMPLE_TARGET,
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
# Jobs List Command
# ---------------------------------------------------------------------------


class TestJobsList:
    """Tests for jobs list command."""

    def test_jobs_list_basic(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list shows jobs."""
        rows = [job_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list"])
        assert_success(result)
        assert_contains(result, "JOB_ID", "STATUS")

    def test_jobs_list_empty(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
    ) -> None:
        """pulldb-admin jobs list with no jobs shows message."""
        configure_cursor_for_query(mock_mysql_pool, [], sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list"])
        assert_success(result)
        assert_contains(result, "No jobs found")

    def test_jobs_list_active_filter(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list --active filters to active jobs."""
        rows = [
            job_row_factory(status="running", current_operation="downloading"),
            job_row_factory(
                job_id="abcd1234-5678-90ab-cdef-1234567890ab",
                status="queued",
            ),
        ]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list", "--active"])
        assert_success(result)
        # Should show active count
        assert "active" in result.output.lower()

    def test_jobs_list_status_filter(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list --status=complete filters by status."""
        rows = [job_row_factory(status="complete")]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list", "--status", "complete"])
        assert_success(result)

    def test_jobs_list_user_filter(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list --user=xxx filters by user."""
        rows = [job_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list", "--user", SAMPLE_USERNAME])
        assert_success(result)

    def test_jobs_list_dbhost_filter(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list --dbhost=xxx filters by host."""
        rows = [job_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list", "--dbhost", SAMPLE_DBHOST])
        assert_success(result)

    def test_jobs_list_limit(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list --limit=5 limits results."""
        rows = [job_row_factory() for _ in range(5)]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list", "--limit", "5"])
        assert_success(result)

    def test_jobs_list_json_output(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list --json outputs JSON."""
        rows = [job_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(cli, ["jobs", "list", "--json"])
        assert_success(result)
        data = assert_valid_json(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == SAMPLE_JOB_ID

    def test_jobs_list_combined_filters(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
        sample_job_columns: list[str],
        job_row_factory,
    ) -> None:
        """pulldb-admin jobs list with multiple filters."""
        rows = [job_row_factory()]
        configure_cursor_for_query(mock_mysql_pool, rows, sample_job_columns)

        result = runner.invoke(
            cli,
            [
                "jobs", "list",
                "--status", "complete",
                "--user", SAMPLE_USERNAME,
                "--limit", "10",
            ],
        )
        assert_success(result)


# ---------------------------------------------------------------------------
# Jobs Cancel Command
# ---------------------------------------------------------------------------


class TestJobsCancel:
    """Tests for jobs cancel command."""

    def test_jobs_cancel_success(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel <job_id> cancels job."""
        # First query: check job status
        configure_cursor_fetchone(mock_mysql_pool, ("running",))
        # Second operation: update
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(
            cli,
            ["jobs", "cancel", SAMPLE_JOB_ID, "--force"],
        )
        assert_success(result)
        assert_contains(result, "Cancellation requested")

    def test_jobs_cancel_with_prefix(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel with prefix cancels job."""
        configure_cursor_fetchone(mock_mysql_pool, ("queued",))
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(
            cli,
            ["jobs", "cancel", SAMPLE_JOB_PREFIX, "--force"],
        )
        assert_success(result)

    def test_jobs_cancel_not_found(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel with unknown ID shows error."""
        configure_cursor_fetchone(mock_mysql_pool, None)

        result = runner.invoke(
            cli,
            ["jobs", "cancel", "nonexistent", "--force"],
        )
        assert_error(result)
        assert_contains(result, "not found")

    def test_jobs_cancel_already_complete(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel on complete job shows error."""
        configure_cursor_fetchone(mock_mysql_pool, ("complete",))

        result = runner.invoke(
            cli,
            ["jobs", "cancel", SAMPLE_JOB_ID, "--force"],
        )
        assert_error(result)
        assert_contains(result, "already complete")

    def test_jobs_cancel_already_failed(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel on failed job shows error."""
        configure_cursor_fetchone(mock_mysql_pool, ("failed",))

        result = runner.invoke(
            cli,
            ["jobs", "cancel", SAMPLE_JOB_ID, "--force"],
        )
        assert_error(result)
        assert_contains(result, "already failed")

    def test_jobs_cancel_already_canceled(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel on canceled job shows error."""
        configure_cursor_fetchone(mock_mysql_pool, ("canceled",))

        result = runner.invoke(
            cli,
            ["jobs", "cancel", SAMPLE_JOB_ID, "--force"],
        )
        assert_error(result)
        assert_contains(result, "already canceled")

    def test_jobs_cancel_confirmation_required(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel without --force prompts."""
        result = runner.invoke(
            cli,
            ["jobs", "cancel", SAMPLE_JOB_ID],
            input="n\n",
        )
        assert_contains(result, "Aborted")

    def test_jobs_cancel_confirmation_accepted(
        self,
        runner: CliRunner,
        mock_mysql_pool: MagicMock,
    ) -> None:
        """pulldb-admin jobs cancel with confirmation cancels."""
        configure_cursor_fetchone(mock_mysql_pool, ("running",))
        configure_cursor_for_update(mock_mysql_pool, rowcount=1)

        result = runner.invoke(
            cli,
            ["jobs", "cancel", SAMPLE_JOB_ID],
            input="y\n",
        )
        assert_success(result)


# ---------------------------------------------------------------------------
# Jobs Command Help
# ---------------------------------------------------------------------------


class TestJobsHelp:
    """Tests for jobs command help."""

    def test_jobs_list_help(self, runner: CliRunner) -> None:
        """pulldb-admin jobs list --help shows options."""
        result = runner.invoke(cli, ["jobs", "list", "--help"])
        assert_success(result)
        assert_contains(result, "--active", "--limit", "--user")

    def test_jobs_cancel_help(self, runner: CliRunner) -> None:
        """pulldb-admin jobs cancel --help shows usage."""
        result = runner.invoke(cli, ["jobs", "cancel", "--help"])
        assert_success(result)
        assert_contains(result, "JOB_ID", "--force")
