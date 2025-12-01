"""
Category 3: Search Command Tests

Tests for:
- S3 backup search functionality
- Search argument parsing
- Filter options (date, s3env, limit)
- Output formats (table, json)
- Error handling

Test Count: 14 tests

ARCHITECTURE NOTE:
The `search` command is UNIQUE among CLI commands - it accesses S3 directly
(via pulldb.infra.s3.S3Client) rather than going through the API. This is
a design decision for fast local searching without API roundtrip.

This is different from all other commands which use the API:
- restore, status, history, events, cancel, profile → API calls

Tests here focus on argument parsing and validation since S3 access
requires AWS credentials that may not be available in test environment.
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
        """pulldb search without args shows error (customer required)."""
        result = runner.invoke(cli, ["search"])
        # Should require customer argument
        assert result.exit_code != 0
        assert "missing" in result.output.lower() or "customer" in result.output.lower()

    def test_search_help(self, runner: CliRunner) -> None:
        """pulldb search --help shows help text."""
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output.lower()
        assert "customer" in result.output.lower()

    def test_search_with_customer_positional(self, runner: CliRunner) -> None:
        """pulldb search <customer> parses customer as positional arg."""
        result = runner.invoke(cli, ["search", "testcust"])
        # Will fail with S3/AWS error, but should parse args OK
        # Should not error with "missing" customer
        assert "missing" not in result.output.lower() or "s3" in result.output.lower()


# ---------------------------------------------------------------------------
# Search Command - Filter Options
# ---------------------------------------------------------------------------


class TestSearchFilters:
    """Tests for search filter options."""

    def test_search_with_date_filter(self, runner: CliRunner) -> None:
        """pulldb search with date=YYYYMMDD filter."""
        result = runner.invoke(
            cli, ["search", "testcust", "date=20251115"]
        )
        # Should parse the date argument correctly (may fail on S3 access)
        assert "unrecognized option" not in result.output.lower()

    def test_search_with_s3env_staging(self, runner: CliRunner) -> None:
        """pulldb search with s3env=staging parses correctly."""
        result = runner.invoke(
            cli, ["search", "testcust", "s3env=staging"]
        )
        # Valid s3env value should be accepted
        assert "unrecognized option" not in result.output.lower()
        assert "s3env must be" not in result.output.lower()

    def test_search_with_s3env_prod(self, runner: CliRunner) -> None:
        """pulldb search with s3env=prod parses correctly."""
        result = runner.invoke(
            cli, ["search", "testcust", "s3env=prod"]
        )
        # Valid s3env value should be accepted
        assert "s3env must be" not in result.output.lower()

    def test_search_with_s3env_both(self, runner: CliRunner) -> None:
        """pulldb search with s3env=both parses correctly."""
        result = runner.invoke(
            cli, ["search", "testcust", "s3env=both"]
        )
        # Valid s3env value should be accepted
        assert "s3env must be" not in result.output.lower()


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

    def test_search_invalid_s3env(self, runner: CliRunner) -> None:
        """pulldb search with invalid s3env shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "s3env=invalid"]
        )
        # Invalid s3env should be rejected
        assert result.exit_code != 0
        assert "s3env must be" in result.output.lower()

    def test_search_invalid_date_format(self, runner: CliRunner) -> None:
        """pulldb search with invalid date format shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "date=not-a-date"]
        )
        # Should fail with date format error
        assert result.exit_code != 0
        assert "invalid date" in result.output.lower() or "yyyymmdd" in result.output.lower()

    def test_search_invalid_limit(self, runner: CliRunner) -> None:
        """pulldb search with non-numeric limit shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=abc"]
        )
        # Should fail with invalid limit error
        assert result.exit_code != 0

    def test_search_limit_out_of_range(self, runner: CliRunner) -> None:
        """pulldb search with limit > 100 shows error."""
        result = runner.invoke(
            cli, ["search", "testcust", "limit=200"]
        )
        # Should fail - limit must be between 1 and 100
        assert result.exit_code != 0
        assert "limit" in result.output.lower()


# ---------------------------------------------------------------------------
# Search Command - Argument Variations
# ---------------------------------------------------------------------------


class TestSearchArgVariations:
    """Tests for search argument variations."""

    def test_search_multiple_options(self, runner: CliRunner) -> None:
        """pulldb search with multiple options."""
        result = runner.invoke(
            cli, ["search", "testcust", "date=20251115", "limit=5"]
        )
        # Should accept all arguments
        assert "unrecognized option" not in result.output.lower()

    def test_search_all_options(self, runner: CliRunner) -> None:
        """pulldb search with all option types."""
        result = runner.invoke(
            cli, [
                "search",
                "testcust",
                "date=20251115",
                "s3env=prod",
                "limit=10",
                "json",
            ]
        )
        # Should accept all arguments
        assert "unrecognized option" not in result.output.lower()

    def test_search_wildcard_customer(self, runner: CliRunner) -> None:
        """pulldb search with wildcard customer pattern."""
        result = runner.invoke(
            cli, ["search", "test*"]
        )
        # Wildcards are valid customer patterns
        assert "unrecognized option" not in result.output.lower()
