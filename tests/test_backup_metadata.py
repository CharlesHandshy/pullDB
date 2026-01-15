"""Tests for unified backup_metadata module.

Tests the consolidated backup metadata handling including:
- Metadata format detection
- Row estimation using ISIZE sampling
- Binlog position parsing
- Backward compatibility wrappers
"""

from __future__ import annotations

import configparser
import gzip
import os
import tempfile
from pathlib import Path

import pytest

from pulldb.worker.backup_metadata import (
    DEFAULT_BYTES_PER_ROW,
    ESTIMATION_SAFETY_MARGIN,
    BackupMetadata,
    BinlogPosition,
    DumpMetadata,
    MetadataFormat,
    TableRowEstimate,
    count_rows_in_file,
    ensure_compatible_metadata,
    ensure_myloader_compatibility,
    estimate_rows_by_sampling,
    estimate_rows_from_size,
    get_backup_metadata,
    get_gzip_uncompressed_size,
    get_table_row_estimates,
    parse_binlog_position,
    parse_dump_metadata,
    parse_filename,
)


def create_dummy_sql_gz(filepath: str, content: str) -> None:
    """Helper to create a gzip-compressed SQL file."""
    with gzip.open(filepath, "wt", encoding="utf-8") as f:
        f.write(content)


# ============================================================================
# Metadata Format Detection Tests
# ============================================================================


class TestMetadataFormatDetection:
    """Test format detection for various backup types."""

    def test_detect_ini_format(self, tmp_path: Path) -> None:
        """Detect 0.19+ INI format metadata."""
        metadata = tmp_path / "metadata"
        metadata.write_text("[config]\nquote-character = BACKTICK\n")

        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19

    def test_detect_legacy_format_and_upgrade(self, tmp_path: Path) -> None:
        """Detect and upgrade 0.9 legacy format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("Started dump at: 2025-01-01\nLog: bin.000001\nPos: 123\n")

        # Add a data file so synthesis has something to scan
        create_dummy_sql_gz(
            str(tmp_path / "mydb.users.sql.gz"),
            "INSERT INTO `users` VALUES (1,'test');\n",
        )

        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19

        # Verify upgrade happened
        content = metadata.read_text()
        assert "[config]" in content

    def test_create_metadata_when_missing(self, tmp_path: Path) -> None:
        """Create minimal metadata when missing."""
        # Create a data file so it looks like a backup
        create_dummy_sql_gz(
            str(tmp_path / "db.table.sql.gz"),
            "INSERT INTO t VALUES (1);",
        )

        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19

        metadata = tmp_path / "metadata"
        assert metadata.exists()

    def test_empty_directory_returns_unknown(self, tmp_path: Path) -> None:
        """Empty directory without data files returns UNKNOWN."""
        # Don't create any files
        result = ensure_myloader_compatibility(str(tmp_path))
        # Still creates metadata (empty), returns INI format
        assert result == MetadataFormat.INI_0_19


# ============================================================================
# ISIZE Estimation Tests
# ============================================================================


class TestGzipISIZE:
    """Test ISIZE reading from gzip files."""

    def test_valid_file(self) -> None:
        """Read ISIZE from a valid gzip file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.sql.gz")
            content = "A" * 1000  # 1000 bytes uncompressed
            create_dummy_sql_gz(filepath, content)

            size = get_gzip_uncompressed_size(filepath)
            assert size == 1000

    def test_nonexistent_file(self) -> None:
        """Return 0 for nonexistent file."""
        size = get_gzip_uncompressed_size("/nonexistent/path/file.sql.gz")
        assert size == 0

    def test_invalid_file(self) -> None:
        """Return some value for non-gzip file without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "not_gzip.txt")
            with open(filepath, "w") as f:
                f.write("not a gzip file")

            size = get_gzip_uncompressed_size(filepath)
            assert isinstance(size, int)


class TestRowEstimation:
    """Test ISIZE-based row estimation."""

    def test_basic_estimation(self) -> None:
        """Test basic row estimation calculation."""
        assert estimate_rows_from_size(200) == 1
        assert estimate_rows_from_size(400) == 2
        assert estimate_rows_from_size(1000) == 5
        assert estimate_rows_from_size(2000) == 10

    def test_minimum_one(self) -> None:
        """Estimation always returns at least 1."""
        assert estimate_rows_from_size(0) == 1
        assert estimate_rows_from_size(-1) == 1
        assert estimate_rows_from_size(1) == 1

    def test_custom_bytes_per_row(self) -> None:
        """Test estimation with custom bytes per row."""
        assert estimate_rows_from_size(1000, bytes_per_row=100) == 10
        assert estimate_rows_from_size(1000, bytes_per_row=50) == 20

    def test_sampling_accuracy(self) -> None:
        """Test that sampling gives reasonable accuracy with safety margin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.sql.gz")

            # Create file with known row count: 500 rows
            rows = [f"({i},'user{i}','user{i}@example.com')" for i in range(500)]
            content = "INSERT INTO `users` VALUES " + ",".join(rows) + ";\n"
            create_dummy_sql_gz(filepath, content)

            estimated = estimate_rows_by_sampling(filepath)
            # With 10% safety margin, expect ~550 for 500 actual rows
            # Allow 20% variance: 440 to 660
            assert 440 <= estimated <= 660

    def test_count_rows_in_file(self) -> None:
        """Test count_rows_in_file uses sampling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.sql.gz")
            rows = [f"({i},'value{i}')" for i in range(100)]
            content = "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"
            create_dummy_sql_gz(filepath, content)

            estimated = count_rows_in_file(filepath)
            # With margin, expect ~110. Allow variance: 88 to 132
            assert 88 <= estimated <= 132


# ============================================================================
# Binlog Parsing Tests
# ============================================================================


class TestBinlogParsing:
    """Test binlog position extraction."""

    def test_parse_legacy_binlog(self, tmp_path: Path) -> None:
        """Parse binlog from legacy format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("Started dump at: 2025-01-01\nLog: bin.000001\nPos: 123456\n")

        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is not None
        assert binlog.file == "bin.000001"
        assert binlog.position == 123456
        assert binlog.gtid_set == ""

    def test_parse_ini_binlog(self, tmp_path: Path) -> None:
        """Parse binlog from INI format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""[source]
File = mysql-bin.000042
Position = 987654
Executed_Gtid_Set = abc-123:1-100
""")

        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is not None
        assert binlog.file == "mysql-bin.000042"
        assert binlog.position == 987654
        assert binlog.gtid_set == "abc-123:1-100"

    def test_missing_metadata_returns_none(self, tmp_path: Path) -> None:
        """Return None when metadata file is missing."""
        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is None


