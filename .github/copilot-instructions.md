# Copilot Instructions for pullDB

## Overview

This document is the **primary reference for AI coding agents** working on pullDB. It distills the essential architecture, patterns, and constraints from the comprehensive documentation. Always read this file first, then consult other documents as needed.

**Related Documents**: Read `constitution.md` for coding standards, tooling philosophy, and development workflow. Read `docs/coding-standards.md` for comprehensive style guidelines for all file types (Python, Markdown, SQL, Shell, YAML, Mermaid). These documents form the foundation—all other documentation flows from these principles.

## Project Overview

pullDB is a database restoration tool that pulls production MySQL backups from S3 and restores them to development environments. The system follows a **documentation-first, prototype-first** approach with extensive planning before implementation.

**Current Status**: Pre-implementation phase - comprehensive design documentation exists but no code has been written yet.

**Environment Context**:
- **Development environment** (`345321506926`) runs pullDB and needs cross-account S3 access to:
  - **Staging backups** (`333204494849`): `s3://pestroutesrdsdbs/daily/stg/` - **Primary for development** - Contains both newer and older mydumper format backups for testing
  - **Production backups** (`448509429610`): `s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/` - Older mydumper format (will migrate to newer format post-implementation)
- **Prototype development**: Use staging backups as primary source (has both formats available)
- Multi-format mydumper support required (deferred feature - see roadmap.md)

## Architecture Principles

- **Single CLI + Daemon**: CLI validates and enqueues jobs, daemon executes them
- **MySQL as Coordination Layer**: All state, locks, and job tracking via MySQL database
- **Download-Per-Job**: No archive reuse in prototype - download fresh each time
- **Per-Target Exclusivity**: MySQL constraints prevent concurrent restores to same target database

## Key Files & Directory Structure

```
.github/copilot-instructions.md  # THIS FILE - Primary AI agent reference
constitution.md                   # Coding standards and development workflow (co-primary)
docs/
  ├── coding-standards.md         # Comprehensive style guide for all file types
  ├── mysql-schema.md             # Complete database schema with invariants
  ├── aws-setup.md                # AWS CLI and SDK configuration overview
  ├── aws-cross-account-setup.md  # Cross-account S3 access with IAM user (local dev)
  ├── aws-service-role-setup.md   # Cross-account S3 access with service roles (production)
  ├── aws-iam-setup.md            # IAM users, roles, and policies
  └── parameter-store-setup.md    # Secure credential storage in AWS
customers_after_sql/              # Post-restore SQL for customer databases (PII removal)
  ├── 010.remove_customer_pii.sql
  ├── 020.remove_billto_info.sql
  └── ... (120.reset_business_registration.sql)
qa_template_after_sql/            # Post-restore SQL for QA templates (currently empty)
  └── README.md                   # Explains no scripts needed for QA templates
reference/                        # Legacy PHP implementations (read-only)
  ├── pullDB-auth                 # Customer restore with obfuscation
  └── pullQA-auth                 # QA template restore
```

**Documentation Hierarchy**: This file + constitution.md are top-level guides. All other docs elaborate on specific aspects defined here.

## Critical Design Constraints

### CLI Usage Pattern
```bash
pullDB user=jdoe customer=acme dbhost=dev-db-01 [overwrite]
pullDB user=jdoe qatemplate [overwrite]
pullDB status
```
- `user=` must be first, requires 6+ alphabetic chars for user_code generation
- Exactly one of `customer=` or `qatemplate` required (mutually exclusive)
- `dbhost=` optional, falls back to configured default
- `overwrite` prevents interactive prompts for existing targets

