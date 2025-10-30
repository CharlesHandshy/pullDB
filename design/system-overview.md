# System Overview

> **Prerequisites**: Read `../.github/copilot-instructions.md` for architectural principles and `../constitution.md` for coding standards before diving into these implementation details.

The pullDB prototype consists of a CLI that validates user intent and inserts jobs into MySQL, plus a long-running daemon that executes restores. This document expands on the high-level flow described in `../README.md`.

## Component Responsibilities

- **CLI**
  - Validate option combinations (`user`, `customer`/`qatemplate`, `overwrite`, optional `dbhost`).
  - Inject jobs into MySQL with `status=queued` while enforcing per-target uniqueness.
  - Provide a `status` command that reads active job summaries from the `active_jobs` view.
- **Daemon**
  - Poll MySQL for queued work, acquiring per-target locks before mutation.
  - Stream backups from S3, verify disk capacity, extract to a workspace, and invoke MySQL restore tooling (`myloader`).
  - Execute post-restore SQL scripts, emit `job_events`, and update job status.
  - Publish metrics (queue depth, disk alerts) and structured logs.
- **MySQL Coordination Database**
  - Serves as the coordination plane for jobs, events, configuration, and locks.
  - Enforces invariants through constraints and triggers defined in `../docs/mysql-schema.md`.
- **MySQL Target Hosts**
  - Receive restored databases using least-privilege service accounts.
  - Track capacity via `db_hosts.max_db_count` to prevent over-allocation.

Refer to `../constitution.md` for coding standards, tooling choices, and deployment workflow.

## Diagrams

### System Architecture
See `diagrams/system-overview.mmd` for the Mermaid source showing component interactions. Render it with a Mermaid-compatible viewer when updating design discussions.

### AWS Security Architecture
pullDB operates in a cross-account AWS environment with defense-in-depth security:

- **`diagrams/aws-security-architecture.mmd`** - Complete security architecture showing:
  - Cross-account IAM role assumption flow
  - S3 bucket policies and KMS encryption
  - Parameter Store integration with SecureString
  - CloudTrail audit logging
  - Multi-layer security controls

- **`diagrams/aws-cross-account-flow.mmd`** - Step-by-step sequence diagram of:
  - STS AssumeRole authentication process
  - External ID validation (confused deputy prevention)
  - Temporary credential issuance and refresh
  - S3 and Parameter Store access with KMS decryption
  - Automatic credential rotation by AWS SDK

- **`diagrams/aws-security-layers.mmd`** - Defense-in-depth security layers:
  - Layer 1: Identity & Authentication
  - Layer 2: Trust Boundary (External ID, optional MFA)
  - Layer 3: Authorization (IAM policies with explicit deny)
  - Layer 4: Resource Policies (bucket/key policies)
  - Layer 5: Network & Encryption (TLS + SSE-KMS)
  - Layer 6: Temporal Controls (session duration, auto-refresh)
  - Layer 7: Audit & Monitoring (CloudTrail, CloudWatch)
  - Layer 8: Access Patterns (read-only, least privilege)
  - Layer 9: Operational Security (rotation, restrictions)

See `../docs/aws-cross-account-setup.md` for complete setup instructions implementing these security controls.
