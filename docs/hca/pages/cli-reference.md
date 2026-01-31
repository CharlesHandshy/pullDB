# CLI Reference

[← Back to Documentation Index](START-HERE.md)

> **Version**: 1.0.8 | **Last Updated**: January 2026

pullDB provides two command-line interfaces:
- **`pulldb`** - End-user CLI for submitting and monitoring restore jobs
- **`pulldb-admin`** - Administrator CLI for system management

**Related:** [Getting Started](getting-started.md) · [Admin Guide](admin-guide.md)

---

## Quick Reference

### User Commands (pulldb)

```bash
# Submit a restore job
pulldb restore <customer> [dbhost] [options]

# Custom target database name
pulldb restore actionpest target=mytest
pulldb restore qatemplate target=qatest

# Add suffix to target database
pulldb restore actionpest suffix=dev

# Check job status
pulldb status [job_id]
pulldb status --rt           # Realtime event streaming

# View job events
pulldb events <job_id> [--follow]

# Search for customers
pulldb search <pattern>

# List backups for a customer
pulldb list <customer>

# View job history
pulldb history [--days=30]

# Cancel a job
pulldb cancel <job_id>

# View performance profile
pulldb profile <job_id>

# Account management
pulldb register              # Create new account or request key for new machine
pulldb setpass               # Change password
pulldb hosts                 # List available database hosts
```

### Admin Commands (pulldb-admin)

```bash
# Manage settings
pulldb-admin settings list|get|set|reset|export|diff|pull|push

# Manage secrets
pulldb-admin secrets list|get|set|delete|test|rotate-host

# Manage jobs
pulldb-admin jobs list [--active]
pulldb-admin jobs cancel <job_id>

# Cleanup orphaned resources
pulldb-admin cleanup --dry-run|--execute

# Retention cleanup
pulldb-admin run-retention-cleanup --dry-run|--execute

# Backup analysis
pulldb-admin backups list|search

# Manage hosts
pulldb-admin hosts list|add|provision|test|enable|disable|remove|cred

# Manage users
pulldb-admin users list|show|enable|disable

# Manage API keys
pulldb-admin keys pending|approve|revoke|list

# Manage disallowed users
pulldb-admin disallow list|add|remove
```

---

## pulldb Commands

### restore

Submits a restore job to download a backup from S3 and restore it to your development database.

**Syntax:**
```bash
pulldb restore <customer> [dbhost] [options]
pulldb restore qatemplate [dbhost] [options]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `<customer>` | Yes* | - | Customer identifier matching S3 backup path |
| `qatemplate` | Yes* | - | Restore QA template (mutually exclusive with customer) |
| `[dbhost]` | No | `localhost` | Target database host (positional argument) |
| `dbhost=<host>` | No | `localhost` | Target database host (named parameter) |
| `target=<name>` | No | - | Custom target database name (1-51 lowercase letters) |
| `suffix=<abc>` | No | - | Suffix for target database (1-3 lowercase letters) |
| `date=<YYYY-MM-DD>` | No | Latest | Specific backup date |
| `s3env=<env>` | No | `prod` | S3 environment: staging, prod, or both |
| `overwrite` | No | false | Overwrite existing target database |

*Either `customer` or `qatemplate` required, but not both.

**Admin-Only Options:**

| Parameter | Description |
|-----------|-------------|
| `user=<username>` | Submit job on behalf of another user |

> **Note:** `target=` and `suffix=` cannot be used together. If using `target=`, include any suffix in the target name directly (e.g., `target=mytestdev`).

**Target Database Naming:**

| Mode | Example | Result |
|------|---------|--------|
| Default | `pulldb restore acme` | `chrles_acme` |
| With suffix | `pulldb restore acme suffix=dev` | `chrles_acme_dev` |
| Custom target | `pulldb restore acme target=mytest` | `mytest` |
| QA template | `pulldb restore qatemplate` | `chrles_qatemplate` |
| QA with suffix | `pulldb restore qatemplate suffix=dev` | `chrles_qatemplate_dev` |
| QA with target | `pulldb restore qatemplate target=qatest` | `qatest` |

**Staging Database:** During restore, a temporary staging database is created: `<target>_<job_prefix>` (e.g., `mytest_abc123de`), then atomically renamed to the final target.

**Examples:**

```bash
# Basic restore
pulldb restore actionpest

