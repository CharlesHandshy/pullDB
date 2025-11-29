"""Tests for atomic logic units (Level 3 atoms).

These tests verify the smallest units of logic identified in the flow graph,
ensuring "full functionality tests from the atoms backwards".
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from pulldb.cli.parse import _tokenize
from pulldb.domain.config import (
    _parse_extra_args,
    _parse_positive_float,
    _parse_positive_int,
)
from pulldb.domain.errors import StagingError
from pulldb.domain.restore_models import MyLoaderSpec
from pulldb.infra.s3 import BACKUP_FILENAME_REGEX, parse_s3_bucket_path
from pulldb.worker.downloader import _stream_download
from pulldb.worker.post_sql import _discover_scripts
from pulldb.worker.restore import build_myloader_command
from pulldb.worker.staging import (
    _find_orphaned_staging_databases,
    generate_staging_name,
)


# --- Atom: cp_tokens ---
def test_atom_cp_tokens() -> None:
    """Verify tokenization loop logic."""
    # Case 1: Customer with dbhost and overwrite
    user, cust, is_qa, host, date, s3env, over = _tokenize(
        ["customer=Acme", "dbhost=db1", "overwrite"]
    )
    assert cust == "Acme"
    assert not is_qa
    assert host == "db1"
    assert date is None
    assert s3env is None
    assert over
    assert user is None

    # Case 2: QA Template
    user, cust, is_qa, host, date, s3env, over = _tokenize(["qatemplate"])
    assert cust is None
    assert is_qa
    assert host is None
    assert date is None
    assert s3env is None
    assert not over

    # Case 3: Error (Unknown)
    from pulldb.cli.parse import CLIParseError

    with pytest.raises(CLIParseError, match="Unrecognized token"):
        _tokenize(["unknown=1"])


# --- Atom: s3_regex ---
def test_atom_s3_regex() -> None:
    """Verify S3 filename regex parsing."""
    # Valid
    fname = "daily_mydumper_acme_2024-10-15T06-22-10Z_Tue_dbimp.tar"
    match = BACKUP_FILENAME_REGEX.match(fname)
    assert match
    assert match.group("target") == "acme"
    assert match.group("ts") == "2024-10-15T06-22-10Z"

    # Invalid
    assert not BACKUP_FILENAME_REGEX.match("daily_mydumper_acme.tar")


# --- Atom: wd_stream ---
def test_atom_wd_stream() -> None:
    """Verify download stream loop."""

    class FakeBody:
        def __init__(self, data: bytes, chunk_size: int):
            self.data = data
            self.chunk_size = chunk_size
            self.pos = 0

        def read(self, size: int) -> bytes:
            if self.pos >= len(self.data):
                return b""
            # Return smaller of requested size or internal chunk size to simulate chunks
            read_size = min(size, self.chunk_size, len(self.data) - self.pos)
            chunk = self.data[self.pos : self.pos + read_size]
            self.pos += read_size
            return chunk

    data = b"x" * 1000
    body = FakeBody(data, chunk_size=100)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _stream_download(body, tmp_path, "job-1", len(data))

        assert os.path.exists(tmp_path)
        with open(tmp_path, "rb") as f:
            assert f.read() == data
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# --- Atom: wr_cmd ---
def test_atom_wr_cmd() -> None:
    """Verify myloader command construction."""
    spec = MyLoaderSpec(
        job_id="job-1",
        staging_db="staging_db",
        backup_dir="/tmp/backup",
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="user",
        mysql_password="pwd",
        binary_path="myloader",
        extra_args=["--threads=4"],
        env={},
    )
    cmd = build_myloader_command(spec)
    assert cmd[0] == "myloader"
    assert "--database=staging_db" in cmd
    assert "--directory=/tmp/backup" in cmd
    assert "--threads=4" in cmd


# --- Atom: stg_name ---
def test_atom_stg_name() -> None:
    """Verify staging name generation logic."""
    # Success
    target = "customer12"
    job_id = "550e8400-e29b-41d4-a716-446655440000"
    expected = "customer12_550e8400e29b"
    assert generate_staging_name(target, job_id) == expected

    # Target too long
    with pytest.raises(StagingError, match="exceeds maximum"):
        generate_staging_name("a" * 52, job_id)

    # Job ID too short
    with pytest.raises(StagingError, match="too short"):
        generate_staging_name("customer", "short")

    # Invalid Hex
    with pytest.raises(StagingError, match="non-hexadecimal"):
        generate_staging_name("customer", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz")


# --- Atom: stg_orphan ---
def test_atom_stg_orphan() -> None:
    """Verify staging orphan detection logic."""
    target = "cust1"
    databases = [
        "cust1",
        "cust1_1234567890ab",
        "cust1_1234567890ab_extra",
        "cust1_short",
        "other_1234567890ab",
        "cust1_ABCDEF123456",
        "cust1_1234567890ac",
    ]
    expected = ["cust1_1234567890ab", "cust1_1234567890ac"]
    assert _find_orphaned_staging_databases(target, databases) == expected


# --- Atom: s3_parse ---
def test_atom_s3_parse() -> None:
    """Verify S3 path parsing logic."""
    assert parse_s3_bucket_path("s3://my-bucket/path/to/") == ("my-bucket", "path/to/")
    assert parse_s3_bucket_path("my-bucket/path") == ("my-bucket", "path/")
    assert parse_s3_bucket_path("bucket-only") == ("bucket-only", "")

    with pytest.raises(ValueError):
        parse_s3_bucket_path("")
    with pytest.raises(ValueError):
        parse_s3_bucket_path("s3://")


# --- Atom: cfg_parse ---
def test_atom_cfg_parse() -> None:
    """Verify config parsing logic."""
    # Extra args
    assert _parse_extra_args(None, source="test") == ()
    assert _parse_extra_args("--flag value", source="test") == ("--flag", "value")

    # Float
    assert _parse_positive_float("10.5", source="test") == 10.5
    with pytest.raises(ValueError):
        _parse_positive_float("0", source="test")

    # Int
    assert _parse_positive_int("10", source="test") == 10
    with pytest.raises(ValueError):
        _parse_positive_int("10.5", source="test")


# --- Atom: psql_disc ---
def test_atom_psql_disc(tmp_path: Path) -> None:
    """Verify post-SQL script discovery logic."""
    (tmp_path / "020.sql").touch()
    (tmp_path / "010.sql").touch()
    (tmp_path / "005.sql").touch()
    (tmp_path / "ignore.txt").touch()

    scripts = _discover_scripts(tmp_path)
    names = [p.name for p in scripts]
    assert names == ["005.sql", "010.sql", "020.sql"]

    assert _discover_scripts(tmp_path / "nonexistent") == []