### MySQL Schema Patterns
- Timestamps with microsecond precision via `CURRENT_TIMESTAMP(6)` (MySQL 8.0 compatible)
  - Implemented using generated virtual column `active_target_key` (MySQL 8.0 doesn't support partial indexes)

### Configuration Philosophy
- AWS Parameter Store for secure credential storage (values starting with `/` auto-resolved)
- AWS profile-only authentication (`PULLDB_AWS_PROFILE` required, no explicit credentials)
- `.env` file for local development (gitignored)

## Python Implementation Guidelines

### Proactive Error Checking

**CRITICAL**: Always use the `get_errors` tool to check for VS Code diagnostics before and after editing files. This tool provides access to:
- **Ruff diagnostics**: Missing docstrings (D101-D107), style violations (E, W), unused imports (F401), etc.
- **Mypy diagnostics**: Type checking errors, incompatible types, missing type hints
- **Other linters**: Any configured VS Code extensions

**Workflow**:
1. Before editing: `get_errors` on target files to understand existing issues
2. Make changes addressing the issues
3. After editing: `get_errors` to verify fixes and check for new issues
4. Iterate until all errors are resolved

**Example Error**: `config.py:16 - Missing docstring in public class Ruff(D101)`
- **Action**: Add comprehensive Google-style docstring to class
- **Verification**: Run `get_errors` again to confirm fix

### Project Structure (from `design/implementation-notes.md`)
```python
pulldb/
  cli/           # Command validation, option parsing, MySQL job insertion
  daemon/        # Job polling, S3 download, MySQL restore orchestration
  infra/         # MySQL, S3, logging abstractions
  domain/        # Job, JobEvent, configuration dataclasses
  tests/         # Unit tests with test MySQL instances, integration smoke tests
```

### Code Style (PEP 8 Required)
**Primary Reference**: See `docs/coding-standards.md` for complete standards covering Python, Markdown, SQL, Shell, YAML, and Mermaid.

**Python Quick Reference**:
- **Primary linter**: Ruff (replaces Flake8, isort, pydocstyle, etc.) - 10-100x faster
- **Maximum line length**: 88 characters (Ruff/Black default)
- **Type hints required**: All function signatures must include type hints (checked by mypy)
- **Docstrings required**: Google-style docstrings for all public functions/classes (Ruff D101-D107)
- **Import order**: stdlib, third-party, local (alphabetized within groups, enforced by Ruff I001)
- **Naming**: snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants (Ruff N802, N806)
- **Error handling**: Use specific exceptions, always `raise ... from e` to preserve traceback (Ruff B904)
- **No print statements**: Use Python `logging` module exclusively (Ruff T201)
- **Quality tools**: Code must pass `ruff check`, `ruff format`, `mypy`, and tests before commit
- **VS Code integration**: Use `get_errors` tool to access real-time Ruff/mypy diagnostics

**Other File Types**:
- **Markdown**: Follow CommonMark + GitHub Flavored Markdown (enforced by markdownlint)
- **SQL**: SQL Style Guide with MySQL dialect (enforced by sqlfluff)
- **Shell**: Google Shell Style Guide (enforced by shellcheck + shfmt)
- **YAML**: YAML 1.2 spec (enforced by yamllint)
- **Mermaid**: Clear node IDs, descriptive labels, consistent styling

All standards automatically enforced via pre-commit hooks. See `constitution.md` and `docs/coding-standards.md` for complete details.

### Dependency Patterns
- **MySQL**: `mysql-connector-python` or `PyMySQL` for coordination database and restored databases
- **S3**: `boto3.client('s3')` with paginated listing for latest backup discovery
- **MySQL Restore**: Shell out to `myloader` via `subprocess.run`, capture stdout/stderr
- **Testing**: `pytest` with fixtures, moto for S3 mocking, test MySQL instances
- **Logging**: Structured JSON via Python `logging`, include job_id/target/phase

### Repository Pattern
```python
class JobRepository:
    def enqueue_job(self, job: Job) -> None: ...
    def mark_running(self, job_id: str) -> None: ...
    def append_event(self, job_id: str, event_type: str, detail: str) -> None: ...
```

## Critical Business Logic

### User Code Generation
- Extract first 6 alphabetic characters from username (strip non-letters, lowercase, letters only)
- Handle collisions by replacing 6th char with next unused letter from username
- Escalate to 5th, then 4th position if needed (max 3 adjustments)
- Fail if unique 6-char code cannot be generated

### Target Database Naming
- Customer: `{user_code}{sanitized_customer_id}`
- QA Template: `{user_code}qatemplate`
- Sanitization: lowercase, remove all non-letter characters (letters only)
- **Length Limit**: Maximum 51 characters (reserves 13 chars for staging suffix: `_` + 12-char job_id)
- **MySQL Constraint**: Total staging name must not exceed 64 characters
- Validation must reject customer IDs that would result in target > 51 chars

### S3 Backup Discovery
- Path: `pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/{customer|qatemplate}`
- Pattern: `daily_mydumper_{target}_{YYYY-MM-DDThh-mm-ssZ}_{Day}_dbimp.tar`
- Validate `*-schema-create.sql.zst` exists before download
- Require `size * 1.8` free space before extraction

### Disk Capacity Management
- Check available space before extraction: `tar_size + (tar_size * 1.8)`
- Clean up only temp working directory for current job
- No automatic pruning of historical restores

### MySQL Restore Behavior
- **Read-Only Restore**: Restored MySQL databases are never modified after myloader completes
- **Post-Restore SQL Scripts**: After successful restore, SQL files from `customers_after_sql/` or `qa_template_after_sql/` directories are executed in lexicographic order
- **Script Naming Convention**: Files named `NNN.descriptive_purpose.sql` (e.g., `010.remove_customer_pii.sql`)
- **Execution Order**: Scripts execute sequentially (010, 020, 030...) with status tracked
- **Customer Sanitization**: Customer databases require 12 post-restore scripts removing PII, credentials, and disabling external integrations
- **QA Templates**: No post-restore scripts needed (already sanitized in production)
- **Single Addition**: Only one `pullDB` table is added to track restore metadata
- **Restore Metadata Table**: Contains user who restored, restore timestamp, backup filename used, and JSON report of post-restore SQL script execution status

### Staging-to-Production Rename Pattern (MANDATORY)
- **Staging Name**: `<target>_<job_id_first_12_chars>` (e.g., `jdoecustomer_550e8400e29b`)
- **Length Constraints**: Target max 51 chars + suffix 13 chars = staging name max 64 chars (MySQL limit)
- **Orphaned Cleanup**: Before restore, auto-drop all staging databases matching `{target}_[0-9a-f]{12}` pattern
- **Cleanup Rationale**: User re-restoring same target implies done examining previous staging databases
- **Uniqueness Check**: Verify staging name doesn't exist after cleanup (should never exist)
- **Restore Target**: myloader restores to staging database, not final target
- **Post-Restore SQL**: Execute against staging database
- **Metadata Table**: Add `pullDB` table to staging database with job details
- **Atomic Rename**: Use stored procedure to rename all tables staging → target
- **Cleanup**: Drop staging database after successful rename
- **Failure Handling**: Preserve staging database on failure; auto-cleaned on next restore to same target
- **Safety Benefits**: Zero downtime, validation before cutover, rollback capability, audit trail

## Testing Strategy

### Unit Tests
- Test MySQL instances with temporary databases
- Mock S3 calls with moto library
- Mock subprocess calls to avoid external dependencies
- Test user_code generation edge cases and collision handling

### Integration Tests
- Use local installed shared MySQL instance for disposable MySQL instances ensuring consistent environment and cleanup after tests always
- Test complete restore flow against staging S3 bucket
- Verify cleanup and error handling scenarios

## Development Workflow

1. **Document First**: Update design docs before any code changes
2. **Test-Driven**: Write tests covering success/failure cases before implementation
3. **Schema-Driven**: MySQL constraints enforce business rules
4. **Migration-Safe**: Forward-only SQL migrations, no downgrades supported

## Common Pitfalls to Avoid

- Don't implement deferred features marked in roadmap.md
- Never hardcode credentials, hosts, or S3 bucket names
- Don't retry failed jobs automatically - require manual resubmission
- Don't allow multiple active jobs per target database
- Don't implement cancellation, history, or admin commands in prototype
- Ensure all database operations are wrapped in transactions
- Validate CLI options before MySQL insertion, not in daemon

## Key Domain Concepts

- **Job**: User restore request with options, owner, target, and lifecycle status
- **Target**: Sanitized database name derived from user_code + customer/template
- **Lock**: Advisory coordination mechanism for per-target exclusivity
- **Event**: Audit trail entry for job lifecycle transitions and troubleshooting
- **Host Registration**: Pre-configured database servers with capacity limits

Read `README.md` first for complete context, then refer to specific design documents for implementation details.
