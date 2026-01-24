"""Unit tests for unified backup_metadata module.

Tests the consolidated backup metadata handling for:
- Metadata format detection
- Row estimation using ISIZE and sampling
- Binlog position parsing
- Event callback support
"""

import gzip
from pathlib import Path
from typing import Any

from pulldb.worker.backup_metadata import (
    SAMPLE_BYTES,
    BackupMetadata,
    MetadataFormat,
    _estimate_rows_by_sampling,
    count_rows_in_file,
    ensure_compatible_metadata,
    ensure_myloader_compatibility,
    get_backup_metadata,
    get_table_row_estimates,
    parse_binlog_position,
    parse_filename,
)


class TestEnsureMyloaderCompatibility:
    """Test metadata compatibility ensurance."""

    def test_already_compatible(self, tmp_path: Path) -> None:
        """Return early if already 0.19+ format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("[config]\nquote-character = BACKTICK\n")

        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19

    def test_upgrade_legacy_format(self, tmp_path: Path) -> None:
        """Upgrade legacy format to INI."""
        metadata = tmp_path / "metadata"
        metadata.write_text(
            "Started dump at: 2025-01-01\nLog: bin.000001\nPos: 123\n"
        )

        # Create a data file
        data_file = tmp_path / "db.table.sql.gz"
        with gzip.open(data_file, "wt") as f:
            f.write("INSERT INTO t VALUES (1);")

        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19

        # Verify upgrade happened
        content = metadata.read_text()
        assert "[config]" in content
        assert "[source]" in content

    def test_create_metadata_when_missing(self, tmp_path: Path) -> None:
        """Create minimal metadata when missing."""
        # Create a data file so it looks like a backup
        data_file = tmp_path / "db.table.sql.gz"
        with gzip.open(data_file, "wt") as f:
            f.write("INSERT INTO t VALUES (1);")

        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19

        metadata = tmp_path / "metadata"
        assert metadata.exists()

    def test_emits_events(self, tmp_path: Path) -> None:
        """Emit start/complete events via callback."""
        metadata = tmp_path / "metadata"
        metadata.write_text("[config]\nquote-character = BACKTICK\n")

        events: list[tuple[str, dict[str, Any]]] = []

        def event_callback(event_type: str, detail: dict[str, Any]) -> None:
            events.append((event_type, detail))

        ensure_myloader_compatibility(str(tmp_path), event_callback=event_callback)

        assert len(events) == 2
        assert events[0][0] == "metadata_synthesis_started"
        assert events[1][0] == "metadata_synthesis_complete"
        assert events[1][1]["action"] == "none_needed"


class TestGetBackupMetadata:
    """Test complete backup metadata retrieval."""

    def test_returns_complete_metadata(self, tmp_path: Path) -> None:
        """Get complete metadata including tables and binlog."""
        # Create INI metadata
        metadata = tmp_path / "metadata"
        metadata.write_text("""[config]
quote-character = BACKTICK

[source]
File = mysql-bin.000001
Position = 12345

[`mydb`.`users`]
rows = 1000

[`mydb`.`orders`]
rows = 5000
""")

        result = get_backup_metadata(str(tmp_path))

        assert isinstance(result, BackupMetadata)
        assert result.format == MetadataFormat.INI_0_19
        assert result.total_rows == 6000
        assert len(result.tables) == 2
        assert result.binlog is not None
        assert result.binlog.file == "mysql-bin.000001"
        assert result.binlog.position == 12345


class TestGetTableRowEstimates:
    """Test ISIZE-based row estimation."""

    def test_estimate_from_ini(self, tmp_path: Path) -> None:
        """Use row counts from INI metadata when available."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""
[config]
quote-character = BACKTICK

[`mydb`.`users`]
rows = 1000

[`mydb`.`orders`]
rows = 5000
""")

        estimates = get_table_row_estimates(str(tmp_path))
        total = sum(e.rows for e in estimates)
        assert total == 6000

    def test_legacy_backup_returns_zero_rows(self, tmp_path: Path) -> None:
        """Legacy backups return rows=0 (no row estimation), only file counts.

        Row estimation for legacy backups was removed because:
        1. ISIZE estimation is unreliable (4GB wraparound, compression variance)
        2. Full file scanning is too slow and resource-intensive
        3. With log-based progress tracking, we only need file counts
        """
        # Create gzip file with INSERT statements
        data_file = tmp_path / "db.table.sql.gz"
        content = """INSERT INTO `table` VALUES (1, 'a'),
