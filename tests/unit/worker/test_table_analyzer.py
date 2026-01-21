"""Tests for table_analyzer module."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.table_analyzer import (
    AnalyzeBatchResult,
    AnalyzeResult,
    AnalyzeStatus,
    analyze_database_tables,
    analyze_table,
    analyze_tables,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_connection() -> MagicMock:
    """Create mock MySQL connection."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = [
        {"Table": "db.users", "Op": "analyze", "Msg_type": "status", "Msg_text": "OK"}
    ]
    return conn


# ============================================================================
# AnalyzeResult Tests
# ============================================================================

class TestAnalyzeResult:
    """Test AnalyzeResult dataclass."""
    
    def test_creates_with_defaults(self) -> None:
        """Creates result with default values."""
        result = AnalyzeResult(
            table_name="db.users",
            status=AnalyzeStatus.OK,
        )
        assert result.table_name == "db.users"
        assert result.status == AnalyzeStatus.OK
        assert result.duration_seconds == 0.0
        assert result.message == ""
        assert result.error == ""
    
    def test_creates_with_all_fields(self) -> None:
        """Creates result with all fields."""
        result = AnalyzeResult(
            table_name="db.users",
            status=AnalyzeStatus.ERROR,
            duration_seconds=1.5,
            message="some message",
            error="some error",
        )
        assert result.duration_seconds == 1.5
        assert result.message == "some message"
        assert result.error == "some error"


# ============================================================================
# AnalyzeBatchResult Tests
# ============================================================================

class TestAnalyzeBatchResult:
    """Test AnalyzeBatchResult dataclass."""
    
    def test_creates_empty(self) -> None:
        """Creates empty batch result."""
        result = AnalyzeBatchResult()
        assert result.total_tables == 0
        assert result.successful == 0
        assert result.failed == 0
        assert len(result.tables) == 0
    
    def test_add_result_increments_successful(self) -> None:
        """add_result increments successful counter for OK status."""
        batch = AnalyzeBatchResult()
        batch.add_result(AnalyzeResult("db.t1", AnalyzeStatus.OK))
        
        assert batch.total_tables == 1
        assert batch.successful == 1
        assert batch.failed == 0
    
    def test_add_result_increments_failed(self) -> None:
        """add_result increments failed counter for ERROR status."""
        batch = AnalyzeBatchResult()
        batch.add_result(AnalyzeResult("db.t1", AnalyzeStatus.ERROR))
        
        assert batch.total_tables == 1
        assert batch.successful == 0
        assert batch.failed == 1
    
    def test_add_result_accumulates_duration(self) -> None:
        """add_result accumulates total duration."""
        batch = AnalyzeBatchResult()
        batch.add_result(AnalyzeResult("db.t1", AnalyzeStatus.OK, duration_seconds=1.0))
        batch.add_result(AnalyzeResult("db.t2", AnalyzeStatus.OK, duration_seconds=2.5))
        
        assert batch.total_duration_seconds == 3.5
    
    def test_finalize_sets_completed_at(self) -> None:
        """finalize sets completed_at timestamp."""
        batch = AnalyzeBatchResult()
        assert batch.completed_at is None
        
        batch.finalize()
        
        assert batch.completed_at is not None
        assert isinstance(batch.completed_at, datetime)


# ============================================================================
# analyze_table Tests
# ============================================================================

class TestAnalyzeTable:
    """Test analyze_table function."""
    
    def test_invalid_table_name_format(self, mock_connection: MagicMock) -> None:
        """Returns error for invalid table name format."""
        result = analyze_table(mock_connection, "no_dot_table")
        
        assert result.status == AnalyzeStatus.ERROR
        assert "Invalid table name format" in result.error
        mock_connection.cursor.assert_not_called()
    
    def test_builds_correct_query_with_binlog(self, mock_connection: MagicMock) -> None:
        """Builds query with NO_WRITE_TO_BINLOG by default."""
        analyze_table(mock_connection, "mydb.users", no_write_to_binlog=True)
        
        cursor = mock_connection.cursor.return_value
        cursor.execute.assert_called_once()
        query = cursor.execute.call_args[0][0]
        assert "NO_WRITE_TO_BINLOG" in query
        assert "`mydb`.`users`" in query
    
    def test_builds_query_without_binlog(self, mock_connection: MagicMock) -> None:
        """Builds query without NO_WRITE_TO_BINLOG when disabled."""
        analyze_table(mock_connection, "mydb.users", no_write_to_binlog=False)
        
        cursor = mock_connection.cursor.return_value
        query = cursor.execute.call_args[0][0]
        assert "NO_WRITE_TO_BINLOG" not in query
        assert "ANALYZE TABLE `mydb`.`users`" in query
    
    def test_returns_ok_on_success(self, mock_connection: MagicMock) -> None:
        """Returns OK status on successful analyze."""
        result = analyze_table(mock_connection, "db.users")
        
        assert result.status == AnalyzeStatus.OK
        assert result.table_name == "db.users"
        assert result.duration_seconds >= 0
    
    def test_returns_error_on_msg_type_error(self, mock_connection: MagicMock) -> None:
        """Returns ERROR status when MySQL returns error msg_type."""
        cursor = mock_connection.cursor.return_value
        cursor.fetchall.return_value = [
            {"Msg_type": "error", "Msg_text": "Table not found"}
        ]
        
        result = analyze_table(mock_connection, "db.missing")
        
        assert result.status == AnalyzeStatus.ERROR
    
    def test_returns_not_found_on_doesnt_exist(self, mock_connection: MagicMock) -> None:
        """Returns TABLE_NOT_FOUND when table doesn't exist."""
        cursor = mock_connection.cursor.return_value
        cursor.fetchall.return_value = [
            {"Msg_type": "status", "Msg_text": "Table doesn't exist"}
        ]
        
        result = analyze_table(mock_connection, "db.gone")
        
        assert result.status == AnalyzeStatus.TABLE_NOT_FOUND
    
    def test_handles_exception(self, mock_connection: MagicMock) -> None:
        """Handles exceptions gracefully."""
        cursor = mock_connection.cursor.return_value
        cursor.execute.side_effect = Exception("Connection lost")
        
        result = analyze_table(mock_connection, "db.users")
        
        assert result.status == AnalyzeStatus.ERROR
        assert "Connection lost" in result.error
    
    def test_closes_cursor(self, mock_connection: MagicMock) -> None:
        """Closes cursor after use."""
        analyze_table(mock_connection, "db.users")
        
        cursor = mock_connection.cursor.return_value
        cursor.close.assert_called_once()
    
    def test_closes_cursor_on_exception(self, mock_connection: MagicMock) -> None:
        """Closes cursor even on exception."""
        cursor = mock_connection.cursor.return_value
        cursor.execute.side_effect = Exception("Error")
        
        analyze_table(mock_connection, "db.users")
        
        cursor.close.assert_called_once()


