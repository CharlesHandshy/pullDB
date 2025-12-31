"""Backup downloader with disk capacity guard.

Milestone 3: Streams selected S3 tar archive to a local staging directory
and validates sufficient disk space prior to download (size * 1.8 rule).

Responsibilities:
    * Verify available disk space on target volume (FAIL HARD early)
    * Stream S3 object to file (no full in-memory buffering)
    * Provide progress logging (every N MB) - placeholder basic logging
    * Return path to downloaded tar archive for extraction phase (future)

Extraction (mydumper tar unpack) will be implemented in a later milestone.
"""

from __future__ import annotations

import os
import shutil
import typing as t
from typing import Any

from pulldb.domain.errors import DiskCapacityError, DownloadError
from pulldb.infra.logging import get_logger
from pulldb.infra.s3 import BackupSpec, S3Client


logger = get_logger("pulldb.worker.downloader")

BUFFER_SIZE = 8 * 1024 * 1024  # 8MB streaming chunks
PROGRESS_INTERVAL_MB = 64  # Log every 64MB downloaded
CANCEL_CHECK_INTERVAL_MB = 128  # Check for cancellation every 128MB


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
    s3: S3Client,
    spec: BackupSpec,
    job_id: str,
    dest_dir: str,
    progress_callback: t.Callable[[int, int, float], None] | None = None,
    cancel_check: t.Callable[[], bool] | None = None,
) -> str:
    """Download backup tar archive with disk capacity preflight.

    Args:
        s3: Initialized S3 client.
        spec: Discovered backup specification.
        job_id: Job identifier for logging.
        dest_dir: Directory to place downloaded file (created if absent).
        progress_callback: Optional callback(downloaded_bytes, total_bytes, percent_complete).
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

    try:
        response = s3.get_object(spec.bucket, spec.key, profile=spec.profile)
    except Exception as e:  # pragma: no cover - network errors hard to unit test
        error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "Unknown")
        raise DownloadError(
            job_id=job_id,
            backup_key=spec.key,
            error_code=error_code,
            message=str(e),
        ) from e

    body = response["Body"]  # Streaming body object
    _stream_download(body, dest_path, job_id, spec.size_bytes, progress_callback, cancel_check)

    logger.info(
        "Download complete",
        extra={
            "phase": "download_complete",
            "job_id": job_id,
            "dest_path": dest_path,
            "expected_bytes": spec.size_bytes,
        },
    )

    return dest_path


def _stream_download(
    body: Any,
    dest_path: str,
    job_id: str,
    total_bytes: int,
    progress_callback: t.Callable[[int, int, float], None] | None = None,
    cancel_check: t.Callable[[], bool] | None = None,
) -> None:
    """Stream data from body to file with progress logging.

    Extracted atom for testing.

    Args:
        body: Streaming response body from S3.
        dest_path: Local file path to write to.
        job_id: Job identifier for logging.
        total_bytes: Expected total size.
        progress_callback: Called with (downloaded, total, percent) every 64MB.
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
                logger.info(
                    "Download progress",
                    extra={
                        "phase": "download_progress",
                        "job_id": job_id,
                        "downloaded_bytes": downloaded,
                        "total_bytes": total_bytes,
                        "percent_complete": percent,
                    },
                )
                if progress_callback:
                    try:
                        progress_callback(downloaded, total_bytes, percent)
                    except Exception:
                        # Don't let callback failure break download
                        pass
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
