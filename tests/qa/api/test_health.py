"""
Category 1: Health and Status Endpoint Tests

Tests for:
- GET /api/health
- GET /api/status

Test Count: 6 tests
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import (
    assert_contains,
    assert_success,
    configure_job_repo,
)


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for health check endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """GET /api/health returns ok status."""
        response = client.get("/api/health")
        data = assert_success(response)
        assert_contains(data, "status")
        assert data["status"] == "ok"

    def test_health_no_auth_required(self, client: TestClient) -> None:
        """Health endpoint doesn't require authentication."""
        response = client.get("/api/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Status Endpoint
# ---------------------------------------------------------------------------


class TestStatus:
    """Tests for status endpoint."""

    def test_status_returns_queue_depth(
        self, client: TestClient, mock_api_state, job_factory
    ) -> None:
        """GET /api/status returns queue depth."""
        jobs = [job_factory(), job_factory(job_id="abcd1234-5678-90ab-cdef-1234567890ab")]
        configure_job_repo(mock_api_state, jobs=jobs)

        response = client.get("/api/status")
        data = assert_success(response)
        assert_contains(data, "queue_depth", "active_restores", "service")
        assert data["queue_depth"] == 2
        assert data["service"] == "api"

    def test_status_empty_queue(
        self, client: TestClient, mock_api_state
    ) -> None:
        """GET /api/status with no active jobs."""
        configure_job_repo(mock_api_state, jobs=[])

        response = client.get("/api/status")
        data = assert_success(response)
        assert data["queue_depth"] == 0
        assert data["active_restores"] == 0
