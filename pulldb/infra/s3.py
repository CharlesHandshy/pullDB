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

HCA Layer: shared
"""

from __future__ import annotations

import os
import concurrent.futures
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

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

# B3b: Serialise the ProfileNotFound fallback that temporarily mutates
# os.environ["AWS_PROFILE"].  _clients_lock already prevents concurrent
# get_client() calls, but this module-level lock ensures other threads that
# happen to read os.environ directly cannot observe the transient absence.
_aws_env_lock = threading.Lock()

# Maximum time (seconds) to wait for S3 list_keys during backup discovery.
# A slow or unresponsive S3 endpoint would otherwise block the worker indefinitely.
_S3_DISCOVERY_TIMEOUT_SECONDS = 60


logger = get_logger("pulldb.infra.s3")


@runtime_checkable
class S3ClientProtocol(Protocol):
    """Protocol for S3 operations supporting both real and mock implementations.

    Defines the interface for S3 backup discovery operations. Real implementation
    uses boto3, simulation uses MockS3Client for deterministic testing.

    This protocol enables type-safe dependency injection in WorkerExecutor
    and other components that need S3 access.
    """

    def list_keys(
        self,
        bucket: str,
        prefix: str,
        profile: str | None = None,
        max_keys: int | None = None,
    ) -> list[str]:
        """Return keys under prefix (non-recursive).

        Args:
            bucket: S3 bucket name.
            prefix: Prefix to search under.
            profile: Optional AWS profile name.
            max_keys: Maximum number of keys to return.

        Returns:
            List of object keys matching the prefix.
        """
        ...

    def head_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> HeadObjectOutputTypeDef | dict[str, Any]:
        """Return object metadata (HEAD request).

        Args:
            bucket: S3 bucket name.
            key: Object key.
            profile: Optional AWS profile name.

        Returns:
            Object metadata including ContentLength, LastModified, etc.

        Raises:
            Exception: If object does not exist or access denied.
        """
        ...

    def get_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> GetObjectOutputTypeDef | dict[str, Any]:
        """Return object with streaming body.

        Args:
            bucket: S3 bucket name.
            key: Object key.
            profile: Optional AWS profile name.

        Returns:
            Object response with Body (streaming) and metadata.

        Raises:
            Exception: If object does not exist or access denied.
        """
        ...

    def get_object_size(
        self, bucket: str, key: str, profile: str | None = None
    ) -> int | None:
        """Return object size in bytes, or None if not found.

        Uses HEAD request for efficiency.

        Args:
            bucket: S3 bucket name.
            key: Object key.
            profile: Optional AWS profile name.

        Returns:
            Size in bytes if object exists, None if not found.

        Raises:
            Exception: For S3 errors other than 404.
        """
        ...


# Old format (mydumper 0.9.x): daily_mydumper_<customer>_<ts>Z_<Day>_<host>.tar
# e.g. daily_mydumper_acme_2026-03-23T07-39-14Z_Monday_db10.tar
_FORMAT_V1 = re.compile(
    r"^daily_mydumper_(?P<target>.+?)_(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_[A-Za-z]+_(?:dbimp|db\d+)\.tar$"
)

# New format (mydumper 0.21.1+): daily_mydumper_<host>_<ts>_<Day>_<customer>.tar
# e.g. daily_mydumper_db10_2026-03-23T07-17-16_Monday_acme.tar
_FORMAT_V2 = re.compile(
    r"^daily_mydumper_(?:dbimp|db\d+)_(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})_[A-Za-z]+_(?P<target>.+?)\.tar$"
)

# Backward-compatible alias — matches old format only.
# Prefer parse_backup_filename() for new code.
BACKUP_FILENAME_REGEX = _FORMAT_V1


def parse_backup_filename(filename: str) -> tuple[str, str] | None:
    """Parse a backup tar filename and return (target, ts_str).

    Supports both naming conventions:
    - Old (mydumper 0.9.x):   daily_mydumper_<customer>_<ts>Z_<Day>_<host>.tar
    - New (mydumper 0.21.1+): daily_mydumper_<host>_<ts>_<Day>_<customer>.tar

    Args:
        filename: Basename of the tar file (not a full path).

    Returns:
        ``(target, ts_str)`` where *target* is the customer/database name and
        *ts_str* is the ISO-8601 timestamp **without** a trailing ``Z``, e.g.
        ``"2026-03-23T07-17-16"``.  Returns ``None`` for unrecognised names.
    """
    m = _FORMAT_V1.match(filename)
    if m:
        # V1 captures the Z inside the group — strip it for a uniform return value
        return m.group("target"), m.group("ts").rstrip("Z")
    m = _FORMAT_V2.match(filename)
    if m:
        return m.group("target"), m.group("ts")
    return None


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
    sha256_key: str | None = None  # S3 key of companion .sha256 file, if present

    @property
    def filename(self) -> str:
        """Return basename of object key for local filesystem naming."""
        return self.key.rsplit("/", 1)[-1]


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
        self._clients: dict[str | None, Any] = {}
        self._clients_lock = threading.Lock()
        # Initialize default client
        self._clients[profile] = self._create_client(profile, region)

    def _create_client(self, profile: str | None, region: str | None) -> Any:
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
            # _aws_env_lock serialises this mutation against any concurrent
            # thread that may read os.environ directly.
            with _aws_env_lock:
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
            logger.debug("Failed to create S3 client, falling back to default", exc_info=True)
            return boto3.client(
                "s3",
                region_name=(region or "us-east-1"),
            )

    def get_client(self, profile: str | None = None) -> Any:
        """Get or create a boto3 client for the specified profile."""
        target_profile = profile if profile is not None else self._default_profile
        with self._clients_lock:
            if target_profile not in self._clients:
                self._clients[target_profile] = self._create_client(
                    target_profile, self._default_region
                )
            return self._clients[target_profile]

    def list_keys(
        self,
        bucket: str,
        prefix: str,
        profile: str | None = None,
        max_keys: int | None = None,
    ) -> list[str]:  # pragma: no cover - simple wrapper
        """Return keys under prefix (non recursive).

        Args:
            bucket: S3 bucket name
            prefix: Prefix to search under
            profile: AWS profile to use
            max_keys: Maximum number of keys to return (None = all)

        Returns:
            List of object keys
        """
        client = self.get_client(profile)
        keys: list[str] = []
        continuation: str | None = None
        page_count = 0
        while True:
            page_count += 1
            if page_count % 10 == 0:
                logger.info("Listing keys page %d for %s/%s", page_count, bucket, prefix)
            # Use max_keys for page size if specified and smaller than default
            page_size = min(max_keys, 1000) if max_keys else 1000
            params: dict[str, Any] = {
                "Bucket": bucket,
                "Prefix": prefix,
                "MaxKeys": page_size,
            }
            if continuation:
                params["ContinuationToken"] = continuation
            resp: ListObjectsV2OutputTypeDef = client.list_objects_v2(**params)
            for item in resp.get("Contents") or []:
                k = item.get("Key")
                if isinstance(k, str):
                    keys.append(k)
                    if max_keys and len(keys) >= max_keys:
                        return keys
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

    def get_object_size(
        self, bucket: str, key: str, profile: str | None = None
    ) -> int | None:
        """Return object size in bytes, or None if object doesn't exist.

        Uses HEAD request to check object existence and get size without
        downloading the object. This is efficient for verifying user-selected
        backups exist before job execution.

        Args:
            bucket: S3 bucket name.
            key: Object key.
            profile: AWS profile to use.

        Returns:
            Size in bytes if object exists, None otherwise.

        Raises:
            Exception: For S3 errors other than 404 (not found).
        """
        try:
            resp = self.head_object(bucket, key, profile=profile)
            return resp.get("ContentLength")
        except Exception as exc:
            # Check if it's a 404 Not Found
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return None
            raise

    def get_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> GetObjectOutputTypeDef:  # pragma: no cover - thin
        """Return object (streaming body)."""
        client = self.get_client(profile)
        resp: GetObjectOutputTypeDef = client.get_object(Bucket=bucket, Key=key)
        return resp

    def list_prefixes(
        self,
        bucket: str,
        prefix: str,
        profile: str | None = None,
        max_results: int | None = None,
    ) -> list[str]:  # pragma: no cover - S3 wrapper
        """Return folder names under prefix using S3 Delimiter.

        Uses CommonPrefixes from list_objects_v2 with Delimiter='/' for
        efficient folder discovery without listing all objects.

        Args:
            bucket: S3 bucket name
            prefix: Prefix to search under (should end with '/')
            profile: AWS profile to use
            max_results: Maximum number of prefixes to return (None = all)

        Returns:
            List of folder names (without trailing '/')
        """
        client = self.get_client(profile)
        prefixes: list[str] = []
        continuation: str | None = None

        while True:
            params: dict[str, Any] = {
                "Bucket": bucket,
                "Prefix": prefix,
                "Delimiter": "/",
                "MaxKeys": 1000,
            }
            if continuation:
                params["ContinuationToken"] = continuation

            resp: ListObjectsV2OutputTypeDef = client.list_objects_v2(**params)

            for item in resp.get("CommonPrefixes") or []:
                p = item.get("Prefix", "")
                if p:
                    # Strip the base prefix and trailing '/'
                    name = p[len(prefix) :].rstrip("/")
                    if name:
                        prefixes.append(name)
                        if max_results and len(prefixes) >= max_results:
                            return prefixes

            if resp.get("IsTruncated"):
                continuation = resp.get("NextContinuationToken")
            else:
                break

        return prefixes

    def list_keys_with_sizes(
        self,
        bucket: str,
        prefix: str,
        profile: str | None = None,
        max_results: int | None = None,
    ) -> list[tuple[str, int]]:  # pragma: no cover - S3 wrapper
        """Return keys with their sizes under prefix.

        Extracts Size from list_objects_v2 Contents response, avoiding
        separate head_object calls for each key.

        Args:
            bucket: S3 bucket name
            prefix: Prefix to search under
            profile: AWS profile to use
            max_results: Maximum number of results to return (None = all)

        Returns:
            List of (key, size_bytes) tuples
        """
        logger.debug(
            "list_keys_with_sizes starting",
            extra={"bucket": bucket, "prefix": prefix, "profile": profile},
        )
        client = self.get_client(profile)
        results: list[tuple[str, int]] = []
        continuation: str | None = None
        page_count = 0

        while True:
            page_count += 1
            params: dict[str, Any] = {
                "Bucket": bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation:
                params["ContinuationToken"] = continuation

            resp: ListObjectsV2OutputTypeDef = client.list_objects_v2(**params)
            logger.debug(
                f"list_keys_with_sizes page {page_count}",
                extra={
                    "bucket": bucket,
                    "prefix": prefix,
                    "items_in_page": len(resp.get("Contents") or []),
                    "is_truncated": resp.get("IsTruncated", False),
                },
            )

            for item in resp.get("Contents") or []:
                key = item.get("Key")
                size = item.get("Size", 0)
                if isinstance(key, str):
                    results.append((key, size))
                    if max_results and len(results) >= max_results:
                        return results

            if resp.get("IsTruncated"):
                continuation = resp.get("NextContinuationToken")
            else:
                break

        return results


def discover_latest_backup(
    s3: S3ClientProtocol,
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

    # format_tag will be determined post-extraction by _detect_backup_version()
    # Setting to None here - executor.py will detect after extraction
    format_tag = None

    # Old format: {prefix}{target}/daily_mydumper_{target}_<ts>Z_<Day>_<host>.tar
    # New format: {prefix}{target}/daily_mydumper_<host>_<ts>_<Day>_{target}.tar
    # Both live under the same per-target prefix directory.
    search_prefix = f"{prefix}{target}/"

    logger.info("Starting list_keys for bucket=%s prefix=%s", bucket, search_prefix)
    # M10: Wrap list_keys in a timeout so a slow/unresponsive S3 endpoint does
    # not block the worker indefinitely.  _S3_DISCOVERY_TIMEOUT_SECONDS = 60.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
        _future = _pool.submit(s3.list_keys, bucket, search_prefix, profile=profile)
        try:
            keys = _future.result(timeout=_S3_DISCOVERY_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            raise BackupValidationError(
                job_id="discovery",
                backup_key=f"s3://{bucket}/{search_prefix}",
                missing_files=[
                    f"(S3 list timed out after {_S3_DISCOVERY_TIMEOUT_SECONDS}s — "
                    "check S3 connectivity and bucket permissions)"
                ],
            )
    logger.info(
        "Found %d keys for target '%s' in %s/%s",
        len(keys), target, bucket, search_prefix,
    )

    if not keys:
        raise BackupValidationError(
            job_id="discovery",
            backup_key=f"s3://{bucket}/{search_prefix}",
            missing_files=["tar archive"],
        )

    candidates: list[tuple[datetime, int, str]] = []
    for key in keys:
        filename = key.rsplit("/", 1)[-1]
        parsed = parse_backup_filename(filename)
        if not parsed:
            logger.warning("Regex mismatch: %s", filename)
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
        file_target, ts_str = parsed
        if file_target != target:
            continue
        # Format priority: 1 = new (0.21.1+, host-first), 0 = old (0.9.x, customer-first)
        fmt_priority = 1 if _FORMAT_V2.match(filename) else 0
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%S")
        except ValueError as e:
            # Malformed timestamp in an otherwise matching filename should
            # surface a specific validation error referencing timestamp.
            raise BackupValidationError(
                job_id="discovery",
                backup_key=key,
                missing_files=["valid timestamp"],
            ) from e
        candidates.append((ts, fmt_priority, key))

    if not candidates:
        raise BackupValidationError(
            job_id="discovery",
            backup_key=f"s3://{bucket}/{prefix}",
            missing_files=[f"daily_mydumper_{target}_*.tar"],
        )

    # Select best backup: prefer new format (V2) over old on the same calendar
    # date; fall back to latest timestamp when dates differ.
    # Sort key: (date DESC, format_priority DESC, timestamp DESC)
    candidates.sort(key=lambda x: (x[0].date(), x[1], x[0]), reverse=True)
    newest_ts, _fmt, newest_key = candidates[0]

    # Retrieve size for disk planning
    logger.info("Head object for %s", newest_key)
    head = s3.head_object(bucket, newest_key, profile=profile)
    size_bytes = int(head.get("ContentLength", 0))

    # M5: Check for companion SHA-256 checksum file alongside the .tar archive.
    # Convention: replace trailing .tar with .sha256 (e.g. backup.tar → backup.sha256).
    # If the file exists, store its key in BackupSpec so downloader can verify.
    # If absent, log a warning — checksums are encouraged but not always present.
    sha256_key: str | None = None
    if newest_key.endswith(".tar"):
        candidate_sha256_key = newest_key[:-4] + ".sha256"
        try:
            sha256_head = s3.head_object(bucket, candidate_sha256_key, profile=profile)
        except Exception:
            sha256_head = None
        if sha256_head is not None:
            sha256_key = candidate_sha256_key
            logger.info(
                "SHA-256 checksum file found",
                extra={"phase": "s3_discovery", "sha256_key": sha256_key},
            )
        else:
            logger.warning(
                "No SHA-256 checksum file found alongside backup archive; "
                "integrity will not be verified after download",
                extra={
                    "phase": "s3_discovery",
                    "backup_key": newest_key,
                    "expected_sha256_key": candidate_sha256_key,
                },
            )

    spec = BackupSpec(
        bucket=bucket,
        key=newest_key,
        target=target,
        timestamp=newest_ts,
        size_bytes=size_bytes,
        format_tag=format_tag,
        profile=profile,
        sha256_key=sha256_key,
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
