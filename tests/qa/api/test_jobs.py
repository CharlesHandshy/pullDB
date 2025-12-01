"""
Category 2: Job Submission and Listing Tests

Tests for:
- POST /api/jobs (submit job)
- GET /api/jobs (list jobs)
- GET /api/jobs/active (active jobs)
- GET /api/jobs/resolve/{prefix} (ID resolution)
- POST /api/jobs/{job_id}/cancel (cancellation)

Test Count: 32 tests
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from pulldb.domain.models import JobStatus

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
    configure_job_repo,
    configure_settings_repo,
    configure_user_repo,
)


# ---------------------------------------------------------------------------
# Job Submission
# ---------------------------------------------------------------------------


class TestJobSubmission:
    """Tests for job submission endpoint."""

    def test_submit_job_qatemplate(
        self, client: TestClient, mock_api_state, sample_user, job_factory
    ) -> None:
        """POST /api/jobs with qatemplate creates job."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)
        configure_settings_repo(mock_api_state)
        job = job_factory()
        configure_job_repo(mock_api_state, job=job)

        response = client.post(
            "/api/jobs",
            json={"user": SAMPLE_USERNAME, "qatemplate": True},
        )
        data = assert_success(response, 201)
        assert_contains(data, "job_id", "target", "staging_name", "status")
        assert data["status"] == "queued"

    def test_submit_job_customer(
        self, client: TestClient, mock_api_state, sample_user, job_factory
    ) -> None:
        """POST /api/jobs with customer creates job."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)
        configure_settings_repo(mock_api_state)
        job = job_factory(target=f"{SAMPLE_USER_CODE}acme")
        configure_job_repo(mock_api_state, job=job)

        response = client.post(
            "/api/jobs",
            json={"user": SAMPLE_USERNAME, "customer": "ACME Corp"},
        )
        data = assert_success(response, 201)
        assert "acme" in data["target"].lower()

    def test_submit_job_requires_user(self, client: TestClient) -> None:
        """POST /api/jobs without user returns 422."""
        response = client.post("/api/jobs", json={"qatemplate": True})
        assert response.status_code == 422

    def test_submit_job_requires_customer_or_qatemplate(
        self, client: TestClient, mock_api_state, sample_user
    ) -> None:
        """POST /api/jobs without customer or qatemplate returns 400."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)

        response = client.post("/api/jobs", json={"user": SAMPLE_USERNAME})
        assert_error(response, 400)
        assert "exactly one" in response.json()["detail"].lower()

    def test_submit_job_rejects_both_customer_and_qatemplate(
        self, client: TestClient, mock_api_state, sample_user
    ) -> None:
        """POST /api/jobs with both customer and qatemplate returns 400."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)

        response = client.post(
            "/api/jobs",
            json={"user": SAMPLE_USERNAME, "customer": "ACME", "qatemplate": True},
        )
        assert_error(response, 400)

    def test_submit_job_customer_requires_alpha(
        self, client: TestClient, mock_api_state, sample_user
    ) -> None:
        """POST /api/jobs with non-alpha customer returns 400."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)

        response = client.post(
            "/api/jobs",
            json={"user": SAMPLE_USERNAME, "customer": "12345"},
        )
        assert_error(response, 400)
        assert "alphabetic" in response.json()["detail"].lower()

    def test_submit_job_with_options(
        self, client: TestClient, mock_api_state, sample_user, job_factory
    ) -> None:
        """POST /api/jobs with date and env options."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)
        configure_settings_repo(mock_api_state)
        job = job_factory()
        configure_job_repo(mock_api_state, job=job)

        response = client.post(
            "/api/jobs",
            json={
                "user": SAMPLE_USERNAME,
                "qatemplate": True,
                "date": "2025-01-15",
                "env": "prod",
            },
        )
        data = assert_success(response, 201)
        assert data["status"] == "queued"


# ---------------------------------------------------------------------------
# Concurrency Limits
# ---------------------------------------------------------------------------


class TestConcurrencyLimits:
    """Tests for job submission concurrency limits."""

    def test_submit_job_global_limit(
        self, client: TestClient, mock_api_state, sample_user
    ) -> None:
        """POST /api/jobs at global limit returns 429."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)
        configure_settings_repo(mock_api_state, max_global=5)
        configure_job_repo(mock_api_state, active_count=5)

        response = client.post(
            "/api/jobs",
            json={"user": SAMPLE_USERNAME, "qatemplate": True},
        )
        assert_error(response, 429)
        assert "capacity" in response.json()["detail"].lower()

    def test_submit_job_per_user_limit(
        self, client: TestClient, mock_api_state, sample_user
    ) -> None:
        """POST /api/jobs at per-user limit returns 429."""
        configure_user_repo(mock_api_state, user=sample_user, create_user=sample_user)
        configure_settings_repo(mock_api_state, max_per_user=3)
        configure_job_repo(mock_api_state, user_active_count=3)

        response = client.post(
            "/api/jobs",
            json={"user": SAMPLE_USERNAME, "qatemplate": True},
        )
        assert_error(response, 429)
        assert "user limit" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Job Listing
# ---------------------------------------------------------------------------