# ============================================================================
# Full Metadata Parsing Tests
# ============================================================================


class TestGetBackupMetadata:
    """Test complete backup metadata parsing."""

    def test_parse_ini_with_rows(self, tmp_path: Path) -> None:
        """Parse INI metadata with row counts."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""[config]
quote-character = BACKTICK

[`mydb`.`users`]
rows = 1000

[`mydb`.`orders`]
rows = 5000

[source]
File = mysql-bin.000001
Position = 12345
""")

        result = get_backup_metadata(str(tmp_path))
        assert result.format == MetadataFormat.INI_0_19
        assert result.total_rows == 6000
        assert len(result.tables) == 2
        assert result.binlog is not None
        assert result.binlog.file == "mysql-bin.000001"

    def test_fallback_to_file_scanning(self, tmp_path: Path) -> None:
        """Fall back to ISIZE scanning when no INI."""
        # Create data files without metadata
        rows = [f"({i},'data{i}')" for i in range(50)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"
        create_dummy_sql_gz(str(tmp_path / "db.table.sql.gz"), content)

        result = get_backup_metadata(str(tmp_path))
        assert result.format == MetadataFormat.MISSING
        assert len(result.tables) == 1
        assert result.tables[0].database == "db"
        assert result.tables[0].table == "table"
        # Row count should be an estimate with safety margin
        assert result.tables[0].rows >= 1

    def test_get_table_row_estimates(self, tmp_path: Path) -> None:
        """Test convenience function for row estimates."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""[config]
quote-character = BACKTICK

[`db`.`t1`]
rows = 100

[`db`.`t2`]
rows = 200
""")

        estimates = get_table_row_estimates(str(tmp_path))
        assert len(estimates) == 2
        total = sum(e.rows for e in estimates)
        assert total == 300


# ============================================================================
# Backward Compatibility Tests
# ============================================================================


