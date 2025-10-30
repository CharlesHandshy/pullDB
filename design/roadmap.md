# Roadmap (Documentation-First)

> **Governance**: All feature additions must align with principles in `../.github/copilot-instructions.md` and `../constitution.md`. Update those documents first if architectural changes are needed.

This roadmap records deferred features and the documentation prerequisites before implementation begins. Always update this file before expanding scope.

## Phase 0 – Prototype (Current)

- CLI enqueue + status command.
- Daemon polling, download, restore, post-restore SQL execution, logging, metrics.
- MySQL schema as defined in `../docs/mysql-schema.md`.
- Authentication via trusted wrapper (sudo context).

## Phase 1 – Operational Enhancements

- **Cancellation Support**
  - Documentation: update README, schema notes, runbooks, security considerations.
  - Design work: sequence diagram covering cancel lifecycle, failure handling.
- **History Endpoint**
  - Documentation: define API output, retention policy, and new diagrams.
  - Schema: enable `history_cache` materialization; document migration steps.
- **Job Logs Table**
  - Document expected volume, log format, and pruning approach.

## Phase 2 – Concurrency Controls & Usability

- Introduce per-user/per-host/global active caps.
- Document configuration additions and failure scenarios.
- Extend security model and runbooks for throttling alerts.
- **Short Hostname Aliases**
  - Support `dbhost=db3-dev`, `dbhost=db4-dev`, `dbhost=db5-dev` as aliases for full FQDNs.
  - Document alias-to-FQDN resolution logic in CLI.
  - Add `host_alias` column to `db_hosts` table or maintain alias mapping in `settings` table.
  - Update README with shortened syntax examples.

## Phase 3 – Multi-Daemon & Distributed Locks

- Evaluate distributed locking (e.g., Consul, DynamoDB, or MySQL advisory locks).
- Document deployment topology, failover behaviour, audit adjustments.
- Update diagrams to reflect new components.

## Phase 4 – Web Interface & Enhanced Authentication

- **Web Interface**
  - Browser-based job submission, status monitoring, and history viewing.
  - Real-time job progress updates via WebSockets or polling.
  - Document UI/UX patterns, accessibility requirements, and browser support.
- **Enhanced Authentication System**
  - User login with username/password storage (bcrypt/argon2).
  - Two-factor authentication (2FA) via TOTP or SMS.
  - Session management with secure token handling.
  - Password reset and account recovery flows.
  - Document security model updates, credential storage, and audit logging.
- **Migration Strategy**
  - Maintain CLI trusted wrapper authentication for backwards compatibility.
  - Add `auth_credentials` table for web users (hashed passwords, 2FA secrets).
  - Document authentication flow differences between CLI and web interfaces.

## Phase 5 – Automation & APIs

- REST/GraphQL API for programmatic job submission and monitoring.
- API token authentication for service accounts.
- Document onboarding flows, rate limits, and security posture.

## Continuous Tasks

- Review backlog items quarterly.
- Keep this roadmap synchronized with `../constitution.md` and product decisions.
- Ensure every phase has clear exit criteria and testing expectations before coding.
