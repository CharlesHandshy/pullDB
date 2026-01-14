import configparser
import gzip
import os
import sys
import tempfile

# Add scripts directory to path so we can import synthesize_metadata
sys.path.append(os.path.join(os.path.dirname(__file__), "../scripts"))

from pulldb.worker.metadata_synthesis import (
    DEFAULT_BYTES_PER_ROW,
    ESTIMATION_SAFETY_MARGIN,
    count_rows_in_file,
    estimate_rows_by_sampling,
    estimate_rows_from_size,
    get_gzip_uncompressed_size,
    parse_filename,
    synthesize_metadata,
)


def create_dummy_sql_gz(filepath: str, content: str) -> None:
    with gzip.open(filepath, "wt", encoding="utf-8") as f:
        f.write(content)


def test_parse_filename() -> None:
    assert parse_filename("db.table.sql.gz") == ("db", "table")
    assert parse_filename("db.table.00001.sql.gz") == ("db", "table")
    assert parse_filename("db.table-schema.sql.gz") is None
    assert parse_filename("db.table-schema-create.sql.gz") is None
    assert parse_filename("not_sql_file.txt") is None


# ============================================================================
# ISIZE Optimization Tests (Phase 1)
# ============================================================================


def test_get_gzip_uncompressed_size_valid_file() -> None:
    """Test reading ISIZE from a valid gzip file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.sql.gz")
        content = "A" * 1000  # 1000 bytes uncompressed
        create_dummy_sql_gz(filepath, content)

        size = get_gzip_uncompressed_size(filepath)
        assert size == 1000, f"Expected 1000, got {size}"


def test_get_gzip_uncompressed_size_nonexistent_file() -> None:
    """Test ISIZE returns 0 for nonexistent file."""
    size = get_gzip_uncompressed_size("/nonexistent/path/file.sql.gz")
    assert size == 0


def test_get_gzip_uncompressed_size_invalid_file() -> None:
    """Test ISIZE returns 0 for non-gzip file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "not_gzip.txt")
        with open(filepath, "w") as f:
            f.write("not a gzip file")

        size = get_gzip_uncompressed_size(filepath)
        # Will return some garbage value from last 4 bytes, but won't crash
        # The important thing is it doesn't raise an exception
        assert isinstance(size, int)


def test_estimate_rows_from_size_basic() -> None:
    """Test basic row estimation calculation."""
    # 200 bytes = 1 row (at default 200 bytes/row)
    assert estimate_rows_from_size(200) == 1

    # 400 bytes = 2 rows
    assert estimate_rows_from_size(400) == 2

    # 1000 bytes = 5 rows
    assert estimate_rows_from_size(1000) == 5

    # 2000 bytes = 10 rows
    assert estimate_rows_from_size(2000) == 10


def test_estimate_rows_from_size_minimum_one() -> None:
    """Test that estimation always returns at least 1."""
    assert estimate_rows_from_size(0) == 1
    assert estimate_rows_from_size(-1) == 1
    assert estimate_rows_from_size(1) == 1  # Less than bytes_per_row


def test_estimate_rows_from_size_custom_bytes_per_row() -> None:
    """Test estimation with custom bytes per row."""
    # 1000 bytes at 100 bytes/row = 10 rows
    assert estimate_rows_from_size(1000, bytes_per_row=100) == 10

    # 1000 bytes at 50 bytes/row = 20 rows
    assert estimate_rows_from_size(1000, bytes_per_row=50) == 20


def test_estimate_rows_from_size_invalid_bytes_per_row() -> None:
    """Test estimation with invalid bytes_per_row returns 1."""
    assert estimate_rows_from_size(1000, bytes_per_row=0) == 1
    assert estimate_rows_from_size(1000, bytes_per_row=-1) == 1


def test_count_rows_in_file_uses_isize_estimation() -> None:
    """Test that count_rows_in_file uses sampling for accurate estimation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.sql.gz")
        # Create realistic SQL content with known row count
        # Extended INSERT format: INSERT INTO ... VALUES (...),(...),...
        rows = [f"({i},'value{i}')" for i in range(100)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"
        create_dummy_sql_gz(filepath, content)

        estimated = count_rows_in_file(filepath)
        # With sampling + safety margin (1.10), expect ~110 for 100 actual rows
        # Allow 20% variance: 88 to 132
        assert 88 <= estimated <= 132, f"Expected ~110 rows (100 + margin), got {estimated}"


def test_count_rows_in_file_nonexistent_returns_one() -> None:
    """Test that count_rows_in_file returns 1 for nonexistent file."""
    rows = count_rows_in_file("/nonexistent/path/file.sql.gz")
    assert rows == 1


# ============================================================================
# Phase 1B: Sampling Tests
# ============================================================================


def test_estimate_rows_by_sampling_accuracy() -> None:
    """Test that sampling gives reasonable accuracy with safety margin."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.sql.gz")

        # Create file with known row count: 500 rows
        rows = [f"({i},'user{i}','user{i}@example.com')" for i in range(500)]
        content = "INSERT INTO `users` VALUES " + ",".join(rows) + ";\n"
        create_dummy_sql_gz(filepath, content)

        estimated = estimate_rows_by_sampling(filepath)
        # With 10% safety margin, expect ~550 for 500 actual rows
        # Allow 20% variance around the margined value: 440 to 660
        assert 440 <= estimated <= 660, f"Expected ~550 (500 + margin), got {estimated}"


