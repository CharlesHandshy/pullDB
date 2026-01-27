"""Domain exception classes following FAIL HARD principles.

All exceptions provide structured diagnostic information: goal, problem,
root cause, and ranked solutions. Never silently degrade—fail immediately
with actionable context for operators.

Example:
    >>> raise DiskCapacityError(
    ...     job_id="abc123", required_gb=150, available_gb=80, volume="/mnt/data"
    ... )

HCA Layer: entities
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


class ExtractionError(JobExecutionError):
    """Extraction of downloaded backup archive failed."""

    def __init__(self, job_id: str, archive_path: str, error_message: str) -> None:
        super().__init__(
            goal=f"Extract backup archive for job {job_id}",
            problem="Extraction failed",
            root_cause=error_message,
            solutions=[
                "Re-download the archive to rule out corruption",
                "Verify GNU tar / libzstd are installed on the worker host",
                "Check permissions and free space for the worker work_dir",
            ],
            detail={
                "job_id": job_id,
                "archive_path": archive_path,
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


class BackupDiscoveryError(JobExecutionError):
    """Raised when no configured S3 location contains a matching backup."""

    def __init__(
        self,
        job_id: str,
        attempts: list[dict[str, str]],
    ) -> None:
        detail = {
            "job_id": job_id,
            "attempts": attempts,
        }
        super().__init__(
            goal=f"Discover backup in configured S3 locations for job {job_id}",
            problem="No S3 location yielded a valid backup archive",
            root_cause=(
                "Configured bucket/prefix combinations either lacked matching objects "
                "or failed validation."
            ),
            solutions=[
                "Verify target aliases match S3 directory names for each bucket",
                "Inspect attempts list and check the corresponding S3 prefix",
                "Add/adjust PULLDB_S3_BACKUP_LOCATIONS configuration to include legacy paths",
                "Re-run backup creation process if archives are missing",
            ],
            detail=detail,
        )


class MetadataInjectionError(JobExecutionError):
    """Metadata table injection failed.

    Raised when pullDB metadata table creation or record insertion fails
    after successful restore. Staging database is preserved with restored data.
    """

    def __init__(
        self,
        job_id: str,
        operation: str,
        error_message: str,
    ) -> None:
        """Initialize metadata injection error.

        Args:
            job_id: Job UUID.
            operation: Operation that failed ('connect', 'create_table', 'insert').
            error_message: MySQL error message with context.
        """
        solutions = []
        if operation == "connect":
            solutions = [
                "Verify staging database exists (check myloader output)",
                "Verify MySQL credentials have database access privilege",
                "Check network connectivity to target MySQL host",
            ]
        elif operation == "create_table":
            solutions = [
                "Verify MySQL user has CREATE TABLE privilege",
                "Check if database has exceeded table limit",
                "Inspect MySQL error logs for storage engine issues",
            ]
        elif operation == "insert":
            solutions = [
                "Verify pullDB table schema matches expected structure",
                "Check for existing record with same job_id (duplicate key)",
                "Inspect post-SQL JSON for invalid characters or size limit",
            ]
        else:
            solutions = [
                f"Inspect error message for '{operation}' operation details",
                "Contact DBA for MySQL-level diagnostics",
            ]

        super().__init__(
            goal=f"Inject pullDB metadata table into staging database for job {job_id}",
            problem=f"Metadata {operation} operation failed",
            root_cause=error_message,
            solutions=solutions,
            detail={
                "job_id": job_id,
                "operation": operation,
            },
        )


class TargetCollisionError(JobExecutionError):
    """Target database collision detected during pre-flight check.

    Raised when the target database exists but cannot be safely overwritten:
    - External database (no pullDB metadata table)
    - Owned by different user
    - Database exists but overwrite not enabled
    - Connection failed (cannot verify safety)
    
    This check runs BEFORE expensive operations (download, extract, myloader)
    to fail fast and save resources.
    
    See .pulldb/standards/database-protection.md for protection requirements.
    """

    def __init__(
        self,
        job_id: str,
        target: str,
        dbhost: str,
        collision_type: str,
        owner_info: str | None = None,
    ) -> None:
        """Initialize target collision error.

        Args:
            job_id: Job UUID.
            target: Target database name that collided.
            dbhost: Database host where collision occurred.
            collision_type: Type of collision:
                - 'external_db': No pullDB metadata table
                - 'owner_mismatch': Owned by different user
                - 'exists_no_overwrite': Exists but overwrite not enabled
                - 'connection_failed': Cannot connect to verify safety
            owner_info: Owner username/code if available (for owner_mismatch).
        """
        if collision_type == "external_db":
            problem = (
                f"PROTECTED: Database '{target}' exists on '{dbhost}' but was NOT created by pullDB "
                f"(no pullDB metadata table found)"
            )
            solutions = [
                "Choose a different target database name",
                "Manually drop the existing database if you're certain it's safe",
                "Contact DBA to verify database origin and ownership",
            ]
        elif collision_type == "owner_mismatch":
            problem = (
                f"PROTECTED: Database '{target}' exists on '{dbhost}' and is owned by user '{owner_info}'"
            )
            solutions = [
                f"Contact user '{owner_info}' to coordinate database access",
                "Choose a different target database name",
                "Request administrator assistance if user is no longer active",
            ]
        elif collision_type == "exists_no_overwrite":
            problem = (
                f"Database '{target}' already exists on '{dbhost}' but overwrite was not enabled"
            )
            solutions = [
                "Enable 'Allow Overwrite' checkbox in the UI or add 'overwrite' flag in CLI",
                "Choose a different target database name",
            ]
        elif collision_type == "connection_failed":
            problem = (
                f"Cannot verify safety of target '{target}' on '{dbhost}' - connection failed"
            )
            solutions = [
                "Check that the target database host is reachable",
                "Verify MySQL credentials are correct",
                "Try again after network connectivity is restored",
            ]
        else:
            problem = f"Target collision detected: {collision_type}"
            solutions = ["Review collision details and choose a different target"]

        super().__init__(
            goal=f"Verify target database '{target}' is safe to overwrite for job {job_id}",
            problem=problem,
            root_cause=(
                "Pre-flight safety check failed. pullDB cannot overwrite databases "
                "it did not create or databases owned by other users."
            ),
            solutions=solutions,
            detail={
                "job_id": job_id,
                "target": target,
                "dbhost": dbhost,
                "collision_type": collision_type,
                "owner": owner_info,
            },
        )


class StagingError(Exception):
    """Staging database lifecycle operation failed.

    Raised when staging name generation, orphan cleanup, or uniqueness
    verification fails. Uses simplified error format for operations that
    don't warrant full FAIL HARD structure (e.g., input validation).
    """

    pass


class CancellationError(JobExecutionError):
    """Job was canceled by user request.

    Raised when a running job detects a cancellation request at a checkpoint.
    This is a controlled termination, not an error condition. Cleanup
    happens automatically (staging database dropped, work dir removed).
    """

    def __init__(
        self,
        job_id: str,
        phase: str,
    ) -> None:
        """Initialize cancellation error.

        Args:
            job_id: Job UUID.
            phase: Phase where cancellation was detected (download, extraction, etc.).
        """
        super().__init__(
            goal=f"Execute restore job {job_id}",
            problem=f"Job canceled by user request at phase: {phase}",
            root_cause="User requested cancellation via API or CLI",
            solutions=[
                "This is expected behavior - job terminated cleanly",
                "Submit a new job if restore is still needed",
            ],
            detail={
                "job_id": job_id,
                "phase": phase,
            },
        )


class LockedUserError(Exception):
    """Raised when attempting to modify a locked user account.

    Locked users are system-protected accounts (e.g., pulldb_service) that
    cannot be modified via the admin UI, API, or CLI. They can only be
    unlocked via direct SQL updates.

    Attributes:
        username: The username of the locked user.
        action: The action that was attempted (e.g., "disable", "delete").
    """

    def __init__(self, username: str, action: str) -> None:
        """Initialize locked user error.

        Args:
            username: Username of the locked user.
            action: Operation that was blocked (e.g., "enable", "delete").
        """
        self.username = username
        self.action = action
        super().__init__(f"Cannot {action} locked user: {username}")


class KeyPendingApprovalError(Exception):
    """Raised when attempting to use an API key that is pending admin approval.

    New API keys created via request-host-key are inactive until an admin
    approves them. This error indicates the key exists but cannot be used yet.

    Attributes:
        key_id: The public key identifier that is pending approval.
    """

    def __init__(self, key_id: str) -> None:
        """Initialize key pending approval error.

        Args:
            key_id: The public key identifier (key_xxxxx...).
        """
        self.key_id = key_id
        super().__init__(
            f"API key pending approval: {key_id}. Contact an administrator to approve your key."
        )

class KeyRevokedError(Exception):
    """Raised when attempting to use an API key that has been revoked.

    API keys can be revoked by administrators or when a user is disabled.
    This error indicates the key was previously valid but is no longer active.

    Attributes:
        key_id: The public key identifier that was revoked.
    """

    def __init__(self, key_id: str) -> None:
        """Initialize key revoked error.

        Args:
            key_id: The public key identifier (key_xxxxx...).
        """
        self.key_id = key_id
        super().__init__(
            f"API key has been revoked: {key_id}. Contact an administrator if you believe this is an error."
        )