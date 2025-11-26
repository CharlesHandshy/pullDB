"""Tests for restore model helpers."""

from __future__ import annotations

from typing import Any

from pulldb.domain.config import Config
from pulldb.domain.restore_models import build_configured_myloader_spec


def _base_config(**overrides: Any) -> Config:
    params: dict[str, Any] = {
        "mysql_host": "mysql",
        "mysql_user": "worker",
        "mysql_password": "pw",
    }
    params.update(overrides)
    return Config(**params)


def test_build_spec_applies_configured_defaults() -> None:
    # Disable default args to isolate the configured values being tested
    config = _base_config(
        myloader_binary="/opt/myloader",
        myloader_default_args=(),
        myloader_extra_args=("--skip-triggers",),
        myloader_threads=6,
    )

    spec = build_configured_myloader_spec(
        config=config,
        job_id="job-1",
        staging_db="staging_db",
        backup_dir="/tmp/backup",
        mysql_host="dbhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="secret",
        extra_args=["--progress"],
    )

    assert spec.binary_path == "/opt/myloader"
    assert spec.extra_args == (
        "--skip-triggers",
        "--progress",
        "--threads=6",
    )


def test_build_spec_respects_existing_threads_override() -> None:
    # Disable default args to isolate threads behavior
    config = _base_config(
        myloader_threads=10,
        myloader_default_args=(),
        myloader_extra_args=(),
    )

    spec = build_configured_myloader_spec(
        config=config,
        job_id="job-2",
        staging_db="staging_db",
        backup_dir="/tmp/backup",
        mysql_host="dbhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="secret",
        extra_args=["--threads=4"],
    )

    # When --threads is in extra_args, config.myloader_threads is not appended
    assert spec.extra_args == ("--threads=4",)


def test_build_spec_includes_max_threads_per_table_for_new_format() -> None:
    config = _base_config()
    spec = build_configured_myloader_spec(
        config=config,
        job_id="job-3",
        staging_db="staging_db",
        backup_dir="/tmp/backup",
        mysql_host="dbhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="secret",
        format_tag="new",
    )

    assert "--max-threads-per-table=1" in spec.extra_args
