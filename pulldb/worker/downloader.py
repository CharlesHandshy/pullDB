"""Backup downloader with disk capacity guard.

Milestone 3: Streams selected S3 tar archive to a local staging directory
and validates sufficient disk space prior to download (size * 1.8 rule).

Responsibilities:
    * Verify available disk space on target volume (FAIL HARD early)
    * Stream S3 object to file (no full in-memory buffering)
    * Provide progress logging (every N MB) - placeholder basic logging
    * Return path to downloaded tar archive for extraction phase (future)

Extraction (mydumper tar unpack) will be implemented in a later milestone.

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from collections.abc import Callable
from typing import Any

from pulldb.domain.errors import DiskCapacityError, DownloadError
from pulldb.infra.logging import get_logger
from pulldb.infra.s3 import BackupSpec, S3ClientProtocol


logger = get_logger("pulldb.worker.downloader")

BUFFER_SIZE = 8 * 1024 * 1024  # 8MB streaming chunks
PROGRESS_INTERVAL_MB = 64  # Log every 64MB downloaded
CANCEL_CHECK_INTERVAL_MB = 128  # Check for cancellation every 128MB

# S3 error codes that are safe to retry (throttling / transient service errors).
# Permanent errors (NoSuchKey, AccessDenied, InvalidBucketName) are NOT listed
# here and will propagate immediately without retrying.
_RETRYABLE_S3_CODES = frozenset({
    "SlowDown",           # 503 throttling
    "RequestTimeout",     # transient timeout
    "ServiceUnavailable", # 503 temporary unavailability
    "InternalError",      # S3 internal error
    "RequestTimeTooSkewed",  # clock skew; usually resolves on retry
})
_S3_RETRY_DELAYS = (1.0, 2.0, 4.0)  # seconds between attempts (3 total attempts)


def _is_retryable_s3_error(exc: Exception) -> bool:
    """Return True if *exc* is a transient S3 error worth retrying."""
    code = (
        getattr(getattr(exc, "response", None), "get", lambda *_: {})("Error", {}).get("Code")
        or getattr(exc, "error_code", None)
    )
    if code is None:
        # Fallback: try dict-style access (boto3 ClientError stores response as dict)
        try:
            code = exc.response["Error"]["Code"]  # type: ignore[attr-defined]
        except (AttributeError, KeyError, TypeError):
            return False
    return code in _RETRYABLE_S3_CODES


def _get_object_with_retry(
    s3: S3ClientProtocol,
    bucket: str,
    key: str,
    profile: str | None,
    job_id: str,
) -> Any:
    """Call s3.get_object with exponential-backoff retry on transient errors.

    Makes up to ``len(_S3_RETRY_DELAYS) + 1`` attempts.  Retries only when
    ``_is_retryable_s3_error`` returns True; permanent errors (NoSuchKey,
    AccessDenied) propagate immediately.

    Args:
        s3: S3 client protocol instance.
        bucket: S3 bucket name.
        key: S3 object key.
        profile: AWS profile name (or None for default credentials).
        job_id: Job identifier used in retry log messages.

    Returns:
        S3 GetObject response dict.

    Raises:
        DownloadError: After all retry attempts are exhausted, or immediately
            for non-retryable errors.
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((*_S3_RETRY_DELAYS, None), start=1):
        try:
            return s3.get_object(bucket, key, profile=profile)
        except Exception as exc:
            error_code = "Unknown"
            try:
                error_code = exc.response["Error"]["Code"]  # type: ignore[attr-defined]
            except (AttributeError, KeyError, TypeError):
                pass

            if not _is_retryable_s3_error(exc) or delay is None:
                # Non-retryable, or final attempt — raise immediately
                raise DownloadError(
                    job_id=job_id,
                    backup_key=key,
                    error_code=error_code,
                    message=str(exc),
                ) from exc

            logger.warning(
                "S3 get_object transient error, will retry",
                extra={
                    "job_id": job_id,
                    "attempt": attempt,
                    "max_attempts": len(_S3_RETRY_DELAYS) + 1,
                    "error_code": error_code,
                    "retry_in_seconds": delay,
                },
            )
            last_exc = exc
            time.sleep(delay)

    # Should be unreachable, but satisfy type checker
    raise DownloadError(  # pragma: no cover
        job_id=job_id,
        backup_key=key,
        error_code="Unknown",
        message=str(last_exc),
    )


def _verify_sha256(local_path: str, expected_hex: str, job_id: str) -> None:
    """Compute SHA-256 of *local_path* and raise ``DownloadError`` on mismatch.

    Args:
        local_path: Path to the downloaded file.
        expected_hex: Expected hex digest from the companion .sha256 file.
        job_id: Job identifier for error context.

    Raises:
        DownloadError: When the computed digest does not match *expected_hex*.
    """
    hasher = hashlib.sha256()
    with open(local_path, "rb") as fh:
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            hasher.update(block)
    actual = hasher.hexdigest()
    if actual != expected_hex.strip().lower():
        raise DownloadError(
            job_id=job_id,
            backup_key=local_path,
            error_code="ChecksumMismatch",
            message=(
                f"SHA-256 mismatch for {os.path.basename(local_path)}: "
                f"expected {expected_hex.strip()!r}, got {actual!r}. "
                "The downloaded archive may be corrupt or tampered with."
            ),
        )
    logger.info(
        "SHA-256 verification passed",
        extra={"job_id": job_id, "sha256": actual, "path": local_path},
    )


