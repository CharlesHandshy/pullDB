"""Tests for RestoreProgressTracker - unified row-based progress tracking."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from pulldb.worker.backup_metadata import TableRowEstimate
from pulldb.worker.processlist_monitor import ProcesslistSnapshot, TableProgress
from pulldb.worker.restore_progress import (
    RestoreProgress,
    RestoreProgressTracker,
    TableProgressInfo,
    ThroughputStats,
    create_progress_tracker,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def table_metadata() -> list[TableRowEstimate]:
    """Sample table metadata for testing."""
    return [
        TableRowEstimate(database="mydb", table="users", rows=1000),
        TableRowEstimate(database="mydb", table="orders", rows=5000),
        TableRowEstimate(database="mydb", table="items", rows=10000),
    ]


@pytest.fixture
def tracker(table_metadata: list[TableRowEstimate]) -> RestoreProgressTracker:
    """Fresh tracker instance."""
    return RestoreProgressTracker(
        table_metadata=table_metadata,
        throttle_interval_seconds=0,  # Disable throttling for tests
    )


@pytest.fixture
def tracker_with_callback(
    table_metadata: list[TableRowEstimate],
) -> tuple[RestoreProgressTracker, MagicMock]:
    """Tracker with mocked callback."""
    callback = MagicMock()
    tracker = RestoreProgressTracker(
        table_metadata=table_metadata,
        on_progress=callback,
        throttle_interval_seconds=0,
    )
    return tracker, callback


def make_snapshot(
    tables: dict[str, tuple[str, float, int]] | None = None,
) -> ProcesslistSnapshot:
    """Create ProcesslistSnapshot from dict.

    Args:
        tables: Dict of table_name -> (phase, percent, running_seconds)
    """
    table_progress = {}
    if tables:
        for name, (phase, pct, secs) in tables.items():
            table_progress[name] = TableProgress(
                table=name,
                percent_complete=pct,
                phase=phase,
                running_seconds=secs,
            )

    return ProcesslistSnapshot(
        tables=table_progress,
        active_threads=len(table_progress),
        timestamp=time.monotonic(),
    )


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInitialization:
    """Test tracker initialization."""

    def test_creates_tracker_with_metadata(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Tracker initializes from table metadata."""
        tracker = RestoreProgressTracker(table_metadata=table_metadata)

        assert tracker._total_tables == 3
        assert tracker._total_rows == 16000  # 1000 + 5000 + 10000
        assert len(tracker._tables) == 3
        assert "users" in tracker._tables
        assert "orders" in tracker._tables
        assert "items" in tracker._tables

    def test_empty_metadata(self) -> None:
        """Tracker handles empty metadata."""
        tracker = RestoreProgressTracker(table_metadata=[])

        assert tracker._total_tables == 0
        assert tracker._total_rows == 0
        progress = tracker.get_progress()
        assert progress.percent_complete == 0.0

    def test_accepts_callback(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Tracker accepts progress callback."""
        callback = MagicMock()
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            on_progress=callback,
        )
        assert tracker._on_progress is callback

    def test_accepts_throttle_interval(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Tracker accepts custom throttle interval."""
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=1.5,
        )
        assert tracker._throttle_interval == 1.5


# =============================================================================
# Processlist Update Tests
# =============================================================================


