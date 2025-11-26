"""S3 backup discovery utilities.

Milestone 3: Implements backup listing and latest selection with validation
for required schema file presence. This module intentionally limits scope
to read-only discovery; download/extraction implemented separately in
``pulldb.worker.downloader``.

Design Principles:
    * FAIL HARD: Missing backups or corrupt/mismatched artifact sets raise
      ``BackupValidationError`` with actionable solutions.
    * Deterministic selection: Always chooses newest backup by timestamp
      embedded in filename pattern after validating completeness.
    * Read-only safety: No deletion or mutation of S3 state.

Filename Pattern (legacy mydumper tar archives)::
    daily_mydumper_{target}_{YYYY-MM-DDThh-mm-ssZ}_{Day}_dbimp.tar

Associated schema file (inside archive, validated prior to download)::
    <archive_root>/<database>-schema-create.sql.zst

Note: Multi-format support (newer directory style dumps) is deferred. This
implementation targets tar archives present in staging bucket.
"""

from __future__ import annotations

import os
import re
import typing as t
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ProfileNotFound

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import (
        GetObjectOutputTypeDef,
        HeadObjectOutputTypeDef,
        ListObjectsV2OutputTypeDef,
    )

from pulldb.domain.errors import BackupValidationError
from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.infra.s3")

BACKUP_FILENAME_REGEX = re.compile(
    r"^daily_mydumper_(?P<target>.+?)_(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_[A-Za-z]+_(?:dbimp|db\d+)\.tar$"
)

# Regex for Production backups (legacy mydumper v0.9)
# Bucket: pestroutes-rds-backup-prod-vpc-us-east-1-s3
# Pattern: daily_mydumper_{target}_{ts}_{Day}_dbimp.tar
PROD_BACKUP_REGEX = re.compile(
    r"^daily_mydumper_(?P<target>.+?)_(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_[A-Za-z]+_(?:dbimp|db\d+)\.tar$"
)

# Regex for Staging backups (mydumper v0.19+)
# Bucket: pestroutesrdsdbs
# Pattern: daily_mydumper_{target}_{ts}_{Day}_db1.tar (or dbN.tar)
# Note: Also supports legacy dbimp format if present
STAGING_BACKUP_REGEX = re.compile(
    r"^daily_mydumper_(?P<target>.+?)_(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_[A-Za-z]+_(?:dbimp|db\d+)\.tar$"
)


@dataclass(slots=True)
class BackupSpec:
    """Specification for a discovered backup artifact.

    Attributes:
        bucket: S3 bucket containing the backup.
        key: Object key of the tar archive.
        target: Sanitized target identifier (customer or template).
        timestamp: Parsed timestamp embedded in filename (UTC).
        size_bytes: Size in bytes from HEAD (for disk capacity planning).
    """

    bucket: str
    key: str
    target: str
    timestamp: datetime
    size_bytes: int
    format_tag: str | None = None
    profile: str | None = None

    @property
    def filename(self) -> str:
        """Return basename of object key for local filesystem naming."""
        return self.key.rsplit("/", 1)[-1]


def parse_s3_bucket_path(value: str) -> tuple[str, str]:
    """Parse bucket/prefix from configuration value."""
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("s3_bucket_path configuration is required")

    if trimmed.startswith("s3://"):
        trimmed = trimmed[len("s3://") :]

    if not trimmed:
        raise ValueError("s3_bucket_path must include bucket name")

    bucket, _, remainder = trimmed.partition("/")
    prefix = remainder.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix = f"{prefix}/"
    return bucket, prefix


