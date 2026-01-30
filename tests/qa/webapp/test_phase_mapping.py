"""Tests for EVENT_TO_PHASE mapping and phase derivation.

These tests ensure the phase stepper correctly reflects job progress,
particularly that analyze events (which run concurrently with myloader)
don't cause premature phase transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from pulldb.web.features.jobs.routes import EVENT_TO_PHASE, _derive_current_phase


class TestEventToPhaseMapping:
    """Tests for EVENT_TO_PHASE mapping correctness."""

    def test_analyze_events_map_to_myloader(self) -> None:
        """Analyze events should map to myloader phase.

        EarlyAnalyzeWorker runs concurrently with myloader, so these events
        must not trigger transition to post_sql phase.
        """
        assert EVENT_TO_PHASE["table_analyze_started"] == "myloader"
        assert EVENT_TO_PHASE["table_analyze_complete"] == "myloader"
        assert EVENT_TO_PHASE["analyze_batch_started"] == "myloader"
        assert EVENT_TO_PHASE["analyze_batch_complete"] == "myloader"
        assert EVENT_TO_PHASE["early_analyze_batch_complete"] == "myloader"

    def test_restore_complete_transitions_to_post_sql(self) -> None:
        """restore_complete should transition to post_sql phase."""
        assert EVENT_TO_PHASE["restore_complete"] == "post_sql"

    def test_post_sql_events_map_to_post_sql(self) -> None:
        """Post-SQL events should map to post_sql phase."""
        assert EVENT_TO_PHASE["post_sql_started"] == "post_sql"
        assert EVENT_TO_PHASE["post_sql_script_complete"] == "post_sql"
        assert EVENT_TO_PHASE["post_sql_complete"] == "post_sql"

    def test_myloader_events_map_to_myloader(self) -> None:
        """Core myloader events should map to myloader phase."""
        assert EVENT_TO_PHASE["myloader_started"] == "myloader"
        assert EVENT_TO_PHASE["restore_progress"] == "myloader"
        assert EVENT_TO_PHASE["table_restore_complete"] == "myloader"


@dataclass
class MockEvent:
    """Mock event for testing _derive_current_phase."""

    event_type: str


class TestDeriveCurrentPhase:
    """Tests for _derive_current_phase function."""

    def test_analyze_during_myloader_shows_myloader_phase(self) -> None:
        """When analyze events occur during myloader, phase should stay 'myloader'.

        This is the key regression test: EarlyAnalyzeWorker emits analyze events
        while myloader is still running. The phase should remain 'myloader'.
        """
        events = [
            MockEvent("myloader_started"),
            MockEvent("restore_progress"),
            MockEvent("table_restore_complete"),
            MockEvent("table_analyze_started"),  # Analyze runs concurrently
            MockEvent("table_analyze_complete"),
            MockEvent("restore_progress"),  # myloader still running
        ]

        phase, phase_list, effective_status = _derive_current_phase(events, "running")

        assert phase == "myloader"
        assert effective_status == "running"
        # Verify phase list has myloader as active
        myloader_phase = next(p for p in phase_list if p["id"] == "myloader")
        assert myloader_phase["state"] == "active"

    def test_restore_complete_triggers_post_sql(self) -> None:
        """restore_complete event should transition to post_sql phase."""
        events = [
            MockEvent("myloader_started"),
            MockEvent("table_analyze_complete"),
            MockEvent("early_analyze_batch_complete"),
            MockEvent("restore_complete"),  # This should trigger post_sql
        ]

        phase, phase_list, effective_status = _derive_current_phase(events, "running")

        assert phase == "post_sql"
        assert effective_status == "running"
        # Verify phase list has post_sql as active
        post_sql_phase = next(p for p in phase_list if p["id"] == "post_sql")
        assert post_sql_phase["state"] == "active"

    def test_takes_most_recent_mapped_event(self) -> None:
        """Phase derivation should use the most recent mapped event."""
        # Events in chronological order (oldest first)
        events = [
            MockEvent("download_complete"),
            MockEvent("extraction_complete"),
            MockEvent("myloader_started"),
        ]

        phase, _, effective_status = _derive_current_phase(events, "running")

        # Most recent is myloader_started
        assert phase == "myloader"
        assert effective_status == "running"

    def test_deployed_status_overrides_to_complete(self) -> None:
        """Deployed job status should show complete phase."""
        events = [
            MockEvent("myloader_started"),
            MockEvent("restore_complete"),
        ]

        phase, phase_list, effective_status = _derive_current_phase(events, "deployed")

        assert phase == "complete"
        assert effective_status == "deployed"
        # All phases before complete should be marked complete
        for p in phase_list:
            if p["id"] != "complete":
                assert p["state"] == "complete"

    def test_failed_status_shows_failed_state(self) -> None:
        """Failed job should show current phase as failed."""
        events = [
            MockEvent("myloader_started"),
            MockEvent("restore_progress"),
        ]

        phase, phase_list, effective_status = _derive_current_phase(events, "failed")

        assert phase == "myloader"
        assert effective_status == "failed"
        myloader_phase = next(p for p in phase_list if p["id"] == "myloader")
        assert myloader_phase["state"] == "failed"

    def test_empty_events_defaults_to_queued(self) -> None:
        """No events should default to queued phase."""
        phase, _, effective_status = _derive_current_phase([], "queued")
        assert phase == "queued"
        assert effective_status == "queued"

    def test_stale_queued_status_returns_running_effective_status(self) -> None:
        """When DB says queued but events show progress, effective_status should be running."""
        events = [
            MockEvent("download_started"),
            MockEvent("download_complete"),
            MockEvent("extraction_started"),
        ]

        phase, phase_list, effective_status = _derive_current_phase(events, "queued")

        # Even though DB says queued, events show extraction phase
        assert phase == "extraction"
        # effective_status should override to "running"
        assert effective_status == "running"
