import configparser
import gzip
import os
import sys
import tempfile

# Add scripts directory to path so we can import synthesize_metadata
sys.path.append(os.path.join(os.path.dirname(__file__), "../scripts"))

from pulldb.worker.metadata_synthesis import (
    count_rows_in_file,
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


def test_count_rows_in_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # Case 1: Simple inserts
        f1 = os.path.join(tmpdir, "simple.sql.gz")
        content1 = """
        INSERT INTO `t` VALUES (1);
        INSERT INTO `t` VALUES (2);
        """
        create_dummy_sql_gz(f1, content1)
        assert count_rows_in_file(f1) == 2

        # Case 2: Extended inserts
        f2 = os.path.join(tmpdir, "extended.sql.gz")
        content2 = """
        INSERT INTO `t` VALUES (1)
        ,(2)
        ,(3);
        """
        create_dummy_sql_gz(f2, content2)
        assert count_rows_in_file(f2) == 3

        # Case 3: Complex strings (simulating HTML with escaped newlines)
        # Note: mydumper escapes newlines in strings as \n,
        # so they remain on one line physically
        f3 = os.path.join(tmpdir, "complex.sql.gz")
        content3 = """
        INSERT INTO `t` VALUES (1, "some text")
        ,(2, "multi\\nline\\ntext")
        ,(3, "<div>html</div>");
        """
        create_dummy_sql_gz(f3, content3)
        assert count_rows_in_file(f3) == 3


def test_synthesize_metadata_integration() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some dummy files

        # Table 1: 5 rows total (split across 2 chunks)
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table1.00000.sql.gz"),
            "INSERT INTO `t` VALUES (1)\n,(2)\n,(3);",
        )
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table1.00001.sql.gz"),
            "INSERT INTO `t` VALUES (4)\n,(5);",
        )

        # Table 2: 1 row
        create_dummy_sql_gz(
            os.path.join(tmpdir, "mydb.table2.sql.gz"), "INSERT INTO `t` VALUES (1);"
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
        assert config[s1]["rows"] == "5"

        assert s2 in config
        assert config[s2]["rows"] == "1"