# ============================================================================
# analyze_tables Tests
# ============================================================================

class TestAnalyzeTables:
    """Test analyze_tables function."""
    
    def test_analyzes_all_tables(self, mock_connection: MagicMock) -> None:
        """Analyzes all tables in list."""
        result = analyze_tables(
            mock_connection, 
            ["db.t1", "db.t2", "db.t3"]
        )
        
        assert result.total_tables == 3
        assert len(result.tables) == 3
    
    def test_returns_finalized_result(self, mock_connection: MagicMock) -> None:
        """Returns finalized batch result."""
        result = analyze_tables(mock_connection, ["db.t1"])
        
        assert result.completed_at is not None
    
    def test_stop_on_error_false_continues(self, mock_connection: MagicMock) -> None:
        """Continues on error when stop_on_error is False."""
        cursor = mock_connection.cursor.return_value
        # First call succeeds, second fails, third succeeds
        cursor.fetchall.side_effect = [
            [{"Msg_type": "status", "Msg_text": "OK"}],
            Exception("Error"),
            [{"Msg_type": "status", "Msg_text": "OK"}],
        ]
        
        result = analyze_tables(
            mock_connection,
            ["db.t1", "db.t2", "db.t3"],
            stop_on_error=False,
        )
        
        assert result.total_tables == 3
    
    def test_stop_on_error_true_stops(self, mock_connection: MagicMock) -> None:
        """Stops on first error when stop_on_error is True."""
        cursor = mock_connection.cursor.return_value
        cursor.fetchall.side_effect = [
            [{"Msg_type": "status", "Msg_text": "OK"}],
            Exception("Error"),
            [{"Msg_type": "status", "Msg_text": "OK"}],  # Should not reach
        ]
        
        result = analyze_tables(
            mock_connection,
            ["db.t1", "db.t2", "db.t3"],
            stop_on_error=True,
        )
        
        # Should stop after second table
        assert result.total_tables == 2
    
    def test_empty_list_returns_empty_result(self, mock_connection: MagicMock) -> None:
        """Returns empty result for empty table list."""
        result = analyze_tables(mock_connection, [])
        
        assert result.total_tables == 0
        assert result.completed_at is not None


# ============================================================================
# analyze_database_tables Tests
# ============================================================================

class TestAnalyzeDatabaseTables:
    """Test analyze_database_tables function."""
    
    def test_lists_and_analyzes_tables(self, mock_connection: MagicMock) -> None:
        """Lists tables from database and analyzes them."""
        cursor = mock_connection.cursor.return_value
        # First call is SHOW TABLES, rest are ANALYZE
        cursor.fetchall.side_effect = [
            [{"Tables_in_mydb": "users"}, {"Tables_in_mydb": "orders"}],
            [{"Msg_type": "status", "Msg_text": "OK"}],
            [{"Msg_type": "status", "Msg_text": "OK"}],
        ]
        
        result = analyze_database_tables(mock_connection, "mydb")
        
        assert result.total_tables == 2
    
    def test_handles_exclude_patterns(self, mock_connection: MagicMock) -> None:
        """Filters tables based on exclude patterns."""
        cursor = mock_connection.cursor.return_value
        cursor.fetchall.side_effect = [
            [
                {"Tables_in_mydb": "users"},
                {"Tables_in_mydb": "tmp_cache"},
                {"Tables_in_mydb": "orders"},
            ],
            [{"Msg_type": "status", "Msg_text": "OK"}],  # users
            [{"Msg_type": "status", "Msg_text": "OK"}],  # orders (tmp_cache excluded)
        ]
        
        result = analyze_database_tables(
            mock_connection, 
            "mydb",
            exclude_patterns=["tmp%"],
        )
        
        # tmp_cache should be excluded
        assert result.total_tables == 2
    
    def test_handles_list_tables_error(self, mock_connection: MagicMock) -> None:
        """Returns empty result on error listing tables."""
        cursor = mock_connection.cursor.return_value
        cursor.execute.side_effect = Exception("Permission denied")
        
        result = analyze_database_tables(mock_connection, "mydb")
        
        assert result.total_tables == 0
        assert result.completed_at is not None


# ============================================================================
# AnalyzeStatus Tests
# ============================================================================

class TestAnalyzeStatus:
    """Test AnalyzeStatus enum."""
    
    def test_has_expected_values(self) -> None:
        """Has all expected status values."""
        assert AnalyzeStatus.OK
        assert AnalyzeStatus.TABLE_NOT_FOUND
        assert AnalyzeStatus.ERROR
        assert AnalyzeStatus.SKIPPED
