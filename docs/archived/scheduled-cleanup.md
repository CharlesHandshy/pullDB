# Scheduled Staging Database Cleanup

This document covers the scheduled staging cleanup mechanism that removes
abandoned staging databases across all database hosts.

## Overview

When a restore job runs, it creates a staging database named `{target}_{job_id_prefix}`.
This staging database is normally:
1. Renamed to the final target on success
2. Dropped on failure (when the same target is restored again)

However, if a user never re-restores the same target, orphaned staging databases
can accumulate. The scheduled cleanup catches these edge cases.

## How It Works

### Identification

A staging database is **only** considered for cleanup if ALL of these are true:
1. It matches the staging name pattern `{target}_{hex12}`
2. **A matching job exists in the pullDB `jobs` table** (CRITICAL)
3. The job is in a terminal state (completed/failed/canceled)
4. The job completed more than N days ago (default: 7 days)

### Safety Guarantees

**Non-pullDB databases are NEVER touched.** The cleanup process:

1. **Requires a matching job record**: If a database matches the pattern but has
   no corresponding job in the pullDB database, it is SKIPPED. This protects
   user databases that happen to end with `_{12_hex_chars}`.

2. **Active job check**: Skip if any queued/running job exists for that target.

3. **Terminal status only**: Only considers staging from completed/failed/canceled jobs.

4. **Age threshold**: Only drops staging older than retention period.

5. **Audit trail**: All deletions are logged to `job_events`.

### Why This Matters

Consider a database named `analytics_data_abc123def456`. This matches the staging
pattern, but if it wasn't created by pullDB, it will NOT be deleted because:
- No job record exists with ID starting `abc123def456` for target `analytics_data`
- Without a matching job, the database is assumed to be user-owned

## Usage

### CLI Commands

```bash
# Scan all hosts, 7 day threshold (default)
pulldb cleanup-staging --yes

# Custom age threshold
pulldb cleanup-staging --days 14 --yes

# Specific host only
pulldb cleanup-staging --host dev-db-01 --yes

# Preview what would be deleted (no actual deletion)
pulldb cleanup-staging --dry-run
```

### API Endpoints

```bash
# Dry run - preview cleanup
curl -X POST http://localhost:8080/api/admin/cleanup-staging \
  -H "Content-Type: application/json" \
  -d '{"days": 7, "dry_run": true}'

# Actual cleanup - all hosts
curl -X POST http://localhost:8080/api/admin/cleanup-staging \
  -H "Content-Type: application/json" \
  -d '{"days": 7, "dry_run": false}'

# Specific host cleanup
curl -X POST http://localhost:8080/api/admin/cleanup-staging \
  -H "Content-Type: application/json" \
  -d '{"days": 7, "dbhost": "dev-db-01", "dry_run": false}'
```

## Configuration

### Age Threshold

Default: 7 days

The age threshold determines when a staging database is considered abandoned.
It counts from the job's completion time (found in `job_events`).

| Environment | Recommended | Rationale |
|-------------|-------------|-----------|
| Development | 1-3 days | Fast iteration, less storage |
| Staging | 5-7 days | Allow time for debugging |
| Production | 7-14 days | Conservative, allow investigations |

### Scheduled Execution

For automated maintenance, add to cron:

```bash
# Daily cleanup at 4am
0 4 * * * /usr/local/bin/pulldb cleanup-staging --days 7 --yes >> /var/log/pulldb-cleanup.log 2>&1
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

## Response Format

### API Response

```json
{
  "hosts_scanned": 3,
  "total_candidates": 10,
  "total_dropped": 8,
  "total_skipped": 2,
  "total_errors": 0,
  "retention_days": 7,
  "dry_run": false
}
```

### Fields

| Field | Description |
|-------|-------------|
| `hosts_scanned` | Number of database hosts scanned |
| `total_candidates` | Orphaned staging databases found |
| `total_dropped` | Databases actually dropped |
| `total_skipped` | Databases skipped (active job, dry run) |
| `total_errors` | Errors encountered during cleanup |
| `retention_days` | Age threshold used |
| `dry_run` | Whether this was a dry run |

## Audit Trail

All cleanup operations are logged:

1. **API logs**: Each cleanup operation logs host, counts, errors
2. **job_events**: Each dropped database logs event type `staging_scheduled_cleanup`

### Query Cleanup History

```sql
SELECT j.target, j.dbhost, je.detail, je.logged_at
FROM job_events je
JOIN jobs j ON je.job_id = j.id
WHERE je.event_type = 'staging_scheduled_cleanup'
ORDER BY je.logged_at DESC
LIMIT 50;
```

## Error Handling

Errors during cleanup are:
1. Logged to the API logs
2. Counted in `total_errors`
3. Non-fatal (cleanup continues to other databases/hosts)

Common errors:
- **Connection failure**: Cannot connect to database host
- **Permission denied**: User lacks DROP privilege
- **Database in use**: Active connections prevent drop

## Monitoring

### Key Metrics

1. **Cleanup frequency**: How often cleanup runs
2. **Databases dropped**: Trend of orphaned databases
3. **Error rate**: Cleanup failures

### Alerts

Consider alerting on:
- High number of orphaned databases (>50)
- Cleanup errors (any `total_errors > 0`)
- Cleanup not running (no cleanup events in 48+ hours)
