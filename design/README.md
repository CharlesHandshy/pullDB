# pullDB Design Index

This directory curates the documentation and diagrams that shape the pullDB prototype. Start with the top-level governance documents before diving into these technical details:

1. **`.github/copilot-instructions.md`** - Primary AI agent reference, architectural principles
2. **`constitution.md`** - Coding standards, tooling philosophy, development workflow
3. **`README.md`** - Complete API reference and usage patterns (this provides user-facing context)
4. **Design docs** (below) - Technical implementation guidance

## Document Map

- `system-overview.md`: narrative walkthrough of the CLI/daemon/S3/MySQL interactions.
- `implementation-notes.md`: technical guidance for Python structure, dependency injection, and logging patterns.
- `configuration-map.md`: describes configuration sources, secrets handling, and the MySQL `settings` linkage.
- `security-model.md`: summarizes IAM, host hardening, and audit expectations.
- `runbook-restore.md`: operational checklist for the happy-path restore.
- `runbook-failure.md`: troubleshooting flow for common failure scenarios.
- `roadmap.md`: backlog of deferred features and the documentation required before each expansion.

## Diagrams

Raw Mermaid sources live in `diagrams/` so they can be rendered by Markdown viewers or tooling:

- `diagrams/system-overview.mmd`
- `diagrams/restore-lifecycle.mmd`
- `diagrams/mysql-schema.mmd`

Keep diagram names synchronized with the referencing documents.
