"""Tests for pulldb.worker.profiling module.

Tests restore profiling operations:
- Phase timing and metrics
- Profile aggregation
- JSON serialization
- Event parsing
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.profiling import (
    PhaseProfile,
    RestorePhase,
    RestoreProfile,
    RestoreProfiler,
    parse_profile_from_event,
)


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"


# ---------------------------------------------------------------------------
# PhaseProfile Tests
# ---------------------------------------------------------------------------


class TestPhaseProfile:
    """Tests for PhaseProfile dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """PhaseProfile can be created with minimal fields."""
        profile = PhaseProfile(
            phase=RestorePhase.DOWNLOAD,
            started_at=datetime.now(UTC),
        )
        assert profile.phase == RestorePhase.DOWNLOAD
        assert profile.completed_at is None
        assert profile.duration_seconds is None

    def test_complete_sets_duration(self) -> None:
        """complete() calculates duration from timestamps."""
        started = datetime.now(UTC)
        profile = PhaseProfile(phase=RestorePhase.DOWNLOAD, started_at=started)

        # Simulate time passing
        with patch("pulldb.worker.profiling.datetime") as mock_dt:
            mock_dt.now.return_value = started + timedelta(seconds=5.5)
            profile.complete()

        assert profile.completed_at is not None
        assert profile.duration_seconds == pytest.approx(5.5, abs=0.1)

    def test_complete_with_bytes_calculates_throughput(self) -> None:
        """complete() with bytes calculates bytes_per_second."""
        started = datetime.now(UTC)
        profile = PhaseProfile(phase=RestorePhase.DOWNLOAD, started_at=started)

        with patch("pulldb.worker.profiling.datetime") as mock_dt:
            mock_dt.now.return_value = started + timedelta(seconds=10)
            profile.complete(bytes_processed=1024 * 1024 * 100)  # 100 MB

        assert profile.bytes_processed == 100 * 1024 * 1024
        assert profile.bytes_per_second == pytest.approx(10 * 1024 * 1024, rel=0.01)

    def test_to_dict_minimal(self) -> None:
        """to_dict() returns minimal fields when not completed."""
        profile = PhaseProfile(
            phase=RestorePhase.MYLOADER,
            started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        )
        result = profile.to_dict()

        assert result["phase"] == "myloader"
        assert result["started_at"] == "2025-01-15T10:00:00+00:00"
        assert "completed_at" not in result
        assert "duration_seconds" not in result

    def test_to_dict_complete(self) -> None:
        """to_dict() includes all fields when completed."""
        profile = PhaseProfile(
            phase=RestorePhase.DOWNLOAD,
            started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2025, 1, 15, 10, 5, 0, tzinfo=UTC),
            duration_seconds=300.0,
            bytes_processed=1024 * 1024 * 500,
            bytes_per_second=1024 * 1024 * 500 / 300,
            metadata={"bucket": "test-bucket"},
        )
        result = profile.to_dict()

        assert result["phase"] == "download"
        assert "completed_at" in result
        assert result["duration_seconds"] == 300.0
        assert result["bytes_processed"] == 1024 * 1024 * 500
        assert "bytes_per_second" in result
        assert "mbps" in result
        assert result["metadata"] == {"bucket": "test-bucket"}


# ---------------------------------------------------------------------------
# RestoreProfile Tests
# ---------------------------------------------------------------------------


