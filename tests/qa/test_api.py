"""
QA API Tests for pullDB

Comprehensive API endpoint tests.
Run with: pytest tests/qa/test_api.py -v -m api

Note: Most API endpoints require authentication. Tests use either:
- authenticated_api_client: For testing against live server with HMAC auth
- api_client_with_mocks: For isolated testing with mocked dependencies

Set PULLDB_QA_API_KEY and PULLDB_QA_API_SECRET to match the server's
API key configuration for authenticated tests.
"""

import pytest


@pytest.mark.api
class TestJobEndpoints:
    """Job-related API endpoint tests."""

    def test_jobs_search_valid(self, authenticated_api_client, sample_search_term):
        """Job search with valid term returns results (requires auth)."""
        response = authenticated_api_client.get("/api/jobs/search", params={"q": sample_search_term})
        # Accept 401 if API key not configured on server
        if response.status_code == 401:
            pytest.skip("API authentication not configured - set PULLDB_QA_API_KEY/SECRET")
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "count" in data
        assert "jobs" in data
        assert data["query"] == sample_search_term

    def test_jobs_resolve_valid(self, api_client_with_mocks, sample_job_id):
        """Job resolve with valid prefix returns 200 with mocked data."""
        prefix = sample_job_id[:8]
        response = api_client_with_mocks.get(f"/api/jobs/resolve/{prefix}")
        assert response.status_code == 200
        data = response.json()
        # Response should have standard structure
        assert "resolved_id" in data
        assert "matches" in data
        assert "count" in data
        assert data["count"] >= 1

    def test_jobs_resolve_invalid_length(self, authenticated_api_client):
        """Job resolve with short prefix returns 400 (after auth)."""
        response = authenticated_api_client.get("/api/jobs/resolve/abc")
        # Accept 401 if API key not configured
        if response.status_code == 401:
            pytest.skip("API authentication not configured - set PULLDB_QA_API_KEY/SECRET")
        assert response.status_code == 400
        data = response.json()
        assert "at least 8 characters" in data["detail"]

    def test_jobs_events(self, authenticated_api_client, sample_job_id):
        """Job events returns event list (requires auth)."""
        response = authenticated_api_client.get(f"/api/jobs/{sample_job_id}/events")
        # Accept 401 if API key not configured
        if response.status_code == 401:
            pytest.skip("API authentication not configured - set PULLDB_QA_API_KEY/SECRET")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            event = data[0]
            assert "event_type" in event
            assert "logged_at" in event

    def test_jobs_profile(self, api_client_with_mocks, sample_job_id):
        """Job profile returns performance data with mocked data."""
        response = api_client_with_mocks.get(f"/api/jobs/{sample_job_id}/profile")
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert "phases" in data
        assert "total_duration_seconds" in data


@pytest.mark.api
class TestUserEndpoints:
    """User-related API endpoint tests."""

    def test_user_last_job(self, authenticated_api_client, sample_user_code):
        """User last job endpoint returns job info (requires auth)."""
        response = authenticated_api_client.get(f"/api/users/{sample_user_code}/last-job")
        # Accept 401 if API key not configured
        if response.status_code == 401:
            pytest.skip("API authentication not configured - set PULLDB_QA_API_KEY/SECRET")
        assert response.status_code == 200
        data = response.json()
        assert "found" in data

    def test_my_last_job(self, authenticated_api_client, sample_user_code):
        """My last job endpoint returns job with user context (requires auth)."""
        response = authenticated_api_client.get("/api/jobs/my-last", params={"user_code": sample_user_code})
        # Accept 401 if API key not configured
        if response.status_code == 401:
            pytest.skip("API authentication not configured - set PULLDB_QA_API_KEY/SECRET")
        assert response.status_code == 200
        data = response.json()
        assert "job" in data or "user_code" in data


@pytest.mark.api
class TestAdminEndpoints:
    """Admin API endpoint tests."""

    def test_orphan_databases(self, authenticated_api_client):
        """Orphan databases scan requires admin authentication."""
        response = authenticated_api_client.get("/api/admin/orphan-databases")
        # Admin endpoints require authentication - 401 is expected without proper admin auth
        if response.status_code == 401:
            pytest.skip("Admin endpoint requires admin authentication")
        if response.status_code == 403:
            pytest.skip("Admin endpoint requires admin role")
        # If auth passed, verify response structure
        assert response.status_code == 200
        data = response.json()
        assert "hosts_scanned" in data
        assert "total_orphans" in data
        assert "reports" in data
        assert isinstance(data["reports"], list)


@pytest.mark.api
class TestJobSubmission:
    """Job submission API tests."""

    def test_submit_job_validation(self, authenticated_api_client):
        """Job submission validates required fields (after auth)."""
        response = authenticated_api_client.post("/api/jobs", json={})
        # Accept 401 if API key not configured
        if response.status_code == 401:
            pytest.skip("API authentication not configured - set PULLDB_QA_API_KEY/SECRET")
        assert response.status_code == 422
        data = response.json()
        assert "user" in str(data["detail"])

    def test_submit_job_structure(self, authenticated_api_client):
        """Job submission returns expected structure."""
        # This creates a real job - use with caution
        # response = authenticated_api_client.post("/api/jobs", json={
        #     "user": "test",
        #     "customer": "qatemplate",
        # })
        # assert response.status_code == 201
        # data = response.json()
        # assert "job_id" in data
        # assert "status" in data
        # assert data["status"] == "queued"
        pytest.skip("Skipping job creation to avoid side effects")


@pytest.mark.api
class TestPublicEndpoints:
    """Tests for endpoints that should work without authentication."""

    def test_health_endpoint(self, api_client):
        """Health endpoint is always accessible."""
        response = api_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_openapi_schema(self, api_client):
        """OpenAPI schema is publicly accessible."""
        response = api_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data

    def test_swagger_docs(self, api_client):
        """Swagger UI is publicly accessible."""
        response = api_client.get("/docs")
        assert response.status_code == 200