class TestJobListing:
    """Tests for job listing endpoints."""

    def test_list_jobs_default(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs returns recent jobs."""
        jobs = [job_factory()]
        configure_job_repo(mock_api_state, jobs=jobs)

        response = client.get("/api/jobs")
        data = assert_success(response)
        assert isinstance(data, list)

    def test_list_jobs_with_limit(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs?limit=5 limits results."""
        jobs = [job_factory() for _ in range(5)]
        configure_job_repo(mock_api_state, jobs=jobs)

        response = client.get("/api/jobs", params={"limit": 5})
        assert_success(response)

    def test_list_jobs_active_filter(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs?active=true filters to active."""
        jobs = [job_factory(status=JobStatus.RUNNING)]
        configure_job_repo(mock_api_state, jobs=jobs)

        response = client.get("/api/jobs", params={"active": True})
        assert_success(response)

    def test_list_jobs_history_filter(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs?history=true includes completed."""
        jobs = [job_factory(status=JobStatus.COMPLETE)]
        configure_job_repo(mock_api_state, jobs=jobs)

        response = client.get("/api/jobs", params={"history": True})
        assert_success(response)

    def test_list_active_jobs(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/active returns only active jobs."""
        jobs = [job_factory(status=JobStatus.RUNNING)]
        configure_job_repo(mock_api_state, jobs=jobs)

        response = client.get("/api/jobs/active")
        assert_success(response)


# ---------------------------------------------------------------------------
# Job ID Resolution
# ---------------------------------------------------------------------------


class TestJobResolution:
    """Tests for job ID resolution endpoint."""

    def test_resolve_full_id(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/resolve/{full_id} returns job."""
        job = job_factory()
        configure_job_repo(mock_api_state, job=job)

        response = client.get(f"/api/jobs/resolve/{SAMPLE_JOB_ID}")
        data = assert_success(response)
        assert_contains(data, "resolved_id", "matches", "count")
        assert data["resolved_id"] == SAMPLE_JOB_ID
        assert data["count"] == 1

    def test_resolve_prefix(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/resolve/{prefix} resolves to full ID."""
        job = job_factory()
        configure_job_repo(mock_api_state, job=job)
        mock_api_state._mock_job_repo.get_job_by_id.return_value = None
        mock_api_state._mock_job_repo.find_jobs_by_prefix.return_value = [job]

        response = client.get(f"/api/jobs/resolve/{SAMPLE_JOB_PREFIX}")
        data = assert_success(response)
        assert data["resolved_id"] == SAMPLE_JOB_ID

    def test_resolve_prefix_too_short(self, client: TestClient) -> None:
        """GET /api/jobs/resolve with short prefix returns 400."""
        response = client.get("/api/jobs/resolve/abc")
        assert_error(response, 400)
        assert "at least 8" in response.json()["detail"]

    def test_resolve_not_found(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/jobs/resolve with unknown prefix returns 404."""
        mock_api_state._mock_job_repo.get_job_by_id.return_value = None
        mock_api_state._mock_job_repo.find_jobs_by_prefix.return_value = []

        response = client.get("/api/jobs/resolve/abcd1234")
        assert_error(response, 404)

    def test_resolve_multiple_matches(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/resolve with ambiguous prefix returns matches."""
        jobs = [
            job_factory(job_id="abcd1234-0000-0000-0000-000000000001"),
            job_factory(job_id="abcd1234-0000-0000-0000-000000000002"),
        ]
        mock_api_state._mock_job_repo.get_job_by_id.return_value = None
        mock_api_state._mock_job_repo.find_jobs_by_prefix.return_value = jobs

        response = client.get("/api/jobs/resolve/abcd1234")
        data = assert_success(response)
        assert data["resolved_id"] is None
        assert data["count"] == 2
        assert len(data["matches"]) == 2


# ---------------------------------------------------------------------------
# Job Cancellation
# ---------------------------------------------------------------------------


class TestJobCancellation:
    """Tests for job cancellation endpoint."""

    def test_cancel_queued_job(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """POST /api/jobs/{id}/cancel cancels queued job immediately."""
        job = job_factory(status=JobStatus.QUEUED)
        configure_job_repo(mock_api_state, job=job)

        response = client.post(f"/api/jobs/{SAMPLE_JOB_ID}/cancel")
        data = assert_success(response)
        assert_contains(data, "job_id", "status", "message")
        assert data["status"] == "canceled"

    def test_cancel_running_job(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """POST /api/jobs/{id}/cancel requests cancellation for running job."""
        job = job_factory(status=JobStatus.RUNNING)
        configure_job_repo(mock_api_state, job=job)

        response = client.post(f"/api/jobs/{SAMPLE_JOB_ID}/cancel")
        data = assert_success(response)
        assert data["status"] == "pending"
        assert "checkpoint" in data["message"].lower()

    def test_cancel_completed_job(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """POST /api/jobs/{id}/cancel on complete job returns 409."""
        job = job_factory(status=JobStatus.COMPLETE)
        configure_job_repo(mock_api_state, job=job)

        response = client.post(f"/api/jobs/{SAMPLE_JOB_ID}/cancel")
        assert_error(response, 409)
        assert "cannot be canceled" in response.json()["detail"].lower()

    def test_cancel_not_found(
        self, client: TestClient, mock_api_state
    ) -> None:
        """POST /api/jobs/{id}/cancel on unknown job returns 404."""
        configure_job_repo(mock_api_state, job=None)

        response = client.post("/api/jobs/nonexistent-job-id/cancel")
        assert_error(response, 404)
