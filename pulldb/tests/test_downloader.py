"""Tests for backup downloader."""

from __future__ import annotations

"""HCA Layer: tests."""

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from pulldb.domain.errors import DiskCapacityError, DownloadError
from pulldb.infra.s3 import BackupSpec
from pulldb.worker import downloader
from pulldb.worker.downloader import download_backup, ensure_disk_capacity


class FakeBody:
    def __init__(self, total: int, chunk: int = 1024 * 1024) -> None:
        self.remaining = total
        self.chunk = chunk

    def read(self, size: int) -> bytes:
        if self.remaining <= 0:
            return b""
        to_send = min(size, self.chunk, self.remaining)
        self.remaining -= to_send
        return b"x" * to_send


def test_ensure_disk_capacity_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate very low disk space
    class FakeUsage:
        total = 100
        used = 0
        free = 50

    def fake_usage(_path: str) -> FakeUsage:
        return FakeUsage()

    # Patch within downloader module to ensure our fake is used
    monkeypatch.setattr(downloader.shutil, "disk_usage", fake_usage)
    with pytest.raises(DiskCapacityError):
        ensure_disk_capacity("job-1", required_bytes=200, path="/tmp/file.tar")


def test_ensure_disk_capacity_sufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeUsage:
        total = 1000
        used = 100
        free = 900

    def fake_usage(_path: str) -> FakeUsage:
        return FakeUsage()

    monkeypatch.setattr(downloader.shutil, "disk_usage", fake_usage)
    # Should not raise
    ensure_disk_capacity("job-1", required_bytes=200, path="/tmp/file.tar")


def test_download_backup_success(monkeypatch: pytest.MonkeyPatch) -> None:
    tmpdir = tempfile.mkdtemp()
    spec = BackupSpec(
        bucket="bucket",
        key="daily/stg/daily_mydumper_acme_2024-01-01T00-00-00Z_Mon_dbimp.tar",
        target="acme",
        timestamp=__import__("datetime").datetime.now(),
        size_bytes=5 * 1024 * 1024,
    )

    # Fake S3 client with streaming body
    fake_s3 = MagicMock()
    # downloader calls s3.get_object(...) (wrapper), so mock that symbol
    fake_s3.get_object.return_value = {"Body": FakeBody(spec.size_bytes)}

    # Plenty disk space
    class FakeUsage:
        total = 10 * 1024 * 1024 * 1024
        used = 0
        free = 9 * 1024 * 1024 * 1024

    def fake_usage(_path: str) -> FakeUsage:
        return FakeUsage()

    monkeypatch.setattr(downloader.shutil, "disk_usage", fake_usage)

    path = download_backup(fake_s3, spec, job_id="job-xyz", dest_dir=tmpdir)
    assert os.path.exists(path)
    assert os.path.getsize(path) == spec.size_bytes  # Body was exact size


def test_download_backup_s3_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tmpdir = tempfile.mkdtemp()
    spec = BackupSpec(
        bucket="bucket",
        key="daily/stg/daily_mydumper_acme_2024-01-01T00-00-00Z_Mon_dbimp.tar",
        target="acme",
        timestamp=__import__("datetime").datetime.now(),
        size_bytes=1,
    )

    fake_s3 = MagicMock()
    fake_s3.get_object.side_effect = Exception("AccessDenied: denied")

    class FakeUsage:
        total = 1024
        used = 0
        free = 1024

    def fake_usage(_path: str) -> FakeUsage:
        return FakeUsage()

    monkeypatch.setattr(downloader.shutil, "disk_usage", fake_usage)

    with pytest.raises(DownloadError) as exc:
        download_backup(fake_s3, spec, job_id="job-xyz", dest_dir=tmpdir)
    assert "AccessDenied" in str(exc.value)


# End of file
