"""Tests for RestoreStateTracker coordinating log parser and processlist monitor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from pulldb.worker.myloader_log_parser import MyloaderLogParser, TablePhase, TableState
from pulldb.worker.processlist_monitor import ProcesslistSnapshot, TableProgress
from pulldb.worker.restore_state_tracker import (
    CombinedPhase,
    CombinedTableState,
    RestoreStateTracker,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def log_parser() -> MyloaderLogParser:
    """Fresh log parser instance."""
    return MyloaderLogParser()


@pytest.fixture
def tracker(log_parser: MyloaderLogParser) -> RestoreStateTracker:
    """Fresh tracker instance with log parser."""
    return RestoreStateTracker(log_parser=log_parser)


@pytest.fixture
def tracker_with_callback(log_parser: MyloaderLogParser) -> tuple[RestoreStateTracker, MagicMock]:
    """Tracker with mocked event callback."""
    callback = MagicMock()
    tracker = RestoreStateTracker(log_parser=log_parser, event_callback=callback)
    return tracker, callback


def make_snapshot(tables: dict[str, tuple[str, float, int | None]] | None = None) -> ProcesslistSnapshot:
    """Create ProcesslistSnapshot from dict.
    
    Args:
        tables: Dict of table_name -> (phase, percent, running_seconds)
                phase is 'loading' or 'indexing'
    """
    import time
    table_progress = {}
    if tables:
        for name, (phase, pct, secs) in tables.items():
            table_progress[name] = TableProgress(
                table=name,
                percent_complete=pct,
                phase=phase,
                running_seconds=secs or 0,
            )
    
    return ProcesslistSnapshot(
        tables=table_progress,
        active_threads=len(table_progress),
        timestamp=time.monotonic(),
    )


# ============================================================================
# Basic Initialization Tests
# ============================================================================

class TestInitialization:
    """Test tracker initialization."""
    
    def test_creates_empty_tracker(self, log_parser: MyloaderLogParser) -> None:
        """Tracker starts with no states."""
        tracker = RestoreStateTracker(log_parser=log_parser)
        assert len(tracker.get_all_states()) == 0
    
    def test_accepts_event_callback(self, log_parser: MyloaderLogParser) -> None:
        """Tracker accepts optional callback."""
        callback = MagicMock()
        tracker = RestoreStateTracker(log_parser=log_parser, event_callback=callback)
        assert tracker._event_callback is callback
    
    def test_accepts_stale_threshold(self, log_parser: MyloaderLogParser) -> None:
        """Tracker accepts custom stale threshold."""
        tracker = RestoreStateTracker(log_parser=log_parser, stale_threshold_seconds=30.0)
        assert tracker._stale_threshold == 30.0


# ============================================================================
# Processlist Update Tests
# ============================================================================

class TestProcesslistUpdates:
    """Test updating from processlist snapshots."""
    
    def test_creates_state_from_processlist(self, tracker: RestoreStateTracker) -> None:
        """Processlist creates state for new tables."""
        snapshot = make_snapshot({"db.users": ("loading", 25.0, None)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("db.users")
        assert state is not None
        assert state.table_name == "db.users"
        assert state.processlist_phase == "loading"
        assert state.percent_complete == 25.0
    
    def test_updates_loading_phase(self, tracker: RestoreStateTracker) -> None:
        """Loading from processlist sets LOADING_DATA phase."""
        snapshot = make_snapshot({"db.orders": ("loading", 50.0, None)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("db.orders")
        assert state.phase == CombinedPhase.LOADING_DATA
    
    def test_updates_indexing_phase(self, tracker: RestoreStateTracker) -> None:
        """Indexing from processlist sets REBUILDING_INDEXES phase."""
        snapshot = make_snapshot({"db.products": ("indexing", 0.0, 45)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("db.products")
        assert state.phase == CombinedPhase.REBUILDING_INDEXES
        assert state.index_running_seconds == 45
    
    def test_tracks_last_seen_time(self, tracker: RestoreStateTracker) -> None:
        """Records when table was last seen in processlist."""
        snapshot = make_snapshot({"db.users": ("loading", 30.0, None)})
        before = datetime.now(UTC)
        tracker.update_from_processlist(snapshot)
        after = datetime.now(UTC)
        
        state = tracker.get_table_state("db.users")
        assert state.last_seen_in_processlist is not None
        assert before <= state.last_seen_in_processlist <= after
    
    def test_handles_none_snapshot(self, tracker: RestoreStateTracker) -> None:
        """Gracefully handles None snapshot."""
        tracker.update_from_processlist(None)
        assert len(tracker.get_all_states()) == 0


# ============================================================================
# Log Parser Merge Tests
# ============================================================================

class TestLogParserMerge:
    """Test merging states from log parser."""
    
    def test_merges_log_parser_state(
        self, log_parser: MyloaderLogParser, tracker: RestoreStateTracker
    ) -> None:
        """Log parser state is merged on processlist update."""
        # Feed log parser (format: Thread X: restoring db.table part X of Y from file)
        log_parser.parse_line("Thread 1: restoring mydatabase.users part 1 of 4 from users.00001.sql")
        log_parser.parse_line("Thread 1: restoring mydatabase.users part 2 of 4 from users.00002.sql")

        # Trigger merge via processlist update
        snapshot = make_snapshot({"mydatabase.users": ("loading", 50.0, None)})
        tracker.update_from_processlist(snapshot)

        state = tracker.get_table_state("mydatabase.users")
        assert state.log_phase == TablePhase.LOADING_DATA
        assert state.data_parts_completed == 2
        assert state.data_parts_total == 4
    
    def test_log_parser_data_complete_updates_phase(
        self, log_parser: MyloaderLogParser, tracker: RestoreStateTracker
    ) -> None:
        """DATA_COMPLETE from log parser updates combined phase."""
        # Simulate data complete (data progress then enqueue index)
        log_parser.parse_line("Thread 1: restoring db.tbl part 1 of 1 from tbl.00001.sql")
        log_parser.parse_line("Thread 1: Enqueuing index for table: db.tbl")

        snapshot = make_snapshot({})
        tracker.update_from_processlist(snapshot)

        state = tracker.get_table_state("db.tbl")
        # DATA_COMPLETE because log parser saw enqueue index
        assert state is not None
        assert state.phase == CombinedPhase.DATA_COMPLETE
    
    def test_log_parser_index_phase(
        self, log_parser: MyloaderLogParser, tracker: RestoreStateTracker
    ) -> None:
        """Restoring indexes message sets REBUILDING_INDEXES."""
        # First enqueue, then start restoring indexes (correct format)
        log_parser.parse_line("Thread 1: Enqueuing index for table: db.tbl")
        log_parser.parse_line("Thread 1: restoring indexes db.tbl from index")
        
        snapshot = make_snapshot({})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("db.tbl")
        assert state is not None
        assert state.phase == CombinedPhase.REBUILDING_INDEXES


# ============================================================================
# Completion Detection Tests
# ============================================================================

class TestCompletionDetection:
    """Test table completion detection."""
    
    def test_completes_when_leaves_processlist(
        self, log_parser: MyloaderLogParser
    ) -> None:
        """Table completes when it leaves processlist after indexing."""
        tracker = RestoreStateTracker(log_parser=log_parser, stale_threshold_seconds=0.1)
        
        # Table indexing
        snapshot1 = make_snapshot({"db.tbl": ("indexing", 0.0, 10)})
        tracker.update_from_processlist(snapshot1)
        assert tracker.get_table_state("db.tbl").phase == CombinedPhase.REBUILDING_INDEXES
        
        # Simulate time passing and table leaving processlist
        import time
        time.sleep(0.15)
        
        snapshot2 = make_snapshot({})  # Table gone
        tracker.update_from_processlist(snapshot2)
        
        state = tracker.get_table_state("db.tbl")
        assert state.phase == CombinedPhase.COMPLETE
    
    def test_emits_event_on_completion(
        self, log_parser: MyloaderLogParser
    ) -> None:
        """Emits table_restore_complete event on completion."""
        callback = MagicMock()
        tracker = RestoreStateTracker(
            log_parser=log_parser,
            event_callback=callback,
            stale_threshold_seconds=0.1
        )
        
        # Table indexing then leaves
        snapshot1 = make_snapshot({"db.tbl": ("indexing", 0.0, 25)})
        tracker.update_from_processlist(snapshot1)
        
        import time
        time.sleep(0.15)
        
        snapshot2 = make_snapshot({})
        tracker.update_from_processlist(snapshot2)
        
        # Check callback was called
        callback.assert_called()
        call_args = callback.call_args
        assert call_args[0][0] == "table_restore_complete"
        assert call_args[0][1]["table"] == "db.tbl"
        assert call_args[0][1]["index_duration_seconds"] == 25
    
    def test_mark_all_complete(
        self, tracker: RestoreStateTracker
    ) -> None:
        """mark_all_complete marks all tables as COMPLETE."""
        # Add some tables in various phases
        snapshot = make_snapshot({
            "db.tbl1": ("loading", 50.0, None),
            "db.tbl2": ("indexing", 0.0, 10),
        })
        tracker.update_from_processlist(snapshot)
        
        tracker.mark_all_complete()
        
        for state in tracker.get_all_states().values():
            assert state.phase == CombinedPhase.COMPLETE


# ============================================================================
# Event Emission Tests
# ============================================================================

class TestEventEmission:
    """Test event callback emissions."""
    
    def test_emits_index_rebuild_confirmed(
        self, log_parser: MyloaderLogParser
    ) -> None:
        """Emits table_index_rebuild_confirmed when processlist shows indexing."""
        callback = MagicMock()
        tracker = RestoreStateTracker(log_parser=log_parser, event_callback=callback)
        
        # First loading
        snapshot1 = make_snapshot({"db.tbl": ("loading", 90.0, None)})
        tracker.update_from_processlist(snapshot1)
        
        # Then indexing
        snapshot2 = make_snapshot({"db.tbl": ("indexing", 0.0, 5)})
        tracker.update_from_processlist(snapshot2)
        
        # Check index rebuild event
        call_args_list = callback.call_args_list
        assert any(
            call[0][0] == "table_index_rebuild_confirmed" and call[0][1]["table"] == "db.tbl"
            for call in call_args_list
        )
    
    def test_callback_error_logged_not_raised(
        self, log_parser: MyloaderLogParser
    ) -> None:
        """Callback errors are logged but don't raise."""
        callback = MagicMock(side_effect=ValueError("boom"))
        tracker = RestoreStateTracker(log_parser=log_parser, event_callback=callback)
        
        # Should not raise
        snapshot = make_snapshot({"db.tbl": ("indexing", 0.0, 10)})
        tracker.update_from_processlist(snapshot)
        
        # Confirm callback was called (even though it raised)
        callback.assert_called()


