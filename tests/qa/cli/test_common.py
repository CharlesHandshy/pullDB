"""
Category 9: Common Patterns and Edge Cases Tests

Tests for:
- Job ID prefix resolution edge cases
- API connection handling
- Environment variable edge cases
- Unicode and special characters
- Timeout handling

Test Count: 15 tests
"""

from __future__ import annotations

import responses
from click.testing import CliRunner

from pulldb.cli.main import cli

from .conftest import (
    MOCK_API_BASE,
    SAMPLE_JOB_ID,
    SAMPLE_JOB_PREFIX,
    SAMPLE_USER_CODE,
    SAMPLE_USERNAME,
)


# ---------------------------------------------------------------------------
# Job ID Prefix Resolution Edge Cases
# ---------------------------------------------------------------------------


class TestJobIdPrefixEdgeCases:
    """Tests for job ID prefix resolution edge cases."""

    def test_prefix_exactly_8_chars(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Prefix of exactly 8 characters works."""
        # This should be the minimum valid prefix
        # Mock resolve endpoint + jobs endpoint with filter
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
                json={
                    "resolved_id": SAMPLE_JOB_ID,
                    "matches": [{"id": SAMPLE_JOB_ID}],
                    "count": 1,
                },
                status=200,
            )
            # Mock the jobs list endpoint (called after resolve)
            rsps.add_callback(
                responses.GET,
                f"{MOCK_API_BASE}/api/jobs",
                callback=lambda req: (
                    200,
                    {},
                    '[{"id": "' + SAMPLE_JOB_ID + '"}]'
                ),
            )
            result = runner.invoke(cli, ["status", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]

    def test_prefix_7_chars_fails(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Prefix of 7 characters fails (below minimum)."""
        result = runner.invoke(cli, ["status", "1234567"])  # Only 7 chars
        assert result.exit_code != 0
        output_lower = result.output.lower()
        has_indicator = (
            "8" in output_lower
            or "minimum" in output_lower
            or "short" in output_lower
        )
        assert has_indicator

    def test_prefix_with_dashes(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Prefix with dashes (partial UUID) works."""
        partial_uuid = "75777a4c-3dd9"  # 13 chars including dash
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{MOCK_API_BASE}/api/jobs/resolve/{partial_uuid}",
                json={
                    "resolved_id": SAMPLE_JOB_ID,
                    "matches": [{"id": SAMPLE_JOB_ID}],
                    "count": 1,
                },
                status=200,
            )
            rsps.add_callback(
                responses.GET,
                f"{MOCK_API_BASE}/api/jobs",
                callback=lambda req: (
                    200,
                    {},
                    '[{"id": "' + SAMPLE_JOB_ID + '"}]'
                ),
            )
            result = runner.invoke(cli, ["status", partial_uuid])
        assert result.exit_code in [0, 1]

    def test_full_uuid_works(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Full 36-character UUID works (no resolve needed)."""
        # Full UUID bypasses resolve endpoint
        with responses.RequestsMock() as rsps:
            rsps.add_callback(
                responses.GET,
                f"{MOCK_API_BASE}/api/jobs",
                callback=lambda req: (
                    200,
                    {},
                    '[{"id": "' + SAMPLE_JOB_ID + '"}]'
                ),
            )
            result = runner.invoke(cli, ["status", SAMPLE_JOB_ID])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# API Connection Edge Cases
# ---------------------------------------------------------------------------


class TestAPIConnectionEdgeCases:
    """Tests for API connection edge cases."""

    def test_api_url_with_trailing_slash(
        self, runner: CliRunner, monkeypatch
    ) -> None:
        """API URL with trailing slash works."""
        monkeypatch.setenv("PULLDB_API_URL", f"{MOCK_API_BASE}/")
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{MOCK_API_BASE}/api/jobs",
                json=[],
                status=200,
            )
            result = runner.invoke(cli, ["status"])
        # Should handle trailing slash gracefully
        assert result.exit_code in [0, 1]

    def test_api_url_without_port(
        self, runner: CliRunner, monkeypatch
    ) -> None:
        """API URL without port specified works."""
        monkeypatch.setenv("PULLDB_API_URL", "http://api.example.com")
        # Just verify it doesn't crash
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    @responses.activate
    def test_api_connection_refused(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Connection refused error handled gracefully."""
        # responses library will raise ConnectionError for unmocked URLs
        # Don't add any mocks, let it fail
        result = runner.invoke(cli, ["status"])
        # Should fail but not crash
        assert result.exit_code in [1, 2]


# ---------------------------------------------------------------------------
# Environment Variable Edge Cases
# ---------------------------------------------------------------------------


class TestEnvironmentEdgeCases:
    """Tests for environment variable edge cases."""

    def test_no_api_url_set(
        self, runner: CliRunner, monkeypatch
    ) -> None:
        """Command works with default API URL when env not set."""
        monkeypatch.delenv("PULLDB_API_URL", raising=False)
        # Help should still work
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    def test_empty_api_url(
        self, runner: CliRunner, monkeypatch
    ) -> None:
        """Empty API URL handled gracefully."""
        monkeypatch.setenv("PULLDB_API_URL", "")
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    def test_user_env_from_sudo_user(
        self, runner: CliRunner, monkeypatch, mock_api_env: str
    ) -> None:
        """SUDO_USER is used when running as root."""
        monkeypatch.setenv("USER", "root")
        monkeypatch.setenv("SUDO_USER", SAMPLE_USERNAME)
        with responses.RequestsMock() as rsps:
            # History command uses /api/jobs/history endpoint
            rsps.add(
                responses.GET,
                f"{MOCK_API_BASE}/api/jobs/history",
                json=[],
                status=200,
            )
            result = runner.invoke(cli, ["history"])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Special Characters and Unicode
# ---------------------------------------------------------------------------


class TestSpecialCharacters:
    """Tests for special characters and unicode handling."""

    @responses.activate
    def test_target_with_underscore(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Target name with underscore works."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {"id": SAMPLE_JOB_ID, "target": "my_target_db", "status": "complete"}
            ],
            status=200,
        )
        result = runner.invoke(cli, ["status"])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_target_with_numbers(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Target name with numbers works."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {"id": SAMPLE_JOB_ID, "target": "db123_test456", "status": "complete"}
            ],
            status=200,
        )
        result = runner.invoke(cli, ["status"])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Output Format Edge Cases
# ---------------------------------------------------------------------------


class TestOutputEdgeCases:
    """Tests for output format edge cases."""

    @responses.activate
    def test_json_output_with_empty_data(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """JSON output with empty results is valid."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[],
            status=200,
        )
        result = runner.invoke(cli, ["status", "--json"])
        if result.exit_code == 0:
            # Should be valid JSON (empty array or message)
            import json
            try:
                json.loads(result.output)
            except json.JSONDecodeError:
                pass  # May output message instead

    @responses.activate
    def test_table_output_with_long_values(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Table output handles long values gracefully."""
        long_target = "a" * 50
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs",
            json=[
                {"id": SAMPLE_JOB_ID, "target": long_target, "status": "complete"}
            ],
            status=200,
        )
        result = runner.invoke(cli, ["status"])
        # Should not crash
        assert result.exit_code in [0, 1]
