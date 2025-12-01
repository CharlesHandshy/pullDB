"""
Category 3: User Endpoint Tests

Tests for:
- GET /api/users/{username}
- GET /api/users/{user_code}/last-job
- GET /api/jobs/my-last

Test Count: 12 tests
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from pulldb.domain.models import JobStatus

from .conftest import (
    SAMPLE_JOB_ID,
    SAMPLE_USER_CODE,
    SAMPLE_USERNAME,
    assert_contains,
    assert_error,
    assert_success,
    configure_job_repo,
    configure_user_repo,
)


# ---------------------------------------------------------------------------
# User Lookup
# ---------------------------------------------------------------------------


class TestUserLookup:
    """Tests for user lookup endpoint."""

    def test_get_user_info(
        self, client: TestClient, mock_api_state, sample_user
    ) -> None:
        """GET /api/users/{username} returns user info."""
        configure_user_repo(mock_api_state, user=sample_user)

        response = client.get(f"/api/users/{SAMPLE_USERNAME}")
        data = assert_success(response)
        assert_contains(data, "username", "user_code", "is_admin")
        assert data["username"] == SAMPLE_USERNAME
        assert data["user_code"] == SAMPLE_USER_CODE

    def test_get_user_not_found(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/users/{username} with unknown user returns 404."""
        configure_user_repo(mock_api_state, user=None)

        response = client.get("/api/users/nonexistent")
        assert_error(response, 404)
        assert "not found" in response.json()["detail"].lower()

    def test_get_admin_user(
        self, client: TestClient, mock_api_state, user_factory
    ) -> None:
        """GET /api/users/{username} shows admin status."""
        admin_user = user_factory(is_admin=True)
        configure_user_repo(mock_api_state, user=admin_user)

        response = client.get(f"/api/users/{SAMPLE_USERNAME}")
        data = assert_success(response)
        assert data["is_admin"] is True


# ---------------------------------------------------------------------------
# User Last Job
# ---------------------------------------------------------------------------


class TestUserLastJob:
    """Tests for user's last job endpoint."""

    def test_get_user_last_job_found(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/users/{user_code}/last-job returns job."""
        job = job_factory(status=JobStatus.COMPLETE)
        mock_api_state._mock_job_repo.get_user_last_job.return_value = job

        response = client.get(f"/api/users/{SAMPLE_USER_CODE}/last-job")
        data = assert_success(response)
        assert_contains(data, "job_id", "target", "status", "found")
        assert data["found"] is True
        assert data["job_id"] == SAMPLE_JOB_ID

    def test_get_user_last_job_not_found(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/users/{user_code}/last-job with no jobs."""
        mock_api_state._mock_job_repo.get_user_last_job.return_value = None

        response = client.get(f"/api/users/{SAMPLE_USER_CODE}/last-job")
        data = assert_success(response)
        assert data["found"] is False

    def test_get_user_last_job_with_error(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/users/{user_code}/last-job shows error detail."""
        job = job_factory(
            status=JobStatus.FAILED,
            error_detail="Connection timeout",
        )
        mock_api_state._mock_job_repo.get_user_last_job.return_value = job

        response = client.get(f"/api/users/{SAMPLE_USER_CODE}/last-job")
        data = assert_success(response)
        assert data["error_detail"] == "Connection timeout"


# ---------------------------------------------------------------------------
# My Last Job
# ---------------------------------------------------------------------------


class TestMyLastJob:
    """Tests for my-last job endpoint."""

    def test_get_my_last_job_found(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/jobs/my-last returns job for user."""
        job = job_factory()
        # This uses a different repo method
        mock_api_state._mock_job_repo.get_last_job_by_user_code.return_value = job

        response = client.get(
            "/api/jobs/my-last", params={"user_code": SAMPLE_USER_CODE}
        )
        data = assert_success(response)
        assert_contains(data, "job", "user_code")
        assert data["user_code"] == SAMPLE_USER_CODE

    def test_get_my_last_job_not_found(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/jobs/my-last with no jobs."""
        mock_api_state._mock_job_repo.get_last_job_by_user_code.return_value = None

        response = client.get(
            "/api/jobs/my-last", params={"user_code": SAMPLE_USER_CODE}
        )
        data = assert_success(response)
        assert data["job"] is None

    def test_get_my_last_job_requires_user_code(
        self, client: TestClient
    ) -> None:
        """GET /api/jobs/my-last without user_code returns 422."""
        response = client.get("/api/jobs/my-last")
        assert response.status_code == 422
