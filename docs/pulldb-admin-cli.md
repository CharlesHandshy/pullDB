# pulldb-admin CLI Reference

> **Version**: 0.0.4 | **Last Updated**: November 28, 2025

The `pulldb-admin` CLI provides administrative commands for system-wide settings, job management, and maintenance operations.

---

## Quick Start

```bash
# View all settings
pulldb-admin settings list

# Update concurrency limits (updates both db AND .env)
pulldb-admin settings set max_active_jobs_per_user 3

# View all active jobs
pulldb-admin jobs list --active

# Audit settings drift between db and .env
pulldb-admin settings diff

# Cleanup orphaned resources
pulldb-admin cleanup --dry-run
```

---

## Commands

### settings

View or modify system configuration settings. Settings can be stored in both the database and `.env` file.

**Subcommands:**
```bash
pulldb-admin settings list              # List all settings with sources
pulldb-admin settings get <key>         # Get setting from both db AND .env
pulldb-admin settings set <key> <value> # Set in both db AND .env (default)
pulldb-admin settings reset <key>       # Reset setting (remove from db)
pulldb-admin settings export            # Export all settings
pulldb-admin settings diff              # Show differences: db ↔ .env
pulldb-admin settings pull              # Sync: database → .env file
pulldb-admin settings push              # Sync: .env file → database
```

**Examples:**

```bash
# View all settings
pulldb-admin settings list

# View all settings including unset ones
pulldb-admin settings list --all

# View specific setting (shows both db and env values)
pulldb-admin settings get max_active_jobs_per_user

# Set value in BOTH database AND .env (default behavior)
pulldb-admin settings set max_active_jobs_per_user 3

# Set only in database
pulldb-admin settings set max_active_jobs_per_user 3 --db-only

# Set only in .env file
pulldb-admin settings set max_active_jobs_per_user 3 --env-only

# Set with description
pulldb-admin settings set max_active_jobs_per_user 3 -d "Limit for Phase 2"

# Reset to environment/default value
pulldb-admin settings reset max_active_jobs_per_user

# Export as environment variables
pulldb-admin settings export

# Export as JSON
pulldb-admin settings export --format=json

# Show differences between db and .env
pulldb-admin settings diff

# Sync database → .env file (preview)
pulldb-admin settings pull --dry-run

# Sync database → .env file
pulldb-admin settings pull

# Sync .env file → database (preview)
pulldb-admin settings push --dry-run

# Sync .env file → database  
pulldb-admin settings push
```

**Output (get):**
```
Setting: max_active_jobs_per_user
Description: Maximum active jobs per user (0=unlimited)
Environment variable: PULLDB_MAX_ACTIVE_JOBS_PER_USER

  db:      3
  env:     5
  default: 0

  effective: 3 (from database)
```

**Output (diff):**
```
Comparing database vs .env file (/opt/pulldb.service/.env)

DIFFERENCES (db ≠ env):
------------------------------------------------------------
  max_active_jobs_per_user:
    db:  3
    env: 5

DATABASE ONLY (not in .env):
------------------------------------------------------------
  custom_setting: some_value

.ENV ONLY (not in database):
------------------------------------------------------------
  myloader_threads (PULLDB_MYLOADER_THREADS): 16

MATCHING: 8 setting(s) are in sync

Summary:
  Differences: 1
  DB only:     1
  .env only:   1
  In sync:     8

Use 'pulldb-admin settings pull' to sync db → .env
Use 'pulldb-admin settings push' to sync .env → db
```

**Output (list):**
```
SETTING                    SOURCE       VALUE
-------------------------  -----------  ----------------------------------------
myloader_binary            default      /opt/pulldb.service/bin/myloader-0.19.3-3
myloader_threads           database     8
max_active_jobs_per_user   database     3
max_active_jobs_global     environment  10
work_dir                   default      /opt/pulldb.service/work

5 setting(s) displayed.

Use 'pulldb-admin settings get <key>' for full value.
Use 'pulldb-admin settings set <key> <value>' to override in database.
```

**Available Settings:**

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `myloader_binary` | string | `/opt/pulldb.service/bin/myloader-0.19.3-3` | Path to myloader binary |
| `myloader_threads` | int | `8` | Number of parallel restore threads |
| `myloader_timeout_seconds` | int | `7200` | Maximum execution time |
| `work_dir` | string | `/opt/pulldb.service/work` | Working directory |
| `max_active_jobs_per_user` | int | `0` | Per-user job limit (0=unlimited) |
| `max_active_jobs_global` | int | `0` | System-wide job limit (0=unlimited) |

