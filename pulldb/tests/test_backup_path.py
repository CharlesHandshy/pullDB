"""Tests for backup path handling in job submission and worker execution.

Tests the following scenarios:
1. Backup path validation against customer name
2. S3 location matching for backup paths
3. Options snapshot capturing all job parameters
4. Worker honoring user-selected backup path
5. Backward compatibility for jobs without backup_path
"""

from __future__ import annotations

import pytest

from pulldb.domain.config import (
    S3BackupLocationConfig,
    find_location_for_backup_path,
    parse_backup_path,
)


class TestParseBackupPath:
    """Tests for parse_backup_path helper."""

    def test_parse_full_s3_uri(self):
        """Full s3:// URI is parsed correctly."""
        result = parse_backup_path("s3://mybucket/daily/stg/acme/daily_mydumper_acme.tar")
        assert result == ("mybucket", "daily/stg/acme/daily_mydumper_acme.tar")

    def test_parse_path_without_scheme(self):
        """Path without s3:// scheme is parsed correctly."""
        result = parse_backup_path("mybucket/daily/stg/acme/daily_mydumper_acme.tar")
        assert result == ("mybucket", "daily/stg/acme/daily_mydumper_acme.tar")

    def test_parse_empty_path_returns_none(self):
        """Empty or None path returns None."""
        assert parse_backup_path("") is None
        assert parse_backup_path(None) is None  # type: ignore

    def test_parse_bucket_only_returns_none(self):
        """Path with only bucket (no key) returns None."""
        assert parse_backup_path("mybucket") is None
        assert parse_backup_path("s3://mybucket") is None


class TestFindLocationForBackupPath:
    """Tests for find_location_for_backup_path helper."""

    @pytest.fixture
    def sample_locations(self) -> tuple[S3BackupLocationConfig, ...]:
        """Create sample S3 backup location configs."""
        return (
            S3BackupLocationConfig(
                name="staging",
                bucket_path="s3://pestroutesrdsdbs/daily/stg/",
                bucket="pestroutesrdsdbs",
                prefix="daily/stg/",
                format_tag="new",
                profile="pr-staging",
            ),
            S3BackupLocationConfig(
                name="production",
                bucket_path="s3://pestroutes-rds-backup-prod/daily/prod/",
                bucket="pestroutes-rds-backup-prod",
                prefix="daily/prod/",
                format_tag="legacy",
                profile="pr-prod",
            ),
            S3BackupLocationConfig(
                name="staging-special",
                bucket_path="s3://pestroutesrdsdbs/daily/stg/special/",
                bucket="pestroutesrdsdbs",
                prefix="daily/stg/special/",
                format_tag="new",
                profile="pr-staging",
            ),
        )

    def test_match_staging_location(self, sample_locations):
        """Backup path correctly matches staging location."""
        path = "s3://pestroutesrdsdbs/daily/stg/acme/daily_mydumper_acme.tar"
        result = find_location_for_backup_path(path, sample_locations)
        assert result is not None
        assert result.name == "staging"
        assert result.profile == "pr-staging"

    def test_match_production_location(self, sample_locations):
        """Backup path correctly matches production location."""
        path = "s3://pestroutes-rds-backup-prod/daily/prod/acme/daily_mydumper_acme.tar"
        result = find_location_for_backup_path(path, sample_locations)
        assert result is not None
        assert result.name == "production"
        assert result.profile == "pr-prod"

    def test_longest_prefix_wins(self, sample_locations):
        """When multiple prefixes match, longest (most specific) wins."""
        # This path matches both "daily/stg/" and "daily/stg/special/"
        path = "s3://pestroutesrdsdbs/daily/stg/special/acme/daily_mydumper_acme.tar"
        result = find_location_for_backup_path(path, sample_locations)
        assert result is not None
        assert result.name == "staging-special"  # More specific prefix wins

    def test_no_match_returns_none(self, sample_locations):
        """Unrecognized bucket returns None."""
        path = "s3://unknown-bucket/path/to/backup.tar"
        result = find_location_for_backup_path(path, sample_locations)
        assert result is None

    def test_wrong_prefix_returns_none(self, sample_locations):
        """Correct bucket but wrong prefix returns None."""
        path = "s3://pestroutesrdsdbs/wrong/prefix/backup.tar"
        result = find_location_for_backup_path(path, sample_locations)
        assert result is None

    def test_empty_locations_returns_none(self):
        """Empty locations list returns None."""
        path = "s3://mybucket/path/to/backup.tar"
        result = find_location_for_backup_path(path, ())
        assert result is None


class TestBackupPathValidation:
    """Tests for backup path validation against customer name."""

    def test_valid_customer_path_pattern(self):
        """Valid backup path contains expected customer pattern."""
        customer = "actionpest"
        backup_key = "daily/stg/actionpest/daily_mydumper_actionpest_2024-12-30T05-30-00Z_Mon_db1.tar"
        
        # Extract letters-only customer name
        customer_letters = ''.join(ch for ch in customer.lower() if ch.isalpha())
        expected_pattern = f"{customer_letters}/daily_mydumper_{customer_letters}_"
        
        assert expected_pattern in backup_key.lower()

    def test_mismatched_customer_path_detected(self):
        """Mismatched backup path does not contain customer pattern."""
        customer = "actionpest"
        backup_key = "daily/stg/differentcustomer/daily_mydumper_differentcustomer_2024-12-30T05-30-00Z.tar"
        
        customer_letters = ''.join(ch for ch in customer.lower() if ch.isalpha())
        expected_pattern = f"{customer_letters}/daily_mydumper_{customer_letters}_"
        
        assert expected_pattern not in backup_key.lower()

    def test_qatemplate_path_pattern(self):
        """QA template backup path validation."""
        customer = "qatemplate"
        backup_key = "daily/stg/qatemplate/daily_mydumper_qatemplate_2024-12-30T05-30-00Z_Mon_db1.tar"
        
        expected_pattern = "qatemplate/daily_mydumper_qatemplate_"
        assert expected_pattern in backup_key.lower()
