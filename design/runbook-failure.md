# Failure Runbook (Prototype)

Use this guide to triage and resolve common pullDB restore failures.

## Queue Rejection

**Symptoms**: CLI returns validation error, job not created.

- Verify `user` exists and has ≥6 alphabetic characters.
- Confirm exactly one of `customer` or `qatemplate` was provided.
- Check for existing `queued`/`running` job with same target via `active_jobs` view.
- Consult CLI logs for precise validation message; update documentation if wording is unclear.

## Disk Capacity Failure

**Symptoms**: Job transitions to `failed`; `error_detail` references insufficient space.

- Inspect daemon logs for required vs. available bytes.
- Delete unused restored databases or expand storage.
- Rerun job once capacity confirmed.
- Consider adjusting `extraction_directory` or retention policies if recurrent.

## S3 Download Failure

**Symptoms**: `failed` status with detail pointing to S3 read error.

- Verify IAM role still has `s3:GetObject` on the backup prefix.
- Confirm object exists (use `aws s3 ls s3://bucket/prefix/`).
- Check network connectivity and retry; if persistent, escalate to backup owners.

## MySQL Restore Failure

**Symptoms**: `myloader` subprocess non-zero exit.

- Review captured stdout/stderr in `error_detail`.
- Ensure target host reachable and credentials valid.
- Check for conflicting active sessions or locks on the target database.
- Drop partially created database manually before retrying.

## Obfuscation Failure

**Symptoms**: Restore completes but obfuscation script errors.

- Inspect obfuscation SQL for recent changes.
- Run script manually against staging to reproduce.
- If data remains partially obfuscated, isolate database and notify security stakeholders.

## Daemon Crash

**Symptoms**: No `status` updates, logs silent.

- Restart daemon service; observe logs on startup.
- Inspect system journal for Python tracebacks.
- Check SQLite integrity (`PRAGMA integrity_check;`).
- If corruption detected, restore from latest backup and replay necessary jobs manually.

## Escalation

- Capture job ID, timestamps, CLI output, relevant logs.
- Notify on-call engineer with summary and immediate mitigations attempted.
- Update incident ticket with remediation steps and prevention recommendations.
