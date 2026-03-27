"""Domain interfaces for pullDB.

This module defines the protocols (interfaces) for the core infrastructure components.
These interfaces allow for dependency injection and swapping of implementations
(e.g., Real vs. Simulated).

HCA Compliance:
- Domain Layer: Defines interfaces (Ports).
- Infra Layer: Implements interfaces (Adapters).

HCA Layer: entities
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, ClassVar, Protocol

from pulldb.domain.models import (
    CommandResult,
    DBHost,
    DisallowedUser,
    Job,
    JobEvent,
    MaintenanceItems,
    User,
    UserDetail,
    UserNotification,
    UserRole,
    UserSummary,
)


class JobRepository(Protocol):
    """Protocol for job queue operations.

    Defines the interface for job lifecycle management including creation,
    status transitions, cancellation, and history queries. Implementations
    must enforce per-target exclusivity and FIFO ordering within status.

    All job state transitions are atomic and idempotent where possible.
    """

    # Constants for stale running job detection
    STALE_RUNNING_PROCESS_CHECK_COUNT: ClassVar[int]
    STALE_RUNNING_PROCESS_CHECK_DELAY_SECONDS: ClassVar[float]

    def enqueue_job(self, job: Job) -> str:
        """Insert new job into queue.

        Args:
            job: Job to enqueue (id may be empty, will be generated).

        Returns:
            UUID of the enqueued job.

        Raises:
            ValueError: If target already has active job on same host.
        """
        ...

    def create_claimed_job(
        self,
        *,
        job_id: str,
        owner_user_id: str,
        owner_username: str,
        owner_user_code: str,
        target: str,
        dbhost: str,
        origin: str,
    ) -> str:
        """Create a synthetic deployed job for an externally-managed database.

        Used by Database Discovery claim/assign. The job is inserted directly
        into 'deployed' status without going through the restore pipeline.

        Args:
            job_id: Pre-generated UUID.
            owner_user_id: UUID of the database owner.
            owner_username: Owner's username.
            owner_user_code: Owner's 6-char code.
            target: Database name on the target host.
            dbhost: Target MySQL host.
            origin: 'claim' or 'assign'.

        Returns:
            job_id of the created job.
        """
        ...

    def claim_next_job(self, worker_id: str | None = None) -> Job | None:
        """Atomically claim next queued job for processing.

        Args:
            worker_id: Optional identifier of the claiming worker.

        Returns:
            Claimed job with status='running', or None if queue empty.
        """
        ...

    def get_job_by_id(self, job_id: str) -> Job | None:
        """Get job by ID.

        Args:
            job_id: UUID of the job.

        Returns:
            Job if found, None otherwise.
        """
        ...

    def find_jobs_by_prefix(self, prefix: str, limit: int = 10) -> list[Job]:
        """Find jobs by ID prefix.

        Args:
            prefix: Job ID prefix to search for.
            limit: Maximum results to return.

        Returns:
            List of matching jobs, ordered by submitted_at descending.
        """
        ...

    def search_jobs(
        self, query: str, limit: int = 50, exact: bool = False
    ) -> list[Job]:
        """Search jobs by query string.

        Args:
            query: Search term (matches target, customer, or job_id).
            limit: Maximum results to return.
            exact: If True, require exact match; otherwise partial match.

        Returns:
            List of matching jobs.
        """
        ...

    def get_last_job_by_user_code(self, user_code: str) -> Job | None:
        """Get the most recent job submitted by a user.

        Args:
            user_code: Six-character user code.

        Returns:
            Most recent job if found, None otherwise.
        """
        ...

    def mark_job_deployed(self, job_id: str) -> bool:
        """Mark job as deployed (database live, user working with it).

        Args:
            job_id: UUID of the job to mark deployed.

        Returns:
            True if job was successfully marked deployed, False if job was
            no longer in expected status.
        """
        ...

    def mark_job_user_completed(self, job_id: str) -> None:
        """Mark deployed job as user-completed (moves to History).

        Args:
            job_id: UUID of the job to complete.
        """
        ...

    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail.

        Args:
            job_id: UUID of the job.
            error: Error message describing the failure.
        """
        ...

    def request_cancellation(self, job_id: str) -> bool:
        """Request cancellation of a job.

        Args:
            job_id: UUID of the job to cancel.

        Returns:
            True if cancellation was requested, False if job cannot be canceled.
        """
        ...

    def lock_for_restore(self, job_id: str, worker_id: str) -> bool:
        """Lock job for restore phase, preventing further cancellation.

        Atomically verifies can_cancel=True AND cancel_requested_at IS NULL,
        then sets can_cancel=False, locked_at, locked_by.

        The lock prevents both service and user interruption during Loading
        through Complete. Cleared by mark_job_deployed().

        Args:
            job_id: UUID of the job to lock.
            worker_id: Identifier of the worker locking the job.

        Returns:
            True if lock was acquired successfully, False if job was already
            canceled or cancel was requested (job should abort).
        """
        ...

    def mark_job_canceled(self, job_id: str, reason: str | None = None) -> None:
        """Mark job as canceled.

        Args:
            job_id: UUID of the job.
            reason: Optional cancellation reason for audit trail.
        """
        ...

    def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job.

        Args:
            job_id: UUID of the job.

        Returns:
            True if cancellation was requested.
        """
        ...

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running).

        Returns:
            List of jobs with status in ('queued', 'running').
        """
        ...

    def get_recent_jobs(
        self, limit: int = 100, offset: int = 0, statuses: list[str] | None = None
    ) -> list[Job]:
        """Get recent jobs (active + completed).

        Args:
            limit: Maximum results to return.
            offset: Number of jobs to skip for pagination.
            statuses: Optional status filter.

        Returns:
            List of jobs ordered by submitted_at descending.
        """
        ...

    def get_user_last_job(self, user_code: str) -> Job | None:
        """Get the most recently submitted job for a user.

        Args:
            user_code: Six-character user code.

        Returns:
            Most recent job if found, None otherwise.
        """
        ...

    def get_job_history(
        self,
        limit: int = 100,
        retention_days: int | None = None,
        user_code: str | None = None,
        target: str | None = None,
        dbhost: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """Get historical jobs with optional filtering.

        Args:
            limit: Maximum results to return.
            retention_days: Only include jobs newer than this.
            user_code: Filter by submitting user.
            target: Filter by target database.
            dbhost: Filter by database host.
            status: Filter by job status.

        Returns:
            List of matching jobs.
        """
        ...

    def list_jobs(
        self,
        limit: int = 20,
        active_only: bool = False,
        user_filter: str | None = None,
        dbhost: str | None = None,
        status_filter: str | None = None,
    ) -> list[Job]:
        """List jobs with flexible filtering.

        Args:
            limit: Maximum results to return.
            active_only: If True, only return active jobs.
            user_filter: Filter by user code or username.
            dbhost: Filter by database host.
            status_filter: Filter by job status.

        Returns:
            List of matching jobs.
        """
        ...

    def get_jobs_by_user(self, user_id: str) -> list[Job]:
        """Get all jobs for a user.

        Args:
            user_id: UUID of the user.

        Returns:
            List of jobs submitted by the user.
        """
        ...

    def find_orphaned_staging_databases(
        self, older_than_hours: int, dbhost: str | None = None
    ) -> list[Job]:
        """Find jobs with uncleaned staging databases.

        Args:
            older_than_hours: Only find jobs older than this.
            dbhost: Optional filter by database host.

        Returns:
            List of jobs with staging_cleaned=False.
        """
        ...

    def mark_staging_cleaned(self, job_id: str) -> None:
        """Mark staging database as cleaned.

        Args:
            job_id: UUID of the job.
        """
        ...

    def mark_job_staging_cleaned(self, job_id: str) -> None:
        """Mark a job's staging database as cleaned.

        Sets staging_cleaned_at timestamp to track that cleanup was performed.
        This prevents re-processing the same job in future cleanup runs.

        Args:
            job_id: UUID of job to mark as cleaned.
        """
        ...

    def mark_job_deleted(self, job_id: str, detail: str | None = None) -> None:
        """Mark job as deleted (soft delete complete).

        User-initiated deletion. Updates status to 'deleted' and sets
        completed_at if not already set. Used after databases are dropped.

        Args:
            job_id: UUID of job.
            detail: Optional detail about the deletion (stored in error_detail).
        """
        ...

    def mark_job_delete_failed(
        self, job_id: str, error_detail: str | None = None
    ) -> None:
        """Mark job as failed after exhausting delete retry attempts.

        Called when a job has been stuck in 'deleting' and has exceeded
        the maximum retry count. Sets status to 'failed' with an
        appropriate error message.

        Args:
            job_id: UUID of job.
            error_detail: Optional error detail.
        """
        ...

    def mark_stale_running_failed(
        self,
        job_id: str,
        worker_id: str | None = None,
        error_detail: str | None = None,
    ) -> bool:
        """Mark a stale running job as failed after verification.

        Called after confirming (via process list check) that a running job
        is actually stale and not just a long-running restore. Transitions
        the job from 'running' to 'failed' and logs the recovery event.

        Args:
            job_id: UUID of job to mark as failed.
            worker_id: ID of worker performing the recovery.
            error_detail: Optional custom error detail.

        Returns:
            True if job was marked failed, False if job not found or already
            transitioned to another state.
        """
        ...

    def mark_db_dropped(self, job_id: str) -> None:
        """Mark that the actual database was dropped from target host.

        Args:
            job_id: Job ID to mark.
        """
        ...

    def has_any_deployed_job_for_target(
        self, target: str, dbhost: str
    ) -> Job | None:
        """Check if ANY user has a deployed job for target+host.

        Unlike get_deployed_job_for_target() which is user-scoped, this checks
        across ALL users. Used for deletion safety - we must never drop a
        database that ANY user has deployed.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            Deployed Job if found (any user), None otherwise.
        """
        ...

    def has_any_locked_job_for_target(
        self, target: str, dbhost: str
    ) -> Job | None:
        """Check if ANY user has a locked job for target+host.

        Used for deletion safety - we should not drop a database that
        has been explicitly locked by any user.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            Locked Job if found (any user), None otherwise.
        """
        ...

    def get_job_completion_time(self, job_id: str) -> datetime | None:
        """Get the completion time of a job from events.

        Looks for the last terminal event (complete, failed, canceled).

        Args:
            job_id: Job UUID.

        Returns:
            Datetime of completion, or None if not found.
        """
        ...

    def get_old_terminal_jobs(self, dbhost: str, cutoff_date: datetime) -> list[Job]:
        """Get terminal jobs older than cutoff date for a specific host.

        Used by scheduled cleanup to find jobs whose staging databases
        may need cleanup.

        Args:
            dbhost: Database host to filter by.
            cutoff_date: Only return jobs completed before this date.

        Returns:
            List of Job instances in terminal state older than cutoff.
        """
        ...

    def get_expired_cleanup_candidates(self, grace_days: int) -> list[Job]:
        """Get jobs eligible for automatic database cleanup.

        Returns deployed jobs that are:
        - Past expiration + grace period
        - Not locked
        - Database not already dropped
        - Not superseded

        Args:
            grace_days: Additional days after expiry before cleanup.

        Returns:
            List of jobs whose databases can be dropped.
        """
        ...

    def get_expired_terminal_job_candidates(self, grace_days: int) -> list[Job]:
        """Get failed/canceled jobs eligible for automatic record cleanup.

        Returns terminal jobs (failed, canceled) that are:
        - Past expiration + grace period
        - Have expires_at set

        Args:
            grace_days: Additional days after expiry before cleanup.

        Returns:
            List of failed/canceled jobs past their expiration + grace period.
        """
        ...

    def purge_terminal_job(self, job_id: str) -> None:
        """Mark a failed/canceled job as deleted (record cleanup).

        Soft-deletes the job record so it leaves the active History view.

        Args:
            job_id: UUID of the terminal job to purge.
        """
        ...

    def check_target_exclusivity(self, target: str, dbhost: str) -> bool:
        """Check if target can accept new job.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            True if no active job exists for this target/host combination.
        """
        ...

    def count_active_jobs_for_user(self, user_id: str) -> int:
        """Count active jobs for a specific user.

        Args:
            user_id: UUID of the user.

        Returns:
            Count of active jobs.
        """
        ...

    def count_all_active_jobs(self) -> int:
        """Count all active jobs system-wide.

        Returns:
            Total count of active jobs.
        """
        ...

    def count_active_jobs_for_host(self, hostname: str) -> int:
        """Count active jobs (queued + running) for a specific host.

        Args:
            hostname: Database host hostname.

        Returns:
            Count of active jobs on this host.
        """
        ...

    def count_running_jobs_for_host(self, hostname: str) -> int:
        """Count running jobs for a specific host.

        Args:
            hostname: Database host hostname.

        Returns:
            Count of running jobs on this host.
        """
        ...

    def has_active_jobs_for_target(self, target: str, dbhost: str) -> bool:
        """Check if there are any active jobs for a target.

        Active jobs include queued, running, and canceling states.
        Used as a safety check before allowing new job submission.

        Args:
            target: Target database name.
            dbhost: Database host.

        Returns:
            True if active jobs exist, False otherwise.
        """
        ...

    def get_locked_by_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> "Job | None":
        """Find a locked job for a specific target+host+user combination.

        Used to check if a new restore should be blocked due to existing lock.

        Args:
            target: Target database name.
            dbhost: Database host.
            owner_user_id: User ID who owns the job.

        Returns:
            Locked Job if found, None otherwise.
        """
        ...

    def supersede_job(self, job_id: str, superseded_by_job_id: str) -> None:
        """Mark a job as superseded by a newer restore to the same target.

        Sets status to 'superseded' and records the superseding job ID.

        Args:
            job_id: Job ID being superseded.
            superseded_by_job_id: Job ID of the new restore.
        """
        ...

    def mark_job_canceling(self, job_id: str) -> bool:
        """Transition a running job to canceling state.

        Sets status to 'canceling' to indicate cancellation is in progress.
        Worker will detect this and stop at next checkpoint.

        Args:
            job_id: UUID of job.

        Returns:
            True if status was updated, False if job not in running state.
        """
        ...

    def get_cancel_requested_at(self, job_id: str) -> datetime | None:
        """Get the timestamp when cancellation was requested for a job.

        Args:
            job_id: UUID of job.

        Returns:
            Datetime when cancellation was requested, or None if not requested.
        """
        ...

    def get_current_operation(self, job_id: str) -> str | None:
        """Get user-friendly current operation string for a job.

        Queries the latest job event and derives a human-readable operation
        string (e.g., "Downloading(45%)", "Restoring", "Queued").

        Args:
            job_id: UUID of job.

        Returns:
            Human-readable operation string, or None if job not found.
        """
        ...

    def append_job_event(
        self, job_id: str, event_type: str, detail: str | None = None
    ) -> None:
        """Append event to job audit log.

        Args:
            job_id: UUID of job.
            event_type: Type of event.
            detail: Optional detail message or JSON payload.
        """
        ...

    def get_job_events(
        self, job_id: str, since_id: int | None = None
    ) -> list[JobEvent]:
        """Get all events for a job, optionally since a specific event ID.

        Args:
            job_id: UUID of job.
            since_id: Optional event ID to fetch events after (exclusive).

        Returns:
            List of events ordered by logged_at.
        """
        ...

    def prune_job_events(self, retention_days: int = 90) -> int:
        """Delete job events older than retention period.

        Args:
            retention_days: Days to retain events.

        Returns:
            Number of events deleted.
        """
        ...

    def find_job_by_staging_prefix(
        self, target: str, dbhost: str, job_id_prefix: str
    ) -> Job | None:
        """Find a job by its staging database prefix.

        Used by scheduled cleanup to match staging databases to jobs.

        Args:
            target: Target database name.
            dbhost: Database host.
            job_id_prefix: First 12 characters of job UUID.

        Returns:
            Job if found, None otherwise.
        """
        ...

    def set_job_expiration(self, job_id: str, expires_at: datetime) -> None:
        """Set expiration date for a job's database.

        Args:
            job_id: Job ID to update.
            expires_at: New expiration timestamp.
        """
        ...

    def lock_job(self, job_id: str, locked_by: str) -> bool:
        """Lock a job's database to protect from cleanup and overwrites.

        Args:
            job_id: Job ID to lock.
            locked_by: Username of user locking the database.

        Returns:
            True if lock was set, False if job not found or already locked.
        """
        ...

    def unlock_job(self, job_id: str) -> bool:
        """Unlock a job's database.

        Args:
            job_id: Job ID to unlock.

        Returns:
            True if unlocked, False if job not found or wasn't locked.
        """
        ...

    def get_deployed_job_for_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Get the deployed job for a target+host+user if one exists.

        Used to check if a database already exists before allowing a new restore.
        A deployed job means the database is live and in use.

        Args:
            target: Target database name.
            dbhost: Database host.
            owner_user_id: User ID who owns the job.

        Returns:
            Deployed Job if found, None otherwise.
        """
        ...

    def get_latest_completed_job_for_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Get the most recent completed job for a target+host+user.

        Used for supersession - finding the job to mark as superseded when
        a new restore to the same target is submitted.

        Args:
            target: Target database name.
            dbhost: Database host.
            owner_user_id: User ID who owns the job.

        Returns:
            Most recent completed Job if found, None otherwise.
        """
        ...

    def get_maintenance_items(
        self, user_id: str, notice_days: int, grace_days: int
    ) -> "MaintenanceItems":
        """Get maintenance items for a user's daily modal.

        Returns jobs grouped by maintenance status: expired and expiring.
        Locked databases are excluded — they are already protected from cleanup.

        Args:
            user_id: User ID to get items for.
            notice_days: Days before expiry to show in "expiring" section.
            grace_days: Additional grace days after expiry (for reference).

        Returns:
            MaintenanceItems with expired and expiring job lists.
        """
        ...


class S3Client(Protocol):
    """Protocol for S3 operations.

    Minimal interface for backup discovery. Real implementation uses boto3,
    simulation uses in-memory MockS3Client.
    """

    def list_keys(
        self, bucket: str, prefix: str, profile: str | None = None
    ) -> list[str]:
        """Return keys under prefix (non-recursive).

        Args:
            bucket: S3 bucket name.
            prefix: Prefix to filter by.
            profile: Optional AWS profile name.

        Returns:
            List of object keys.
        """
        ...

    def head_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> Any:
        """Return object metadata (HEAD request).

        Args:
            bucket: S3 bucket name.
            key: Object key.
            profile: Optional AWS profile name.

        Returns:
            Object metadata including ContentLength.
        """
        ...

    def get_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> Any:
        """Return object with streaming body.

        Args:
            bucket: S3 bucket name.
            key: Object key.
            profile: Optional AWS profile name.

        Returns:
            Object response with Body for streaming.
        """
        ...

class ProcessExecutor(Protocol):
    """Protocol for subprocess execution.

    Abstracts process spawning for myloader and other external tools.
    Enables simulation without actual subprocess calls.
    """

    def run_command(self, command: list[str], env: dict[str, str] | None = None) -> int:
        """Run command synchronously and return exit code.

        Args:
            command: Command and arguments as list.
            env: Optional environment variables to set.

        Returns:
            Process exit code (0 for success).
        """
        ...

    def run_command_streaming(
        self,
        command: Sequence[str],
        line_callback: Callable[[str], None],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
        abort_check: Callable[[], bool] | None = None,
        abort_check_interval: int = 100,
    ) -> CommandResult:
        """Execute command with streaming output.

        Streams merged stdout/stderr line-by-line to callback. Supports
        timeout and periodic abort checking for cancellation.

        Args:
            command: Command and arguments as sequence.
            line_callback: Called with each output line.
            env: Optional environment variables.
            timeout: Maximum execution time in seconds.
            cwd: Working directory for the process.
            abort_check: Callable returning True to abort.
            abort_check_interval: Lines between abort checks.

        Returns:
            CommandResult with exit_code, timed_out, aborted flags.
        """
        ...


class UserRepository(Protocol):
    """Protocol for user management operations.

    Handles user CRUD, role management, and manager relationships.
    User identity is UUID-based; usernames are for human reference.
    """

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username.

        Args:
            username: Unix-style username.

        Returns:
            User if found, None otherwise.
        """
        ...

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by unique identifier.

        Args:
            user_id: UUID of the user.

        Returns:
            User if found, None otherwise.
        """
        ...

    def create_user(self, username: str, user_code: str, manager_id: str | None = None) -> User:
        """Create new user with generated UUID.

        Args:
            username: Unix-style username.
            user_code: 6-character unique code for display.
            manager_id: Optional UUID of managing user.

        Returns:
            Newly created User object.
        """
        ...

    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create new one.

        For auto-provisioning on first authentication.

        Args:
            username: Unix-style username.

        Returns:
            Existing or newly created User.
        """
        ...

    def generate_user_code(self, username: str) -> str:
        """Generate unique 6-character user code.

        Args:
            username: Username to derive code from.

        Returns:
            Unique 6-character code.
        """
        ...

    def check_user_code_exists(self, user_code: str) -> bool:
        """Check if user_code already exists.

        Args:
            user_code: Code to check.

        Returns:
            True if code is taken.
        """
        ...

    def get_users_with_job_counts(self) -> list[UserSummary]:
        """Get all users with their active job counts.

        Returns:
            List of UserSummary with aggregated stats.
        """
        ...

    def enable_user(self, username: str) -> None:
        """Enable a disabled user.

        Args:
            username: Username to enable.
        """
        ...

    def disable_user(self, username: str) -> None:
        """Disable a user (soft delete).

        Preferred over delete for users with job history.

        Args:
            username: Username to disable.
        """
        ...

    def get_user_detail(self, username: str) -> UserDetail | None:
        """Get detailed user statistics.

        Includes job counts, manager info, role details.

        Args:
            username: Username to look up.

        Returns:
            UserDetail if found, None otherwise.
        """
        ...

    def get_users_managed_by(self, manager_id: str) -> list[User]:
        """Get all users managed by a specific manager.

        Args:
            manager_id: UUID of the manager.

        Returns:
            List of users under this manager.
        """
        ...

    def set_user_manager(self, user_id: str, manager_id: str | None) -> None:
        """Set or remove the manager for a user.

        Args:
            user_id: UUID of the user to update.
            manager_id: UUID of new manager, or None to remove.
        """
        ...

    def update_user_role(self, user_id: str, role: UserRole) -> None:
        """Update a user's role.

        Args:
            user_id: UUID of the user.
            role: New role to assign.
        """
        ...

    def update_user_max_active_jobs(self, user_id: str, max_active_jobs: int | None) -> None:
        """Update a user's max active jobs limit.

        Args:
            user_id: UUID of the user.
            max_active_jobs: New limit (None = system default, 0 = unlimited).
        """
        ...

    def delete_user(self, user_id: str) -> dict[str, int]:
        """Delete a user and all related records.
        
        Deletes the user and cascades to:
        - sessions (CASCADE)
        - auth_credentials (CASCADE)
        - user_hosts (CASCADE)
        - manager relationships: Sets manager_id to NULL for managed users
        
        IMPORTANT: Users with ANY jobs cannot be deleted (preserves history).
        Use disable_user() instead for users with job history.
        
        Args:
            user_id: The user ID to delete.
            
        Returns:
            Dict with counts of affected records:
            {
                "managed_users_updated": int,
                "user_deleted": 1
            }
            
        Raises:
            ValueError: If user not found or has any jobs.
        """
        ...

    def create_user_with_code(self, username: str) -> User:
        """Create new user with auto-generated user_code.

        Unlike get_or_create_user, this method does NOT check for existing users.
        It always attempts to create a new user.

        Args:
            username: Username for the new user.

        Returns:
            Newly created User instance.

        Raises:
            ValueError: If user_code cannot be generated or username invalid.
        """
        ...

    def search_users(self, query: str, limit: int = 15) -> list[User]:
        """Search for users by username or user_code.

        Args:
            query: Search string.
            limit: Maximum number of results to return.

        Returns:
            List of matching User instances, ordered by username.
        """
        ...

    def list_users(self) -> list[User]:
        """Get all users.

        Returns:
            List of User instances.
        """
        ...

    def list_users_paginated(self, offset: int = 0, limit: int = 100) -> list[User]:
        """Get a page of users ordered by username.

        Args:
            offset: Number of rows to skip (0-based).
            limit: Maximum number of rows to return.

        Returns:
            List of User instances for the requested page.
        """
        ...

    def set_last_maintenance_ack(self, user_id: str, ack_date: datetime) -> None:
        """Set last maintenance acknowledgment date for a user.

        Args:
            user_id: User UUID.
            ack_date: Date to record (typically today's date).
        """
        ...

    def needs_maintenance_ack(self, user_id: str) -> bool:
        """Check if user needs to acknowledge maintenance modal today.

        Args:
            user_id: User UUID.

        Returns:
            True if user hasn't acknowledged today, False otherwise.
        """
        ...

    def create_notification(
        self,
        user_id: str,
        notification_type: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Create an inbox notification for a user.

        Args:
            user_id: Recipient user UUID.
            notification_type: Type key (e.g. 'ownership_claimed').
            message: Human-readable message.
            context: Optional structured data stored as JSON.

        Returns:
            Notification UUID.
        """
        ...

    def get_pending_notifications(self, user_id: str) -> list[UserNotification]:
        """Return all unread notifications for a user.

        Args:
            user_id: Recipient user UUID.

        Returns:
            List of unread UserNotification instances, oldest first.
        """
        ...

    def mark_notifications_read(self, user_id: str) -> None:
        """Mark all unread notifications for a user as read.

        Args:
            user_id: Recipient user UUID.
        """
        ...


class HostRepository(Protocol):
    """Protocol for database host configuration.

    Manages MySQL target hosts, their connection credentials,
    and job capacity limits.
    """

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        """Get host configuration by hostname.

        Args:
            hostname: Fully qualified hostname.

        Returns:
            DBHost if found, None otherwise.
        """
        ...

    def get_host_by_alias(self, alias: str) -> DBHost | None:
        """Get host configuration by short alias.

        Args:
            alias: Short alias (e.g., 'prod', 'staging').

        Returns:
            DBHost if found, None otherwise.
        """
        ...

    def resolve_hostname(self, name: str) -> str | None:
        """Resolve a hostname or alias to canonical hostname.

        Accepts either full hostname or alias.

        Args:
            name: Hostname or alias to resolve.

        Returns:
            Canonical hostname if found, None otherwise.
        """
        ...

    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled database hosts.

        Returns:
            List of hosts where enabled=True.
        """
        ...

    def get_all_hosts(self) -> list[DBHost]:
        """Get all database hosts.

        Returns:
            List of all hosts regardless of enabled status.
        """
        ...

    def get_host_credentials(self, hostname: str) -> Any:
        """Get resolved MySQL credentials for host.

        Fetches from AWS Secrets Manager using credential_ref.

        Args:
            hostname: Host to get credentials for.

        Returns:
            Credentials dict with host, port, user, password.
        """
        ...

    def check_host_running_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for running jobs.

        Worker-side enforcement against max_running_jobs.

        Args:
            hostname: Host to check.

        Returns:
            True if running jobs < max_running_jobs.
        """
        ...

    def check_host_active_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for active jobs.

        API-side enforcement against max_active_jobs.

        Args:
            hostname: Host to check.

        Returns:
            True if active jobs < max_active_jobs.
        """
        ...

    def update_host_limits(
        self, hostname: str, max_active_jobs: int, max_running_jobs: int
    ) -> None:
        """Update job limits for a host.

        Args:
            hostname: Host to update.
            max_active_jobs: New max active jobs limit.
            max_running_jobs: New max concurrent running jobs.
        """
        ...

    def add_host(
        self,
        hostname: str,
        max_concurrent: int,
        credential_ref: str | None,
        *,
        host_id: str | None = None,
        host_alias: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Add a new database host.

        Args:
            hostname: Hostname of the database server.
            max_concurrent: Maximum concurrent running jobs.
            credential_ref: AWS Secrets Manager reference.
            host_id: Optional UUID (generated if not provided).
            host_alias: Optional short alias.
            max_running_jobs: Optional max running jobs.
            max_active_jobs: Optional max active jobs (default 10).
        """
        ...

    def update_host_config(
        self,
        host_id: str,
        *,
        host_alias: str | None = None,
        credential_ref: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Update an existing host's configuration.

        Only provided arguments are updated.

        Args:
            host_id: UUID of the host to update.
            host_alias: New alias if changing.
            credential_ref: New credential reference if changing.
            max_running_jobs: New max running jobs if changing.
            max_active_jobs: New max active jobs if changing.
        """
        ...

    def delete_host(self, hostname: str) -> None:
        """Delete a database host.

        Args:
            hostname: Hostname to delete.

        Raises:
            ValueError: If host not found.
        """
        ...

    def enable_host(self, hostname: str) -> None:
        """Enable a database host.

        Args:
            hostname: Host to enable.
        """
        ...

    def disable_host(self, hostname: str) -> None:
        """Disable a database host.

        Disabled hosts cannot accept new jobs.

        Args:
            hostname: Host to disable.
        """
        ...

    def get_host_by_id(self, host_id: str) -> DBHost | None:
        """Get host configuration by ID.

        Args:
            host_id: UUID string of the host.

        Returns:
            DBHost instance if found, None otherwise.
        """
        ...

    def search_hosts(self, query: str, limit: int = 10) -> list[DBHost]:
        """Search for hosts by hostname or alias.

        Args:
            query: Search string.
            limit: Maximum number of results to return.

        Returns:
            List of matching DBHost instances, ordered by hostname.
        """
        ...

    def get_host_credentials_for_maintenance(self, hostname: str) -> Any:
        """Get resolved MySQL credentials for maintenance operations.

        Similar to get_host_credentials but allows disabled hosts.
        Use for cleanup, deletion, and staging operations that need
        to work on disabled hosts.

        Args:
            hostname: Hostname to get credentials for.

        Returns:
            Resolved credentials instance.

        Raises:
            ValueError: If host not found (deleted from db_hosts).
        """
        ...

    def is_staging_db_active(
        self,
        hostname: str,
        staging_name: str,
        check_count: int = 3,
        check_delay_seconds: float = 2.0,
    ) -> bool:
        """Check if a staging database has active MySQL processes.

        Performs multiple SHOW PROCESSLIST checks to verify if a restore is
        still actively running on the staging database. This prevents false
        positives from treating long-running restores as stale jobs.

        Args:
            hostname: Database host to check.
            staging_name: Staging database name to look for in processlist.
            check_count: Number of times to check (default 3).
            check_delay_seconds: Delay between checks in seconds (default 2.0).

        Returns:
            True if any process is using the staging database, False otherwise.
        """
        ...

    def list_hosts(self) -> list[DBHost]:
        """Get all hosts (alias for get_all_hosts).

        Provided for API consistency.

        Returns:
            List of all DBHost instances.
        """
        ...

    def database_exists(self, hostname: str, db_name: str) -> bool:
        """Check if a database exists on the specified host.

        Uses ``SHOW DATABASES LIKE`` to determine existence.

        Args:
            hostname: Database host to check.
            db_name: Database name to look for.

        Returns:
            True if the database exists on the host, False otherwise.

        Raises:
            Exception: If the connection to the host fails.
        """
        ...

    def get_pulldb_metadata_owner(
        self, hostname: str, db_name: str
    ) -> tuple[bool, str | None, str | None]:
        """Check if a database has a pullDB metadata table and get the owner.

        Args:
            hostname: Database host to check.
            db_name: Database name to inspect.

        Returns:
            Tuple of ``(has_pulldb_table, owner_user_id, owner_user_code)``.
            If no pullDB table exists, returns ``(False, None, None)``.
        """
        ...


class SettingsRepository(Protocol):
    """Protocol for system settings management.

    Key-value store for runtime configuration. Settings include
    global job limits, feature flags, and operational parameters.
    """

    def get_setting(self, key: str) -> str | None:
        """Get setting value by key.

        Args:
            key: Setting key name.

        Returns:
            Setting value if exists, None otherwise.
        """
        ...

    def get_setting_required(self, key: str) -> str:
        """Get required setting value.

        Args:
            key: Setting key name.

        Returns:
            Setting value.

        Raises:
            KeyError: If setting not found.
        """
        ...

    def get_max_active_jobs_per_user(self) -> int:
        """Get maximum active jobs allowed per user.

        Returns:
            Default limit for user active jobs.
        """
        ...

    def get_max_active_jobs_global(self) -> int:
        """Get maximum active jobs allowed globally.

        Returns:
            System-wide active jobs limit.
        """
        ...

    def get_all_settings(self) -> dict[str, str]:
        """Get all settings as a dictionary.

        Returns:
            Dict mapping setting keys to values.
        """
        ...

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Set a setting value.

        Creates or updates the setting.

        Args:
            key: Setting key name.
            value: Setting value.
            description: Optional human-readable description.
        """
        ...

    def delete_setting(self, key: str) -> bool:
        """Delete a setting.

        Args:
            key: Setting key to delete.

        Returns:
            True if deleted, False if not found.
        """
        ...

    def get(self, key: str) -> str | None:
        """Alias for get_setting().

        Args:
            key: Setting key name.

        Returns:
            Setting value if exists, None otherwise.
        """
        ...

    def get_staging_retention_days(self) -> int:
        """Get number of days before staging databases are eligible for cleanup.

        Returns:
            Retention days. 7 is the default. 0 means cleanup is disabled.
        """
        ...

    def get_cleanup_grace_days(self) -> int:
        """Get days after expiry before automatic cleanup.

        Returns:
            Number of days. Default: 7.
        """
        ...

    def get_expiring_warning_days(self) -> int:
        """Get days before expiry to show yellow 'will expire soon' warning.

        Returns:
            Number of days. Default: 7.
        """
        ...

    def get_retention_options(
        self, include_now: bool = False
    ) -> list[tuple[str, str]]:
        """Get retention dropdown options based on current settings.

        Args:
            include_now: Whether to include "Now" (immediate removal) option.

        Returns:
            List of (value, label) tuples for dropdown options.
        """
        ...

    def get_all_settings_with_metadata(self) -> list[dict[str, str | None]]:
        """Get all settings with metadata (key, value, description, updated_at).

        Returns:
            List of setting dictionaries.
        """
        ...

    def get_default_retention_days(self) -> int:
        """Get default retention days for new restores.

        Returns:
            Number of days. Default: 7.
        """
        ...

    def get_max_retention_days(self) -> int:
        """Get maximum retention days allowed.

        Returns:
            Number of days. Default: 180.
        """
        ...

    def get_job_log_retention_days(self) -> int:
        """Get days before job logs are eligible for pruning.

        Returns:
            Number of days. Default: 30. 0 means disabled.
        """
        ...

    def get_jobs_refresh_interval(self) -> int:
        """Get auto-refresh interval for the jobs page.

        Returns:
            Interval in seconds. Default: 5. 0 means disabled.
        """
        ...


# ============================================================================
# Authentication & Authorization Protocols
# ============================================================================


class AuthRepository(Protocol):
    """Protocol for authentication repository.

    Manages password hashes, TOTP secrets, password reset state,
    and API key authentication.
    """

    def get_password_hash(self, user_id: str) -> str | None:
        """Get stored password hash for user.

        Args:
            user_id: UUID of the user.

        Returns:
            bcrypt password hash, or None if no password set.
        """
        ...

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        """Set password hash for user.

        Args:
            user_id: UUID of the user.
            password_hash: bcrypt hash to store.
        """
        ...

    def has_password(self, user_id: str) -> bool:
        """Check if user has a password set.

        Args:
            user_id: UUID of the user.

        Returns:
            True if password is set.
        """
        ...

    def mark_password_reset(self, user_id: str) -> None:
        """Mark user as requiring password reset on next login.

        Args:
            user_id: UUID of the user.
        """
        ...

    def clear_password_reset(self, user_id: str) -> None:
        """Clear password reset requirement.

        Args:
            user_id: UUID of the user.
        """
        ...

    def is_password_reset_required(self, user_id: str) -> bool:
        """Check if user must reset password.

        Args:
            user_id: UUID of the user.

        Returns:
            True if password reset is required.
        """
        ...

    def get_password_reset_at(self, user_id: str) -> datetime | None:
        """Get timestamp when password reset was flagged.

        Args:
            user_id: UUID of the user.

        Returns:
            Datetime when reset was required, or None.
        """
        ...

    def get_totp_secret(self, user_id: str) -> str | None:
        """Get TOTP secret for user.

        Args:
            user_id: UUID of the user.

        Returns:
            Base32-encoded TOTP secret, or None if not enabled.
        """
        ...

    def set_totp_secret(self, user_id: str, totp_secret: str) -> None:
        """Set TOTP secret for user.

        Args:
            user_id: UUID of the user.
            totp_secret: Base32-encoded secret.
        """
        ...

    def disable_totp(self, user_id: str) -> None:
        """Disable TOTP for user.

        Args:
            user_id: UUID of the user.
        """
        ...

    def is_totp_enabled(self, user_id: str) -> bool:
        """Check if TOTP is enabled for user.

        Args:
            user_id: UUID of the user.

        Returns:
            True if TOTP is configured.
        """
        ...

    def create_api_key(
        self,
        user_id: str,
        name: str | None = None,
        host_name: str | None = None,
        created_from_ip: str | None = None,
        auto_approve: bool = False,
        approved_by: str | None = None,
    ) -> tuple[str, str]:
        """Create new API key for user.

        Generates key_id and secret internally. The secret is only returned
        once and cannot be retrieved later.

        Args:
            user_id: UUID of the user.
            name: Optional friendly name for the key (auto-generated if not provided).
            host_name: Hostname where key was requested.
            created_from_ip: IP address of the request.
            auto_approve: If True, automatically approve the key.
            approved_by: User ID of admin approving (required if auto_approve=True).

        Returns:
            Tuple of (key_id, secret) - secret is only returned once!
        """
        ...

    def verify_api_key(self, key_id: str, secret: str) -> str | None:
        """Verify API key and return user_id if valid.

        Args:
            key_id: API key identifier.
            secret: API secret to verify.

        Returns:
            user_id if key is valid and not expired, None otherwise.
        """
        ...

    def get_api_key_user(self, key_id: str) -> str | None:
        """Get user_id for an API key.

        Args:
            key_id: API key identifier.

        Returns:
            user_id if key exists, None otherwise.
        """
        ...

    def get_api_key_secret(self, key_id: str) -> str | None:
        """Get the plaintext secret for an API key (for HMAC verification).

        Args:
            key_id: The public key identifier.

        Returns:
            Plaintext secret if key is active and approved, None if not found.
        """
        ...

    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke (soft-delete) an API key.

        Args:
            key_id: API key identifier.

        Returns:
            True if revoked, False if not found.
        """
        ...

    def get_api_keys_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Get all API keys for a user.

        Args:
            user_id: UUID of the user.

        Returns:
            List of API key info dicts.
        """
        ...

    def get_pending_api_keys(self) -> list[dict[str, Any]]:
        """Get all API keys pending admin approval.

        Returns:
            List of pending key dicts with user info.
        """
        ...

    def approve_api_key(self, key_id: str, approved_by: str) -> bool:
        """Approve an API key (make it active and usable).

        Args:
            key_id: The public key identifier to approve.
            approved_by: User ID of the admin approving the key.

        Returns:
            True if key was approved, False if not found or already approved.
        """
        ...

    def get_api_key_info(self, key_id: str) -> dict[str, Any] | None:
        """Get full info about an API key.

        Args:
            key_id: The public key identifier.

        Returns:
            Dict with key info including username, or None if not found.
        """
        ...

    def get_all_api_keys(
        self, include_inactive: bool = False, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all API keys with filtering options.

        Args:
            include_inactive: If True, include revoked keys.
            user_id: If provided, filter to keys for this user only.

        Returns:
            List of key info dicts with user details.
        """
        ...


class DisallowedUserRepository(Protocol):
    """Protocol for disallowed username checks.

    Manages database entries that extend the hardcoded disallowed list.
    """

    def get_all(self) -> list[DisallowedUser]:
        """Get all disallowed usernames from database.

        Returns:
            List of DisallowedUser entries, sorted by username.
        """
        ...

    def exists(self, username: str) -> bool:
        """Check if username is in database disallowed list.

        Args:
            username: Username to check (case-insensitive).

        Returns:
            True if username is disallowed in database.
        """
        ...

    def add(
        self,
        username: str,
        reason: str | None = None,
        created_by: str | None = None,
    ) -> bool:
        """Add a username to the disallowed list.

        Args:
            username: Username to disallow (stored lowercase).
            reason: Optional reason for disallowing.
            created_by: User ID who added this entry.

        Returns:
            True if added, False if already exists.
        """
        ...

    def remove(self, username: str) -> tuple[bool, str]:
        """Remove a username from the disallowed list.

        Only non-hardcoded entries can be removed.

        Args:
            username: Username to remove.

        Returns:
            Tuple of (success, message) explaining the result.
        """
        ...


class AuditRepository(Protocol):
    """Protocol for audit logging.

    Records manager/admin actions for transparency and compliance.
    """

    def log_action(
        self,
        actor_user_id: str,
        action: str,
        target_user_id: str | None = None,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Record an audit log entry.

        Args:
            actor_user_id: User ID of who performed the action.
            action: Action type (e.g., 'submit_for_user', 'create_user').
            target_user_id: User ID affected (if applicable).
            detail: Human-readable detail of the action.
            context: Additional JSON context data.

        Returns:
            Audit log ID (UUID).
        """
        ...

    def get_audit_logs(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve audit log entries with optional filtering.

        Args:
            actor_user_id: Filter by actor (who did the action).
            target_user_id: Filter by target user (who was affected).
            action: Filter by action type.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of audit log dictionaries.
        """
        ...