# ============================================================================
# Query Methods Tests
# ============================================================================

class TestQueryMethods:
    """Test state query methods."""
    
    def test_get_table_state_by_full_name(self, tracker: RestoreStateTracker) -> None:
        """Get state by full qualified name."""
        snapshot = make_snapshot({"mydb.mytable": ("loading", 30.0, None)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("mydb.mytable")
        assert state is not None
        assert state.table_name == "mydb.mytable"
    
    def test_get_table_state_by_short_name(self, tracker: RestoreStateTracker) -> None:
        """Get state by just table name (partial match)."""
        snapshot = make_snapshot({"mydb.mytable": ("loading", 30.0, None)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("mytable")
        assert state is not None
        assert state.table_name == "mydb.mytable"
    
    def test_get_table_state_not_found(self, tracker: RestoreStateTracker) -> None:
        """Returns None for unknown table."""
        assert tracker.get_table_state("nonexistent") is None
    
    def test_get_tables_in_phase(self, tracker: RestoreStateTracker) -> None:
        """Get all tables in specific phase."""
        snapshot = make_snapshot({
            "db.tbl1": ("loading", 50.0, None),
            "db.tbl2": ("loading", 75.0, None),
            "db.tbl3": ("indexing", 0.0, 10),
        })
        tracker.update_from_processlist(snapshot)
        
        loading = tracker.get_tables_in_phase(CombinedPhase.LOADING_DATA)
        indexing = tracker.get_tables_in_phase(CombinedPhase.REBUILDING_INDEXES)
        
        assert len(loading) == 2
        assert len(indexing) == 1
        assert "db.tbl3" in indexing
    
    def test_get_summary(self, tracker: RestoreStateTracker) -> None:
        """Get summary of restore state."""
        snapshot = make_snapshot({
            "db.tbl1": ("loading", 50.0, None),
            "db.tbl2": ("indexing", 0.0, 30),
            "db.tbl3": ("indexing", 0.0, 20),
        })
        tracker.update_from_processlist(snapshot)
        
        summary = tracker.get_summary()
        
        assert summary["total_tables"] == 3
        assert summary["total_index_time_seconds"] == 50
        assert "tables_by_phase" in summary
        assert summary["tables_by_phase"]["LOADING_DATA"] == 1
        assert summary["tables_by_phase"]["REBUILDING_INDEXES"] == 2


# ============================================================================
# CombinedTableState Tests
# ============================================================================

class TestCombinedTableState:
    """Test CombinedTableState dataclass."""
    
    def test_is_complete_property(self) -> None:
        """is_complete returns True only for COMPLETE phase."""
        state = CombinedTableState(table_name="test")
        assert not state.is_complete
        
        state.phase = CombinedPhase.COMPLETE
        assert state.is_complete
    
    def test_is_indexing_property(self) -> None:
        """is_indexing returns True only for REBUILDING_INDEXES phase."""
        state = CombinedTableState(table_name="test")
        assert not state.is_indexing
        
        state.phase = CombinedPhase.REBUILDING_INDEXES
        assert state.is_indexing


# ============================================================================
# Thread Safety Tests
# ============================================================================

class TestThreadSafety:
    """Test thread-safe operations."""
    
    def test_concurrent_updates(self, tracker: RestoreStateTracker) -> None:
        """Multiple threads can update without corruption."""
        import threading
        
        errors = []
        
        def update_worker(table_suffix: int) -> None:
            try:
                for i in range(10):
                    snapshot = make_snapshot({
                        f"db.tbl{table_suffix}": ("loading", float(i * 10), None)
                    })
                    tracker.update_from_processlist(snapshot)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=update_worker, args=(i,))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(tracker.get_all_states()) == 5


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests with log parser."""
    
    def test_full_restore_lifecycle(
        self, log_parser: MyloaderLogParser
    ) -> None:
        """Simulate full table restore lifecycle."""
        callback = MagicMock()
        tracker = RestoreStateTracker(
            log_parser=log_parser,
            event_callback=callback,
            stale_threshold_seconds=0.1
        )
        
        # Phase 1: Data loading (from log) 
        # Format: Thread X: restoring db.table part X of Y from file
        log_parser.parse_line("Thread 1: restoring prod.orders part 1 of 3 from orders.00001.sql")
        snapshot = make_snapshot({"prod.orders": ("loading", 33.0, None)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("prod.orders")
        assert state.phase == CombinedPhase.LOADING_DATA
        assert state.data_parts_completed == 1
        
        # Phase 2: More data
        log_parser.parse_line("Thread 1: restoring prod.orders part 2 of 3 from orders.00002.sql")
        log_parser.parse_line("Thread 2: restoring prod.orders part 3 of 3 from orders.00003.sql")
        snapshot = make_snapshot({"prod.orders": ("loading", 99.0, None)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("prod.orders")
        assert state.data_parts_completed == 3
        
        # Phase 3: Index rebuild (from log + processlist)
        log_parser.parse_line("Thread 1: Enqueuing index for table: prod.orders")
        snapshot = make_snapshot({"prod.orders": ("indexing", 0.0, 15)})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("prod.orders")
        assert state.phase == CombinedPhase.REBUILDING_INDEXES
        
        # Phase 4: Complete (table leaves processlist)
        import time
        time.sleep(0.15)
        
        snapshot = make_snapshot({})
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("prod.orders")
        assert state.phase == CombinedPhase.COMPLETE
        
        # Verify completion event
        complete_calls = [
            call for call in callback.call_args_list
            if call[0][0] == "table_restore_complete"
        ]
        assert len(complete_calls) == 1
