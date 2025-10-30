# Copilot Instructions for pullDB

## Project Overview

pullDB is a database restoration tool that pulls production MySQL backups from S3 and restores them to development environments. The system follows a **documentation-first, prototype-first** approach with extensive planning before implementation.

**Current Status**: Pre-implementation phase - comprehensive design documentation exists but no code has been written yet.

## Architecture Principles

- **Single CLI + Daemon**: CLI validates and enqueues jobs, daemon executes them
- **MySQL as Coordination Layer**: All state, locks, and job tracking via MySQL database
- **Download-Per-Job**: No archive reuse in prototype - download fresh each time
- **Per-Target Exclusivity**: MySQL constraints prevent concurrent restores to same target database

## Key Files & Directory Structure

```
README.md                    # Complete API reference and usage patterns
constitution.md             # Coding standards, tooling choices, principles
design/
  ├── system-overview.md     # Component responsibilities and interactions  
  ├── implementation-notes.md # Python structure and integration patterns
  ├── configuration-map.md   # Config sources and SQLite settings flow
  └── roadmap.md            # Deferred features documentation requirements
docs/
  └── mysql-schema.md      # Complete database schema with invariants
```

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
- UUIDs for primary keys (`user_id`, `job_id`)
- UTC timestamps in ISO-8601 format via `UTC_TIMESTAMP(6)`
- Status constraints: `('queued','running','failed','complete','canceled')`
- Per-target job exclusivity: `UNIQUE INDEX ON jobs(target) WHERE status IN ('queued','running')`
- Foreign key constraints enabled
- Triggers for automatic event logging on status changes

### Configuration Philosophy
- Environment variables for secrets and deployment-specific values
- MySQL `settings` table for runtime configuration  
- Never hardcode credentials or host-specific settings in code
- Support AWS Secrets Manager/SSM for credential references

## Python Implementation Guidelines

### Project Structure (from `design/implementation-notes.md`)
```python
pulldb/
  cli/           # Command validation, option parsing, MySQL job insertion
  daemon/        # Job polling, S3 download, MySQL restore orchestration  
  infra/         # MySQL, S3, logging abstractions
  domain/        # Job, JobEvent, configuration dataclasses
  tests/         # Unit tests with test MySQL instances, integration smoke tests
```

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
- **Post-Restore SQL Scripts**: After successful restore, SQL files from `customers_after_sql/` or `qa_template_after_sql/` directories are executed
- **Single Addition**: Only one `pullDB` table is added to track restore metadata
- **Restore Metadata Table**: Contains user who restored, restore timestamp, backup filename used, and JSON report of post-restore SQL script execution status

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