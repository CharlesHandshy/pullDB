# Concurrency Controls

> **Version**: Phase 2 (v0.0.4)
> **Status**: Active

## Overview

pullDB implements **three layers** of concurrency control to prevent system overload and ensure fair resource distribution:

1. **Per-Target Exclusivity** (Phase 0) - Only one active job per target database
2. **Per-Host Capacity** (Phase 0) - Max concurrent restores per database host
3. **Global & Per-User Caps** (Phase 2) - System-wide and user-level rate limiting

## Configuration

### Settings Table

Concurrency limits are configured via the `settings` table in the coordination database:

| Setting Key | Default | Description |
|-------------|---------|-------------|
| `max_active_jobs_per_user` | `0` | Maximum active jobs per user (0=unlimited) |
| `max_active_jobs_global` | `0` | Maximum active jobs system-wide (0=unlimited) |

### Modifying Limits

```sql
-- Set per-user limit to 3 active jobs
UPDATE settings 
SET setting_value = '3', 
    updated_at = UTC_TIMESTAMP(6) 
WHERE setting_key = 'max_active_jobs_per_user';

-- Set global limit to 10 active jobs
UPDATE settings 
SET setting_value = '10', 
    updated_at = UTC_TIMESTAMP(6) 
WHERE setting_key = 'max_active_jobs_global';

-- Disable limit (unlimited)
UPDATE settings 
SET setting_value = '0', 
    updated_at = UTC_TIMESTAMP(6) 
WHERE setting_key = 'max_active_jobs_per_user';
```

### Viewing Current Limits

```sql
SELECT setting_key, setting_value, description, updated_at
FROM settings
WHERE setting_key LIKE 'max_active_%';
```

## Enforcement Order

When a job is submitted, limits are checked in this order:

1. **Global limit** - Checked first (higher priority)
   - If system is at capacity, returns HTTP 429 with "System at capacity" message
   
2. **Per-user limit** - Checked second
   - If user has reached their limit, returns HTTP 429 with "User limit reached" message

3. **Per-target exclusivity** - Checked during enqueue (via unique constraint)
   - If target already has an active job, returns HTTP 409 Conflict

4. **Per-host capacity** - Checked by worker when picking up jobs
   - Job remains queued until host has capacity

## Error Responses

### 429 Too Many Requests (Rate Limited)

```json
{
  "detail": "User limit reached: you have 3 active jobs (limit: 3). Wait for jobs to complete or cancel one."
}
```

```json
{
  "detail": "System at capacity: 10 active jobs (limit: 10). Please try again later."
}
```

### 409 Conflict (Target Exclusivity)

```json
{
  "detail": "Target 'janedoacme' on host 'dev-db-01' already has an active job"
}
```

## Monitoring

### Check Current Active Job Counts

```sql
-- Global active jobs
SELECT COUNT(*) AS global_active 
FROM jobs 
WHERE status IN ('queued', 'running');

-- Per-user active jobs
SELECT owner_username, owner_user_code, COUNT(*) AS active_jobs
FROM jobs
WHERE status IN ('queued', 'running')
GROUP BY owner_user_id, owner_username, owner_user_code
ORDER BY active_jobs DESC;

-- Per-host running jobs
SELECT dbhost, COUNT(*) AS running_jobs
FROM jobs
WHERE status = 'running'
GROUP BY dbhost;
```

### API Endpoint

```bash
# Check active jobs via API
curl http://localhost:8080/api/jobs/active | jq

# Check with limit
curl "http://localhost:8080/api/jobs?active=true&limit=50" | jq
```

## Recommendations

### For Development Environments

```sql
-- Relaxed limits for development
UPDATE settings SET setting_value = '5' WHERE setting_key = 'max_active_jobs_per_user';
UPDATE settings SET setting_value = '0' WHERE setting_key = 'max_active_jobs_global';
```

### For Production Environments

```sql
-- Conservative limits for production
UPDATE settings SET setting_value = '3' WHERE setting_key = 'max_active_jobs_per_user';
UPDATE settings SET setting_value = '20' WHERE setting_key = 'max_active_jobs_global';
```

### Capacity Planning

Consider these factors when setting limits:
- **Disk I/O capacity** - Each restore writes significant data
- **Network bandwidth** - S3 downloads consume bandwidth
- **MySQL connections** - Each restore uses target host connections
- **User expectations** - Lower limits = longer wait times

## Metrics and Events

When a job is rejected due to rate limiting, the following event is emitted:

```
Event: job_enqueue_rejected
Labels:
  - phase: enqueue
  - status: rate_limited
Detail: "User limit reached for jdoe: 3/3" or "Global limit reached: 10/10 active jobs"
```

## Related Documentation

- [MySQL Schema](mysql-schema.md) - Settings table definition
- [Runbook: Restore](../design/runbook-restore.md) - Operational procedures
- [Security Model](../design/security-model.md) - Access control