,(2, 'b'),
,(3, 'c');
INSERT INTO `table` VALUES (4, 'd'),
,(5, 'e'),
,(6, 'f'),
,(7, 'g'),
,(8, 'h'),
,(9, 'i'),
,(10, 'j');
"""
        with gzip.open(data_file, "wt") as f:
            f.write(content)

        estimates = get_table_row_estimates(str(tmp_path))
        assert len(estimates) == 1
        # Rows is 0 for legacy backups (no row estimation)
        assert estimates[0].rows == 0
        # But file_count is accurate
        assert estimates[0].file_count == 1


class TestParseBinlogPosition:
    """Test binlog position extraction."""

    def test_parse_legacy_binlog(self, tmp_path: Path) -> None:
        """Parse binlog from legacy format."""
        metadata = tmp_path / "metadata"
        metadata.write_text(
            "Started dump at: 2025-01-01\nLog: bin.000001\nPos: 123456\n"
        )

        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is not None
        assert binlog.file == "bin.000001"
        assert binlog.position == 123456

    def test_parse_ini_binlog(self, tmp_path: Path) -> None:
        """Parse binlog from INI format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""
[source]
File = mysql-bin.000042
Position = 987654
Executed_Gtid_Set = abc-123:1-100
""")

        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is not None
        assert binlog.file == "mysql-bin.000042"
        assert binlog.position == 987654
        assert binlog.gtid_set == "abc-123:1-100"

    def test_returns_none_for_missing_metadata(self, tmp_path: Path) -> None:
        """Return None when metadata file doesn't exist."""
        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is None


class TestParseFilename:
    """Tests for parse_filename function (backwards compat alias)."""

    def test_parses_simple_data_file(self) -> None:
        """Parses standard mydumper data filename."""
        result = parse_filename("database.table.00000.sql.gz")
        assert result == ("database", "table")

    def test_parses_non_chunked_file(self) -> None:
        """Parses data file without chunk number."""
        result = parse_filename("database.table.sql.gz")
        assert result == ("database", "table")

    def test_ignores_schema_file(self) -> None:
        """Returns None for schema files."""
        assert parse_filename("database.table-schema.sql.gz") is None
        assert parse_filename("database-schema-create.sql.gz") is None

    def test_ignores_non_sql_files(self) -> None:
        """Returns None for non-.sql.gz files."""
        assert parse_filename("metadata") is None
        assert parse_filename("database.table.sql") is None

    def test_handles_table_with_dots(self) -> None:
        """Handles table names containing dots."""
        result = parse_filename("db.table.with.dots.00000.sql.gz")
        assert result == ("db", "table.with.dots")


class TestCountRowsInFile:
    """Tests for count_rows_in_file function (backwards compat alias)."""

    def test_counts_insert_statements(self, tmp_path: Path) -> None:
        """Counts INSERT INTO and continuation lines."""
        sql_content = b"""\
INSERT INTO `table` VALUES (1, 'a'),
,(2, 'b'),
,(3, 'c');
INSERT INTO `table` VALUES (4, 'd');
"""
        gz_path = tmp_path / "test.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(sql_content)

        count = count_rows_in_file(str(gz_path))
        # 2 INSERT lines + 2 continuation lines = 4 rows
        assert count == 4

    def test_returns_zero_for_nonexistent(self) -> None:
        """Returns 0 for nonexistent file."""
        count = count_rows_in_file("/nonexistent/file.sql.gz")
        assert count == 0


