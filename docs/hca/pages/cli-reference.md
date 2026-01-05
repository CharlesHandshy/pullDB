# CLI Reference

[← Back to Documentation Index](START-HERE.md)

> **Version**: 0.2.2 | **Last Updated**: January 2026

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

# Account management
pulldb register              # Create new account (first-time setup)
pulldb request-host-key      # Request API key for new host machine
pulldb setpass               # Change password
pulldb hosts                 # List available database hosts
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

# Manage API keys
pulldb-admin keys pending     # List keys awaiting approval
pulldb-admin keys approve     # Approve a pending key
pulldb-admin keys revoke      # Revoke a key
pulldb-admin keys list        # List user's keys

# Manage secrets
pulldb-admin secrets rotate-host <hostname>
pulldb-admin secrets verify
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

### register

Create a new pullDB account. This is the first step for new users.

**Syntax:**
```bash
pulldb register
```

The command prompts for:
- Username (must contain at least 6 letters)
- Password (minimum 8 characters)

**Output:**
```bash
$ pulldb register
Enter username: jsmith
Enter password: ********
Confirm password: ********

✓ Account created successfully!

  Username:  jsmith
  User Code: JSMITH

✓ API credentials saved to ~/.pulldb/credentials

Your account is pending approval.
Contact an administrator to enable your account.
```

**What Happens:**
1. Account is created in **disabled** state
2. API key is created in **pending** state
3. Credentials are saved to `~/.pulldb/credentials`
4. Admin must run `pulldb-admin users enable jsmith` to activate
5. Admin must run `pulldb-admin keys approve <key_id>` for CLI access

---

### request-host-key

Request an API key for a new host machine. Use this when you need CLI access from a second (or subsequent) computer.

**Syntax:**
```bash
pulldb request-host-key [--host-name=<hostname>]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--host-name=` | Override auto-detected hostname |

The command prompts for your password to verify identity.

**Output:**
```bash
$ pulldb request-host-key
Enter password: ********

✓ API key requested successfully!

  Username:  jsmith
  User Code: JSMITH
  Hostname:  my-laptop

✓ API credentials saved to ~/.pulldb/credentials

⚠ Your API key is PENDING APPROVAL
Contact an administrator to approve your key.
```

**What Happens:**
1. New API key is created for this host
2. Key is in **pending** state until approved
3. Credentials saved to `~/.pulldb/credentials`
4. Admin must run `pulldb-admin keys approve <key_id>` for CLI access

---

### setpass

Change your password.

**Syntax:**
```bash
pulldb setpass
```

The command prompts for current and new passwords.

**Output:**
```bash
$ pulldb setpass
Current password: ********
New password: ********
Confirm new password: ********

✓ Password changed successfully
You can now log in with your new password.
```

---

### hosts

List available database hosts where you can restore databases.

**Syntax:**
```bash
pulldb hosts [--json]
```

**Output:**
```bash
$ pulldb hosts

Available Database Hosts
==================================================
ALIAS            HOSTNAME
---------------- --------------------------------
localhost        localhost
dev              dev-db-01.internal
staging          staging-db.internal
---------------- --------------------------------

Total: 3 host(s)

Use alias or hostname with: pulldb restore <customer> dbhost=<alias>
```

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
| `work_directory` | string | `/opt/pulldb.service/work` | Working directory |
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

### keys

Manage API keys for CLI authentication.

API keys authenticate CLI requests using HMAC signatures. Each key is tied to a specific host machine. New keys require admin approval before they can be used.

**Subcommands:**

```bash
pulldb-admin keys pending               # List keys awaiting approval
pulldb-admin keys approve <key_id>      # Approve a pending key
pulldb-admin keys revoke <key_id>       # Revoke a key
pulldb-admin keys list <username>       # List all keys for a user
```

**pending** - Shows all keys awaiting admin approval:

```bash
$ pulldb-admin keys pending
Pending API Keys:

KEY_ID                                   USERNAME        HOSTNAME             CREATED
key_abc123...                           jsmith          dev-workstation      2026-01-05 14:30
key_def456...                           alice           laptop               2026-01-05 15:00

Total: 2 pending key(s)
Use 'pulldb-admin keys approve <key_id>' to approve a key.
```

**approve** - Approves a pending key so the user can use the CLI from that host:

```bash
$ pulldb-admin keys approve key_abc123def456...
✓ API key 'key_abc123...' approved
  User: jsmith
  Host: dev-workstation

The user can now use the CLI from 'dev-workstation'.
```

**revoke** - Immediately blocks CLI access from the associated host:

```bash
$ pulldb-admin keys revoke key_abc123def456...
✓ API key revoked
```

**list** - Shows all keys for a specific user (active and revoked):

```bash
$ pulldb-admin keys list jsmith
API Keys for 'jsmith':

KEY_ID           HOST              STATUS      CREATED       LAST USED
key_abc123...    dev-workstation   Active      2026-01-01    2026-01-05 10:30
key_def456...    laptop            Pending     2026-01-05    Never
key_ghi789...    old-machine       Revoked     2025-12-01    2025-12-15 09:00
```

> **Web UI Alternative:** Use Admin → API Keys for a visual interface with approve/reject buttons.

---

### secrets

Manage MySQL credentials stored in AWS Secrets Manager.

**Subcommands:**

```bash
pulldb-admin secrets rotate-host <hostname> [--yes]   # Rotate host credentials
pulldb-admin secrets verify                           # Verify all secrets
```

**rotate-host** - Atomically rotates MySQL credentials for a host:

1. Validates current credentials work
2. Generates new secure password
3. Updates MySQL user password
4. Updates AWS Secrets Manager
5. Verifies new credentials work

**Options:**

| Option | Description |
|--------|-------------|
| `--yes`, `-y` | Skip confirmation prompt |

**Example:**

```bash
# Rotate credentials for localhost (interactive)
pulldb-admin secrets rotate-host localhost

# Non-interactive rotation
pulldb-admin secrets rotate-host localhost --yes
```

> **Alternative:** Use the **Quick Rotate** button in the Web UI at Admin → Hosts → [hostname] for a visual rotation workflow with progress tracking.

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
