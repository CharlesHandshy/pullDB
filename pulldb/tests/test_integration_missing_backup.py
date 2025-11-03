"""Integration test: missing backup scenario (S3 discovery fails).

Simulates the case where S3 backup discovery cannot find any matching
backups for the specified target, triggering BackupValidationError.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import TYPE_CHECKING, cast

import pytest
from moto import mock_aws

from pulldb.domain.errors import BackupValidationError
from pulldb.infra.s3 import S3Client, discover_latest_backup


if TYPE_CHECKING:
    from mypy_boto3_s3.service_resource import S3ServiceResource


@pytest.fixture(autouse=True)
def _isolate_aws_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure AWS_PROFILE does not interfere with moto tests.

    Removes AWS_PROFILE and PULLDB_AWS_PROFILE for duration of each test
    in this module to prevent ProfileNotFound errors when using moto mocks.
    """
    if "AWS_PROFILE" in os.environ:
        monkeypatch.delenv("AWS_PROFILE", raising=False)
    if "PULLDB_AWS_PROFILE" in os.environ:
        monkeypatch.delenv("PULLDB_AWS_PROFILE", raising=False)


@pytest.fixture
def moto_s3_empty() -> Generator[None, None, None]:
    """Provide moto S3 environment with empty bucket."""
    with mock_aws():
        import boto3

        s3_resource = cast(
            "S3ServiceResource", boto3.resource("s3", region_name="us-east-1")
        )
        s3_resource.create_bucket(Bucket="test-backup-bucket")
        yield


def test_missing_backup_discovery(moto_s3_empty: None) -> None:
    """Raise BackupValidationError when no backups exist in S3 prefix.

    Uses moto to create an empty bucket; discovery should fail with
    a specific diagnostic message indicating no tar archives found.
    """
    s3 = S3Client(region="us-east-1")

    with pytest.raises(BackupValidationError) as exc:
        discover_latest_backup(
            s3=s3,
            bucket="test-backup-bucket",
            prefix="daily/prod/",
            target="customerdoesnotexist",
        )

    # Verify error structure includes missing files detail
    detail = exc.value.detail
    assert "missing_files" in detail
    missing_files = detail.get("missing_files")
    assert isinstance(missing_files, list), "missing_files should be a list"
    # Cast to list[str] after validation to satisfy mypy type narrowing
    missing_files_list = cast(list[str], missing_files)
    assert len(missing_files_list) > 0, (
        "missing_files should contain at least one entry"
    )
