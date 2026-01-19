"""Tests for domain error classes."""

from __future__ import annotations

"""HCA Layer: tests."""

import pytest

from pulldb.domain.errors import (
    AtomicRenameError,
    BackupValidationError,
    DiskCapacityError,
    DownloadError,
    JobExecutionError,
    MyLoaderError,
    PostSQLError,
    TargetCollisionError,
)


def test_job_execution_error_structure() -> None:
    """JobExecutionError includes FAIL HARD diagnostic fields."""
    error = JobExecutionError(
        goal="Test operation",
        problem="Operation failed",
        root_cause="Invalid input",
        solutions=["Fix input", "Retry"],
        detail={"key": "value"},
    )

    assert error.goal == "Test operation"
    assert error.problem == "Operation failed"
    assert error.root_cause == "Invalid input"
    assert error.solutions == ["Fix input", "Retry"]
    assert error.detail == {"key": "value"}


def test_job_execution_error_message_format() -> None:
    """JobExecutionError formats multi-line diagnostic message."""
    error = JobExecutionError(
        goal="Process data",
        problem="Data corrupt",
        root_cause="Invalid checksum",
        solutions=["Re-download", "Verify source"],
    )

    msg = str(error)
    assert "Goal: Process data" in msg
    assert "Problem: Data corrupt" in msg
    assert "Root Cause: Invalid checksum" in msg
    assert "1. Re-download" in msg
    assert "2. Verify source" in msg


def test_download_error_no_such_key() -> None:
    """DownloadError provides S3-specific solutions for NoSuchKey."""
    error = DownloadError(
        job_id="abc123",
        backup_key="daily/prod/customer/backup.tar",
        error_code="NoSuchKey",
        message="The specified key does not exist.",
    )

    assert "job_id" in error.detail
    assert error.detail["error_code"] == "NoSuchKey"
    assert any("backup exists" in sol for sol in error.solutions)


def test_download_error_access_denied() -> None:
    """DownloadError provides IAM solutions for AccessDenied."""
    error = DownloadError(
        job_id="abc123",
        backup_key="daily/prod/customer/backup.tar",
        error_code="AccessDenied",
        message="Access Denied",
    )

    assert any("IAM policy" in sol for sol in error.solutions)
    assert any("bucket policy" in sol for sol in error.solutions)


def test_disk_capacity_error_details() -> None:
    """DiskCapacityError includes capacity calculations."""
    error = DiskCapacityError(
        job_id="abc123",
        required_gb=150.5,
        available_gb=80.2,
        volume="/mnt/data",
    )

    assert error.detail["required_gb"] == 150.5
    assert error.detail["available_gb"] == 80.2
    assert "150.5GB" in str(error)
    assert "80.2GB" in str(error)
    assert any("Free disk space" in sol for sol in error.solutions)


def test_myloader_error_preserves_output() -> None:
    """MyLoaderError captures stdout/stderr for diagnostics."""
    stdout = "Loading tables..." + "x" * 6000  # Exceeds 5KB
    stderr = "Error: Connection refused" + "y" * 6000

    error = MyLoaderError(
        job_id="abc123",
        command=["myloader", "--database=test", "--directory=/tmp/backup"],
        exit_code=1,
        stdout=stdout,
        stderr=stderr,
    )

    # Should truncate to last 5000 chars
    assert len(error.detail["stdout"]) == 5000
    assert len(error.detail["stderr"]) == 5000
    assert error.detail["exit_code"] == 1
    assert "--database=test" in error.detail["command"]


def test_post_sql_error_tracks_completed() -> None:
    """PostSQLError preserves list of successfully completed scripts."""
    error = PostSQLError(
        job_id="abc123",
        script_name="030.sanitize_users.sql",
        error_message="Table 'users' doesn't exist",
        completed_scripts=["010.remove_pii.sql", "020.disable_email.sql"],
    )

    assert error.detail["script_name"] == "030.sanitize_users.sql"
    assert len(error.detail["completed_scripts"]) == 2
    assert "010.remove_pii.sql" in error.detail["completed_scripts"]
    assert any("Inspect 030" in sol for sol in error.solutions)


