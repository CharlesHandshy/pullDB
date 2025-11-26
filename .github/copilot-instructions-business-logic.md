# Business Logic & Domain Concepts

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
- AWS Secrets Manager for MySQL target database credentials (credential_ref pattern)
- AWS Parameter Store for configuration values (values starting with `/` auto-resolved)
- AWS profile-only authentication (`PULLDB_AWS_PROFILE` required, no explicit credentials)
- `.env` file for local development (gitignored)
- **Two-phase loading**: Bootstrap from environment → Enrich from MySQL settings table

### Credential Resolution (Implemented)
- **CredentialResolver**: Production-ready class for resolving MySQL credentials
- **Supported formats**:
  - `aws-secretsmanager:/pulldb/mysql/{db-name}` (recommended)
  - `aws-ssm:/pulldb/mysql/{param-name}` (alternative)
- **Usage**: `resolver = CredentialResolver(); creds = resolver.resolve(credential_ref)`
- **Testing**: Command-line interface available: `python3 -m pulldb.infra.secrets <credential_ref>`
- **Documentation**: See `docs/aws-secrets-manager-setup.md` for complete setup guide
- **Profile Split (Nov 14 2025)**: Use the EC2 instance profile (preferred) or `pr-dev` for Secrets Manager/MySQL access. `pr-staging` and `pr-prod` are reserved for staging/production S3 reads and deliberately lack secret permissions.

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

## Common Pitfalls to Avoid

- Don't implement deferred features marked in roadmap.md
- Never hardcode credentials, hosts, or S3 bucket names
- Don't retry failed jobs automatically - require manual resubmission
- Don't allow multiple active jobs per target database
- Don't implement cancellation, history, or admin commands in prototype
- Ensure all database operations are wrapped in transactions
- Validate CLI options before calling daemon API, daemon validates again before MySQL insertion

## Key Domain Concepts

- **Job**: User restore request with options, owner, target, and lifecycle status
- **Target**: Sanitized database name derived from user_code + customer/template
- **Lock**: Advisory coordination mechanism for per-target exclusivity
- **Event**: Audit trail entry for job lifecycle transitions and troubleshooting
- **Host Registration**: Pre-configured database servers with capacity limits