**Setting Priority:** Database > Environment > Default

---

### jobs

View and manage jobs across all users.

**Subcommands:**
```bash
pulldb-admin jobs list [OPTIONS]        # List jobs
pulldb-admin jobs cancel <job_id> [-f]  # Cancel a job
```

**List Options:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--active` | - | Show only active jobs (queued/running) |
| `--limit=N` | 20 | Number of jobs to show |
| `--user=` | - | Filter by username or user_code |
| `--dbhost=` | - | Filter by target host |
| `--status=` | - | Filter by status (queued/running/complete/failed/canceled) |
| `--json` | - | Output JSON instead of table |

**Cancel Options:**

| Parameter | Description |
|-----------|-------------|
| `-f, --force` | Skip confirmation prompt |

**Examples:**

```bash
# All active jobs across all users
pulldb-admin jobs list --active

# Recent jobs from specific user
pulldb-admin jobs list --user=charles --limit=50

# Failed jobs on specific host
pulldb-admin jobs list --dbhost=dev-db-01 --status=failed

# All running jobs
pulldb-admin jobs list --status=running

# Cancel a job (with confirmation)
pulldb-admin jobs cancel abc123de

# Cancel a job (skip confirmation)
pulldb-admin jobs cancel abc123de --force
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

### cleanup

Manages cleanup of orphaned staging databases and old work files.

**Syntax:**
```bash
# Preview cleanup (dry run)
pulldb-admin cleanup --dry-run

# Execute cleanup
pulldb-admin cleanup --execute

# Target specific host
pulldb-admin cleanup --dbhost=<host> --execute

# Set age threshold
pulldb-admin cleanup --older-than=<hours> --execute
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--dry-run` | - | Preview what would be cleaned (no changes) |
| `--execute` | - | Actually perform the cleanup |
| `--dbhost=` | All hosts | Target specific database host |
| `--older-than=` | 24 | Only clean items older than N hours |

**Examples:**

```bash
# Preview cleanup
pulldb-admin cleanup --dry-run

# Execute cleanup on all hosts
pulldb-admin cleanup --execute

# Cleanup only localhost
pulldb-admin cleanup --dbhost=localhost --execute

# Cleanup items older than 48 hours
pulldb-admin cleanup --older-than=48 --execute
```

**Output (dry run):**
```
Cleanup Preview (DRY RUN):

Orphaned Staging Databases:
  localhost:
    - chrles_acme_abc123de1234 (job completed 2025-11-27)
    - alice_beta_def456ab5678 (job failed 2025-11-26)
  
  dev-db-01:
    - bob_gamma_ghi789cd9012 (job completed 2025-11-25)

Old Work Directories:
  - /var/lib/pulldb/work/abc123de-f456-7890-abcd-ef1234567890/ (3.2 GB)
  - /var/lib/pulldb/work/def456ab-c789-0123-defg-hi4567890123/ (1.8 GB)

Summary:
  Staging databases: 3
  Work directories: 2
  Total space: 5.0 GB

Run with --execute to perform cleanup.
```

**Output (execute):**
```
Cleanup Executed:

Dropped Staging Databases:
  ✓ chrles_acme_abc123de1234 (localhost)
  ✓ alice_beta_def456ab5678 (localhost)
  ✓ bob_gamma_ghi789cd9012 (dev-db-01)

Removed Work Directories:
  ✓ /var/lib/pulldb/work/abc123de-f456-7890-abcd-ef1234567890/ (3.2 GB)
  ✓ /var/lib/pulldb/work/def456ab-c789-0123-defg-hi4567890123/ (1.8 GB)

Cleanup Complete:
  Databases dropped: 3
  Directories removed: 2
  Space freed: 5.0 GB
```

**What Gets Cleaned:**

| Resource | Criteria |
|----------|----------|
| Staging databases | Job completed/failed, `staging_cleaned_at` is NULL |
| Work directories | Job completed/failed, directory exists |

---

### hosts

Manage registered database hosts.

**Subcommands:**
```bash
pulldb-admin hosts list [OPTIONS]       # List all hosts
pulldb-admin hosts add <hostname>       # Add a new host
pulldb-admin hosts enable <hostname>    # Enable a host
pulldb-admin hosts disable <hostname>   # Disable a host
```

**List Options:**

| Parameter | Description |
|-----------|-------------|
| `--json` | Output JSON instead of table |

