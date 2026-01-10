"""Domain interfaces for pullDB.

This module defines the protocols (interfaces) for the core infrastructure components.
These interfaces allow for dependency injection and swapping of implementations
(e.g., Real vs. Simulated).

HCA Compliance:
- Domain Layer: Defines interfaces (Ports).
- Infra Layer: Implements interfaces (Adapters).
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
    """Protocol for job queue operations."""

    def enqueue_job(self, job: Job) -> str:
        """Insert new job into queue."""
        ...

    def claim_next_job(self, worker_id: str | None = None) -> Job | None:
        """Atomically claim next queued job for processing."""
        ...

    def get_job_by_id(self, job_id: str) -> Job | None:
        """Get job by ID."""
        ...

    def find_jobs_by_prefix(self, prefix: str, limit: int = 10) -> list[Job]:
        """Find jobs by ID prefix."""
        ...

    def search_jobs(
        self, query: str, limit: int = 50, exact: bool = False
    ) -> list[Job]:
        """Search jobs by query string."""
        ...

    def get_last_job_by_user_code(self, user_code: str) -> Job | None:
        """Get the most recent job submitted by a user."""
        ...

    def mark_job_deployed(self, job_id: str) -> None:
        """Mark job as deployed (database live, user working with it)."""
        ...

    def mark_job_user_completed(self, job_id: str) -> None:
        """Mark deployed job as user-completed (moves to History)."""
        ...

    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail."""
        ...

    def request_cancellation(self, job_id: str) -> bool:
        """Request cancellation of a job."""
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
        """Mark job as canceled."""
        ...

    def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job."""
        ...

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running)."""
        ...

    def get_recent_jobs(
        self, limit: int = 100, statuses: list[str] | None = None
    ) -> list[Job]:
        """Get recent jobs (active + completed)."""
        ...

    def get_user_last_job(self, user_code: str) -> Job | None:
        """Get the most recently submitted job for a user."""
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
        """Get historical jobs with optional filtering."""
        ...

    def list_jobs(
        self,
        limit: int = 20,
        active_only: bool = False,
        user_filter: str | None = None,
        dbhost: str | None = None,
        status_filter: str | None = None,
    ) -> list[Job]:
        """List jobs with flexible filtering."""
        ...

    def get_jobs_by_user(self, user_id: str) -> list[Job]:
        """Get all jobs for a user."""
        ...

    def find_orphaned_staging_databases(
        self, older_than_hours: int, dbhost: str | None = None
    ) -> list[Job]:
        """Find jobs with uncleaned staging databases."""
        ...

    def mark_staging_cleaned(self, job_id: str) -> None:
        """Mark staging database as cleaned."""
        ...

    def check_target_exclusivity(self, target: str, dbhost: str) -> bool:
        """Check if target can accept new job."""
        ...

    def count_active_jobs_for_user(self, user_id: str) -> int:
        """Count active jobs for a specific user."""
        ...

    def count_all_active_jobs(self) -> int:
        """Count all active jobs system-wide."""
        ...

    def count_active_jobs_for_host(self, hostname: str) -> int:
        """Count active jobs (queued + running) for a specific host."""
        ...

    def count_running_jobs_for_host(self, hostname: str) -> int:
        """Count running jobs for a specific host."""
        ...

class AuthRepository(Protocol):
    """Protocol for authentication operations."""
    
    def get_password_hash(self, user_id: str) -> str | None:
        """Get stored password hash for user."""
        ...

class S3Client(Protocol):
    """Protocol for S3 operations."""

    def list_keys(
        self, bucket: str, prefix: str, profile: str | None = None
    ) -> list[str]:
        """Return keys under prefix (non recursive)."""
        ...

    def head_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> Any:
        """Return object metadata (HEAD)."""
        ...

    def get_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> Any:
        """Return object (streaming body)."""
        ...

