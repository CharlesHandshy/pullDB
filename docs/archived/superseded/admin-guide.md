# Administrator Guide

[← Back to Documentation Index](START-HERE.md)

> **Version**: 0.0.8 | **Last Updated**: December 2025

This guide covers system administration tasks: schema migrations, cleanup operations, monitoring, and maintenance.

**Related:** [Deployment](deployment.md) · [CLI Reference](cli-reference.md) · [Runbooks](../design/)

---

## Table of Contents

1. [Schema Migrations](#schema-migrations)
2. [Staging Cleanup](#staging-cleanup)
3. [Settings Management](#settings-management)
4. [Health Monitoring](#health-monitoring)
5. [Troubleshooting](#troubleshooting)

---

## Schema Migrations

pullDB uses **dbmate** for database schema migrations. Migrations are plain SQL files stored in `/opt/pulldb.service/migrations/`.

### Migration Commands

```bash
# Check status
pulldb-migrate status

# Apply pending migrations
pulldb-migrate up

# Apply non-interactively (for automation)
pulldb-migrate up --yes

# Rollback last migration
pulldb-migrate rollback

# Verify schema integrity
pulldb-migrate verify

# Create new migration
pulldb-migrate new add_new_feature
```

### Status Output

```
[X] 20250101000000_initial_schema.sql
[X] 20250115000000_add_cancel_requested.sql
[X] 20250128000000_phase2_concurrency.sql
[ ] 20251201000000_pending_change.sql

Applied: 3
Pending: 1
```

### Migration History

| Migration | Description | Version |
|-----------|-------------|---------|
| `initial_schema` | Core tables (jobs, auth_users, db_hosts, settings) | v0.0.1 |
| `add_cancel_requested` | Job cancellation support | v0.0.2 |
| `add_staging_cleaned` | Staging cleanup tracking | v0.0.3 |
| `phase2_concurrency` | Per-user and global job limits | v0.0.4 |

### Production Upgrade Workflow

```bash
# 1. Stop worker (recommended for major changes)
sudo systemctl stop pulldb-worker

# 2. Apply migrations
sudo pulldb-migrate up --yes

# 3. Verify schema
sudo pulldb-migrate verify

# 4. Restart services
sudo systemctl start pulldb-worker
```

### Writing Migrations

Migration file format:
```sql
-- migrate:up
ALTER TABLE jobs ADD COLUMN priority ENUM('low', 'normal', 'high') DEFAULT 'normal';

-- migrate:down
ALTER TABLE jobs DROP COLUMN priority;
```

Best practices:
- One change per migration
- Always write the `down` section
- Use `IF NOT EXISTS` / `IF EXISTS` where possible
- Test rollback: `up` → `down` → `up`

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
| `work_dir` | string | `/opt/pulldb.service/work` | Working directory |
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
