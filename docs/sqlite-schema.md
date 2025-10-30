# pullDB SQLite Schema Constitution

## Prototype Charter

- **Single source of truth**: SQLite captures every restore request, its lifecycle, and audit breadcrumbs for the CLI and daemon.
- **Lean first release**: only tables required for the minimal restore loop ship in the prototype; everything else waits until the feature lands.
- **Predictable invariants**: constraints enforce unique usernames, per-target job exclusivity, and traceable status transitions.
- **Future-friendly**: deferred structures are documented so we can grow without rewriting foundations.

## Core Tables

### auth_users

```sql
CREATE TABLE auth_users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    user_code TEXT NOT NULL UNIQUE,
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    disabled_at TEXT,
    CHECK (length(user_code) = 6)
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
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    owner_username TEXT NOT NULL,
    owner_user_code TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','failed','complete','canceled')),
    submitted_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    options_json TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_detail TEXT,
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);
```

- `target`: sanitized database name (`user_code` + customer token or `qatemplate`).
- `options_json`: frozen snapshot of CLI flags for replay and inspection.
- `retry_count`: increments when operators resubmit after failure (manual only).
- `error_detail`: optional payload describing failure context.
- `status`: only `queued`, `running`, `failed`, `complete` are emitted in the prototype; `canceled` remains reserved for future work.

Enforce per-target exclusivity with a partial unique index:

```sql
CREATE UNIQUE INDEX idx_jobs_target_active
    ON jobs(target)
    WHERE status IN ('queued','running');
```

### job_events

```sql
CREATE TABLE job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_user_id TEXT,
    actor_username TEXT,
    actor_user_code TEXT,
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
    dbhost TEXT PRIMARY KEY,
    description TEXT,
    credential_ref TEXT NOT NULL,
    max_db_count INTEGER NOT NULL,
    last_known_db_count INTEGER NOT NULL DEFAULT 0,
    last_refreshed_at TEXT,
    disabled_at TEXT
);
```

- `credential_ref`: pointer to the credential material provisioned on the daemon host.
- `max_db_count`: hard ceiling checked before each restore; failure to meet headroom aborts the job.
- `last_known_db_count`: cached observation maintained by the daemon.
- `disabled_at`: allows temporary suspension without losing metadata.

### locks

```sql
CREATE TABLE locks (
    name TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at TEXT NOT NULL
);
```

- Locks coordinate single-process access (for example `target:<db>` or `schema:migrate`).
- The daemon releases locks explicitly; watchdog jobs should reclaim abandoned rows.

### settings

```sql
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

- Stores JSON or scalar configuration (default extraction directory, default `dbhost`, S3 bucket path, obfuscation script references).
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

## Daemon-Oriented Triggers

- **jobs_after_insert**: set `submitted_at` to `strftime` (if not provided), insert a matching `job_events` row with `event_type='queued'`.
- **jobs_after_status_update**: whenever `status` changes, append an event snapshot capturing `actor_*` context and `detail` (error text when moving to `failed`).
- **auth_users_after_update_admin**: record admin toggles in `job_events` so audit history remains centralized even before admin tooling exists.

## Deferred Schema (Backlog)

- `job_logs`: retains high-volume worker output once richer telemetry ships.
- `history_cache`: materialized view of completed restores to power `history=` responses.
- `user_concurrency_limits` and `host_concurrency_limits`: override tables for future concurrency policies.
- Additional queue partitions (`priority`, `cancel_requested`) and event types that depend on cancellation or multi-daemon orchestration.

Documenting these tables now avoids architectural drift while keeping the prototype schema lean.

## Timestamp Policy

- Every timestamp column stores UTC strings via `strftime('%Y-%m-%dT%H:%M:%fZ','now')`.
- Application code should treat values as milliseconds-precision ISO-8601 for easy comparison and ordering.
- When external systems ingest the data, they should not mutate timestamps in place; use new event rows instead.

_This constitution guides the initial implementation and provides a grounded roadmap for the queued enhancements without committing code we are not ready to operate yet._
