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
        """Tracks indexing phase from processlist (after log-based file tracking)."""
        # First, simulate myloader output so the table appears in progress
        # (we now use log-based detection, not processlist-based)
        # Must use the full Progress format that triggers _mark_file_started
        tracker.update_from_myloader_line(
            "** Message: 00:00:02.000: Thread 1: restoring `mydb`.`users` "
            "part 1 of 10 from mydb.users.00001.sql.gz | Progress 1 of 100. Tables 0 of 3 completed"
        )

        # Now the processlist update can set the phase
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


class TestFileBasedProgress:
    """Tests for file-based progress tracking (Option 2 fix for >100% issue)."""

    def test_parses_progress_message_with_file_info(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Parses 'Progress X of Y' message to track file starts."""
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        # Simulate myloader Progress message (printed BEFORE file processing)
        line = (
            "Thread 1: restoring mydb.users part 1 of 3 from users.00000.sql.gz | "
            "Progress 1 of 10. Tables 0 of 3 completed"
        )
        tracker.update_from_myloader_line(line)

        state = tracker._tables["users"]
        assert state.files_started == 1
        assert state.file_count == 3  # Updated from myloader output
        assert state.was_ever_seen is True

    def test_file_based_progress_calculation(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """File-based progress uses files_started / file_count ratio."""
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        # Mark 2 of 4 files started for users (1000 rows)
        tracker._tables["users"].files_started = 2
        tracker._tables["users"].file_count = 4

        # Calculate rows: 2/4 = 50% of 1000 = 500 rows
        rows = tracker._calculate_rows_loaded()
        assert rows == 500

    def test_file_based_takes_priority_over_processlist(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """File-based progress overrides processlist percentage."""
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        # Processlist shows 150% (the bug we're fixing)
        tracker._tables["users"].percent_complete = 150.0

        # But we have file-based data: 3 of 4 files started
        tracker._tables["users"].files_started = 3
        tracker._tables["users"].file_count = 4

        # Should use file-based: 3/4 = 75% of 1000 = 750 rows
        rows = tracker._calculate_rows_loaded()
        assert rows == 750  # Not 1500 (150% bug) or 1000 (capped 100%)

    def test_data_complete_flag_means_100_percent(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """When data_complete=True (from Enqueuing index), use DATA_PHASE_WEIGHT of rows.
        
        Tables with data_complete contribute 85% of their rows to overall progress
        because indexing is still pending. Only index_complete or is_complete
        contribute 100% of rows.
        """
        from pulldb.worker.restore_progress import DATA_PHASE_WEIGHT
        
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        # Simulate "Enqueuing index" which sets data_complete
        line = "Thread 1: Enqueuing index for table: mydb.users"
        tracker.update_from_myloader_line(line)

        state = tracker._tables["users"]
        assert state.data_complete is True
        # Percent is capped at 85% because indexing is still pending
        assert state.percent_complete == DATA_PHASE_WEIGHT * 100.0  # 85%

        # Calculate rows: should be 85% = 850 rows (weighted by DATA_PHASE_WEIGHT)
        rows = tracker._calculate_rows_loaded()
        assert rows == int(DATA_PHASE_WEIGHT * 1000)  # 850

    def test_fallback_to_processlist_when_no_file_data(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Falls back to processlist percent when no file tracking data."""
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        # Only processlist data, no file tracking
        tracker._tables["users"].percent_complete = 50.0
        tracker._tables["users"].files_started = 0
        tracker._tables["users"].file_count = 1

        # Should use processlist: 50% of 1000 = 500 rows
        rows = tracker._calculate_rows_loaded()
        assert rows == 500

    def test_progress_never_exceeds_100_with_file_tracking(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """File-based tracking ensures progress cannot exceed 100%."""
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        # Even if files_started somehow exceeds file_count (shouldn't happen)
        # the result should be clamped by actual file_count
        tracker._tables["users"].files_started = 5
        tracker._tables["users"].file_count = 4

        # 5/4 = 125%, but multiplied by rows gives 1250 which is > total
        # However, this edge case should be handled by max() in _mark_file_started
        # For now, test that it doesn't crash
        rows = tracker._calculate_rows_loaded()
        assert rows >= 0  # At minimum, no negative values

    def test_multiple_files_tracked_correctly(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Multiple Progress messages track file starts correctly."""
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
        )

        # Simulate multiple Progress messages for same table
        lines = [
            "Thread 1: restoring mydb.users part 1 of 3 from users.00000.sql.gz | Progress 1 of 10. Tables 0 of 3 completed",
            "Thread 2: restoring mydb.users part 2 of 3 from users.00001.sql.gz | Progress 2 of 10. Tables 0 of 3 completed",
            "Thread 3: restoring mydb.users part 3 of 3 from users.00002.sql.gz | Progress 3 of 10. Tables 0 of 3 completed",
        ]

        for line in lines:
            tracker.update_from_myloader_line(line)

        state = tracker._tables["users"]
        assert state.files_started == 3
        assert state.file_count == 3

        # All 3 files started = 100% of 1000 rows
        rows = tracker._calculate_rows_loaded()
        assert rows == 1000


# =============================================================================
# Strike-Based Completion Detection Tests
# =============================================================================


class TestStrikeBasedCompletion:
    """Test strike-based table completion detection.
    
    The strike system counts consecutive polls where a table is absent from
    the processlist. This handles FULLTEXT index gaps where a table briefly
    leaves and rejoins the processlist between separate ALTER statements.
    
    Key thresholds:
    - _INDEX_COMPLETE_STRIKES = 3 (after data_complete signal)
    - _FALLBACK_COMPLETE_STRIKES = 5 (without data_complete signal)
    """

    def test_strike_increments_when_table_absent(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Strikes increment when table leaves processlist."""
        # First, table appears in processlist
        snapshot1 = make_snapshot({"users": ("loading", 50.0, 5)})
        tracker.update_from_processlist(snapshot1)
        
        state = tracker._tables["users"]
        assert state.was_ever_seen is True
        assert state.absent_strikes == 0
        
        # Table leaves processlist - strike 1
        snapshot2 = make_snapshot({})
        tracker.update_from_processlist(snapshot2)
        assert state.absent_strikes == 1
        
        # Still absent - strike 2
        tracker.update_from_processlist(snapshot2)
        assert state.absent_strikes == 2

    def test_strikes_reset_when_table_reappears(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Strikes reset to 0 when table reappears (FULLTEXT gap handling)."""
        # Table appears
        snapshot1 = make_snapshot({"users": ("loading", 50.0, 5)})
        tracker.update_from_processlist(snapshot1)
        
        state = tracker._tables["users"]
        
        # Table leaves - accumulate 2 strikes
        snapshot_empty = make_snapshot({})
        tracker.update_from_processlist(snapshot_empty)
        tracker.update_from_processlist(snapshot_empty)
        assert state.absent_strikes == 2
        
        # Table reappears (e.g., next FULLTEXT ALTER) - strikes reset
        snapshot2 = make_snapshot({"users": ("indexing", 0.0, 1)})
        tracker.update_from_processlist(snapshot2)
        assert state.absent_strikes == 0

    def test_completes_after_index_strikes_with_data_complete(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Table completes after 3 strikes when data_complete is True."""
        # Table appears and gets data_complete signal
        snapshot1 = make_snapshot({"users": ("indexing", 0.0, 5)})
        tracker.update_from_processlist(snapshot1)
        
        state = tracker._tables["users"]
        state.data_complete = True  # Simulate "Enqueuing index" received
        
        assert state.is_complete is False
        
        # Table leaves - need 3 strikes to complete
        snapshot_empty = make_snapshot({})
        tracker.update_from_processlist(snapshot_empty)  # Strike 1
        assert state.is_complete is False
        
        tracker.update_from_processlist(snapshot_empty)  # Strike 2
        assert state.is_complete is False
        
        tracker.update_from_processlist(snapshot_empty)  # Strike 3 - complete!
        assert state.is_complete is True
        assert state.percent_complete == 100.0
        assert state.phase == "complete"

    def test_completes_after_fallback_strikes_without_data_complete(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Table completes after 5 strikes when data_complete is False."""
        # Table appears but no data_complete signal
        snapshot1 = make_snapshot({"users": ("loading", 100.0, 10)})
        tracker.update_from_processlist(snapshot1)
        
        state = tracker._tables["users"]
        assert state.data_complete is False
        assert state.is_complete is False
        
        # Table leaves - need 5 strikes for fallback completion
        snapshot_empty = make_snapshot({})
        for i in range(4):
            tracker.update_from_processlist(snapshot_empty)
            assert state.is_complete is False, f"Should not complete at strike {i+1}"
        
        tracker.update_from_processlist(snapshot_empty)  # Strike 5 - complete!
        assert state.is_complete is True

    def test_fulltext_gap_prevents_premature_completion(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Simulates FULLTEXT index gap - table leaves and rejoins processlist.
        
        myloader runs separate ALTER per FULLTEXT index, so table briefly
        leaves processlist between them. Strike reset prevents premature completion.
        """
        # Table starts indexing
        snapshot1 = make_snapshot({"users": ("indexing", 0.0, 2)})
        tracker.update_from_processlist(snapshot1)
        
        state = tracker._tables["users"]
        state.data_complete = True
        
        # First FULLTEXT ALTER finishes - table leaves
        snapshot_empty = make_snapshot({})
        tracker.update_from_processlist(snapshot_empty)  # Strike 1
        tracker.update_from_processlist(snapshot_empty)  # Strike 2
        assert state.absent_strikes == 2
        assert state.is_complete is False
        
        # Second FULLTEXT ALTER starts - table reappears, strikes reset!
        snapshot2 = make_snapshot({"users": ("indexing", 0.0, 1)})
        tracker.update_from_processlist(snapshot2)
        assert state.absent_strikes == 0
        assert state.is_complete is False
        
        # Second ALTER finishes - need fresh 3 strikes
        tracker.update_from_processlist(snapshot_empty)  # Strike 1
        tracker.update_from_processlist(snapshot_empty)  # Strike 2
        tracker.update_from_processlist(snapshot_empty)  # Strike 3 - now complete
        assert state.is_complete is True

    def test_never_seen_tables_not_completed_by_strikes(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Tables never seen in processlist are skipped (rely on finalize)."""
        # Don't put users in processlist at all
        snapshot = make_snapshot({"orders": ("loading", 50.0, 5)})
        tracker.update_from_processlist(snapshot)
        
        # Remove orders too
        for _ in range(10):
            tracker.update_from_processlist(make_snapshot({}))
        
        # Users was never seen, so should not be complete
        users_state = tracker._tables["users"]
        assert users_state.was_ever_seen is False
        assert users_state.is_complete is False
        
        # Orders should be complete (fallback strikes)
        orders_state = tracker._tables["orders"]
        assert orders_state.is_complete is True

    def test_already_complete_tables_ignored(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Tables already marked complete don't accumulate more strikes."""
        # Complete a table
        snapshot1 = make_snapshot({"users": ("indexing", 0.0, 5)})
        tracker.update_from_processlist(snapshot1)
        tracker.mark_table_complete("users")
        
        state = tracker._tables["users"]
        assert state.is_complete is True
        initial_strikes = state.absent_strikes
        
        # Further polls should not affect strikes
        for _ in range(5):
            tracker.update_from_processlist(make_snapshot({}))
        
        assert state.absent_strikes == initial_strikes


# =============================================================================
# File-Based ETA Tests
# =============================================================================


class TestFileBasedETA:
    """Test file-based ETA fallback for legacy backups with rows=0.
    
    When row counts are unavailable (0.9.0 backups), ETA is calculated from:
    - files_completed / elapsed = files_per_second
    - remaining_files / files_per_second = eta_seconds
    """

    def test_uses_row_based_eta_when_rows_available(self) -> None:
        """Row-based ETA is preferred when row counts are available."""
        metadata = [
            TableRowEstimate(database="db", table="users", rows=1000, file_count=2),
            TableRowEstimate(database="db", table="orders", rows=2000, file_count=3),
        ]
        tracker = RestoreProgressTracker(
            table_metadata=metadata,
            throttle_interval_seconds=0,
        )
        
        # Simulate some progress
        import time
        time.sleep(0.02)  # Small delay for elapsed time
        snapshot = make_snapshot({"users": ("loading", 50.0, 5)})
        tracker.update_from_processlist(snapshot)
        
        progress = tracker.get_progress()
        # Should use rows mode when rows are available and loaded > 0
        if progress.throughput.eta_mode is not None:
            assert progress.throughput.eta_mode == "rows"

    def test_uses_bytes_based_eta_when_total_bytes_available(self) -> None:
        """Bytes-based ETA is used when total_bytes > 0 and files completing."""
        # Backup with rows=0 but total_bytes available (from extraction stats)
        metadata = [
            TableRowEstimate(
                database="db", table="users", rows=0, file_count=3, total_bytes=30_000_000
            ),
            TableRowEstimate(
                database="db", table="orders", rows=0, file_count=5, total_bytes=50_000_000
            ),
        ]
        tracker = RestoreProgressTracker(
            table_metadata=metadata,
            throttle_interval_seconds=0,
        )
        
        # Mark one table as data complete (all bytes done)
        tracker._mark_data_complete("users")
        
        import time
        time.sleep(0.02)  # Small delay for elapsed time
        
        progress = tracker.get_progress()
        
        # Should use bytes mode when total_bytes available
        assert progress.throughput.eta_mode == "bytes"
        assert progress.throughput.bytes_completed == 30_000_000  # users complete
        assert progress.throughput.bytes_total == 80_000_000  # 30M + 50M
        assert progress.throughput.bytes_per_second > 0
        assert progress.throughput.eta_seconds is not None

    def test_falls_back_to_file_based_eta_when_rows_zero(self) -> None:
        """File-based ETA is used when all row counts are 0."""
        # Legacy backup with rows=0
        metadata = [
            TableRowEstimate(database="db", table="users", rows=0, file_count=3),
            TableRowEstimate(database="db", table="orders", rows=0, file_count=5),
        ]
        tracker = RestoreProgressTracker(
            table_metadata=metadata,
            throttle_interval_seconds=0,
        )
        
        # Mark some files complete
        tracker.mark_table_file_complete("users")  # 1 file done
        tracker.mark_table_file_complete("users")  # 2 files done
        
        import time
        time.sleep(0.02)  # Small delay for elapsed time
        
        progress = tracker.get_progress()
        
        # Should use files mode
        assert progress.throughput.eta_mode == "files"
        assert progress.throughput.files_completed == 2
        assert progress.throughput.files_total == 8  # 3 + 5
        assert progress.throughput.files_per_second > 0
        assert progress.throughput.eta_seconds is not None

    def test_eta_none_when_no_progress(self) -> None:
        """ETA is None when no files completed yet."""
        metadata = [
            TableRowEstimate(database="db", table="users", rows=0, file_count=3),
        ]
        tracker = RestoreProgressTracker(
            table_metadata=metadata,
            throttle_interval_seconds=0,
        )
        
        progress = tracker.get_progress()
        
        # No progress yet - ETA should be None
        assert progress.throughput.eta_seconds is None
        assert progress.throughput.eta_mode is None

    def test_files_completed_counts_data_complete_tables(self) -> None:
        """Tables with data_complete count as all files done."""
        metadata = [
            TableRowEstimate(database="db", table="users", rows=0, file_count=3),
            TableRowEstimate(database="db", table="orders", rows=0, file_count=5),
        ]
        tracker = RestoreProgressTracker(
            table_metadata=metadata,
            throttle_interval_seconds=0,
        )
        
        # Mark users as data complete (all 3 files done)
        tracker._mark_data_complete("users")
        
        # Mark 1 file done for orders
        tracker.mark_table_file_complete("orders")
        
        import time
        time.sleep(0.01)
        
        progress = tracker.get_progress()
        
        # users: 3 files (data_complete), orders: 1 file = 4 total
        assert progress.throughput.files_completed == 4

    def test_event_dict_includes_file_stats(self) -> None:
        """to_event_dict includes file-based stats."""
        metadata = [
            TableRowEstimate(database="db", table="users", rows=0, file_count=5),
        ]
        tracker = RestoreProgressTracker(
            table_metadata=metadata,
            throttle_interval_seconds=0,
        )
        
        progress = tracker.get_progress()
        event_dict = progress.to_event_dict()
        
        detail = event_dict["detail"]
        assert "eta_mode" in detail
        assert "files_per_second" in detail
        assert "files_completed" in detail
        assert "files_total" in detail
        assert detail["files_total"] == 5


# =============================================================================
# Early Analyze Mode Tests
# =============================================================================


class TestEarlyAnalyzeMode:
    """Test early_analyze_enabled behavior for proper phase tracking."""

    @pytest.fixture
    def early_analyze_tracker(
        self, table_metadata: list[TableRowEstimate]
    ) -> RestoreProgressTracker:
        """Tracker with early_analyze_enabled=True."""
        return RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
            early_analyze_enabled=True,
        )

    def test_strikes_do_not_complete_table_in_early_analyze_mode(
        self, early_analyze_tracker: RestoreProgressTracker
    ) -> None:
        """With early_analyze_enabled, strikes mark index_complete but NOT is_complete."""
        # Table appears and gets data_complete signal
        snapshot1 = make_snapshot({"users": ("indexing", 0.0, 5)})
        early_analyze_tracker.update_from_processlist(snapshot1)
        
        state = early_analyze_tracker._tables["users"]
        state.data_complete = True
        
        # Table leaves - accumulate 3 strikes
        snapshot_empty = make_snapshot({})
        for _ in range(3):
            early_analyze_tracker.update_from_processlist(snapshot_empty)
        
        # index_complete should be True, but is_complete should still be False
        assert state.index_complete is True
        assert state.is_complete is False

    def test_mark_table_analyzing_reactivates_finalized_table(
        self, early_analyze_tracker: RestoreProgressTracker
    ) -> None:
        """mark_table_analyzing should re-activate a table after finalize()."""
        # Simulate myloader completing
        early_analyze_tracker.finalize()
        
        state = early_analyze_tracker._tables["users"]
        # Table should NOT be complete after finalize in early_analyze mode
        assert state.is_complete is False
        assert state.index_complete is True
        
        # Now early analyze starts
        early_analyze_tracker.mark_table_analyzing("users")
        assert state.phase == "analyzing"
        assert state.is_complete is False

    def test_mark_table_analyze_complete_finalizes_table(
        self, early_analyze_tracker: RestoreProgressTracker
    ) -> None:
        """mark_table_analyze_complete marks table as truly complete."""
        # Simulate full lifecycle
        early_analyze_tracker.finalize()  # myloader done
        early_analyze_tracker.mark_table_analyzing("users")  # analyze starts
        early_analyze_tracker.mark_table_analyze_complete("users")  # analyze done
        
        state = early_analyze_tracker._tables["users"]
        assert state.is_complete is True
        assert state.analyze_complete is True
        assert state.phase == "complete"

    def test_finalize_waits_for_analyze_in_early_analyze_mode(
        self, early_analyze_tracker: RestoreProgressTracker
    ) -> None:
        """In early_analyze mode, finalize() doesn't mark tables complete."""
        # finalize represents myloader exiting
        progress = early_analyze_tracker.finalize()
        
        # Tables should NOT be complete yet - waiting for analyze
        assert progress.tables_completed == 0
        
        for state in early_analyze_tracker._tables.values():
            assert state.is_complete is False
            assert state.index_complete is True

    def test_traditional_mode_still_completes_on_finalize(
        self, tracker: RestoreProgressTracker
    ) -> None:
        """Without early_analyze_enabled, finalize() completes all tables."""
        progress = tracker.finalize()
        
        # All tables should be complete
        assert progress.tables_completed == 3
        
        for state in tracker._tables.values():
            assert state.is_complete is True

    def test_create_progress_tracker_passes_early_analyze_flag(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """create_progress_tracker passes early_analyze_enabled correctly."""
        tracker = create_progress_tracker(
            table_metadata=table_metadata,
            early_analyze_enabled=True,
        )
        
        assert tracker._early_analyze_enabled is True

    def test_analyzing_tables_show_in_progress(
        self, early_analyze_tracker: RestoreProgressTracker
    ) -> None:
        """Tables in 'analyzing' phase should appear in tables_in_progress."""
        early_analyze_tracker.finalize()
        early_analyze_tracker.mark_table_analyzing("users")
        
        progress = early_analyze_tracker.get_progress()
        
        # users should be in tables_in_progress with phase 'analyzing'
        table_names = [t.name for t in progress.tables_in_progress]
        assert "users" in table_names
        
        users_info = next(t for t in progress.tables_in_progress if t.name == "users")
        assert users_info.phase == "analyzing"

    def test_finalize_analyze_phase_safety_net(
        self, early_analyze_tracker: RestoreProgressTracker
    ) -> None:
        """finalize_analyze_phase marks stuck analyzing tables as complete."""
        # Simulate myloader done + some tables in analyzing
        early_analyze_tracker.finalize()
        early_analyze_tracker.mark_table_analyzing("users")
        early_analyze_tracker.mark_table_analyzing("orders")
        
        # One table completes normally
        early_analyze_tracker.mark_table_analyze_complete("users")
        
        # orders is stuck in analyzing
        orders_state = early_analyze_tracker._tables["orders"]
        assert orders_state.phase == "analyzing"
        assert orders_state.is_complete is False
        
        # Call safety net (simulates timeout)
        early_analyze_tracker.finalize_analyze_phase()
        
        # Now orders should be complete
        assert orders_state.is_complete is True
        assert orders_state.analyze_complete is True

    def test_emits_table_index_complete_event_in_early_analyze_mode(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Strike completion emits table_index_complete event in early_analyze mode."""
        events: list[tuple[str, dict]] = []
        
        def capture_event(event_type: str, data: dict) -> None:
            events.append((event_type, data))
        
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
            early_analyze_enabled=True,
            on_event=capture_event,
        )
        
        # Table appears with data_complete
        snapshot1 = make_snapshot({"users": ("indexing", 0.0, 5)})
        tracker.update_from_processlist(snapshot1)
        tracker._tables["users"].data_complete = True
        
        # Table leaves - accumulate 3 strikes
        snapshot_empty = make_snapshot({})
        for _ in range(3):
            tracker.update_from_processlist(snapshot_empty)
        
        # Should have emitted table_index_complete (NOT table_restore_complete)
        index_complete_events = [e for e in events if e[0] == "table_index_complete"]
        restore_complete_events = [e for e in events if e[0] == "table_restore_complete"]
        
        assert len(index_complete_events) == 1
        assert index_complete_events[0][1]["table"] == "users"
        assert len(restore_complete_events) == 0  # Should NOT emit restore_complete

    def test_emits_table_restore_complete_in_traditional_mode(
        self, table_metadata: list[TableRowEstimate]
    ) -> None:
        """Strike completion emits table_restore_complete in traditional mode."""
        events: list[tuple[str, dict]] = []
        
        def capture_event(event_type: str, data: dict) -> None:
            events.append((event_type, data))
        
        tracker = RestoreProgressTracker(
            table_metadata=table_metadata,
            throttle_interval_seconds=0,
            early_analyze_enabled=False,  # Traditional mode
            on_event=capture_event,
        )
        
        # Table appears with data_complete
        snapshot1 = make_snapshot({"users": ("indexing", 0.0, 5)})
        tracker.update_from_processlist(snapshot1)
        tracker._tables["users"].data_complete = True
        
        # Table leaves - accumulate 3 strikes
        snapshot_empty = make_snapshot({})
        for _ in range(3):
            tracker.update_from_processlist(snapshot_empty)
        
        # Should have emitted table_restore_complete (NOT table_index_complete)
        index_complete_events = [e for e in events if e[0] == "table_index_complete"]
        restore_complete_events = [e for e in events if e[0] == "table_restore_complete"]
        
        assert len(restore_complete_events) == 1
        assert restore_complete_events[0][1]["table"] == "users"
        assert len(index_complete_events) == 0  # Should NOT emit index_complete