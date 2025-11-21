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

from pulldb.domain.config import Config


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


def build_configured_myloader_spec(
    *,
    config: Config,
    job_id: str,
    staging_db: str,
    backup_dir: str,
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    extra_args: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> MyLoaderSpec:
    """Build :class:`MyLoaderSpec` using configurable defaults.

    Args:
        config: Fully-loaded Config containing myloader overrides.
        job_id: Job identifier forwarded to error diagnostics.
        staging_db: Target staging database for restore.
        backup_dir: Filesystem path to extracted mydumper files.
        mysql_host: Destination MySQL host.
        mysql_port: Destination MySQL port.
        mysql_user: Destination MySQL user.
        mysql_password: Destination MySQL password.
        extra_args: Optional additional CLI args provided by caller.
        env: Optional env overrides passed to subprocess.

    Returns:
        Configured MyLoaderSpec honoring environment/settings overrides.
    """

    merged_args: list[str] = list(config.myloader_extra_args)
    if extra_args:
        merged_args.extend(extra_args)

    if not _has_threads_flag(merged_args):
        merged_args.append(f"--threads={config.myloader_threads}")

    return MyLoaderSpec(
        job_id=job_id,
        staging_db=staging_db,
        backup_dir=backup_dir,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_user=mysql_user,
        mysql_password=mysql_password,
        extra_args=tuple(merged_args),
        env=env,
        binary_path=config.myloader_binary,
    )


def _has_threads_flag(args: Sequence[str]) -> bool:
    return any(arg.startswith("--threads") for arg in args)
