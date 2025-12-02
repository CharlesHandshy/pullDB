# pullDB Constitution

## Purpose

This document establishes the foundational principles, standards, and workflows for the pullDB project. Together with `.github/copilot-instructions.md` (which provides architectural overview and AI agent guidance), this constitution forms the top-level governance for all implementation decisions.

**For AI Agents**: Read `.github/copilot-instructions.md` first for architectural context, then refer to this document for coding standards and workflow requirements. The vendored Engineering DNA snapshot (`dna_repo/`) contains shared protocols (FAIL HARD, Pre-Commit Hygiene, Test Timeout Monitoring) and enforcement scripts; integrate these via pre-commit and CI as described in `design/engineering-dna-adoption.md`.

## Mission

Deliver a dependable, minimal restore pipeline that prioritizes correctness, clarity, and maintainability over feature breadth. Prototype fast, validate thoroughly, and expand only when real usage demands it.

## Guiding Principles

1. **Document First**: capture intent in `README.md`, `docs/mysql-schema.md`, and design notes before writing code. Every feature starts as prose and diagrams.
2. **FAIL HARD, Not Soft**: when something breaks, **stop immediately** and surface the root cause with diagnostic context. Never silently degrade, work around, or mask failures. Present users with: (1) what was attempted, (2) what failed and why, (3) potential solutions ranked by likelihood of success. Graceful degradation is acceptable only when explicitly documented as a fallback path with clear user notification.
3. **KISS**: prefer the simplest solution that works; avoid clever abstractions until experience proves they are required.
4. **Function Over Fashion**: choose reliability and transparency over stylistic novelty. Consistency matters more than novelty.
5. **Minimal Is Best**: ship the smallest viable slice (CLI + daemon REST API + MySQL) and iterate deliberately.
6. **Prototype Before Scale**: validate workflows end-to-end with constrained scope before layering on options, services, or automation.
7. **HCA Mandate**: All new development must strictly adhere to Hierarchical Containment Architecture (HCA) principles. Legacy code will be migrated incrementally; do not refactor old code unless necessary for the current task.

## HCA Enforcement

**Primary Directive**: All new development MUST utilize Hierarchical Containment Architecture (HCA). This is a strict requirement.

- **New Code**: Must be designed and implemented according to HCA principles (see `docs/IngestMe/HCA/`).
- **Legacy Code**: Existing code that does not follow HCA is currently exempt but will be migrated eventually. Do not refactor legacy code to HCA solely for the sake of refactoring; focus on new features and bug fixes using HCA.
- **Enforcement**: Code reviews and architectural decisions must prioritize HCA compliance.

## Architecture Charter

- CLI is a thin client that calls API service via HTTP; CLI has no AWS or MySQL access.
- API service accepts job requests, validates input, inserts jobs to MySQL, provides status queries; API service has no AWS or myloader access.
- Worker service polls MySQL queue, downloads from S3, executes restores via myloader; worker service has no HTTP exposure.
- API and Worker services coordinate exclusively via MySQL - never communicate directly.
- MySQL is the sole coordination layer. Enforce per-target exclusivity through schema constraints.
- S3 remains the system of record for backups; worker service downloads on demand, cleans up temp storage afterward.
- Configuration lives outside binaries (environment variables, MySQL settings table). Never hardcode secrets or host-specific settings.
- System always runs in development environment with read-only access to production S3 backups.
- Reference `Tools/pullDB/README.md` for flow diagrams, option scope, and future roadmap.
- See `.github/copilot-instructions.md` for architectural principles and critical design constraints.
- See `design/two-service-architecture.md` for detailed API/Worker service separation.

## FAIL HARD Philosophy

**Core Principle**: When an operation cannot complete as designed, **fail immediately** with comprehensive diagnostics rather than silently degrading or working around the issue.

### Fail Hard Requirements

Every failure must provide:

1. **Goal Context**: What was the system attempting to accomplish?
   - Example: "Attempting to restore customer database 'acme' from S3 backup dated 2025-10-31"

2. **Failure Point**: Where exactly did the operation fail?
   - Example: "S3 GetObject failed for key `daily/prod/acme/daily_mydumper_acme_2025-10-31T03-15-00Z_Sunday_dbimp.tar`"

3. **Root Cause Analysis**: Why did it fail?
   - Example: "AccessDenied: IAM role `pulldb-ec2-service-role` lacks `s3:GetObject` permission on production bucket"

4. **Ranked Solutions**: Potential fixes ordered by likelihood of success and alignment with original goal
   - Example:
     1. "Attach managed policy `pulldb-s3-read-access` to role (recommended - preserves least privilege)"
     2. "Grant inline policy with `s3:GetObject` on `arn:aws:s3:::prod-bucket/*`"
     3. "Switch to staging bucket with existing permissions (workaround - changes data source)"

