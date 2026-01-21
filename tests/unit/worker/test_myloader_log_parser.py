"""Tests for myloader log parser module.

Tests cover:
1. Individual regex pattern matching
2. MyloaderLogParser state machine
3. Event emission
4. Edge cases and malformed input

HCA Layer: tests
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from pulldb.worker.myloader_log_parser import (
    LogParseResult,
    MyloaderLogParser,
    TablePhase,
    TableState,
    RE_DATA_PROGRESS,
    RE_ENQUEUE_INDEX,
    RE_INDEX_THREAD_ENDING,
    RE_LOADER_THREAD_ENDING,
    RE_OVERALL_PROGRESS,
    RE_RESTORING_INDEX,
    RE_RESTORING_INDEXES,
)


class TestRegexPatterns:
    """Test individual regex pattern matching against myloader output."""
    
    def test_enqueue_index_pattern(self) -> None:
        """Matches 'Thread X: Enqueuing index for table: db.table'."""
        line = "Thread 5: Enqueuing index for table: staging_abc123.users"
        match = RE_ENQUEUE_INDEX.search(line)
        assert match is not None
        assert match.group(1) == "5"
        assert match.group(2) == "staging_abc123"
        assert match.group(3) == "users"
    
    def test_enqueue_index_negative_thread(self) -> None:
        """Thread ID can be -1 per myloader source code."""
        line = "Thread -1: Enqueuing index for table: staging.changeLog"
        match = RE_ENQUEUE_INDEX.search(line)
        assert match is not None
        assert match.group(1) == "-1"
        assert match.group(2) == "staging"
        assert match.group(3) == "changeLog"
    
    def test_enqueue_index_with_message_prefix(self) -> None:
        """Handles ** Message: timestamp prefix."""
        line = "** Message: 06:02:20.155: Thread 0: Enqueuing index for table: brunodfoxpest_655929085e57.changeLog"
        match = RE_ENQUEUE_INDEX.search(line)
        assert match is not None
        assert match.group(2) == "brunodfoxpest_655929085e57"
        assert match.group(3) == "changeLog"
    
    def test_restoring_index_pattern(self) -> None:
        """Matches 'restoring index: db.table'."""
        line = "restoring index: foxpest.changeLog"
        match = RE_RESTORING_INDEX.search(line)
        assert match is not None
        assert match.group(1) == "foxpest"
        assert match.group(2) == "changeLog"
    
    def test_restoring_index_with_prefix(self) -> None:
        """Handles g_message prefix."""
        line = "** Message: 06:02:20.155: restoring index: foxpest.changeLog"
        match = RE_RESTORING_INDEX.search(line)
        assert match is not None
        assert match.group(1) == "foxpest"
        assert match.group(2) == "changeLog"
    
    def test_restoring_indexes_pattern(self) -> None:
        """Matches 'Thread X: restoring indexes db.table from index'."""
        line = "Thread 3: restoring indexes staging_abc.orders from index file"
        match = RE_RESTORING_INDEXES.search(line)
        assert match is not None
        assert match.group(1) == "3"
        assert match.group(2) == "staging_abc"
        assert match.group(3) == "orders"
    
    def test_data_progress_pattern(self) -> None:
        """Matches 'Thread X: restoring db.table part N of M from file'."""
        line = "Thread 2: restoring staging_abc.users part 3 of 10 from users.00002.sql.gz | Progress 45 of 120"
        match = RE_DATA_PROGRESS.search(line)
        assert match is not None
        assert match.group(1) == "2"           # thread_id
        assert match.group(2) == "staging_abc" # target_db
        assert match.group(3) == "users"       # table_name
        assert match.group(4) == "3"           # part
        assert match.group(5) == "10"          # total
        assert "users.00002.sql.gz" in match.group(6)  # filename
    
    def test_overall_progress_pattern(self) -> None:
        """Matches 'Progress X of Y. Tables A of B completed'."""
        line = "Progress 45 of 120. Tables 5 of 15 completed"
        match = RE_OVERALL_PROGRESS.search(line)
        assert match is not None
        assert match.group(1) == "45"   # progress
        assert match.group(2) == "120"  # total
        assert match.group(3) == "5"    # tables done
        assert match.group(4) == "15"   # tables total
    
    def test_loader_thread_ending_pattern(self) -> None:
        """Matches 'L-Thread X: ending'."""
        line = "L-Thread 3: ending"
        match = RE_LOADER_THREAD_ENDING.search(line)
        assert match is not None
        assert match.group(1) == "3"
    
    def test_index_thread_ending_pattern(self) -> None:
        """Matches 'I-Thread X: ending'."""
        line = "I-Thread 5: ending"
        match = RE_INDEX_THREAD_ENDING.search(line)
        assert match is not None
        assert match.group(1) == "5"
    
    def test_non_matching_lines(self) -> None:
        """Various lines that should NOT match any pattern."""
        non_matching = [
            "Starting myloader",
            "Connected to MySQL 8.0.34",
            "Thread 1: Creating table users",
            "Some random log output",
            "",
        ]
        for line in non_matching:
            assert RE_ENQUEUE_INDEX.search(line) is None
            assert RE_RESTORING_INDEX.search(line) is None


class TestMyloaderLogParser:
    """Test MyloaderLogParser state machine."""
    
    def test_initial_state(self) -> None:
        """Parser starts with empty state."""
        parser = MyloaderLogParser()
        assert parser.get_all_states() == {}
        summary = parser.get_summary()
        assert summary["tables_tracked"] == 0
    
    def test_data_progress_creates_table_state(self) -> None:
        """Data progress message creates table state."""
        parser = MyloaderLogParser()
        line = "Thread 1: restoring staging_db.users part 1 of 5 from users.00000.sql.gz | Progress 1 of 50"
        
        result = parser.parse_line(line)
        
        assert result.event_type == "table_data_progress"
        assert result.event_data["table"] == "users"
        assert result.event_data["part"] == 1
        assert result.event_data["total"] == 5
        
        state = parser.get_table_state("staging_db.users")
        assert state is not None
        assert state.phase == TablePhase.LOADING_DATA
        assert state.data_parts_completed == 1
        assert state.data_parts_total == 5
    
    def test_enqueue_index_transitions_to_data_complete(self) -> None:
        """Enqueue index message transitions table to DATA_COMPLETE."""
        parser = MyloaderLogParser()
        
        # First, some data progress
        parser.parse_line("Thread 1: restoring staging_db.users part 5 of 5 from users.00004.sql.gz | Progress 5 of 50")
        
        # Then index enqueue
        result = parser.parse_line("Thread 1: Enqueuing index for table: staging_db.users")
        
        assert result.event_type == "table_index_rebuild_queued"
        assert result.phase_change == TablePhase.DATA_COMPLETE
        
        state = parser.get_table_state("staging_db.users")
        assert state.phase == TablePhase.DATA_COMPLETE
        assert state.index_started_at is not None
    
    def test_restoring_index_transitions_to_rebuilding(self) -> None:
        """Restoring index message transitions to REBUILDING_INDEXES."""
        parser = MyloaderLogParser()
        
        # Set up initial state
        parser.parse_line("Thread 1: restoring staging_db.users part 5 of 5 from users.00004.sql.gz | Progress 5 of 50")
        parser.parse_line("Thread 1: Enqueuing index for table: staging_db.users")
        
        # Index rebuild starts
        result = parser.parse_line("restoring index: source_db.users")
        
        assert result.event_type == "table_index_rebuild_started"
        assert result.phase_change == TablePhase.REBUILDING_INDEXES
    
    def test_event_callback_invoked(self) -> None:
        """Event callback is called when events occur."""
        callback = Mock()
        parser = MyloaderLogParser(event_callback=callback)
        
        parser.parse_line("Thread 1: Enqueuing index for table: staging_db.users")
        
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] == "table_index_rebuild_queued"
        assert call_args[0][1]["table"] == "users"
    
    def test_overall_progress_tracked(self) -> None:
        """Overall progress is extracted from log lines."""
        parser = MyloaderLogParser()
        
        parser.parse_line("Thread 1: restoring staging_db.users part 1 of 5 from users.00000.sql.gz | Progress 45 of 120. Tables 5 of 15 completed")
        
        summary = parser.get_summary()
        assert summary["overall_progress"] == 45
        assert summary["overall_total"] == 120
        assert summary["tables_completed"] == 5
        assert summary["tables_total"] == 15
    
    def test_thread_endings_counted(self) -> None:
        """Loader and index thread endings are counted."""
        parser = MyloaderLogParser()
        
        parser.parse_line("L-Thread 1: ending")
        parser.parse_line("L-Thread 2: ending")
        parser.parse_line("I-Thread 1: ending")
        
        summary = parser.get_summary()
        assert summary["loader_threads_ended"] == 2
        assert summary["index_threads_ended"] == 1
    
    def test_get_tables_in_phase(self) -> None:
        """Can filter tables by phase."""
        parser = MyloaderLogParser()
        
        # Create tables in different phases
        parser.parse_line("Thread 1: restoring staging_db.table1 part 1 of 2 from t1.sql.gz | Progress 1 of 10")
        parser.parse_line("Thread 2: restoring staging_db.table2 part 2 of 2 from t2.sql.gz | Progress 2 of 10")
        parser.parse_line("Thread 1: Enqueuing index for table: staging_db.table2")
        
        loading = parser.get_tables_in_phase(TablePhase.LOADING_DATA)
        queued = parser.get_tables_in_phase(TablePhase.DATA_COMPLETE)
        
        assert "staging_db.table1" in loading
        assert "staging_db.table2" in queued
    
    def test_mark_table_complete(self) -> None:
        """Can explicitly mark a table as complete."""
        callback = Mock()
        parser = MyloaderLogParser(event_callback=callback)
        
        parser.parse_line("Thread 1: restoring staging_db.users part 1 of 1 from users.sql.gz | Progress 1 of 1")
        callback.reset_mock()
        
        parser.mark_table_complete("staging_db.users")
        
        state = parser.get_table_state("staging_db.users")
        assert state.phase == TablePhase.COMPLETE
        
        callback.assert_called_once()
        assert callback.call_args[0][0] == "table_restore_complete"


class TestMyloaderLogParserEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_line(self) -> None:
        """Empty lines are handled gracefully."""
        parser = MyloaderLogParser()
        result = parser.parse_line("")
        assert result.event_type is None
    
    def test_malformed_line(self) -> None:
        """Malformed lines don't cause errors."""
        parser = MyloaderLogParser()
        result = parser.parse_line("Thread X: restoring blah blah incomplete")
        assert result.event_type is None
    
    def test_index_before_data(self) -> None:
        """Index message before data message creates state correctly."""
        parser = MyloaderLogParser()
        
        # Index message arrives first (unusual but possible)
        result = parser.parse_line("restoring index: source_db.orphan_table")
        
        assert result.event_type == "table_index_rebuild_started"
        state = parser.get_table_state("source_db.orphan_table")
        assert state is not None
        assert state.phase == TablePhase.REBUILDING_INDEXES
    
    def test_duplicate_enqueue_messages(self) -> None:
        """Duplicate enqueue messages don't corrupt state."""
        parser = MyloaderLogParser()
        
        parser.parse_line("Thread 1: Enqueuing index for table: staging_db.users")
        first_state = parser.get_table_state("staging_db.users")
        first_time = first_state.index_started_at
        
        # Duplicate message (shouldn't happen but be defensive)
        parser.parse_line("Thread 2: Enqueuing index for table: staging_db.users")
        second_state = parser.get_table_state("staging_db.users")
        
        # State should be updated but not corrupted
        assert second_state.phase == TablePhase.DATA_COMPLETE
    
    def test_real_myloader_output_sequence(self) -> None:
        """Test with realistic sequence from actual myloader run."""
        callback = Mock()
        parser = MyloaderLogParser(event_callback=callback)
        
        # Realistic output sequence
        lines = [
            "** Message: 06:02:13.767: Thread 2: restoring brunodfoxpest_655929085e57.salesRoutesAccess part 56 of 297 from foxpest.salesRoutesAccess.00159.sql.gz | Progress 600 of 606. Tables 507 of 509 completed",
            "** Message: 06:02:20.155: Thread 0: Enqueuing index for table: brunodfoxpest_655929085e57.changeLog",
            "** Message: 06:02:20.155: restoring index: foxpest.changeLog",
            "** Message: 06:02:20.155: Thread 9: restoring indexes brunodfoxpest_655929085e57.changeLog from index. Tables 507 of 509 completed",
            "** Message: 06:04:21.888: L-Thread 1: ending",
            "** Message: 06:04:21.888: L-Thread 2: ending",
        ]
        
        for line in lines:
            parser.parse_line(line)
        
        # Verify final state
        summary = parser.get_summary()
        assert summary["overall_progress"] == 600
        assert summary["overall_total"] == 606
        assert summary["loader_threads_ended"] == 2
        
        # changeLog should be in REBUILDING_INDEXES phase
        changelog_state = None
        for key, state in parser.get_all_states().items():
            if "changeLog" in key:
                changelog_state = state
                break
        
        assert changelog_state is not None
        assert changelog_state.phase == TablePhase.REBUILDING_INDEXES
