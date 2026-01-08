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

-- Key privileges for atomic rename operations:
-- CREATE ROUTINE, ALTER ROUTINE: Deploy stored procedures
-- EXECUTE: Run stored procedures for atomic rename
-- PROCESS: View other sessions for advisory lock management
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
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL,
    CONSTRAINT chk_user_code_length CHECK (CHAR_LENGTH(user_code) = 6)
);
```

- `user_id`: immutable UUID referenced by other tables.
- `username`: normalized login supplied through the trusted wrapper.
- `user_code`: six-character identifier used to derive restore targets. Generation rules follow the README prototype strategy and reject non-unique results.
- `is_admin`: reserved for future admin tooling; prototype treats every authenticated user the same.
- `disabled_at`: soft-delete marker so audit history remains intact.

**Phase 4 Addition**: The `role` column was added to support role-based access control:

```sql
ALTER TABLE auth_users ADD COLUMN role ENUM('user','manager','admin') NOT NULL DEFAULT 'user';
```

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
    status ENUM('queued','running','failed','complete','canceled') NOT NULL DEFAULT 'queued',
    submitted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    options_json JSON,
    retry_count INT NOT NULL DEFAULT 0,
    error_detail TEXT,
    worker_id VARCHAR(255) NULL,
    cancel_requested_at TIMESTAMP(6) NULL,
    staging_cleaned_at TIMESTAMP(6) NULL,
    active_target_key VARCHAR(520) GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued','running') THEN CONCAT(target,'@@',dbhost) ELSE NULL END
    ) VIRTUAL,
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);
```

- `target`: sanitized database name (`user_code` + customer token or `qatemplate`). Maximum 51 characters.
- `staging_name`: temporary database name used during restore (`target_<job_id_first_12_chars>`). Maximum 64 characters.
- `dbhost`: target database server hostname.
- `options_json`: frozen snapshot of CLI flags for replay and inspection.
- `retry_count`: increments when operators resubmit after failure (manual only).
- `error_detail`: optional payload describing failure context.
- `worker_id`: identifier of the worker that claimed the job (format: "hostname:pid"). Set by `claim_next_job()` for debugging/monitoring in multi-daemon deployments. NULL for unclaimed jobs.
- `cancel_requested_at`: timestamp when user requested cancellation (Phase 1). Worker checks this periodically and aborts gracefully if set.
- `staging_cleaned_at`: timestamp when staging database was cleaned up after restore (Phase 1). Prevents re-processing in cleanup runs.
- `status`: `queued`, `running`, `failed`, `complete`, `canceled`. The `canceled` status is set when a job is successfully canceled.
- `active_target_key`: generated virtual column for per-target exclusivity (NULL unless status is queued/running).

Enforce per-target exclusivity with unique index on generated column (MySQL 8.0 doesn't support partial indexes):

```sql
CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);

CREATE INDEX idx_jobs_queue ON jobs(status, submitted_at);

-- Index for worker tracking (Phase 3)
CREATE INDEX idx_jobs_worker_id ON jobs(worker_id);

-- Index for staging cleanup queries (Phase 1)
CREATE INDEX idx_jobs_staging_cleanup ON jobs(dbhost, status, staging_cleaned_at, completed_at);
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
    max_concurrent_restores INT NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
```

- `hostname`: Logical hostname or alias (e.g., `dev-db-01`). Must match the `dbhost` value used in CLI/API. The actual connection FQDN is stored in the referenced secret.
- `credential_ref`: Reference to credentials in AWS Secrets Manager or SSM Parameter Store
  - Format: `aws-secretsmanager:/pulldb/mysql/dev-db-01` (recommended)
  - Format: `aws-ssm:/pulldb/mysql/dev-db-01-credentials` (alternative)
- `max_concurrent_restores`: Maximum number of simultaneous restore operations on this host
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

## Supporting Views & Indices

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
       started_at
FROM jobs
WHERE status IN ('queued','running');

CREATE INDEX idx_jobs_owner_status
    ON jobs(owner_user_id, status);
```

- `active_jobs` powers duplicate detection and status reporting without extra predicates in application code.
- `idx_jobs_owner_status` accelerates per-user status queries in the CLI `status` command.

## Initial Data Population

### Database Hosts (Local + Legacy)

Pre-populate `db_hosts` with a local sandbox plus the three legacy development database servers. Local development uses the sandbox by default; legacy endpoints remain registered (disabled) for explicit overrides:

```sql
-- Local development sandbox (default)
INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440003',
     'localhost',
    'aws-secretsmanager:/pulldb/mysql/localhost-test',
     1,
     TRUE);

