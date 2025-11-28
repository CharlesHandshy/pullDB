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
        is_admin: Whether user has admin privileges (reserved for Phase 4).
        created_at: Timestamp when user was created.
        disabled_at: Timestamp when user was disabled (soft delete).
    """

    user_id: str
    username: str
    user_code: str
    is_admin: bool
    created_at: datetime
    disabled_at: datetime | None = None


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
