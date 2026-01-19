# pullDB MySQL Schema Constitution

[← Back to Documentation Index](START-HERE.md)

> **Foundation Documents**: This schema implements the architectural principles defined in `../.github/copilot-instructions.md` and coding standards from `../constitution.md`.
>
> **Related:** [Architecture](architecture.md) · [Development Guide](development.md)

> **Schema Management**:
> - **Source of Truth**: `schema/pulldb_service/*.sql` - numbered files defining all tables, views, indexes, and seed data
> - **Production Migrations**: `migrations/*.sql` - dbmate migrations for upgrading existing databases
> - **Test Setup**: Tests use `schema/pulldb_service/*.sql` directly for fresh databases each run
>
> When making schema changes:
> 1. Update `schema/pulldb_service/*.sql` (always)
> 2. Create a corresponding migration in `migrations/` for production upgrades
> 3. Migrations must be **idempotent** (use IF NOT EXISTS, INSERT IGNORE, etc.)
>
> The former monolithic dump is preserved at `schema/archived/pulldb.sql` for audit history only.

## Table of Contents

- [Prototype Charter](#prototype-charter)
- [MySQL User Model](#mysql-user-model)
- [Core Tables](#core-tables)
  - [auth_users](#auth_users)
  - [auth_credentials](#auth_credentials-phase-4)
  - [sessions](#sessions-phase-4)
  - [api_keys](#api_keys)
  - [jobs](#jobs)
  - [job_events](#job_events)
  - [db_hosts](#db_hosts)
  - [user_hosts](#user_hosts)
  - [locks](#locks)
  - [settings](#settings)
- [Admin & Audit Tables](#admin--audit-tables)
  - [admin_tasks](#admin_tasks)
  - [audit_logs](#audit_logs)
  - [procedure_deployments](#procedure_deployments)
  - [disallowed_users](#disallowed_users)
- [Feature Request Tables](#feature-request-tables)
  - [feature_requests](#feature_requests)
  - [feature_request_votes](#feature_request_votes)
  - [feature_request_notes](#feature_request_notes)
- [Supporting Views & Indices](#supporting-views--indices)
- [Stored Procedures](#stored-procedures)
- [Initial Data Population](#initial-data-population)
- [Timestamp Policy](#timestamp-policy)

---

## Prototype Charter

- **Single source of truth**: MySQL captures every restore request, its lifecycle, and audit breadcrumbs for the CLI and daemon.
- **Lean first release**: only tables required for the minimal restore loop ship in the prototype; everything else waits until the feature lands.
- **Predictable invariants**: constraints enforce unique usernames, per-target job exclusivity, and traceable status transitions.
- **Future-friendly**: deferred structures are documented so we can grow without rewriting foundations.

## MySQL User Model

pullDB uses **three separate MySQL users** following least-privilege principles:

| User | Service | Database | Permissions |
|------|---------|----------|-------------|
| `pulldb_api` | API service | `pulldb_service` | Limited: create users, submit jobs, read config |
| `pulldb_worker` | Worker service | `pulldb_service` | Job management: update status, manage events/locks/settings |
| `pulldb_loader` | myloader | Target databases | Full restore: CREATE, DROP, INSERT, etc. on `*.*` |

### Environment Variables

```bash
# Coordination database
PULLDB_MYSQL_DATABASE=pulldb_service

# Service-specific users (REQUIRED)
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker

# Password via AWS Secrets Manager (service-specific secrets)
# API service: aws-secretsmanager:/pulldb/mysql/api
# Worker service: aws-secretsmanager:/pulldb/mysql/worker
```

### Grant Statements

See `schema/pulldb_service/03000_mysql_users.sql` for complete grant statements.

**API User (`pulldb_api`):**
```sql
GRANT SELECT, INSERT ON pulldb_service.auth_users TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.jobs TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_api'@'localhost';
```

**Worker User (`pulldb_worker`):**
```sql
GRANT SELECT ON pulldb_service.auth_users TO 'pulldb_worker'@'localhost';
GRANT SELECT, UPDATE ON pulldb_service.jobs TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.settings TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.locks TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_worker'@'localhost';
```

**Loader User (`pulldb_loader`):**

This user exists on **target database hosts** (dev-db-01, etc.), not the coordination database. It's used by myloader for restore operations and needs broad permissions:

```sql
-- Run on each TARGET database host
GRANT CREATE, DROP, ALTER, INDEX, INSERT, UPDATE, DELETE, SELECT,
      LOCK TABLES, TRIGGER, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE,
      REFERENCES, EVENT, EXECUTE, PROCESS
ON *.* TO 'pulldb_loader'@'%';

-- Note: CREATE ROUTINE + ALTER ROUTINE required for deploying pulldb_atomic_rename
-- EXECUTE required to call the stored procedure
-- PROCESS required for connection monitoring
```

Loader credentials are stored per-host in the `db_hosts` table via `credential_ref`.

## Core Tables

### auth_users

```sql
CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- RBAC support
    role ENUM('user', 'manager', 'admin', 'service') NOT NULL DEFAULT 'user',
    
    -- Manager relationship
    manager_id CHAR(36) NULL,
    
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL,
    
    -- Per-user job limit (NULL=system default, 0=unlimited)
    max_active_jobs INT NULL
        COMMENT 'Per-user active job limit (NULL=system default, 0=unlimited)',
    
    -- Maintenance acknowledgment
    last_maintenance_ack DATE NULL
        COMMENT 'Last date user acknowledged maintenance modal',
    
    -- System account lock (locked users cannot be modified via UI)
    locked_at TIMESTAMP(6) NULL DEFAULT NULL
        COMMENT 'When set, user cannot be modified or login. For system accounts.',
    
    CONSTRAINT chk_user_code_length CHECK (CHAR_LENGTH(user_code) = 6),
    
    CONSTRAINT fk_auth_users_manager 
        FOREIGN KEY (manager_id) REFERENCES auth_users(user_id)
        ON DELETE SET NULL
);

-- Index for efficient manager->user lookups
CREATE INDEX idx_auth_users_manager ON auth_users(manager_id);
```

**Column Descriptions**:

- `user_id`: immutable UUID referenced by other tables.
- `username`: normalized login supplied through the trusted wrapper.
- `user_code`: six-character identifier used to derive restore targets. Generation rules follow the README prototype strategy and reject non-unique results.
- `is_admin`: legacy boolean flag (retained for compatibility, use `role` column instead).
- `role`: RBAC role controlling access levels:
  - `user`: Standard user - submit and manage own jobs only
  - `manager`: Team lead - view all jobs, manage assigned users' jobs
  - `admin`: Full system access including user management and configuration
  - `service`: System service accounts (e.g., `pulldb_service` for systemd tasks)
- `manager_id`: FK to manager user for hierarchical team assignment.
- `disabled_at`: soft-delete marker so audit history remains intact.
- `max_active_jobs`: Per-user limit override (NULL=use system default, 0=unlimited).
- `last_maintenance_ack`: Tracks when user last acknowledged the maintenance modal.
- `locked_at`: System account protection - locked accounts cannot be modified via UI.

**Built-in Accounts:**

| Username | User Code | UUID | Role | Purpose |
|----------|-----------|------|------|---------|
| `admin` | `adminn` | `00000000-0000-0000-0000-000000000002` | admin | Human administrator (password set at install) |
| `pulldb_service` | `sbcacc` | `00000000-0000-0000-0000-000000000001` | service | Service Bootstrap/CLI Admin Account for systemd tasks |

The `pulldb_service` account:
- Has a fixed UUID: `00000000-0000-0000-0000-000000000001`
- Has no password (cannot login via web UI)
- Has `locked_at` set to prevent modification
- Enables systemd services (e.g., `pulldb-retention.timer`) to run `pulldb-admin` commands
- Created by `schema/pulldb_service/02_seed/050_seed_service_account.sql`

The `admin` account:
- Has a fixed UUID: `00000000-0000-0000-0000-000000000002`
- Password is generated randomly during install and displayed to the administrator
- Created by `schema/pulldb_service/02_seed/040_seed_admin_account.sql`
- Password set by `packaging/debian/postinst`

### auth_credentials (Phase 4)

Password and 2FA storage for web authentication:

```sql
CREATE TABLE auth_credentials (
    user_id CHAR(36) PRIMARY KEY,
    password_hash VARCHAR(255) NULL,  -- bcrypt hash, NULL = no password set
    totp_secret VARCHAR(64) NULL,     -- Base32 encoded TOTP secret
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_credentials_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE
);
```

- `password_hash`: bcrypt hash of user password. NULL means no password set (uses Linux system auth only).
- `totp_secret`: Base32 encoded TOTP secret for 2FA. NULL if 2FA not configured.
- `totp_enabled`: Whether 2FA is active for this user.

### sessions (Phase 4)

Session management for web authentication:

```sql
CREATE TABLE sessions (
    session_id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    token_hash CHAR(64) NOT NULL,  -- SHA-256 of session token
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6) NOT NULL,
    last_activity TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ip_address VARCHAR(45) NULL,   -- IPv4 or IPv6
    user_agent VARCHAR(255) NULL,
    CONSTRAINT fk_session_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE,
    INDEX idx_sessions_user (user_id),
    INDEX idx_sessions_expires (expires_at),
    INDEX idx_sessions_token (token_hash)
);
```

- `token_hash`: SHA-256 hash of session token for secure lookup.
- `expires_at`: Session expiration time.
- `last_activity`: Updated on each authenticated request for session timeout tracking.
- `ip_address`: Client IP for security auditing.
- `user_agent`: Browser/client identifier for session management UI.

### api_keys

API key storage for CLI/programmatic authentication with approval workflow:

```sql
CREATE TABLE api_keys (
    key_id VARCHAR(64) PRIMARY KEY,              -- Public key identifier (key_xxxxx...)
    user_id CHAR(36) NOT NULL,                   -- Owner of this API key
    key_secret_hash VARCHAR(255) NOT NULL,       -- bcrypt hash of the secret (for audit)
    key_secret VARCHAR(255) NOT NULL,            -- Plaintext secret (needed for HMAC verification)
    name VARCHAR(100) NULL,                      -- Optional friendly name for the key
    
    -- Host tracking
    host_name VARCHAR(255) NULL
        COMMENT 'Auto-detected hostname when key was requested',
    created_from_ip VARCHAR(45) NULL
        COMMENT 'IP address of the request-host-key call',
    
    -- Keys start inactive until approved
    is_active BOOLEAN NOT NULL DEFAULT FALSE,    -- Can be revoked without deletion
    
    -- Approval workflow
    approved_at TIMESTAMP(6) NULL
        COMMENT 'When admin approved the key (NULL = pending)',
    approved_by CHAR(36) NULL
        COMMENT 'Which admin approved the key',
    
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_used_at TIMESTAMP(6) NULL,              -- Track last usage for auditing
    last_used_ip VARCHAR(45) NULL
        COMMENT 'IP address of most recent authenticated request',
    expires_at TIMESTAMP(6) NULL,                -- Optional expiration
    
    CONSTRAINT fk_apikey_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_apikey_approved_by FOREIGN KEY (approved_by)
        REFERENCES auth_users(user_id) ON DELETE SET NULL,
    
    INDEX idx_apikey_user (user_id),
    INDEX idx_apikey_active (is_active, user_id),
    INDEX idx_apikey_pending (approved_at, created_at),
    INDEX idx_apikey_approval_status (is_active, approved_at)
);
```

**Approval Workflow:**
1. User requests key via CLI (`pulldb request-host-key`) or Web UI
2. Key created with `is_active=FALSE`, `approved_at=NULL`
3. Admin reviews pending keys in Web UI or CLI (`pulldb-admin keys pending`)
4. Admin approves: sets `is_active=TRUE`, `approved_at`, `approved_by`
5. Key can later be revoked: sets `is_active=FALSE` (without deletion)

### jobs

```sql
CREATE TABLE jobs (
    id CHAR(36) PRIMARY KEY,
    owner_user_id CHAR(36) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    owner_user_code CHAR(6) NOT NULL,
    target VARCHAR(255) NOT NULL,
    staging_name VARCHAR(64) NOT NULL,
    dbhost VARCHAR(255) NOT NULL,
    
    -- Full status ENUM with all statuses
    status ENUM(
        'queued',       -- Job submitted, waiting to be processed
        'running',      -- Job being executed by worker
        'canceling',    -- Cancellation requested, worker stopping at checkpoint
        'failed',       -- Job execution failed
        'complete',     -- Job successfully completed (legacy, before retention)
        'canceled',     -- Job was canceled before completion
        'deleting',     -- Job databases being deleted (async bulk delete)
        'deleted',      -- Job databases deleted by user
        'deployed',     -- Database deployed and available for use
        'expired',      -- Database exceeded retention period, awaiting cleanup
        'superseded'    -- Replaced by newer restore to same target
    ) NOT NULL DEFAULT 'queued',
    
    submitted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    options_json JSON,
    
    -- Custom target tracking
    custom_target TINYINT(1) NOT NULL DEFAULT 0 
        COMMENT 'Whether custom target naming was used (1=custom, 0=auto-generated)',
    
    retry_count INT NOT NULL DEFAULT 0,
    error_detail TEXT,
    
    -- Cancel support
    can_cancel BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Whether job can still be canceled (false once loading begins)',
    cancel_requested_at TIMESTAMP(6) NULL 
        COMMENT 'User-requested cancellation timestamp',
    staging_cleaned_at TIMESTAMP(6) NULL 
        COMMENT 'When staging database was cleaned up',
    
    -- Worker tracking
    worker_id VARCHAR(255) NULL 
        COMMENT 'Worker that claimed this job (hostname:pid)',
    
    -- Database retention & lifecycle
    expires_at TIMESTAMP(6) NULL 
        COMMENT 'When database expires and becomes eligible for cleanup',
    locked_at TIMESTAMP(6) NULL 
        COMMENT 'When user locked this database (NULL = not locked)',
    locked_by VARCHAR(255) NULL 
        COMMENT 'Username who locked this database',
    db_dropped_at TIMESTAMP(6) NULL 
        COMMENT 'When the actual database was dropped from target host',
    superseded_at TIMESTAMP(6) NULL 
        COMMENT 'When a newer restore to same target replaced this job',
    superseded_by_job_id CHAR(36) NULL 
        COMMENT 'Job ID that superseded this one',
    
    -- Virtual column for unique constraint enforcement (per-target exclusivity)
    active_target_key VARCHAR(520) GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued','running','canceling') 
             THEN CONCAT(target,'@@',dbhost) ELSE NULL END
    ) VIRTUAL,
    
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);

-- Core indexes
CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);
CREATE INDEX idx_jobs_queue ON jobs(status, submitted_at);
CREATE INDEX idx_jobs_owner_status ON jobs(owner_user_id, status);
CREATE INDEX idx_jobs_worker_id ON jobs(worker_id);
CREATE INDEX idx_jobs_staging_cleanup ON jobs(dbhost, status, staging_cleaned_at, completed_at);

-- Retention indexes
CREATE INDEX idx_jobs_retention_cleanup 
    ON jobs(status, expires_at, locked_at, db_dropped_at, superseded_at);
CREATE INDEX idx_jobs_locked ON jobs(locked_at, owner_user_id);

-- Delete support index
CREATE INDEX idx_jobs_deletable ON jobs(owner_user_id, status, completed_at);

-- Cancel support index
CREATE INDEX idx_jobs_can_cancel ON jobs(can_cancel);

-- Custom target index
CREATE INDEX idx_jobs_custom_target ON jobs(custom_target, status);

-- Stale delete recovery index
CREATE INDEX idx_jobs_stale_deleting ON jobs(status, retry_count, started_at);
```

**Column Descriptions:**

- `target`: sanitized database name (`user_code` + customer token or `qatemplate`). Maximum 51 characters.
- `staging_name`: temporary database name used during restore (`target_<job_id_first_12_chars>`). Maximum 64 characters.
- `dbhost`: target database server hostname.
- `options_json`: frozen snapshot of CLI flags for replay and inspection.
- `custom_target`: Boolean flag indicating if `--custom-target` option was used (1=custom, 0=auto-generated).
- `retry_count`: increments when operators resubmit after failure (manual only).
- `error_detail`: optional payload describing failure context.
- `worker_id`: identifier of the worker that claimed the job (format: "hostname:pid"). Set by `claim_next_job()` for debugging/monitoring. NULL for unclaimed jobs.
- `can_cancel`: Whether job can still be canceled. Set to FALSE once myloader begins loading data.
- `cancel_requested_at`: timestamp when user requested cancellation. Worker checks this periodically and aborts gracefully if set.
- `staging_cleaned_at`: timestamp when staging database was cleaned up after restore. Prevents re-processing in cleanup runs.
- `expires_at`: When the deployed database expires and becomes eligible for retention cleanup.
- `locked_at`: When a user locked this database to prevent automatic expiration.
- `locked_by`: Username who locked the database.
- `db_dropped_at`: When the actual database was dropped from the target host.
- `superseded_at`: When a newer restore to the same target replaced this job.
- `superseded_by_job_id`: Job ID of the replacement job.
- `active_target_key`: generated virtual column for per-target exclusivity (NULL unless status is queued/running/canceling).

**Job Status State Machine:**

```
queued → running → deployed → expired → deleted
           ↓           ↓
         failed    superseded
           
queued → canceling → canceled
running → canceling → canceled

deployed → deleting → deleted (user-initiated)
```

### job_events

```sql
CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail TEXT,
    logged_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_job_events_job FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_job_events_job_id ON job_events(job_id, logged_at);
```

- `event_type`: expected prototype values include `queued`, `running`, `failed`, `complete`, plus `heartbeat` or `note` as needed for troubleshooting.
- `logged_at`: timestamp of event (uses CURRENT_TIMESTAMP(6) for microsecond precision).
- Actor columns removed in final implementation - job ownership is tracked in jobs table.

### db_hosts

```sql
CREATE TABLE db_hosts (
    id CHAR(36) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    credential_ref VARCHAR(512) NOT NULL,
    max_running_jobs INT NOT NULL DEFAULT 1,
    max_active_jobs INT NOT NULL DEFAULT 10,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
```

- `hostname`: Logical hostname or alias (e.g., `dev-db-01`). Must match the `dbhost` value used in CLI/API. The actual connection FQDN is stored in the referenced secret.
- `credential_ref`: Reference to credentials in AWS Secrets Manager or SSM Parameter Store
  - Format: `aws-secretsmanager:/pulldb/mysql/dev-db-01` (recommended)
  - Format: `aws-ssm:/pulldb/mysql/dev-db-01-credentials` (alternative)
- `max_running_jobs`: Maximum concurrent restore operations on this host (Worker enforcement)
- `max_active_jobs`: Maximum queued+running jobs on this host (API enforcement)
- `enabled`: Boolean flag to temporarily disable a host without deleting the record


### locks

```sql
CREATE TABLE locks (
    lock_name VARCHAR(100) PRIMARY KEY,
    locked_by VARCHAR(255) NOT NULL,
    locked_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6) NOT NULL,
    INDEX idx_locks_expires (expires_at)
);
```

- `expires_at`: TTL for automatic lock expiration if daemon crashes.
- The daemon releases locks explicitly; watchdog jobs can reclaim abandoned rows after expiration.

### settings

```sql
CREATE TABLE settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
);
```

- `description`: human-readable explanation of setting purpose.

**Available Settings:**

| Key | Type | Category | Description |
|-----|------|----------|-------------|
| `default_dbhost` | string | hosts | Default target host for restores |
| `s3_bucket_path` | string | storage | S3 bucket path for backups |
| `work_directory` | path | storage | Local working directory for downloads |
| `max_active_jobs_per_user` | integer | limits | Per-user active job limit (0=unlimited) |
| `max_active_jobs_global` | integer | limits | System-wide active job limit (0=unlimited) |
| `staging_retention_days` | integer | retention | Days to keep staging databases |
| `job_log_retention_days` | integer | retention | Days to keep job event logs |
| `max_retention_months` | integer | retention | Maximum database retention (months) |
| `max_retention_increment` | integer | retention | Maximum extension per request (months) |
| `expiring_notice_days` | integer | retention | Days before expiration to show warning |
| `cleanup_grace_days` | integer | retention | Grace period after expiration |
| `customers_after_sql_dir` | path | scripts | Customer post-SQL script directory |
| `qa_template_after_sql_dir` | path | scripts | QA template post-SQL script directory |

### user_hosts

```sql
CREATE TABLE user_hosts (
    user_id CHAR(36) NOT NULL,
    host_id CHAR(36) NOT NULL,
    assigned_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    assigned_by CHAR(36) NULL,
    PRIMARY KEY (user_id, host_id),
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (host_id) REFERENCES db_hosts(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES auth_users(user_id) ON DELETE SET NULL
);

CREATE INDEX idx_user_hosts_host ON user_hosts(host_id);
```

- Tracks which hosts each user is allowed to restore to.
- If no entries exist for a user, they can restore to any enabled host.
- `assigned_by`: Admin user who granted this host access.

---

## Admin & Audit Tables

### admin_tasks

Background task queue for long-running admin operations:

```sql
CREATE TABLE admin_tasks (
    task_id CHAR(36) PRIMARY KEY,
    
    -- Task type
    task_type ENUM(
        'force_delete_user',   -- Delete user and optionally drop databases
        'scan_user_orphans',   -- Find databases for deleted users
        'bulk_delete_jobs',    -- Mass job deletion
        'retention_cleanup'    -- Scheduled expiration processing
    ) NOT NULL,
    status ENUM('pending', 'running', 'complete', 'failed') NOT NULL DEFAULT 'pending',
    
    -- Who requested the task
    requested_by CHAR(36) NOT NULL,
    
    -- Target user (for user-related tasks)
    target_user_id CHAR(36) NULL,
    
    -- Task parameters and results (JSON)
    parameters_json JSON NULL,
    result_json JSON NULL,
    
    -- Timestamps
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    
    -- Error detail for failed tasks
    error_detail TEXT NULL,
    
    -- Worker tracking for orphan recovery
    worker_id VARCHAR(255) NULL COMMENT 'Worker that claimed this task (hostname:pid)',
    
    -- Generated column for single-running-task constraint
    running_task_type VARCHAR(50) GENERATED ALWAYS AS (
        CASE WHEN status = 'running' THEN task_type ELSE NULL END
    ) STORED,
    
    -- Indexes
    INDEX idx_admin_tasks_status_created (status, created_at),
    INDEX idx_admin_tasks_requested_by (requested_by),
    INDEX idx_admin_tasks_target_user (target_user_id),
    INDEX idx_admin_tasks_type_status (task_type, status)
);

-- Enforce max 1 concurrent task of same type
CREATE UNIQUE INDEX idx_admin_tasks_single_running ON admin_tasks(running_task_type);
```

**Virtual Column:** `running_task_type` enforces only one task of each type can run simultaneously via unique index on non-null values.

### audit_logs

Audit trail for administrative actions:

```sql
CREATE TABLE audit_logs (
    audit_id CHAR(36) PRIMARY KEY,
    
    -- Who performed the action
    actor_user_id CHAR(36) NOT NULL,
    
    -- Target of the action (if applicable)
    target_user_id CHAR(36) NULL,
    
    -- What action was performed
    action VARCHAR(50) NOT NULL,
    
    -- Human-readable detail
    detail TEXT NULL,
    
    -- Additional context as JSON
    context_json JSON NULL,
    
    -- Timestamp
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    
    -- Indexes
    INDEX idx_audit_logs_actor (actor_user_id),
    INDEX idx_audit_logs_target (target_user_id),
    INDEX idx_audit_logs_action (action),
    INDEX idx_audit_logs_created (created_at)
);
```

**Action Types:**
- `submit_for_user` - Admin submitted job on behalf of user
- `cancel_job` - Admin/manager canceled a job
- `create_user` - New user created
- `disable_user` - User disabled
- `enable_user` - User re-enabled
- `set_role` - User role changed
- `assign_manager` - User assigned to manager
- `approve_key` - API key approved
- `revoke_key` - API key revoked
- `force_password_reset` - Admin forced password reset

**Note:** No foreign key constraints to allow audit log preservation even if users are deleted.

### procedure_deployments

Tracks stored procedure deployments per host:

```sql
CREATE TABLE procedure_deployments (
    id CHAR(36) PRIMARY KEY COMMENT 'UUID of deployment event',
    host VARCHAR(255) NOT NULL COMMENT 'MySQL hostname where procedure deployed',
    procedure_name VARCHAR(64) NOT NULL COMMENT 'Name of stored procedure',
    version_deployed VARCHAR(20) NOT NULL COMMENT 'Semantic version (e.g., 1.0.1)',
    deployed_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    deployed_by VARCHAR(50) COMMENT 'User or service that deployed',
    deployment_reason ENUM('initial', 'version_mismatch', 'missing') NOT NULL,
    job_id CHAR(36) NULL COMMENT 'Job that triggered deployment',
    
    INDEX idx_host_proc_time (host, procedure_name, deployed_at DESC),
    INDEX idx_job_id (job_id),
    INDEX idx_deployed_at (deployed_at DESC)
);
```

**Purpose:** Tracks when `pulldb_atomic_rename` stored procedure is deployed to target hosts, enabling version management and audit trail.

### disallowed_users

Username blacklist for registration:

```sql
CREATE TABLE disallowed_users (
    username VARCHAR(100) NOT NULL PRIMARY KEY,
    reason VARCHAR(500) NULL,
    is_hardcoded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    created_by CHAR(36) NULL,
    
    INDEX idx_disallowed_users_hardcoded (is_hardcoded),
    INDEX idx_disallowed_users_created (created_at)
);
```

- `is_hardcoded`: TRUE for entries from `domain/validation.py` (cannot be removed via UI)
- `created_by`: User ID who added the entry (NULL for seed/hardcoded entries)

**Hardcoded Usernames** (from `domain/validation.py`):
- `admin`, `root`, `system`, `service`, `pulldb`, `pulldb_service`
- And other reserved names that could cause confusion or security issues

---

## Feature Request Tables

### feature_requests

User feature request tracking:

```sql
CREATE TABLE feature_requests (
    request_id CHAR(36) PRIMARY KEY,
    
    submitted_by_user_id CHAR(36) NOT NULL,
    
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    
    status ENUM('open', 'in_progress', 'complete', 'declined') NOT NULL DEFAULT 'open',
    
    -- Vote aggregates (denormalized for performance)
    vote_score INT NOT NULL DEFAULT 0,
    upvote_count INT UNSIGNED NOT NULL DEFAULT 0,
    downvote_count INT UNSIGNED NOT NULL DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    
    -- Admin response
    admin_response TEXT NULL,
    
    -- Indexes
    INDEX idx_feature_requests_status (status),
    INDEX idx_feature_requests_score (vote_score DESC),
    INDEX idx_feature_requests_created (created_at DESC),
    INDEX idx_feature_requests_submitted_by (submitted_by_user_id),
    
    FOREIGN KEY (submitted_by_user_id) REFERENCES auth_users(user_id)
);
```

### feature_request_votes

Vote tracking per user per request:

```sql
CREATE TABLE feature_request_votes (
    vote_id CHAR(36) PRIMARY KEY,
    request_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    vote_value TINYINT NOT NULL,  -- 1 = upvote, -1 = downvote
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    
    UNIQUE KEY uk_user_request (user_id, request_id),
    
    FOREIGN KEY (request_id) REFERENCES feature_requests(request_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);
```

### feature_request_notes

Discussion/notes on feature requests:

```sql
CREATE TABLE feature_request_notes (
    note_id CHAR(36) NOT NULL PRIMARY KEY,
    request_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    note_text TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (request_id) REFERENCES feature_requests(request_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id) ON DELETE CASCADE,
    
    INDEX idx_notes_request (request_id),
    INDEX idx_notes_created (created_at)
);
```

---

## Supporting Views & Indices

### active_jobs View

```sql
CREATE VIEW active_jobs AS
SELECT id,
       owner_user_id,
       owner_username,
       owner_user_code,
       target,
       staging_name,
       dbhost,
       status,
       submitted_at,
       started_at,
       worker_id,
       can_cancel
FROM jobs
WHERE status IN ('queued', 'running', 'canceling', 'deployed');
```

- `active_jobs` powers duplicate detection and status reporting without extra predicates in application code.
- Includes `deployed` status since those databases are still "active" from user perspective.
- `can_cancel` included for UI display of cancel button availability.

---

## Stored Procedures

### pulldb_atomic_rename

Zero-downtime database rename procedure deployed to target MySQL hosts.

**Version:** 1.0.1  
**Location:** Auto-deployed by worker to each target host  
**Tracking:** `procedure_deployments` table

```sql
-- Signature
CALL pulldb_atomic_rename(
    @staging_db VARCHAR(64),  -- Source staging database
    @target_db VARCHAR(64),   -- Final database name
    @result VARCHAR(255) OUTPUT
);
```

**Deployment Logic** (in `pulldb/worker/atomic_rename.py`):
1. Check `procedure_deployments` for current version on host
2. If missing or version < 1.0.1, deploy fresh using advisory lock
3. Lock prevents concurrent deployments from multiple workers

**Behavior:**
- Renames all tables from staging database to target database atomically
- Handles existing target database (DROP IF EXISTS for overwrite support)
- Returns result status message

---

## Initial Data Population

### Database Hosts (Local + Legacy)

Pre-populate `db_hosts` with a local sandbox plus the three legacy development database servers. Local development uses the sandbox by default; legacy endpoints remain registered (disabled) for explicit overrides:

```sql
-- Local development sandbox (default)
INSERT INTO db_hosts (id, hostname, credential_ref, max_running_jobs, max_active_jobs, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440003',
     'localhost',
    'aws-secretsmanager:/pulldb/mysql/localhost-test',
     1,
     10,
     TRUE);

-- Development database server
INSERT INTO db_hosts (id, hostname, credential_ref, max_running_jobs, max_active_jobs, enabled) VALUES
    ('f869577c-752a-4fbd-b257-4e6f8930d77d',
     'dev-db-01',
     'aws-secretsmanager:/pulldb/mysql/dev-db-01',
     1,
     10,
     TRUE);
```

**Note**: Credentials for these hosts must be created in AWS Secrets Manager before the Worker service can connect. See `docs/AWS-SETUP.md` for setup instructions. The local sandbox secret (`/pulldb/mysql/localhost-test`) is required for development setups.

### Configuration Settings

Set default `dbhost` to the local sandbox and configure other operational parameters:

```sql
-- Default database host (local development sandbox)
INSERT INTO settings (setting_key, setting_value) VALUES
    ('default_dbhost', 'localhost');

-- S3 backup bucket path
INSERT INTO settings (setting_key, setting_value) VALUES
    ('s3_bucket_path', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/');

-- Post-restore SQL script directories
INSERT INTO settings (setting_key, setting_value) VALUES
    ('customers_after_sql_dir', '/opt/pulldb.service/customers_after_sql/'),
    ('qa_template_after_sql_dir', '/opt/pulldb.service/qa_template_after_sql/');

-- Default working directory for downloads and extractions
INSERT INTO settings (setting_key, setting_value) VALUES
    ('work_directory', '/var/lib/pulldb/work/');

-- Concurrency limits (Phase 2 - v0.0.4)
-- 0 = unlimited (default), any positive integer enforces the limit
INSERT INTO settings (setting_key, setting_value) VALUES
    ('max_active_jobs_per_user', '0'),   -- Max concurrent jobs per user
    ('max_active_jobs_global', '0');     -- Max concurrent jobs system-wide
```

**Concurrency Settings** (added v0.0.4):
- `max_active_jobs_per_user`: Maximum concurrent active jobs per user (0=unlimited)
- `max_active_jobs_global`: Maximum concurrent active jobs system-wide (0=unlimited)
- See `docs/concurrency-controls.md` for detailed configuration and monitoring guidance.

**Migration Note**: Users of legacy `pullDB-auth --type=SUPPORT` should use `pullDB user=<user> customer=<customer>` (default, now targeting the local sandbox).

## Timestamp Policy

- Every timestamp column uses `CURRENT_TIMESTAMP(6)` with microsecond precision for automatic timestamp insertion.
- MySQL's `TIMESTAMP` type stores UTC values internally and converts based on session time zone.
- Server and application should be configured with `time_zone = '+00:00'` to ensure UTC storage and retrieval.
- Application code should treat values as MySQL TIMESTAMP(6) for easy comparison and ordering.
- When external systems ingest the data, they should not mutate timestamps in place; use new event rows instead.
- Triggers may use `UTC_TIMESTAMP(6)` for explicit UTC timestamp generation when needed.

## Deferred Schema (Backlog)

Items documented for future consideration but not yet implemented:

- `job_logs`: High-volume worker output retention once richer telemetry ships.
- `history_cache`: Materialized view of completed restores to power `history=` responses.
- `user_concurrency_limits` and `host_concurrency_limits`: Override tables for advanced concurrency policies.
- `manager_of_managers`: Hierarchical manager relationships for senior manager oversight.

_This constitution guides the implementation and provides a grounded roadmap for queued enhancements._

---

[← Back to Documentation Index](START-HERE.md) · [Architecture →](architecture.md)
