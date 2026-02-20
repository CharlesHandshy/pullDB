"""Unit tests for pulldb.cli.backup_commands pure utility functions.

Tests the three pure functions that have no I/O dependency:
  - _parse_size: human-readable size → bytes
  - _parse_date: date string → YYYYMMDD
  - _extract_date_from_key: S3 object key → YYYYMMDD

HCA Layer: features (tests)
"""

from __future__ import annotations

import pytest

from pulldb.cli.backup_commands import _parse_date, _parse_size, _extract_date_from_key

try:
    import click
except ImportError:
    click = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# _parse_size
# ---------------------------------------------------------------------------

class TestParseSize:
    def test_gigabytes(self) -> None:
        assert _parse_size("5GB") == 5 * 1024 ** 3

    def test_megabytes(self) -> None:
        assert _parse_size("500MB") == 500 * 1024 ** 2

    def test_terabytes(self) -> None:
        assert _parse_size("1TB") == 1024 ** 4

    def test_kilobytes(self) -> None:
        assert _parse_size("1024KB") == 1024 * 1024

    def test_bytes_default_unit(self) -> None:
        assert _parse_size("1024") == 1024

    def test_decimal_gigabytes(self) -> None:
        # 1.5 GB = 1.5 * 1024^3 bytes
        result = _parse_size("1.5GB")
        assert result == int(1.5 * 1024 ** 3)

    def test_lowercase_unit(self) -> None:
        # Units should be case-insensitive
        assert _parse_size("5gb") == _parse_size("5GB")

    def test_whitespace_stripped(self) -> None:
        assert _parse_size("  10MB  ") == 10 * 1024 ** 2

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(Exception):  # click.BadParameter
            _parse_size("invalid")

    def test_missing_number_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_size("GB")

    def test_zero_size(self) -> None:
        assert _parse_size("0GB") == 0


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_yyyymmdd_format(self) -> None:
        assert _parse_date("20260101") == "20260101"

    def test_dashed_format(self) -> None:
        assert _parse_date("2026-01-01") == "20260101"

    def test_dashed_format_mid_year(self) -> None:
        assert _parse_date("2025-06-15") == "20250615"

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_date("01/01/2026")

    def test_too_short_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_date("2026101")

    def test_invalid_date_raises(self) -> None:
        # Feb 30 doesn't exist
        with pytest.raises(Exception):
            _parse_date("20260230")

    def test_non_digit_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_date("2026ABCD")


# ---------------------------------------------------------------------------
# _extract_date_from_key
# ---------------------------------------------------------------------------

class TestExtractDateFromKey:
    def test_extracts_date_from_valid_key(self) -> None:
        key = "backups/acme/daily_mydumper_acme_2026-01-15T06-18-55Z_Thu_dbimp.tar"
        result = _extract_date_from_key(key)
        assert result == "20260115"

    def test_returns_none_for_non_backup_key(self) -> None:
        result = _extract_date_from_key("some/random/file.txt")
        assert result is None

    def test_returns_none_for_empty_key(self) -> None:
        result = _extract_date_from_key("")
        assert result is None

    def test_handles_key_without_directory(self) -> None:
        key = "daily_mydumper_acme_2025-12-31T00-00-00Z_Wed_db1.tar"
        result = _extract_date_from_key(key)
        assert result == "20251231"

    def test_handles_deep_nested_key(self) -> None:
        key = "us-east-1/prod/customers/acme/2026/daily_mydumper_bigcorp_2026-03-20T10-30-00Z_Fri_dbimp.tar"
        result = _extract_date_from_key(key)
        assert result == "20260320"
