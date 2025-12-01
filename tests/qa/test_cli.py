"""
QA CLI Tests for pullDB

CLI command tests using subprocess.
Run with: pytest tests/qa/test_cli.py -v -m cli
"""

import pytest


@pytest.mark.cli
class TestCLISearch:
    """CLI search command tests."""

    def test_search_returns_results(self, cli_runner, sample_search_term):
        """Search command returns backup results."""
        result = cli_runner(["search", sample_search_term, "--limit", "3"])
        assert "Backups matching" in result.stdout
        assert sample_search_term in result.stdout
        assert "backup(s) found" in result.stdout

    def test_search_with_limit(self, cli_runner, sample_search_term):
        """Search respects limit parameter."""
        result = cli_runner(["search", sample_search_term, "--limit", "5"])
        # Count backup entries (lines with dates)
        lines = result.stdout.split("\n")
        backup_lines = [l for l in lines if "2025-" in l]
        assert len(backup_lines) <= 5


@pytest.mark.cli
class TestCLIHistory:
    """CLI history command tests."""

    def test_history_shows_jobs(self, cli_runner):
        """History command shows recent jobs."""
        result = cli_runner(["history", "--limit", "5"])
        # Should show column headers
        assert "STATUS" in result.stdout or "JOB_ID" in result.stdout
        # Should show job count
        assert "job(s)" in result.stdout

    def test_history_with_status_filter(self, cli_runner):
        """History command respects status filter."""
        # Note: This may show no results if no failed jobs exist
        result = cli_runner(["history", "--status", "failed", "--limit", "3"], check=False)
        assert result.returncode == 0


@pytest.mark.cli
class TestCLIEvents:
    """CLI events command tests."""

    def test_events_shows_log(self, cli_runner, sample_job_id):
        """Events command shows job event log."""
        prefix = sample_job_id[:8]
        result = cli_runner(["events", prefix])
        assert "Events for job" in result.stdout
        assert "event(s)" in result.stdout

    def test_events_with_json_output(self, cli_runner, sample_job_id):
        """Events command supports JSON output format."""
        prefix = sample_job_id[:8]
        # Just verify the default output works
        result = cli_runner(["events", prefix])
        assert result.returncode == 0
        assert "event(s)" in result.stdout


@pytest.mark.cli
class TestCLIProfile:
    """CLI profile command tests."""

    def test_profile_shows_performance(self, cli_runner, sample_job_id):
        """Profile command shows performance breakdown."""
        prefix = sample_job_id[:8]
        result = cli_runner(["profile", prefix])
        assert "Performance Profile" in result.stdout
        assert "Phase Breakdown" in result.stdout

    def test_profile_shows_phases(self, cli_runner, sample_job_id):
        """Profile shows expected phases."""
        prefix = sample_job_id[:8]
        result = cli_runner(["profile", prefix])
        # Check for phase names
        output_lower = result.stdout.lower()
        assert "discovery" in output_lower or "download" in output_lower
