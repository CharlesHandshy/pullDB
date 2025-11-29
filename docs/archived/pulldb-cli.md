# pulldb CLI Reference

> **Version**: 0.0.4 | **Last Updated**: November 28, 2025

The `pulldb` CLI is the primary user interface for submitting and managing database restore jobs.

---

## Quick Start

### Load a Customer Database

The most common use case is restoring a customer's production database to your local development environment:

```bash
# 1. Submit a restore request
pulldb user=charles customer=acme

# Output:
#   Job submitted successfully.
#   Job ID: abc123de-f456-7890-abcd-ef1234567890
#   Target: chrles_acme
#   Status: queued

# 2. Wait for the restore to complete
pulldb status abc123de-f456-7890-abcd-ef1234567890

# Or stream events in realtime
pulldb events abc123de --follow

# 3. Once complete, connect to your database
mysql -u charles -p chrles_acme

# That's it! The customer database is now available.
```

### Common Workflows

```bash
# Restore a customer database (most common)
pulldb user=charles customer=acme

# Restore a specific date's backup
pulldb user=charles customer=acme date=2025-11-27

# Overwrite existing target database
pulldb user=charles customer=acme overwrite

# Check your active jobs
pulldb status

# View job history
pulldb history

# Cancel a pending/running job
pulldb cancel <job_id>

# View detailed job events
pulldb events <job_id>

# Search for available backups
pulldb search acme

# View performance profile of completed job
pulldb profile <job_id>
```

---

## Commands

### restore

Submits a restore job to download a customer backup from S3 and restore it to your development database.

**Syntax:**
```bash
pulldb user=<username> customer=<customer_id> [dbhost=<host>] [date=<YYYY-MM-DD>] [overwrite]
```

**Alternative: QA Template Restore:**
```bash
pulldb user=<username> qatemplate [dbhost=<host>]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `user=` | **Yes** | - | Your username for job ownership and database naming |
| `customer=` | **Yes**† | - | Customer identifier matching S3 backup path |
| `qatemplate` | **Yes**† | - | Restore QA template instead of customer (mutually exclusive with `customer=`) |
| `dbhost=` | No | `localhost` | Target database host (must be in `db_hosts` table) |
| `date=` | No | Latest | Specific backup date in `YYYY-MM-DD` format |
| `overwrite` | No | false | Overwrite existing target database without confirmation |

†Either `customer=` or `qatemplate` must be specified, but not both.

**Examples:**

```bash
# Basic restore - uses defaults
pulldb user=charles customer=acme

# Restore to specific host
pulldb user=charles customer=acme dbhost=dev-db-01

# Restore specific date
pulldb user=charles customer=acme date=2025-11-27

# Overwrite existing database
pulldb user=charles customer=acme overwrite

# Full specification
pulldb user=charles customer=acme dbhost=dev-db-01 date=2025-11-27 overwrite

# QA template restore
pulldb user=charles qatemplate
```

**Target Database Naming:**

Your restored database is named: `<user_code>_<customer>`

Example: User `charles` with user_code `CHRLES` restoring customer `acme`:
- **Target**: `chrles_acme`
- **Staging** (temporary): `chrles_acme_abc123de1234`

**Output:**
```
Job submitted successfully.
  Job ID: abc123de-f456-7890-abcd-ef1234567890
  Target: chrles_acme
  Status: queued

Track progress with: pulldb status abc123de-f456-7890-abcd-ef1234567890
```

**Errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| "Concurrency limit reached" | Too many active jobs | Wait or cancel a job |
| "Target already has active job" | Duplicate restore in progress | Wait for it to complete |
| "Backup not found" | Customer/date not in S3 | Check customer name or omit date |
| "Database host not found" | Invalid dbhost | Use a registered host |

---

### status

Shows your active (queued/running) jobs.

**Syntax:**
```bash
pulldb status [job_id]
```

**Examples:**

```bash
# All active jobs
pulldb status

# Specific job details
pulldb status abc123de-f456-7890-abcd-ef1234567890
```

**Output (all jobs):**
```
Active Jobs for charles:

  Job ID: abc123de-f456-7890-abcd-ef1234567890
  Target: chrles_acme @ localhost
  Status: running
  Submitted: 2025-11-28 10:30:00
  Started: 2025-11-28 10:30:05

Total: 1 active job
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

### history

Shows your completed job history.

**Syntax:**
```bash
pulldb history [options]
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--limit=` | 50 | Number of jobs to show |
| `--days=` | 30 | Show jobs from last N days |
| `--user=` | - | Filter by user code |
| `--target=` | - | Filter by target database name |
| `--dbhost=` | - | Filter by database host |
| `--status=` | - | Filter by status (complete, failed, canceled) |
| `--wide` | false | Show additional columns including error details |
| `--json` | false | Output JSON instead of table |

**Examples:**

```bash
# Last 30 days of jobs
pulldb history

# Last 50 jobs
pulldb history --limit=50

# Last 7 days
pulldb history --days=7

# Only failed jobs
pulldb history --status=failed

# With error details
pulldb history --wide

# JSON output
pulldb history --json
```

**Output:**
```
STATUS       JOB_ID        TARGET              USER    COMPLETED         DURATION
-----------  ------------  ------------------  ------  ----------------  --------
✓ complete   abc123de...   chrles_acme         CHRLES  2025-11-28 10:45  15.2m
✗ failed     def456ab...   chrles_beta         CHRLES  2025-11-27 15:30  2.3m
○ canceled   ghi789cd...   chrles_gamma        CHRLES  2025-11-26 09:15  0.5m

3 job(s): 1 complete, 1 failed, 1 canceled
(showing last 30 days, limit 50)
```

