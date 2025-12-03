"""
QA Smoke Tests for pullDB

Quick health check tests that validate basic functionality.
Run with: pytest tests/qa/test_smoke.py -v -m smoke
"""

import pytest


@pytest.mark.smoke
class TestAPIHealth:
    """API health check tests."""
    
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
        assert "0.0" in result.stdout  # Version format
    
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
        assert "user" in result.stdout.lower()
        assert "customer" in result.stdout.lower()
    
    def test_search_help(self, cli_runner):
        """CLI search help works."""
        result = cli_runner(["search", "--help"])
        assert "prefix" in result.stdout.lower() or "search" in result.stdout.lower()


@pytest.mark.smoke
class TestAPIEndpoints:
    """API endpoint availability tests."""
    
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
        """Admin orphan databases endpoint works."""
        response = api_client.get("/api/admin/orphan-databases")
        assert response.status_code == 200
        data = response.json()
        assert "hosts_scanned" in data
        assert "total_orphans" in data
