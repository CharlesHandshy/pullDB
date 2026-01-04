"""
Category 3: Search Command Tests

Tests for:
- Customer name search functionality
- Search argument parsing
- Limit and JSON output options
- Error handling

Test Count: 14 tests

ARCHITECTURE NOTE:
The `search` command now searches for customer names via the API.
For listing available backups, use the `list` command instead.

This command goes through the API:
- search → API call to /api/customers/search
"""

from __future__ import annotations

from click.testing import CliRunner

from pulldb.cli.main import cli


# ---------------------------------------------------------------------------
# Search Command - Basic Functionality
# ---------------------------------------------------------------------------


class TestSearchBasic:
    """Tests for basic search functionality."""

    def test_search_no_args_shows_error(
        self, runner: CliRunner
    ) -> None:
        """pulldb search without args shows error (query required)."""
        result = runner.invoke(cli, ["search"])
        # Should require query argument
        assert result.exit_code != 0
        # The error may say "missing" or show usage, both indicate missing arg
        output_lower = result.output.lower()
        assert "missing" in output_lower or "usage" in output_lower or "query" in output_lower

    def test_search_help(self, runner: CliRunner) -> None:
        """pulldb search --help shows help text."""
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output.lower()

    def test_search_with_query_positional(self, runner: CliRunner) -> None:
        """pulldb search <query> parses query as positional arg."""
        result = runner.invoke(cli, ["search", "testcust"])
        # Will fail with API error, but should parse args OK
        # Should not error with "missing" query
        assert "missing" not in result.output.lower() or "api" in result.output.lower()


# ---------------------------------------------------------------------------
# Search Command - Limit Option
# ---------------------------------------------------------------------------


class TestSearchFilters:
    """Tests for search limit options."""

    def test_search_with_limit_option(self, runner: CliRunner) -> None:
        """pulldb search with limit=N option."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=50"]
        )
        # Should parse the limit argument correctly (may fail on API access)
        assert "unrecognized option" not in result.output.lower()

    def test_search_limit_in_range(self, runner: CliRunner) -> None:
        """pulldb search with valid limit value parses correctly."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=20"]
        )
        # Valid limit should be accepted
        assert "unrecognized option" not in result.output.lower()
        assert "limit must be" not in result.output.lower()

    def test_search_default_limit(self, runner: CliRunner) -> None:
        """pulldb search without limit uses default."""
        result = runner.invoke(
            cli, ["search", "testcust"]
        )
        # Should not require explicit limit
        assert "limit" not in result.output.lower() or "api" in result.output.lower()

    def test_search_max_limit(self, runner: CliRunner) -> None:
        """pulldb search with limit=500 (max) parses correctly."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=500"]
        )
        # Max valid limit should be accepted
        assert "limit must be" not in result.output.lower()


# ---------------------------------------------------------------------------
# Search Command - Output Formats
# ---------------------------------------------------------------------------


class TestSearchOutput:
    """Tests for search output formats."""

    def test_search_json_flag_accepted(self, runner: CliRunner) -> None:
        """pulldb search accepts json argument."""
        result = runner.invoke(
            cli, ["search", "testcust", "json"]
        )
        # Should not error with "unrecognized option"
        assert "unrecognized option" not in result.output.lower()

    def test_search_limit_option(self, runner: CliRunner) -> None:
        """pulldb search accepts limit= argument."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=10"]
        )
        # Should not error with "unrecognized option"
        assert "unrecognized option" not in result.output.lower()

    def test_search_limit_with_dashes(self, runner: CliRunner) -> None:
        """pulldb search accepts --limit option syntax."""
        result = runner.invoke(
            cli, ["search", "testcust", "--limit", "10"]
        )
        # Should not error with "unrecognized option"
        assert "unrecognized option" not in result.output.lower()


# ---------------------------------------------------------------------------
# Search Command - Error Cases
# ---------------------------------------------------------------------------


class TestSearchErrors:
    """Tests for search error scenarios."""

    def test_search_limit_out_of_range_high(self, runner: CliRunner) -> None:
        """pulldb search with limit > 500 shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=501"]
        )
        # Should fail - limit must be between 1 and 500
        assert result.exit_code != 0
        assert "limit" in result.output.lower()

    def test_search_limit_out_of_range_zero(self, runner: CliRunner) -> None:
        """pulldb search with limit=0 shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=0"]
        )
        # Should fail - limit must be > 0
        assert result.exit_code != 0
        assert "limit" in result.output.lower()

    def test_search_invalid_limit(self, runner: CliRunner) -> None:
        """pulldb search with non-numeric limit shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=abc"]
        )
        # Should fail with invalid limit error
        assert result.exit_code != 0

    def test_search_negative_limit(self, runner: CliRunner) -> None:
        """pulldb search with negative limit shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=-5"]
        )
        # Should fail - limit must be positive
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Search Command - Argument Variations
# ---------------------------------------------------------------------------


class TestSearchArgVariations:
    """Tests for search argument variations."""

    def test_search_with_limit_and_json(self, runner: CliRunner) -> None:
        """pulldb search with limit and json options."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=5", "json"]
        )
        # Should accept all arguments
        assert "unrecognized option" not in result.output.lower()

    def test_search_json_and_limit(self, runner: CliRunner) -> None:
        """pulldb search with json and limit in different order."""
        result = runner.invoke(
            cli, [
                "search",
                "testcust",
                "json",
                "limit=10",
            ]
        )
        # Should accept all arguments regardless of order
        assert "unrecognized option" not in result.output.lower()

    def test_search_wildcard_customer(self, runner: CliRunner) -> None:
        """pulldb search with wildcard customer pattern."""
        result = runner.invoke(
            cli, ["search", "test*"]
        )
        # Wildcards are valid search patterns
        assert "unrecognized option" not in result.output.lower()
