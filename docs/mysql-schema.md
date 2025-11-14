# pullDB MySQL Schema Constitution

> **Foundation Documents**: This schema implements the architectural principles defined in `../.github/copilot-instructions.md` and coding standards from `../constitution.md`.

> **Schema Update Mandate**: All schema changes must be reflected in the numbered files under `schema/pulldb/` and mirrored in `scripts/setup-tests-dbdata.sh`. See `.github/copilot-instructions.md` and `docs/mysql-setup.md` for the complete workflow. The legacy `scripts/setup-pulldb-schema.sh` helper now lives in `scripts/archived/` for historical reference.
>
> The former monolithic dump is preserved at `schema/archived/pulldb.sql` for audit history only.

## Prototype Charter

- **Single source of truth**: MySQL captures every restore request, its lifecycle, and audit breadcrumbs for the CLI and daemon.
- **Lean first release**: only tables required for the minimal restore loop ship in the prototype; everything else waits until the feature lands.
- **Predictable invariants**: constraints enforce unique usernames, per-target job exclusivity, and traceable status transitions.
- **Future-friendly**: deferred structures are documented so we can grow without rewriting foundations.

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
- `status`: only `queued`, `running`, `failed`, `complete` are emitted in the prototype; `canceled` remains reserved for future work.
- `active_target_key`: generated virtual column for per-target exclusivity (NULL unless status is queued/running).

Enforce per-target exclusivity with unique index on generated column (MySQL 8.0 doesn't support partial indexes):

```sql
CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);

CREATE INDEX idx_jobs_queue ON jobs(status, submitted_at);
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

- `hostname`: Fully qualified domain name of the target MySQL server
- `credential_ref`: Reference to credentials in AWS Secrets Manager or SSM Parameter Store
  - Format: `aws-secretsmanager:/pulldb/mysql/db3-dev` (recommended)
  - Format: `aws-ssm:/pulldb/mysql/db3-dev-credentials` (alternative)
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
     'aws-secretsmanager:/pulldb/mysql/db-local-dev',
     1,
     TRUE);

-- DEV team database server (legacy --type=DEV)
INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440000',
     'db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db3-dev',
     1,
     FALSE);

-- SUPPORT team database server (legacy --type=SUPPORT)
INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440001',
     'db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db4-dev',
     1,
     FALSE);

-- IMPLEMENTATION team database server (legacy --type=IMPLEMENTATION)
INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440002',
     'db-mysql-db5-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db5-dev',
     1,
     FALSE);
```

**Note**: Credentials for these hosts must be created in AWS Secrets Manager before the Worker service can connect. See `aws-secrets-manager-setup.md` for setup instructions. The local sandbox secret (`/pulldb/mysql/db-local-dev`) is required for development setups; the legacy team secrets remain for historical restores.

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
    ('customers_after_sql_dir', '/opt/pulldb/customers_after_sql/'),
    ('qa_template_after_sql_dir', '/opt/pulldb/qa_template_after_sql/');

-- Default working directory for downloads and extractions
INSERT INTO settings (setting_key, setting_value) VALUES
    ('work_dir', '/var/lib/pulldb/work/');
```

**Migration Note**: Users of legacy `pullDB-auth --type=SUPPORT` should use `pullDB user=<user> customer=<customer>` (default, now targeting the local sandbox) or explicitly specify `dbhost=db-mysql-db4-dev` to reach the legacy SUPPORT host.

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
