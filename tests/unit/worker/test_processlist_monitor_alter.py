"""Tests for processlist_monitor ALTER TABLE detection.

Tests the new index rebuild detection capability added for Phase 5.

HCA Layer: tests
"""

from __future__ import annotations

import pytest

from pulldb.worker.processlist_monitor import (
    ProcesslistMonitor,
    ProcesslistMonitorConfig,
    TableProgress,
    RE_ADD_KEY,
    RE_ALTER_TABLE,
)


class TestAlterTableRegex:
    """Test ALTER TABLE regex patterns."""
    
    def test_alter_table_simple(self) -> None:
        """Match simple ALTER TABLE statement."""
        info = "ALTER TABLE users ADD KEY idx_email (email)"
        match = RE_ALTER_TABLE.search(info)
        assert match is not None
        assert match.group(1) == "users"
    
    def test_alter_table_backticks(self) -> None:
        """Match ALTER TABLE with backtick-quoted name."""
        info = "ALTER TABLE `changeLog` ADD KEY `class` (`class`)"
        match = RE_ALTER_TABLE.search(info)
        assert match is not None
        assert match.group(1) == "changeLog"
    
    def test_alter_table_complex(self) -> None:
        """Match complex ALTER TABLE with multiple indexes."""
        info = "ALTER TABLE `changeLog` ADD KEY `class` (`class`), ADD KEY `category` (`category`), ADD KEY `entityId` (`entityId`)"
        match = RE_ALTER_TABLE.search(info)
        assert match is not None
        assert match.group(1) == "changeLog"
    
    def test_add_key_pattern(self) -> None:
        """Match ADD KEY pattern."""
        info = "ALTER TABLE users ADD KEY idx_email (email)"
        assert RE_ADD_KEY.search(info) is not None
    
    def test_add_index_pattern(self) -> None:
        """Match ADD INDEX pattern."""
        info = "ALTER TABLE users ADD INDEX idx_email (email)"
        assert RE_ADD_KEY.search(info) is not None
    
    def test_add_column_no_match(self) -> None:
        """ADD COLUMN should NOT match ADD KEY pattern."""
        info = "ALTER TABLE users ADD COLUMN email VARCHAR(255)"
        assert RE_ADD_KEY.search(info) is None


class TestTableProgressPhase:
    """Test TableProgress phase tracking."""
    
    def test_default_phase_is_loading(self) -> None:
        """Default phase should be 'loading'."""
        progress = TableProgress(table="users")
        assert progress.phase == "loading"
    
    def test_phase_can_be_indexing(self) -> None:
        """Phase can be set to 'indexing'."""
        progress = TableProgress(table="users", phase="indexing")
        assert progress.phase == "indexing"
    
    def test_running_seconds_default(self) -> None:
        """Running seconds defaults to 0."""
        progress = TableProgress(table="users")
        assert progress.running_seconds == 0
    
    def test_running_seconds_can_be_set(self) -> None:
        """Running seconds can be set."""
        progress = TableProgress(table="users", running_seconds=45)
        assert progress.running_seconds == 45


class TestProcesslistMonitorAlterDetection:
    """Test ProcesslistMonitor ALTER TABLE detection."""
    
    def test_parse_alter_table_row(self) -> None:
        """Parse processlist row with ALTER TABLE."""
        config = ProcesslistMonitorConfig(
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="test",
            mysql_password="test",
            staging_db="staging_test",
        )
        monitor = ProcesslistMonitor(config)
        
        # Simulate processlist row for ALTER TABLE
        rows = [
            {
                "db": "staging_test",
                "Info": "ALTER TABLE `changeLog` ADD KEY `class` (`class`), ADD KEY `category` (`category`)",
                "Time": 45,
            }
        ]
        
        snapshot = monitor._parse_processlist_rows(rows)
        
        assert snapshot is not None
        assert "changeLog" in snapshot.tables
        assert snapshot.tables["changeLog"].phase == "indexing"
        assert snapshot.tables["changeLog"].running_seconds == 45
        assert snapshot.tables["changeLog"].percent_complete == 100.0
        assert snapshot.active_threads == 1
    
    def test_parse_mixed_operations(self) -> None:
        """Parse processlist with both data loading and index rebuild."""
        config = ProcesslistMonitorConfig(
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="test",
            mysql_password="test",
            staging_db="staging_test",
        )
        monitor = ProcesslistMonitor(config)
        
        rows = [
            # Data loading row
            {
                "db": "staging_test",
                "Info": "/* Completed: 45.5% */ INSERT INTO `users` VALUES ...",
                "Time": 10,
            },
            # Index rebuild row
            {
                "db": "staging_test",
                "Info": "ALTER TABLE `orders` ADD KEY `customer_id` (`customer_id`)",
                "Time": 30,
            },
        ]
        
        snapshot = monitor._parse_processlist_rows(rows)
        
        assert snapshot is not None
        assert len(snapshot.tables) == 2
        assert snapshot.active_threads == 2
        
        # Check data loading table
        assert "users" in snapshot.tables
        assert snapshot.tables["users"].phase == "loading"
        assert snapshot.tables["users"].percent_complete == 45.5
        
        # Check indexing table
        assert "orders" in snapshot.tables
        assert snapshot.tables["orders"].phase == "indexing"
        assert snapshot.tables["orders"].running_seconds == 30
    
    def test_ignore_other_databases(self) -> None:
        """Ignore ALTER TABLE on other databases."""
        config = ProcesslistMonitorConfig(
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="test",
            mysql_password="test",
            staging_db="staging_test",
        )
        monitor = ProcesslistMonitor(config)
        
        rows = [
            {
                "db": "other_database",
                "Info": "ALTER TABLE `users` ADD KEY `email` (`email`)",
                "Time": 10,
            },
        ]
        
        snapshot = monitor._parse_processlist_rows(rows)
        
        assert snapshot is not None
        assert len(snapshot.tables) == 0
        assert snapshot.active_threads == 0
