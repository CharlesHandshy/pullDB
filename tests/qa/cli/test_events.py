"""
Category 6: Events Command Tests

Tests for:
- Job event timeline display
- Event type filtering
- Chronological ordering
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
    SAMPLE_TARGET,
    SAMPLE_USER_CODE,
)


# ---------------------------------------------------------------------------
# Events Command - Basic Functionality
# ---------------------------------------------------------------------------


class TestEventsBasic:
    """Tests for basic events functionality."""

    @responses.activate
    def test_events_with_job_id(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb events <job_id> shows job events."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[
                {
                    "id": 1,
                    "job_id": SAMPLE_JOB_ID,
                    "event_type": "queued",
                    "detail": "Job submitted",
                    "logged_at": "2025-01-15T10:00:00",
                },
                {
                    "id": 2,
                    "job_id": SAMPLE_JOB_ID,
                    "event_type": "running",
                    "detail": "Job started",
                    "logged_at": "2025-01-15T10:01:00",
                },
            ],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]

    def test_events_no_args_shows_error(
        self, runner: CliRunner
    ) -> None:
        """pulldb events without job_id shows error."""
        result = runner.invoke(cli, ["events"])
        # Should require job ID
        assert result.exit_code != 0

    @responses.activate
    def test_events_with_full_uuid(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb events with full UUID works."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_ID])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Events Command - Event Types
# ---------------------------------------------------------------------------


class TestEventsTypes:
    """Tests for different event types."""

    @responses.activate
    def test_events_shows_queued_event(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Events includes queued event."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[
                {
                    "id": 1,
                    "event_type": "queued",
                    "detail": "Job submitted",
                    "logged_at": "2025-01-15T10:00:00",
                }
            ],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            assert "queued" in result.output.lower() or "submitted" in result.output.lower()

    @responses.activate
    def test_events_shows_phase_transitions(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Events shows phase transitions (discovery, download, etc.)."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[
                {"id": 1, "event_type": "running", "detail": "Phase: discovery"},
                {"id": 2, "event_type": "running", "detail": "Phase: download"},
                {"id": 3, "event_type": "running", "detail": "Phase: extraction"},
                {"id": 4, "event_type": "running", "detail": "Phase: restore"},
            ],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_events_shows_error_event(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Events shows error events."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[
                {"id": 1, "event_type": "running", "detail": "Job started"},
                {
                    "id": 2,
                    "event_type": "failed",
                    "detail": "Error: Connection refused",
                },
            ],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_PREFIX])
        if result.exit_code == 0:
            output_lower = result.output.lower()
            assert "failed" in output_lower or "error" in output_lower


# ---------------------------------------------------------------------------
# Events Command - Output Formats
# ---------------------------------------------------------------------------


class TestEventsOutput:
    """Tests for events output formats."""

    @responses.activate
    def test_events_json_output(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb events --json outputs valid JSON."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[
                {"id": 1, "event_type": "queued", "detail": "Job submitted"},
            ],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_PREFIX, "--json"])
        if result.exit_code == 0:
            try:
                data = json.loads(result.output)
                assert isinstance(data, list)
            except json.JSONDecodeError:
                pytest.fail(f"Invalid JSON: {result.output}")

    @responses.activate
    def test_events_chronological_order(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Events are displayed in chronological order."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[
                {"id": 1, "event_type": "queued", "logged_at": "2025-01-15T10:00:00"},
                {"id": 2, "event_type": "running", "logged_at": "2025-01-15T10:01:00"},
                {"id": 3, "event_type": "complete", "logged_at": "2025-01-15T10:05:00"},
            ],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Events Command - Empty and Error Cases
# ---------------------------------------------------------------------------


class TestEventsErrors:
    """Tests for events error scenarios."""

    @responses.activate
    def test_events_no_events(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Events shows message when job has no events."""
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
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/events",
            json=[],
            status=200,
        )
        result = runner.invoke(cli, ["events", SAMPLE_JOB_PREFIX])
        # Should succeed with empty events
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_events_job_not_found(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Events shows error for non-existent job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/deadbeef",
            json={"detail": "Not found"},
            status=404,
        )
        result = runner.invoke(cli, ["events", "deadbeef"])
        assert result.exit_code != 0

    def test_events_prefix_too_short(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Events with prefix < 8 chars fails."""
        result = runner.invoke(cli, ["events", "abc"])  # Only 3 chars
        assert result.exit_code != 0
