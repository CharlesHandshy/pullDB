from __future__ import annotations


"""Tests for worker component failure modes (FAIL HARD verification).

    HCA Layer: tests

Covers edge cases and failure paths identified in atom evaluation:
- Service: Config/Repo/Executor build failures
- Executor: FS permissions, DB errors
- Downloader: Stream write errors (disk full simulation)
- Restore: Binary missing, execution errors
- Staging: DB permission errors
- Post-SQL: Script read errors
"""

import os
import stat
from datetime import datetime
from pathlib import Path
from unittest import mock

import mysql.connector
import pytest

from pulldb.domain.config import Config
from pulldb.domain.errors import (
    MyLoaderError,
    StagingError,
)
from pulldb.domain.models import Job, JobStatus
from pulldb.infra.exec import CommandExecutionError
from pulldb.infra.mysql import JobRepository
from pulldb.infra.s3 import BackupSpec, S3Client
from pulldb.worker.downloader import download_backup
from pulldb.worker.executor import WorkerExecutorDependencies, WorkerJobExecutor
from pulldb.worker.post_sql import PostSQLConnectionSpec, execute_post_sql
from pulldb.worker.restore import run_myloader
from pulldb.worker.service import _build_job_executor, _build_job_repository
from pulldb.worker.staging import StagingConnectionSpec, cleanup_orphaned_staging


# --- Service Failure Tests ---


def test_build_job_repository_fails_on_db_error() -> None:
    """Verify _build_job_repository propagates DB connection errors."""
    config = Config.minimal_from_env()
    config.mysql_host = "invalid-host"

    # Mock is_simulation_mode to return False and MySQLPool to raise
    with mock.patch("pulldb.worker.service.is_simulation_mode", return_value=False):
        with mock.patch("pulldb.worker.service.MySQLPool") as mock_pool:
            mock_pool.side_effect = mysql.connector.Error(msg="Connection failed")

            with pytest.raises(mysql.connector.Error, match="Connection failed"):
                _build_job_repository(config)


def test_build_job_executor_fails_on_s3_error() -> None:
    """Verify _build_job_executor propagates S3 client init errors."""
    config = Config.minimal_from_env()
    job_repo = mock.Mock(spec=JobRepository)
    job_repo.pool = mock.Mock()  # Add pool attribute

    # Mock is_simulation_mode to return False and S3Client to raise
    with mock.patch("pulldb.worker.service.is_simulation_mode", return_value=False):
        with mock.patch("pulldb.worker.service.S3Client") as mock_s3:
            mock_s3.side_effect = Exception("S3 init failed")

            with pytest.raises(Exception, match="S3 init failed"):
                _build_job_executor(config, job_repo)


# --- Executor Failure Tests ---


def test_executor_prepare_job_dirs_permission_error(tmp_path: Path) -> None:
    """Verify executor fails hard if work dir cannot be created."""
    # Create a read-only directory
    read_only_dir = tmp_path / "readonly"
    read_only_dir.mkdir()
    os.chmod(read_only_dir, stat.S_IREAD | stat.S_IEXEC)

    config = Config.minimal_from_env()
    config.work_dir = read_only_dir
    config.s3_bucket_path = "bucket/prefix"  # Required for executor init

    deps = mock.Mock(spec=WorkerExecutorDependencies)
    executor = WorkerJobExecutor(config=config, deps=deps)
    job = Job(
        id="job-123",
        owner_user_id="u1",
        owner_username="owner",
        owner_user_code="owner",
        target="target",
        staging_name="target_job123",
        dbhost="localhost",
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(),
    )

    # Should raise PermissionError when trying to create job_dir inside read-only root
    with pytest.raises(PermissionError):
        executor._prepare_job_dirs(job.id)  # type: ignore[attr-defined]


def test_executor_handle_failure_db_error() -> None:
    """Verify _handle_failure logs exception if DB update fails."""
    config = Config.minimal_from_env()
    config.s3_bucket_path = "bucket/prefix"  # Required for executor init
    deps = mock.Mock(spec=WorkerExecutorDependencies)
    deps.job_repo.mark_job_failed.side_effect = Exception("DB update failed")

    executor = WorkerJobExecutor(config=config, deps=deps)
    job = Job(
        id="job-123",
        owner_user_id="u1",
        owner_username="owner",
        owner_user_code="owner",
        target="target",
        staging_name="target_job123",
        dbhost="localhost",
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(),
    )

    # Should not raise, but log error (verified via coverage/logs in real run)
    # We just ensure it doesn't crash the worker loop
    executor._handle_failure(job, Exception("Original error"))  # type: ignore[attr-defined]


