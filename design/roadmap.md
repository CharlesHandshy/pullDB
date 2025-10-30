# Roadmap (Documentation-First)

This roadmap records deferred features and the documentation prerequisites before implementation begins. Always update this file before expanding scope.

## Phase 0 – Prototype (Current)

- CLI enqueue + status command.
- Daemon polling, download, restore, obfuscation, logging, metrics.
- SQLite schema as defined in `../docs/sqlite-schema.md`.

## Phase 1 – Operational Enhancements

- **Cancellation Support**
  - Documentation: update README, schema notes, runbooks, security considerations.
  - Design work: sequence diagram covering cancel lifecycle, failure handling.
- **History Endpoint**
  - Documentation: define API output, retention policy, and new diagrams.
  - Schema: enable `history_cache` materialization; document migration steps.
- **Job Logs Table**
  - Document expected volume, log format, and pruning approach.

## Phase 2 – Concurrency Controls

- Introduce per-user/per-host/global active caps.
- Document configuration additions and failure scenarios.
- Extend security model and runbooks for throttling alerts.

## Phase 3 – Multi-Daemon & Distributed Locks

- Evaluate distributed locking (e.g., Consul, DynamoDB, or SQLite WAL strategies).
- Document deployment topology, failover behaviour, audit adjustments.
- Update diagrams to reflect new components.

## Phase 4 – Automation & APIs

- REST/GraphQL API for job submission and monitoring.
- Programmatic authentication (API tokens, service accounts).
- Document onboarding flows, rate limits, and security posture.

## Continuous Tasks

- Review backlog items quarterly.
- Keep this roadmap synchronized with `../constitution.md` and product decisions.
- Ensure every phase has clear exit criteria and testing expectations before coding.
