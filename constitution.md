# pullDB Constitution

## Mission

Deliver a dependable, minimal restore pipeline that prioritizes correctness, clarity, and maintainability over feature breadth. Prototype fast, validate thoroughly, and expand only when real usage demands it.

## Guiding Principles

1. **Document First**: capture intent in `README.md`, `docs/mysql-schema.md`, and design notes before writing code. Every feature starts as prose and diagrams.
2. **KISS**: prefer the simplest solution that works; avoid clever abstractions until experience proves they are required.
3. **Function Over Fashion**: choose reliability and transparency over stylistic novelty. Consistency matters more than novelty.
4. **Minimal Is Best**: ship the smallest viable slice (CLI + daemon + MySQL) and iterate deliberately.
5. **Prototype Before Scale**: validate workflows end-to-end with constrained scope before layering on options, services, or automation.

## Architecture Charter

- Single CLI funnels requests into MySQL; one daemon owns validation, execution, and status updates.
- MySQL is the sole coordination layer. Enforce per-target exclusivity through schema constraints.
- S3 remains the system of record for backups; the daemon downloads on demand, cleans up temp storage afterward.
- Configuration lives outside binaries (environment variables, config files). Never hardcode secrets or host-specific settings.
- Reference `Tools/pullDB/README.md` for flow diagrams, option scope, and future roadmap.

## Tooling & Language Policy

- **Python 3.11+**: primary implementation language for the CLI and daemon.
- **MySQL**: use `mysql-connector-python` or `PyMySQL` for coordination database access; wrap access in thin repositories to keep SQL close to the domain.
- **AWS S3**: interact via `boto3` with least-privilege IAM roles. Mock calls in tests using moto or local stubs.
- **MySQL Restore**: orchestrate `myloader` or compatible utilities for ingestion into MySQL 8.x. Shell out through well-audited helpers and capture logs for diagnostics.
- **MySQL Client Libraries**: use `mysql-connector-python` or `PyMySQL` for light metadata queries. Keep credentials external.
- **Shell Utilities**: prefer Python wrappers; when shells are necessary ensure commands are idempotent and checked for non-zero exit codes.

## Coding Standards

- Follow PEP 8 with pragmatic exceptions (100-character line max, descriptive naming).
- Structure modules by domain (`cli`, `daemon`, `storage`, `services`). Keep files short and focused.
- Inject dependencies (S3 client, DB connection) to enable isolated testing.
- Log with Python `logging` using structured JSON payloads where practical. No print statements.
- Handle errors explicitly; surface actionable messages and attach context to `job_events`.

## Testing Doctrine

1. **Design Tests Early**: outline minimal success/failure cases before implementation. Prefer lightweight pytest fixtures.
2. **Unit Tests First**: cover queue interactions, option parsing, and disk guards with deterministic tests.
3. **Integration Smoke Tests**: script happy-path restore against disposable MySQL instances; ensure cleanup runs.
4. **No Feature Without Tests**: prototypes may ship with minimal coverage, but every behaviour must have at least one verifying test before merge.
5. **Continuous Verification**: run tests locally before PRs and in CI after pushes.

## Configuration & Security

- Store secrets in environment variables, AWS Secrets Manager, or SSM Parameter Store. Never commit secrets.
- Separate configuration (`config/`, environment files) from application code. Support overrides per environment.
- Enforce TLS for S3 and database connections. Validate certificates.
- Implement least privilege IAM: S3 read-only to backup bucket, restricted MySQL service accounts.
- Audit changes through `job_events`; ensure admin actions note the actor and timestamp.

## Development Workflow

1. Update documentation first (design notes, strategy, schema).
2. Create or update tests covering the change.
3. Implement code adhering to the architecture charter and coding standards.
4. Run `python -m pytest` (or project-approved command) and linting (mypy/ruff if configured).
5. Update diagrams or docs impacted by the change.
6. Submit PR with clear rationale, testing evidence, and doc references.

## Deployment & Operations

- Package CLI and daemon together; migrations run before daemon restart.
- Maintain migration scripts under `migrations/`. Each schema change requires forward-only SQL and rollback notes.
- Instrument the daemon with queue depth and disk capacity metrics pushed to Datadog.
- Keep operational runbooks updated alongside feature work.

## Backlog Stewardship

- Track deferred features (history views, cancellation, concurrency overrides) in backlog docs.
- Reassess backlog items periodically based on observed needs. No speculative implementation.
- When ready to expand scope, update this constitution, README, and schema docs before coding.

## Amendments

- Changes to this constitution require consensus from the maintainers. Document amendments in PR descriptions and keep a changelog at the bottom.
- Last updated: 2025-10-27.