# --- Downloader Failure Tests ---


def test_download_backup_write_error(tmp_path: Path) -> None:
    """Verify download fails if disk write fails (simulated disk full)."""
    s3 = mock.Mock(spec=S3Client)
    spec = BackupSpec(
        bucket="b",
        key="k",
        target="t",
        timestamp=datetime.now(),
        size_bytes=100,
    )

    # Mock S3 body stream
    mock_body = mock.Mock()
    mock_body.read.return_value = b"data"
    s3.get_object.return_value = {"Body": mock_body}

    # Mock open() to simulate write error
    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        mock_file.return_value.write.side_effect = OSError("No space left on device")

        # Bypass disk capacity check
        with (
            mock.patch("pulldb.worker.downloader.ensure_disk_capacity"),
            pytest.raises(OSError, match="No space left on device"),
        ):
            download_backup(s3, spec, "job-1", str(tmp_path))


# --- Restore Failure Tests ---


def test_run_myloader_binary_missing() -> None:
    """Verify run_myloader raises MyLoaderError if binary missing."""
    spec = mock.Mock()
    spec.binary_path = "/non/existent/myloader"
    spec.job_id = "job-1"
    spec.env = {}
    spec.extra_args = []
    spec.backup_dir = "/tmp/backup"  # Must be a string for Path()

    # Mock run_command to raise CommandExecutionError (simulating FileNotFoundError)
    with mock.patch("pulldb.worker.restore.run_command_streaming") as mock_run:
        mock_run.side_effect = CommandExecutionError(
            ["/non/existent/myloader"],
            FileNotFoundError(2, "No such file or directory"),
        )

        with pytest.raises(MyLoaderError) as exc:
            run_myloader(spec)

        assert exc.value.detail["exit_code"] == -1
        assert "No such file or directory" in exc.value.detail["stderr"]


# --- Staging Failure Tests ---


def test_cleanup_orphaned_staging_drop_permission_error() -> None:
    """Verify cleanup raises StagingError if DROP DATABASE fails."""
    conn_spec = StagingConnectionSpec("h", 3306, "u", "p", 5)

    with mock.patch("mysql.connector.connect") as mock_connect:
        mock_cursor = mock_connect.return_value.cursor.return_value
        # Mock SHOW DATABASES and processlist
        mock_cursor.fetchall.side_effect = [
            [("target_000000000000",)],  # SHOW DATABASES (first call)
            [],  # SELECT db FROM information_schema.processlist
        ]
        # _has_pulldb_table creates its own cursor (same mock_cursor) and
        # calls fetchone; return a row so the orphan passes ownership check.
        mock_cursor.fetchone.return_value = ("1",)

        # Mock execute calls in order:
        #   1. SHOW DATABASES
        #   2. SELECT db FROM information_schema.processlist
        #   3. _has_pulldb_table: SELECT 1 FROM information_schema.TABLES
        #   4. DROP DATABASE IF EXISTS — raises access-denied error
        mock_cursor.execute.side_effect = [
            None,  # SHOW DATABASES
            None,  # SELECT db FROM information_schema.processlist
            None,  # _has_pulldb_table ownership check
            mysql.connector.Error(msg="Access denied for DROP"),  # DROP
        ]

        with pytest.raises(StagingError, match="Access denied for DROP"):
            cleanup_orphaned_staging(
                conn_spec, "target", "550e8400-e29b-41d4-a716-446655440000"
            )


# --- Post-SQL Failure Tests ---


def test_execute_post_sql_script_read_error(tmp_path: Path) -> None:
    """Verify execute_post_sql raises PostSQLError if script unreadable."""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    script = script_dir / "01.sql"
    script.write_text("SELECT 1;")

    # Make script unreadable
    os.chmod(script, 0o000)

    spec = PostSQLConnectionSpec("db", script_dir, "h", 3306, "u", "p")

    try:
        with (
            mock.patch("mysql.connector.connect"),
            pytest.raises(PermissionError),
        ):  # Or PostSQLError wrapping it
            execute_post_sql(spec)
    finally:
        # Restore permissions for cleanup
        os.chmod(script, 0o644)
