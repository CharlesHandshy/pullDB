"""Domain exception classes following FAIL HARD principles.

All exceptions provide structured diagnostic information: goal, problem,
root cause, and ranked solutions. Never silently degrade—fail immediately
with actionable context for operators.

Example:
    >>> raise DiskCapacityError(
    ...     job_id="abc123", required_gb=150, available_gb=80, volume="/mnt/data"
    ... )
"""

from __future__ import annotations

from typing import Any


class JobExecutionError(Exception):
    """Base exception for job execution failures.

    All pullDB job failures inherit from this class. Includes structured
    FAIL HARD diagnostic fields required for troubleshooting.

    Attributes:
        goal: What operation was attempted.
        problem: What went wrong (specific symptom).
        root_cause: Why it failed (validated diagnosis).
        solutions: Ranked remediation steps (most effective first).
        detail: Additional context (job_id, parameters, etc.).
    """

    def __init__(
        self,
        goal: str,
        problem: str,
        root_cause: str,
        solutions: list[str],
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Initialize job execution error with FAIL HARD diagnostics.

        Args:
            goal: Intended operation (single sentence).
            problem: Observed failure (specific, verbatim when possible).
            root_cause: Validated reason (no speculation).
            solutions: Ranked remediation steps (1 = best).
            detail: Additional context dict (job_id, parameters, etc.).
        """
        self.goal = goal
        self.problem = problem
        self.root_cause = root_cause
        self.solutions = solutions
        self.detail = detail or {}

        # Format multi-line diagnostic message
        msg_lines = [
            f"Goal: {goal}",
            f"Problem: {problem}",
            f"Root Cause: {root_cause}",
            "Solutions:",
        ]
        for idx, solution in enumerate(solutions, 1):
            msg_lines.append(f"  {idx}. {solution}")

        if detail:
            msg_lines.append("Detail:")
            for key, value in detail.items():
                msg_lines.append(f"  {key}: {value}")

        super().__init__("\n".join(msg_lines))


class DownloadError(JobExecutionError):
    """S3 backup download failed.

    Raised when S3 GetObject fails, backup validation fails, or network
    errors prevent download completion.
    """

    def __init__(
        self,
        job_id: str,
        backup_key: str,
        error_code: str,
        message: str,
    ) -> None:
        """Initialize download error.

        Args:
            job_id: Job UUID.
            backup_key: S3 object key attempted.
            error_code: AWS error code (NoSuchKey, AccessDenied, etc.).
            message: AWS error message.
        """
        solutions = []
        if error_code == "NoSuchKey":
            solutions = [
                "Verify backup exists in S3 bucket (check backup schedule)",
                "Confirm customer/template name matches S3 prefix",
                "Check if backup rotation deleted the archive",
            ]
        elif error_code == "AccessDenied":
            solutions = [
                "Attach IAM policy 'pulldb-s3-read-access' to worker role",
                "Verify bucket policy allows GetObject from worker account",
                "Check KMS key permissions if bucket uses SSE-KMS encryption",
            ]
        else:
            solutions = [
                f"Inspect AWS error code '{error_code}' documentation",
                "Retry download (may be transient network issue)",
                "Check CloudWatch logs for additional context",
            ]

        super().__init__(
            goal=f"Download backup from S3 for job {job_id}",
            problem=f"S3 GetObject failed with error: {error_code}",
            root_cause=message,
            solutions=solutions,
            detail={
                "job_id": job_id,
                "backup_key": backup_key,
                "error_code": error_code,
            },
        )


class DiskCapacityError(JobExecutionError):
    """Insufficient disk space for backup extraction.

    Raised when available disk space is less than required (tar_size * 1.8).
    Job fails before download to prevent partial extraction failures.
    """

    def __init__(
        self,
        job_id: str,
        required_gb: float,
        available_gb: float,
        volume: str,
    ) -> None:
        """Initialize disk capacity error.

        Args:
            job_id: Job UUID.
            required_gb: Required space (tar size * 1.8).
            available_gb: Currently available space.
            volume: Volume path checked.
        """
        super().__init__(
            goal=f"Verify disk capacity for job {job_id}",
            problem=(
                f"Insufficient space: need {required_gb:.1f}GB, "
                f"have {available_gb:.1f}GB"
            ),
            root_cause=(
                f"Volume {volume} does not meet 1.8x extraction buffer requirement"
            ),
            solutions=[
                "Free disk space by removing old restored databases",
                "Clean up staging databases from failed jobs (orphan cleanup)",
                "Increase volume size or attach additional EBS volume",
                "Switch to alternative worker host with more capacity",
            ],
            detail={
                "job_id": job_id,
                "required_gb": required_gb,
                "available_gb": available_gb,
                "volume": volume,
            },
        )


class MyLoaderError(JobExecutionError):
    """myloader subprocess failed during restore.

    Raised when myloader exits with non-zero status. Preserves stdout/stderr
    for diagnostics and suggests common remediation steps.
    """

    def __init__(
        self,
        job_id: str,
        command: list[str],
        exit_code: int,
        stdout: str,
        stderr: str,
    ) -> None:
        """Initialize myloader error.

        Args:
            job_id: Job UUID.
            command: myloader command executed.
            exit_code: Non-zero exit code.
            stdout: Captured stdout (last 5000 chars).
            stderr: Captured stderr (last 5000 chars).
        """
        super().__init__(
            goal=f"Execute myloader to restore staging database for job {job_id}",
            problem=f"myloader exited with code {exit_code}",
            root_cause="Non-zero exit code from subprocess (see stderr for detail)",
            solutions=[
                "Inspect stderr for missing tables or permission errors",
                "Verify disk space and MySQL user privileges on target host",
                "Check MySQL connection limits (max_connections)",
                "Re-run with increased verbosity: add --verbose flag to myloader",
                "Verify backup format matches myloader version",
            ],
            detail={
                "job_id": job_id,
                "command": " ".join(command),
                "exit_code": exit_code,
                "stdout": stdout[-5000:],  # Last 5KB
                "stderr": stderr[-5000:],
            },
        )


class PostSQLError(JobExecutionError):
    """Post-restore SQL script execution failed.

    Raised when a post-restore SQL script returns an error. Preserves partial
    results (scripts that succeeded before failure) and identifies failing script.
    """

    def __init__(
        self,
        job_id: str,
        script_name: str,
        error_message: str,
        completed_scripts: list[str],
    ) -> None:
        """Initialize post-SQL error.

        Args:
            job_id: Job UUID.
            script_name: Script that failed (e.g., '030.sanitize_users.sql').
            error_message: MySQL error message.
            completed_scripts: Scripts that succeeded before failure.
        """
        super().__init__(
            goal=f"Execute post-restore SQL scripts for job {job_id}",
            problem=f"Script {script_name} failed with error",
            root_cause=error_message,
            solutions=[
                f"Inspect {script_name} for syntax errors or missing tables",
                "Verify backup format matches expected schema (check myloader output)",
                "Review completed scripts for unintended side effects",
                "Fix script and rerun job (staging database preserved for debugging)",
            ],
            detail={
                "job_id": job_id,
                "script_name": script_name,
                "error_message": error_message,
                "completed_scripts": completed_scripts,
            },
        )


class AtomicRenameError(JobExecutionError):
    """Staging database rename to target failed.

    Raised when the atomic rename procedure fails after successful restore.
    Staging database is preserved for manual inspection and retry.
    """

    def __init__(
        self,
        job_id: str,
        staging_name: str,
        target_name: str,
        error_message: str,
    ) -> None:
        """Initialize atomic rename error.

        Args:
            job_id: Job UUID.
            staging_name: Staging database name.
            target_name: Target database name.
            error_message: MySQL error message from rename procedure.
        """
        super().__init__(
            goal=f"Atomically rename staging database to target for job {job_id}",
            problem=f"Rename procedure failed: {staging_name} → {target_name}",
            root_cause=error_message,
            solutions=[
                "Check if target database has active connections (close them)",
                "Verify MySQL user has ALTER/DROP privileges on both databases",
                "Inspect staging database manually (preserved for debugging)",
                "Retry job with overwrite flag after manual cleanup",
                "Contact DBA if stored procedure is missing or corrupted",
            ],
            detail={
                "job_id": job_id,
                "staging_name": staging_name,
                "target_name": target_name,
                "error_message": error_message,
            },
        )


class BackupValidationError(JobExecutionError):
    """Backup archive failed validation checks.

    Raised when schema-create.sql.zst is missing or backup format is invalid.
    Prevents wasted download/extraction cycles for corrupt backups.
    """

    def __init__(
        self,
        job_id: str,
        backup_key: str,
        missing_files: list[str],
    ) -> None:
        """Initialize backup validation error.

        Args:
            job_id: Job UUID.
            backup_key: S3 object key attempted.
            missing_files: Required files not found in listing.
        """
        super().__init__(
            goal=f"Validate backup completeness for job {job_id}",
            problem=f"Required files missing from backup: {', '.join(missing_files)}",
            root_cause="Backup archive is incomplete or corrupt",
            solutions=[
                "Check backup creation logs for errors (mydumper logs)",
                "Verify backup rotation didn't delete schema files",
                "Try previous day's backup as fallback",
                "Contact backup administrator to investigate corruption",
            ],
            detail={
                "job_id": job_id,
                "backup_key": backup_key,
                "missing_files": missing_files,
            },
        )
