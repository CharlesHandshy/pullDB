"""Tests for restore profiling functionality.

Tests cover:
- RestoreProfiler context manager behavior
- Phase timing and metrics collection
- Profile serialization and parsing
- API endpoint for profile retrieval
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.profiling import (
    PhaseProfile,
    RestorePhase,
    RestoreProfile,
    RestoreProfiler,
    parse_profile_from_event,
)


class TestRestorePhase:
    """Tests for RestorePhase enum."""

    def test_all_phases_defined(self) -> None:
        """All expected restore phases should be defined."""
        expected = {
            "discovery",
            "download",
            "extraction",
            "myloader",
            "post_sql",
            "metadata",
            "atomic_rename",
            "total",
        }
        actual = {p.value for p in RestorePhase}
        assert actual == expected

    def test_phase_string_values(self) -> None:
        """Phases should be string enum members."""
        assert RestorePhase.DOWNLOAD.value == "download"
        assert RestorePhase.MYLOADER.value == "myloader"
        assert RestorePhase.ATOMIC_RENAME.value == "atomic_rename"


class TestPhaseProfile:
    """Tests for PhaseProfile dataclass."""

    def test_phase_profile_creation(self) -> None:
        """PhaseProfile should initialize with required fields."""
        profile = PhaseProfile(
            phase=RestorePhase.DOWNLOAD,
            started_at=datetime.now(UTC),
        )
        assert profile.phase == RestorePhase.DOWNLOAD
        assert profile.completed_at is None
        assert profile.duration_seconds is None
        assert profile.bytes_processed is None

    def test_phase_complete_calculates_duration(self) -> None:
        """complete() should calculate duration from start to end."""
        start = datetime.now(UTC)
        profile = PhaseProfile(phase=RestorePhase.DOWNLOAD, started_at=start)

        # Simulate some work
        time.sleep(0.01)
        profile.complete()

        assert profile.completed_at is not None
        assert profile.duration_seconds is not None
        assert profile.duration_seconds >= 0.01

    def test_phase_complete_with_bytes(self) -> None:
        """complete() with bytes should calculate throughput."""
        start = datetime.now(UTC)
        profile = PhaseProfile(phase=RestorePhase.DOWNLOAD, started_at=start)

        time.sleep(0.01)
        profile.complete(bytes_processed=1_000_000)

        assert profile.bytes_processed == 1_000_000
        assert profile.bytes_per_second is not None
        assert profile.bytes_per_second > 0

    def test_phase_to_dict(self) -> None:
        """to_dict() should produce serializable dictionary."""
        start = datetime.now(UTC)
        profile = PhaseProfile(
            phase=RestorePhase.DOWNLOAD,
            started_at=start,
            metadata={"bucket": "test-bucket"},
        )
        profile.complete(bytes_processed=1_048_576)  # 1 MB

        result = profile.to_dict()

        assert result["phase"] == "download"
        assert "started_at" in result
        assert "completed_at" in result
        assert "duration_seconds" in result
        assert result["bytes_processed"] == 1_048_576
        assert "mbps" in result
        assert result["metadata"]["bucket"] == "test-bucket"


class TestRestoreProfile:
    """Tests for RestoreProfile aggregation."""

    def test_profile_creation(self) -> None:
        """RestoreProfile should initialize with job_id."""
        profile = RestoreProfile(job_id="test-123")

        assert profile.job_id == "test-123"
        assert profile.started_at is not None
        assert profile.completed_at is None
        assert profile.phases == {}

    def test_start_and_complete_phase(self) -> None:
        """start_phase() and complete_phase() should track phases."""
        profile = RestoreProfile(job_id="test-123")

        profile.start_phase(RestorePhase.DOWNLOAD)
        time.sleep(0.01)
        result = profile.complete_phase(RestorePhase.DOWNLOAD, bytes_processed=1000)

        assert RestorePhase.DOWNLOAD in profile.phases
        assert result is not None
        assert result.duration_seconds is not None
        assert profile.total_bytes == 1000

    def test_complete_unstarted_phase_returns_none(self) -> None:
        """complete_phase() on unstarted phase should return None."""
        profile = RestoreProfile(job_id="test-123")

        result = profile.complete_phase(RestorePhase.DOWNLOAD)

        assert result is None

    def test_phase_breakdown_percentage(self) -> None:
        """phase_breakdown should show percentage of total time."""
        profile = RestoreProfile(job_id="test-123")

        # Start multiple phases
        profile.start_phase(RestorePhase.DISCOVERY)
        time.sleep(0.01)
        profile.complete_phase(RestorePhase.DISCOVERY)

        profile.start_phase(RestorePhase.DOWNLOAD)
        time.sleep(0.02)
        profile.complete_phase(RestorePhase.DOWNLOAD)

        profile.complete()

        breakdown = profile.phase_breakdown
        assert "discovery" in breakdown
        assert "download" in breakdown
        # Download took ~2x as long, should be ~67%, discovery ~33%
        assert breakdown["download"] > breakdown["discovery"]

    def test_to_dict_serializable(self) -> None:
        """to_dict() should produce JSON-serializable output."""
        profile = RestoreProfile(job_id="test-123")
        profile.start_phase(RestorePhase.DOWNLOAD)
        profile.complete_phase(RestorePhase.DOWNLOAD, bytes_processed=1000)
        profile.complete()

        result = profile.to_dict()

        # Verify it's JSON serializable
        json_str = json.dumps(result)
        assert "test-123" in json_str
        assert "download" in json_str

    def test_to_event_detail_json(self) -> None:
        """to_event_detail() should produce compact JSON string."""
        profile = RestoreProfile(job_id="test-123")
        profile.complete()

        detail = profile.to_event_detail()

        # Should be valid JSON
        parsed = json.loads(detail)
        assert parsed["job_id"] == "test-123"


class TestRestoreProfiler:
    """Tests for RestoreProfiler context manager."""

    def test_profiler_phase_context_manager(self) -> None:
        """phase() context manager should time the block."""
        profiler = RestoreProfiler(job_id="test-123")

        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            time.sleep(0.01)
            p.metadata["file_count"] = 5

        profiler.complete()

        assert RestorePhase.DOWNLOAD in profiler.profile.phases
        phase = profiler.profile.phases[RestorePhase.DOWNLOAD]
        assert phase.duration_seconds is not None
        assert phase.duration_seconds >= 0.01
        assert phase.metadata["file_count"] == 5

    def test_profiler_disabled_skips_timing(self) -> None:
        """Disabled profiler should not collect data."""
        profiler = RestoreProfiler(job_id="test-123", enabled=False)

        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            p.metadata["test"] = True

        profiler.complete()

        # Should have no phases when disabled
        assert len(profiler.profile.phases) == 0

    def test_profiler_bytes_processed_via_metadata(self) -> None:
        """bytes_processed in metadata should be captured."""
        profiler = RestoreProfiler(job_id="test-123")

        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            p.metadata["bytes_processed"] = 1_000_000

        profiler.complete()

        phase = profiler.profile.phases[RestorePhase.DOWNLOAD]
        assert phase.bytes_processed == 1_000_000

    def test_profiler_multiple_phases(self) -> None:
        """Profiler should handle multiple sequential phases."""
        profiler = RestoreProfiler(job_id="test-123")

        with profiler.phase(RestorePhase.DISCOVERY):
            time.sleep(0.005)

        with profiler.phase(RestorePhase.DOWNLOAD):
            time.sleep(0.005)

        with profiler.phase(RestorePhase.MYLOADER):
            time.sleep(0.005)

        profiler.complete()

        assert len(profiler.profile.phases) == 3
        assert profiler.profile.total_duration_seconds is not None

    def test_profiler_with_error(self) -> None:
        """complete() with error should record error message."""
        profiler = RestoreProfiler(job_id="test-123")

        with profiler.phase(RestorePhase.DOWNLOAD):
            pass

        profiler.complete(error="Download failed: timeout")

        assert profiler.profile.error == "Download failed: timeout"


class TestParseProfileFromEvent:
    """Tests for parse_profile_from_event function."""

    def test_parse_valid_profile(self) -> None:
        """Should parse valid profile JSON from event."""
        profiler = RestoreProfiler(job_id="test-123")

        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            p.metadata["bytes_processed"] = 1000

        profiler.complete()
        event_detail = profiler.profile.to_event_detail()

        # Parse it back
        parsed = parse_profile_from_event(event_detail)

        assert parsed is not None
        assert parsed.job_id == "test-123"
        assert RestorePhase.DOWNLOAD in parsed.phases
        assert parsed.phases[RestorePhase.DOWNLOAD].bytes_processed == 1000

    def test_parse_invalid_json_returns_none(self) -> None:
        """Invalid JSON should return None."""
        result = parse_profile_from_event("not valid json")
        assert result is None

    def test_parse_empty_string_returns_none(self) -> None:
        """Empty string should return None."""
        result = parse_profile_from_event("")
        assert result is None

    def test_parse_minimal_profile(self) -> None:
        """Should handle minimal profile data."""
        minimal = json.dumps(
            {
                "job_id": "test-456",
                "started_at": "2024-01-15T10:00:00+00:00",
                "phases": {},
            }
        )

        parsed = parse_profile_from_event(minimal)

        assert parsed is not None
        assert parsed.job_id == "test-456"
        assert len(parsed.phases) == 0


class TestProfileAPIModels:
    """Tests for profile API response models."""

    def test_phase_profile_response_model(self) -> None:
        """PhaseProfileResponse should have expected fields."""
        from pulldb.api.main import PhaseProfileResponse

        response = PhaseProfileResponse(
            phase="download",
            started_at="2024-01-15T10:00:00+00:00",
            completed_at="2024-01-15T10:01:00+00:00",
            duration_seconds=60.0,
            bytes_processed=1_000_000,
            bytes_per_second=16666.67,
            mbps=0.02,
        )
        assert response.phase == "download"
        assert response.duration_seconds == 60.0
        assert response.mbps == 0.02

    def test_job_profile_response_model(self) -> None:
        """JobProfileResponse should aggregate phase data."""
        from pulldb.api.main import JobProfileResponse, PhaseProfileResponse

        response = JobProfileResponse(
            job_id="test-123",
            started_at="2024-01-15T10:00:00+00:00",
            completed_at="2024-01-15T10:05:00+00:00",
            total_duration_seconds=300.0,
            total_bytes=10_000_000,
            phases={
                "download": PhaseProfileResponse(
                    phase="download",
                    started_at="2024-01-15T10:00:00+00:00",
                    duration_seconds=120.0,
                ),
                "myloader": PhaseProfileResponse(
                    phase="myloader",
                    started_at="2024-01-15T10:02:00+00:00",
                    duration_seconds=180.0,
                ),
            },
            phase_breakdown_percent={"download": 40.0, "myloader": 60.0},
        )
        assert response.job_id == "test-123"
        assert response.total_duration_seconds == 300.0
        assert len(response.phases) == 2
        assert response.phase_breakdown_percent["download"] == 40.0


class TestProfileAPIEndpoint:
    """Tests for GET /api/jobs/{job_id}/profile endpoint."""

    def test_get_job_profile_function(self) -> None:
        """_get_job_profile should parse profile from events."""
        from pulldb.api.main import _get_job_profile

        # Create mock state
        mock_state = MagicMock()

        # Mock job exists
        mock_job = MagicMock()
        mock_job.status = "complete"
        mock_state.job_repo.get_job_by_id.return_value = mock_job

        # Create profile event (event type matches executor's "restore_profile")
        profiler = RestoreProfiler(job_id="test-123")
        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            p.metadata["bytes_processed"] = 1000
        profiler.complete()

        mock_event = MagicMock()
        mock_event.event_type = "restore_profile"
        mock_event.detail = profiler.profile.to_event_detail()

        mock_state.job_repo.get_job_events.return_value = [mock_event]

        # Call the function
        result = _get_job_profile(mock_state, "test-123")

        assert result.job_id == "test-123"
        assert "download" in result.phases

    def test_get_job_profile_not_found(self) -> None:
        """_get_job_profile should raise 404 for missing job."""
        from fastapi import HTTPException
        from pulldb.api.main import _get_job_profile

        mock_state = MagicMock()
        mock_state.job_repo.get_job_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            _get_job_profile(mock_state, "missing-job")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    def test_get_job_profile_no_profile_event(self) -> None:
        """_get_job_profile should raise 404 if no profile event."""
        from fastapi import HTTPException
        from pulldb.api.main import _get_job_profile

        mock_state = MagicMock()
        mock_state.job_repo.get_job_by_id.return_value = MagicMock()
        mock_state.job_repo.get_job_events.return_value = []  # No events

        with pytest.raises(HTTPException) as exc_info:
            _get_job_profile(mock_state, "job-without-profile")

        assert exc_info.value.status_code == 404
        assert "not available" in exc_info.value.detail.lower()


class TestProfileCLI:
    """Tests for pulldb profile CLI command."""

    def test_format_profile_duration(self) -> None:
        """_format_profile_duration should format correctly."""
        from pulldb.cli.main import _format_profile_duration

        assert _format_profile_duration(None) == "-"
        assert _format_profile_duration(0.05) == "50ms"
        assert _format_profile_duration(1.5) == "1.5s"
        assert _format_profile_duration(90) == "1m 30s"
        assert _format_profile_duration(3700) == "1h 1m"

    def test_format_bytes(self) -> None:
        """_format_bytes should format correctly."""
        from pulldb.cli.main import _format_bytes

        assert _format_bytes(100) == "100 B"
        assert _format_bytes(1500) == "1.5 KB"
        assert _format_bytes(1_500_000) == "1.4 MB"
        assert _format_bytes(1_500_000_000) == "1.40 GB"

    def test_profile_cmd_requires_8_char_job_id(self) -> None:
        """profile command should require at least 8 character job ID."""
        from click.testing import CliRunner
        from pulldb.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["profile", "abc"])

        assert result.exit_code != 0
        assert "8 characters" in result.output
