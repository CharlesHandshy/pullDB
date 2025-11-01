# Failure Runbook (Prototype)

Use this guide to triage and resolve common pullDB restore failures.

## FAIL HARD Diagnostic Checklist

For every incident capture:
1. Goal (operation attempted)
2. Problem (exact symptom / error excerpt)
3. Root Cause (validated, cite evidence)
4. Ranked Solutions (1 = best fix, least blast radius)

Template:
```
Goal: <short intent>
Problem: <verbatim error/log excerpt>
Root Cause: <specific misconfiguration/permission/state>
Solutions:
	1. <primary fix>
	2. <secondary>
	3. <workaround (only if documented)>
```

Refactor each category below using this structure when recording actual incidents.

## Queue Rejection

Goal: Accept restore request into queue.
Problem: CLI validation error; job not created.
Root Cause: Option contract violated (missing/conflicting customer|qatemplate, insufficient alphabetic chars, duplicate active job).
Solutions:
	1. Correct option set (ensure exactly one of customer|qatemplate; user has ≥6 letters)
	2. Query existing jobs: SELECT id,status FROM jobs WHERE target='<target>'
	3. Adjust username (add alphabetic characters) if collision persists

## Disk Capacity Failure

Goal: Extract backup safely.
Problem: Job failed; error_detail shows insufficient space.
Root Cause: Available bytes < required (tar_size + tar_size*1.8) or incorrect volume mounted.
Solutions:
	1. Free space (drop obsolete restored DBs)
	2. Expand underlying volume; verify with `df -h` before retry
	3. Relocate working directory to larger mount (update settings) if recurrent

## S3 Download Failure

Goal: Download backup archive.
Problem: Failed S3 read (AccessDenied / NoSuchKey / timeout).
Root Cause: Missing IAM permission, object deleted/mistyped key, transient network issue.
Solutions:
	1. List object: `aws s3 ls s3://<bucket>/<prefix>` to confirm existence
	2. Attach/verify policy granting s3:GetObject to prefix
	3. Re-run after network stabilization; escalate if key absent

## MySQL Restore Failure

Goal: Import schema/data into staging database.
Problem: `myloader` exited non-zero.
Root Cause: Corrupt backup, connectivity failure, invalid credentials, lock contention.
Solutions:
	1. Inspect stdout/stderr in error_detail for first failing table
	2. Validate connectivity: `mysql -h <host> -u <user> -p -e 'SELECT 1'`
	3. Drop partial staging database; retry full restore

## Post-Restore SQL Failure

Goal: Sanitize staging database via ordered scripts.
Problem: One or more scripts failed.
Root Cause: Script syntax drift, dependency on missing table, unexpected data shape.
Solutions:
	1. Query metadata table JSON execution report
	2. Manually run failing script to reproduce
	3. Patch script (guards/syntax), commit, re-run full restore

## Daemon Crash

Goal: Maintain continuous restore processing.
Problem: Daemon stopped; no new events.
Root Cause: Unhandled exception, resource exhaustion, lost DB connectivity.
Solutions:
	1. Inspect logs/journal for traceback root cause
	2. Verify MySQL reachability; resolve connectivity or lock issues
	3. Restart daemon with elevated logging; file incident summary

## Escalation

- Capture job ID, timestamps, CLI output, relevant logs.
- Notify on-call engineer with summary and immediate mitigations attempted.
- Update incident ticket with remediation steps and prevention recommendations.
