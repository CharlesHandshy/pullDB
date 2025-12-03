# CLI Reference

[← Back to Documentation Index](START-HERE.md)

> **Version**: 0.0.8 | **Last Updated**: December 2025

pullDB provides two command-line interfaces:
- **`pulldb`** - End-user CLI for submitting and monitoring restore jobs
- **`pulldb-admin`** - Administrator CLI for system management

**Related:** [Getting Started](getting-started.md) · [Admin Guide](admin-guide.md)

---

## Quick Reference

### User Commands (pulldb)

```bash
# Submit a restore job
pulldb user=charles customer=acme

# Check job status
pulldb status [job_id]

# View job events
pulldb events <job_id> [--follow]

# Search for backups
pulldb search <customer>

# View job history
pulldb history [--days=30]

# Cancel a job
pulldb cancel <job_id>

# View performance profile
pulldb profile <job_id>
```

### Admin Commands (pulldb-admin)

```bash
# Manage settings
pulldb-admin settings list|get|set|diff|pull|push

# Manage jobs
pulldb-admin jobs list [--active]
pulldb-admin jobs cancel <job_id>

# Cleanup orphaned resources
pulldb-admin cleanup --dry-run|--execute

# Manage hosts
pulldb-admin hosts list|add|enable|disable

# Manage users
pulldb-admin users list|show|enable|disable
```

---

## pulldb Commands

### restore

Submits a restore job to download a backup from S3 and restore it to your development database.

**Syntax:**
```bash
pulldb user=<username> customer=<customer_id> [dbhost=<host>] [date=<YYYY-MM-DD>] [overwrite]
pulldb user=<username> qatemplate [dbhost=<host>]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `user=` | Yes | - | Your username for job ownership |
| `customer=` | Yes* | - | Customer identifier matching S3 backup path |
| `qatemplate` | Yes* | - | Restore QA template (mutually exclusive with customer) |
| `dbhost=` | No | `localhost` | Target database host |
| `date=` | No | Latest | Specific backup date (YYYY-MM-DD) |
| `overwrite` | No | false | Overwrite existing target database |

*Either `customer=` or `qatemplate` required, but not both.

**Target Database Naming:**

Your restored database is named: `<user_code>_<customer>`

Example: User `charles` with user_code `CHRLES` restoring customer `acme`:
- **Target**: `chrles_acme`
- **Staging** (temporary): `chrles_acme_abc123de1234`

**Examples:**

```bash
# Basic restore
pulldb user=charles customer=acme

# Restore to specific host
pulldb user=charles customer=acme dbhost=dev-db-01

# Restore specific date
pulldb user=charles customer=acme date=2025-11-27

# Overwrite existing
pulldb user=charles customer=acme overwrite

# QA template restore
pulldb user=charles qatemplate
```

---

### status

Shows your active (queued/running) jobs.

**Syntax:**
```bash
pulldb status [job_id]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--limit=N` | Maximum results (default: 20) |
| `--all` | Show all active jobs, not just yours |
| `--json` | Output JSON |

**Examples:**

```bash
# Your active jobs
pulldb status

