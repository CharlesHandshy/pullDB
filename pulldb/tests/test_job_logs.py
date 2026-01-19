"""Job Logs / Event Pruning tests.

Unit tests for job event logging and pruning functionality.
Tests the API models without requiring a database connection.

NOTE: CLI tests for prune-logs (admin command) are in pulldb-admin tests.
See docs/KNOWLEDGE-POOL.md "CLI Architecture & Scope" for rationale.
"""

from __future__ import annotations

"""HCA Layer: tests."""

import pytest


class TestPruneLogsAPI:
    """Test prune-logs API endpoint models."""

    def test_prune_logs_request_model(self) -> None:
        """PruneLogsRequest model validates retention days."""
        from pulldb.api.main import PruneLogsRequest

        # Valid request with defaults
        request = PruneLogsRequest()
        assert request.days == 90
        assert request.dry_run is False

        # Valid request with custom values
        request = PruneLogsRequest(days=30, dry_run=True)
        assert request.days == 30
        assert request.dry_run is True

    def test_prune_logs_request_validation(self) -> None:
        """PruneLogsRequest rejects invalid retention days."""
        from pydantic import ValidationError

        from pulldb.api.main import PruneLogsRequest

        # days=0 is now valid (delete all terminal job events)
        request = PruneLogsRequest(days=0)
        assert request.days == 0

        # days must be >= 0
        with pytest.raises(ValidationError):
            PruneLogsRequest(days=-1)

        # days must be <= 365
        with pytest.raises(ValidationError):
            PruneLogsRequest(days=366)

    def test_prune_logs_response_model(self) -> None:
        """PruneLogsResponse model has expected fields."""
        from pulldb.api.main import PruneLogsResponse

        # Dry run response
        response = PruneLogsResponse(
            deleted=0,
            would_delete=100,
            retention_days=90,
            dry_run=True,
        )
        assert response.deleted == 0
        assert response.would_delete == 100
        assert response.retention_days == 90
        assert response.dry_run is True

        # Actual prune response
        response = PruneLogsResponse(
            deleted=50,
            would_delete=0,
            retention_days=30,
            dry_run=False,
        )
        assert response.deleted == 50
        assert response.would_delete == 0
        assert response.dry_run is False


# NOTE: CLI tests for prune-logs command have been moved to pulldb-admin.
# The pulldb CLI only contains user-scoped commands.


class TestJobRepositoryPruneValidation:
    """Test prune_job_events method validation."""

    def test_prune_job_events_method_exists(self) -> None:
        """JobRepository has prune_job_events method."""
        from pulldb.infra.mysql import JobRepository

        assert hasattr(JobRepository, "prune_job_events")

    def test_prune_job_events_docstring(self) -> None:
        """prune_job_events has comprehensive docstring."""
        from pulldb.infra.mysql import JobRepository

        docstring = JobRepository.prune_job_events.__doc__
        assert docstring is not None

        # Docstring should document key aspects
        assert "retention" in docstring.lower()
        assert "terminal" in docstring.lower() or "completed" in docstring.lower()
        assert "volume" in docstring.lower() or "expected" in docstring.lower()


class TestEventTypes:
    """Document and verify expected event types."""

    def test_append_job_event_docstring_has_event_types(self) -> None:
        """append_job_event docstring documents common event types."""
        from pulldb.infra.mysql import JobRepository

        docstring = JobRepository.append_job_event.__doc__
        assert docstring is not None

        # At least some key event types should be documented
        assert "queued" in docstring.lower()
        assert "running" in docstring.lower()
        assert "complete" in docstring.lower()
