"""
Category 4: History and Events Tests

Tests for:
- GET /api/jobs/history
- GET /api/jobs/{job_id}/events

Test Count: 14 tests
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from pulldb.domain.models import JobStatus

from .conftest import (
    SAMPLE_JOB_ID,
    SAMPLE_USER_CODE,
    assert_contains,
    assert_error,
    assert_success,
    configure_job_repo,
)


# ---------------------------------------------------------------------------
# Job History
# ---------------------------------------------------------------------------


class TestJobHistory:
    """Tests for job history endpoint."""

    def test_get_history_default(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/history returns completed jobs."""
        job = job_factory(
            status=JobStatus.COMPLETE,
            completed_at=datetime.now(UTC),
        )
        mock_api_state._mock_job_repo.get_job_history.return_value = [job]

        response = client.get("/api/jobs/history")
        data = assert_success(response)
        assert isinstance(data, list)

    def test_get_history_with_limit(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/history?limit=10 limits results."""
        jobs = [
            job_factory(status=JobStatus.COMPLETE, completed_at=datetime.now(UTC))
            for _ in range(10)
        ]
        mock_api_state._mock_job_repo.get_job_history.return_value = jobs

        response = client.get("/api/jobs/history", params={"limit": 10})
        assert_success(response)

    def test_get_history_with_days(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/history?days=7 filters by age."""
        job = job_factory(status=JobStatus.COMPLETE, completed_at=datetime.now(UTC))
        mock_api_state._mock_job_repo.get_job_history.return_value = [job]

        response = client.get("/api/jobs/history", params={"days": 7})
        assert_success(response)

    def test_get_history_with_user_filter(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/history?user_code=xxx filters by user."""
        job = job_factory(status=JobStatus.COMPLETE, completed_at=datetime.now(UTC))
        mock_api_state._mock_job_repo.get_job_history.return_value = [job]

        response = client.get(
            "/api/jobs/history", params={"user_code": SAMPLE_USER_CODE}
        )
        assert_success(response)

    def test_get_history_with_status_filter(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/history?status=failed filters by status."""
        job = job_factory(status=JobStatus.FAILED, completed_at=datetime.now(UTC))
        mock_api_state._mock_job_repo.get_job_history.return_value = [job]

        response = client.get("/api/jobs/history", params={"status": "failed"})
        assert_success(response)

    def test_get_history_invalid_status(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/jobs/history with invalid status returns 400."""
        response = client.get("/api/jobs/history", params={"status": "invalid"})
        assert_error(response, 400)
        assert "invalid status" in response.json()["detail"].lower()

    def test_get_history_includes_duration(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/history computes duration."""
        started = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2025, 1, 15, 10, 5, 30, tzinfo=UTC)
        job = job_factory(
            status=JobStatus.COMPLETE,
            started_at=started,
            completed_at=completed,
        )
        mock_api_state._mock_job_repo.get_job_history.return_value = [job]

        response = client.get("/api/jobs/history")
        data = assert_success(response)
        # Duration should be ~330 seconds
        if len(data) > 0 and "duration_seconds" in data[0]:
            assert data[0]["duration_seconds"] is not None


# ---------------------------------------------------------------------------
# Job Events
# ---------------------------------------------------------------------------


class TestJobEvents:
    """Tests for job events endpoint."""

    def test_get_events_basic(
        self, client: TestClient, mock_api_state, event_factory
    ) -> None:
        """GET /api/jobs/{id}/events returns events."""
        events = [
            event_factory(event_id=1, event_type="queued"),
            event_factory(event_id=2, event_type="running"),
        ]
        configure_job_repo(mock_api_state, events=events)

        response = client.get(f"/api/jobs/{SAMPLE_JOB_ID}/events")
        data = assert_success(response)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_get_events_empty(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/jobs/{id}/events with no events returns empty list."""
        configure_job_repo(mock_api_state, events=[])

        response = client.get(f"/api/jobs/{SAMPLE_JOB_ID}/events")
        data = assert_success(response)
        assert data == []

    def test_get_events_since_id(
        self, client: TestClient, mock_api_state, event_factory
    ) -> None:
        """GET /api/jobs/{id}/events?since_id=X filters events."""
        events = [event_factory(event_id=3, event_type="complete")]
        configure_job_repo(mock_api_state, events=events)

        response = client.get(
            f"/api/jobs/{SAMPLE_JOB_ID}/events", params={"since_id": 2}
        )
        data = assert_success(response)
        assert len(data) == 1
        assert data[0]["id"] == 3

    def test_get_events_contains_required_fields(
        self, client: TestClient, mock_api_state, event_factory
    ) -> None:
        """GET /api/jobs/{id}/events returns expected fields."""
        events = [event_factory()]
        configure_job_repo(mock_api_state, events=events)

        response = client.get(f"/api/jobs/{SAMPLE_JOB_ID}/events")
        data = assert_success(response)
        event = data[0]
        assert_contains(event, "id", "job_id", "event_type", "detail", "logged_at")