class ProcessExecutor(Protocol):
    """Protocol for subprocess execution."""

    def run_command(self, command: list[str], env: dict[str, str] | None = None) -> int:
        """Run command and return exit code."""
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
        """Execute command, streaming merged stdout/stderr to callback."""
        ...


class UserRepository(Protocol):
    """Protocol for user operations."""

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username."""
        ...

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by user_id."""
        ...

    def create_user(self, username: str, user_code: str, manager_id: str | None = None) -> User:
        """Create new user with generated UUID and optional manager assignment."""
        ...

    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create new one."""
        ...

    def generate_user_code(self, username: str) -> str:
        """Generate unique 6-character user code."""
        ...

    def check_user_code_exists(self, user_code: str) -> bool:
        """Check if user_code already exists."""
        ...

    def get_users_with_job_counts(self) -> list[UserSummary]:
        """Get users with active job counts."""
        ...

    def enable_user(self, username: str) -> None:
        """Enable a user."""
        ...

    def disable_user(self, username: str) -> None:
        """Disable a user."""
        ...

    def get_user_detail(self, username: str) -> UserDetail | None:
        """Get detailed user statistics."""
        ...

    def get_users_managed_by(self, manager_id: str) -> list[User]:
        """Get all users managed by a specific manager."""
        ...

    def set_user_manager(self, user_id: str, manager_id: str | None) -> None:
        """Set or remove the manager for a user."""
        ...

    def update_user_role(self, user_id: str, role: UserRole) -> None:
        """Update a user's role."""
        ...

    def update_user_max_active_jobs(self, user_id: str, max_active_jobs: int | None) -> None:
        """Update a user's max active jobs limit.
        
        Args:
            user_id: The user ID to update.
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
    """Protocol for database host operations."""

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        """Get host configuration by hostname."""
        ...

    def get_host_by_alias(self, alias: str) -> DBHost | None:
        """Get host configuration by alias."""
        ...

    def resolve_hostname(self, name: str) -> str | None:
        """Resolve a hostname or alias to the canonical hostname."""
        ...

    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled database hosts."""
        ...

    def get_all_hosts(self) -> list[DBHost]:
        """Get all database hosts."""
        ...

    def get_host_credentials(self, hostname: str) -> Any:
        """Get resolved MySQL credentials for host."""
        ...

    def check_host_running_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for running jobs (worker enforcement)."""
        ...

    def check_host_active_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for active jobs (API enforcement)."""
        ...

    def update_host_limits(
        self, hostname: str, max_active_jobs: int, max_running_jobs: int
    ) -> None:
        """Update job limits for a host."""
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
            max_concurrent: Maximum concurrent running jobs allowed.
            credential_ref: AWS Secrets Manager reference.
            host_id: Optional UUID (generated if not provided).
            host_alias: Optional short alias for the host.
            max_active_jobs: Optional max active jobs (defaults to 10).
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
        
        Args:
            host_id: UUID of the host to update.
            host_alias: New alias (if changing).
            credential_ref: New credential reference (if changing).
            max_running_jobs: New max running jobs (if changing).
            max_active_jobs: New max active jobs (if changing).
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
        """Enable a database host."""
        ...

    def disable_host(self, hostname: str) -> None:
        """Disable a database host."""
        ...


class SettingsRepository(Protocol):
    """Protocol for settings operations."""

    def get_setting(self, key: str) -> str | None:
        """Get setting value by key."""
        ...

    def get_setting_required(self, key: str) -> str:
        """Get required setting value."""
        ...

    def get_max_active_jobs_per_user(self) -> int:
        """Get maximum active jobs allowed per user."""
        ...

    def get_max_active_jobs_global(self) -> int:
        """Get maximum active jobs allowed globally."""
        ...

    def get_all_settings(self) -> dict[str, str]:
        """Get all settings as a dictionary."""
        ...

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Set a setting value."""
        ...

    def delete_setting(self, key: str) -> bool:
        """Delete a setting. Returns True if deleted, False if not found."""
        ...
