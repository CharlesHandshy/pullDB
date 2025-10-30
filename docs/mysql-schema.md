# pullDB MySQL Schema Constitution

> **Foundation Documents**: This schema implements the architectural principles defined in `../.github/copilot-instructions.md` and coding standards from `../constitution.md`.

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
    created_at TIMESTAMP(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),
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
    status ENUM('queued','running','failed','complete','canceled') NOT NULL,
    submitted_at TIMESTAMP(6) NOT NULL,
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    options_json JSON,
    retry_count INT NOT NULL DEFAULT 0,
    error_detail TEXT,
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);
```

- `target`: sanitized database name (`user_code` + customer token or `qatemplate`).
- `options_json`: frozen snapshot of CLI flags for replay and inspection.
- `retry_count`: increments when operators resubmit after failure (manual only).
- `error_detail`: optional payload describing failure context.
- `status`: only `queued`, `running`, `failed`, `complete` are emitted in the prototype; `canceled` remains reserved for future work.

Enforce per-target exclusivity with a functional index:

```sql
CREATE UNIQUE INDEX idx_jobs_target_active
    ON jobs(target, status)
    WHERE status IN ('queued','running');
```

### job_events

```sql
CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_time TIMESTAMP(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),
    event_type VARCHAR(50) NOT NULL,
    actor_user_id CHAR(36),
    actor_username VARCHAR(255),
    actor_user_code CHAR(6),
    detail TEXT,
    CONSTRAINT fk_events_job FOREIGN KEY (job_id) REFERENCES jobs(id),
    CONSTRAINT fk_events_actor FOREIGN KEY (actor_user_id) REFERENCES auth_users(user_id)
);

CREATE INDEX idx_job_events_job_time
    ON job_events (job_id, event_time);
```

- `event_type`: expected prototype values include `queued`, `running`, `failed`, `complete`, plus `heartbeat` or `note` as needed for troubleshooting.
- Actor columns remain nullable so daemon-generated events can omit operator identity.

### db_hosts

```sql
CREATE TABLE db_hosts (
    dbhost VARCHAR(255) PRIMARY KEY,
    description TEXT,
    credential_ref VARCHAR(255) NOT NULL,
    max_db_count INT NOT NULL,
    last_known_db_count INT NOT NULL DEFAULT 0,
    last_refreshed_at TIMESTAMP(6),
    disabled_at TIMESTAMP(6)
);
```

- `credential_ref`: pointer to the credential material provisioned on the daemon host.
- `max_db_count`: hard ceiling checked before each restore; failure to meet headroom aborts the job.
- `last_known_db_count`: cached observation maintained by the daemon.
- `disabled_at`: allows temporary suspension without losing metadata.

### locks

```sql
CREATE TABLE locks (
    name VARCHAR(255) PRIMARY KEY,
    owner VARCHAR(255) NOT NULL,
    acquired_at TIMESTAMP(6) NOT NULL DEFAULT UTC_TIMESTAMP(6)
);
```

- Locks coordinate single-process access (for example `target:<db>` or `schema:migrate`).
- The daemon releases locks explicitly; watchdog jobs should reclaim abandoned rows.

### settings

```sql
CREATE TABLE settings (
    `key` VARCHAR(255) PRIMARY KEY,
    `value` TEXT NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT UTC_TIMESTAMP(6)
);
```

- Stores JSON or scalar configuration (default extraction directory, default `dbhost`, S3 bucket path, post-restore SQL script directories).
- Prototype keeps the set small; future feature flags can reuse this store.

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

### Database Hosts (Legacy appType Support)

Pre-populate `db_hosts` with the three existing development database servers to support legacy `--type=` behavior via `dbhost=` parameter:

```sql
-- DEV team database server (legacy --type=DEV)
INSERT INTO db_hosts (dbhost, description, credential_ref, max_db_count) VALUES
    ('db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'Development team database server (legacy DEV type)',
     'aws-ssm:/pulldb/db3-dev-credentials',
     1000);

-- SUPPORT team database server (legacy --type=SUPPORT, default)
INSERT INTO db_hosts (dbhost, description, credential_ref, max_db_count) VALUES
    ('db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'Support team database server (legacy SUPPORT type, default)',
     'aws-ssm:/pulldb/db4-dev-credentials',
     1000);

-- IMPLEMENTATION team database server (legacy --type=IMPLEMENTATION)
INSERT INTO db_hosts (dbhost, description, credential_ref, max_db_count) VALUES
    ('db-mysql-db5-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'Implementation team database server (legacy IMPLEMENTATION type)',
     'aws-ssm:/pulldb/db5-dev-credentials',
     1000);
```

### Configuration Settings

Set default `dbhost` to match legacy SUPPORT default and configure other operational parameters:

```sql
-- Default database host (matches legacy SUPPORT default)
INSERT INTO settings (`key`, `value`) VALUES
    ('default_dbhost', 'db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com');

-- S3 backup bucket path
INSERT INTO settings (`key`, `value`) VALUES
    ('s3_bucket_path', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/');

-- Post-restore SQL script directories
INSERT INTO settings (`key`, `value`) VALUES
    ('customers_after_sql_dir', '/opt/pulldb/customers_after_sql/'),
    ('qa_template_after_sql_dir', '/opt/pulldb/qa_template_after_sql/');

-- Default working directory for downloads and extractions
INSERT INTO settings (`key`, `value`) VALUES
    ('work_dir', '/var/lib/pulldb/work/');
```

**Migration Note**: Users of legacy `pullDB-auth --type=SUPPORT` should use `pullDB user=<user> customer=<customer>` (default) or explicitly specify `dbhost=db-mysql-db4-dev` for clarity.

## Daemon-Oriented Triggers

- **jobs_after_insert**: set `submitted_at` to `UTC_TIMESTAMP(6)` (if not provided), insert a matching `job_events` row with `event_type='queued'`.
- **jobs_after_status_update**: whenever `status` changes, append an event snapshot capturing `actor_*` context and `detail` (error text when moving to `failed`).
- **auth_users_after_update_admin**: record admin toggles in `job_events` so audit history remains centralized even before admin tooling exists.

## Deferred Schema (Backlog)

- `job_logs`: retains high-volume worker output once richer telemetry ships.
- `history_cache`: materialized view of completed restores to power `history=` responses.
- `user_concurrency_limits` and `host_concurrency_limits`: override tables for future concurrency policies.
- Additional queue partitions (`priority`, `cancel_requested`) and event types that depend on cancellation or multi-daemon orchestration.

Documenting these tables now avoids architectural drift while keeping the prototype schema lean.

## Timestamp Policy

- Every timestamp column stores UTC values via `UTC_TIMESTAMP(6)` with microsecond precision.
- Application code should treat values as MySQL TIMESTAMP(6) for easy comparison and ordering.
- When external systems ingest the data, they should not mutate timestamps in place; use new event rows instead.

_This constitution guides the initial implementation and provides a grounded roadmap for the queued enhancements without committing code we are not ready to operate yet._