# Specific job details
pulldb status abc123de
```

---

### events

Shows detailed event log for a job.

**Syntax:**
```bash
pulldb events <job_id> [options]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--follow`, `-f` | Stream events in realtime |
| `--limit=N` | Maximum events (default: 100) |
| `--json` | Output JSON |

**Event Types:**

| Type | Description |
|------|-------------|
| `queued` | Job submitted |
| `running` | Worker started |
| `note` | Progress info |
| `heartbeat` | Worker alive signal |
| `failed` | Job failed |
| `complete` | Job succeeded |
| `canceled` | Job canceled |

---

### search

Search for available backups by customer name.

**Syntax:**
```bash
pulldb search <customer> [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--date=` | - | Start date (YYYYMMDD format) |
| `--limit=` | 5 | Maximum backups to show |
| `--env=` | both | Environment: staging, prod, or both |
| `--json` | - | Output JSON |

**Examples:**

```bash
# Search for recent backups
pulldb search actionpest

# Search with wildcard
pulldb search action*

# Production backups from specific date
pulldb search actionpest --date=20251101 --env=prod
```

---

### history

Shows your completed job history.

**Syntax:**
```bash
pulldb history [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--limit=` | 50 | Number of jobs to show |
| `--days=` | 30 | Show jobs from last N days |
| `--user=` | - | Filter by user code |
| `--target=` | - | Filter by target database |
| `--dbhost=` | - | Filter by database host |
| `--status=` | - | Filter: complete, failed, canceled |
| `--wide` | false | Show error details |
| `--json` | false | Output JSON |

---

### cancel

Cancels a queued or running job.

**Syntax:**
```bash
pulldb cancel <job_id>
```

**Behavior:**

| Job Status | Behavior |
|------------|----------|
| `queued` | Immediate cancel |
| `running` | Graceful abort at next checkpoint |
| `complete`/`failed` | Cannot cancel |

---

### profile

Show performance profile for a completed job.

**Syntax:**
```bash
pulldb profile <job_id> [--json]
```

**Output Phases:**

| Phase | Description |
|-------|-------------|
| discovery | Backup validation |
| download | S3 download |
| extraction | Tarball extraction |
| myloader | Database restore |
| post_sql | Post-restore SQL scripts |
| atomic_rename | Staging → target rename |

---

## pulldb-admin Commands

### settings

Manage system configuration. Settings can be stored in database, `.env` file, or both.

**Subcommands:**

```bash
pulldb-admin settings list              # List all settings with sources
pulldb-admin settings get <key>         # Get setting from both db AND .env
pulldb-admin settings set <key> <value> # Set in both db AND .env
pulldb-admin settings reset <key>       # Remove from database
pulldb-admin settings export            # Export all settings
pulldb-admin settings diff              # Show differences: db ↔ .env
pulldb-admin settings pull              # Sync: database → .env
pulldb-admin settings push              # Sync: .env → database
```

**Available Settings:**

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `myloader_binary` | string | `/opt/pulldb.service/bin/myloader-0.19.3-3` | Path to myloader |
| `myloader_threads` | int | `8` | Parallel restore threads |
| `myloader_timeout_seconds` | int | `7200` | Max execution time |
| `work_dir` | string | `/opt/pulldb.service/work` | Working directory |
| `max_active_jobs_per_user` | int | `0` | Per-user limit (0=unlimited) |
| `max_active_jobs_global` | int | `0` | System limit (0=unlimited) |

**Priority:** Database > Environment > Default

**Examples:**

```bash
# View all settings
pulldb-admin settings list

# Check setting (shows db and env values)
pulldb-admin settings get max_active_jobs_per_user

# Set in BOTH database AND .env (default)
pulldb-admin settings set max_active_jobs_per_user 3

# Set only in database
pulldb-admin settings set max_active_jobs_per_user 3 --db-only

# Show drift between db and .env
pulldb-admin settings diff

# Sync database → .env file
pulldb-admin settings pull

# Sync .env → database
pulldb-admin settings push
```

---

### jobs

View and manage jobs across all users.

**Subcommands:**

```bash
pulldb-admin jobs list [OPTIONS]        # List jobs
pulldb-admin jobs cancel <job_id> [-f]  # Cancel a job
```

**List Options:**

| Option | Description |
|--------|-------------|
| `--active` | Show only queued/running jobs |
| `--limit=N` | Number of jobs (default: 20) |
| `--user=` | Filter by username |
| `--dbhost=` | Filter by host |
| `--status=` | Filter by status |
| `--json` | Output JSON |

---

### cleanup

Clean orphaned staging databases and work files.

**Syntax:**

```bash
pulldb-admin cleanup --dry-run          # Preview (no changes)
pulldb-admin cleanup --execute          # Execute cleanup
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | - | Preview only |
| `--execute` | - | Perform cleanup |
| `--dbhost=` | All | Target specific host |
| `--older-than=` | 24 | Hours threshold |

---

### hosts

Manage registered database hosts.

**Subcommands:**

```bash
pulldb-admin hosts list                 # List all hosts
pulldb-admin hosts add <hostname>       # Add a host
pulldb-admin hosts enable <hostname>    # Enable a host
pulldb-admin hosts disable <hostname>   # Disable a host
```

**Add Options:**

| Option | Description |
|--------|-------------|
| `--max-concurrent=N` | Max concurrent jobs (default: 1) |
| `--credential-ref=` | AWS Secrets Manager reference |

---

### users

View and manage users.

**Subcommands:**

```bash
pulldb-admin users list                 # List all users
pulldb-admin users show <username>      # Show user details
pulldb-admin users enable <username>    # Enable a user
pulldb-admin users disable <username>   # Disable a user
```

---

## Concurrency Controls

| Setting | Scope | Description |
|---------|-------|-------------|
| `max_active_jobs_per_user` | Per user | Max jobs one user can have active |
| `max_active_jobs_global` | System-wide | Max total active jobs |

**Recommended Settings:**

| Environment | Per-User | Global |
|-------------|----------|--------|
| Development | 3 | 10 |
| Production | 2 | 5 |
| Unlimited | 0 | 0 |

---

## Troubleshooting

### Job stuck in "running"

```bash
# Check worker status
sudo systemctl status pulldb-worker.service

# View worker logs
sudo journalctl -u pulldb-worker.service -f

# Check job events
pulldb events <job_id>
```

### Can't find my job

```bash
pulldb status           # Active jobs
pulldb history          # Completed jobs
```

### Restore failed

```bash
pulldb events <job_id>  # View error details
```

### Too many active jobs

```bash
pulldb-admin jobs list --active
pulldb-admin settings set max_active_jobs_per_user 2
```

### Orphaned staging databases

```bash
pulldb-admin cleanup --dry-run
pulldb-admin cleanup --execute
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PULLDB_API_URL` | `http://localhost:8080` | API service URL |
| `PULLDB_API_TIMEOUT` | `30` | API timeout (seconds) |

---

## Job Lifecycle

```
1. Submit  → pulldb user=charles customer=acme
2. Queue   → MySQL (status='queued')
3. Worker  → Claims job (status='running')
4. Download → S3 → /opt/pulldb.service/work/<job_id>/
5. Extract  → Tarball decompression
6. Restore  → myloader → staging database
7. Rename   → Atomic: staging → target
8. Cleanup  → Remove staging + work files
9. Complete → (status='complete')
```

Monitor: `pulldb status` or `pulldb events <job_id> --follow`

---

[← Back to Documentation Index](START-HERE.md) · [Admin Guide →](admin-guide.md)
