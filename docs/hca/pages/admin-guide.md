# Administrator Guide

[← Back to Documentation Index](START-HERE.md)

> **Version**: 1.0.1 | **Last Updated**: January 2026

This guide covers system administration tasks: user and host management, cleanup operations, monitoring, and maintenance.

**Related:** [Deployment](deployment.md) · [CLI Reference](cli-reference.md) · [Runbooks](../design/)

---

## Table of Contents

1. [Admin Dashboard](#admin-dashboard)
2. [User Management](#user-management)
3. [Host Management](#host-management)
4. [API Key Management](#api-key-management)
5. [Database Lifecycle](#database-lifecycle)
6. [Cleanup Tools](#cleanup-tools)
7. [Disallowed Users](#disallowed-users)
8. [Audit Logs](#audit-logs)
9. [Schema Migrations](#schema-migrations)
10. [Settings Management](#settings-management)
11. [Health Monitoring](#health-monitoring)
12. [Troubleshooting](#troubleshooting)

---

## Admin Dashboard

The Admin Dashboard provides an at-a-glance view of system health and key metrics.

**Web UI:** Administration → Dashboard

### System Statistics Cards

| Card | Description |
|------|-------------|
| **Active Jobs** | Jobs currently in `queued` or `running` state |
| **Failed (24h)** | Jobs that failed in the last 24 hours |
| **Total Users** | Registered user count (enabled + disabled) |
| **Enabled Hosts** | Database hosts available for restores |
| **Pending Keys** | API keys awaiting approval |
| **Orphan DBs** | Detected orphan staging databases |

### Host Health Overview

Shows each registered host with:
- Current status (enabled/disabled)
- Active job count
- Last successful restore time
- Connection status indicator

### Quick Access Links

- **Pending API Keys** - Badge shows count needing approval
- **Active Jobs** - View currently running restores
- **Cleanup Tools** - Access cleanup utilities
- **System Settings** - Configure system behavior

---

## User Management

Administrators can manage users via CLI or Web UI.

### User Lifecycle

```
┌──────────────────────────────────────────────────────────────────┐
│  1. User registers (CLI or Web)                                   │
│        pulldb register OR /web/register                          │
│                                                                   │
│  2. User is created in DISABLED state                            │
│        (Cannot use CLI without API key approval)                 │
│                                                                   │
│  3. Admin enables user                                           │
│        pulldb-admin users enable <username>                      │
│                                                                   │
│  4. Admin approves pending API keys                              │
│        pulldb-admin keys approve <key_id>                        │
│                                                                   │
│  5. User can now use CLI and API                                 │
└──────────────────────────────────────────────────────────────────┘
```

### User Commands

```bash
# List all users
pulldb-admin users list

# Enable a disabled user
pulldb-admin users enable jsmith
# Shows if user has pending API keys that need approval

# Disable a user (revokes access)
pulldb-admin users disable jsmith

# Force password reset on next login
pulldb-admin users force-reset jsmith

# Promote to admin
pulldb-admin users promote jsmith

# Demote from admin
pulldb-admin users demote jsmith
```

### Web UI User Management

Navigate to **Administration → Users** to:

**User List (LazyTable)**:
- Sortable columns: username, user_code, role, status, created_at, last_login
- Filter by role: user, manager, admin
- Filter by status: enabled, disabled
- Click row to view user details

**User Actions**:
- **Enable/Disable**: Toggle user access
- **Force Password Reset**: Require password change on next login
- **Set Role**: Assign user, manager, or admin role
- **Set Manager**: Assign a manager for the user
- **View Jobs**: See user's job history and active jobs

**User Detail Page** shows:
- Account information and timestamps
- Role and manager assignment
- API key list with statuses
- Active/recent jobs count
- Storage usage

---

## Host Management

Manage database hosts where restores are performed.

**Web UI:** Administration → Hosts

### Host List

The host list shows:
- Hostname and alias
- Status (enabled/disabled)
- Max concurrent jobs setting
- Active job count
- Last successful restore
- Credential status

### Add Host (Simple)

For hosts with credentials already in AWS Secrets Manager:

```bash
pulldb-admin hosts add new-db-01 --max-concurrent=2
```

Or via Web UI:
1. Click **Add Host**
2. Enter hostname/alias
3. Enter AWS Secrets Manager reference
4. Set max concurrent jobs
5. Click **Add**

### Provision Host (Full Wizard)

For new hosts needing complete setup:

**Web UI:** Administration → Hosts → **Provision New Host**

The wizard performs:
1. **Test Connectivity** - Verify network access
2. **Create MySQL User** - Create `pulldb_restore` user
3. **Create Database** - Create `pulldb_restore` database
4. **Deploy Procedures** - Install stored procedures
5. **Store Credentials** - Save to AWS Secrets Manager
6. **Register Host** - Add to pullDB

**CLI equivalent:**
```bash
pulldb-admin hosts provision new-db-01
```

### Test Connection

Verify a host is properly configured:

```bash
pulldb-admin hosts test localhost
```

Tests:
- Network connectivity
- Credential validity
- Required permissions
- Stored procedure version

### Credential Rotation

Rotate MySQL credentials for security:

**Web UI:** Administration → Hosts → [hostname] → **Rotate Credentials**

**CLI:**
```bash
pulldb-admin secrets rotate-host localhost
```

Rotation is atomic (all-or-nothing):
1. Validate current credentials
2. Generate new password
3. Update MySQL user
4. Update AWS Secrets Manager
5. Verify new credentials

### Host Detail Page

The host detail page shows:
- Connection information
- Current credentials (masked)
- Active jobs on this host
- Historical job statistics
- Stored procedure version
- Quick rotate button

---

## API Key Management

pullDB uses HMAC-signed API keys for secure CLI authentication across multiple hosts. Each key is tied to a specific host and requires admin approval before use.

### How API Keys Work

```
┌──────────────────────────────────────────────────────────────────┐
│  CLI Request with API Key                                         │
│                                                                   │
│  1. CLI sends signed request:                                    │
│     X-API-Key: abc123...                                         │
│     X-Timestamp: 1737123456                                      │
│     X-Signature: HMAC-SHA256(method|path|timestamp)              │
│                                                                   │
│  2. Server validates:                                            │
│     - Key exists and not revoked                                 │
│     - Key is approved (not pending)                              │
│     - Timestamp within 5 minute window                           │
│     - Signature matches                                          │
│                                                                   │
│  3. Request proceeds as authenticated user                       │
└──────────────────────────────────────────────────────────────────┘
```

### Key States

| State | Description | CLI Access |
|-------|-------------|------------|
| **pending** | Awaiting admin approval | ❌ Blocked |
| **approved** | Admin approved, active | ✅ Works |
| **revoked** | Admin revoked | ❌ Blocked |

### Admin CLI Commands

```bash
# List all pending keys (requires approval)
pulldb-admin keys pending

# View all keys for all users
pulldb-admin keys list

# View keys for specific user
pulldb-admin keys list --user jsmith

# Approve a pending key
pulldb-admin keys approve <key_id>

# Revoke an active key
pulldb-admin keys revoke <key_id>
```

### Key Information Displayed

When listing keys, you'll see:
- **Key ID**: First 8 characters for identification
- **Host Name**: Host where key was registered
- **Created From IP**: IP address of registration request
- **Last Used IP**: IP address of most recent use
- **Status**: pending, approved, or revoked
- **Created/Approved**: Timestamps

### Web UI Key Management

Navigate to **Administration > API Keys** to:
- View all pending keys with user/host info
- Approve or reject keys with one click
- See pending count badge in Quick Access

### User Key Registration Flow

When a user runs CLI commands from a new host:

```bash
# User's first CLI command from new host
$ pulldb status
API key required for this host. Run: pulldb request-host-key

# User requests key for this host
$ pulldb request-host-key
✓ API key requested for host: devserver
  Key ID: abc12345...
  Status: Pending admin approval
  
Contact an administrator to approve your key.

# After admin approves
$ pulldb status
[Active Jobs: 0] [Queued: 2]
```

### Security Considerations

1. **One key per host**: Users need separate keys for each machine
2. **IP tracking**: Created and last-used IPs are logged
3. **Manual approval**: No auto-approval, admin must review
4. **Revocation**: Instantly blocks access, no grace period
5. **Host binding**: Keys cannot be moved between hosts

### Two-Step User Activation

For new users, there are TWO steps:
1. **Enable user**: `pulldb-admin users enable <username>`
2. **Approve key**: `pulldb-admin keys approve <key_id>`

This is intentional—user activation and host authorization are separate security decisions.

---

## Database Lifecycle

Restored databases have a lifecycle from creation through retention and eventual cleanup.

### Status Flow

```
queued → running → deployed → (expired OR deleted OR superseded)
              ↓
          failed/canceled
```

### Retention System

When a restore completes, the database enters a retention period:

| Setting | Default | Description |
|---------|---------|-------------|
| `staging_retention_days` | 30 | Default days until database expires |
| `expiring_warning_days` | 7 | Days before expiry to show warning |
| `cleanup_grace_days` | 7 | Days after expiry before cleanup |

**User Actions:**
- **Extend** - Add time before expiration
- **Lock** - Prevent cleanup (with reason)
- **Delete** - Remove database immediately

### Locked Databases

**Web UI:** Administration → Locked Databases

Users can lock databases to prevent automatic cleanup:
- Lock requires a reason
- Locked databases skip retention cleanup
- Admins can view all locked databases
- Admins can unlock any database

**CLI:**
```bash
# Via API (no direct CLI command)
curl -X POST http://localhost:8080/api/jobs/<job_id>/lock \
  -H "Content-Type: application/json" \
  -d '{"reason": "Production testing"}'
```

### Superseding

When a user restores the same target again:
1. New job is created
2. Old job marked `superseded`
3. Old staging database cleaned up
4. User only sees the latest restore

---

## Cleanup Tools

**Web UI:** Administration → Cleanup

### Job Event Log Pruning

Remove old event logs to manage database size:

**Web UI:** Administration → Cleanup → **Prune Event Logs**

```bash
# Preview (dry run)
curl -X POST "http://localhost:8080/api/admin/prune-logs?days=30&dry_run=true"

# Execute
curl -X POST "http://localhost:8080/api/admin/prune-logs?days=30&dry_run=false"
```

### Staging Database Cleanup

Clean orphaned staging databases from failed/interrupted jobs:

```bash
# Preview
pulldb-admin cleanup --dry-run

# Execute
pulldb-admin cleanup --execute --older-than=24
```

**Web UI:** Administration → Cleanup → **Staging Cleanup**

### Orphan Database Detection

Databases matching staging pattern but with no job record:

**Web UI:** Administration → Cleanup → **Orphan Databases**

Features:
- LazyTable with filtering and sorting
- View metadata from `pullDB` table in each database
- Single delete or bulk delete
- Per-host filtering

**CLI:**
```bash
pulldb-admin cleanup --dry-run  # Shows orphans
```

### User Orphan Databases

Databases restored by users who no longer exist:

**Web UI:** Administration → Cleanup → **User Orphans**

These are databases where:
- Owner user has been deleted
- Database still exists on host
- Manual cleanup required

### Retention Cleanup

Delete expired databases that are past retention:

```bash
# Preview
pulldb-admin run-retention-cleanup --dry-run

# Execute
pulldb-admin run-retention-cleanup --execute
```

---

## Disallowed Users

Prevent specific usernames from registering accounts.

**Web UI:** Administration → Disallowed Users

### Hardcoded List

Some usernames are hardcoded as disallowed (e.g., `admin`, `root`, `test`).

### Database Additions

Administrators can add usernames to the disallow list:

```bash
# Add user
pulldb-admin disallow add baduser --reason="Policy violation"

# List all
pulldb-admin disallow list

# Remove
pulldb-admin disallow remove baduser --force
```

**Web UI:** Click **Add Disallowed User**, enter username and reason.

---

## Audit Logs

Track administrative actions for compliance and debugging.

**Web UI:** Administration → Audit Logs

### Logged Actions

| Action Type | Description |
|-------------|-------------|
| `user_enabled` | User account enabled |
| `user_disabled` | User account disabled |
| `user_role_changed` | User role modified |
| `key_approved` | API key approved |
| `key_revoked` | API key revoked |
| `host_added` | Database host registered |
| `host_removed` | Database host removed |
| `setting_changed` | System setting modified |
| `orphan_deleted` | Orphan database deleted |

### Browsing Logs

- Filter by action type
- Filter by admin user
- Filter by date range
- Full-text search in details

### Example Queries

```sql
-- Recent admin actions
SELECT * FROM audit_logs 
ORDER BY created_at DESC 
LIMIT 100;

-- Actions by specific admin
SELECT * FROM audit_logs 
WHERE admin_username = 'charles'
ORDER BY created_at DESC;

-- User-related actions today
SELECT * FROM audit_logs 
WHERE action_type LIKE 'user_%'
  AND created_at > CURDATE()
ORDER BY created_at DESC;
```

---

## Schema Migrations

pullDB uses numbered SQL files for database schema. Schema files are stored in `/opt/pulldb.service/schema/pulldb_service/` and automatically applied during package installation.

### Checking Applied Schema

```bash
# View all applied schema files
mysql -e "SELECT * FROM pulldb_service.schema_migrations ORDER BY applied_at"

# List available schema files
ls -la /opt/pulldb.service/schema/pulldb_service/*.sql
```

### Manual Schema Application (if needed)

```bash
# Apply a specific schema file manually
mysql pulldb_service < /opt/pulldb.service/schema/pulldb_service/00716_api_keys_host_tracking.sql
```

### Schema File Naming

Schema files use a numbered naming convention:
```
00000_auth_users.sql       # Core tables
00100_jobs.sql             # Job tracking
00715_api_keys.sql         # API key storage
00716_api_keys_host_tracking.sql  # API key approval workflow
```

Files are applied in lexicographic order. The `schema_migrations` table tracks which files have been applied.

### Production Upgrade Workflow

```bash
# 1. Stop worker (recommended for major changes)
sudo systemctl stop pulldb-worker

# 2. Install new package (schema applied automatically)
sudo dpkg -i pulldb_X.X.X_amd64.deb

# 3. Verify schema was applied
mysql -e "SELECT * FROM pulldb_service.schema_migrations ORDER BY applied_at"

# 4. Restart services
sudo systemctl start pulldb-worker
```

### Adding New Schema Files

Schema file format (idempotent):
```sql
-- 00XXX_description.sql
-- Use stored procedures or IF NOT EXISTS for idempotent operations

-- Add column if not exists (MySQL 8.0.16+)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority ENUM('low', 'normal', 'high') DEFAULT 'normal';

-- Or use procedure wrapper for older MySQL versions
```

Best practices:
- Use sequential numbering (00100_, 00200_, etc.)
- Make operations idempotent (safe to run twice)
- Test on fresh install AND upgrade scenarios

---

## Settings Management

Settings control system behavior. They can be stored in database, `.env` file, or both.

### Available Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `myloader_binary` | string | `/opt/pulldb.service/bin/myloader` | Path to myloader |
| `myloader_threads` | int | `8` | Parallel restore threads |
| `myloader_timeout_seconds` | int | `86400` | Max execution time (24 hours) |
| `work_directory` | string | `/opt/pulldb.service/work` | Working directory |
| `max_active_jobs_per_user` | int | `0` | Per-user limit (0=unlimited) |
| `max_active_jobs_global` | int | `0` | System limit (0=unlimited) |
| `default_retention_days` | int | `7` | Default expiration for new restores |
| `max_retention_days` | int | `180` | Maximum retention allowed |
| `expiring_warning_days` | int | `7` | Days before expiry to show warning |
| `cleanup_grace_days` | int | `7` | Days after expiry before cleanup |

### Priority Order

**Database > Environment > Default**

Settings in database take precedence over `.env` file values.

### Common Operations

```bash
# View all settings with sources
pulldb-admin settings list

# Get specific setting (shows both sources)
pulldb-admin settings get max_active_jobs_per_user

# Set in BOTH database AND .env (default)
pulldb-admin settings set max_active_jobs_per_user 3

# Set only in database
pulldb-admin settings set max_active_jobs_per_user 3 --db-only

# Check for drift between db and .env
pulldb-admin settings diff

# Sync database → .env file
pulldb-admin settings pull

# Sync .env → database
pulldb-admin settings push
```

### Concurrency Recommendations

| Environment | Per-User | Global | Rationale |
|-------------|----------|--------|-----------|
| Development | 3 | 10 | Prevent resource exhaustion |
| Production | 2 | 5 | Conservative limits |
| Unlimited | 0 | 0 | No restrictions (default) |

---

## Health Monitoring

### Service Status

```bash
# Check service status
sudo systemctl status pulldb-api
sudo systemctl status pulldb-worker

# View service logs
sudo journalctl -u pulldb-worker -f
```

### Active Jobs Check

```bash
# All active jobs
pulldb-admin jobs list --active

# Jobs on specific host
pulldb-admin jobs list --dbhost=dev-db-01 --active

# Stuck jobs (running too long)
pulldb-admin jobs list --status=running
```

### Database Health

```sql
-- Active jobs count
SELECT status, COUNT(*) FROM jobs 
WHERE status IN ('queued', 'running') 
GROUP BY status;

-- Recent failures
SELECT id, target, dbhost, created_at 
FROM jobs 
WHERE status = 'failed' 
  AND created_at > NOW() - INTERVAL 1 DAY
ORDER BY created_at DESC;

-- Cleanup history
SELECT COUNT(*), DATE(logged_at) as day
FROM job_events 
WHERE event_type = 'staging_scheduled_cleanup'
GROUP BY DATE(logged_at)
ORDER BY day DESC;
```

### Key Metrics to Monitor

| Metric | Alert Threshold | Action |
|--------|-----------------|--------|
| Active jobs | > 20 | Check for stuck jobs |
| Failed jobs (24h) | > 5 | Investigate root cause |
| Orphaned staging | > 50 | Run cleanup |
| Worker heartbeat | Missing > 10min | Restart worker |
| Cleanup errors | Any | Check host connectivity |

---

## Troubleshooting

### Job Stuck in "running"

```bash
# Check worker status
sudo systemctl status pulldb-worker.service

# View worker logs
sudo journalctl -u pulldb-worker.service -f

# Check job events
pulldb events <job_id>

# If worker is dead, job will stay stuck
# After restarting worker, job will be picked up on next poll
```

### Migration Fails Midway

Migrations run in transactions. If one fails:
1. Transaction is rolled back
2. Schema unchanged
3. Fix the issue and re-run `pulldb-migrate up`

Check applied migrations:
```sql
SELECT * FROM schema_migrations ORDER BY version;
```

### Orphaned Staging Databases

```bash
# Find orphaned databases
pulldb-admin cleanup --dry-run

# Clean them up
pulldb-admin cleanup --execute

# Verify removal
pulldb-admin cleanup --dry-run
```

### Host Overloaded

```bash
# Check jobs on specific host
pulldb-admin jobs list --dbhost=dev-db-01 --active

# Temporarily disable host (prevents new jobs)
pulldb-admin hosts disable dev-db-01

# Wait for active jobs to complete
pulldb-admin jobs list --dbhost=dev-db-01 --active

# Re-enable when ready
pulldb-admin hosts enable dev-db-01
```

### Settings Drift

If database and `.env` file have different values:

```bash
# See differences
pulldb-admin settings diff

# Sync database → .env (make .env match database)
pulldb-admin settings pull

# Or sync .env → database
pulldb-admin settings push
```

### Emergency: Disable All Restores

```bash
# Set global limit to 1 active job
pulldb-admin settings set max_active_jobs_global 1

# Wait for current jobs to complete
pulldb-admin jobs list --active

# Or disable all hosts
pulldb-admin hosts disable localhost
pulldb-admin hosts disable dev-db-01
```

---

## Backup & Recovery

### Configuration Backup

```bash
# Export all settings
pulldb-admin settings export --format=json > settings-backup.json

# Backup .env file
cp /opt/pulldb.service/.env /opt/pulldb.service/.env.bak
```

### Database Backup

The coordination database (`pulldb_service`) should be backed up regularly:

```bash
# Using mysqldump
mysqldump -u root -p pulldb_service > pulldb_service_backup.sql
```

### Recovery

```bash
# Restore database
mysql -u root -p pulldb_service < pulldb_service_backup.sql

# Verify schema
pulldb-migrate verify

# Apply any missing migrations
pulldb-migrate up --yes
```

---

## Audit Trail

All significant operations are logged to `job_events`:

| Event Type | Description |
|------------|-------------|
| `staging_scheduled_cleanup` | Staging database dropped by cleanup |
| `staging_auto_cleanup` | Staging dropped when same target restored |
| `setting_changed` | Configuration setting modified |

Query audit history:
```sql
SELECT event_type, detail, logged_at
FROM job_events
WHERE event_type LIKE '%cleanup%' OR event_type = 'setting_changed'
ORDER BY logged_at DESC
LIMIT 100;
```

---

[← Back to Documentation Index](START-HERE.md) · [Deployment →](deployment.md)
