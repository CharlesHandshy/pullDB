"""Tests for pulldb.worker.downloader module.

Tests backup download operations:
- Disk capacity verification
- S3 streaming download
- Progress callback handling
- Cancellation during download
- Error handling
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from pulldb.domain.errors import CancellationError, DiskCapacityError, DownloadError
from pulldb.worker.downloader import (
    BUFFER_SIZE,
    CANCEL_CHECK_INTERVAL_MB,
    PROGRESS_INTERVAL_MB,
    _stream_download,
    download_backup,
    ensure_disk_capacity,
)


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"
SAMPLE_BUCKET = "test-backup-bucket"
SAMPLE_KEY = "daily/stg/qatemplate/backup-2025-01-15.tar"
SAMPLE_SIZE = 100 * 1024 * 1024  # 100 MB


# ---------------------------------------------------------------------------
# ensure_disk_capacity Tests
# ---------------------------------------------------------------------------


class TestEnsureDiskCapacity:
    """Tests for ensure_disk_capacity function."""

    def test_sufficient_space_succeeds(self) -> None:
        """No error when sufficient disk space available."""
        mock_usage = MagicMock()
        mock_usage.free = 200 * 1024 * 1024 * 1024  # 200 GB

        with patch("shutil.disk_usage", return_value=mock_usage):
            # Should not raise
            ensure_disk_capacity(
                SAMPLE_JOB_ID,
                required_bytes=100 * 1024 * 1024 * 1024,  # 100 GB
                path="/tmp/test.tar",
            )

    def test_insufficient_space_raises_error(self) -> None:
        """DiskCapacityError raised when space insufficient."""
        mock_usage = MagicMock()
        mock_usage.free = 50 * 1024 * 1024 * 1024  # 50 GB

        with patch("shutil.disk_usage", return_value=mock_usage):
            with pytest.raises(DiskCapacityError):
                ensure_disk_capacity(
                    SAMPLE_JOB_ID,
                    required_bytes=100 * 1024 * 1024 * 1024,  # 100 GB
                    path="/tmp/test.tar",
                )

    def test_uses_parent_directory_for_volume(self) -> None:
        """disk_usage is called with parent directory."""
        mock_usage = MagicMock()
        mock_usage.free = 200 * 1024 * 1024 * 1024

        with patch("shutil.disk_usage", return_value=mock_usage) as mock_du:
            ensure_disk_capacity(SAMPLE_JOB_ID, 1024, "/var/pulldb/downloads/file.tar")
            # Should use parent directory
            call_arg = mock_du.call_args[0][0]
            assert "file.tar" not in call_arg

    def test_exact_capacity_threshold(self) -> None:
        """Exactly sufficient space succeeds."""
        required = 100 * 1024 * 1024
        mock_usage = MagicMock()
        mock_usage.free = required  # Exactly enough

        with patch("shutil.disk_usage", return_value=mock_usage):
            # Should not raise
            ensure_disk_capacity(SAMPLE_JOB_ID, required, "/tmp/test.tar")


# ---------------------------------------------------------------------------
# _stream_download Tests
# ---------------------------------------------------------------------------


class TestStreamDownload:
    """Tests for _stream_download internal function."""

    def test_writes_data_to_file(self, tmp_path) -> None:
        """Data is written to destination file."""
        import time
        dest_path = str(tmp_path / "test.tar")
        data = b"test data content"

        mock_body = MagicMock()
        mock_body.read.side_effect = [data, b""]

        _stream_download(mock_body, dest_path, SAMPLE_JOB_ID, len(data), time.monotonic(), None)

        with open(dest_path, "rb") as f:
            assert f.read() == data

    def test_calls_progress_callback(self, tmp_path) -> None:
        """Progress callback is invoked during download."""
        import time
        dest_path = str(tmp_path / "test.tar")
        # Create data larger than progress interval
        chunk_size = PROGRESS_INTERVAL_MB * 1024 * 1024
        data = b"x" * chunk_size

        mock_body = MagicMock()
        mock_body.read.side_effect = [data, b""]

        progress_calls = []

        def progress_callback(downloaded: int, total: int, percent: float, elapsed: float) -> None:
            progress_calls.append((downloaded, total, percent, elapsed))

        _stream_download(
            mock_body, dest_path, SAMPLE_JOB_ID, chunk_size, time.monotonic(), progress_callback
        )

        assert len(progress_calls) >= 1
        assert progress_calls[0][0] == chunk_size
        assert progress_calls[0][2] == 100.0  # 100% since downloaded == total

    def test_handles_callback_exception(self, tmp_path) -> None:
        """Download continues even if callback raises exception."""
        import time
        dest_path = str(tmp_path / "test.tar")
        chunk_size = PROGRESS_INTERVAL_MB * 1024 * 1024
        data = b"x" * chunk_size

        mock_body = MagicMock()
        mock_body.read.side_effect = [data, b""]

        def failing_callback(downloaded: int, total: int, percent: float, elapsed: float) -> None:
            raise RuntimeError("Callback failed")

        # Should not raise despite callback failure
        _stream_download(
            mock_body, dest_path, SAMPLE_JOB_ID, chunk_size, time.monotonic(), failing_callback
        )

        # File should still be written
        with open(dest_path, "rb") as f:
            assert len(f.read()) == chunk_size

    def test_reads_in_chunks(self, tmp_path) -> None:
        """Data is read in BUFFER_SIZE chunks."""
        import time
        dest_path = str(tmp_path / "test.tar")

        mock_body = MagicMock()
        mock_body.read.side_effect = [b"chunk1", b"chunk2", b""]

        _stream_download(mock_body, dest_path, SAMPLE_JOB_ID, 12, time.monotonic(), None)

        # Verify read was called with BUFFER_SIZE
        mock_body.read.assert_called_with(BUFFER_SIZE)

    def test_cancel_check_raises_cancellation_error(self, tmp_path) -> None:
        """Cancel check triggers CancellationError when it returns True."""
        import time
        dest_path = str(tmp_path / "test.tar")
        # Create data larger than cancel check interval (128MB)
        chunk_size = CANCEL_CHECK_INTERVAL_MB * 1024 * 1024
        data = b"x" * chunk_size

        mock_body = MagicMock()
        # Provide enough chunks to trigger cancel check
        mock_body.read.side_effect = [data, data, b""]

        # Cancel check returns True (cancellation requested)
        cancel_check = MagicMock(return_value=True)

        with pytest.raises(CancellationError) as exc_info:
            _stream_download(
                mock_body, dest_path, SAMPLE_JOB_ID, chunk_size * 2, time.monotonic(), None, cancel_check
            )

        assert exc_info.value.detail["job_id"] == SAMPLE_JOB_ID
        assert exc_info.value.detail["phase"] == "download"

    def test_cancel_check_not_triggered_when_returns_false(self, tmp_path) -> None:
        """Download continues when cancel_check returns False."""
        import time
        dest_path = str(tmp_path / "test.tar")
        chunk_size = CANCEL_CHECK_INTERVAL_MB * 1024 * 1024
        data = b"x" * chunk_size

        mock_body = MagicMock()
        mock_body.read.side_effect = [data, data, b""]

        # Cancel check returns False (no cancellation)
        cancel_check = MagicMock(return_value=False)

        # Should complete without error
        _stream_download(
            mock_body, dest_path, SAMPLE_JOB_ID, chunk_size * 2, time.monotonic(), None, cancel_check
        )

        # File should be written completely
        with open(dest_path, "rb") as f:
            assert len(f.read()) == chunk_size * 2

        # Cancel check should have been called
        assert cancel_check.call_count >= 1


# ---------------------------------------------------------------------------
# download_backup Tests
# ---------------------------------------------------------------------------


class TestDownloadBackup:
    """Tests for download_backup function."""

    @pytest.fixture
    def mock_backup_spec(self) -> MagicMock:
        """Create mock BackupSpec."""
        mock = MagicMock()
        mock.bucket = SAMPLE_BUCKET
        mock.key = SAMPLE_KEY
        mock.filename = "backup-2025-01-15.tar"
        mock.size_bytes = SAMPLE_SIZE
        mock.profile = "test-profile"
        return mock

    @pytest.fixture
    def mock_s3_client(self) -> MagicMock:
        """Create mock S3Client."""
        mock = MagicMock()
        mock_body = MagicMock()
        mock_body.read.side_effect = [b"test data", b""]
        mock.get_object.return_value = {"Body": mock_body}
        return mock

    def test_creates_destination_directory(
        self, tmp_path, mock_s3_client, mock_backup_spec
    ) -> None:
        """Destination directory is created if not exists."""
        dest_dir = str(tmp_path / "new_dir" / "nested")

        mock_usage = MagicMock()
        mock_usage.free = 1024 * 1024 * 1024 * 100  # 100GB

        with patch("shutil.disk_usage", return_value=mock_usage):
            download_backup(mock_s3_client, mock_backup_spec, SAMPLE_JOB_ID, dest_dir)

        assert os.path.isdir(dest_dir)

    def test_returns_destination_path(
        self, tmp_path, mock_s3_client, mock_backup_spec
    ) -> None:
        """Returns full path to downloaded file."""
        dest_dir = str(tmp_path)

        mock_usage = MagicMock()
        mock_usage.free = 1024 * 1024 * 1024 * 100

        with patch("shutil.disk_usage", return_value=mock_usage):
            result = download_backup(
                mock_s3_client, mock_backup_spec, SAMPLE_JOB_ID, dest_dir
            )

        assert result == os.path.join(dest_dir, mock_backup_spec.filename)

    def test_applies_1_8_size_rule(
        self, tmp_path, mock_s3_client, mock_backup_spec
    ) -> None:
        """Disk capacity check uses 1.8x file size."""
        dest_dir = str(tmp_path)
        mock_backup_spec.size_bytes = 100 * 1024 * 1024  # 100 MB

        mock_usage = MagicMock()
        mock_usage.free = 150 * 1024 * 1024  # 150 MB (less than 180 MB needed)

        with patch("shutil.disk_usage", return_value=mock_usage):
            with pytest.raises(DiskCapacityError):
                download_backup(
                    mock_s3_client, mock_backup_spec, SAMPLE_JOB_ID, dest_dir
                )

    def test_calls_s3_get_object(
        self, tmp_path, mock_s3_client, mock_backup_spec
    ) -> None:
        """S3 get_object is called with correct parameters."""
        dest_dir = str(tmp_path)

        mock_usage = MagicMock()
        mock_usage.free = 1024 * 1024 * 1024 * 100

        with patch("shutil.disk_usage", return_value=mock_usage):
            download_backup(mock_s3_client, mock_backup_spec, SAMPLE_JOB_ID, dest_dir)

        mock_s3_client.get_object.assert_called_once_with(
            SAMPLE_BUCKET, SAMPLE_KEY, profile=mock_backup_spec.profile
        )

    def test_s3_error_raises_download_error(
        self, tmp_path, mock_s3_client, mock_backup_spec
    ) -> None:
        """S3 errors are wrapped in DownloadError."""
        dest_dir = str(tmp_path)
        mock_s3_client.get_object.side_effect = Exception("S3 connection failed")

        mock_usage = MagicMock()
        mock_usage.free = 1024 * 1024 * 1024 * 100

        with patch("shutil.disk_usage", return_value=mock_usage):
            with pytest.raises(DownloadError):
                download_backup(
                    mock_s3_client, mock_backup_spec, SAMPLE_JOB_ID, dest_dir
                )

    def test_passes_progress_callback(
        self, tmp_path, mock_s3_client, mock_backup_spec
    ) -> None:
        """Progress callback is passed to streaming function."""
        dest_dir = str(tmp_path)
        progress_calls = []

        def callback(downloaded: int, total: int, percent: float, elapsed: float) -> None:
            progress_calls.append((downloaded, total, percent, elapsed))

        mock_usage = MagicMock()
        mock_usage.free = 1024 * 1024 * 1024 * 100

        # Set up body to return enough data to trigger progress
        chunk = b"x" * (PROGRESS_INTERVAL_MB * 1024 * 1024)
        mock_body = MagicMock()
        mock_body.read.side_effect = [chunk, b""]
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        with patch("shutil.disk_usage", return_value=mock_usage):
            download_backup(
                mock_s3_client,
                mock_backup_spec,
                SAMPLE_JOB_ID,
                dest_dir,
                progress_callback=callback,
            )

        assert len(progress_calls) >= 1
