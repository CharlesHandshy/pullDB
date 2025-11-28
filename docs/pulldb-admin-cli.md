# pulldb-admin CLI Reference

> **Version**: 0.0.4 | **Last Updated**: November 28, 2025

The `pulldb-admin` CLI provides administrative commands for system-wide settings, job management, and maintenance operations.

---

## Quick Start

```bash
# View all settings
pulldb-admin settings

# Update concurrency limits
pulldb-admin settings max_active_jobs_per_user=3

# View all active jobs
pulldb-admin jobs --active

# Cleanup orphaned resources
pulldb-admin cleanup --dry-run
```

---

## Commands

### settings

View or modify system configuration settings.

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

# View specific setting
pulldb-admin settings max_active_jobs_per_user

# Set per-user concurrent job limit
pulldb-admin settings max_active_jobs_per_user=3

# Set global concurrent job limit
pulldb-admin settings max_active_jobs_global=10

# Disable limits (0 = unlimited)
pulldb-admin settings max_active_jobs_per_user=0
pulldb-admin settings max_active_jobs_global=0
```

**Output (view all):**
```
System Settings:

  Key                        Value                                              Description
  ─────────────────────────  ─────────────────────────────────────────────────  ────────────────────────────────────
  default_dbhost             localhost                                          Default database host
  s3_bucket_path             pestroutes-rds-backup-prod-vpc-us-east-1-s3/...    S3 backup bucket path
  work_dir                   /var/lib/pulldb/work/                              Working directory for downloads
  max_active_jobs_per_user   3                                                  Max concurrent jobs per user
  max_active_jobs_global     10                                                 Max concurrent jobs system-wide
```

**Available Settings:**

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `default_dbhost` | string | `localhost` | Default target database host |
| `s3_bucket_path` | string | - | S3 bucket and prefix for backups |
| `work_dir` | string | `/var/lib/pulldb/work/` | Temporary download directory |
| `max_active_jobs_per_user` | int | `0` | Per-user job limit (0=unlimited) |
| `max_active_jobs_global` | int | `0` | System-wide job limit (0=unlimited) |

---

### jobs

View and manage jobs across all users.

**Syntax:**
```bash
# View all active jobs
pulldb-admin jobs --active

# View recent jobs
pulldb-admin jobs --limit=N

# Filter by user
pulldb-admin jobs --user=<username>

# Filter by host
pulldb-admin jobs --dbhost=<host>

# Filter by status
pulldb-admin jobs --status=<status>
```

**Parameters:**

| Parameter | Description |
|-----------|-------------|
| `--active` | Show only queued/running jobs |
| `--limit=N` | Number of jobs to show (default: 20) |
| `--user=` | Filter by username |
| `--dbhost=` | Filter by target host |
| `--status=` | Filter by status (queued/running/failed/complete/canceled) |

**Examples:**

```bash
# All active jobs across all users
pulldb-admin jobs --active

# Recent jobs from specific user
pulldb-admin jobs --user=charles --limit=50

# Failed jobs on specific host
pulldb-admin jobs --dbhost=dev-db-01 --status=failed

# All running jobs
pulldb-admin jobs --status=running
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

**Syntax:**
```bash
# List all hosts
pulldb-admin hosts

# Show host details
pulldb-admin hosts <hostname>

# Enable/disable host
pulldb-admin hosts <hostname> --enable
pulldb-admin hosts <hostname> --disable
```

**Examples:**

```bash
# List all registered hosts
pulldb-admin hosts

# Disable a host (prevents new jobs)
pulldb-admin hosts dev-db-01 --disable

# Re-enable a host
pulldb-admin hosts dev-db-01 --enable
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

**Syntax:**
```bash
# List all users
pulldb-admin users

# Show user details
pulldb-admin users <username>

# Disable a user
pulldb-admin users <username> --disable

# Enable a user
pulldb-admin users <username> --enable
```

**Examples:**

```bash
# List all users
pulldb-admin users

# Disable a user (prevents new jobs)
pulldb-admin users charles --disable
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
pulldb-admin settings max_active_jobs_per_user
pulldb-admin settings max_active_jobs_global

# See current active job count
pulldb-admin jobs --active

# Check per-user breakdown
pulldb-admin jobs --active | grep -E "Owner|Total"
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
pulldb-admin jobs --active

# Check for stuck jobs (running too long)
pulldb-admin jobs --status=running

# Verify settings
pulldb-admin settings
```

### Emergency: Disable All Restores

```bash
# Set global limit to 0 active jobs
pulldb-admin settings max_active_jobs_global=1

# Wait for current jobs to complete
pulldb-admin jobs --active

# Or disable specific host
pulldb-admin hosts dev-db-01 --disable
```

---

## Troubleshooting

### Too Many Active Jobs

```bash
# Check current counts
pulldb-admin jobs --active

# Identify heavy users
pulldb-admin jobs --active --user=charles

# Adjust limits if needed
pulldb-admin settings max_active_jobs_per_user=2
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
pulldb-admin jobs --dbhost=dev-db-01 --active

# Temporarily disable host
pulldb-admin hosts dev-db-01 --disable

# Wait for jobs to complete, then re-enable
pulldb-admin hosts dev-db-01 --enable
```