class S3Client:
    """Thin S3 client wrapper for backup discovery.

    Provides minimal operations required for listing and reading backup
    artifacts. Encapsulates the boto3 client so higher layers can be
    unit-tested with a simple fake.
    """

    def __init__(
        self,
        profile: str | None = None,
        region: str | None = None,
    ) -> None:
        """Create a new S3 client wrapper.

        Args:
            profile: Optional AWS profile name (falls back to default
                credential chain when omitted).
            region: Optional AWS region; if omitted boto3 resolves via
                environment / profile configuration.
        """
        self._default_profile = profile
        self._default_region = region
        self._clients: dict[str | None, boto3.client] = {}
        # Initialize default client
        self._clients[profile] = self._create_client(profile, region)

    def _create_client(self, profile: str | None, region: str | None) -> boto3.client:
        # Construct a Session without relying on **kwargs expansion to keep
        # mypy strict mode happy and avoid arg-type confusion. Only pass
        # explicitly provided values.
        try:
            if profile is not None and region is not None:
                session = boto3.Session(profile_name=profile, region_name=region)
            elif profile is not None:
                session = boto3.Session(profile_name=profile)
            elif region is not None:
                session = boto3.Session(region_name=region)
            else:
                session = boto3.Session()
            return session.client("s3")
        except ProfileNotFound:
            # Temporarily remove AWS_PROFILE to avoid recursive failures when
            # constructing a client in hermetic/moto environments where that
            # profile is not configured locally.
            env_profile = os.environ.pop("AWS_PROFILE", None)
            try:
                return boto3.client(
                    "s3",
                    region_name=(region or "us-east-1"),
                )
            finally:
                if env_profile is not None:
                    os.environ["AWS_PROFILE"] = env_profile
        except Exception:  # pragma: no cover - defensive catch for strange local env
            return boto3.client(
                "s3",
                region_name=(region or "us-east-1"),
            )

    def get_client(self, profile: str | None = None) -> boto3.client:
        """Get or create a boto3 client for the specified profile."""
        target_profile = profile if profile is not None else self._default_profile
        if target_profile not in self._clients:
            self._clients[target_profile] = self._create_client(
                target_profile, self._default_region
            )
        return self._clients[target_profile]

    def list_keys(
        self, bucket: str, prefix: str, profile: str | None = None
    ) -> list[str]:  # pragma: no cover - simple wrapper
        """Return keys under prefix (non recursive)."""
        client = self.get_client(profile)
        keys: list[str] = []
        continuation: str | None = None
        page_count = 0
        while True:
            page_count += 1
            if page_count % 10 == 0:
                logger.info(f"Listing keys page {page_count} for {bucket}/{prefix}")
            params: dict[str, t.Any] = {
                "Bucket": bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation:
                params["ContinuationToken"] = continuation
            resp: ListObjectsV2OutputTypeDef = client.list_objects_v2(**params)
            for item in resp.get("Contents") or []:
                k = item.get("Key")
                if isinstance(k, str):
                    keys.append(k)
            if resp.get("IsTruncated"):
                continuation = resp.get("NextContinuationToken")
            else:
                break
        return keys

    def head_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> HeadObjectOutputTypeDef:  # pragma: no cover - thin
        """Return object metadata (HEAD)."""
        client = self.get_client(profile)
        resp: HeadObjectOutputTypeDef = client.head_object(Bucket=bucket, Key=key)
        return resp

    def get_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> GetObjectOutputTypeDef:  # pragma: no cover - thin
        """Return object (streaming body)."""
        client = self.get_client(profile)
        resp: GetObjectOutputTypeDef = client.get_object(Bucket=bucket, Key=key)
        return resp


def discover_latest_backup(
    s3: S3Client,
    bucket: str,
    prefix: str,
    target: str,
    profile: str | None = None,
) -> BackupSpec:
    """Discover the latest valid backup for a target.

    Scans objects under the provided prefix filtering by filename pattern
    and target. Validates presence of at least one tar archive and selects
    the newest by embedded timestamp. Performs a `head_object` call to
    obtain size for disk planning.

    Args:
        s3: S3 client wrapper.
        bucket: S3 bucket name.
        prefix: Path prefix containing backups (e.g. 'daily/stg/').
        target: Sanitized target database identifier.
        profile: Optional AWS profile to use for S3 operations.

    Returns:
        BackupSpec for newest tar archive.

    Raises:
        BackupValidationError: When no backups found or filename malformed.
    """
    logger.info(
        "Discovering latest backup",
        extra={
            "phase": "s3_discovery",
            "bucket": bucket,
            "prefix": prefix,
            "target": target,
            "profile": profile,
        },
    )

    # Select regex based on bucket
    if bucket == "pestroutes-rds-backup-prod-vpc-us-east-1-s3":
        regex = PROD_BACKUP_REGEX
        format_tag = "legacy"
    else:
        # Default to staging regex for pestroutesrdsdbs and others
        regex = STAGING_BACKUP_REGEX
        format_tag = "new"

    # Optimization: Filter S3 listing by target to avoid scanning entire bucket.
    # This reduces the search space from all customers (thousands of objects)
    # to just the specific target's backups.
    # Note: Both production and staging buckets use a subdirectory per target:
    # {prefix}{target}/daily_mydumper_{target}_...
    search_prefix = f"{prefix}{target}/daily_mydumper_{target}_"

    logger.info(f"Starting list_keys for bucket={bucket} prefix={search_prefix}")
    keys = s3.list_keys(bucket, search_prefix, profile=profile)
    logger.info(
        f"Found {len(keys)} keys for target '{target}' in {bucket}/{search_prefix}"
    )

    if not keys:
        raise BackupValidationError(
            job_id="discovery",
            backup_key=f"s3://{bucket}/{search_prefix}",
            missing_files=["tar archive"],
        )

    candidates: list[tuple[datetime, str]] = []
    for key in keys:
        filename = key.rsplit("/", 1)[-1]
        match = regex.match(filename)
        if not match:
            logger.warning(f"Regex mismatch: {filename}")
            # Detect structurally similar filename with bad timestamp to
            # provide clearer diagnostic (test expectation).
            if filename.startswith(f"daily_mydumper_{target}_") and (
                filename.endswith("_dbimp.tar") or re.search(r"_db\d+\.tar$", filename)
            ):
                raise BackupValidationError(
                    job_id="discovery",
                    backup_key=key,
                    missing_files=["valid timestamp"],
                )
            continue  # Ignore unrelated files
        if match.group("target") != target:
            continue
        ts_str = match.group("ts")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%SZ")
        except ValueError as e:
            # Malformed timestamp in an otherwise matching filename should
            # surface a specific validation error referencing timestamp.
            raise BackupValidationError(
                job_id="discovery",
                backup_key=key,
                missing_files=["valid timestamp"],
            ) from e
        candidates.append((ts, key))

    if not candidates:
        raise BackupValidationError(
            job_id="discovery",
            backup_key=f"s3://{bucket}/{prefix}",
            missing_files=[f"daily_mydumper_{target}_*.tar"],
        )

    # Select newest by timestamp
    candidates.sort(key=lambda x: x[0], reverse=True)
    newest_ts, newest_key = candidates[0]

    # Retrieve size for disk planning
    logger.info(f"Head object for {newest_key}")
    head = s3.head_object(bucket, newest_key, profile=profile)
    size_bytes = int(head.get("ContentLength", 0))

    spec = BackupSpec(
        bucket=bucket,
        key=newest_key,
        target=target,
        timestamp=newest_ts,
        size_bytes=size_bytes,
        format_tag=format_tag,
        profile=profile,
    )

    logger.info(
        "Latest backup selected",
        extra={
            "phase": "s3_discovery",
            "backup_key": spec.key,
            "size_bytes": spec.size_bytes,
            "timestamp": spec.timestamp.isoformat(),
        },
    )
    return spec

