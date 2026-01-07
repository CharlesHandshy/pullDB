# Administrator Guide

[← Back to Documentation Index](START-HERE.md)

> **Version**: 1.0.0 | **Last Updated**: January 2026

This guide covers system administration tasks: schema migrations, cleanup operations, monitoring, and maintenance.

**Related:** [Deployment](deployment.md) · [CLI Reference](cli-reference.md) · [Runbooks](../design/)

---

## Table of Contents

1. [User Management](#user-management)
2. [API Key Management](#api-key-management)
3. [Schema Migrations](#schema-migrations)
4. [Staging Cleanup](#staging-cleanup)
5. [Settings Management](#settings-management)
6. [Health Monitoring](#health-monitoring)
7. [Troubleshooting](#troubleshooting)

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

Navigate to **Administration > Users** to:
- View all users with status
- Enable/disable users
- Promote/demote admins

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

## Schema Management

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

## Staging Cleanup

Restore jobs create temporary staging databases (`{target}_{job_id_prefix}`). These are normally cleaned up, but can become orphaned if a user never re-restores the same target.

### Safety Guarantees

A staging database is **only** cleaned up if ALL conditions are met:
1. Matches staging pattern `{target}_{hex12}`
2. Has a matching job record in pullDB database
3. Job is in terminal state (complete/failed/canceled)
4. Job completed more than N days ago (default: 7)

**Non-pullDB databases are NEVER touched** - without a matching job record, databases are assumed to be user-owned.

### CLI Commands

```bash
# Preview cleanup (dry run)
pulldb-admin cleanup --dry-run

# Execute cleanup
pulldb-admin cleanup --execute

# Custom age threshold
pulldb-admin cleanup --older-than=14 --execute

# Specific host only
pulldb-admin cleanup --dbhost=dev-db-01 --execute
```

### Scheduled Cleanup

Add to cron for automated daily cleanup:
```bash
# Daily at 4am
0 4 * * * pulldb-admin cleanup --older-than=7 --execute >> /var/log/pulldb-cleanup.log 2>&1
```

Or use systemd timer:
```ini
# /etc/systemd/system/pulldb-cleanup.timer
[Unit]
Description=Run pullDB staging cleanup daily

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### Age Threshold Recommendations

| Environment | Recommended Days | Rationale |
|-------------|-----------------|-----------|
| Development | 1-3 | Fast iteration, less storage |
| Staging | 5-7 | Allow debugging time |
| Production | 7-14 | Conservative for investigations |

---

## Settings Management

Settings control system behavior. They can be stored in database, `.env` file, or both.

### Available Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `myloader_binary` | string | `/opt/pulldb.service/bin/myloader-0.19.3-3` | Path to myloader |
| `myloader_threads` | int | `8` | Parallel restore threads |
| `myloader_timeout_seconds` | int | `7200` | Max execution time (2 hours) |
| `work_directory` | string | `/opt/pulldb.service/work` | Working directory |
| `max_active_jobs_per_user` | int | `0` | Per-user limit (0=unlimited) |
| `max_active_jobs_global` | int | `0` | System limit (0=unlimited) |

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