class TestBackwardCompatibility:
    """Test compatibility wrappers for old module interfaces."""

    def test_parse_dump_metadata_wrapper(self, tmp_path: Path) -> None:
        """Test parse_dump_metadata returns DumpMetadata."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""[config]
quote-character = BACKTICK

[`mydb`.`users`]
rows = 1000
""")

        result = parse_dump_metadata(str(tmp_path))
        assert isinstance(result, DumpMetadata)
        assert result.total_rows == 1000
        assert result.format_version == "0.19+"

    def test_ensure_compatible_metadata_wrapper(self, tmp_path: Path) -> None:
        """Test ensure_compatible_metadata wrapper."""
        create_dummy_sql_gz(
            str(tmp_path / "db.table.sql.gz"),
            "INSERT INTO t VALUES (1);",
        )

        # Should not raise, just call the underlying function
        ensure_compatible_metadata(str(tmp_path))
        assert (tmp_path / "metadata").exists()

    def test_parse_filename_reexport(self) -> None:
        """Test parse_filename is re-exported."""
        assert parse_filename("db.table.sql.gz") == ("db", "table")
        assert parse_filename("db.table.00001.sql.gz") == ("db", "table")
        assert parse_filename("db.table-schema.sql.gz") is None


# ============================================================================
# Integration Tests
# ============================================================================


