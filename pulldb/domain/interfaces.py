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
from typing import Any, Protocol

from pulldb.domain.models import (
    CommandResult,
    DBHost,
    Job,
    User,
    UserDetail,
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

    def mark_job_deployed(self, job_id: str) -> None:
        """Mark job as deployed (database live, user working with it).

        Args:
            job_id: UUID of the job to mark deployed.
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
        self, limit: int = 100, statuses: list[str] | None = None
    ) -> list[Job]:
        """Get recent jobs (active + completed).

        Args:
            limit: Maximum results to return.
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

class AuthRepository(Protocol):
    """Protocol for authentication operations.

    Manages password hashes and authentication state for users.
    """

    def get_password_hash(self, user_id: str) -> str | None:
        """Get stored password hash for user.

        Args:
            user_id: UUID of the user.

        Returns:
            Bcrypt password hash if set, None if user has no password.
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
        host_id: str | None = None,
        host_alias: str | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Add a new database host.

        Args:
            hostname: Hostname of the database server.
            max_concurrent: Maximum concurrent running jobs.
            credential_ref: AWS Secrets Manager reference.
            host_id: Optional UUID (generated if not provided).
            host_alias: Optional short alias.
            max_active_jobs: Optional max active jobs (default 10).
        """
        ...

    def update_host_config(
        self,
        host_id: str,
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