# Restore to specific host (positional arg)
pulldb restore actionpest dev-db-01

# Restore to specific host (named parameter)
pulldb restore actionpest dbhost=dev-db-01

# Restore specific date
pulldb restore actionpest date=2025-11-27

# Custom target database name
pulldb restore actionpest target=mytest

# Add suffix to target
pulldb restore actionpest suffix=dev

# Overwrite existing
pulldb restore actionpest overwrite

# QA template restore
pulldb restore qatemplate

# QA template with dbhost (positional)
pulldb restore qatemplate dev-db-01

# QA template with suffix
pulldb restore qatemplate suffix=dev

# QA template with custom target
pulldb restore qatemplate target=qatest

# Specify S3 environment
pulldb restore actionpest s3env=prod

# Admin: submit on behalf of user
pulldb restore actionpest user=jsmith
```

---

### status

Shows job status and history. When run without arguments, shows your last submitted job.

**Syntax:**
```bash
pulldb status [job_id] [options]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--limit=N` | Maximum results (default: 100) |
| `--active` | Show only active jobs (queued/running) |
| `--history` | Show historical jobs (completed/failed/canceled) |
| `--status=` | Filter by status: queued, running, complete, failed, canceled |
| `--wide` | Show additional columns (staging_name) |
| `--rt` | Realtime mode: stream job events, auto-exits when job completes |
| `--json` | Output JSON |

**Examples:**

```bash
# Your last submitted job
pulldb status

# Specific job details
pulldb status abc123de

# Stream job events in realtime
pulldb status --rt
pulldb status abc123de --rt

# Active jobs only
pulldb status --active

# Filter by status
pulldb status --history --status failed
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

Search for customers by name pattern. Returns matching customer identifiers.

**Syntax:**
```bash
pulldb search <pattern> [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `limit=N` | 20 | Maximum results to show |
| `json` | - | Output JSON |

**Pattern Matching:**
- `action` - Find customers containing 'action'
- `action*` - Find customers starting with 'action'
- `*pest` - Find customers ending with 'pest'
- `actionpest` - Exact match

**Examples:**

```bash
# Find customers containing 'action'
pulldb search action

# Find customers starting with 'action'
pulldb search action*

# Find customers ending with 'pest'
pulldb search *pest