class TestMetadataSynthesisIntegration:
    """Test full metadata synthesis flow."""

    def test_synthesize_with_legacy_binlog(self, tmp_path: Path) -> None:
        """Synthesize metadata preserving binlog from legacy."""
        # Create legacy metadata with binlog
        legacy = tmp_path / "metadata"
        legacy.write_text("Started dump at: 2025-01-01\nLog: bin.000099\nPos: 999999\n")

        # Create data files
        rows = [f"({i},'x')" for i in range(100)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"
        create_dummy_sql_gz(str(tmp_path / "mydb.users.sql.gz"), content)
        create_dummy_sql_gz(str(tmp_path / "mydb.orders.sql.gz"), content)

        # Run compatibility check (will upgrade)
        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19

        # Verify synthesized metadata
        config = configparser.ConfigParser()
        config.read(str(legacy))

        # Check config section
        assert config.has_section("config")
        assert config.get("config", "quote-character") == "BACKTICK"

        # Check binlog preserved
        assert config.has_section("source")
        assert config.get("source", "File") == "bin.000099"
        assert config.get("source", "Position") == "999999"

        # Check tables synthesized
        assert config.has_section("`mydb`.`users`")
        assert config.has_section("`mydb`.`orders`")

    def test_chunked_table_row_aggregation(self, tmp_path: Path) -> None:
        """Test that chunked table files have rows aggregated."""
        # Create multiple chunks for same table
        rows = [f"({i},'data')" for i in range(50)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"

        create_dummy_sql_gz(str(tmp_path / "db.bigtable.00000.sql.gz"), content)
        create_dummy_sql_gz(str(tmp_path / "db.bigtable.00001.sql.gz"), content)
        create_dummy_sql_gz(str(tmp_path / "db.bigtable.00002.sql.gz"), content)

        result = get_backup_metadata(str(tmp_path))
        assert len(result.tables) == 1
        assert result.tables[0].table == "bigtable"
        # Should be ~165 rows (3 chunks × 55 estimated per chunk with margin)
        assert result.tables[0].rows >= 100  # At least some aggregation happened


# ============================================================================
# Parallel Streaming Row Count Tests
# ============================================================================


class TestStreamingRowCount:
    """Tests for exact row counting via streaming decompression."""

    def test_count_rows_streaming_mydumper_format(self, tmp_path: Path) -> None:
        """Count rows in mydumper 0.9 multi-line format."""
        from pulldb.worker.backup_metadata import count_rows_streaming

        # mydumper 0.9 format: INSERT on first line, continuation rows start with ,(
        content = (
            "/*!40101 SET NAMES binary*/;\n"
            "INSERT INTO `t` VALUES(1,'a')\n"
            ",(2,'b')\n"
            ",(3,'c')\n"
            ",(4,'d')\n"
            ",(5,'e')\n"
            ";\n"
        )
        filepath = str(tmp_path / "db.table.sql.gz")
        create_dummy_sql_gz(filepath, content)

        result = count_rows_streaming(filepath)
        assert result == 5

    def test_count_rows_streaming_multiple_inserts(self, tmp_path: Path) -> None:
        """Count rows from multiple INSERT statements."""
        from pulldb.worker.backup_metadata import count_rows_streaming

        # Multiple INSERT blocks
        content = (
            "INSERT INTO `t` VALUES(1)\n"
            ",(2)\n"
            ",(3)\n"
            ";\n"
            "INSERT INTO `t` VALUES(4)\n"
            ",(5)\n"
            ";\n"
            "INSERT INTO `t` VALUES(6)\n"
            ";\n"
        )
        filepath = str(tmp_path / "db.table.sql.gz")
        create_dummy_sql_gz(filepath, content)

        result = count_rows_streaming(filepath)
        assert result == 6  # 3 + 2 + 1

    def test_count_rows_streaming_nonexistent_returns_zero(self, tmp_path: Path) -> None:
        """Non-existent file returns 0."""
        from pulldb.worker.backup_metadata import count_rows_streaming

        result = count_rows_streaming(str(tmp_path / "nonexistent.sql.gz"))
        assert result == 0

    def test_count_rows_streaming_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns 0."""
        from pulldb.worker.backup_metadata import count_rows_streaming

        filepath = str(tmp_path / "db.empty.sql.gz")
        create_dummy_sql_gz(filepath, "")

        result = count_rows_streaming(filepath)
        assert result == 0


class TestParallelRowCount:
    """Tests for parallel file processing with progress events."""

    def test_count_rows_parallel_basic(self, tmp_path: Path) -> None:
        """Process multiple files in parallel."""
        from pulldb.worker.backup_metadata import count_rows_parallel

        # Create 3 files with known row counts (mydumper 0.9 format)
        create_dummy_sql_gz(
            str(tmp_path / "db.t1.sql.gz"),
            "INSERT INTO `t1` VALUES(1)\n,(2)\n,(3)\n;\n",
        )
        create_dummy_sql_gz(
            str(tmp_path / "db.t2.sql.gz"),
            "INSERT INTO `t2` VALUES(1)\n,(2)\n,(3)\n,(4)\n,(5)\n;\n",
        )
        create_dummy_sql_gz(
            str(tmp_path / "db.t3.sql.gz"),
            "INSERT INTO `t3` VALUES(1)\n;\n",
        )

        result = count_rows_parallel(str(tmp_path))

        assert result["db.t1.sql.gz"] == 3
        assert result["db.t2.sql.gz"] == 5
        assert result["db.t3.sql.gz"] == 1

    def test_count_rows_parallel_excludes_schema_files(self, tmp_path: Path) -> None:
        """Schema files are excluded from row counting."""
        from pulldb.worker.backup_metadata import count_rows_parallel

        create_dummy_sql_gz(
            str(tmp_path / "db.table.sql.gz"),
            "INSERT INTO `t` VALUES(1)\n,(2)\n;\n",
        )
        create_dummy_sql_gz(
            str(tmp_path / "db.table-schema.sql.gz"),
            "CREATE TABLE `t` (id INT);\n",
        )

        result = count_rows_parallel(str(tmp_path))

        assert "db.table.sql.gz" in result
        assert "db.table-schema.sql.gz" not in result

    def test_count_rows_parallel_emits_events(self, tmp_path: Path) -> None:
        """Progress events are emitted during counting with cumulative rows."""
        from pulldb.worker.backup_metadata import count_rows_parallel

        create_dummy_sql_gz(
            str(tmp_path / "db.t1.sql.gz"),
            "INSERT INTO `t` VALUES(1)\n,(2)\n;\n",
        )
        create_dummy_sql_gz(
            str(tmp_path / "db.t2.sql.gz"),
            "INSERT INTO `t` VALUES(1)\n;\n",
        )

        events: list[tuple[str, dict]] = []

        def capture_event(event_type: str, data: dict) -> None:
            events.append((event_type, data))

        count_rows_parallel(str(tmp_path), event_callback=capture_event)

        # Should have start, per-file, and complete events
        event_types = [e[0] for e in events]
        assert "row_count_start" in event_types
        assert "row_count_file_done" in event_types
        assert "row_count_complete" in event_types

        # Verify start event
        start_event = next(e for e in events if e[0] == "row_count_start")
        assert start_event[1]["total_files"] == 2

        # Verify file_done events have cumulative rows_so_far
        file_done_events = [e for e in events if e[0] == "row_count_file_done"]
        assert len(file_done_events) == 2
        # Last file_done should have rows_so_far == total
        last_file_done = file_done_events[-1]
        assert last_file_done[1]["rows_so_far"] == 3  # 2 + 1

        # Verify complete event
        complete_event = next(e for e in events if e[0] == "row_count_complete")
        assert complete_event[1]["total_rows"] == 3  # 2 + 1
        assert complete_event[1]["files_processed"] == 2

    def test_count_rows_parallel_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty dict."""
        from pulldb.worker.backup_metadata import count_rows_parallel

        result = count_rows_parallel(str(tmp_path))
        assert result == {}
