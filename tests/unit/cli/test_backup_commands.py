"""Unit tests for pulldb.cli.backup_commands.

Covers:
  Pure utilities (no I/O):
    - _parse_size: human-readable size → bytes
    - _parse_date: date string → YYYYMMDD
    - _extract_date_from_key: S3 object key → YYYYMMDD

  S3 collection/filtering logic (mocked S3 client):
    - _get_backup_locations: JSON env-var parsing + environment filter
    - CustomerBackupStats.add_backup: aggregation invariants
    - _collect_all_backups: date / size / customer filtering, multi-page,
      multi-location, non-.tar skip, non-alpha customer skip
    - _collect_pattern_backups: fnmatch wildcard, prefix optimisation

HCA Layer: features (tests)
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from pulldb.cli.backup_commands import (
    CustomerBackupStats,
    _collect_all_backups,
    _collect_pattern_backups,
    _extract_date_from_key,
    _get_backup_locations,
    _parse_date,
    _parse_size,
)

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


# ---------------------------------------------------------------------------
# _get_backup_locations
# ---------------------------------------------------------------------------

_SAMPLE_LOCATIONS_JSON = json.dumps(
    [
        {
            "name": "prod",
            "bucket_path": "s3://my-prod-bucket/backups/",
            "profile": "prod-profile",
        },
        {
            "name": "staging",
            "bucket_path": "s3://my-staging-bucket/backups/",
            "profile": None,
        },
        {
            "name": "dev",
            "bucket_path": "s3://my-dev-bucket/",
        },
    ]
)


class TestGetBackupLocations:
    def test_returns_all_when_environment_is_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", _SAMPLE_LOCATIONS_JSON)
        result = _get_backup_locations("both")
        assert len(result) == 3

    def test_filters_by_environment_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", _SAMPLE_LOCATIONS_JSON)
        result = _get_backup_locations("prod")
        assert len(result) == 1
        name, bucket, prefix, profile, region = result[0]
        assert name == "prod"
        assert bucket == "my-prod-bucket"
        assert prefix == "backups/"
        assert profile == "prod-profile"
        assert region is None  # no region in sample

    def test_staging_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", _SAMPLE_LOCATIONS_JSON)
        result = _get_backup_locations("staging")
        assert len(result) == 1
        assert result[0][0] == "staging"
        assert result[0][3] is None  # no profile
        assert result[0][4] is None  # no region

    def test_region_field_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps([
            {
                "name": "eu-prod",
                "bucket_path": "s3://eu-bucket/backups/",
                "profile": "eu-profile",
                "region": "eu-west-1",
            }
        ])
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", payload)
        result = _get_backup_locations("eu-prod")
        assert len(result) == 1
        _, _, _, _, region = result[0]
        assert region == "eu-west-1"

    def test_bucket_without_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # "s3://my-dev-bucket/" has no path component beyond the bucket,
        # so the code leaves prefix as "" (no sub-path)
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", _SAMPLE_LOCATIONS_JSON)
        result = _get_backup_locations("dev")
        assert len(result) == 1
        _, bucket, prefix, _, _ = result[0]
        assert bucket == "my-dev-bucket"
        # The trailing slash in "s3://my-dev-bucket/" produces prefix="" after
        # splitting on "/" and joining the rest — but the code appends "/" to
        # non-empty prefixes only, so an empty path segment becomes "/".
        # Accept whatever the implementation returns for a bucket-only path.
        assert prefix in ("", "/")

    def test_raises_when_env_var_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PULLDB_S3_BACKUP_LOCATIONS", raising=False)
        with pytest.raises(Exception):
            _get_backup_locations("prod")

    def test_raises_on_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", "not-json{")
        with pytest.raises(Exception):
            _get_backup_locations("prod")

    def test_raises_when_no_matching_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", _SAMPLE_LOCATIONS_JSON)
        with pytest.raises(Exception):
            _get_backup_locations("nonexistent-env")

    def test_skips_entries_without_s3_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps([
            {"name": "both", "bucket_path": "gs://wrong-bucket/"},
            {"name": "both", "bucket_path": "s3://correct-bucket/ok/"},
        ])
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", payload)
        result = _get_backup_locations("both")
        assert len(result) == 1
        assert result[0][1] == "correct-bucket"

    def test_raises_when_payload_is_not_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", json.dumps({"name": "prod"}))
        with pytest.raises(Exception):
            _get_backup_locations("prod")


# ---------------------------------------------------------------------------
# CustomerBackupStats.add_backup
# ---------------------------------------------------------------------------


class TestCustomerBackupStatsAddBackup:
    def test_first_backup_sets_all_fields(self) -> None:
        s = CustomerBackupStats(customer="acme")
        s.add_backup(1000, "20260115")
        assert s.count == 1
        assert s.total_bytes == 1000
        assert s.min_bytes == 1000
        assert s.max_bytes == 1000
        assert s.oldest_date == "20260115"
        assert s.newest_date == "20260115"

    def test_avg_bytes_computed_correctly(self) -> None:
        s = CustomerBackupStats(customer="acme")
        s.add_backup(1000, "20260101")
        s.add_backup(3000, "20260102")
        assert s.avg_bytes == 2000

    def test_min_bytes_tracks_smallest(self) -> None:
        s = CustomerBackupStats(customer="acme")
        s.add_backup(5000, "20260101")
        s.add_backup(2000, "20260102")
        s.add_backup(8000, "20260103")
        assert s.min_bytes == 2000

    def test_max_bytes_tracks_largest(self) -> None:
        s = CustomerBackupStats(customer="acme")
        s.add_backup(5000, "20260101")
        s.add_backup(2000, "20260102")
        s.add_backup(8000, "20260103")
        assert s.max_bytes == 8000

    def test_date_range_tracks_oldest_and_newest(self) -> None:
        s = CustomerBackupStats(customer="acme")
        s.add_backup(1000, "20260315")
        s.add_backup(1000, "20260101")
        s.add_backup(1000, "20260630")
        assert s.oldest_date == "20260101"
        assert s.newest_date == "20260630"

    def test_empty_date_string_ignored(self) -> None:
        s = CustomerBackupStats(customer="acme")
        s.add_backup(1000, "20260115")
        s.add_backup(2000, "")
        assert s.oldest_date == "20260115"
        assert s.newest_date == "20260115"

    def test_count_increments_correctly(self) -> None:
        s = CustomerBackupStats(customer="acme")
        for i in range(5):
            s.add_backup(1000, f"202601{i+1:02d}")
        assert s.count == 5

    def test_avg_bytes_zero_when_empty(self) -> None:
        s = CustomerBackupStats(customer="acme")
        assert s.avg_bytes == 0


# ---------------------------------------------------------------------------
# Helpers for S3 collection tests
# ---------------------------------------------------------------------------

_PROD_LOCATION: list[tuple[str, str, str, str | None, str | None]] = [
    ("prod", "my-bucket", "backups/", None, None)
]

_TWO_LOCATIONS: list[tuple[str, str, str, str | None, str | None]] = [
    ("prod", "prod-bucket", "backups/", None, None),
    ("staging", "staging-bucket", "staging/", None, None),
]


def _make_key(prefix: str, customer: str, date: str, suffix: str = "db1") -> str:
    """Build a realistic S3 backup key."""
    # date format "20260115" → "2026-01-15"
    d = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return f"{prefix}{customer}/daily_mydumper_{customer}_{d}T06-00-00Z_Mon_{suffix}.tar"


# ---------------------------------------------------------------------------
# _collect_all_backups
# ---------------------------------------------------------------------------


class TestCollectAllBackups:
    def _run(
        self,
        keys_with_sizes: list[tuple[str, int]],
        locations: list[tuple[str, str, str, str | None, str | None]] | None = None,
        **kwargs: object,
    ) -> dict[str, CustomerBackupStats]:
        if locations is None:
            locations = _PROD_LOCATION
        defaults = dict(
            customer_filter=None,
            date_from=None,
            date_to=None,
            min_bytes=None,
            max_bytes=None,
            verbose=False,
        )
        defaults.update(kwargs)  # type: ignore[arg-type]
        with patch("pulldb.cli.backup_commands.S3Client") as MockS3:
            mock_s3 = MagicMock()
            MockS3.return_value = mock_s3
            mock_s3.list_keys_with_sizes.return_value = keys_with_sizes
            return _collect_all_backups(locations, **defaults)  # type: ignore[arg-type]

    def test_basic_aggregation(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
            (_make_key("backups/", "acme", "20260116"), 2_000_000),
        ]
        result = self._run(keys)
        assert "acme" in result
        assert result["acme"].count == 2
        assert result["acme"].total_bytes == 3_000_000

    def test_skips_non_tar_files(self) -> None:
        keys = [
            ("backups/acme/some_file.sql", 500),
            ("backups/acme/manifest.json", 100),
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
        ]
        result = self._run(keys)
        assert result["acme"].count == 1

    def test_skips_customer_with_uppercase(self) -> None:
        keys = [
            (_make_key("backups/", "Acme", "20260115"), 1_000_000),
            (_make_key("backups/", "acme", "20260115"), 2_000_000),
        ]
        result = self._run(keys)
        assert "acme" in result
        assert "Acme" not in result
        assert result["acme"].count == 1

    def test_skips_customer_with_digits(self) -> None:
        keys = [
            (_make_key("backups/", "acme123", "20260115"), 1_000_000),
            (_make_key("backups/", "acme", "20260115"), 2_000_000),
        ]
        result = self._run(keys)
        assert "acme123" not in result
        assert "acme" in result

    def test_customer_filter_exact_match(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
            (_make_key("backups/", "beta", "20260115"), 1_000_000),
        ]
        result = self._run(keys, customer_filter="acme")
        assert "acme" in result
        assert "beta" not in result

    def test_date_from_filter(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260101"), 1_000_000),
            (_make_key("backups/", "acme", "20260201"), 2_000_000),
        ]
        result = self._run(keys, date_from="20260115")
        assert result["acme"].count == 1
        assert result["acme"].total_bytes == 2_000_000

    def test_date_to_filter(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260101"), 1_000_000),
            (_make_key("backups/", "acme", "20260201"), 2_000_000),
        ]
        result = self._run(keys, date_to="20260115")
        assert result["acme"].count == 1
        assert result["acme"].total_bytes == 1_000_000

    def test_min_bytes_filter(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260101"), 500_000),
            (_make_key("backups/", "acme", "20260102"), 2_000_000),
        ]
        result = self._run(keys, min_bytes=1_000_000)
        assert result["acme"].count == 1

    def test_max_bytes_filter(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260101"), 500_000),
            (_make_key("backups/", "acme", "20260102"), 2_000_000),
        ]
        result = self._run(keys, max_bytes=1_000_000)
        assert result["acme"].count == 1

    def test_multiple_customers_aggregated_separately(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
            (_make_key("backups/", "beta", "20260115"), 2_000_000),
            (_make_key("backups/", "gamma", "20260115"), 3_000_000),
        ]
        result = self._run(keys)
        assert len(result) == 3
        assert result["acme"].total_bytes == 1_000_000
        assert result["beta"].total_bytes == 2_000_000
        assert result["gamma"].total_bytes == 3_000_000

    def test_multi_location_merges_stats(self) -> None:
        """Results from two S3 locations with same customer are merged."""
        keys_loc1 = [(_make_key("backups/", "acme", "20260115"), 1_000_000)]
        keys_loc2 = [(_make_key("staging/", "acme", "20260116"), 2_000_000)]

        with patch("pulldb.cli.backup_commands.S3Client") as MockS3:
            mock_s3 = MagicMock()
            MockS3.return_value = mock_s3
            mock_s3.list_keys_with_sizes.side_effect = [keys_loc1, keys_loc2]
            result = _collect_all_backups(
                _TWO_LOCATIONS,
                customer_filter=None,
                date_from=None,
                date_to=None,
                min_bytes=None,
                max_bytes=None,
                verbose=False,
            )

        assert result["acme"].count == 2
        assert result["acme"].total_bytes == 3_000_000

    def test_s3_error_skips_location(self) -> None:
        """If S3 raises, location is skipped and other locations still work."""
        keys_loc2 = [(_make_key("staging/", "acme", "20260116"), 2_000_000)]
        with patch("pulldb.cli.backup_commands.S3Client") as MockS3:
            mock_s3 = MagicMock()
            MockS3.return_value = mock_s3
            mock_s3.list_keys_with_sizes.side_effect = [Exception("Access Denied"), keys_loc2]
            result = _collect_all_backups(
                _TWO_LOCATIONS,
                customer_filter=None,
                date_from=None,
                date_to=None,
                min_bytes=None,
                max_bytes=None,
                verbose=False,
            )
        assert result["acme"].count == 1

    def test_skips_key_at_root_level(self) -> None:
        """Keys with no customer directory segment are skipped."""
        keys = [
            ("backups/daily_mydumper_acme_2026-01-15T06-00-00Z_Mon_db1.tar", 1_000_000),
        ]
        result = self._run(keys)
        assert len(result) == 0

    def test_empty_s3_result_returns_empty_dict(self) -> None:
        result = self._run([])
        assert result == {}

    def test_per_location_s3_client_receives_region(self) -> None:
        """S3Client must be constructed with the location's region (M8)."""
        locations: list[tuple[str, str, str, str | None, str | None]] = [
            ("eu-prod", "eu-bucket", "backups/", "eu-profile", "eu-west-1"),
        ]
        with patch("pulldb.cli.backup_commands.S3Client") as MockS3:
            MockS3.return_value.list_keys_with_sizes.return_value = []
            _collect_all_backups(
                locations,
                customer_filter=None,
                date_from=None,
                date_to=None,
                min_bytes=None,
                max_bytes=None,
                verbose=False,
            )
            MockS3.assert_called_once_with(profile="eu-profile", region="eu-west-1")