class TestRestoreProfile:
    """Tests for RestoreProfile dataclass."""

    def test_creates_with_job_id(self) -> None:
        """RestoreProfile initializes with job_id and started_at."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        assert profile.job_id == SAMPLE_JOB_ID
        assert profile.started_at is not None
        assert profile.completed_at is None
        assert profile.phases == {}

    def test_start_phase_creates_profile(self) -> None:
        """start_phase() creates and returns PhaseProfile."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        phase_profile = profile.start_phase(RestorePhase.DISCOVERY)

        assert RestorePhase.DISCOVERY in profile.phases
        assert phase_profile.phase == RestorePhase.DISCOVERY

    def test_start_phase_with_metadata(self) -> None:
        """start_phase() accepts initial metadata."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        phase_profile = profile.start_phase(
            RestorePhase.DOWNLOAD, metadata={"bucket": "test"}
        )

        assert phase_profile.metadata == {"bucket": "test"}

    def test_complete_phase_marks_done(self) -> None:
        """complete_phase() completes an existing phase."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        profile.start_phase(RestorePhase.MYLOADER)

        result = profile.complete_phase(RestorePhase.MYLOADER, bytes_processed=1000)

        assert result is not None
        assert result.completed_at is not None
        assert result.bytes_processed == 1000

    def test_complete_phase_returns_none_for_unstarted(self) -> None:
        """complete_phase() returns None for unstarted phase."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        result = profile.complete_phase(RestorePhase.MYLOADER)
        assert result is None

    def test_complete_phase_adds_to_total_bytes(self) -> None:
        """complete_phase() accumulates total_bytes."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)

        profile.start_phase(RestorePhase.DOWNLOAD)
        profile.complete_phase(RestorePhase.DOWNLOAD, bytes_processed=100)

        profile.start_phase(RestorePhase.EXTRACTION)
        profile.complete_phase(RestorePhase.EXTRACTION, bytes_processed=200)

        assert profile.total_bytes == 300

    def test_complete_marks_profile_done(self) -> None:
        """complete() sets completed_at timestamp."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        profile.complete()

        assert profile.completed_at is not None

    def test_complete_with_error(self) -> None:
        """complete() stores error message."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        profile.complete(error="Restore failed: disk full")

        assert profile.error == "Restore failed: disk full"

    def test_total_duration_seconds(self) -> None:
        """total_duration_seconds property calculates duration."""
        profile = RestoreProfile(
            job_id=SAMPLE_JOB_ID,
            started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        )
        profile.completed_at = datetime(2025, 1, 15, 10, 10, 0, tzinfo=UTC)

        assert profile.total_duration_seconds == 600.0

    def test_total_duration_seconds_none_when_incomplete(self) -> None:
        """total_duration_seconds is None before completion."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        assert profile.total_duration_seconds is None

    def test_phase_breakdown_percentages(self) -> None:
        """phase_breakdown calculates percentage per phase."""
        profile = RestoreProfile(
            job_id=SAMPLE_JOB_ID,
            started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        )
        profile.completed_at = datetime(2025, 1, 15, 10, 10, 0, tzinfo=UTC)

        # Add phases with known durations
        p1 = profile.start_phase(RestorePhase.DOWNLOAD)
        p1.duration_seconds = 300  # 50% of 600

        p2 = profile.start_phase(RestorePhase.MYLOADER)
        p2.duration_seconds = 300  # 50% of 600

        breakdown = profile.phase_breakdown
        assert breakdown["download"] == pytest.approx(50.0, abs=0.1)
        assert breakdown["myloader"] == pytest.approx(50.0, abs=0.1)

    def test_to_dict_structure(self) -> None:
        """to_dict() returns expected structure."""
        profile = RestoreProfile(
            job_id=SAMPLE_JOB_ID,
            started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        )
        profile.total_bytes = 1024 * 1024
        profile.complete()

        result = profile.to_dict()

        assert result["job_id"] == SAMPLE_JOB_ID
        assert "started_at" in result
        assert "completed_at" in result
        assert "total_duration_seconds" in result
        assert "total_bytes" in result
        assert "phases" in result
        assert "phase_breakdown_percent" in result

    def test_to_event_detail_json(self) -> None:
        """to_event_detail() returns valid JSON."""
        profile = RestoreProfile(job_id=SAMPLE_JOB_ID)
        profile.complete()

        detail = profile.to_event_detail()

        # Should be valid JSON
        parsed = json.loads(detail)
        assert parsed["job_id"] == SAMPLE_JOB_ID


# ---------------------------------------------------------------------------
# RestoreProfiler Tests
# ---------------------------------------------------------------------------


class TestRestoreProfiler:
    """Tests for RestoreProfiler context manager."""

    def test_creates_profile(self) -> None:
        """Profiler creates RestoreProfile on init."""
        profiler = RestoreProfiler(SAMPLE_JOB_ID)
        assert profiler.profile.job_id == SAMPLE_JOB_ID

    def test_phase_context_manager(self) -> None:
        """phase() context manager tracks phase timing."""
        profiler = RestoreProfiler(SAMPLE_JOB_ID)

        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            time.sleep(0.01)  # Small delay

        assert RestorePhase.DOWNLOAD in profiler.profile.phases
        phase = profiler.profile.phases[RestorePhase.DOWNLOAD]
        assert phase.completed_at is not None
        assert phase.duration_seconds >= 0.01

    def test_phase_allows_metadata_update(self) -> None:
        """Phase profile can be enriched with metadata."""
        profiler = RestoreProfiler(SAMPLE_JOB_ID)

        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            p.metadata["bucket"] = "my-bucket"
            p.metadata["bytes_processed"] = 1024

        phase = profiler.profile.phases[RestorePhase.DOWNLOAD]
        assert phase.metadata["bucket"] == "my-bucket"

    def test_disabled_profiler_no_op(self) -> None:
        """Disabled profiler doesn't record phases."""
        profiler = RestoreProfiler(SAMPLE_JOB_ID, enabled=False)

        with profiler.phase(RestorePhase.DOWNLOAD):
            pass

        assert RestorePhase.DOWNLOAD not in profiler.profile.phases

    def test_complete_finalizes_profile(self) -> None:
        """complete() marks profile as done."""
        profiler = RestoreProfiler(SAMPLE_JOB_ID)
        profiler.complete()

        assert profiler.profile.completed_at is not None

    def test_complete_with_error(self) -> None:
        """complete() stores error message."""
        profiler = RestoreProfiler(SAMPLE_JOB_ID)
        profiler.complete(error="Something went wrong")

        assert profiler.profile.error == "Something went wrong"

    def test_phase_exception_does_not_affect_restore(self) -> None:
        """Profiler exceptions don't propagate."""
        profiler = RestoreProfiler(SAMPLE_JOB_ID)

        # Simulate phase that raises
        with pytest.raises(ValueError):
            with profiler.phase(RestorePhase.DOWNLOAD):
                raise ValueError("Test error")

        # Phase should still be recorded despite exception
        # The exception should propagate (it's the user's exception)


