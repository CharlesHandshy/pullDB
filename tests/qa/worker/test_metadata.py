"""Tests for pulldb.worker.metadata module.

Tests metadata table injection:
- Metadata specification creation
- Table creation SQL
- Data insertion
- Error handling
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from pulldb.worker.metadata import (
    MetadataConnectionSpec,
    MetadataSpec,
    inject_metadata_table,
)
from pulldb.worker.post_sql import PostSQLExecutionResult


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"
SAMPLE_TARGET = "charleqatemplate"
SAMPLE_STAGING = "charleqatemplate_75777a4c3dd9"


# ---------------------------------------------------------------------------
# MetadataConnectionSpec Tests
# ---------------------------------------------------------------------------


class TestMetadataConnectionSpec:
    """Tests for MetadataConnectionSpec dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """MetadataConnectionSpec can be created with required fields."""
        spec = MetadataConnectionSpec(
            staging_db=SAMPLE_STAGING,
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="restore_user",
            mysql_password="password",
            timeout_seconds=30,
        )
        assert spec.staging_db == SAMPLE_STAGING
        assert spec.mysql_host == "localhost"
        assert spec.mysql_port == 3306

    def test_is_frozen(self) -> None:
        """MetadataConnectionSpec is immutable."""
        spec = MetadataConnectionSpec(
            staging_db=SAMPLE_STAGING,
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="user",
            mysql_password="pass",
            timeout_seconds=30,
        )
        with pytest.raises(AttributeError):
            spec.mysql_host = "other"


# ---------------------------------------------------------------------------
# MetadataSpec Tests
# ---------------------------------------------------------------------------


class TestMetadataSpec:
    """Tests for MetadataSpec dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """MetadataSpec can be created with required fields."""
        now = datetime.now(UTC)
        spec = MetadataSpec(
            job_id=SAMPLE_JOB_ID,
            owner_username="testuser",
            target_db=SAMPLE_TARGET,
            backup_filename="backup-2025-01-15.tar",
            restore_started_at=now,
            restore_completed_at=now,
            post_sql_result=None,
        )
        assert spec.job_id == SAMPLE_JOB_ID
        assert spec.owner_username == "testuser"
        assert spec.target_db == SAMPLE_TARGET

    def test_with_post_sql_result(self) -> None:
        """MetadataSpec can include post_sql_result."""
        from pulldb.worker.post_sql import PostSQLScriptResult

        now = datetime.now(UTC)
        script_result = PostSQLScriptResult(
            script_name="01_cleanup.sql",
            started_at=now,
            completed_at=now,
            duration_seconds=2.5,
            rows_affected=10,
        )
        post_sql = PostSQLExecutionResult(
            staging_db=SAMPLE_STAGING,
            scripts_executed=[script_result],
            total_duration_seconds=5.0,
        )
        spec = MetadataSpec(
            job_id=SAMPLE_JOB_ID,
            owner_username="testuser",
            target_db=SAMPLE_TARGET,
            backup_filename="backup.tar",
            restore_started_at=now,
            restore_completed_at=now,
            post_sql_result=post_sql,
        )
        assert spec.post_sql_result is not None
        assert len(spec.post_sql_result.scripts_executed) == 1


# ---------------------------------------------------------------------------
# inject_metadata_table Tests
# ---------------------------------------------------------------------------


class TestInjectMetadataTable:
    """Tests for inject_metadata_table function."""

    @pytest.fixture
    def conn_spec(self) -> MetadataConnectionSpec:
        """Create test connection spec."""
        return MetadataConnectionSpec(
            staging_db=SAMPLE_STAGING,
            mysql_host="localhost",
            mysql_port=3306,
            mysql_user="test_user",
            mysql_password="test_password",
            timeout_seconds=30,
        )

    @pytest.fixture
    def metadata_spec(self) -> MetadataSpec:
        """Create test metadata spec."""
        now = datetime.now(UTC)
        return MetadataSpec(
            job_id=SAMPLE_JOB_ID,
            owner_username="testuser",
            target_db=SAMPLE_TARGET,
            backup_filename="backup-2025-01-15.tar",
            restore_started_at=now,
            restore_completed_at=now,
            post_sql_result=None,
        )

    def test_creates_table_and_inserts(
        self, conn_spec: MetadataConnectionSpec, metadata_spec: MetadataSpec
    ) -> None:
        """Creates pullDB table and inserts metadata."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            inject_metadata_table(conn_spec, metadata_spec)

        # Should have executed CREATE TABLE and INSERT
        assert mock_cursor.execute.call_count >= 2
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("CREATE TABLE" in c for c in calls)
        assert any("INSERT" in c for c in calls)

    def test_closes_connection(
        self, conn_spec: MetadataConnectionSpec, metadata_spec: MetadataSpec
    ) -> None:
        """Closes connection after injection."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            inject_metadata_table(conn_spec, metadata_spec)

        mock_conn.close.assert_called_once()

    def test_raises_on_connection_failure(
        self, conn_spec: MetadataConnectionSpec, metadata_spec: MetadataSpec
    ) -> None:
        """Raises error on connection failure."""
        import mysql.connector

        from pulldb.domain.errors import MetadataInjectionError

        with patch(
            "mysql.connector.connect",
            side_effect=mysql.connector.Error("Connection refused"),
        ):
            with pytest.raises(MetadataInjectionError):
                inject_metadata_table(conn_spec, metadata_spec)

    def test_raises_on_table_creation_failure(
        self, conn_spec: MetadataConnectionSpec, metadata_spec: MetadataSpec
    ) -> None:
        """Raises error on table creation failure."""
        import mysql.connector

        from pulldb.domain.errors import MetadataInjectionError

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = mysql.connector.Error("Access denied")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn):
            with pytest.raises(MetadataInjectionError):
                inject_metadata_table(conn_spec, metadata_spec)

    def test_uses_staging_database(
        self, conn_spec: MetadataConnectionSpec, metadata_spec: MetadataSpec
    ) -> None:
        """Connects to staging database."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("mysql.connector.connect", return_value=mock_conn) as mock_connect:
            inject_metadata_table(conn_spec, metadata_spec)

        # Should connect to staging database
        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs["database"] == SAMPLE_STAGING