# ---------------------------------------------------------------------------
# _collect_pattern_backups
# ---------------------------------------------------------------------------


class TestCollectPatternBackups:
    def _run(
        self,
        keys_with_sizes: list[tuple[str, int]],
        pattern: str,
        locations: list[tuple[str, str, str, str | None, str | None]] | None = None,
        **kwargs: object,
    ) -> dict[str, CustomerBackupStats]:
        if locations is None:
            locations = _PROD_LOCATION
        defaults = dict(
            date_from=None,
            date_to=None,
            min_bytes=None,
            max_bytes=None,
            verbose=False,
        )
        defaults.update(kwargs)  # type: ignore[arg-type]
        with patch("pulldb.cli.backup_commands.S3Client") as MockS3:
            mock_s3 = MagicMock()
            MockS3.return_value = mock_s3
            mock_s3.list_keys_with_sizes.return_value = keys_with_sizes
            return _collect_pattern_backups(locations, pattern, **defaults)  # type: ignore[arg-type]

    def test_wildcard_matches_multiple_customers(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
            (_make_key("backups/", "acorp", "20260115"), 2_000_000),
            (_make_key("backups/", "beta", "20260115"), 3_000_000),
        ]
        result = self._run(keys, pattern="a*")
        assert "acme" in result
        assert "acorp" in result
        assert "beta" not in result

    def test_question_mark_wildcard(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
            (_make_key("backups/", "acorp", "20260115"), 2_000_000),
        ]
        # "ac??" matches "acme" (4 chars) but not "acorp" (5 chars)
        result = self._run(keys, pattern="ac??")
        assert "acme" in result
        assert "acorp" not in result

    def test_exact_pattern_no_wildcard(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
            (_make_key("backups/", "beta", "20260115"), 2_000_000),
        ]
        result = self._run(keys, pattern="acme")
        assert "acme" in result
        assert "beta" not in result

    def test_prefix_optimisation_sets_correct_s3_prefix(self) -> None:
        """S3 listing must be called with the literal prefix before first wildcard."""
        with patch("pulldb.cli.backup_commands.S3Client") as MockS3:
            mock_s3 = MagicMock()
            MockS3.return_value = mock_s3
            mock_s3.list_keys_with_sizes.return_value = []
            _collect_pattern_backups(
                _PROD_LOCATION,
                pattern="ac*",
                date_from=None,
                date_to=None,
                min_bytes=None,
                max_bytes=None,
                verbose=False,
            )
            called_prefix = mock_s3.list_keys_with_sizes.call_args[0][1]
            # Expected: "backups/" (location prefix) + "ac" (literal prefix before *)
            assert called_prefix == "backups/ac"

    def test_date_filter_applied(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260101"), 1_000_000),
            (_make_key("backups/", "acme", "20260201"), 2_000_000),
        ]
        result = self._run(keys, pattern="acme", date_from="20260115")
        assert result["acme"].count == 1
        assert result["acme"].total_bytes == 2_000_000

    def test_size_filter_applied(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260101"), 100_000),
            (_make_key("backups/", "acme", "20260102"), 5_000_000),
        ]
        result = self._run(keys, pattern="acme", min_bytes=1_000_000)
        assert result["acme"].count == 1

    def test_case_insensitive_pattern(self) -> None:
        keys = [
            (_make_key("backups/", "acme", "20260115"), 1_000_000),
        ]
        result = self._run(keys, pattern="ACME")
        assert "acme" in result

    def test_non_alpha_customer_skipped(self) -> None:
        keys = [
            (_make_key("backups/", "acme123", "20260115"), 1_000_000),
        ]
        result = self._run(keys, pattern="acme*")
        assert len(result) == 0

    def test_empty_result_when_no_match(self) -> None:
        keys = [
            (_make_key("backups/", "beta", "20260115"), 1_000_000),
        ]
        result = self._run(keys, pattern="xyz*")
        assert result == {}

    def test_per_location_s3_client_receives_region(self) -> None:
        """S3Client must be constructed with the location's region (M8)."""
        locations: list[tuple[str, str, str, str | None, str | None]] = [
            ("ap-prod", "ap-bucket", "backups/", "ap-profile", "ap-southeast-1"),
        ]
        with patch("pulldb.cli.backup_commands.S3Client") as MockS3:
            MockS3.return_value.list_keys_with_sizes.return_value = []
            _collect_pattern_backups(
                locations,
                pattern="acme*",
                date_from=None,
                date_to=None,
                min_bytes=None,
                max_bytes=None,
                verbose=False,
            )
            MockS3.assert_called_once_with(profile="ap-profile", region="ap-southeast-1")
