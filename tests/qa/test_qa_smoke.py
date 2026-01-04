"""
QA Smoke Tests for pullDB

Quick health check tests that validate basic functionality.
Run with: pytest tests/qa/test_smoke.py -v -m smoke

NOTE: API tests require a running server at http://localhost:8000.
These tests are marked with 'integration' and will skip if server is unavailable.
"""

import os

import httpx
import pytest

# Check if API server is available for integration tests
# API runs on port 8080, Web UI runs on port 8000
API_BASE_URL = os.getenv("PULLDB_QA_API_URL", "http://localhost:8080")

def _api_server_available() -> bool:
    """Check if API server is running and accessible."""
    try:
        response = httpx.get(f"{API_BASE_URL}/openapi.json", timeout=2.0)
        return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False

api_server_available = pytest.mark.skipif(
    not _api_server_available(),
    reason=f"API server not available at {API_BASE_URL}"
)


@pytest.mark.smoke
@pytest.mark.integration
@api_server_available
class TestAPIHealth:
    """API health check tests (requires running API server)."""
    
    def test_health_endpoint(self, api_client):
        """API returns healthy status."""
        response = api_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
    
    def test_status_endpoint(self, api_client):
        """API status returns queue metrics."""
        response = api_client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "queue_depth" in data
        assert "active_restores" in data
        assert "service" in data
        assert data["service"] == "api"
    
    def test_openapi_schema(self, api_client):
        """OpenAPI schema is accessible."""
        response = api_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
        assert len(data["paths"]) > 10  # At least 10 endpoints


@pytest.mark.smoke
class TestCLIBasics:
    """CLI basic functionality tests."""
    
    def test_version(self, cli_runner):
        """CLI version command works."""
        result = cli_runner(["--version"])
        assert "pulldb, version" in result.stdout
        # Version should be a valid semver (e.g., 0.2.0)
        import re
        assert re.search(r'\d+\.\d+', result.stdout), "Version should contain major.minor format"
    
    def test_help(self, cli_runner):
        """CLI help command works."""
        result = cli_runner(["--help"])
        assert "restore" in result.stdout
        assert "search" in result.stdout
        assert "status" in result.stdout
        assert "history" in result.stdout
    
    def test_restore_help(self, cli_runner):
        """CLI restore help works."""
        result = cli_runner(["restore", "--help"])
        output_lower = result.stdout.lower()
        # Check for key elements in restore help
        assert "customer" in output_lower or "database" in output_lower
        assert "restore" in output_lower
    
    def test_search_help(self, cli_runner):
        """CLI search help works or indicates registration required."""
        result = cli_runner(["search", "--help"], check=False)
        output_lower = result.stdout.lower()
        # Either shows help content OR registration message (for unregistered users)
        help_terms = ["query", "search", "pattern", "customer"]
        registration_terms = ["register", "account"]
        assert any(term in output_lower for term in help_terms + registration_terms)


@pytest.mark.smoke
@pytest.mark.integration
@api_server_available
class TestAPIEndpoints:
    """API endpoint availability tests (requires running API server)."""
    
    def test_jobs_active(self, api_client):
        """Active jobs endpoint is accessible."""
        response = api_client.get("/api/jobs/active")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_jobs_history(self, api_client):
        """Job history endpoint is accessible."""
        response = api_client.get("/api/jobs/history")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_jobs_search_validation(self, api_client):
        """Job search validates query length."""
        response = api_client.get("/api/jobs/search", params={"q": "ab"})
        assert response.status_code == 422  # Validation error
        data = response.json()
        assert "string_too_short" in str(data)
    
    def test_admin_orphans(self, api_client):
        """Admin orphan databases endpoint requires auth."""
        response = api_client.get("/api/admin/orphan-databases")
        # Admin endpoints require authentication - 401 is expected without auth
        # 200 with valid admin auth would return hosts_scanned and total_orphans
        assert response.status_code in (200, 401), f"Expected 200 (authed) or 401 (unauthed), got {response.status_code}"
        if response.status_code == 200:
            data = response.json()
            assert "hosts_scanned" in data
            assert "total_orphans" in data
