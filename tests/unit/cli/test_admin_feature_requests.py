"""Tests for the feature requests admin CLI commands.

Tests cover:
- CLI argument parsing and options
- Output formatting (table and JSON)
- Error handling (connection failures, not found)
- Mock database interactions

HCA Layer: tests (isolated from production)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from pulldb.cli.admin_feature_requests import (
    _format_date,
    _format_date_short,
    _format_status,
    _truncate,
    feature_requests_group,
)
from pulldb.domain.feature_request import (
    FeatureRequest,
    FeatureRequestNote,
    FeatureRequestStats,
    FeatureRequestStatus,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def sample_request() -> FeatureRequest:
    """Create a sample feature request for testing."""
    return FeatureRequest(
        request_id="12345678-1234-1234-1234-123456789abc",
        submitted_by_user_id="user-001",
        title="Add dark mode support",
        description="Please add a dark mode theme for the web UI.",
        status=FeatureRequestStatus.OPEN,
        vote_score=15,
        upvote_count=15,
        downvote_count=0,
        created_at=datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 20, 14, 45, 0, tzinfo=UTC),
        completed_at=None,
        admin_response=None,
        submitted_by_username="johndoe",
        submitted_by_user_code="JDO",
        user_vote=None,
    )


@pytest.fixture
def sample_requests() -> list[FeatureRequest]:
    """Create multiple sample feature requests."""
    return [
        FeatureRequest(
            request_id="11111111-1111-1111-1111-111111111111",
            submitted_by_user_id="user-001",
            title="Feature A - Dark mode",
            description="Dark mode description",
            status=FeatureRequestStatus.OPEN,
            vote_score=20,
            upvote_count=20,
            downvote_count=0,
            created_at=datetime(2026, 1, 10, tzinfo=UTC),
            updated_at=datetime(2026, 1, 10, tzinfo=UTC),
            submitted_by_username="alice",
            submitted_by_user_code="ALI",
        ),
        FeatureRequest(
            request_id="22222222-2222-2222-2222-222222222222",
            submitted_by_user_id="user-002",
            title="Feature B - Export CSV",
            description="Export to CSV",
            status=FeatureRequestStatus.IN_PROGRESS,
            vote_score=10,
            upvote_count=12,
            downvote_count=2,
            created_at=datetime(2026, 1, 12, tzinfo=UTC),
            updated_at=datetime(2026, 1, 15, tzinfo=UTC),
            submitted_by_username="bob",
            submitted_by_user_code="BOB",
        ),
        FeatureRequest(
            request_id="33333333-3333-3333-3333-333333333333",
            submitted_by_user_id="user-003",
            title="Feature C - API improvements",
            description=None,
            status=FeatureRequestStatus.COMPLETE,
            vote_score=0,
            upvote_count=5,
            downvote_count=5,
            created_at=datetime(2026, 1, 5, tzinfo=UTC),
            updated_at=datetime(2026, 1, 20, tzinfo=UTC),
            completed_at=datetime(2026, 1, 20, tzinfo=UTC),
            admin_response="Implemented in v1.2.0",
            submitted_by_username="charlie",
            submitted_by_user_code="CHA",
        ),
    ]


@pytest.fixture
def sample_notes() -> list[FeatureRequestNote]:
    """Create sample notes for testing."""
    return [
        FeatureRequestNote(
            note_id="note-001",
            request_id="12345678-1234-1234-1234-123456789abc",
            user_id="user-001",
            note_text="This would be really useful!",
            created_at=datetime(2026, 1, 16, 9, 0, 0, tzinfo=UTC),
            username="johndoe",
            user_code="JDO",
        ),
        FeatureRequestNote(
            note_id="note-002",
            request_id="12345678-1234-1234-1234-123456789abc",
            user_id="user-002",
            note_text="I agree, dark mode helps with eye strain.",
            created_at=datetime(2026, 1, 17, 15, 30, 0, tzinfo=UTC),
            username="janedoe",
            user_code="JAN",
        ),
    ]


@pytest.fixture
def sample_stats() -> FeatureRequestStats:
    """Create sample statistics."""
    return FeatureRequestStats(
        total=50,
        open=30,
        in_progress=10,
        complete=8,
        declined=2,
    )


@pytest.fixture
def mock_service(
    sample_requests: list[FeatureRequest],
    sample_request: FeatureRequest,
    sample_notes: list[FeatureRequestNote],
    sample_stats: FeatureRequestStats,
) -> MagicMock:
    """Create a mock FeatureRequestService."""
    service = MagicMock()

    # Mock async methods with AsyncMock
    service.list_requests = AsyncMock(
        return_value=(sample_requests, len(sample_requests))
    )
    service.get_request = AsyncMock(return_value=sample_request)
    service.list_notes = AsyncMock(return_value=sample_notes)
    service.get_stats = AsyncMock(return_value=sample_stats)

    return service


# =============================================================================
# Formatting Tests
# =============================================================================


class TestFormatting:
    """Test output formatting functions."""

    def test_format_status_open(self) -> None:
        """Test status formatting for open."""
        result = _format_status(FeatureRequestStatus.OPEN)
        # Result contains ANSI codes, just verify it contains the value
        assert "open" in result

    def test_format_status_complete(self) -> None:
        """Test status formatting for complete."""
        result = _format_status(FeatureRequestStatus.COMPLETE)
        assert "complete" in result

    def test_format_date_with_value(self) -> None:
        """Test date formatting with a value."""
        dt = datetime(2026, 1, 15, 10, 30, 0)
        result = _format_date(dt)
        assert result == "2026-01-15 10:30"

    def test_format_date_none(self) -> None:
        """Test date formatting with None."""
        result = _format_date(None)
        assert result == "-"

    def test_format_date_short(self) -> None:
        """Test short date formatting."""
        dt = datetime(2026, 1, 15, 10, 30, 0)
        result = _format_date_short(dt)
        assert result == "2026-01-15"

    def test_truncate_short_text(self) -> None:
        """Test truncation of short text (no change)."""
        result = _truncate("Short text", 20)
        assert result == "Short text"

    def test_truncate_long_text(self) -> None:
        """Test truncation of long text."""
        result = _truncate("This is a very long text that needs truncation", 20)
        assert result == "This is a very lo..."
        assert len(result) == 20

    def test_truncate_none(self) -> None:
        """Test truncation with None."""
        result = _truncate(None, 20)
        assert result == ""

    def test_truncate_empty(self) -> None:
        """Test truncation with empty string."""
        result = _truncate("", 20)
        assert result == ""


# =============================================================================
# CLI List Command Tests
# =============================================================================


class TestListCommand:
    """Test the 'list' subcommand."""

    def test_list_basic(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test basic list command."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(feature_requests_group, ["list"])

        assert result.exit_code == 0
        assert "Feature Requests" in result.output
        assert "Feature A" in result.output or "11111111" in result.output

    def test_list_with_status_filter(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test list command with status filter."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group, ["list", "--status", "open"]
            )

        assert result.exit_code == 0
        # Verify the service was called with status filter
        mock_service.list_requests.assert_called_once()
        call_kwargs = mock_service.list_requests.call_args[1]
        assert call_kwargs["status_filter"] == ["open"]

    def test_list_with_sort_by_date(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test list command with date sorting."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group, ["list", "--sort", "date"]
            )

        assert result.exit_code == 0
        call_kwargs = mock_service.list_requests.call_args[1]
        assert call_kwargs["sort_by"] == "created_at"

    def test_list_with_limit(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test list command with limit."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group, ["list", "--limit", "5"]
            )

        assert result.exit_code == 0
        call_kwargs = mock_service.list_requests.call_args[1]
        assert call_kwargs["limit"] == 5

    def test_list_json_output(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test list command with JSON output."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(feature_requests_group, ["list", "--json"])

        assert result.exit_code == 0

        # Parse JSON output
        output = json.loads(result.output)
        assert "total" in output
        assert "requests" in output
        assert isinstance(output["requests"], list)
        assert len(output["requests"]) == 3

    def test_list_empty_results(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test list command with no results."""
        mock_service.list_requests = AsyncMock(return_value=([], 0))

        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(feature_requests_group, ["list"])

        assert result.exit_code == 0
        assert "No feature requests found" in result.output


