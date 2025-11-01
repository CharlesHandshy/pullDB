# Security Model

This document summarizes the protections that guard pullDB operations. Revisit it whenever new capabilities are proposed.

## FAIL HARD Security Enforcement

Security violations (auth failures, secret access issues, cross-account drift, missing IAM permissions) MUST produce immediate hard failures with structured diagnostics:

```
Goal: Resolve MySQL credentials via AWS Secrets Manager
Problem: AccessDenied on secretsmanager:GetSecretValue for /pulldb/mysql/coordination-db
Root Cause: Role pulldb-ec2-service-role missing pulldb-secrets-manager-access attachment
Solutions:
	1. Attach managed policy arn:aws:iam::<dev-acct>:policy/pulldb-secrets-manager-access
	2. Verify region/profile exports (AWS_PROFILE + AWS_DEFAULT_REGION)
	3. Recreate secret if deleted: aws secretsmanager create-secret --name /pulldb/mysql/coordination-db ...
```

No silent fallbacks to hardcoded credentials. Local development overrides MUST emit a notice with remediation steps.

## Authentication & Authorization

- **Host Access**: Operators authenticate to the underlying EC2 host via corporate mechanisms (e.g., SSO + SSH). The wrapper script supplies the `user=` flag.
- **Queue Enforcement**: `auth_users` table verifies authorized operators. Requests from unknown or disabled users are rejected and logged.
- **Admin Rights**: Admin-only features are deferred, but schema maintains the `is_admin` flag for future use.

## Identity Derivation

- Usernames must yield a unique six-letter `user_code`. Collisions trigger immediate rejection.
- CLI logs every submission with `user_id`, `username`, `user_code` for traceability.

## Secrets Management

- Store database credentials in AWS Secrets Manager or SSM Parameter Store. Daemon fetches them at runtime using IAM roles.
- S3 access uses IAM roles attached to the host; scopes limited to the backup bucket.
- No secrets reside in source control. Environment variables may reference secret identifiers but never the raw values.

## Data in Transit

- All S3 transfers use TLS. `boto3` enforces HTTPS by default.
- MySQL client connections require TLS where supported; verify certificates and reject self-signed certs unless explicitly approved.

## Data at Rest

- MySQL coordination database resides on encrypted volumes (EBS level). Access restricted via MySQL user permissions.
- Temporary extraction workspace should live on encrypted storage with restrictive permissions (700).
- Backup tarballs are not persisted beyond the restore window in the prototype.

## Auditing

- `job_events` captures lifecycle transitions, including actor identity and timestamps.
- Structured application logs include job IDs, targets, and phases for ingest into central logging (e.g., Datadog).
- Future admin actions will log additional audit events once the features unfreeze.

## Attack Surface Minimization

- Combine queue service and worker into one daemon to remove surface area.
- Validate all CLI inputs; reject unexpected flags and enforce minimal option set.
- The daemon executes only pre-approved post-restore SQL scripts stored in controlled locations (no dynamic SQL generation).

## Incident Response Hooks

- Log anomalies (auth failures, disk exhaustion) at WARN/ERROR and emit metrics to trigger alerts.
- Maintain `runbook-failure.md` to guide responders through common remediation steps.
