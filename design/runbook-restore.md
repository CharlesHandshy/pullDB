# Restore Runbook (Prototype)

Follow this checklist when performing or validating a restore with pullDB.

## FAIL HARD Operational Guardrail

At ANY deviation from expected flow (validation rejection, disk check failure, missing S3 object, post-SQL error):
1. Stop progression (do not skip phase).
2. Capture Goal / Problem / Root Cause / Ranked Solutions.
3. Persist failure detail in `job_events` with actionable remediation text.
4. Apply primary solution; avoid workaround-first culture.

## Pre-flight

1. Confirm operator exists in `auth_users` and is not disabled.
2. Verify target `dbhost` is registered with sufficient `max_db_count` headroom.
3. Ensure daemon is running and monitoring metrics (queue depth, disk capacity).
4. Check workspace disk space (`df -h`) to verify baseline capacity.

### Worker daemon control (systemd + diagnostics)

- **Systemd service** lives at `/etc/systemd/system/pulldb-worker.service` and runs `pulldb-worker` with `PULLDB_AWS_PROFILE=pr-dev` so Secrets Manager + MySQL calls always hit the development account. Leave `AWS_PROFILE` unset on hosts that have the proper instance profile; only override it when debugging with a local profile that mirrors the host role.
- For targeted diagnostics, run the worker once without systemd:

```bash
PULLDB_AWS_PROFILE=pr-dev pulldb-worker --oneshot --poll-interval 0.5
```

  - `--oneshot` forces a single poll iteration (max-iterations=1) while bypassing exponential backoff so you can quickly validate queue access.
  - `--poll-interval` only applies when not in oneshot mode; in oneshot runs it is clamped to the minimum interval automatically.
- When you need to inspect staging or production S3 backups outside the worker (e.g., manual `aws s3 ls` or `pytest pulldb/tests/test_s3_real_listing_optional.py`), switch `AWS_PROFILE` to `pr-staging` or `pr-prod` respectively **but keep** `PULLDB_AWS_PROFILE=pr-dev` so credential resolution remains in the dev account.

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
2. Observe daemon logs for phase updates (download, extraction, restore, post-restore SQL execution).
3. Check Datadog dashboards for queue depth trends and disk capacity alerts.
4. Inspect `job_events` table if deeper insight is needed:

```sql
SELECT event_time, event_type, detail
FROM job_events
WHERE job_id = '<uuid>'
ORDER BY event_time;
```

## Post-Restore Validation

1. Confirm job status is `complete` in MySQL coordination database.
2. Connect to target MySQL instance and verify restored database presence.
3. Query the `pullDB` metadata table in the restored database to verify post-restore SQL execution status.
4. Run data validation smoke tests as needed for the specific customer or QA template.
5. Notify stakeholders or downstream automation as required.

## Cleanup

- Ensure temporary workspace directory is empty (daemon should remove automatically).
- Review daemon logs for WARN/ERROR entries related to the run.
- Update related documentation or tickets with job ID and validation results.

## Staging Database Lifecycle (Critical)

Before every restore job starts, the worker drops ALL existing staging databases
matching the pattern `{target}_[0-9a-f]{12}`. No retention, reuse, or age-based
policy is applied. This guarantees:

1. Clean slate: Prevents subtle contamination from prior exploratory sessions.
2. Deterministic collision detection: Newly generated staging name must not exist post-cleanup.
3. Operational clarity: Re-restoring a target implicitly discards prior staging revisions.

If a generated staging database name still exists after cleanup, the job FAILS HARD
with a `StagingError` indicating a concurrency issue or UUID collision. Operators
should re-submit the job (generates a new UUID). Investigate simultaneous runs
against the same target if this recurs.

Cutover (atomic rename) occurs only after successful restore, post‑SQL execution,
and metadata injection. On failure prior to rename, the staging database is preserved
for diagnostics and will be removed automatically on the next restore for that target.
