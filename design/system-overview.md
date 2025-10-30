# System Overview

The pullDB prototype consists of a CLI that validates user intent and inserts jobs into SQLite, plus a long-running daemon that executes restores. This document expands on the high-level flow described in `../README.md`.

## Component Responsibilities

- **CLI**
  - Validate option combinations (`user`, `customer`/`qatemplate`, `overwrite`, optional `dbhost`).
  - Inject jobs into SQLite with `status=queued` while enforcing per-target uniqueness.
  - Provide a `status` command that reads active job summaries from the `active_jobs` view.
- **Daemon**
  - Poll SQLite for queued work, acquiring per-target locks before mutation.
  - Stream backups from S3, verify disk capacity, extract to a workspace, and invoke MySQL restore tooling (`myloader`).
  - Run obfuscation SQL, emit `job_events`, and update job status.
  - Publish metrics (queue depth, disk alerts) and structured logs.
- **SQLite**
  - Serves as the coordination plane for jobs, events, configuration, and locks.
  - Enforces invariants through constraints and triggers defined in `../docs/sqlite-schema.md`.
- **MySQL Hosts**
  - Receive restored databases using least-privilege service accounts.
  - Track capacity via `db_hosts.max_db_count` to prevent over-allocation.

Refer to `../constitution.md` for coding standards, tooling choices, and deployment workflow.

## Diagram

See `diagrams/system-overview.mmd` for the Mermaid source. Render it with a Mermaid-compatible viewer when updating design discussions.
