"""Tests for pulldb.worker.staging module.

Tests staging database lifecycle operations:
- Staging name generation
- Orphaned staging detection
- Staging cleanup operations
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pulldb.domain.errors import StagingError
from pulldb.worker.staging import (
    MAX_DATABASE_NAME_LENGTH,
    STAGING_SUFFIX_LENGTH,
    StagingConnectionSpec,
    StagingResult,
    cleanup_orphaned_staging,
    find_orphaned_staging_databases,
    generate_staging_name,
)


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

SAMPLE_TARGET = "charleqatemplate"
SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"
SAMPLE_STAGING_NAME = "charleqatemplate_75777a4c3dd9"


# ---------------------------------------------------------------------------
# generate_staging_name Tests
# ---------------------------------------------------------------------------


class TestGenerateStagingName:
    """Tests for generate_staging_name function."""

    def test_generates_correct_format(self) -> None:
        """Staging name uses target_jobidprefix12 format."""
        result = generate_staging_name(SAMPLE_TARGET, SAMPLE_JOB_ID)
        assert result == SAMPLE_STAGING_NAME

    def test_strips_hyphens_from_uuid(self) -> None:
        """UUID hyphens are removed before taking prefix."""
        job_id = "aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = generate_staging_name("testdb", job_id)
        assert result == "testdb_aaaabbbbcccc"

    def test_lowercase_hex_chars(self) -> None:
        """Hex characters are lowercased."""
        job_id = "ABCD1234EF567890ABCD1234"
        result = generate_staging_name("testdb", job_id)
        assert result == "testdb_abcd1234ef56"

    def test_exact_12_char_suffix(self) -> None:
        """Suffix is exactly 12 hex characters."""
        result = generate_staging_name("testdb", SAMPLE_JOB_ID)
        suffix = result.split("_")[-1]
        assert len(suffix) == 12

    def test_target_at_max_length(self) -> None:
        """Target at maximum allowed length succeeds."""
        max_target_len = MAX_DATABASE_NAME_LENGTH - STAGING_SUFFIX_LENGTH
        target = "a" * max_target_len
        result = generate_staging_name(target, SAMPLE_JOB_ID)
        assert len(result) == MAX_DATABASE_NAME_LENGTH

    def test_target_too_long_raises_error(self) -> None:
        """Target exceeding maximum length raises StagingError."""
        max_target_len = MAX_DATABASE_NAME_LENGTH - STAGING_SUFFIX_LENGTH
        target = "a" * (max_target_len + 1)
        with pytest.raises(StagingError) as exc_info:
            generate_staging_name(target, SAMPLE_JOB_ID)
        assert "exceeds maximum" in str(exc_info.value)

    def test_short_job_id_raises_error(self) -> None:
        """Job ID shorter than 12 chars raises StagingError."""
        with pytest.raises(StagingError) as exc_info:
            generate_staging_name("testdb", "short")
        assert "too short" in str(exc_info.value)

    def test_non_hex_job_id_raises_error(self) -> None:
        """Job ID with non-hex chars raises StagingError."""
        with pytest.raises(StagingError) as exc_info:
            generate_staging_name("testdb", "ghijklmnopqrstuvwx")
        assert "non-hexadecimal" in str(exc_info.value)

    def test_preserves_target_case(self) -> None:
        """Target database name case is preserved."""
        result = generate_staging_name("MyDatabase", SAMPLE_JOB_ID)
        assert result.startswith("MyDatabase_")


# ---------------------------------------------------------------------------
# find_orphaned_staging_databases Tests
# ---------------------------------------------------------------------------


class TestFindOrphanedStagingDatabases:
    """Tests for find_orphaned_staging_databases function."""

    def test_empty_database_list(self) -> None:
        """Returns empty list when no databases exist."""
        result = find_orphaned_staging_databases(SAMPLE_TARGET, [])
        assert result == []

    def test_no_matching_databases(self) -> None:
        """Returns empty list when no staging databases match."""
        databases = ["mysql", "information_schema", "otherdb"]
        result = find_orphaned_staging_databases(SAMPLE_TARGET, databases)
        assert result == []

    def test_finds_single_orphan(self) -> None:
        """Finds a single orphaned staging database."""
        databases = ["mysql", "charleqatemplate_abcdef123456", "otherdb"]
        result = find_orphaned_staging_databases("charleqatemplate", databases)
        assert result == ["charleqatemplate_abcdef123456"]

    def test_finds_multiple_orphans(self) -> None:
        """Finds multiple orphaned staging databases."""
        databases = [
            "charleqatemplate_111111111111",
            "charleqatemplate_222222222222",
            "charleqatemplate_333333333333",
            "otherdb",
        ]
        result = find_orphaned_staging_databases("charleqatemplate", databases)
        assert len(result) == 3

    def test_returns_sorted_list(self) -> None:
        """Returns orphan list in sorted order."""
        databases = [
            "testdb_ccc111111111",
            "testdb_aaa111111111",
            "testdb_bbb111111111",
        ]
        result = find_orphaned_staging_databases("testdb", databases)
        assert result == [
            "testdb_aaa111111111",
            "testdb_bbb111111111",
            "testdb_ccc111111111",
        ]

    def test_ignores_non_hex_suffix(self) -> None:
        """Ignores databases with non-hex suffix."""
        databases = ["testdb_notahexvalue1"]
        result = find_orphaned_staging_databases("testdb", databases)
        assert result == []

    def test_ignores_wrong_suffix_length(self) -> None:
        """Ignores databases with wrong suffix length."""
        databases = ["testdb_abc123", "testdb_abcdef123456789"]
        result = find_orphaned_staging_databases("testdb", databases)
        assert result == []

    def test_ignores_different_target(self) -> None:
        """Ignores staging databases for different targets."""
        databases = ["othertarget_abcdef123456"]
        result = find_orphaned_staging_databases("mytarget", databases)
        assert result == []

    def test_exact_target_match(self) -> None:
        """Only matches exact target prefix."""
        databases = [
            "test_abcdef123456",  # matches 'test'
            "testing_abcdef123456",  # does not match 'test'
        ]
        result = find_orphaned_staging_databases("test", databases)
        assert result == ["test_abcdef123456"]


# ---------------------------------------------------------------------------
# cleanup_orphaned_staging Tests
# ---------------------------------------------------------------------------


class TestCleanupOrphanedStaging:
    """Tests for cleanup_orphaned_staging function."""

    @pytest.fixture
    def conn_spec(self) -> StagingConnectionSpec:
        """Create test connection spec."""
        return StagingConnectionSpec(
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="test_user",
            mysql_password="test_password",
            timeout_seconds=30,
        )

    def test_successful_cleanup_no_orphans(self, conn_spec: StagingConnectionSpec) -> None:
        """Cleanup succeeds with no orphans to drop."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [("mysql",), ("information_schema",)],  # SHOW DATABASES
            [],  # information_schema.processlist (no active connections)
            [("mysql",), ("information_schema",)],  # SHOW DATABASES verification
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            result = cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)

        assert isinstance(result, StagingResult)
        assert result.staging_db == SAMPLE_STAGING_NAME
        assert result.target_db == SAMPLE_TARGET
        assert result.orphans_dropped == []

    def test_successful_cleanup_with_orphans(self, conn_spec: StagingConnectionSpec) -> None:
        """Cleanup drops orphaned databases."""
        # Calls: SHOW DATABASES, processlist, DROP, SHOW DATABASES (verify)
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [("mysql",), ("charleqatemplate_aaaaaaaaaaaa",)],  # SHOW DATABASES
            [],  # information_schema.processlist (no active connections)
            [("mysql",)],  # SHOW DATABASES verification (orphan dropped)
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            result = cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)

        assert result.orphans_dropped == ["charleqatemplate_aaaaaaaaaaaa"]
        mock_cursor.execute.assert_any_call(
            "DROP DATABASE IF EXISTS `charleqatemplate_aaaaaaaaaaaa`"
        )

    def test_connection_failure_raises_error(self, conn_spec: StagingConnectionSpec) -> None:
        """Connection failure raises StagingError."""
        import mysql.connector

        with patch(
            "mysql.connector.connect",
            side_effect=mysql.connector.Error("Connection refused"),
        ):
            with pytest.raises(StagingError) as exc_info:
                cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)
            assert "Failed to connect" in str(exc_info.value)

    def test_show_databases_failure_raises_error(self, conn_spec: StagingConnectionSpec) -> None:
        """SHOW DATABASES failure raises StagingError."""
        import mysql.connector

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = mysql.connector.Error("Access denied")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            with pytest.raises(StagingError) as exc_info:
                cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)
            assert "Failed to list databases" in str(exc_info.value)

    def test_drop_failure_raises_error(self, conn_spec: StagingConnectionSpec) -> None:
        """DROP DATABASE failure raises StagingError."""
        import mysql.connector

        mock_cursor = MagicMock()
        # Calls: SHOW DATABASES, processlist, DROP (fails)
        # fetchall calls:
        #   1. SHOW DATABASES - returns databases including orphan
        #   2. processlist - returns empty (no active connections, so DROP proceeds)
        mock_cursor.fetchall.side_effect = [
            [("mysql",), ("charleqatemplate_aaaaaaaaaaaa",)],  # SHOW DATABASES
            [],  # processlist - no active connections
        ]

        def execute_side_effect(sql: str) -> None:
            if "DROP" in sql:
                raise mysql.connector.Error("Drop denied")

        mock_cursor.execute.side_effect = execute_side_effect

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            with pytest.raises(StagingError) as exc_info:
                cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)
            assert "Failed to drop" in str(exc_info.value)

    def test_staging_collision_raises_error(self, conn_spec: StagingConnectionSpec) -> None:
        """Raises error if staging name exists after cleanup."""
        mock_cursor = MagicMock()
        # Calls: SHOW DATABASES, processlist, SHOW DATABASES (verify)
        mock_cursor.fetchall.side_effect = [
            [("mysql",)],  # SHOW DATABASES (no orphans)
            [],  # information_schema.processlist (no active connections)
            [("mysql",), (SAMPLE_STAGING_NAME,)],  # SHOW DATABASES verify - collision!
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            with pytest.raises(StagingError) as exc_info:
                cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)
            assert "still exists" in str(exc_info.value)

    def test_closes_connection_on_success(self, conn_spec: StagingConnectionSpec) -> None:
        """Connection is closed after successful cleanup."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [("mysql",)],  # SHOW DATABASES
            [],  # information_schema.processlist (no active connections)
            [("mysql",)],  # SHOW DATABASES verification
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)

        mock_conn.close.assert_called_once()

    def test_closes_connection_on_error(self, conn_spec: StagingConnectionSpec) -> None:
        """Connection is closed even on error."""
        import mysql.connector

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = mysql.connector.Error("Error")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            with pytest.raises(StagingError):
                cleanup_orphaned_staging(conn_spec, SAMPLE_TARGET, SAMPLE_JOB_ID)

        mock_conn.close.assert_called_once()