**Add Options:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--max-concurrent=N` | 1 | Maximum concurrent jobs on this host |
| `--credential-ref=` | - | AWS Secrets Manager reference for credentials |

**Examples:**

```bash
# List all registered hosts
pulldb-admin hosts list

# Add a new host
pulldb-admin hosts add dev-db-02 --max-concurrent=2 --credential-ref=aws-secretsmanager:/pulldb/mysql/dev-db-02

# Disable a host (prevents new jobs)
pulldb-admin hosts disable dev-db-01

# Re-enable a host
pulldb-admin hosts enable dev-db-01
```

**Output:**
```
Registered Database Hosts:

  Hostname     Max Concurrent  Enabled  Credential Reference
  ───────────  ──────────────  ───────  ─────────────────────────────────────
  localhost    1               Yes      aws-secretsmanager:/pulldb/mysql/localhost-test
  dev-db-01    2               Yes      aws-secretsmanager:/pulldb/mysql/dev-db-01

Total: 2 hosts (2 enabled)
```

---

### users

View and manage users.

**Subcommands:**
```bash
pulldb-admin users list [OPTIONS]       # List all users
pulldb-admin users show <username>      # Show user details
pulldb-admin users enable <username>    # Enable a user
pulldb-admin users disable <username>   # Disable a user
```

**List Options:**

| Parameter | Description |
|-----------|-------------|
| `--json` | Output JSON instead of table |

**Examples:**

```bash
# List all users
pulldb-admin users list

# Show detailed user info
pulldb-admin users show charles

# Disable a user (prevents new jobs)
pulldb-admin users disable charles

# Re-enable a user
pulldb-admin users enable charles
```

**Output:**
```
Registered Users:

  Username     User Code  Admin  Active Jobs  Created
  ───────────  ─────────  ─────  ───────────  ────────────────────
  charles      CHRLES     No     2            2025-11-01 09:00:00
  alice        ALICE1     No     1            2025-11-05 10:30:00
  bob          BOBXYZ     No     0            2025-11-10 14:15:00
  admin        ADMN01     Yes    0            2025-10-15 08:00:00

Total: 4 users
```

---

## Concurrency Management

### Understanding Limits

| Setting | Scope | Effect |
|---------|-------|--------|
| `max_active_jobs_per_user` | Per user | Limits how many jobs one user can have active |
| `max_active_jobs_global` | System-wide | Limits total active jobs across all users |

**Setting to 0 means unlimited.**

### Recommended Settings

| Environment | Per-User | Global | Rationale |
|-------------|----------|--------|-----------|
| Development | 3 | 10 | Prevent resource exhaustion |
| Production | 2 | 5 | Conservative limits |
| Unlimited | 0 | 0 | No restrictions (default) |

### Monitoring Concurrency

```bash
# Check current limits
pulldb-admin settings get max_active_jobs_per_user
pulldb-admin settings get max_active_jobs_global

# See current active job count
pulldb-admin jobs list --active

# Check per-user breakdown
pulldb-admin jobs list --active | grep -E "Owner|Total"
```

---

## Maintenance Tasks

### Daily Cleanup

```bash
# Preview orphaned resources
pulldb-admin cleanup --dry-run

# Clean up if needed
pulldb-admin cleanup --execute
```

### Health Check

```bash
# Check active jobs
pulldb-admin jobs list --active

# Check for stuck jobs (running too long)
pulldb-admin jobs list --status=running

# Verify settings
pulldb-admin settings list
```

### Emergency: Disable All Restores

```bash
# Set global limit to 1 active job
pulldb-admin settings set max_active_jobs_global 1

# Wait for current jobs to complete
pulldb-admin jobs list --active

# Or disable specific host
pulldb-admin hosts disable dev-db-01
```

---

## Troubleshooting

### Too Many Active Jobs

```bash
# Check current counts
pulldb-admin jobs list --active

# Identify heavy users
pulldb-admin jobs list --active --user=charles

# Adjust limits if needed
pulldb-admin settings set max_active_jobs_per_user 2
```

### Orphaned Staging Databases

```bash
# Find orphaned databases
pulldb-admin cleanup --dry-run

# Clean them up
pulldb-admin cleanup --execute
```

### Host Overloaded

```bash
# Check jobs on specific host
pulldb-admin jobs list --dbhost=dev-db-01 --active

# Temporarily disable host
pulldb-admin hosts disable dev-db-01

# Wait for jobs to complete, then re-enable
pulldb-admin hosts enable dev-db-01
```
