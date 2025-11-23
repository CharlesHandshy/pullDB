"""Tests for S3 backup discovery."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import suppress

import pytest
from moto import mock_aws

from pulldb.domain.errors import BackupValidationError
from pulldb.infra.s3 import BACKUP_FILENAME_REGEX, S3Client, discover_latest_backup


@pytest.fixture
def s3_client() -> S3Client:
    return S3Client(region="us-east-1")


@pytest.fixture(autouse=True)
def _isolate_aws_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure AWS_PROFILE does not interfere with moto tests.

    Removes AWS_PROFILE for duration of each test in this module and restores
    after. This keeps boto3 from attempting to resolve nonexistent local
    profiles when running the full suite.
    """
    import os

    if "AWS_PROFILE" in os.environ:
        monkeypatch.delenv("AWS_PROFILE", raising=False)
    # Restore happens automatically via monkeypatch context


@pytest.fixture
def moto_s3() -> Generator[None, None, None]:
    """Provide mocked AWS context (moto)."""
    with mock_aws():  # moto provides generator fixture semantics
        yield


def _put_object(
    s3_client: S3Client, bucket: str, key: str, body: bytes = b"data"
) -> None:
    """Create bucket (idempotent) and put object.

    Moto + local dev may have an AWS_PROFILE pointing at a non-existent
    profile, causing ProfileNotFound during raw client construction. We
    temporarily remove AWS_PROFILE for this isolated helper to ensure
    hermetic behavior without altering global test environment.
    """
    # Directly use wrapped client to avoid fresh profile/session resolution.
    raw = s3_client.get_client()
    with suppress(Exception):
        raw.create_bucket(Bucket=bucket)
    raw.put_object(Bucket=bucket, Key=key, Body=body)


def test_discovery_selects_newest_backup(moto_s3: None, s3_client: S3Client) -> None:
    bucket = "test-bucket"
    prefix = "daily/stg/"
    target = "cust123"

    # Old backup
    _put_object(
        s3_client,
        bucket,
        f"{prefix}{target}/daily_mydumper_{target}_2024-01-01T00-00-00Z_Mon_dbimp.tar",
    )
    # New backup
    _put_object(
        s3_client,
        bucket,
        f"{prefix}{target}/daily_mydumper_{target}_2024-01-02T12-30-45Z_Tue_dbimp.tar",
    )

    spec = discover_latest_backup(s3_client, bucket, prefix, target)
    assert spec.key.endswith("2024-01-02T12-30-45Z_Tue_dbimp.tar")


def test_discovery_no_objects_raises(moto_s3: None, s3_client: S3Client) -> None:
    bucket = "empty-bucket"
    prefix = "daily/stg/"
    target = "cust123"
    # Use wrapped client
    raw = s3_client.get_client()
    raw.create_bucket(Bucket=bucket)

    with pytest.raises(BackupValidationError) as exc:
        discover_latest_backup(s3_client, bucket, prefix, target)
    assert "tar archive" in str(exc.value)


def test_discovery_malformed_timestamp(moto_s3: None, s3_client: S3Client) -> None:
    bucket = "bad-bucket"
    prefix = "daily/stg/"
    target = "cust123"
    _put_object(
        s3_client,
        bucket,
        f"{prefix}{target}/daily_mydumper_{target}_BADTIMESTAMP_Mon_dbimp.tar",
    )

    with pytest.raises(BackupValidationError) as exc:
        discover_latest_backup(s3_client, bucket, prefix, target)
    assert "valid timestamp" in str(exc.value)


def test_discovery_no_matching_target(moto_s3: None, s3_client: S3Client) -> None:
    bucket = "bucket"
    prefix = "daily/stg/"
    target = "cust123"
    # Different target present
    _put_object(
        s3_client,
        bucket,
        f"{prefix}other/daily_mydumper_other_2024-01-01T00-00-00Z_Mon_dbimp.tar",
    )

    with pytest.raises(BackupValidationError) as exc:
        discover_latest_backup(s3_client, bucket, prefix, target)
    assert f"s3://{bucket}/{prefix}{target}/daily_mydumper_{target}_" in str(exc.value)


def test_filename_regex_valid() -> None:
    """Regex matches valid filename and extracts target."""
    filename = "daily_mydumper_acme_2024-10-15T06-22-10Z_Tue_dbimp.tar"
    match = BACKUP_FILENAME_REGEX.match(filename)
    assert match
    assert match.group("target") == "acme"


# End of file