-- Development database server
INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('f869577c-752a-4fbd-b257-4e6f8930d77d',
     'dev-db-01',
     'aws-secretsmanager:/pulldb/mysql/dev-db-01',
     1,
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
    ('work_dir', '/var/lib/pulldb/work/');

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

## Daemon-Oriented Triggers

- **jobs_after_insert**: set `submitted_at` to `UTC_TIMESTAMP(6)` (if not provided), insert a matching `job_events` row with `event_type='queued'`.
- **jobs_after_status_update**: whenever `status` changes, append an event snapshot capturing `actor_*` context and `detail` (error text when moving to `failed`).
- **auth_users_after_update_admin**: record admin toggles in `job_events` so audit history remains centralized even before admin tooling exists.

## Deferred Schema (Backlog)

- `job_logs`: retains high-volume worker output once richer telemetry ships.
- `history_cache`: materialized view of completed restores to power `history=` responses.
- `user_concurrency_limits` and `host_concurrency_limits`: override tables for future concurrency policies.
- Additional queue partitions (`priority`, `cancel_requested`) and event types that depend on cancellation or multi-daemon orchestration.
- **Role-Based Access Control (Phase 4)**:
  - Add `role` column to `auth_users` table: `ENUM('user','manager','admin') NOT NULL DEFAULT 'user'`
  - **User Role** (default): Submit and manage own jobs only, view all jobs (read-only)
  - **Manager Role**: View all jobs, cancel/modify assigned users' jobs only
  - **Admin Role**: Full system access including user management and configuration
  - Track role changes in `job_events` with event_type='role_changed'
  - Add authorization checks in CLI and daemon for role-based operations
  - Web interface renders UI components based on role capabilities
- **Hierarchical Manager-User Relationships (Phase 5)**:
  - Add `manager_id` column to `auth_users`: `CHAR(36) NULL, FOREIGN KEY (manager_id) REFERENCES auth_users(user_id)`
  - Users assigned to specific manager for team-based oversight
  - Managers can only action (cancel/modify) jobs for their assigned users
  - Create `manager_of_managers` table:
    ```sql
    CREATE TABLE manager_of_managers (
        manager_id CHAR(36) NOT NULL,
        subordinate_manager_id CHAR(36) NOT NULL,
        assigned_at TIMESTAMP(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),
        assigned_by_user_id CHAR(36) NOT NULL,
        PRIMARY KEY (manager_id, subordinate_manager_id),
        FOREIGN KEY (manager_id) REFERENCES auth_users(user_id),
        FOREIGN KEY (subordinate_manager_id) REFERENCES auth_users(user_id),
        FOREIGN KEY (assigned_by_user_id) REFERENCES auth_users(user_id)
    );
    ```
  - Senior managers inherit visibility of subordinate managers' teams
  - Authorization: managers action only assigned users' jobs, but VIEW all jobs
  - Universal job visibility: all roles can view all jobs (read-only job list)
  - Action permissions: filtered by role and manager assignment
  - Track manager assignments in job_events for audit trail
  - Example hierarchy: Manager A → Users 1-5, Manager B → Users 6-10, Senior Manager C → Managers A+B (sees all 10 users)

Documenting these tables now avoids architectural drift while keeping the prototype schema lean.

## Timestamp Policy

- Every timestamp column uses `CURRENT_TIMESTAMP(6)` with microsecond precision for automatic timestamp insertion.
- MySQL's `TIMESTAMP` type stores UTC values internally and converts based on session time zone.
- Server and application should be configured with `time_zone = '+00:00'` to ensure UTC storage and retrieval.
- Application code should treat values as MySQL TIMESTAMP(6) for easy comparison and ordering.
- When external systems ingest the data, they should not mutate timestamps in place; use new event rows instead.
- Triggers may use `UTC_TIMESTAMP(6)` for explicit UTC timestamp generation when needed.

_This constitution guides the initial implementation and provides a grounded roadmap for the queued enhancements without committing code we are not ready to operate yet._

---

[← Back to Documentation Index](START-HERE.md) · [Architecture →](architecture.md)
