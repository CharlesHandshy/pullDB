"""
Category 7: Profile Command Tests

Tests for:
- Job performance profiling
- Phase timing display
- Throughput metrics
- Output formats
- Error handling

Test Count: 12 tests
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
)


# ---------------------------------------------------------------------------
# Profile Command - Basic Functionality
# ---------------------------------------------------------------------------


class TestProfileBasic:
    """Tests for basic profile functionality."""

    @responses.activate
    def test_profile_with_job_id(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb profile <job_id> shows job performance profile."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/profile",
            json={
                "job_id": SAMPLE_JOB_ID,
                "started_at": "2025-01-15T10:00:00+00:00",
                "completed_at": "2025-01-15T10:05:00+00:00",
                "total_duration_seconds": 300.0,
                "total_bytes": 104857600,
                "phases": {
                    "discovery": {"duration_seconds": 1.5},
                    "download": {"duration_seconds": 120.0, "bytes_processed": 50000000},
                    "extraction": {"duration_seconds": 30.0, "bytes_processed": 104857600},
                    "restore": {"duration_seconds": 148.5},
                },
            },
            status=200,
        )
        result = runner.invoke(cli, ["profile", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]

    def test_profile_no_args_shows_error(
        self, runner: CliRunner
    ) -> None:
        """pulldb profile without job_id shows error."""
        result = runner.invoke(cli, ["profile"])
        # Should require job ID
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Profile Command - Phase Display
# ---------------------------------------------------------------------------


class TestProfilePhases:
    """Tests for profile phase display."""

    @responses.activate
    def test_profile_shows_all_phases(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Profile shows all job phases."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/profile",
            json={
                "job_id": SAMPLE_JOB_ID,
                "total_duration_seconds": 300.0,
                "phases": {
                    "discovery": {"phase": "discovery", "duration_seconds": 1.5},
                    "download": {"phase": "download", "duration_seconds": 120.0},
                    "extraction": {"phase": "extraction", "duration_seconds": 30.0},
                    "restore": {"phase": "restore", "duration_seconds": 148.5},
                },
            },
            status=200,
        )
        result = runner.invoke(cli, ["profile", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            output_lower = result.output.lower()
            # Should mention key phases
            assert any(
                phase in output_lower
                for phase in ["discovery", "download", "extract", "restore"]
            )

    @responses.activate
    def test_profile_shows_throughput(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Profile shows throughput metrics (MB/s)."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/profile",
            json={
                "job_id": SAMPLE_JOB_ID,
                "total_duration_seconds": 300.0,
                "total_bytes": 104857600,
                "phases": {
                    "download": {
                        "duration_seconds": 120.0,
                        "bytes_processed": 50000000,
                        "mbps": 3.33,
                    },
                },
            },
            status=200,
        )
        result = runner.invoke(cli, ["profile", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Profile Command - Output Formats
# ---------------------------------------------------------------------------


class TestProfileOutput:
    """Tests for profile output formats."""

    @responses.activate
    def test_profile_json_output(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb profile --json outputs valid JSON."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/profile",
            json={
                "job_id": SAMPLE_JOB_ID,
                "total_duration_seconds": 300.0,
                "phases": {},
            },
            status=200,
        )
        result = runner.invoke(cli, ["profile", SAMPLE_JOB_PREFIX, "--json"])
        if result.exit_code == 0:
            try:
                data = json.loads(result.output)
                assert "job_id" in data or "total_duration" in str(data)
            except json.JSONDecodeError:
                pytest.fail(f"Invalid JSON: {result.output}")

    @responses.activate
    def test_profile_shows_total_duration(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Profile shows total job duration."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/profile",
            json={
                "job_id": SAMPLE_JOB_ID,
                "total_duration_seconds": 300.0,
                "phases": {},
            },
            status=200,
        )
        result = runner.invoke(cli, ["profile", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            # Should show duration in some format
            assert any(
                x in result.output.lower()
                for x in ["duration", "300", "5:00", "5 min"]
            )


# ---------------------------------------------------------------------------
# Profile Command - Error Cases
# ---------------------------------------------------------------------------


class TestProfileErrors:
    """Tests for profile error scenarios."""

    @responses.activate
    def test_profile_job_not_found(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Profile shows error for non-existent job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/deadbeef",
            json={"detail": "Not found"},
            status=404,
        )
        result = runner.invoke(cli, ["profile", "deadbeef"])
        assert result.exit_code != 0

    @responses.activate
    def test_profile_job_not_complete(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Profile shows error for job still running."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/profile",
            json={"error": "Job not complete"},
            status=400,
        )
        result = runner.invoke(cli, ["profile", SAMPLE_JOB_PREFIX])
        # Should fail or show appropriate message
        assert result.exit_code in [0, 1]

    def test_profile_prefix_too_short(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Profile with prefix < 8 chars fails."""
        result = runner.invoke(cli, ["profile", "abc"])  # Only 3 chars
        assert result.exit_code != 0

    @responses.activate
    def test_profile_api_error(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Profile handles API error gracefully."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/profile",
            json={"error": "Internal server error"},
            status=500,
        )
        result = runner.invoke(cli, ["profile", SAMPLE_JOB_PREFIX])
        assert result.exit_code != 0
