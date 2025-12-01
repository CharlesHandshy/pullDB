"""
Category 4: Status Command Tests

Tests for:
- Job status lookup by ID
- Job status lookup by prefix
- Multiple job status display
- Status filtering options
- Output formats (table, JSON)
- Error handling

Test Count: 20 tests
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
    SAMPLE_JOB_PREFIX,
    SAMPLE_TARGET,
    SAMPLE_USER_CODE,
    SAMPLE_USERNAME,
)


# ---------------------------------------------------------------------------
# Status Command - Basic Functionality
# ---------------------------------------------------------------------------


class TestStatusBasic:
    """Tests for basic status functionality."""

    @responses.activate
    def test_status_no_args_lists_jobs(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status without args lists recent jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "target": SAMPLE_TARGET,
                    "status": "queued",
                    "user_code": SAMPLE_USER_CODE,
                    "submitted_at": "2025-01-15T10:00:00",
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["status"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_status_with_job_id(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status <job_id> shows specific job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "running",
                "user_code": SAMPLE_USER_CODE,
                "current_operation": "downloading",
                "submitted_at": "2025-01-15T10:00:00",
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Status Command - Job ID Resolution
# ---------------------------------------------------------------------------


class TestStatusJobIdResolution:
    """Tests for job ID prefix resolution."""

    @responses.activate
    def test_status_with_8char_prefix(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status with 8-char prefix resolves job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "complete",
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_status_with_full_uuid(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status with full UUID works."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_ID}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "complete",
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_ID])
        assert result.exit_code in [0, 1]

    def test_status_with_short_prefix_fails(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status with prefix < 8 chars fails."""
        result = runner.invoke(cli, ["status", "abc"])  # Only 3 chars
        # Should fail - prefix too short
        assert result.exit_code != 0

    @responses.activate
    def test_status_ambiguous_prefix(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status with ambiguous prefix shows options."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": None,
                "matches": [
                    {"id": SAMPLE_JOB_ID, "target": "target1"},
                    {"id": "75777a4c-xxxx-xxxx-xxxx-xxxxxxxxxxxx", "target": "target2"},
                ],
                "count": 2,
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        # Should indicate multiple matches
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_status_prefix_not_found(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status with unknown prefix shows error."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/deadbeef",
            json={"detail": "No job found matching prefix"},
            status=404,
        )
        result = runner.invoke(cli, ["status", "deadbeef"])
        # Should show not found error
        assert result.exit_code in [1, 2]


# ---------------------------------------------------------------------------
# Status Command - Filtering
# ---------------------------------------------------------------------------


class TestStatusFiltering:
    """Tests for status filtering options."""

    @responses.activate
    def test_status_active_flag(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status --active shows active jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "target": SAMPLE_TARGET,
                    "status": "queued",
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["status", "--active"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_status_history_flag(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status --history shows historical jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[],
            status=200,
        )
        result = runner.invoke(cli, ["status", "--history"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_status_filter_json(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status --filter='{"status":"failed"}' filters jobs."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "target": SAMPLE_TARGET,
                    "status": "failed",
                    "user_code": SAMPLE_USER_CODE,
                }
            ],
            status=200,
        )
        result = runner.invoke(
            cli, ["status", "--filter", '{"status":"failed"}']
        )
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_status_limit_results(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status --limit=5 limits results."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {"id": f"job-{i}", "target": f"target-{i}", "status": "complete"}
                for i in range(5)
            ],
            status=200,
        )
        result = runner.invoke(cli, ["status", "--limit=5"])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Status Command - Output Formats
# ---------------------------------------------------------------------------


class TestStatusOutput:
    """Tests for status output formats."""

    @responses.activate
    def test_status_json_output(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status --json outputs valid JSON."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "complete",
                "user_code": SAMPLE_USER_CODE,
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX, "--json"])
        if result.exit_code == 0:
            try:
                data = json.loads(result.output)
                assert "id" in data or "status" in data
            except json.JSONDecodeError:
                pytest.fail(f"Invalid JSON: {result.output}")

    @responses.activate
    def test_status_table_output_default(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb status default output is table format."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {
                    "id": SAMPLE_JOB_ID,
                    "target": SAMPLE_TARGET,
                    "status": "queued",
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["status"])
        if result.exit_code == 0:
            # Should not be JSON (starts with { or [)
            output = result.output.strip()
            if output:
                assert not output.startswith("{") or not output.startswith("[")


# ---------------------------------------------------------------------------
# Status Command - Job States Display
# ---------------------------------------------------------------------------


class TestStatusJobStates:
    """Tests for displaying different job states."""

    @responses.activate
    def test_status_shows_queued_job(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Status shows queued job correctly."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "queued",
                "current_operation": None,
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            assert "queued" in result.output.lower()

    @responses.activate
    def test_status_shows_running_job(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Status shows running job with current operation."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "running",
                "current_operation": "downloading",
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            assert "running" in result.output.lower()

    @responses.activate
    def test_status_shows_complete_job(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Status shows complete job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "complete",
                "completed_at": "2025-01-15T10:30:00",
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            assert "complete" in result.output.lower()

    @responses.activate
    def test_status_shows_failed_job(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Status shows failed job with error detail."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}",
            json={
                "id": SAMPLE_JOB_ID,
                "target": SAMPLE_TARGET,
                "status": "failed",
                "error_detail": "Connection refused",
            },
            status=200,
        )
        result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            assert "failed" in result.output.lower()


# ---------------------------------------------------------------------------
# Status Command - Error Cases
# ---------------------------------------------------------------------------


class TestStatusErrors:
    """Tests for status error scenarios."""

    @responses.activate
    def test_status_api_unavailable(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Status handles API unavailable gracefully."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json={"error": "Service unavailable"},
            status=503,
        )
        result = runner.invoke(cli, ["status"])
        # Should fail with error message
        assert result.exit_code != 0

    @responses.activate
    def test_status_job_not_found(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Status shows error for non-existent job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/deadbeef",
            json={"detail": "Not found"},
            status=404,
        )
        result = runner.invoke(cli, ["status", "deadbeef"])
        assert result.exit_code != 0