### When to Fail Hard

- **Missing permissions**: Don't retry with degraded access - demand correct permissions

## Operational Hygiene Enforcement

The **Pre-Commit Hygiene Protocol** (defined in `.github/copilot-instructions.md`) is mandatory for every change. It enforces:

- Formatting (`ruff format`) followed by lint (`ruff check`) with zero violations
- Strict typing (`mypy .`) with no ignored errors
- Test execution under timeout guard (`pytest --timeout=60 --timeout-method=thread`)
- Drift ledger synchronization (feature status accurately reflected)
- `.gitignore` audit (exclude transient artifacts; retain business SQL & design docs)
- Commit message compliance (includes test count + hygiene declaration)

Any failure in the protocol triggers a FAIL HARD diagnostic report (Goal / Problem / Root Cause / Solutions) and blocks the commit until resolved. This ensures architectural intent, test coverage integrity, and repository cleanliness remain aligned.

Future automation (scripted pre-commit verifier, performance regression alerts, dependency security scanning) will extend this enforcement but must never bypass FAIL HARD transparency.
- **Configuration errors**: Don't fall back to defaults - require explicit correction
- **External service failures**: Don't mask AWS/MySQL errors - surface them with context
- **Schema mismatches**: Don't skip validations - halt until schema is correct
- **Credential resolution failures**: Don't use hardcoded fallbacks - fail until proper credential source is configured

### When Graceful Degradation Is Acceptable

Graceful degradation is permitted **only when**:

1. **Explicitly Documented**: The fallback path is described in design documents
2. **User Visible**: Clear warning/notice shown to user about degraded mode
3. **Non-Critical Path**: The degradation doesn't compromise data integrity or security
4. **Temporary Override**: Intended for local development only (never production/CI)

**Examples of Acceptable Degradation**:
- Test fixtures falling back to local MySQL credentials when AWS Secrets Manager unavailable (dev-only, with clear skip message)
- Skipping optional telemetry when metrics endpoint unreachable (logged warning)
- Using cached metadata when S3 list operation times out (logged, retried on next run)

**Examples of Unacceptable Degradation**:
- ❌ Continuing restore when disk space check fails
- ❌ Skipping post-restore SQL scripts when one fails
- ❌ Proceeding with invalid IAM permissions
- ❌ Masking database connection errors with empty results

### Implementation Patterns

**Error Messages Must Include**:
```python
raise OperationError(
    f"Failed to {goal}: {specific_error}. "
    f"Root cause: {diagnosis}. "
    f"Solutions: (1) {best_solution}, (2) {alternative}, (3) {workaround}"
) from original_exception
```

**Diagnostic Scripts**:
- Verification scripts (like `verify-secrets-perms.sh`) must fail with exit code != 0
- Print remediation steps to stderr
- Include commands user can copy-paste to fix issues

**Test Behavior**:
- Tests should fail loudly when preconditions not met
- Skip messages must explain what's missing and how to fix it
- Never hide test failures behind broad exception catching

### AI Agent Guidance

When implementing features or debugging issues:

1. **Detect the failure** using appropriate tools (`get_errors`, `run_in_terminal`, etc.)
2. **Research the root cause** - don't assume; verify with actual data/logs
3. **Present findings** in structured format:
   - **Goal**: What was supposed to happen
   - **Problem**: What actually happened (specific error/symptom)
   - **Root Cause**: Why it happened (validated diagnosis, not speculation)
   - **Solutions**: Ranked list of fixes with pros/cons
4. **Implement the fix** that best aligns with project architecture
5. **Verify the fix** resolves the root cause (not just the symptom)

## Tooling & Language Policy

- **Python 3.11+**: primary implementation language for the CLI, API service, and worker service.
- **MySQL**: API and worker services use `mysql-connector-python` or `PyMySQL` for coordination database access; wrap access in thin repositories to keep SQL close to the domain. CLI does not access MySQL.
- **AWS S3**: worker service interacts via `boto3` with least-privilege IAM roles. Mock calls in tests using moto or local stubs. CLI and API service do not access S3.
- **MySQL Restore**: worker service orchestrates `myloader` or compatible utilities for ingestion into MySQL 8.x. Shell out through well-audited helpers and capture logs for diagnostics.
- **REST API**: API service provides HTTP REST API using Flask or FastAPI. CLI calls this API for all operations.
- **Shell Utilities**: prefer Python wrappers; when shells are necessary ensure commands are idempotent and checked for non-zero exit codes.

## Coding Standards

**Primary Reference**: See [docs/coding-standards.md](docs/coding-standards.md) for comprehensive standards covering all file types:
- Python (PEP 8, PEP 484 type hints)
- Markdown (CommonMark, GitHub Flavored Markdown)
- SQL (SQL Style Guide with MySQL adaptations)
- Shell Scripts (Google Shell Style Guide)
- YAML (YAML best practices)
- Mermaid Diagrams (Mermaid documentation standards)

