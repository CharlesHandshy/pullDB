"""QA CLI Tests for pullDB

CLI command tests using Click's CliRunner with mocked API responses.
Run with: pytest tests/qa/test_cli.py -v -m cli

These tests use mocked HTTP responses to test CLI behavior
without requiring a running service or registered user.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pulldb.cli.main import cli


# ---------------------------------------------------------------------------
# Mock Data
# ---------------------------------------------------------------------------

MOCK_USER_RESPONSE = {
    "user_code": "testuser",
    "is_disabled": False,
    "has_password": True,
}

MOCK_SEARCH_RESPONSE = {
    "customers": ["actionpest", "actionplumbing", "actionelectric"],
}

MOCK_HISTORY_RESPONSE = [
    {
        "job_id": "75777a4c-3dd9-48dd-b39c-62d8b35934da",
        "status": "complete",
        "user_code": "testuser",
        "target": "action_dev",
        "completed_at": "2025-12-15T10:30:00Z",
        "duration_seconds": 125.5,
    },
    {
        "job_id": "8b4c4a3a-1234-5678-abcd-ef0123456789",
        "status": "failed",
        "user_code": "testuser",
        "target": "pest_staging",
        "completed_at": "2025-12-14T09:15:00Z",
        "duration_seconds": 45.2,
        "error": "Database connection timeout",
    },
]

MOCK_EVENTS_RESPONSE = [
    {
        "logged_at": "2025-12-15T10:25:00Z",
        "event_type": "job_started",
        "detail": "Job started for target action_dev",
    },
    {
        "logged_at": "2025-12-15T10:26:30Z",
        "event_type": "discovery_complete",
        "detail": "Found 45 tables, 1.2GB total",
    },
    {
        "logged_at": "2025-12-15T10:28:00Z",
        "event_type": "download_complete",
        "detail": "Downloaded backup from S3",
    },
    {
        "logged_at": "2025-12-15T10:30:00Z",
        "event_type": "job_complete",
        "detail": "Restore completed successfully",
    },
]

MOCK_PROFILE_RESPONSE = {
    "job_id": "75777a4c-3dd9-48dd-b39c-62d8b35934da",
    "total_duration_seconds": 125.5,
    "total_bytes": 1288490188,
    "error": None,
    "phases": {
        "discovery": {"duration_seconds": 5.2, "mbps": None},
        "download": {"duration_seconds": 45.3, "mbps": 28.4},
        "extraction": {"duration_seconds": 12.1, "mbps": 106.5},
        "myloader": {"duration_seconds": 58.4, "mbps": 22.1},
        "post_sql": {"duration_seconds": 2.5, "mbps": None},
        "atomic_rename": {"duration_seconds": 2.0, "mbps": None},
    },
    "phase_breakdown_percent": {
        "discovery": 4.1,
        "download": 36.1,
        "extraction": 9.6,
        "myloader": 46.5,
        "post_sql": 2.0,
        "atomic_rename": 1.6,
    },
}

MOCK_RESOLVE_RESPONSE = {
    "resolved_id": "75777a4c-3dd9-48dd-b39c-62d8b35934da",
    "matches": [],
    "count": 1,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_cli_runner():
    """CLI runner with mocked API responses.
    
    Provides a test runner that mocks HTTP requests so tests
    don't require a running API service or registered user.
    """
    runner = CliRunner()
    
    def run(args, mock_responses=None, **kwargs):
        """Run CLI command with mocked API responses.
        
        Args:
            args: CLI arguments as list
            mock_responses: Dict mapping URL patterns to responses
            **kwargs: Additional args passed to CliRunner.invoke
        """
        if mock_responses is None:
            mock_responses = {}
            
        def mock_get(url, **req_kwargs):
            """Mock requests.get based on URL."""
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            
            # Match URL patterns
            if "/api/users/" in url:
                mock_resp.json.return_value = MOCK_USER_RESPONSE
            elif "/api/customers/search" in url:
                mock_resp.json.return_value = mock_responses.get("search", MOCK_SEARCH_RESPONSE)
            elif "/api/jobs/history" in url:
                mock_resp.json.return_value = mock_responses.get("history", MOCK_HISTORY_RESPONSE)
            elif "/api/jobs/resolve/" in url:
                mock_resp.json.return_value = mock_responses.get("resolve", MOCK_RESOLVE_RESPONSE)
            elif "/events" in url:
                mock_resp.json.return_value = mock_responses.get("events", MOCK_EVENTS_RESPONSE)
            elif "/profile" in url:
                mock_resp.json.return_value = mock_responses.get("profile", MOCK_PROFILE_RESPONSE)
            else:
                mock_resp.json.return_value = {}
                
            return mock_resp
            
        def mock_post(url, **req_kwargs):
            """Mock requests.post based on URL."""
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_responses.get("post", {})
            return mock_resp
            
        # Patch requests module used by CLI
        with patch("pulldb.cli.main.requests_module") as mock_requests:
            mock_requests.get = mock_get
            mock_requests.post = mock_post
            mock_requests.RequestException = Exception
            
            # Also patch auth module's get_calling_username
            with patch("pulldb.cli.main.get_calling_username", return_value="testuser"):
                with patch("pulldb.cli.main._get_calling_username", return_value="testuser"):
                    result = runner.invoke(cli, args, catch_exceptions=False, **kwargs)
                    
        return result
        
    return run


@pytest.fixture
def sample_job_id() -> str:
    """A known job ID for testing."""
    return "75777a4c-3dd9-48dd-b39c-62d8b35934da"


@pytest.fixture
def sample_search_term() -> str:
    """A known search term for testing."""
    return "action"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.cli
class TestCLISearch:
    """CLI search command tests."""

    def test_search_returns_results(self, mock_cli_runner, sample_search_term):
        """Search command returns customer results."""
        result = mock_cli_runner(["search", sample_search_term])
        assert result.exit_code == 0
        assert "Customers matching" in result.output
        assert "customer(s) found" in result.output

    def test_search_with_limit(self, mock_cli_runner, sample_search_term):
        """Search respects limit parameter."""
        result = mock_cli_runner(["search", sample_search_term, "limit=5"])
        assert result.exit_code == 0
        # Should show customers from mock response
        assert "actionpest" in result.output or "Customers matching" in result.output


@pytest.mark.cli
class TestCLIHistory:
    """CLI history command tests."""

    def test_history_shows_jobs(self, mock_cli_runner):
        """History command shows recent jobs."""
        result = mock_cli_runner(["history", "--limit", "5"])
        assert result.exit_code == 0
        # Should show table headers or job information
        assert "STATUS" in result.output or "complete" in result.output
        assert "job(s)" in result.output

    def test_history_with_status_filter(self, mock_cli_runner):
        """History command respects status filter."""
        result = mock_cli_runner(["history", "--status", "failed", "--limit", "3"])
        assert result.exit_code == 0


@pytest.mark.cli
class TestCLIEvents:
    """CLI events command tests."""

    def test_events_shows_log(self, mock_cli_runner, sample_job_id):
        """Events command shows job event log."""
        prefix = sample_job_id[:8]
        result = mock_cli_runner(["events", prefix])
        assert result.exit_code == 0
        assert "Events for job" in result.output
        assert "event(s)" in result.output

    def test_events_shows_event_types(self, mock_cli_runner, sample_job_id):
        """Events command shows event types from log."""
        prefix = sample_job_id[:8]
        result = mock_cli_runner(["events", prefix])
        assert result.exit_code == 0
        # Check for event types from mock data
        assert "job_started" in result.output or "discovery_complete" in result.output


@pytest.mark.cli
class TestCLIProfile:
    """CLI profile command tests."""

    def test_profile_shows_performance(self, mock_cli_runner, sample_job_id):
        """Profile command shows performance breakdown."""
        prefix = sample_job_id[:8]
        result = mock_cli_runner(["profile", prefix])
        assert result.exit_code == 0
        assert "Performance Profile" in result.output
        assert "Phase Breakdown" in result.output

    def test_profile_shows_phases(self, mock_cli_runner, sample_job_id):
        """Profile shows expected phases."""
        prefix = sample_job_id[:8]
        result = mock_cli_runner(["profile", prefix])
        assert result.exit_code == 0
        # Check for phase names from mock data
        output_lower = result.output.lower()
        assert "discovery" in output_lower or "download" in output_lower
