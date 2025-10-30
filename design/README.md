# pullDB Design Index

This directory curates the documentation and diagrams that shape the pullDB prototype. Start here before touching code, and keep these artefacts current as the system evolves.

## Document Map

- `system-overview.md`: narrative walkthrough of the CLI/daemon/S3/MySQL interactions.
- `implementation-notes.md`: technical guidance for Python structure, dependency injection, and logging patterns.
- `configuration-map.md`: describes configuration sources, secrets handling, and the SQLite `settings` linkage.
- `security-model.md`: summarizes IAM, host hardening, and audit expectations.
- `runbook-restore.md`: operational checklist for the happy-path restore.
- `runbook-failure.md`: troubleshooting flow for common failure scenarios.
- `roadmap.md`: backlog of deferred features and the documentation required before each expansion.

## Diagrams

Raw Mermaid sources live in `diagrams/` so they can be rendered by Markdown viewers or tooling:

- `diagrams/system-overview.mmd`
- `diagrams/restore-lifecycle.mmd`
- `diagrams/sqlite-schema.mmd`

Keep diagram names synchronized with the referencing documents.