def ensure_disk_capacity(job_id: str, required_bytes: int, path: str) -> None:
    """Ensure volume containing path has required free space.

    Applies size * 1.8 rule (caller passes pre-multiplied required_bytes).

    Args:
        job_id: Job identifier.
        required_bytes: Total bytes required (already multiplied).
        path: Target file path (used to derive volume path).

    Raises:
        DiskCapacityError: When available space < required_bytes.
    """
    volume = os.path.dirname(os.path.abspath(path)) or "/"
    usage = shutil.disk_usage(volume)
    available = usage.free
    if available < required_bytes:
        required_gb = required_bytes / (1024**3)
        available_gb = available / (1024**3)
        raise DiskCapacityError(
            job_id=job_id,
            required_gb=required_gb,
            available_gb=available_gb,
            volume=volume,
        )
    logger.info(
        "Disk capacity verified",
        extra={
            "phase": "download_preflight",
            "job_id": job_id,
            "required_bytes": required_bytes,
            "available_bytes": available,
            "volume": volume,
        },
    )


def download_backup(
    s3: S3ClientProtocol,
    spec: BackupSpec,
    job_id: str,
    dest_dir: str,
    progress_callback: Callable[[int, int, float, float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Download backup tar archive with disk capacity preflight.

    Args:
        s3: Initialized S3 client.
        spec: Discovered backup specification.
        job_id: Job identifier for logging.
        dest_dir: Directory to place downloaded file (created if absent).
        progress_callback: Optional callback(downloaded_bytes, total_bytes, percent_complete, elapsed_seconds).
        cancel_check: Optional callback that returns True if cancellation requested.

    Returns:
        Absolute path to downloaded tar archive.

    Raises:
        DiskCapacityError: Insufficient disk space.
        DownloadError: AWS GetObject failure.
        CancellationError: If cancel_check returns True during download.
    """
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, spec.filename)

    # Disk capacity preflight (size * 1.8 rule)
    required_bytes = int(spec.size_bytes * 1.8)
    ensure_disk_capacity(job_id, required_bytes, dest_path)

    logger.info(
        "Starting S3 download",
        extra={
            "phase": "download_start",
            "job_id": job_id,
            "bucket": spec.bucket,
            "key": spec.key,
            "size_bytes": spec.size_bytes,
            "dest_path": dest_path,
        },
    )

    response = _get_object_with_retry(s3, spec.bucket, spec.key, spec.profile, job_id)

    body = response["Body"]  # Streaming body object
    start_time = time.monotonic()
    _stream_download(body, dest_path, job_id, spec.size_bytes, start_time, progress_callback, cancel_check)

    logger.info(
        "Download complete",
        extra={
            "phase": "download_complete",
            "job_id": job_id,
            "dest_path": dest_path,
            "expected_bytes": spec.size_bytes,
        },
    )

    # M5: Verify SHA-256 checksum when companion file was found during discovery.
    if spec.sha256_key:
        try:
            sha256_response = s3.get_object(spec.bucket, spec.sha256_key, profile=spec.profile)
            expected_hex = sha256_response["Body"].read().decode("ascii").split()[0]
            _verify_sha256(dest_path, expected_hex, job_id)
        except DownloadError:
            raise  # Checksum mismatch — propagate immediately
        except Exception as exc:  # Failed to fetch/parse the .sha256 file
            logger.warning(
                "Could not retrieve or parse SHA-256 checksum file; skipping verification",
                extra={
                    "job_id": job_id,
                    "sha256_key": spec.sha256_key,
                    "error": str(exc),
                },
            )

    return dest_path


def _stream_download(
    body: Any,
    dest_path: str,
    job_id: str,
    total_bytes: int,
    start_time: float,
    progress_callback: Callable[[int, int, float, float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Stream data from body to file with progress logging.

    Extracted atom for testing.

    Args:
        body: Streaming response body from S3.
        dest_path: Local file path to write to.
        job_id: Job identifier for logging.
        total_bytes: Expected total size.
        start_time: Monotonic start time for elapsed calculation.
        progress_callback: Called with (downloaded, total, percent, elapsed) every 64MB.
        cancel_check: Called every 128MB; raises CancellationError if returns True.
    """
    from pulldb.domain.errors import CancellationError

    downloaded = 0
    next_progress = PROGRESS_INTERVAL_MB * 1024 * 1024
    next_cancel_check = CANCEL_CHECK_INTERVAL_MB * 1024 * 1024

    with open(dest_path, "wb") as f:  # binary write
        while True:
            chunk = body.read(BUFFER_SIZE)
            if not isinstance(chunk, bytes) or not chunk:  # None or empty -> done
                break
            f.write(chunk)
            downloaded += len(chunk)

            # Progress callback every 64MB
            if downloaded >= next_progress:
                percent = round((downloaded / total_bytes) * 100, 1) if total_bytes > 0 else 0.0
                elapsed = time.monotonic() - start_time
                logger.info(
                    "Download progress",
                    extra={
                        "phase": "download_progress",
                        "job_id": job_id,
                        "downloaded_bytes": downloaded,
                        "total_bytes": total_bytes,
                        "percent_complete": percent,
                        "elapsed_seconds": round(elapsed, 1),
                    },
                )
                if progress_callback:
                    try:
                        progress_callback(downloaded, total_bytes, percent, elapsed)
                    except Exception:
                        # Don't let callback failure break download
                        logger.debug("Progress callback failed", exc_info=True)
                next_progress += PROGRESS_INTERVAL_MB * 1024 * 1024

            # Cancel check every 128MB
            if cancel_check and downloaded >= next_cancel_check:
                if cancel_check():
                    logger.info(
                        "Download cancelled by user request",
                        extra={
                            "phase": "download_cancelled",
                            "job_id": job_id,
                            "downloaded_bytes": downloaded,
                            "total_bytes": total_bytes,
                        },
                    )
                    raise CancellationError(job_id, "download")
                next_cancel_check += CANCEL_CHECK_INTERVAL_MB * 1024 * 1024
