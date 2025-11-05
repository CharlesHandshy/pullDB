"""Domain models for restore execution phases.

These dataclasses describe inputs/outputs for the myloader execution
phase and will be extended as the workflow orchestration matures.

Design Goals:
  * Keep IO contracts explicit and typed
  * Provide stable surface for upcoming workflow tests
  * Avoid premature coupling to CLI/API layers
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MyLoaderSpec:
    """Specification for invoking myloader.

    Attributes:
        job_id: Associated restore job identifier.
        staging_db: Name of staging database to restore into.
        backup_dir: Filesystem path containing extracted mydumper files.
        mysql_host: Target MySQL host.
        mysql_port: Target MySQL port.
        mysql_user: MySQL username with required privileges.
        mysql_password: Password for the MySQL user.
        extra_args: Additional myloader CLI arguments (flags only; no
            host/user duplication). Provided as sequence to preserve
            ordering.
        env: Optional environment variable overrides for subprocess.
    """

    job_id: str
    staging_db: str
    backup_dir: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    extra_args: Sequence[str] = ()
    env: Mapping[str, str] | None = None
    # Path to myloader binary (allows overriding PATH resolution). Default
    # intentionally kept as the simple binary name to allow PATH lookup.
    binary_path: str = "myloader"


@dataclass(slots=True)
class MyLoaderResult:
    """Result of myloader execution.

    Attributes:
        command: Full command list executed.
        exit_code: Process exit code (0 indicates success).
        started_at: UTC timestamp when process launched.
        completed_at: UTC timestamp when process exited.
        duration_seconds: Elapsed wall time in seconds (float
            precision, rounded at caller discretion for logging).
        stdout: Captured stdout (possibly truncated by caller).
        stderr: Captured stderr (possibly truncated by caller).
    """

    command: list[str]
    exit_code: int
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    stdout: str
    stderr: str