class TestProcesslistUpdates:
    """Test updating from processlist snapshots."""

    def test_updates_table_progress(self, tracker: RestoreProgressTracker) -> None:
        """Processlist updates table progress."""
        snapshot = make_snapshot({"users": ("loading", 50.0, 10)})
        tracker.update_from_processlist(snapshot)

        state = tracker._tables["users"]
        assert state.percent_complete == 50.0
        assert state.phase == "loading"
        assert state.running_seconds == 10

    def test_calculates_rows_from_percent(self, tracker: RestoreProgressTracker) -> None:
        """Rows loaded calculated from percent."""
        snapshot = make_snapshot({"users": ("loading", 50.0, 0)})
        tracker.update_from_processlist(snapshot)

        progress = tracker.get_progress()
        # users has 1000 rows, 50% = 500 rows
        # 500 / 16000 total = 3.125%
        assert progress.rows_loaded == 500
        assert 3.0 <= progress.percent_complete <= 3.5

    def test_multiple_tables_in_progress(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Handles multiple tables in progress."""
        snapshot = make_snapshot({
            "users": ("loading", 100.0, 0),
            "orders": ("loading", 50.0, 0),
        })
        tracker.update_from_processlist(snapshot)

        progress = tracker.get_progress()
        # users: 1000 rows (100%)
        # orders: 2500 rows (50% of 5000)
        # total: 3500 / 16000 = 21.875%
        assert progress.rows_loaded == 3500
        assert 21.5 <= progress.percent_complete <= 22.0

    def test_ignores_unknown_tables(self, tracker: RestoreProgressTracker) -> None:
        """Unknown tables in processlist are ignored."""
        snapshot = make_snapshot({"unknown_table": ("loading", 50.0, 0)})
        tracker.update_from_processlist(snapshot)

        progress = tracker.get_progress()
        assert progress.rows_loaded == 0
        assert len(progress.tables_in_progress) == 0

    def test_tracks_indexing_phase(self, tracker: RestoreProgressTracker) -> None:
        """Tracks indexing phase from processlist."""
        snapshot = make_snapshot({"users": ("indexing", 75.0, 30)})
        tracker.update_from_processlist(snapshot)

        progress = tracker.get_progress()
        assert len(progress.tables_in_progress) == 1
        table_info = progress.tables_in_progress[0]
        assert table_info.phase == "indexing"
        assert table_info.running_seconds == 30

    def test_emits_progress_on_update(
        self, tracker_with_callback: tuple[RestoreProgressTracker, MagicMock]
    ) -> None:
        """Progress callback is invoked on processlist update."""
        tracker, callback = tracker_with_callback
        snapshot = make_snapshot({"users": ("loading", 25.0, 0)})

        tracker.update_from_processlist(snapshot)

        callback.assert_called()
        progress = callback.call_args[0][0]
        assert isinstance(progress, RestoreProgress)
        assert progress.source == "processlist"


# =============================================================================
# Myloader Line Parsing Tests
# =============================================================================


class TestMyloaderLineParsing:
    """Test parsing myloader stdout lines."""

    def test_extracts_finished_table(self, tracker: RestoreProgressTracker) -> None:
        """Extracts table name from finished line."""
        line = "Thread 1 finished restoring mydb.users.00000.sql"
        tracker.update_from_myloader_line(line)
        # Line parsing alone doesn't mark complete - needs processlist or finalize

    def test_extracts_verbose_restore(self, tracker: RestoreProgressTracker) -> None:
        """Extracts from verbose restore format."""
        line = "Thread 1: restoring data from mydb.users.00000.sql | Tables"
        tracker.update_from_myloader_line(line)

    def test_ignores_unrelated_lines(self, tracker: RestoreProgressTracker) -> None:
        """Ignores lines without table info."""
        line = "Some other myloader output"
        tracker.update_from_myloader_line(line)
        progress = tracker.get_progress()
        assert progress.tables_completed == 0


# =============================================================================
# Table Name Normalization Tests
# =============================================================================


class TestTableNameNormalization:
    """Test table name normalization."""

    def test_normalizes_db_table_format(self, tracker: RestoreProgressTracker) -> None:
        """Normalizes 'db.table' format."""
        result = tracker._normalize_table_name("mydb.users")
        assert result == "users"

    def test_normalizes_file_path(self, tracker: RestoreProgressTracker) -> None:
        """Normalizes file path format."""
        result = tracker._normalize_table_name("mydb.users.00000.sql.gz")
        assert result == "users"

    def test_normalizes_full_path(self, tracker: RestoreProgressTracker) -> None:
        """Normalizes full file path."""
        result = tracker._normalize_table_name("/backup/mydb.users.00000.sql")
        assert result == "users"

    def test_handles_bare_name(self, tracker: RestoreProgressTracker) -> None:
        """Handles bare table name."""
        result = tracker._normalize_table_name("users")
        assert result == "users"


# =============================================================================
# Finalization Tests
# =============================================================================


class TestFinalization:
    """Test tracker finalization."""

    def test_marks_all_complete(self, tracker: RestoreProgressTracker) -> None:
        """Finalize marks all tables complete."""
        # First add some progress
        snapshot = make_snapshot({"users": ("loading", 50.0, 0)})
        tracker.update_from_processlist(snapshot)

        # Then finalize
        progress = tracker.finalize()

        assert progress.tables_completed == 3
        assert progress.percent_complete == 100.0
        assert progress.rows_loaded == 16000

    def test_emits_final_progress(
        self, tracker_with_callback: tuple[RestoreProgressTracker, MagicMock]
    ) -> None:
        """Finalize emits progress event."""
        tracker, callback = tracker_with_callback
        callback.reset_mock()

        tracker.finalize()

        callback.assert_called()
        progress = callback.call_args[0][0]
        assert progress.source == "finalized"
        assert progress.percent_complete == 100.0

    def test_finalize_includes_tables_at_100_percent(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Finalize includes tables at 100% in event (not empty tables dict).

        Regression test: Previously, finalize() would mark all tables complete
        but then to_event_dict() would show empty tables dict because it only
        included "in-progress" tables. This caused the UI to show tables at
        84%/85% and then suddenly disappear to 100% with no per-table info.
        """
        # First add some progress to simulate restore in progress
        snapshot = make_snapshot({
            "users": ("loading", 85.0, 10),
            "orders": ("loading", 84.0, 12),
        })
        tracker.update_from_processlist(snapshot)

        # Then finalize (myloader exited successfully)
        progress = tracker.finalize()
        event_dict = progress.to_event_dict()

        # CRITICAL: tables should include all tables at 100%
        tables = event_dict["detail"]["tables"]
        assert len(tables) == 3, f"Expected 3 tables, got {len(tables)}: {tables.keys()}"

        # Each table should be at 100%
        for table_name, table_info in tables.items():
            assert table_info["percent_complete"] == 100.0, (
                f"Table {table_name} should be 100%, got {table_info['percent_complete']}"
            )
            assert table_info["is_complete"] is True, (
                f"Table {table_name} should have is_complete=True"
            )


# =============================================================================
# Progress Snapshot Tests
# =============================================================================


class TestProgressSnapshot:
    """Test RestoreProgress snapshot creation."""

    def test_snapshot_is_immutable(self, tracker: RestoreProgressTracker) -> None:
        """Progress snapshot is immutable."""
        progress = tracker.get_progress()

        # Try to modify (should fail)
        with pytest.raises(AttributeError):
            progress.percent_complete = 50.0  # type: ignore

    def test_to_event_dict_format(self, tracker: RestoreProgressTracker) -> None:
        """to_event_dict produces correct format."""
        snapshot = make_snapshot({"users": ("loading", 50.0, 10)})
        tracker.update_from_processlist(snapshot)

        progress = tracker.get_progress()
        event_dict = progress.to_event_dict()

        assert "percent" in event_dict
        assert "detail" in event_dict
        detail = event_dict["detail"]
        assert "status" in detail
        assert "active_threads" in detail
        assert "tables" in detail
        assert "rows_restored" in detail
        assert "total_rows" in detail

    def test_throughput_calculation(self, tracker: RestoreProgressTracker) -> None:
        """Throughput is calculated correctly."""
        # Wait a tiny bit to get non-zero elapsed time
        time.sleep(0.01)

        snapshot = make_snapshot({"users": ("loading", 100.0, 0)})
        tracker.update_from_processlist(snapshot)

        progress = tracker.get_progress()
        assert progress.throughput.elapsed_seconds > 0
        assert progress.throughput.rows_per_second >= 0


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateProgressTracker:
    """Test create_progress_tracker factory."""

    def test_creates_tracker_without_callback(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Creates tracker without callback."""
        tracker = create_progress_tracker(table_metadata=table_metadata)
        assert isinstance(tracker, RestoreProgressTracker)
        assert tracker._on_progress is None

    def test_creates_tracker_with_old_style_callback(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Creates tracker with old-style (percent, detail) callback."""
        calls: list[tuple[float, dict]] = []

        def old_callback(percent: float, detail: dict) -> None:
            calls.append((percent, detail))

        tracker = create_progress_tracker(
            table_metadata=table_metadata,
            progress_callback=old_callback,
        )

        # Trigger a progress update
        snapshot = make_snapshot({"users": ("loading", 50.0, 0)})
        tracker.update_from_processlist(snapshot)

        # Should have received callback in old format
        assert len(calls) >= 1
        percent, detail = calls[-1]
        assert isinstance(percent, float)
        assert isinstance(detail, dict)
        assert "status" in detail


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Test thread-safe operations."""

    def test_concurrent_updates(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Tracker handles concurrent updates safely."""
        import threading

        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        errors: list[Exception] = []

        def update_from_processlist() -> None:
            try:
                for i in range(100):
                    snapshot = make_snapshot({"users": ("loading", float(i), 0)})
                    tracker.update_from_processlist(snapshot)
            except Exception as e:
                errors.append(e)

        def update_from_line() -> None:
            try:
                for _ in range(100):
                    tracker.update_from_myloader_line("Thread 1 finished users.sql")
            except Exception as e:
                errors.append(e)

        def get_progress() -> None:
            try:
                for _ in range(100):
                    tracker.get_progress()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=update_from_processlist),
            threading.Thread(target=update_from_line),
            threading.Thread(target=get_progress),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_rows_table(self) -> None:
        """Handles tables with zero rows."""
        metadata = [
            TableRowEstimate(database="mydb", table="empty", rows=0),
            TableRowEstimate(database="mydb", table="nonempty", rows=100),
        ]
        tracker = RestoreProgressTracker(table_metadata=metadata)

        snapshot = make_snapshot({"nonempty": ("loading", 50.0, 0)})
        tracker.update_from_processlist(snapshot)

        progress = tracker.get_progress()
        assert progress.rows_loaded == 50  # 50% of 100

    def test_percent_clamped_to_100(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Percent is clamped to 100."""
        tracker = RestoreProgressTracker(table_metadata=table_metadata)

        # Simulate processlist reporting > 100%
        snapshot = make_snapshot({"users": ("loading", 150.0, 0)})
        tracker.update_from_processlist(snapshot)

        state = tracker._tables["users"]
        assert state.percent_complete == 100.0  # Clamped

    def test_completed_tables_not_updated(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Completed tables aren't updated from processlist."""
        tracker.mark_table_complete("users")

        snapshot = make_snapshot({"users": ("loading", 50.0, 0)})
        tracker.update_from_processlist(snapshot)

        state = tracker._tables["users"]
        assert state.is_complete
        assert state.percent_complete == 100.0  # Still 100%, not 50%
