# Job Events Logging

This document covers the job event logging system: expected volume, log format,
and pruning approach.

## Overview

pullDB maintains an audit trail of job events in the `job_events` table.
Events are timestamped with microsecond precision and linked to jobs via
foreign key.

## Table Schema

```sql
CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail TEXT,
    logged_at TIMESTAMP(6) NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

## Event Types

### Job Lifecycle Events

| Event Type | Description | Trigger |
|------------|-------------|---------|
| `queued` | Job submitted to queue | `POST /api/jobs/restore` |
| `running` | Worker started processing | Worker claims job |
| `complete` | Job finished successfully | Worker completes restore |
| `failed` | Job execution failed | Any unrecoverable error |
| `canceled` | Job was canceled | Cancellation requested while running |
| `cancel_requested` | Cancellation flag set | `POST /api/jobs/{id}/cancel` |

### Phase Events

| Event Type | Description | Trigger |
|------------|-------------|---------|
| `download_started` | S3 download initiated | Worker begins download |
| `download_complete` | S3 download finished | Download completes |
| `extraction_started` | Archive extraction started | Worker begins extraction |
| `extraction_complete` | Archive extraction finished | Extraction completes |
| `restore_started` | myloader execution started | Worker begins restore |
| `restore_complete` | myloader execution finished | myloader exits successfully |

### Maintenance Events

| Event Type | Description | Trigger |
|------------|-------------|---------|
| `staging_auto_cleanup` | Orphaned staging dropped | New job with same target |
| `staging_manual_cleanup` | Admin dropped staging | Scheduled cleanup task |

## Expected Volume

### Per-Job Events

| Job Outcome | Typical Events | Example Sequence |
|-------------|----------------|------------------|
| Success | 6-8 events | queued → running → download_* → extract_* → restore_* → complete |
| Failure | 3-6 events | queued → running → [phase events] → failed |
| Canceled | 4-7 events | queued → running → [phase events] → cancel_requested → canceled |

### Monthly Projections

Based on typical usage patterns:

| Scenario | Jobs/Month | Events/Month | Events/Year |
|----------|------------|--------------|-------------|
| Light | 50 | ~300-400 | ~4,000 |
| Moderate | 100 | ~600-800 | ~8,000 |
| Heavy | 500 | ~3,000-4,000 | ~40,000 |

### Storage Estimates

- Average event row size: ~200 bytes (including indexes)
- At 90-day retention: ~2,000-3,000 events for moderate usage
- Storage impact: ~400KB-600KB

## Detail Field Format

The `detail` field contains optional context as plain text or JSON:

### Plain Text
```
Downloading from s3://bucket/path
```

### JSON Format (for structured data)
```json
{
    "phase": "download",
    "s3_path": "s3://bucket/path",
    "size_bytes": 1234567
}
```

### Error Detail (for failed jobs)
```json
{
    "error_class": "RestoreError",
    "message": "myloader exited with code 1",
    "context": "During schema validation"
}
```

## Pruning Approach

### Strategy

1. **Retention-based**: Delete events older than retention period (default 90 days)
2. **Terminal-only**: Only prune events for completed/failed/canceled jobs
3. **Active protection**: Never prune events for running or queued jobs

### Retention Policy

| Environment | Recommended Retention | Rationale |
|-------------|----------------------|-----------|
| Development | 30 days | Faster iteration, less storage |
| Staging | 60 days | Moderate history for debugging |
| Production | 90 days | Quarterly review capability |

### Manual Pruning

```bash
# Preview what would be deleted
pulldb prune-logs --dry-run

# Delete events older than 90 days (default)
pulldb prune-logs --yes

# Custom retention period
pulldb prune-logs --days 30 --yes
```

### API Pruning

```bash
# Dry run
curl -X POST http://localhost:8080/api/admin/prune-logs \
  -H "Content-Type: application/json" \
  -d '{"days": 90, "dry_run": true}'

# Actual prune
curl -X POST http://localhost:8080/api/admin/prune-logs \
  -H "Content-Type: application/json" \
  -d '{"days": 90, "dry_run": false}'
```

### Scheduled Pruning

For automated maintenance, add to cron:

```bash
# Weekly prune at 3am Sunday
0 3 * * 0 /usr/local/bin/pulldb prune-logs --days 90 --yes >> /var/log/pulldb-prune.log 2>&1
```

## Querying Events

### CLI: View Job Events

```bash
# View events for a specific job (via API)
curl http://localhost:8080/api/jobs/{job_id}/events
```

### SQL: Direct Queries

```sql
-- Events for a specific job
SELECT * FROM job_events WHERE job_id = 'uuid' ORDER BY id;

-- Failed jobs in last 7 days with error details
SELECT j.id, j.target, je.detail
FROM jobs j
JOIN job_events je ON j.id = je.job_id
WHERE j.status = 'failed'
  AND je.event_type = 'failed'
  AND je.logged_at > DATE_SUB(NOW(), INTERVAL 7 DAY);

-- Event type distribution
SELECT event_type, COUNT(*) as count
FROM job_events
GROUP BY event_type
ORDER BY count DESC;
```

## Monitoring

### Key Metrics

1. **Events per day**: Trend indicator for system usage
2. **Failed event ratio**: Percentage of failed vs complete events
3. **Event table size**: Storage consumption

### Alerts

Consider alerting on:
- Unusual spike in failed events
- Missing expected events (e.g., no complete events for hours)
- Table size exceeding threshold