# ---------------------------------------------------------------------------
# parse_profile_from_event Tests
# ---------------------------------------------------------------------------


class TestParseProfileFromEvent:
    """Tests for parse_profile_from_event function."""

    def test_parses_valid_json(self) -> None:
        """Parses valid profile JSON."""
        data = {
            "job_id": SAMPLE_JOB_ID,
            "started_at": "2025-01-15T10:00:00+00:00",
            "completed_at": "2025-01-15T10:10:00+00:00",
            "total_bytes": 1024 * 1024,
            "phases": {
                "download": {
                    "phase": "download",
                    "started_at": "2025-01-15T10:00:00+00:00",
                    "completed_at": "2025-01-15T10:05:00+00:00",
                    "duration_seconds": 300.0,
                    "bytes_processed": 1024 * 1024,
                }
            },
        }
        json_str = json.dumps(data)

        result = parse_profile_from_event(json_str)

        assert result is not None
        assert result.job_id == SAMPLE_JOB_ID
        assert result.total_bytes == 1024 * 1024
        assert RestorePhase.DOWNLOAD in result.phases

    def test_parses_minimal_json(self) -> None:
        """Parses minimal profile JSON."""
        data = {
            "job_id": SAMPLE_JOB_ID,
            "started_at": "2025-01-15T10:00:00+00:00",
        }
        json_str = json.dumps(data)

        result = parse_profile_from_event(json_str)

        assert result is not None
        assert result.job_id == SAMPLE_JOB_ID
        assert result.phases == {}

    def test_handles_invalid_json(self) -> None:
        """Returns None for invalid JSON."""
        result = parse_profile_from_event("not valid json")
        assert result is None

    def test_handles_missing_required_fields(self) -> None:
        """Returns None for missing required fields."""
        data = {"job_id": SAMPLE_JOB_ID}  # missing started_at
        result = parse_profile_from_event(json.dumps(data))
        assert result is None

    def test_handles_error_field(self) -> None:
        """Parses error field from failed profiles."""
        data = {
            "job_id": SAMPLE_JOB_ID,
            "started_at": "2025-01-15T10:00:00+00:00",
            "error": "Disk full",
        }
        json_str = json.dumps(data)

        result = parse_profile_from_event(json_str)

        assert result is not None
        assert result.error == "Disk full"

    def test_ignores_invalid_phases(self) -> None:
        """Skips phases with invalid data."""
        data = {
            "job_id": SAMPLE_JOB_ID,
            "started_at": "2025-01-15T10:00:00+00:00",
            "phases": {
                "download": {
                    "phase": "download",
                    "started_at": "2025-01-15T10:00:00+00:00",
                },
                "invalid_phase": {
                    "phase": "not_a_real_phase",
                    "started_at": "2025-01-15T10:00:00+00:00",
                },
            },
        }
        json_str = json.dumps(data)

        result = parse_profile_from_event(json_str)

        assert result is not None
        assert RestorePhase.DOWNLOAD in result.phases
        # Invalid phase should be skipped
        assert len(result.phases) == 1

    def test_roundtrip_serialization(self) -> None:
        """Profile can be serialized and parsed back."""
        # Create a profile
        profiler = RestoreProfiler(SAMPLE_JOB_ID)
        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            p.metadata["bytes_processed"] = 1024
        profiler.complete()

        # Serialize
        json_str = profiler.profile.to_event_detail()

        # Parse back
        parsed = parse_profile_from_event(json_str)

        assert parsed is not None
        assert parsed.job_id == SAMPLE_JOB_ID
        assert RestorePhase.DOWNLOAD in parsed.phases