**Quick Summary**:

### Python Style (PEP 8 Compliance)

All Python code must follow [PEP 8](https://peps.python.org/pep-0008/) style guidelines with the following specifics:

**Line Length & Formatting:**
- Maximum line length: 88 characters (Black formatter default)
- Use 4 spaces for indentation (never tabs)
- Two blank lines between top-level functions and classes
- One blank line between methods within a class
- Trailing commas in multi-line structures (lists, dicts, function args)

**Naming Conventions:**
- Modules: `lowercase_with_underscores.py`
- Classes: `CapitalizedWords` (PascalCase)
- Functions/methods: `lowercase_with_underscores` (snake_case)
- Constants: `UPPERCASE_WITH_UNDERSCORES`
- Private attributes/methods: prefix with single underscore `_private`

**Docstrings:**
- Use triple double-quotes `"""` for all docstrings
- Module docstring at top of file explaining purpose
- Function/method docstrings with Args, Returns, Raises sections
- Use Google-style or NumPy-style docstring format consistently
- Example:
  ```python
  def function_name(arg1: str, arg2: int) -> bool:
      """Brief description of function.

      More detailed description if needed.

      Args:
          arg1: Description of arg1
          arg2: Description of arg2

      Returns:
          Description of return value

      Raises:
          ValueError: Description of when this is raised
      """
  ```

**Type Hints:**
- Use type hints for all function signatures (PEP 484)
- Import types from `typing` or use built-in types (Python 3.10+)
- Use `from __future__ import annotations` for forward references
- Explicit return types required (including `-> None`)
- Example: `def process(data: list[str]) -> dict[str, int]:`

**Imports:**
- Group imports in order: standard library, third-party, local
- One import per line for `import` statements
- Alphabetize within groups
- Absolute imports preferred over relative
- Example:
  ```python
  from __future__ import annotations

  import os
  import sys
  from pathlib import Path

  import boto3
  import click

  from pulldb.domain import Config
  ```

**Code Organization:**
- Structure modules by domain (`cli`, `daemon`, `domain`, `infra`)
- Keep files under 500 lines; split if larger
- One class per file for significant domain classes
- Inject dependencies (S3 client, DB connection) for testability
- Avoid global state and mutable defaults

**Error Handling:**
- Handle errors explicitly with specific exception types
- Always use `from e` when re-raising (preserve traceback)
- Surface actionable error messages
- Attach context to `job_events` for debugging
- Example:
  ```python
  except SpecificError as e:
      raise ValueError(f"Context about what failed: {e}") from e
  ```

**Logging:**
- Use Python `logging` module (never `print()`)
- Structured JSON payloads where practical
- Include context: job_id, target, phase
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Code Quality Tools

**Primary Tools**:
- **Ruff**: Ultra-fast Python linter and formatter (replaces Flake8, Black, isort, pydocstyle)
  - **Speed**: 10-100x faster than traditional tools, written in Rust
  - **Comprehensive**: Implements 500+ rules from multiple linters
  - **Auto-fix**: Automatically fixes many issues (imports, formatting, etc.)
  - `ruff check .` - Lint code, show all issues
  - `ruff check --fix .` - Lint and auto-fix issues
  - `ruff format .` - Format code (Black-compatible)
  - `ruff rule D101` - Show documentation for specific rule
  - **VS Code Extension**: Real-time diagnostics (`charliermarsh.ruff`)
- **mypy**: Static type checker for Python
  - `mypy pulldb/` - Check types
  - Catches type errors before runtime
- **pytest**: Testing framework
  - `pytest` - Run all tests
  - `pytest --cov=pulldb tests/` - Run with coverage
- **pre-commit**: Git hook framework for automated checks
  - `pre-commit install` - Install hooks
  - `pre-commit run --all-files` - Run all hooks
  - Runs Ruff, mypy, and other linters automatically on commit

### Legacy Standards (Preserved)
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

1. **Setup** (first time only):
   ```bash
   pip install -e ".[dev]"  # Install package with dev dependencies
   pre-commit install        # Install git pre-commit hooks
   ```
2. Update documentation first (design notes, strategy, schema).
3. Create or update tests covering the change.
4. Implement code adhering to the architecture charter and coding standards.
5. **Quality checks** (automated via pre-commit hooks on git commit):
   ```bash
   ruff check .              # Linting (PEP 8, best practices)
   ruff format .             # Auto-formatting
   mypy .                    # Type checking
   python -m pytest          # Run tests
   ```
6. Update diagrams or docs impacted by the change.
7. Submit PR with clear rationale, testing evidence, and doc references.

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
