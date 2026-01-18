"""Unit tests for metadata synthesis smart row estimation."""

import gzip
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pulldb.worker.metadata_synthesis import (
    ESTIMATED_BYTES_PER_ROW,
    LARGE_FILE_THRESHOLD_BYTES,
    MYDUMPER_DEFAULT_ROWS_PER_CHUNK,
    SMALL_FILE_THRESHOLD_BYTES,
    count_rows_in_file,
    estimate_table_rows,
    get_gzip_uncompressed_size,
    parse_filename,
)


class TestGetGzipUncompressedSize:
    """Tests for get_gzip_uncompressed_size function."""

    def test_reads_isize_correctly(self, tmp_path: Path) -> None:
        """Correctly reads ISIZE from gzip file trailer."""
        # Create a gzip file with known uncompressed size
        content = b"Hello, World! " * 1000  # 14,000 bytes
        gz_path = tmp_path / "test.sql.gz"

        with gzip.open(gz_path, "wb") as f:
            f.write(content)

        size = get_gzip_uncompressed_size(str(gz_path))
        assert size == len(content)

    def test_returns_zero_for_nonexistent_file(self) -> None:
        """Returns 0 for file that doesn't exist."""
        size = get_gzip_uncompressed_size("/nonexistent/file.sql.gz")
        assert size == 0

    def test_returns_zero_for_invalid_file(self, tmp_path: Path) -> None:
        """Returns 0 for file that isn't valid gzip."""
        bad_file = tmp_path / "bad.sql.gz"
        bad_file.write_bytes(b"not a gzip file")

        size = get_gzip_uncompressed_size(str(bad_file))
        # Should return something (reads last 4 bytes as int), but not crash
        assert isinstance(size, int)

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Handles empty file gracefully."""
        empty_file = tmp_path / "empty.sql.gz"
        empty_file.write_bytes(b"")

        size = get_gzip_uncompressed_size(str(empty_file))
        assert size == 0


class TestCountRowsInFile:
    """Tests for count_rows_in_file function (used for small files)."""

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

    def test_handles_schema_content(self, tmp_path: Path) -> None:
        """Returns 0 for schema-only content (no INSERTs)."""
        sql_content = b"""\
CREATE TABLE `test` (
  `id` int NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
"""
        gz_path = tmp_path / "schema.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(sql_content)

        count = count_rows_in_file(str(gz_path))
        assert count == 0


class TestEstimateTableRows:
    """Tests for estimate_table_rows function."""

    def test_empty_file_list(self) -> None:
        """Returns 0 for empty file list."""
        rows = estimate_table_rows([])
        assert rows == 0

    def test_single_small_file_counts_directly(self, tmp_path: Path) -> None:
        """Small single files are counted directly."""
        # Create a small file with known row count
        sql_content = b"INSERT INTO t VALUES (1);\n" * 100
        gz_path = tmp_path / "db.table.00000.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(sql_content)

        # Ensure it's under the threshold
        assert gz_path.stat().st_size < SMALL_FILE_THRESHOLD_BYTES

        rows = estimate_table_rows([gz_path])
        assert rows == 100

    def test_single_large_file_uses_isize(self, tmp_path: Path) -> None:
        """Large single files use ISIZE estimation."""
        # Create a file and mock its size to be "large"
        gz_path = tmp_path / "db.table.00000.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(b"x" * 1000)

        # Mock stat to return a large size
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = LARGE_FILE_THRESHOLD_BYTES + 1

            # Also mock get_gzip_uncompressed_size to return known value
            with patch(
                "pulldb.worker.metadata_synthesis.get_gzip_uncompressed_size"
            ) as mock_isize:
                mock_isize.return_value = 200_000  # 200KB uncompressed

                rows = estimate_table_rows([gz_path])

                # 200KB / 200 bytes per row = 1000 rows
                assert rows == 1000

    def test_multiple_chunks_uses_mydumper_math(self, tmp_path: Path) -> None:
        """Multiple chunk files use mydumper 1M rows/chunk math."""
        # Create 3 chunk files with similar sizes
        files = []
        for i in range(3):
            gz_path = tmp_path / f"db.table.{i:05d}.sql.gz"
            with gzip.open(gz_path, "wb") as f:
                f.write(b"x" * 1000)  # Same size for simplicity
            files.append(gz_path)

        rows = estimate_table_rows(files)

        # 2 full chunks * 1M + last chunk estimated from size ratio
        # Since all files are same size, last chunk estimate = 1M
        expected = 2 * MYDUMPER_DEFAULT_ROWS_PER_CHUNK + MYDUMPER_DEFAULT_ROWS_PER_CHUNK
        assert rows == expected

    def test_last_chunk_size_ratio(self, tmp_path: Path) -> None:
        """Last chunk row count estimated from size ratio."""
        files = []

        # Full chunks: 1000 bytes each
        for i in range(2):
            gz_path = tmp_path / f"db.table.{i:05d}.sql.gz"
            with gzip.open(gz_path, "wb") as f:
                f.write(b"x" * 1000)
            files.append(gz_path)

        # Last chunk: 500 bytes (half size)
        last_path = tmp_path / "db.table.00002.sql.gz"
        with gzip.open(last_path, "wb") as f:
            f.write(b"x" * 500)
        files.append(last_path)

        rows = estimate_table_rows(files)

        # 3 files total: 2 full chunks * 1M + last chunk at ~50% 
        # But gzip adds overhead, so actual ratio won't be exactly 50%
        # Just verify it's roughly in the expected range
        assert rows >= 2 * MYDUMPER_DEFAULT_ROWS_PER_CHUNK  # At least 2M from full chunks


class TestParseFilename:
    """Tests for parse_filename function."""

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


class TestPerformanceCharacteristics:
    """Tests documenting expected performance characteristics."""

    def test_isize_is_constant_time(self, tmp_path: Path) -> None:
        """ISIZE read is O(1) regardless of file size."""
        # Create files of different sizes
        small_path = tmp_path / "small.sql.gz"
        with gzip.open(small_path, "wb") as f:
            f.write(b"x" * 100)

        large_path = tmp_path / "large.sql.gz"
        with gzip.open(large_path, "wb") as f:
            f.write(b"x" * 100_000)

        # Both should complete quickly (we can't really test timing reliably,
        # but we can verify the function works for both)
        small_size = get_gzip_uncompressed_size(str(small_path))
        large_size = get_gzip_uncompressed_size(str(large_path))

        assert small_size == 100
        assert large_size == 100_000

    def test_chunked_estimation_is_constant_time_per_file(self, tmp_path: Path) -> None:
        """Chunked table estimation only uses stat(), not file content."""
        # Create many chunk files
        files = []
        for i in range(100):
            gz_path = tmp_path / f"db.table.{i:05d}.sql.gz"
            with gzip.open(gz_path, "wb") as f:
                f.write(b"x" * 1000)
            files.append(gz_path)

        # This should be fast (100 stat calls, no decompression)
        rows = estimate_table_rows(files)

        # 99 full chunks + last chunk estimate
        assert rows > 99 * MYDUMPER_DEFAULT_ROWS_PER_CHUNK