# Show more results
pulldb search action limit=50
```

---

### list

List available backups for a customer. Shows backup dates, sizes, and filenames.

**Syntax:**
```bash
pulldb list <customer> [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `date=YYYYMMDD` | - | Show backups from this date onwards |
| `limit=N` | 10 | Maximum backups to show |
| `s3env=` | prod | S3 environment: staging, prod, or both |
| `json` | - | Output JSON |

**Examples:**

```bash
# List recent backups for actionpest
pulldb list actionpest

# Show backups from specific date
pulldb list actionpest date=20251101

# Show more backups
pulldb list actionpest limit=20

# Show production backups
pulldb list actionpest s3env=prod
```

**Typical Workflow:**
```bash
# Step 1: Find customer
pulldb search action

# Step 2: List their backups
pulldb list actionpest

# Step 3: Restore specific date
pulldb restore actionpest date=2025-11-25
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

Show performance profile for a completed job, breaking down duration and throughput by phase.

**Syntax:**
```bash
pulldb profile <job_id> [--json]
```

**Output Phases:**

| Phase | Description | Metrics |
|-------|-------------|---------|
| `discovery` | Backup validation | Duration |
| `download` | S3 download | Duration, bytes/sec, total size |
| `extraction` | Tarball extraction | Duration |
| `myloader` | Database restore | Duration, tables restored |
| `post_sql` | Post-restore SQL scripts | Duration, scripts executed |
| `atomic_rename` | Staging → target rename | Duration |

**Example Output:**

```bash
$ pulldb profile abc123de

Job Performance Profile: abc123de
==================================================
Job ID:     abc123de-1234-5678-9abc-def012345678
Customer:   actionpest
Target:     chrles_actionpest
Host:       localhost
Status:     complete
Duration:   12m 34s

Phase Breakdown:
--------------------------------------------------
PHASE            DURATION    THROUGHPUT     SIZE
---------------- ----------- -------------- -----------
discovery        0.8s        -              -
download         8m 12s      45.2 MB/s      22.3 GB
extraction       2m 15s      -              -
myloader         1m 42s      -              847 tables
post_sql         0.3s        -              2 scripts
atomic_rename    0.1s        -              -
---------------- ----------- -------------- -----------
TOTAL            12m 34s
```

---

### register

Create a new pullDB account or request CLI access from a new machine.

This command handles two scenarios:

1. **New User**: Creates a new user account
2. **Existing User**: Requests a new API key for this host machine

**Syntax:**
```bash
pulldb register
```

The command prompts for your password.

**For New Users:**
```bash
$ pulldb register
Enter password: ********
Confirm password: ********

✓ Account created successfully!

  Username:  jsmith
  User Code: JSMITH

✓ API credentials saved to ~/.pulldb/credentials

Your account is pending approval.
Contact an administrator to enable your account.
```

**For Existing Users (New Machine):**
```bash
$ pulldb register
User 'jsmith' already exists. Requesting API key for this machine...

Enter password: ********

✓ API key requested successfully!

  Username:  jsmith
  User Code: JSMITH
  Hostname:  my-laptop

✓ API credentials saved to ~/.pulldb/credentials

⚠ Your API key is PENDING APPROVAL
Contact an administrator to approve your key.
```

**What Happens (New User):**
1. Account is created in **disabled** state
2. API key is created in **pending** state
3. Credentials are saved to `~/.pulldb/credentials`
4. Admin must run `pulldb-admin users enable jsmith` to activate
5. Admin must run `pulldb-admin keys approve <key_id>` for CLI access

**What Happens (Existing User):**
1. New API key is created for this host
2. Key is in **pending** state until approved
3. Credentials saved to `~/.pulldb/credentials`
4. Admin must run `pulldb-admin keys approve <key_id>` for CLI access

---

### setpass

Change your password. This is required after an admin resets your password.

**Syntax:**
```bash
pulldb setpass
```

The command prompts for current and new passwords.

**Password Requirements:**
- Minimum 8 characters
- Must contain at least one uppercase letter
- Must contain at least one lowercase letter
- Must contain at least one digit

**Output:**
```bash
$ pulldb setpass
Current password: ********
New password: ********
Confirm new password: ********

✓ Password changed successfully
You can now log in with your new password.
```

**When to Use:**
- After admin performs password reset via Web UI
- To update your password proactively
- After initial account activation (if prompted)

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
pulldb-admin settings list [--all]      # List settings with sources
pulldb-admin settings get <key>         # Get setting value and sources
pulldb-admin settings set <key> <value> # Set in both db AND .env
pulldb-admin settings set <key> <value> --db-only    # Set only in database
pulldb-admin settings set <key> <value> --env-only   # Set only in .env
pulldb-admin settings reset <key>       # Remove from database (reset to default)
pulldb-admin settings export [--format=json|env]     # Export all settings
pulldb-admin settings diff              # Show differences: db ↔ .env
pulldb-admin settings pull [--dry-run]  # Sync: database → .env
pulldb-admin settings push [--dry-run]  # Sync: .env → database
```

**Available Settings:**

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `myloader_binary` | string | `/opt/pulldb.service/bin/myloader` | Path to myloader |
| `myloader_threads` | int | `8` | Parallel restore threads |
| `myloader_timeout_seconds` | int | `86400` | Max execution time |
| `work_directory` | string | `/opt/pulldb.service/work` | Working directory |
| `max_active_jobs_per_user` | int | `0` | Per-user limit (0=unlimited) |
| `max_active_jobs_global` | int | `0` | System limit (0=unlimited) |
| `default_retention_days` | int | `7` | Default expiration for new restores |
| `max_retention_days` | int | `180` | Maximum retention allowed |
| `expiring_warning_days` | int | `7` | Days before expiry to show warning |
| `cleanup_grace_days` | int | `7` | Days after expiry before cleanup |

**Priority:** Database > Environment > Default

**Examples:**

```bash
# View all settings
pulldb-admin settings list

# Include defaults
pulldb-admin settings list --all

# Check setting (shows db and env values)
pulldb-admin settings get max_active_jobs_per_user

# Set in BOTH database AND .env (default)
pulldb-admin settings set max_active_jobs_per_user 3

# Set only in database
pulldb-admin settings set max_active_jobs_per_user 3 --db-only

# Reset to default
pulldb-admin settings reset max_active_jobs_per_user

# Export as JSON
pulldb-admin settings export --format=json

# Show drift between db and .env
pulldb-admin settings diff

# Preview sync database → .env
pulldb-admin settings pull --dry-run

# Sync database → .env file
pulldb-admin settings pull

# Sync .env → database
pulldb-admin settings push
```

---

### secrets

Manage MySQL credentials stored in AWS Secrets Manager.

**Subcommands:**

```bash
pulldb-admin secrets list [--prefix=<prefix>]    # List all secrets
pulldb-admin secrets get <name> [--show]         # Get secret details
pulldb-admin secrets set <name>                  # Create/update secret
pulldb-admin secrets delete <name> [--force]     # Delete a secret
pulldb-admin secrets test <name>                 # Test MySQL connection
pulldb-admin secrets rotate-host <hostname> [-y] # Rotate host credentials
```

**list** - Lists secrets in AWS Secrets Manager:

```bash
$ pulldb-admin secrets list
Secrets in AWS Secrets Manager (prefix: pulldb/):

NAME                              CREATED              LAST ACCESSED
pulldb/hosts/localhost            2025-11-01 10:00     2026-01-15 14:30
pulldb/hosts/dev-db-01            2025-11-15 09:00     2026-01-15 12:00
pulldb/service                    2025-10-01 08:00     2026-01-15 14:30

Total: 3 secret(s)
```

**get** - Shows secret metadata (use `--show` to reveal value):

```bash
$ pulldb-admin secrets get pulldb/hosts/localhost --show
Secret: pulldb/hosts/localhost

username: pulldb_restore
password: ********
host: localhost
port: 3306

Created: 2025-11-01 10:00
Last Modified: 2026-01-10 15:00
```

**set** - Creates or updates a secret (prompts for values interactively):

```bash
$ pulldb-admin secrets set pulldb/hosts/new-host
Username: pulldb_restore
Password: ********
Host [new-host]: 
Port [3306]: 

✓ Secret created: pulldb/hosts/new-host
```

**delete** - Deletes a secret from AWS Secrets Manager:

```bash
$ pulldb-admin secrets delete pulldb/hosts/old-host
⚠ This will permanently delete the secret 'pulldb/hosts/old-host'
Are you sure? [y/N]: y
✓ Secret deleted
```

**test** - Tests MySQL connection using stored credentials:

```bash
$ pulldb-admin secrets test pulldb/hosts/localhost
Testing connection to 'localhost'...
✓ Connection successful
  MySQL version: 8.0.35
  Server ID: 1
```

**rotate-host** - Atomically rotates MySQL credentials for a host:

1. Validates current credentials work
2. Generates new secure password
3. Updates MySQL user password
4. Updates AWS Secrets Manager
5. Verifies new credentials work

```bash
# Rotate credentials for localhost (interactive)
pulldb-admin secrets rotate-host localhost

# Non-interactive rotation
pulldb-admin secrets rotate-host localhost --yes
```

> **Alternative:** Use the **Quick Rotate** button in the Web UI at Admin → Hosts → [hostname] for a visual rotation workflow with progress tracking.

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

**Examples:**

```bash
# List recent jobs
pulldb-admin jobs list

# Active jobs only
pulldb-admin jobs list --active

# Jobs for specific user
pulldb-admin jobs list --user=jsmith

# Jobs on specific host
pulldb-admin jobs list --dbhost=localhost

# Cancel a job (with confirmation)
pulldb-admin jobs cancel abc123de

# Force cancel without confirmation
pulldb-admin jobs cancel abc123de -f
```

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

**What Gets Cleaned:**
- Staging databases (`*_<job_prefix>` pattern)
- Work directories in `/opt/pulldb.service/work/`
- Files from jobs that failed or were canceled

**Examples:**

```bash
# Preview what would be cleaned
pulldb-admin cleanup --dry-run

# Execute cleanup
pulldb-admin cleanup --execute

# Cleanup specific host only
pulldb-admin cleanup --execute --dbhost=localhost

# Only items older than 48 hours
pulldb-admin cleanup --execute --older-than=48
```

---

### run-retention-cleanup

Execute database retention cleanup to delete expired databases. Locked databases are never dropped.

**Syntax:**

```bash
pulldb-admin run-retention-cleanup --dry-run     # Preview
pulldb-admin run-retention-cleanup --execute     # Execute
```

**Options:**

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview only - show what would be deleted |
| `--json` | Output JSON instead of human-readable text |

**Examples:**

```bash
# Preview expired databases
pulldb-admin run-retention-cleanup --dry-run

# Preview in JSON format
pulldb-admin run-retention-cleanup --dry-run --json
```

**Cleanup Process:**
1. Finds databases past their expiration + grace period
2. Skips locked databases (protected by users)
3. Drops the staging database from the target host
4. Marks the job record as cleaned in the database

> **Note:** This command is typically run automatically via systemd timer (`pulldb-retention.timer`).

---

### backups

Analyze S3 backup inventory with aggregated statistics.

**Subcommands:**

```bash
pulldb-admin backups list [--env=<env>]           # List all backups
pulldb-admin backups search <pattern> [OPTIONS]   # Search with stats
```

**Common Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--env=` | Both | S3 environment: staging, prod, or both |
| `--verbose`, `-v` | false | Show detailed progress |

**list** - Lists all available backups:

```bash
$ pulldb-admin backups list --env=prod

Backup Inventory (prod)
==================================================
CUSTOMER              BACKUPS    MIN SIZE    AVG SIZE    MAX SIZE    LATEST
actionpest            45         2.1 GB      4.5 GB      8.2 GB      2026-01-15
acmecorp              30         1.5 GB      2.0 GB      3.1 GB      2026-01-15
...
```

**search** - Search backups with pattern matching:

```bash
$ pulldb-admin backups search "action*" --env=prod

Search Results for 'action*' (prod)
==================================================
CUSTOMER              BACKUPS    MIN SIZE    AVG SIZE    MAX SIZE    DATE RANGE
actionpest            45         2.1 GB      4.5 GB      8.2 GB      2025-11 - 2026-01
actiontest            12         0.5 GB      0.8 GB      1.2 GB      2025-12 - 2026-01

Total: 2 customer(s), 57 backup(s)
```

**Options:**

| Option | Description |
|--------|-------------|
| `--min-size=` | Minimum backup size filter (e.g., "1GB") |
| `--max-size=` | Maximum backup size filter |
| `--date=` | Filter by backup date (YYYYMMDD) |
| `--json` | Output as JSON |

---

### hosts

Manage registered database hosts.

**Subcommands:**

```bash
pulldb-admin hosts list                 # List all hosts
pulldb-admin hosts add <hostname>       # Add a host
pulldb-admin hosts provision <hostname> # Full automated setup
pulldb-admin hosts test <hostname>      # Test connectivity
pulldb-admin hosts enable <hostname>    # Enable a host
pulldb-admin hosts disable <hostname>   # Disable a host
pulldb-admin hosts remove <hostname>    # Remove a host
pulldb-admin hosts cred <hostname>      # Show stored credentials
```

**list** - Shows all registered hosts with status:

```bash
$ pulldb-admin hosts list

Database Hosts
==================================================
HOSTNAME        ALIAS       STATUS      MAX JOBS    ACTIVE JOBS
localhost       local       enabled     2           1
dev-db-01       dev         enabled     3           0
staging-db      staging     disabled    1           0
```

**add** - Registers a new host (credentials must exist in AWS):

```bash
$ pulldb-admin hosts add new-db-01 --max-concurrent=2
✓ Host 'new-db-01' added
  Credential Ref: pulldb/hosts/new-db-01
  Max Concurrent: 2
```

**provision** - Full automated host setup:

1. Creates MySQL user with correct permissions
2. Creates `pulldb_restore` database
3. Deploys stored procedures
4. Stores credentials in AWS Secrets Manager
5. Registers host in pullDB

```bash
$ pulldb-admin hosts provision new-db-01
Enter MySQL root password: ********

Provisioning host 'new-db-01'...
[1/6] Testing connectivity... ✓
[2/6] Creating MySQL user... ✓
[3/6] Creating database... ✓
[4/6] Deploying procedures... ✓
[5/6] Storing credentials... ✓
[6/6] Registering host... ✓

✓ Host 'new-db-01' provisioned successfully
```

**test** - Tests connectivity and credentials:

```bash
$ pulldb-admin hosts test localhost
Testing host 'localhost'...
  Connection: ✓
  Credentials: ✓
  Permissions: ✓
  Stored Procedure: ✓ (v1.2.0)
```

**remove** - Removes a host:

```bash
$ pulldb-admin hosts remove old-host
⚠ This will remove host 'old-host' from pullDB
Are you sure? [y/N]: y
✓ Host removed

# Also delete AWS secret
$ pulldb-admin hosts remove old-host --delete-secret
```

**cred** - Shows stored credentials (masked):

```bash
$ pulldb-admin hosts cred localhost
Credentials for 'localhost':
  Username: pulldb_restore
  Password: ******* (hidden)
  Source: pulldb/hosts/localhost
```

---

### users

View and manage users.

**Subcommands:**

```bash
pulldb-admin users list [--json]        # List all users
pulldb-admin users show <username>      # Show user details
pulldb-admin users enable <username>    # Enable a user
pulldb-admin users disable <username>   # Disable a user
```

**list** - Shows all users:

```bash
$ pulldb-admin users list

Users
==================================================
USERNAME     CODE      ROLE       STATUS      CREATED           LAST LOGIN
charles      CHRLES    admin      enabled     2025-10-01        2026-01-15 14:30
jsmith       JSMITH    user       enabled     2025-11-01        2026-01-15 10:00
alice        ALICE     manager    enabled     2025-12-01        2026-01-14 16:00
bob          BOB       user       disabled    2025-12-15        Never
```

**show** - Detailed user information:

```bash
$ pulldb-admin users show jsmith

User: jsmith
==================================================
Username:    jsmith
User Code:   JSMITH
Role:        user
Status:      enabled
Manager:     alice
Created:     2025-11-01 10:00
Last Login:  2026-01-15 10:00

API Keys: 2 (1 active, 1 pending)
Active Jobs: 1
Total Jobs: 47
```

**enable/disable**:

```bash
$ pulldb-admin users enable bob
✓ User 'bob' enabled

$ pulldb-admin users disable bob
✓ User 'bob' disabled
```

---

### keys

Manage API keys for CLI authentication.

API keys authenticate CLI requests using HMAC signatures. Each key is tied to a specific host machine. New keys require admin approval before they can be used.

**Subcommands:**

```bash
pulldb-admin keys pending [--json]           # List keys awaiting approval
pulldb-admin keys approve <key_id>           # Approve a pending key
pulldb-admin keys revoke <key_id> [--reason] # Revoke a key
pulldb-admin keys list [<username>] [--all]  # List keys
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

**approve** - Approves a pending key:

```bash
$ pulldb-admin keys approve key_abc123def456...
✓ API key 'key_abc123...' approved
  User: jsmith
  Host: dev-workstation

The user can now use the CLI from 'dev-workstation'.
```

**revoke** - Revokes an active key:

```bash
$ pulldb-admin keys revoke key_abc123def456...
✓ API key revoked

# With reason
$ pulldb-admin keys revoke key_abc123... --reason="Security incident"
```

**list** - Shows keys (optionally for specific user):

```bash
$ pulldb-admin keys list jsmith
API Keys for 'jsmith':

KEY_ID           HOST              STATUS      CREATED       LAST USED
key_abc123...    dev-workstation   Active      2026-01-01    2026-01-05 10:30
key_def456...    laptop            Pending     2026-01-05    Never
key_ghi789...    old-machine       Revoked     2025-12-01    2025-12-15 09:00

# Show all keys (including revoked)
$ pulldb-admin keys list --all
```

> **Web UI Alternative:** Use Admin → API Keys for a visual interface with approve/reject buttons.

---

### disallow

Manage the disallowed users list. Disallowed users cannot register new accounts.

**Subcommands:**

```bash
pulldb-admin disallow list [--json]        # List disallowed users
pulldb-admin disallow add <username>       # Add to disallow list
pulldb-admin disallow remove <username>    # Remove from disallow list
```

**list** - Shows all disallowed users:

```bash
$ pulldb-admin disallow list

Disallowed Users
==================================================
USERNAME          REASON                    ADDED BY      ADDED AT
badactor          Abuse of service          charles       2026-01-10 14:00
testuser          Test account - no access  charles       2026-01-05 10:00

Total: 2 disallowed user(s)
```

**add** - Adds a user to the disallow list:

```bash
$ pulldb-admin disallow add baduser --reason="Policy violation"
✓ User 'baduser' added to disallow list
```

**remove** - Removes a user from the disallow list:

```bash
$ pulldb-admin disallow remove baduser
⚠ This will allow 'baduser' to register for an account
Are you sure? [y/N]: y
✓ User 'baduser' removed from disallow list

# Force without confirmation
$ pulldb-admin disallow remove baduser --force
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
| `PULLDB_API_TIMEOUT` | `30.0` | API timeout (seconds) |
| `PULLDB_S3ENV_DEFAULT` | `prod` | Default S3 environment for backups |
| `PULLDB_API_KEY` | - | API key ID for CLI authentication |
| `PULLDB_API_SECRET` | - | API secret for CLI authentication |

**Credential Storage:**

CLI credentials are stored in `~/.pulldb/credentials`:
```ini
[default]
api_key = key_abc123...
api_secret = secret_xyz789...
api_url = https://pulldb.example.com
```

Environment variables override credential file values.

---

## Job Lifecycle

```
                                    ┌─────────────┐
                                    │   Submit    │
                                    └──────┬──────┘
                                           │
                                           ▼
                                    ┌─────────────┐
               ┌───────────────────►│   queued    │
               │                    └──────┬──────┘
               │                           │ Worker claims
               │                           ▼
               │                    ┌─────────────┐
               │  ┌────────────────►│   running   │◄─────────────────┐
               │  │                 └──────┬──────┘                  │
               │  │                        │                         │
               │  │           ┌────────────┼────────────┐            │
               │  │           │            │            │            │
               │  │     Cancel │      Finish│      Fail │       Cancel (graceful)
               │  │           ▼            ▼            ▼            │
               │  │    ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
               │  │    │ canceling│ │ complete │ │  failed  │ │ canceled │
               │  │    └────┬─────┘ └──────────┘ └──────────┘ └──────────┘
               │  │         │
               │  │         ▼
               │  │  ┌──────────┐
               │  └──│ canceled │
               │     └──────────┘
               │
               │  (User submits new restore for same target)
               │
            ┌──┴─────────┐
            │ superseded │
            └────────────┘
```

**Job Status Definitions:**

| Status | Active? | Terminal? | Description |
|--------|---------|-----------|-------------|
| `queued` | ✓ | | Waiting for worker |
| `running` | ✓ | | Being processed |
| `canceling` | ✓ | | Cancel requested, finishing current operation |
| `deployed` | ✓ | | Database restored, in retention period |
| `complete` | | ✓ | Successfully finished |
| `failed` | | ✓ | Failed with error |
| `canceled` | | ✓ | Canceled by user |
| `expired` | | ✓ | Retention period ended |
| `deleted` | | ✓ | Database deleted |
| `superseded` | | ✓ | Replaced by newer restore |
| `deleting` | | | Being deleted |

**Phases:**

1. **Submit** → `pulldb restore <customer>`
2. **Queue** → MySQL (status='queued')
3. **Worker** → Claims job (status='running')
4. **Download** → S3 → work directory
5. **Extract** → Decompress backup
6. **Restore** → myloader → staging database
7. **Rename** → Atomic: staging → target
8. **Cleanup** → Remove staging + work files
9. **Complete** → (status='deployed' or 'complete')

**Monitor:** `pulldb status` or `pulldb events <job_id> --follow`

---

## Programmatic Usage Examples

The CLI tools can be invoked programmatically from scripts. Here are examples for common automation scenarios.

### Python (subprocess)

```python
import subprocess
import json

# Submit a restore job
result = subprocess.run(
    ["pulldb", "restore", "actionpest", "target=mytest"],
    capture_output=True,
    text=True
)
if result.returncode == 0:
    print("Job submitted successfully")
    print(result.stdout)
else:
    print(f"Error: {result.stderr}")

# Check job status (JSON output for parsing)
result = subprocess.run(
    ["pulldb", "status", "--json"],
    capture_output=True,
    text=True
)
if result.returncode == 0:
    jobs = json.loads(result.stdout)
    for job in jobs:
        print(f"{job['id'][:8]}: {job['status']} - {job['target']}")

# Search for customers
result = subprocess.run(
    ["pulldb", "search", "action*", "limit=10", "json"],
    capture_output=True,
    text=True
)
customers = json.loads(result.stdout) if result.returncode == 0 else []

# Admin: List users (JSON output)
result = subprocess.run(
    ["pulldb-admin", "users", "list", "--json"],
    capture_output=True,
    text=True
)
users = json.loads(result.stdout) if result.returncode == 0 else []
```

### PHP (shell_exec)

```php
<?php
// Submit a restore job
$output = shell_exec('pulldb restore actionpest target=mytest 2>&1');
echo $output;

// Check job status (JSON output for parsing)
$json = shell_exec('pulldb status --json 2>&1');
$jobs = json_decode($json, true);
if ($jobs) {
    foreach ($jobs as $job) {
        echo substr($job['id'], 0, 8) . ": {$job['status']} - {$job['target']}\n";
    }
}

// Search for customers
$json = shell_exec('pulldb search "action*" limit=10 json 2>&1');
$customers = json_decode($json, true) ?: [];

// Admin: List pending API keys
$json = shell_exec('pulldb-admin keys pending --json 2>&1');
$pending = json_decode($json, true) ?: [];
foreach ($pending as $key) {
    echo "Key: {$key['key_id']} - User: {$key['username']}\n";
}
?>
```

### Bash (scripting)

```bash
#!/bin/bash
set -e

# Submit a restore job and capture the output
output=$(pulldb restore actionpest target=mytest 2>&1)
echo "$output"

# Extract job_id from output (grep for UUID pattern)
job_id=$(echo "$output" | grep -oE 'job_id:\s+[0-9a-f-]+' | cut -d' ' -f2)
echo "Job ID: $job_id"

# Wait for job completion
while true; do
    status=$(pulldb status "$job_id" --json 2>/dev/null | jq -r '.[0].status')
    echo "Status: $status"
    
    case "$status" in
        complete|deployed)
            echo "Job completed successfully!"
            break
            ;;
        failed|canceled)
            echo "Job failed or was canceled"
            exit 1
            ;;
        *)
            sleep 10
            ;;
    esac
done

# Admin: Approve all pending keys (batch)
pulldb-admin keys pending --json | jq -r '.[].key_id' | while read key_id; do
    echo "Approving $key_id..."
    pulldb-admin keys approve "$key_id"
done

# Admin: Export settings to JSON
pulldb-admin settings export --format=json > /backup/pulldb-settings.json
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Unauthorized (for admin commands) |
| 3 | Connection error |

---

