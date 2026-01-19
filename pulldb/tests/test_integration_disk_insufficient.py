"""Integration test: disk insufficient failure during download preflight.

Simulates a restore workflow phase where downloader preflight raises
DiskCapacityError. We directly invoke ensure_disk_capacity to keep
scope focused on error translation (no actual S3 download performed).

HCA Layer: tests (pulldb/tests/)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pulldb.domain.errors import DiskCapacityError
from pulldb.worker.downloader import ensure_disk_capacity


def test_disk_insufficient_preflight(tmp_path: Path) -> None:
    """FAIL HARD when required bytes exceed available disk space.

    We simulate by passing an artificially huge required_bytes value
    (e.g., current free + 1 GiB) so the capacity check deterministically
    triggers DiskCapacityError without needing to monkeypatch shutil.
    """
    volume = tmp_path
    # Probe actual free space once
    import os
    import shutil

    usage = shutil.disk_usage(volume)
    # Force requirement beyond available by adding 1 GiB
    required_bytes = usage.free + (1024**3)
    target_file = os.path.join(volume, "dummy.tar")

    with pytest.raises(DiskCapacityError) as exc:
        ensure_disk_capacity(
            job_id="job-disk-1",
            required_bytes=required_bytes,
            path=target_file,
        )

    detail = exc.value.detail
    assert detail.get("volume") == str(volume)
    assert "required_gb" in detail and detail["required_gb"] is not None
    assert "available_gb" in detail and detail["available_gb"] is not None
    required_gb = float(detail["required_gb"])
    available_gb = float(detail["available_gb"])
    assert required_gb > available_gb


def test_disk_capacity_success(tmp_path: Path) -> None:
    """Disk capacity preflight passes when required bytes well below free space.

    Uses actual disk usage and scales required_bytes to 50% of available to
    guarantee success without mocking. Serves as integration sanity check
    distinct from unit tests that patch shutil.disk_usage.
    """
    import os
    import shutil

    usage = shutil.disk_usage(tmp_path)
    required_bytes = int(usage.free * 0.5)
    target_file = os.path.join(tmp_path, "ok.tar")
    # Should not raise
    ensure_disk_capacity(
        job_id="job-disk-2",
        required_bytes=required_bytes,
        path=target_file,
    )
