"""
Category 5: Profile Endpoint Tests

Tests for:
- GET /api/jobs/{job_id}/profile

Test Count: 6 tests
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pulldb.domain.models import JobStatus

from .conftest import (
    SAMPLE_JOB_ID,
    assert_contains,
    assert_error,
    assert_success,
    configure_job_repo,
)


# ---------------------------------------------------------------------------
# Job Profile
# ---------------------------------------------------------------------------


class TestJobProfile:
    """Tests for job profile endpoint."""

    def test_get_profile_not_found(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/jobs/{id}/profile for unknown job returns 404."""
        configure_job_repo(mock_api_state, job=None)

        response = client.get(f"/api/jobs/{SAMPLE_JOB_ID}/profile")
        assert_error(response, 404)
        assert "not found" in response.json()["detail"].lower()

    def test_get_profile_no_profile_event(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/{id}/profile without profile event returns 404."""
        job = job_factory(status=JobStatus.COMPLETE)
        configure_job_repo(mock_api_state, job=job, events=[])

        response = client.get(f"/api/jobs/{SAMPLE_JOB_ID}/profile")
        assert_error(response, 404)
        assert "not available" in response.json()["detail"].lower()

    def test_get_profile_with_profile_event(
        self, client: TestClient, mock_api_state, job_factory, event_factory
    ) -> None:
        """GET /api/jobs/{id}/profile with profile event returns data."""
        job = job_factory(status=JobStatus.COMPLETE)
        # Create a profile event with valid JSON
        profile_json = """{
            "job_id": "75777a4c-3dd9-48dd-b39c-62d8b35934da",
            "started_at": "2025-01-15T10:00:00+00:00",
            "completed_at": "2025-01-15T10:05:30+00:00",
            "phases": {
                "download": {
                    "phase": "download",
                    "started_at": "2025-01-15T10:00:00+00:00",
                    "completed_at": "2025-01-15T10:01:00+00:00",
                    "duration_seconds": 60.0,
                    "bytes_processed": 1048576
                }
            }
        }"""
        profile_event = event_factory(
            event_type="restore_profile",
            detail=profile_json,
        )
        configure_job_repo(mock_api_state, job=job, events=[profile_event])

        # Mock the profile parser
        with patch("pulldb.worker.profiling.parse_profile_from_event") as mock_parse:
            mock_profile = MagicMock()
            mock_profile.job_id = SAMPLE_JOB_ID
            mock_profile.started_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
            mock_profile.completed_at = datetime(2025, 1, 15, 10, 5, 30, tzinfo=UTC)
            mock_profile.total_duration_seconds = 330.0
            mock_profile.total_bytes = 1048576
            mock_profile.phases = {}
            mock_profile.phase_breakdown = {}
            mock_profile.error = None
            mock_parse.return_value = mock_profile

            response = client.get(f"/api/jobs/{SAMPLE_JOB_ID}/profile")
            data = assert_success(response)
            assert_contains(
                data, "job_id", "started_at", "total_duration_seconds", "phases"
            )

    def test_get_profile_running_job(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/{id}/profile for running job may not have profile."""
        job = job_factory(status=JobStatus.RUNNING)
        configure_job_repo(mock_api_state, job=job, events=[])

        response = client.get(f"/api/jobs/{SAMPLE_JOB_ID}/profile")
        # Running jobs typically don't have profile events yet
        assert_error(response, 404)