---

### cancel

Cancels a queued or running job.

**Syntax:**
```bash
pulldb cancel <job_id>
```

**Examples:**

```bash
pulldb cancel abc123de-f456-7890-abcd-ef1234567890
```

**Behavior:**

| Job Status | Cancellation Behavior |
|------------|----------------------|
| `queued` | Immediate cancel |
| `running` | Graceful abort (worker checks periodically) |
| `complete`/`failed` | Cannot cancel (already finished) |

**Output:**
```
Job abc123de-f456-7890-abcd-ef1234567890 has been marked for cancellation.
The worker will stop the job at the next checkpoint.
```

---

### events

Shows detailed event log for a job.

**Syntax:**
```bash
pulldb events <job_id> [options]
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--follow`, `-f` | false | Stream events in realtime (Ctrl+C to stop) |
| `--limit=` | 100 | Maximum number of events to show |
| `--json` | false | Output JSON instead of table |

**Examples:**

```bash
# Show all events for a job
pulldb events abc123de-f456-7890-abcd-ef1234567890

# Stream events in realtime
pulldb events abc123de --follow

# JSON output
pulldb events abc123de --json
```

**Output:**
```
Events for job abc123de...

TIMESTAMP            EVENT TYPE    DETAIL
-------------------  ------------  -------------------------------------
2025-11-28 10:30:00  queued        Job submitted by charles
2025-11-28 10:30:05  running       Worker picked up job
2025-11-28 10:35:00  note          Download complete: 2.3 GB
2025-11-28 10:40:00  note          myloader: 50% complete
2025-11-28 10:45:00  complete      Restore finished successfully

Total: 5 event(s)
```

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

Search for available backups by customer name. Supports wildcard patterns.

**Syntax:**
```bash
pulldb search <customer> [options]
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--date=` | - | Start date in YYYYMMDD format (show backups from this date onwards) |
| `--limit=` | 5 | Maximum number of backups to show |
| `--env=` | both | Environment to search: staging, prod, or both |
| `--json` | false | Output JSON instead of table |

**Examples:**

```bash
# Search for recent backups
pulldb search actionpest

# Search with wildcard
pulldb search action*

# Backups from specific date onwards
pulldb search actionpest --date=20251101

# More results
pulldb search actionpest --limit=10

# Search only production
pulldb search actionpest --env=prod
```

**Output:**
```
Backups matching 'actionpest':

CUSTOMER     DATE        TIME (UTC)  SIZE      ENV   FILENAME
-----------  ----------  ----------  --------  ----  ----------------------------------
actionpest   2025-11-28  03:00:15    1.2 GB    prod  daily_mydumper_actionpest_2025-...
actionpest   2025-11-27  03:00:12    1.2 GB    prod  daily_mydumper_actionpest_2025-...
actionpest   2025-11-26  03:00:18    1.1 GB    prod  daily_mydumper_actionpest_2025-...

3 backup(s) found.
```

---

### profile

Show performance profile for a completed job. Displays timing breakdown by restore phase.

**Syntax:**
```bash
pulldb profile <job_id> [--json]
```

**Examples:**

```bash
# Show performance profile
pulldb profile abc123de-f456-7890-abcd-ef1234567890

# JSON output
pulldb profile abc123de --json
```

**Output:**
```
Performance Profile: abc123de1234...
============================================================
Status: Complete
Total Duration: 15m 23s
Total Data: 2.3 GB

Phase Breakdown:
------------------------------------------------------------
PHASE            DURATION          %    THROUGHPUT
---------------- ------------ -------- ------------
discovery               1.2s     0.1%            -
download             5m 12s    33.8%     7.5 MB/s
extraction           2m 45s    17.9%    14.2 MB/s
myloader             6m 30s    42.3%            -
post_sql                45s     4.9%            -
metadata                 2s     0.0%            -
atomic_rename          150ms     0.0%            -
------------------------------------------------------------

💡 Tip: myloader took 42% of total time.
```

---

## Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                     RESTORE WORKFLOW                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  $ pulldb user=charles customer=acme                         │
│           │                                                  │
│           ▼                                                  │
│  1. Validate: user exists, backup exists, no conflicts       │
│           │                                                  │
│           ▼                                                  │
│  2. Queue job → MySQL (status='queued')                      │
│           │                                                  │
│           ▼                                                  │
│  3. Worker picks up job (status='running')                   │
│           │                                                  │
│           ▼                                                  │
│  4. Download from S3 → /var/lib/pulldb/work/<job_id>/        │
│           │                                                  │
│           ▼                                                  │
│  5. Extract tarball                                          │
│           │                                                  │
│           ▼                                                  │
│  6. myloader restore → staging database                      │
│           │                                                  │
│           ▼                                                  │
│  7. Atomic rename: staging → target                          │
│           │                                                  │
│           ▼                                                  │
│  8. Cleanup staging + work files                             │
│           │                                                  │
│           ▼                                                  │
│  9. Job complete (status='complete')                         │
│                                                              │
│  Monitor: pulldb status / pulldb events <job_id>             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Concurrency Limits

Phase 2 introduced concurrency controls:

| Setting | Description |
|---------|-------------|
| `max_active_jobs_per_user` | Max concurrent jobs per user (0=unlimited) |
| `max_active_jobs_global` | Max concurrent jobs system-wide (0=unlimited) |

When limits are reached, new jobs are rejected with "Concurrency limit reached".

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
# Check active jobs
pulldb status

# Check history
pulldb history --limit=50
```

### Restore failed

```bash
# Check error details
pulldb events <job_id>

# View worker logs for that time
sudo journalctl -u pulldb-worker.service --since "1 hour ago"
```