def test_atomic_rename_error_preserves_staging() -> None:
    """AtomicRenameError advises preserving staging database."""
    error = AtomicRenameError(
        job_id="abc123",
        staging_name="jdoecustomer_550e8400e29b",
        target_name="jdoecustomer",
        error_message="Target database has active connections",
    )

    assert error.detail["staging_name"] == "jdoecustomer_550e8400e29b"
    assert error.detail["target_name"] == "jdoecustomer"
    assert any("active connections" in sol for sol in error.solutions)
    assert any("preserved for debugging" in sol for sol in error.solutions)


def test_backup_validation_error_lists_missing() -> None:
    """BackupValidationError lists all missing required files."""
    error = BackupValidationError(
        job_id="abc123",
        backup_key="daily/prod/customer/backup.tar",
        missing_files=["schema-create.sql.zst", "metadata"],
    )

    assert len(error.detail["missing_files"]) == 2
    assert "schema-create.sql.zst" in error.detail["missing_files"]
    assert any("corrupt" in sol.lower() for sol in error.solutions)


def test_error_inheritance() -> None:
    """All domain errors inherit from JobExecutionError."""
    assert issubclass(DownloadError, JobExecutionError)
    assert issubclass(DiskCapacityError, JobExecutionError)
    assert issubclass(MyLoaderError, JobExecutionError)
    assert issubclass(PostSQLError, JobExecutionError)
    assert issubclass(AtomicRenameError, JobExecutionError)
    assert issubclass(BackupValidationError, JobExecutionError)


def test_error_detail_optional() -> None:
    """JobExecutionError accepts optional detail parameter."""
    error = JobExecutionError(
        goal="Test", problem="Failed", root_cause="Cause", solutions=["Fix"]
    )

    assert error.detail == {}


def test_error_can_be_raised() -> None:
    """Domain errors can be raised and caught."""
    with pytest.raises(DiskCapacityError) as exc_info:
        raise DiskCapacityError(
            job_id="test", required_gb=100, available_gb=50, volume="/data"
        )

    assert "Insufficient space" in str(exc_info.value)
    assert exc_info.value.detail["job_id"] == "test"


# ---------------------------------------------------------------------------
# TargetCollisionError Tests
# ---------------------------------------------------------------------------


def test_target_collision_error_external_db() -> None:
    """TargetCollisionError provides solutions for external database collision."""
    error = TargetCollisionError(
        job_id="abc123",
        target="customerdb",
        dbhost="db-host-1.example.com",
        collision_type="external_db",
    )

    assert error.detail["job_id"] == "abc123"
    assert error.detail["target"] == "customerdb"
    assert error.detail["dbhost"] == "db-host-1.example.com"
    assert error.detail["collision_type"] == "external_db"
    assert "NOT created by pullDB" in str(error)
    assert any("different target" in sol for sol in error.solutions)


def test_target_collision_error_owner_mismatch() -> None:
    """TargetCollisionError provides solutions for owner mismatch."""
    error = TargetCollisionError(
        job_id="abc123",
        target="jdoecustomer",
        dbhost="db-host-1.example.com",
        collision_type="owner_mismatch",
        owner_info="jdoe",
    )

    assert error.detail["collision_type"] == "owner_mismatch"
    assert error.detail["owner"] == "jdoe"
    assert "owned by user 'jdoe'" in str(error)
    assert any("Contact user 'jdoe'" in sol for sol in error.solutions)


def test_target_collision_error_inheritance() -> None:
    """TargetCollisionError inherits from JobExecutionError."""
    assert issubclass(TargetCollisionError, JobExecutionError)


def test_target_collision_error_can_be_raised() -> None:
    """TargetCollisionError can be raised and caught."""
    with pytest.raises(TargetCollisionError) as exc_info:
        raise TargetCollisionError(
            job_id="test",
            target="externaldb",
            dbhost="localhost",
            collision_type="external_db",
        )

    assert exc_info.value.detail["target"] == "externaldb"
