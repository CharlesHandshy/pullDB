"""
QA API Tests for pullDB

Comprehensive API endpoint tests.
Run with: pytest tests/qa/test_api.py -v -m api
"""

import pytest


@pytest.mark.api
class TestJobEndpoints:
    """Job-related API endpoint tests."""

    def test_jobs_search_valid(self, api_client, sample_search_term):
        """Job search with valid term returns results."""
        response = api_client.get("/api/jobs/search", params={"q": sample_search_term})
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "count" in data
        assert "jobs" in data
        assert data["query"] == sample_search_term

    def test_jobs_resolve_valid(self, api_client, sample_job_id):
        """Job resolve with valid prefix returns full ID."""
        prefix = sample_job_id[:8]
        response = api_client.get(f"/api/jobs/resolve/{prefix}")
        assert response.status_code == 200
        data = response.json()
        assert "resolved_id" in data
        assert data["resolved_id"] == sample_job_id

    def test_jobs_resolve_invalid_length(self, api_client):
        """Job resolve with short prefix returns 400."""
        response = api_client.get("/api/jobs/resolve/abc")
        assert response.status_code == 400
        data = response.json()
        assert "at least 8 characters" in data["detail"]

    def test_jobs_events(self, api_client, sample_job_id):
        """Job events returns event list."""
        response = api_client.get(f"/api/jobs/{sample_job_id}/events")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            event = data[0]
            assert "event_type" in event
            assert "logged_at" in event

    def test_jobs_profile(self, api_client, sample_job_id):
        """Job profile returns performance data."""
        response = api_client.get(f"/api/jobs/{sample_job_id}/profile")
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert "phases" in data
        assert "total_duration_seconds" in data


@pytest.mark.api
class TestUserEndpoints:
    """User-related API endpoint tests."""

    def test_user_last_job(self, api_client, sample_user_code):
        """User last job endpoint returns job info."""
        response = api_client.get(f"/api/users/{sample_user_code}/last-job")
        assert response.status_code == 200
        data = response.json()
        assert "found" in data

    def test_my_last_job(self, api_client, sample_user_code):
        """My last job endpoint returns job with user context."""
        response = api_client.get("/api/jobs/my-last", params={"user_code": sample_user_code})
        assert response.status_code == 200
        data = response.json()
        assert "job" in data or "user_code" in data


@pytest.mark.api
class TestAdminEndpoints:
    """Admin API endpoint tests."""

    def test_orphan_databases(self, api_client):
        """Orphan databases scan works."""
        response = api_client.get("/api/admin/orphan-databases")
        assert response.status_code == 200
        data = response.json()
        assert "hosts_scanned" in data
        assert "total_orphans" in data
        assert "reports" in data
        assert isinstance(data["reports"], list)


@pytest.mark.api
class TestJobSubmission:
    """Job submission API tests."""

    def test_submit_job_validation(self, api_client):
        """Job submission validates required fields."""
        response = api_client.post("/api/jobs", json={})
        assert response.status_code == 422
        data = response.json()
        assert "user" in str(data["detail"])

    def test_submit_job_structure(self, api_client):
        """Job submission returns expected structure."""
        # This creates a real job - use with caution
        # response = api_client.post("/api/jobs", json={
        #     "user": "test",
        #     "customer": "qatemplate",
        # })
        # assert response.status_code == 201
        # data = response.json()
        # assert "job_id" in data
        # assert "status" in data
        # assert data["status"] == "queued"
        pytest.skip("Skipping job creation to avoid side effects")