def test_estimate_rows_by_sampling_extended_inserts() -> None:
    """Test sampling with extended INSERT format (multiple chunks)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "extended.sql.gz")

        # Create realistic mydumper extended INSERT format
        # Multiple INSERT statements as mydumper does for large tables
        rows_per_insert = 200
        num_inserts = 5
        content = ""
        for _ in range(num_inserts):
            rows = [f"({i},'data{i}')" for i in range(rows_per_insert)]
            content += "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"

        create_dummy_sql_gz(filepath, content)

        estimated = estimate_rows_by_sampling(filepath)
        actual = rows_per_insert * num_inserts  # 1000 rows
        # With 10% safety margin, expect ~1100 for 1000 actual rows
        # Allow 20% variance: 880 to 1320
        assert actual * 0.88 <= estimated <= actual * 1.32, f"Expected ~{actual * 1.1}, got {estimated}"


def test_estimate_rows_by_sampling_small_file() -> None:
    """Test sampling works correctly for files smaller than sample size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "small.sql.gz")

        # Small file with just 10 rows (less than 64KB sample)
        rows = [f"({i},'x')" for i in range(10)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"
        create_dummy_sql_gz(filepath, content)

        estimated = estimate_rows_by_sampling(filepath)
        # With margin, expect ~11 for 10 rows. Allow 50% variance for small files
        assert 5 <= estimated <= 17, f"Expected ~11, got {estimated}"


def test_estimate_rows_by_sampling_fallback_no_rows() -> None:
    """Test fallback when sampling finds no row markers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "norows.sql.gz")

        # Content without INSERT or ),( patterns
        content = "-- This is just a comment\n" * 100
        create_dummy_sql_gz(filepath, content)

        estimated = estimate_rows_by_sampling(filepath)
        # Should fall back to ISIZE/200 estimation
        assert estimated >= 1  # At minimum 1


def test_estimate_rows_by_sampling_nonexistent_file() -> None:
    """Test sampling returns 1 for nonexistent file."""
    estimated = estimate_rows_by_sampling("/nonexistent/path/file.sql.gz")
    assert estimated == 1


def test_synthesize_metadata_integration() -> None:
    """Test end-to-end metadata synthesis with sampling estimation.

    Note: Row counts are now estimates based on sampling + ISIZE.
    We verify the INI structure is correct and row estimates are reasonable.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create files with realistic SQL content for accurate sampling

        # Table 1: Two chunks with 50 rows each = 100 total
        rows1 = [f"({i},'data{i}')" for i in range(50)]
        chunk1_content = "INSERT INTO `table1` VALUES " + ",".join(rows1) + ";\n"
        rows2 = [f"({i},'data{i}')" for i in range(50, 100)]
        chunk2_content = "INSERT INTO `table1` VALUES " + ",".join(rows2) + ";\n"
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table1.00000.sql.gz"),
            chunk1_content,
        )
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table1.00001.sql.gz"),
            chunk2_content,
        )

        # Table 2: Single file with 20 rows
        rows3 = [f"({i},'x')" for i in range(20)]
        table2_content = "INSERT INTO `table2` VALUES " + ",".join(rows3) + ";\n"
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table2.sql.gz"), table2_content
        )

        # Schema file (should be ignored)
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table1-schema.sql.gz"), "CREATE TABLE ..."
        )

        # Run synthesis
        output_ini = os.path.join(tmpdir, "metadata.ini")
        synthesize_metadata(tmpdir, output_ini)

        # Verify output
        config = configparser.ConfigParser()
        config.read(output_ini)

        # Check section names (synthesize_metadata uses backticks)
        s1 = "`mydb`.`table1`"
        s2 = "`mydb`.`table2`"

        assert s1 in config
        # Table 1: ~100 rows total (50+50), with 10% margin expect ~110
        # Allow ±30% for small files: 77 to 143
        table1_rows = int(config[s1]["rows"])
        assert 77 <= table1_rows <= 143, f"Expected ~110 rows for table1, got {table1_rows}"

        assert s2 in config
        # Table 2: ~20 rows, with margin expect ~22
        # Allow ±50% for very small files: 11 to 33
        table2_rows = int(config[s2]["rows"])
        assert 11 <= table2_rows <= 33, f"Expected ~22 rows for table2, got {table2_rows}"