# =============================================================================
# CLI Show Command Tests
# =============================================================================


class TestShowCommand:
    """Test the 'show' subcommand."""

    def test_show_full_id(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
        sample_request: FeatureRequest,
    ) -> None:
        """Test show command with full request ID."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group,
                ["show", sample_request.request_id],
            )

        assert result.exit_code == 0
        assert sample_request.title in result.output
        assert "JDO" in result.output or "johndoe" in result.output

    def test_show_partial_id(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
        sample_requests: list[FeatureRequest],
    ) -> None:
        """Test show command with partial request ID."""
        # First call returns None (partial ID not found directly)
        # Second call returns the list for searching
        mock_service.get_request = AsyncMock(return_value=None)
        mock_service.list_requests = AsyncMock(
            return_value=(sample_requests, len(sample_requests))
        )

        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group,
                ["show", "11111111"],
            )

        assert result.exit_code == 0
        # Should find the request starting with that ID
        assert "Feature A" in result.output

    def test_show_not_found(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test show command when request not found."""
        mock_service.get_request = AsyncMock(return_value=None)
        mock_service.list_requests = AsyncMock(return_value=([], 0))

        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group,
                ["show", "nonexistent"],
            )

        assert result.exit_code != 0
        assert "Not found" in result.output

    def test_show_json_output(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
        sample_request: FeatureRequest,
    ) -> None:
        """Test show command with JSON output."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group,
                ["show", sample_request.request_id, "--json"],
            )

        assert result.exit_code == 0

        output = json.loads(result.output)
        assert "request" in output
        assert "notes" in output
        assert output["request"]["request_id"] == sample_request.request_id
        assert output["request"]["title"] == sample_request.title

    def test_show_with_notes(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
        sample_request: FeatureRequest,
    ) -> None:
        """Test show command displays notes."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(
                feature_requests_group,
                ["show", sample_request.request_id],
            )

        assert result.exit_code == 0
        assert "Notes" in result.output
        assert "really useful" in result.output
        assert "eye strain" in result.output