class TestEstimateRowsBySampling:
    """Tests for _estimate_rows_by_sampling function."""

    def test_returns_zero_for_empty_file(self, tmp_path: Path) -> None:
        """Returns 0 when ISIZE is 0."""
        gz_path = tmp_path / "empty.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(b"")

        rows = _estimate_rows_by_sampling(str(gz_path))
        assert rows == 0

    def test_estimates_from_sample(self, tmp_path: Path) -> None:
        """Estimates rows by sampling first bytes and extrapolating."""
        rows_content = [f"({i},'value{i}')" for i in range(1000)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows_content) + ";\n"

        gz_path = tmp_path / "data.sql.gz"
        with gzip.open(gz_path, "wt") as f:
            f.write(content)

        estimated = _estimate_rows_by_sampling(str(gz_path))
        # Should be within 25% of actual 1000 rows
        assert 750 <= estimated <= 1250, f"Expected ~1000, got {estimated}"

    def test_handles_extended_inserts(self, tmp_path: Path) -> None:
        """Handles mydumper extended INSERT format correctly."""
        rows = 500
        content = "INSERT INTO `users` VALUES " + ",".join(
            f"({i},'user{i}','user{i}@example.com')" for i in range(rows)
        ) + ";\n"

        gz_path = tmp_path / "extended.sql.gz"
        with gzip.open(gz_path, "wt") as f:
            f.write(content)

        estimated = _estimate_rows_by_sampling(str(gz_path))
        # Should be within 25% of actual 500 rows
        assert 375 <= estimated <= 625, f"Expected ~500, got {estimated}"

    def test_handles_mydumper_newline_format(self, tmp_path: Path) -> None:
        """Handles real mydumper format with newlines between rows.

        Mydumper actually outputs:
            INSERT INTO `t` VALUES (1,'alice'),
            (2,'bob'),
            (3,'charlie');

        Not the single-line format some tests use.
        """
        rows = 500
        # Real mydumper format: comma + newline between rows
        row_values = [f"({i},'user{i}','user{i}@example.com')" for i in range(rows)]
        content = "INSERT INTO `users` VALUES " + ",\n".join(row_values) + ";\n"

        gz_path = tmp_path / "mydumper_real.sql.gz"
        with gzip.open(gz_path, "wt") as f:
            f.write(content)

        estimated = _estimate_rows_by_sampling(str(gz_path))
        # Should be within 25% of actual 500 rows
        assert 375 <= estimated <= 625, f"Expected ~500, got {estimated}"

    def test_uses_fallback_when_no_rows(self, tmp_path: Path) -> None:
        """Falls back when file has no INSERT statements."""
        content = "CREATE TABLE `test` (id int);\n"
        gz_path = tmp_path / "schema.sql.gz"
        with gzip.open(gz_path, "wt") as f:
            f.write(content)

        estimated = _estimate_rows_by_sampling(str(gz_path))
        # Should use fallback (size / 200)
        assert estimated >= 1

    def test_handles_nonexistent_file(self) -> None:
        """Returns 0 for nonexistent file."""
        estimated = _estimate_rows_by_sampling("/nonexistent/file.sql.gz")
        assert estimated == 0

    def test_custom_sample_size(self, tmp_path: Path) -> None:
        """Respects custom sample_bytes parameter."""
        rows_content = [f"({i},'data{i}')" for i in range(200)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows_content) + ";\n"

        gz_path = tmp_path / "data.sql.gz"
        with gzip.open(gz_path, "wt") as f:
            f.write(content)

        small_sample = _estimate_rows_by_sampling(str(gz_path), sample_bytes=1024)
        large_sample = _estimate_rows_by_sampling(str(gz_path), sample_bytes=16384)

        # Both should give reasonable estimates
        assert 100 <= small_sample <= 400
        assert 100 <= large_sample <= 400


class TestBackwardsCompatibility:
    """Test backwards compatibility aliases."""

    def test_ensure_compatible_metadata_alias(self, tmp_path: Path) -> None:
        """ensure_compatible_metadata alias works."""
        metadata = tmp_path / "metadata"
        metadata.write_text("[config]\nquote-character = BACKTICK\n")

        # Should not raise
        ensure_compatible_metadata(str(tmp_path))


class TestEventCallbacks:
    """Test event callback functionality."""

    def test_get_backup_metadata_emits_events(self, tmp_path: Path) -> None:
        """get_backup_metadata emits synthesis events."""
        # Create legacy metadata that needs upgrade
        metadata = tmp_path / "metadata"
        metadata.write_text(
            "Started dump at: 2025-01-01\nLog: bin.000001\nPos: 123\n"
        )

        data_file = tmp_path / "db.table.sql.gz"
        with gzip.open(data_file, "wt") as f:
            f.write("INSERT INTO t VALUES (1);")

        events: list[tuple[str, dict[str, Any]]] = []

        def event_callback(event_type: str, detail: dict[str, Any]) -> None:
            events.append((event_type, detail))

        get_backup_metadata(str(tmp_path), event_callback=event_callback)

        # Should have start and complete events
        event_types = [e[0] for e in events]
        assert "metadata_synthesis_started" in event_types
        assert "metadata_synthesis_complete" in event_types

    def test_no_events_when_callback_none(self, tmp_path: Path) -> None:
        """No crash when event_callback is None."""
        metadata = tmp_path / "metadata"
        metadata.write_text("[config]\nquote-character = BACKTICK\n")

        # Should not raise
        result = get_backup_metadata(str(tmp_path), event_callback=None)
        assert result is not None
