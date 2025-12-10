"""Domain models for pullDB.

This module defines the core business entities used throughout the application.
All models are immutable (frozen=True) to ensure data consistency and prevent
accidental modifications after creation.

Models correspond directly to database tables in the pulldb schema:
- User: auth_users table
- Job: jobs table
- JobEvent: job_events table
- DBHost: db_hosts table
- Setting: settings table
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class JobStatus(Enum):
    """Job lifecycle status.

    Represents the current state of a restore job in the queue.

    Attributes:
        QUEUED: Job submitted and waiting to be processed.
        RUNNING: Job currently being executed by worker.
        FAILED: Job execution failed with error.
        COMPLETE: Job successfully completed.
        CANCELED: Job canceled by user (reserved for Phase 1).
    """

    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETE = "complete"
    CANCELED = "canceled"  # Reserved for Phase 1


# Terminal states - jobs in these states have finished processing and
# their staging databases are eligible for cleanup
TERMINAL_STATUSES = frozenset({JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED})

# SQL-safe terminal status values for use in queries
TERMINAL_STATUS_VALUES = frozenset({s.value for s in TERMINAL_STATUSES})


class UserRole(Enum):
    """User role for RBAC.

    Values correspond to auth_users.role ENUM in database.
    Phase 4: Role-based access control.

    Attributes:
        USER: Standard user - can only manage own jobs.
        MANAGER: Operational oversight - can view/cancel any job.
        ADMIN: Full system access - can manage users and configuration.
    """

    USER = "user"
    MANAGER = "manager"
    ADMIN = "admin"


@dataclass(frozen=True)
class User:
    """User entity from auth_users table.

    Represents a user who can submit restore jobs. The user_code is a unique
    6-character identifier derived from the username, used to construct target
    database names.

    Attributes:
        user_id: UUID primary key.
        username: Unique username from authentication system.
        user_code: 6-character code derived from username.
        is_admin: Whether user has admin privileges (legacy, kept for compatibility).
        role: RBAC role (user/manager/admin) - Phase 4.
        manager_id: User ID of the manager who manages this user (NULL if unmanaged).
        created_at: Timestamp when user was created.
        disabled_at: Timestamp when user was disabled (soft delete).
        allowed_hosts: List of database hostnames this user can restore to.
        default_host: User's default database host for restores.
    """

    user_id: str
    username: str
    user_code: str
    is_admin: bool
    role: UserRole
    created_at: datetime
    manager_id: str | None = None
    disabled_at: datetime | None = None
    allowed_hosts: list[str] | None = None
    default_host: str | None = None

    @property
    def is_manager_or_above(self) -> bool:
        """Check if user has manager or admin role."""
        return self.role in (UserRole.MANAGER, UserRole.ADMIN)

    @property
    def can_view_all_jobs(self) -> bool:
        """Check if user can view all jobs (manager and admin)."""
        return self.role in (UserRole.MANAGER, UserRole.ADMIN)

    @property
    def can_create_users(self) -> bool:
        """Check if user can create new users (manager and admin)."""
        return self.role in (UserRole.MANAGER, UserRole.ADMIN)

    @property
    def is_managed(self) -> bool:
        """Check if this user is managed by someone."""
        return self.manager_id is not None

    @property
    def disabled(self) -> bool:
        """Check if user account is disabled."""
        return self.disabled_at is not None

    @property
    def has_any_hosts(self) -> bool:
        """Check if user has any allowed database hosts.
        
        Admins implicitly have access to all hosts, so always return True.
        """
        if self.role == UserRole.ADMIN:
            return True
        return bool(self.allowed_hosts)

    def can_use_host(self, hostname: str) -> bool:
        """Check if user is authorized to use a specific database host.
        
        Admins can use any host. Other users must have the host in their
        allowed_hosts list.
        """
        if self.role == UserRole.ADMIN:
            return True
        return hostname in (self.allowed_hosts or [])


@dataclass(frozen=True)
class Job:
    """Job entity from jobs table.

    Represents a single database restore request with all lifecycle metadata.
    Jobs progress through states: queued → running → (complete|failed).

    Attributes:
        id: UUID primary key (job_id).
        owner_user_id: Foreign key to auth_users.user_id.
        owner_username: Denormalized username for convenience.
        owner_user_code: Denormalized user_code for convenience.
        target: Target database name (user_code + customer/qatemplate).
        staging_name: Temporary staging database name (target + "_" + job_id[:12]).
        dbhost: Target database server hostname.
        status: Current job status (queued, running, failed, complete).
        submitted_at: Timestamp when job was submitted.
        started_at: Timestamp when job execution started (NULL until running).
        completed_at: Timestamp when job finished (NULL until complete/failed).
        options_json: JSON snapshot of CLI options (customer/qatemplate, overwrite).
        retry_count: Number of manual retries (incremented on resubmit).
        error_detail: Error message if job failed (NULL for success).
        worker_id: Identifier of worker that claimed job (format: hostname:pid).
            Set by claim_next_job() and retained after completion for debugging.
        staging_cleaned_at: Timestamp when staging database was cleaned up (NULL until cleanup).
    """

    id: str
    owner_user_id: str
    owner_username: str
    owner_user_code: str
    target: str
    staging_name: str
    dbhost: str
    status: JobStatus
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    options_json: dict[str, str] | None = None
    retry_count: int = 0
    error_detail: str | None = None
    worker_id: str | None = None
    current_operation: str | None = None
    staging_cleaned_at: datetime | None = None


@dataclass(frozen=True)
class JobEvent:
    """Job event entity from job_events table.

    Represents a single audit trail entry for a job. Events track state
    transitions and significant milestones during job execution.

    Common event_type values:
    - queued: Job submitted to queue
    - running: Job execution started
    - failed: Job execution failed
    - complete: Job execution succeeded
    - staging_auto_cleanup: Orphaned staging database dropped
    - download_started: S3 download initiated
    - restore_started: myloader execution started
    - post_sql_executed: Post-restore SQL scripts completed
    - atomic_rename: Staging renamed to target

    Attributes:
        id: Auto-increment primary key.
        job_id: Foreign key to jobs.id.
        event_type: Type of event (see above).
        detail: Optional detail message or JSON payload.
        logged_at: Timestamp when event was logged (microsecond precision).
    """

    id: int
    job_id: str
    event_type: str
    detail: str | None
    logged_at: datetime


@dataclass(frozen=True)
class DBHost:
    """Database host entity from db_hosts table.

    Represents a target MySQL server where restored databases are created.
    Hosts store credential references resolved via AWS Secrets Manager or
    SSM Parameter Store.

    Attributes:
        id: Auto-increment primary key.
        hostname: Fully qualified domain name of MySQL server.
        host_alias: Optional short alias for the host (e.g., "dev-db-01").
            Allows users to specify short names instead of full FQDNs.
        credential_ref: Reference to credentials in AWS service.
            Format: aws-secretsmanager:/pulldb/mysql/localhost-test (recommended)
            Format: aws-ssm:/pulldb/mysql/localhost-test-credentials (alternative)
        max_concurrent_restores: Maximum simultaneous restores on this host.
        enabled: Whether host is available for new jobs.
        created_at: Timestamp when host was registered.
    """

    id: int
    hostname: str
    credential_ref: str
    max_concurrent_restores: int
    enabled: bool
    created_at: datetime
    host_alias: str | None = None


@dataclass(frozen=True)
class Setting:
    """Setting entity from settings table.

    Represents a configuration value stored in the database. Settings
    supplement environment variables and provide runtime configuration.

    Common settings:
    - default_dbhost: Default target database host
    - s3_bucket_path: S3 bucket path for backups
    - customers_after_sql_dir: Directory for customer post-restore SQL
    - qa_template_after_sql_dir: Directory for QA template post-restore SQL
    - work_dir: Working directory for downloads and extractions

    Attributes:
        setting_key: Primary key, unique setting identifier.
        setting_value: Configuration value (may contain AWS SSM paths).
        description: Human-readable explanation of setting purpose.
        updated_at: Timestamp of last update (auto-updated by MySQL).
    """

    setting_key: str
    setting_value: str
    description: str | None
    updated_at: datetime


@dataclass(frozen=True)
class CommandResult:
    """Captured results of a subprocess execution."""

    command: list[str]
    exit_code: int
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    stdout: str
    stderr: str


@dataclass(frozen=True)
class MySQLCredentials:
    """MySQL database connection credentials.

    Attributes:
        username: MySQL username for authentication.
        password: MySQL password for authentication.
        host: MySQL server hostname or endpoint.
        port: MySQL server port (default: 3306).
        dbClusterIdentifier: Optional RDS/Aurora cluster identifier for rotation.
    """

    username: str
    password: str
    host: str
    port: int = 3306
    db_cluster_identifier: str | None = None

    def __repr__(self) -> str:
        """Return string representation with password redacted."""
        return (
            f"MySQLCredentials(username={self.username!r}, "
            f"password='***REDACTED***', "
            f"host={self.host!r}, "
            f"port={self.port})"
        )


@dataclass(frozen=True)
class UserSummary:
    """User summary with job statistics."""

    user: User
    active_jobs_count: int


@dataclass(frozen=True)
class UserDetail:
    """Detailed user statistics."""

    user: User
    total_jobs: int
    complete_jobs: int
    failed_jobs: int
    active_jobs: int
