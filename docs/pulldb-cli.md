# pulldb CLI Reference

> **Version**: 0.0.4 | **Last Updated**: November 28, 2025

The `pulldb` CLI is the primary user interface for submitting and managing database restore jobs.

---

## Quick Start

```bash
# Restore a customer database
pulldb user=charles customer=acme

# Check your active jobs
pulldb status

# View job history
pulldb history

# Cancel a job
pulldb cancel <job_id>

# View job events
pulldb events <job_id>
```

---

## Commands

### restore

Submits a restore job to download a customer backup from S3 and restore it to your development database.

**Syntax:**
```bash
pulldb user=<username> customer=<customer_id> [dbhost=<host>] [date=<YYYY-MM-DD>]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `user=` | **Yes** | - | Your username for job ownership and database naming |
| `customer=` | **Yes** | - | Customer identifier matching S3 backup path |
| `dbhost=` | No | `localhost` | Target database host (must be in `db_hosts` table) |
| `date=` | No | Latest | Specific backup date in `YYYY-MM-DD` format |

**Examples:**

```bash
# Basic restore - uses defaults
pulldb user=charles customer=acme

# Restore to specific host
pulldb user=charles customer=acme dbhost=dev-db-01

# Restore specific date
pulldb user=charles customer=acme date=2025-11-27

# Full specification
pulldb user=charles customer=acme dbhost=dev-db-01 date=2025-11-27
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
pulldb history [--limit=N]
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--limit=` | 10 | Number of jobs to show |

**Examples:**

```bash
# Last 10 jobs
pulldb history

# Last 50 jobs
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
  2025-11-28 10:35:00    note          Download complete: 2.3 GB
  2025-11-28 10:40:00    note          myloader: 50% complete
  2025-11-28 10:45:00    complete      Restore finished successfully

Total: 5 events
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
