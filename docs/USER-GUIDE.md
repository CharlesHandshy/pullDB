# pullDB Complete User Guide

> **Version**: 0.0.4 (Phase 2)  
> **Last Updated**: November 28, 2025

pullDB is an enterprise database restore tool that downloads production database backups from AWS S3 and restores them to development/staging MySQL servers. It provides job queuing, progress tracking, concurrency controls, and atomic database swaps.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [CLI Commands](#cli-commands)
   - [pulldb restore](#pulldb-restore)
   - [pulldb status](#pulldb-status)
   - [pulldb history](#pulldb-history)
   - [pulldb cancel](#pulldb-cancel)
   - [pulldb events](#pulldb-events)
4. [Admin Commands](#admin-commands-pulldb-admin)
   - [pulldb-admin settings](#pulldb-admin-settings)
   - [pulldb-admin jobs](#pulldb-admin-jobs)
   - [pulldb-admin cleanup](#pulldb-admin-cleanup)
5. [Migration Tool](#migration-tool-pulldb-migrate)
6. [Configuration Reference](#configuration-reference)
7. [Database Schema](#database-schema)
8. [Workflow Details](#workflow-details)
9. [Troubleshooting](#troubleshooting)
10. [Service Management](#service-management)

---

## Quick Start

```bash
# Restore a customer database to your development environment
pulldb user=charles customer=acme

# Check the status of your active jobs
pulldb status

# View your job history
pulldb history

# Cancel a running job
pulldb cancel <job_id>

# View detailed events for a job
pulldb events <job_id>
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         pullDB Architecture                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────────────────────┐    │
│  │  pulldb  │───▶│  API Service │───▶│  MySQL Coordination DB      │    │
│  │   CLI    │    │  (optional)  │    │  (pulldb_service)           │    │
│  └──────────┘    └──────────────┘    │  - jobs table               │    │
│                                       │  - job_events table         │    │
│                                       │  - auth_users table         │    │
│                                       │  - settings table           │    │
│                                       │  - db_hosts table           │    │
│                                       └─────────────────────────────┘    │
│                                                      │                   │
│                                                      ▼                   │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      Worker Service                               │   │
│  │                   (pulldb-worker.service)                         │   │
│  │                                                                   │   │
│  │  1. Poll for queued jobs                                          │   │
│  │  2. Download backup from S3                                       │   │
│  │  3. Extract tarball                                               │   │
│  │  4. Run myloader to restore to staging DB                         │   │
│  │  5. Atomic rename: staging → target                               │   │
│  │  6. Cleanup work files                                            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                           │                        │                     │
│                           ▼                        ▼                     │
│  ┌────────────────────────────┐    ┌────────────────────────────────┐   │
│  │        AWS S3              │    │    Target MySQL Server         │   │
│  │  (production backups)      │    │    (dev-db-01, localhost)      │   │
│  │                            │    │                                │   │
│  │  s3://bucket/daily/prod/   │    │    Restored databases:         │   │
│  │    acme/acme-2025-11-28    │    │    - chrles_acme               │   │
│  │    beta/beta-2025-11-28    │    │    - chrles_beta               │   │
│  └────────────────────────────┘    └────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Description | Location |
|-----------|-------------|----------|
| **pulldb CLI** | User-facing command-line tool | `/usr/local/bin/pulldb` |
| **pulldb-admin CLI** | Admin command-line tool | `/usr/local/bin/pulldb-admin` |
| **pulldb-migrate** | Database migration tool | `/opt/pulldb.service/scripts/pulldb-migrate.sh` |
| **Worker Service** | Background job processor | `systemd: pulldb-worker.service` |
| **API Service** | Optional HTTP API | `systemd: pulldb-api.service` |
| **Coordination DB** | MySQL database for job state | `pulldb_service` database |

---

## CLI Commands

### pulldb restore

Submits a database restore job to download a customer backup from S3 and restore it to your development database.

**Syntax:**
```bash
pulldb user=<username> customer=<customer_id> [dbhost=<host>] [date=<YYYY-MM-DD>]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `user=` | **Yes** | - | Your username for job ownership and database naming |
| `customer=` | **Yes** | - | Customer identifier matching S3 backup path |
| `dbhost=` | No | `localhost` | Target database host (must be registered in `db_hosts`) |
| `date=` | No | Latest | Specific backup date in `YYYY-MM-DD` format |

**Examples:**

```bash
# Basic restore - uses all defaults
pulldb user=charles customer=acme

# Restore to a specific database host
pulldb user=charles customer=acme dbhost=dev-db-01

# Restore a specific date's backup
pulldb user=charles customer=acme date=2025-11-27

# Full specification
pulldb user=charles customer=acme dbhost=dev-db-01 date=2025-11-27
```

**Target Database Naming:**

Your restored database is named using your **user_code** (6-character identifier) plus the customer name:

```
<user_code>_<customer>
```

Example: User `charles` with user_code `CHRLES` restoring customer `acme`:
- **Target database**: `chrles_acme`
- **Staging database**: `chrles_acme_abc123de1234` (temporary, cleaned up after)

**Response:**
```
Job submitted successfully.
  Job ID: abc123de-f456-7890-abcd-ef1234567890
  Target: chrles_acme
  Status: queued

Track progress with: pulldb status abc123de-f456-7890-abcd-ef1234567890
```

**Concurrency Rules (Phase 2):**
- Each user has a limit on concurrent active jobs (`max_active_jobs_per_user`)
- System has a global limit (`max_active_jobs_global`)
- Only one job can target the same database at a time (enforced by unique index)

---

### pulldb status

Shows the status of your active (queued/running) jobs.

**Syntax:**
```bash
pulldb status [job_id]
```

**Examples:**

```bash
# Show all your active jobs
pulldb status

# Show details for a specific job
pulldb status abc123de-f456-7890-abcd-ef1234567890
```

**Output (all active jobs):**
```
Active Jobs for charles:

  Job ID: abc123de-f456-7890-abcd-ef1234567890
  Target: chrles_acme @ localhost
  Status: running
  Submitted: 2025-11-28 10:30:00
  Started: 2025-11-28 10:30:05

  Job ID: def456ab-c789-0123-defg-hi4567890123
  Target: chrles_beta @ dev-db-01
  Status: queued
  Submitted: 2025-11-28 10:35:00
  Started: -

Total: 2 active jobs
```

**Output (specific job):**
```
Job Details:

  Job ID: abc123de-f456-7890-abcd-ef1234567890
  Owner: charles
  Target: chrles_acme
  Host: localhost
  Status: running
  
  Submitted: 2025-11-28 10:30:00
  Started: 2025-11-28 10:30:05
  Completed: -
  
  Options: {"date": "2025-11-28"}
```

---

### pulldb history

Shows your completed job history (successful, failed, or canceled jobs).

**Syntax:**
```bash
pulldb history [--limit=N]
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--limit=` | 10 | Number of recent jobs to show |

**Examples:**

```bash
# Show last 10 jobs (default)
pulldb history

# Show last 50 jobs
pulldb history --limit=50
```

**Output:**
```
Job History for charles:

  ID            Target           Host        Status     Completed
  ────────────  ───────────────  ──────────  ─────────  ────────────────────
  abc123de...   chrles_acme      localhost   complete   2025-11-28 10:45:00
  def456ab...   chrles_beta      dev-db-01   failed     2025-11-27 15:30:00
  ghi789cd...   chrles_gamma     localhost   canceled   2025-11-26 09:15:00

Showing 3 of 3 jobs
```

---

### pulldb cancel

Cancels a queued or running job. You can only cancel your own jobs.

**Syntax:**
```bash
pulldb cancel <job_id>
```

**Examples:**

```bash
pulldb cancel abc123de-f456-7890-abcd-ef1234567890
```

**Behavior:**
- **Queued jobs**: Canceled immediately, status changes to `canceled`
- **Running jobs**: Marked with `cancel_requested_at` timestamp; worker checks periodically and aborts gracefully
- **Completed/Failed jobs**: Cannot be canceled (already finished)

**Output:**
```
Job abc123de-f456-7890-abcd-ef1234567890 has been marked for cancellation.
The worker will stop the job at the next checkpoint.
```

---

### pulldb events

Shows the detailed event log for a specific job, useful for debugging and monitoring progress.

**Syntax:**
```bash
pulldb events <job_id>
```

**Examples:**

```bash
pulldb events abc123de-f456-7890-abcd-ef1234567890
```

**Output:**
```
Events for job abc123de-f456-7890-abcd-ef1234567890:

  Timestamp              Event Type    Detail
  ─────────────────────  ────────────  ─────────────────────────────────────
  2025-11-28 10:30:00    queued        Job submitted by charles
  2025-11-28 10:30:05    running       Worker picked up job
  2025-11-28 10:32:00    note          Starting S3 download
  2025-11-28 10:35:00    note          Download complete: 2.3 GB in 3m
  2025-11-28 10:35:30    note          Extracting tarball
  2025-11-28 10:36:00    note          Starting myloader restore
  2025-11-28 10:40:00    note          myloader: 50% complete (125/250 tables)
  2025-11-28 10:44:00    note          myloader: 100% complete
  2025-11-28 10:44:30    note          Performing atomic rename
  2025-11-28 10:45:00    complete      Restore finished successfully

Total: 10 events
```

**Event Types:**

| Event Type | Description |
|------------|-------------|
| `queued` | Job was submitted and is waiting |
| `running` | Worker started processing |
| `note` | Progress or informational message |
| `heartbeat` | Worker is alive (for long operations) |
| `failed` | Job failed with error |
| `complete` | Job finished successfully |
| `canceled` | Job was canceled by user |

---

## Admin Commands (pulldb-admin)

Admin commands require elevated privileges and affect system-wide settings or other users' jobs.

### pulldb-admin settings

View or modify system settings, including concurrency limits.

**Syntax:**
```bash
# View all settings
pulldb-admin settings

# View specific setting
pulldb-admin settings <key>

# Update a setting
pulldb-admin settings <key>=<value>
```

**Examples:**

```bash
# View all settings
pulldb-admin settings

# View concurrency settings
pulldb-admin settings max_active_jobs_per_user
pulldb-admin settings max_active_jobs_global

# Set per-user limit to 3 concurrent jobs
pulldb-admin settings max_active_jobs_per_user=3

# Set global limit to 10 concurrent jobs
pulldb-admin settings max_active_jobs_global=10

# Disable limits (0 = unlimited)
pulldb-admin settings max_active_jobs_per_user=0
```

**Output (view all):**
```
System Settings:

  Key                        Value                                              Description
  ─────────────────────────  ─────────────────────────────────────────────────  ────────────────────────────────────
  default_dbhost             localhost                                          Default database host
  s3_bucket_path             pestroutes-rds-backup-prod-vpc-us-east-1-s3/...    S3 backup bucket path
  work_dir                   /var/lib/pulldb/work/                              Working directory for downloads
  max_active_jobs_per_user   3                                                  Max concurrent jobs per user (0=unlimited)
  max_active_jobs_global     10                                                 Max concurrent jobs system-wide (0=unlimited)
```

**Available Settings:**

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `default_dbhost` | string | `localhost` | Default target database host |
| `s3_bucket_path` | string | - | S3 bucket and prefix for backups |
| `work_dir` | string | `/var/lib/pulldb/work/` | Temporary directory for downloads |
| `max_active_jobs_per_user` | int | `0` | Max concurrent jobs per user (0=unlimited) |
| `max_active_jobs_global` | int | `0` | Max concurrent jobs system-wide (0=unlimited) |

---

### pulldb-admin jobs

View and manage all jobs across all users.

**Syntax:**
```bash
# View all active jobs
pulldb-admin jobs --active

# View all jobs (with limit)
pulldb-admin jobs --limit=100

# View jobs for specific user
pulldb-admin jobs --user=charles

# View jobs for specific host
pulldb-admin jobs --dbhost=dev-db-01
```

**Examples:**

```bash
# See all currently active jobs
pulldb-admin jobs --active

# See recent jobs from all users
pulldb-admin jobs --limit=50
```

**Output:**
```
All Active Jobs:

  Job ID        Owner     Target           Host        Status    Submitted
  ────────────  ────────  ───────────────  ──────────  ────────  ────────────────────
  abc123de...   charles   chrles_acme      localhost   running   2025-11-28 10:30:00
  def456ab...   alice     alice_beta       dev-db-01   queued    2025-11-28 10:35:00
  ghi789cd...   bob       bob_gamma        localhost   running   2025-11-28 10:32:00

Total: 3 active jobs
  Running: 2
  Queued: 1
```

---

### pulldb-admin cleanup

Manages cleanup of orphaned staging databases and old work files.

**Syntax:**
```bash
# Preview what would be cleaned (dry run)
pulldb-admin cleanup --dry-run

# Execute cleanup
pulldb-admin cleanup --execute

# Cleanup specific host only
pulldb-admin cleanup --dbhost=localhost --execute
```

**Examples:**

```bash
# See what staging databases would be cleaned up
pulldb-admin cleanup --dry-run

# Actually perform the cleanup
pulldb-admin cleanup --execute
```

**Output (dry run):**
```
Cleanup Preview (DRY RUN):

Orphaned Staging Databases:
  - chrles_acme_abc123de1234 (job completed 2025-11-27, staging not cleaned)
  - alice_beta_def456ab5678 (job failed 2025-11-26, staging not cleaned)

Old Work Directories:
  - /var/lib/pulldb/work/abc123de-f456-7890-abcd-ef1234567890/ (3.2 GB)
  - /var/lib/pulldb/work/def456ab-c789-0123-defg-hi4567890123/ (1.8 GB)

Total: 2 databases, 2 directories (5.0 GB)

Run with --execute to perform cleanup.
```

---

## Migration Tool (pulldb-migrate)

The `pulldb-migrate` tool manages database schema migrations using [dbmate](https://github.com/amacneil/dbmate).

**Location:** `/opt/pulldb.service/scripts/pulldb-migrate.sh`

### Commands

```bash
# Check migration status
sudo pulldb-migrate status

# Apply pending migrations
sudo pulldb-migrate up

# Apply migrations non-interactively
sudo pulldb-migrate up --yes

# Rollback last migration
sudo pulldb-migrate rollback

# Verify schema integrity
sudo pulldb-migrate verify

# Create new migration file
sudo pulldb-migrate new add_feature_table

# Baseline existing database (mark all as applied)
sudo pulldb-migrate baseline

# Wait for database availability
sudo pulldb-migrate wait
```

### Migration Status Output

```bash
$ sudo pulldb-migrate status

[INFO] Checking migration status...
[X] 20250101000000_initial_schema.sql
[X] 20250115000000_add_cancel_requested.sql
[X] 20250116000000_add_staging_cleaned.sql
[X] 20250120000000_seed_hosts.sql
[X] 20250121000000_seed_settings.sql
[X] 20250128000000_phase2_concurrency.sql
[X] 20251128051147_repair_missing_columns.sql

Applied: 7
Pending: 0
```

### Schema Verification

```bash
$ sudo pulldb-migrate verify

[INFO] Verifying schema...
[INFO] Schema verification passed
[INFO]   - All required tables present
[INFO]   - Applied migrations: 7
[INFO]   - Phase 2 settings: OK
```

### Authentication

The migration tool uses **socket authentication** for localhost MySQL connections (no password required when running as root). For remote connections, it uses AWS Secrets Manager credentials.

Priority:
1. `DATABASE_URL` environment variable (explicit override)
2. Unix socket auth (localhost, preferred)
3. AWS Secrets Manager (remote/fallback)

---

## Configuration Reference

### Environment Variables

Located in `/opt/pulldb.service/.env`:

```bash
# === Coordination Database ===
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_PORT=3306
PULLDB_MYSQL_DATABASE=pulldb_service

# === AWS Configuration ===
PULLDB_AWS_PROFILE=pr-dev              # For Secrets Manager
PULLDB_S3_AWS_PROFILE=pr-prod          # For S3 backup access
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db

# === Migration User (optional) ===
PULLDB_MIGRATION_MYSQL_USER=pulldb_migrate

# === Worker Configuration ===
PULLDB_WORK_DIR=/var/lib/pulldb/work
PULLDB_LOG_LEVEL=INFO
```

### File Locations

| Path | Description |
|------|-------------|
| `/opt/pulldb.service/` | Main installation directory |
| `/opt/pulldb.service/.env` | Environment configuration |
| `/opt/pulldb.service/venv/` | Python virtual environment |
| `/opt/pulldb.service/scripts/` | Operational scripts |
| `/opt/pulldb.service/migrations/` | Database migrations |
| `/var/lib/pulldb/work/` | Working directory for downloads |
| `/var/log/pulldb/` | Log files |

### Registered Database Hosts

Hosts must be registered in the `db_hosts` table to be used as targets:

```sql
SELECT hostname, credential_ref, max_concurrent_restores, enabled 
FROM db_hosts;
```

| hostname | credential_ref | max_concurrent_restores | enabled |
|----------|----------------|-------------------------|---------|
| localhost | aws-secretsmanager:/pulldb/mysql/localhost-test | 1 | true |
| dev-db-01 | aws-secretsmanager:/pulldb/mysql/dev-db-01 | 2 | true |

---

## Database Schema

### Core Tables

#### `auth_users`
Stores authenticated users and their identifiers.

```sql
CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,    -- Used in database naming
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL
);
```

#### `jobs`
Stores all restore jobs and their state.

```sql
CREATE TABLE jobs (
    id CHAR(36) PRIMARY KEY,
    owner_user_id CHAR(36) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    owner_user_code CHAR(6) NOT NULL,
    target VARCHAR(255) NOT NULL,           -- Final database name
    staging_name VARCHAR(64) NOT NULL,      -- Temporary database name
    dbhost VARCHAR(255) NOT NULL,           -- Target host
    status ENUM('queued','running','failed','complete','canceled') NOT NULL,
    submitted_at TIMESTAMP(6) NOT NULL,
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    options_json JSON,                      -- CLI options snapshot
    retry_count INT NOT NULL DEFAULT 0,
    error_detail TEXT,
    cancel_requested_at TIMESTAMP(6) NULL,  -- Phase 1: cancellation support
    staging_cleaned_at TIMESTAMP(6) NULL,   -- Phase 1: cleanup tracking
    -- Virtual column for per-target exclusivity
    active_target_key VARCHAR(520) GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued','running') THEN CONCAT(target,'@@',dbhost) ELSE NULL END
    ) VIRTUAL
);
```

#### `job_events`
Stores detailed event log for each job.

```sql
CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail TEXT,
    logged_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
```

#### `settings`
Stores system configuration.

```sql
CREATE TABLE settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
);
```

#### `db_hosts`
Registered target database hosts.

```sql
CREATE TABLE db_hosts (
    id CHAR(36) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    credential_ref VARCHAR(512) NOT NULL,  -- AWS secret reference
    max_concurrent_restores INT NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
```

---

## Workflow Details

### Complete Restore Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RESTORE WORKFLOW                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. USER SUBMITS JOB                                                     │
│     $ pulldb user=charles customer=acme                                  │
│                                                                          │
│     ┌─────────────────────────────────────────────────────────────┐     │
│     │ Validation:                                                  │     │
│     │ - User exists in auth_users                                  │     │
│     │ - Customer backup exists in S3                               │     │
│     │ - dbhost is registered and enabled                           │     │
│     │ - No active job for same target                              │     │
│     │ - User under concurrency limit                               │     │
│     │ - System under global concurrency limit                      │     │
│     └─────────────────────────────────────────────────────────────┘     │
│                              │                                           │
│                              ▼                                           │
│  2. JOB QUEUED                                                           │
│     - Insert into jobs table (status='queued')                           │
│     - Insert job_event (event_type='queued')                             │
│     - Return job_id to user                                              │
│                              │                                           │
│                              ▼                                           │
│  3. WORKER PICKS UP JOB                                                  │
│     - Poll for oldest queued job                                         │
│     - Update status='running', set started_at                            │
│     - Insert job_event (event_type='running')                            │
│                              │                                           │
│                              ▼                                           │
│  4. S3 DOWNLOAD                                                          │
│     - Locate backup: s3://bucket/daily/prod/acme/acme-2025-11-28.tar.gz  │
│     - Stream download to: /var/lib/pulldb/work/<job_id>/backup.tar.gz   │
│     - Log progress events                                                │
│     - Check cancel_requested_at periodically                             │
│                              │                                           │
│                              ▼                                           │
│  5. EXTRACT TARBALL                                                      │
│     - Extract to: /var/lib/pulldb/work/<job_id>/extracted/              │
│     - Locate metadata file (handles nested directories)                  │
│     - Validate backup structure                                          │
│                              │                                           │
│                              ▼                                           │
│  6. MYLOADER RESTORE                                                     │
│     - Create staging database: chrles_acme_<job_id_prefix>              │
│     - Run myloader with optimized settings                               │
│     - Stream progress (table counts)                                     │
│     - Check cancel_requested_at periodically                             │
│                              │                                           │
│                              ▼                                           │
│  7. POST-RESTORE SQL (optional)                                          │
│     - Execute customer-specific SQL scripts                              │
│     - Apply data transformations                                         │
│                              │                                           │
│                              ▼                                           │
│  8. ATOMIC RENAME                                                        │
│     ┌─────────────────────────────────────────────────────────────┐     │
│     │ Transaction:                                                 │     │
│     │ 1. RENAME DATABASE chrles_acme TO chrles_acme_old           │     │
│     │ 2. RENAME DATABASE chrles_acme_staging TO chrles_acme       │     │
│     │ 3. DROP DATABASE chrles_acme_old                            │     │
│     └─────────────────────────────────────────────────────────────┘     │
│                              │                                           │
│                              ▼                                           │
│  9. CLEANUP                                                              │
│     - Drop staging database (if not renamed)                             │
│     - Remove work directory                                              │
│     - Set staging_cleaned_at                                             │
│                              │                                           │
│                              ▼                                           │
│  10. JOB COMPLETE                                                        │
│      - Update status='complete', set completed_at                        │
│      - Insert job_event (event_type='complete')                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Cancellation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CANCELLATION FLOW                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  User: $ pulldb cancel <job_id>                                          │
│                                                                          │
│  ┌──────────────────────┐     ┌──────────────────────────────────────┐  │
│  │ If status='queued'   │     │ If status='running'                  │  │
│  │                      │     │                                      │  │
│  │ 1. Set status=       │     │ 1. Set cancel_requested_at=NOW()     │  │
│  │    'canceled'        │     │ 2. Worker checks this flag           │  │
│  │ 2. Immediate cancel  │     │    periodically during:              │  │
│  │                      │     │    - Download                        │  │
│  └──────────────────────┘     │    - myloader restore                │  │
│                               │ 3. Worker aborts gracefully          │  │
│                               │ 4. Cleanup staging/work files        │  │
│                               │ 5. Set status='canceled'             │  │
│                               └──────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### Common Errors

#### "Concurrency limit reached"

**Cause:** You've hit the per-user or global job limit.

**Solution:**
```bash
# Check your active jobs
pulldb status

# Wait for jobs to complete, or cancel one
pulldb cancel <job_id>

# Admin can check/adjust limits
pulldb-admin settings max_active_jobs_per_user
pulldb-admin settings max_active_jobs_per_user=5
```

#### "Target database already has active job"

**Cause:** Another job is already restoring to the same target database.

**Solution:**
```bash
# Check what's running for that target
pulldb status

# Wait for it to complete or cancel it
pulldb cancel <job_id>
```

#### "Backup not found for customer"

**Cause:** The customer/date combination doesn't exist in S3.

**Solution:**
```bash
# Try without date (uses latest)
pulldb user=charles customer=acme

# Check available backups (requires S3 access)
aws s3 ls s3://bucket/daily/prod/acme/
```

#### "Database host not found or disabled"

**Cause:** The specified `dbhost` is not registered or is disabled.

**Solution:**
```bash
# Check registered hosts
sudo mysql -e "SELECT hostname, enabled FROM pulldb_service.db_hosts"

# Use a valid host
pulldb user=charles customer=acme dbhost=localhost
```

#### Job stuck in "running" state

**Cause:** Worker crashed or job is taking too long.

**Solution:**
```bash
# Check worker service status
sudo systemctl status pulldb-worker.service

# View worker logs
sudo journalctl -u pulldb-worker.service -n 100 -f

# Restart worker if needed
sudo systemctl restart pulldb-worker.service

# If job is truly stuck, admin can investigate
pulldb-admin jobs --active
```

### Diagnostic Commands

```bash
# Check service health
sudo systemctl status pulldb-worker.service
sudo systemctl status pulldb-api.service

# View real-time worker logs
sudo journalctl -u pulldb-worker.service -f

# Check database connectivity
sudo mysql -e "SELECT 1 FROM pulldb_service.settings LIMIT 1"

# Verify schema
sudo pulldb-migrate verify

# Check migration status
sudo pulldb-migrate status

# View all active jobs
sudo mysql -e "SELECT id, owner_username, target, status, submitted_at FROM pulldb_service.jobs WHERE status IN ('queued','running')"

# Check concurrency settings
sudo mysql -e "SELECT * FROM pulldb_service.settings WHERE setting_key LIKE 'max_%'"
```

---

## Service Management

### SystemD Services

```bash
# Worker service (required)
sudo systemctl start pulldb-worker.service
sudo systemctl stop pulldb-worker.service
sudo systemctl restart pulldb-worker.service
sudo systemctl status pulldb-worker.service
sudo systemctl enable pulldb-worker.service   # Start on boot

# API service (optional)
sudo systemctl start pulldb-api.service
sudo systemctl stop pulldb-api.service
sudo systemctl restart pulldb-api.service
sudo systemctl status pulldb-api.service
```

### Log Viewing

```bash
# Worker logs (live)
sudo journalctl -u pulldb-worker.service -f

# Worker logs (recent)
sudo journalctl -u pulldb-worker.service -n 100

# Worker logs (since time)
sudo journalctl -u pulldb-worker.service --since "1 hour ago"

# API logs
sudo journalctl -u pulldb-api.service -f
```

### Upgrade Procedure

```bash
# Install new package
sudo dpkg -i pulldb_0.0.4_amd64.deb

# Run upgrade script (stops services, applies migrations, restarts)
sudo /opt/pulldb.service/scripts/upgrade_pulldb.sh

# Or manually:
sudo systemctl stop pulldb-worker.service
sudo pulldb-migrate up --yes
sudo systemctl start pulldb-worker.service
```

### Health Checks

```bash
# Quick health check
sudo /opt/pulldb.service/scripts/service-validate.sh

# Verify database schema
sudo pulldb-migrate verify

# Test MySQL connectivity
sudo mysql -e "SELECT COUNT(*) as active_jobs FROM pulldb_service.jobs WHERE status='running'"
```

---

## Version History

| Version | Date | Features |
|---------|------|----------|
| 0.0.4 | 2025-11-28 | Phase 2: Concurrency controls, dbmate migrations, socket auth |
| 0.0.3 | 2025-11-26 | Phase 1: Cancel support, staging cleanup tracking, atomic rename |
| 0.0.2 | 2025-11-15 | Initial beta: Basic restore workflow |
| 0.0.1 | 2025-11-01 | Alpha release |

---

## Support

For issues or questions:
1. Check this guide's [Troubleshooting](#troubleshooting) section
2. View worker logs: `sudo journalctl -u pulldb-worker.service -n 100`
3. Check job events: `pulldb events <job_id>`
4. Contact the development team
