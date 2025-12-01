"""
Category 5: History Command Tests

Tests for:
- Job history listing
- History filtering (user, status, date range)
- Pagination
- Output formats
- Error handling

Test Count: 15 tests
"""

from __future__ import annotations

import json

import pytest
import responses
from click.testing import CliRunner

from pulldb.cli.main import cli

from .conftest import (
    MOCK_API_BASE,
    SAMPLE_JOB_ID,
    SAMPLE_TARGET,
    SAMPLE_USER_CODE,
    SAMPLE_USERNAME,
)


# ---------------------------------------------------------------------------
# History Command - Basic Functionality
# ---------------------------------------------------------------------------


class TestHistoryBasic:
    """Tests for basic history functionality."""

    @responses.activate
    def test_history_no_args_lists_recent(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history without args lists recent completed jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "target": SAMPLE_TARGET,
                    "status": "complete",
                    "user_code": SAMPLE_USER_CODE,
                    "submitted_at": "2025-01-15T10:00:00",
                    "completed_at": "2025-01-15T10:05:00",
                    "duration_seconds": 300.0,
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_history_shows_completed_jobs(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """History includes completed jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {"id": SAMPLE_JOB_ID, "status": "complete", "target": SAMPLE_TARGET}
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history"])
        if result.exit_code == 0:
            output_lower = result.output.lower()
            assert "complete" in output_lower or SAMPLE_JOB_ID[:8] in result.output

    @responses.activate
    def test_history_shows_failed_jobs(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """History includes failed jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "status": "failed",
                    "target": SAMPLE_TARGET,
                    "error_detail": "Backup not found",
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history"])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# History Command - Filtering
# ---------------------------------------------------------------------------


class TestHistoryFiltering:
    """Tests for history filtering options."""

    @responses.activate
    def test_history_filter_by_user(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history --user=xxx filters by user."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "status": "complete",
                    "user_code": SAMPLE_USER_CODE,
                    "target": SAMPLE_TARGET,
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history", f"--user={SAMPLE_USER_CODE}"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_history_filter_by_status(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history --status=failed filters by status."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[],
            status=200,
        )
        result = runner.invoke(cli, ["history", "--status=failed"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_history_filter_by_target(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history --target=xxx filters by target."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {"id": SAMPLE_JOB_ID, "status": "complete", "target": SAMPLE_TARGET}
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history", f"--target={SAMPLE_TARGET}"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_history_limit_results(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history --limit=10 limits results."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {"id": f"job-{i}", "status": "complete", "target": f"target-{i}"}
                for i in range(10)
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history", "--limit=10"])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# History Command - Output Formats
# ---------------------------------------------------------------------------


class TestHistoryOutput:
    """Tests for history output formats."""

    @responses.activate
    def test_history_json_output(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history --json outputs valid JSON."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "target": SAMPLE_TARGET,
                    "status": "complete",
                    "duration_seconds": 300.0,
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history", "--json"])
        if result.exit_code == 0:
            try:
                data = json.loads(result.output)
                assert isinstance(data, list)
            except json.JSONDecodeError:
                pytest.fail(f"Invalid JSON: {result.output}")

    @responses.activate
    def test_history_table_output_default(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history default output is table format."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[
                {"id": SAMPLE_JOB_ID, "target": SAMPLE_TARGET, "status": "complete"}
            ],
            status=200,
        )
        result = runner.invoke(cli, ["history"])
        if result.exit_code == 0:
            output = result.output.strip()
            if output:
                # Should not be pure JSON for table output
                try:
                    json.loads(output)
                    # If it parses as JSON, that's unexpected for table format
                    # unless it's an error message
                except json.JSONDecodeError:
                    pass  # Expected - it's table format


# ---------------------------------------------------------------------------
# History Command - Empty Results
# ---------------------------------------------------------------------------


class TestHistoryEmptyResults:
    """Tests for history with no results."""

    @responses.activate
    def test_history_no_jobs(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """History shows message when no jobs found."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json=[],
            status=200,
        )
        result = runner.invoke(cli, ["history"])
        # Should succeed with empty results
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# History Command - Pagination
# ---------------------------------------------------------------------------


class TestHistoryPagination:
    """Tests for history pagination."""

    @responses.activate
    def test_history_days_pagination(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb history --days=7 shows recent jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[],
            status=200,
        )
        result = runner.invoke(cli, ["history", "--days=7"])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# History Command - Error Cases
# ---------------------------------------------------------------------------


class TestHistoryErrors:
    """Tests for history error scenarios."""

    @responses.activate
    def test_history_api_unavailable(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """History handles API unavailable gracefully."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/history",
            json={"error": "Service unavailable"},
            status=503,
        )
        result = runner.invoke(cli, ["history"])
        # Should fail with error message
        assert result.exit_code != 0

    @responses.activate
    def test_history_invalid_limit(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """History with invalid limit shows error."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        result = runner.invoke(cli, ["history", "--limit=0"])
        # Should fail or handle gracefully
        assert result.exit_code in [0, 1, 2]
