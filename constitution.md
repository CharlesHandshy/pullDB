# pullDB Constitution

## Purpose

This document establishes the foundational principles, standards, and workflows for the pullDB project. Together with `.github/copilot-instructions.md` (which provides architectural overview and AI agent guidance), this constitution forms the top-level governance for all implementation decisions.

**For AI Agents**: Read `.github/copilot-instructions.md` first for architectural context, then refer to this document for coding standards and workflow requirements.

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
- Configuration lives outside binaries (environment variables, MySQL settings table). Never hardcode secrets or host-specific settings.
- System always runs in development environment with read-only access to production S3 backups.
- Reference `Tools/pullDB/README.md` for flow diagrams, option scope, and future roadmap.
- See `.github/copilot-instructions.md` for architectural principles and critical design constraints.

## Tooling & Language Policy

- **Python 3.11+**: primary implementation language for the CLI and daemon.
- **MySQL**: use `mysql-connector-python` or `PyMySQL` for coordination database access; wrap access in thin repositories to keep SQL close to the domain.
- **AWS S3**: interact via `boto3` with least-privilege IAM roles. Mock calls in tests using moto or local stubs.
- **MySQL Restore**: orchestrate `myloader` or compatible utilities for ingestion into MySQL 8.x. Shell out through well-audited helpers and capture logs for diagnostics.
- **MySQL Client Libraries**: use `mysql-connector-python` or `PyMySQL` for light metadata queries. Keep credentials external.
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
