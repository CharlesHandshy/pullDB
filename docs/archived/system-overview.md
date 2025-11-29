# System Overview

> **Prerequisites**: Read `../.github/copilot-instructions.md` for architectural principles, `../constitution.md` for coding standards, and `two-service-architecture.md` for service separation before diving into these implementation details.

The pullDB prototype consists of three components: a CLI that validates user intent and calls an API service, an API service that manages job requests via MySQL, and a worker service that executes restores. This document expands on the high-level flow described in `../README.md`.

## Current Implementation Snapshot (Nov 1 2025)

Implemented: credential resolver, configuration loader, repository layer (jobs/users/hosts/settings), domain models, MySQL schema. Pending: S3 backup discovery, download/extraction, disk capacity enforcement, myloader execution, post-SQL script runner, staging lifecycle (cleanup + atomic rename), structured logging, metrics, integration tests. CLI and worker remain placeholders. See drift ledger in `../README.md` and `.github/copilot-instructions.md` milestone goals.

## FAIL HARD Reference

All component interactions MUST fail fast when invariants or preconditions cannot be satisfied (see `../constitution.md` and `.github/copilot-instructions.md`).

| Layer | Goal | Problem (Example) | Root Cause (Example) | Ranked Solution #1 |
|-------|------|-------------------|----------------------|--------------------|
| CLI Validation | Accept restore request | "invalid target length" | Sanitized customer id >51 chars | Reject with guidance; user shortens identifier |
| API Insert | Enqueue job | 409 duplicate target | Existing queued/running job | Fail immediately; reference existing job id |
| Worker Disk Check | Prepare extraction | Insufficient space error | Available < required (size*1.8) | Abort; free space then resubmit |
| S3 Fetch | Download backup | AccessDenied | Missing s3:GetObject permission | Attach read policy; rerun |
| Post-SQL | Sanitize database | Script 030 fails | Script drift / missing table | Halt; fix script; rerun job |

Never skip a failing phase; staging database remains for inspection if restore fails after creation.

## Component Responsibilities

- **CLI**
  - Validate option combinations (`user`, `customer`/`qatemplate`, `overwrite`, optional `dbhost`).
  - Generate user_code and target database name.
  - Call API service via HTTP to enqueue jobs.
  - Provide a `status` command that queries API service for active job summaries.
- **API Service**
  - Accept HTTP job requests from CLI.
  - Validate input parameters (user, customer/qatemplate, dbhost, overwrite).
  - Generate user_code and sanitize target database names.
  - Check for existing jobs to prevent duplicates.
  - Insert validated jobs into MySQL with `status='queued'`.
  - Provide status query endpoints for CLI.
  - Does NOT access S3 or execute myloader.
- **Worker Service**
  - Poll MySQL for jobs with `status='queued'`.
  - Acquire per-target locks before mutation.
  - Stream backups from S3, verify disk capacity, extract to workspace.
  - Invoke MySQL restore tooling (`myloader`) to staging database.
  - Execute post-restore SQL scripts, emit `job_events`, and update job status.
  - Does NOT accept HTTP requests.
- **MySQL Coordination Database**
  - Serves as the coordination plane for jobs, events, configuration, and locks.
  - Accessed by API service (INSERT/SELECT) and worker service (SELECT/UPDATE).
  - Enforces invariants through constraints and triggers defined in `../docs/mysql-schema.md`.
- **MySQL Target Hosts**
  - Receive restored databases using least-privilege service accounts.
  - Track capacity via `db_hosts.max_db_count` to prevent over-allocation.

Refer to `../constitution.md` for coding standards, tooling choices, and deployment workflow. See `two-service-architecture.md` for complete details on API/Worker service separation.

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

See `../docs/aws-authentication-setup.md` for complete setup instructions implementing these security controls.
