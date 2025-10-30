# Security Model

This document summarizes the protections that guard pullDB operations. Revisit it whenever new capabilities are proposed.

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

- SQLite file resides on encrypted volumes (EBS level). Access restricted to the daemon and CLI process owners.
- Temporary extraction workspace should live on encrypted storage with restrictive permissions (700).
- Backup tarballs are not persisted beyond the restore window in the prototype.

## Auditing

- `job_events` captures lifecycle transitions, including actor identity and timestamps.
- Structured application logs include job IDs, targets, and phases for ingest into central logging (e.g., Datadog).
- Future admin actions will log additional audit events once the features unfreeze.

## Attack Surface Minimization

- Combine queue service and worker into one daemon to remove surface area.
- Validate all CLI inputs; reject unexpected flags and enforce minimal option set.
- The daemon never executes dynamic SQL beyond parameterized obfuscation scripts stored in controlled locations.

## Incident Response Hooks

- Log anomalies (auth failures, disk exhaustion) at WARN/ERROR and emit metrics to trigger alerts.
- Maintain `runbook-failure.md` to guide responders through common remediation steps.