# =============================================================================
# CLI Stats Command Tests
# =============================================================================


class TestStatsCommand:
    """Test the 'stats' subcommand."""

    def test_stats_basic(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test basic stats command."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(feature_requests_group, ["stats"])

        assert result.exit_code == 0
        assert "Statistics" in result.output
        assert "Total" in result.output
        assert "50" in result.output  # total from sample_stats
        assert "30" in result.output  # open from sample_stats

    def test_stats_json_output(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test stats command with JSON output."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(feature_requests_group, ["stats", "--json"])

        assert result.exit_code == 0

        output = json.loads(result.output)
        assert "statistics" in output
        assert "top_voted" in output
        assert output["statistics"]["total"] == 50
        assert output["statistics"]["open"] == 30

    def test_stats_shows_top_voted(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test that stats shows top voted requests."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(feature_requests_group, ["stats"])

        assert result.exit_code == 0
        assert "Top Voted" in result.output


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_connection_failure(self, cli_runner: CliRunner) -> None:
        """Test handling of database connection failure."""
        with patch(
            "pulldb.cli.admin_feature_requests._get_production_pool",
            side_effect=Exception("Connection refused"),
        ):
            result = cli_runner.invoke(feature_requests_group, ["list"])

        # The exception is raised and causes non-zero exit
        assert result.exit_code != 0
        # Exception info is in result.exception, not output
        assert result.exception is not None
        assert "Connection refused" in str(result.exception)

    def test_service_error(
        self,
        cli_runner: CliRunner,
        mock_service: MagicMock,
    ) -> None:
        """Test handling of service errors."""
        mock_service.list_requests = AsyncMock(
            side_effect=Exception("Database query failed")
        )

        with patch(
            "pulldb.cli.admin_feature_requests._get_feature_request_service",
            return_value=mock_service,
        ):
            result = cli_runner.invoke(feature_requests_group, ["list"])

        # Should propagate the error
        assert result.exit_code != 0


# =============================================================================
# Help Text Tests
# =============================================================================


class TestHelpText:
    """Test CLI help text."""

    def test_group_help(self, cli_runner: CliRunner) -> None:
        """Test feature-requests group help."""
        result = cli_runner.invoke(feature_requests_group, ["--help"])

        assert result.exit_code == 0
        assert "feature requests" in result.output.lower()
        assert "list" in result.output
        assert "show" in result.output
        assert "stats" in result.output

    def test_list_help(self, cli_runner: CliRunner) -> None:
        """Test list command help."""
        result = cli_runner.invoke(feature_requests_group, ["list", "--help"])

        assert result.exit_code == 0
        assert "--status" in result.output
        assert "--sort" in result.output
        assert "--limit" in result.output
        assert "--json" in result.output

    def test_show_help(self, cli_runner: CliRunner) -> None:
        """Test show command help."""
        result = cli_runner.invoke(feature_requests_group, ["show", "--help"])

        assert result.exit_code == 0
        assert "REQUEST_ID" in result.output
        assert "--json" in result.output

    def test_stats_help(self, cli_runner: CliRunner) -> None:
        """Test stats command help."""
        result = cli_runner.invoke(feature_requests_group, ["stats", "--help"])

        assert result.exit_code == 0
        assert "--json" in result.output
