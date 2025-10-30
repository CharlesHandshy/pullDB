# Restore Runbook (Prototype)

Follow this checklist when performing or validating a restore with pullDB.

## Pre-flight

1. Confirm operator exists in `auth_users` and is not disabled.
2. Verify target `dbhost` is registered with sufficient `max_db_count` headroom.
3. Ensure daemon is running and monitoring metrics (queue depth, disk capacity).
4. Check workspace disk space (`df -h`) to verify baseline capacity.

## Submit Restore

```bash
pullDB \
  user=<username> \
  customer=<customer>|qatemplate \
  [dbhost=<override>] \
  [--overwrite]
```

- Replace angle-bracket placeholders with actual values.
- If the target already exists and `--overwrite` was omitted, rerun with explicit `--overwrite`.

## Monitor Progress

1. Run `pullDB status` to confirm job entered `queued`.
2. Observe daemon logs for phase updates (download, extraction, restore, obfuscation).
3. Check Datadog dashboards for queue depth trends and disk capacity alerts.
4. Inspect `job_events` table if deeper insight is needed:

```sql
SELECT event_time, event_type, detail
FROM job_events
WHERE job_id = '<uuid>'
ORDER BY event_time;
```

## Post-Restore Validation

1. Confirm job status is `complete` in SQLite.
2. Connect to target MySQL instance and verify restored database presence.
3. Run obfuscation smoke tests (e.g., confirm PII tables contain masked values).
4. Notify stakeholders or downstream automation as required.

## Cleanup

- Ensure temporary workspace directory is empty (daemon should remove automatically).
- Review daemon logs for WARN/ERROR entries related to the run.
- Update related documentation or tickets with job ID and validation results.
