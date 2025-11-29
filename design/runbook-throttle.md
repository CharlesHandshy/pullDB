# Throttle Runbook

[← Back to Documentation Index](../docs/START-HERE.md) · [Design README](README.md)

Use this guide to diagnose and resolve throttling-related issues (HTTP 429 responses).

## Overview

pullDB enforces concurrency limits to prevent system overload:

1. **Per-User Limit**: Maximum active jobs per user (`max_active_jobs_per_user`)
2. **Global Limit**: Maximum active jobs system-wide (`max_active_jobs_global`)
3. **Per-Host Limit**: Maximum concurrent restores per target host (`db_hosts.max_concurrent_restores`)

When any limit is reached, new job submissions return HTTP 429 "Too Many Requests".

## FAIL HARD Diagnostic Checklist

For every throttling incident capture:
1. **Goal**: Operation attempted
2. **Problem**: Exact error / HTTP 429 response
3. **Root Cause**: Which limit triggered (per-user, global, per-host)
4. **Solutions**: Ranked by effectiveness

---

## User Limit Exceeded

**Goal**: Submit new restore job.

**Problem**: HTTP 429 with message "User has N active jobs (max: M)"

**Root Cause**: User has reached their per-user active job limit.

**Diagnostic Queries**:
```sql
-- Check current limit
SELECT setting_value FROM settings 
WHERE setting_key = 'max_active_jobs_per_user';

-- Count user's active jobs
SELECT COUNT(*) FROM jobs 
WHERE owner_username = '<username>' 
  AND status IN ('queued', 'running');

-- List user's active jobs
SELECT id, target, status, submitted_at 
FROM jobs 
WHERE owner_username = '<username>' 
  AND status IN ('queued', 'running')
ORDER BY submitted_at;
```

**Solutions**:
1. **Wait**: Let existing jobs complete (preferred)
2. **Cancel**: Cancel lower-priority jobs via admin interface (when available)
3. **Increase Limit**: Adjust `max_active_jobs_per_user` if justified
   ```sql
   UPDATE settings 
   SET setting_value = '<new_value>' 
   WHERE setting_key = 'max_active_jobs_per_user';
   ```
4. **Temporary Override**: Set limit to 0 (unlimited) for emergency (revert after)

---

## Global Limit Exceeded

**Goal**: Submit new restore job.

**Problem**: HTTP 429 with message "System at capacity: N active jobs (max: M)"

**Root Cause**: System-wide job count has reached the global limit.

**Diagnostic Queries**:
```sql
-- Check current limit
SELECT setting_value FROM settings 
WHERE setting_key = 'max_active_jobs_global';

-- Count all active jobs
SELECT COUNT(*) FROM jobs 
WHERE status IN ('queued', 'running');

-- Active jobs breakdown by status and host
SELECT dbhost, status, COUNT(*) as count 
FROM jobs 
WHERE status IN ('queued', 'running')
GROUP BY dbhost, status
ORDER BY count DESC;

-- Oldest active jobs (candidates for investigation)
SELECT id, target, dbhost, status, submitted_at,
       TIMESTAMPDIFF(MINUTE, submitted_at, UTC_TIMESTAMP()) as minutes_active
FROM jobs 
WHERE status IN ('queued', 'running')
ORDER BY submitted_at ASC
LIMIT 10;
```

**Solutions**:
1. **Wait**: Let existing jobs complete
2. **Investigate Stuck Jobs**: Check for jobs running longer than expected
   ```sql
   -- Jobs running > 60 minutes (may indicate issues)
   SELECT id, target, dbhost, submitted_at 
   FROM jobs 
   WHERE status = 'running'
     AND submitted_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 60 MINUTE);
   ```
3. **Increase Limit**: If infrastructure can handle more load
   ```sql
   UPDATE settings 
   SET setting_value = '<new_value>' 
   WHERE setting_key = 'max_active_jobs_global';
   ```
4. **Scale Workers**: Deploy additional worker capacity if limit increase justified

---

## Per-Host Limit Exceeded

**Goal**: Submit restore job to specific host.

**Problem**: Worker fails to start job; job stays in `queued` status.

**Root Cause**: Target host has reached `max_concurrent_restores` limit.

**Note**: Per-host limits are enforced by the Worker, not the API. Jobs are accepted but wait in queue.

**Diagnostic Queries**:
```sql
-- Check host configuration
SELECT hostname, max_concurrent_restores, enabled 
FROM db_hosts 
WHERE hostname = '<target_host>';

-- Count running jobs on host
SELECT COUNT(*) FROM jobs 
WHERE dbhost = '<target_host>' 
  AND status = 'running';

-- Jobs queued for this host
SELECT id, target, submitted_at 
FROM jobs 
WHERE dbhost = '<target_host>' 
  AND status = 'queued'
ORDER BY submitted_at;
```

**Solutions**:
1. **Wait**: Jobs will proceed as capacity frees
2. **Increase Host Capacity**: If host can handle more restores
   ```sql
   UPDATE db_hosts 
   SET max_concurrent_restores = <new_value> 
   WHERE hostname = '<target_host>';
   ```
3. **Redirect**: Submit to alternate host (if applicable)
4. **Investigate Slow Restores**: Check for stuck or unusually slow jobs

---

## Monitoring Recommendations

### Key Metrics to Track

| Metric | Query | Alert Threshold |
|--------|-------|-----------------|
| Global utilization | `SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')` | > 80% of limit |
| Per-user backlog | Users with > 5 queued jobs | Notify user |
| Stuck jobs | Running > 2 hours | Investigate |
| Queue depth by host | Queued jobs per dbhost | > 10 per host |

### Dashboard Query

```sql
-- System overview dashboard
SELECT 
    (SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')) as total_active,
    (SELECT setting_value FROM settings WHERE setting_key = 'max_active_jobs_global') as global_limit,
    (SELECT COUNT(*) FROM jobs WHERE status = 'queued') as queued,
    (SELECT COUNT(*) FROM jobs WHERE status = 'running') as running,
    (SELECT COUNT(DISTINCT owner_username) FROM jobs WHERE status IN ('queued','running')) as active_users;
```

---

## Configuration Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `max_active_jobs_per_user` | 0 | Per-user limit (0=unlimited) |
| `max_active_jobs_global` | 0 | System-wide limit (0=unlimited) |
| `db_hosts.max_concurrent_restores` | per-host | Per-host running job limit |

See `docs/concurrency-controls.md` for detailed configuration guidance.

---

## Related Runbooks

- [runbook-failure.md](runbook-failure.md) - General restore failure triage
- [runbook-restore.md](runbook-restore.md) - Restore workflow procedures

---

[← Back to Documentation Index](../docs/START-HERE.md) · [Roadmap →](roadmap.md)
