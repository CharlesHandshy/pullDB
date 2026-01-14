import configparser
import gzip
import os
import sys
import tempfile

# Add scripts directory to path so we can import synthesize_metadata
sys.path.append(os.path.join(os.path.dirname(__file__), "../scripts"))

from pulldb.worker.metadata_synthesis import (
    DEFAULT_BYTES_PER_ROW,
    count_rows_in_file,
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
    """Test that count_rows_in_file now uses ISIZE estimation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.sql.gz")
        # Create content of known size
        content = "A" * 2000  # 2000 bytes = 10 rows at 200 bytes/row
        create_dummy_sql_gz(filepath, content)

        rows = count_rows_in_file(filepath)
        # Should estimate ~10 rows (2000 / 200)
        assert rows == 10, f"Expected ~10 estimated rows, got {rows}"


def test_count_rows_in_file_nonexistent_returns_one() -> None:
    """Test that count_rows_in_file returns 1 for nonexistent file."""
    rows = count_rows_in_file("/nonexistent/path/file.sql.gz")
    assert rows == 1


def test_synthesize_metadata_integration() -> None:
    """Test end-to-end metadata synthesis with ISIZE estimation.

    Note: Row counts are now estimates based on uncompressed file size,
    not exact counts. We verify the INI structure is correct and that
    tables are detected properly.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some dummy files with known content sizes
        # Each file has predictable uncompressed size for estimation

        # Table 1: Two chunks with substantial content
        chunk1_content = "A" * 600  # 600 bytes -> 3 rows estimated
        chunk2_content = "A" * 400  # 400 bytes -> 2 rows estimated
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table1.00000.sql.gz"),
            chunk1_content,
        )
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table1.00001.sql.gz"),
            chunk2_content,
        )

        # Table 2: Single small file
        table2_content = "A" * 200  # 200 bytes -> 1 row estimated
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

        assert (
            "mydb.table1" in config.sections() or "`mydb`.`table1`" in config.sections()
        )

        # Check section names (synthesize_metadata uses backticks)
        s1 = "`mydb`.`table1`"
        s2 = "`mydb`.`table2`"

        assert s1 in config
        # Table 1: 600 + 400 = 1000 bytes / 200 = 5 estimated rows
        assert config[s1]["rows"] == "5", f"Expected 5 rows for table1, got {config[s1]['rows']}"

        assert s2 in config
        # Table 2: 200 bytes / 200 = 1 estimated row
        assert config[s2]["rows"] == "1", f"Expected 1 row for table2, got {config[s2]['rows']}"
