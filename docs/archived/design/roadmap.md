# Roadmap (Documentation-First)

[← Back to Documentation Index](../docs/START-HERE.md) · [Design README](README.md)

> **Governance**: All feature additions must align with principles in `../.github/copilot-instructions.md` and `../constitution.md`. Update those documents first if architectural changes are needed.

This roadmap records deferred features and the documentation prerequisites before implementation begins. Always update this file before expanding scope.

## FAIL HARD Roadmap Guardrail

Every future feature MUST document its failure boundaries pre-implementation:
- Hard-stop vs permissible dev-only downgrade conditions
- Observability additions required (metrics / events) to surface Problem + Root Cause
- Ranked remediation strategies drafted before code

Features lacking these remain deferred until documentation satisfies FAIL HARD standards.

## Phase 0 – Prototype ✅ COMPLETE (v0.0.7)

All Phase 0 components implemented and tested:

### Infrastructure Layer (Complete)
- ✅ MySQL schema provisioned (consolidated schema files)
- ✅ Credential resolution (Secrets Manager + SSM) - `pulldb/infra/secrets.py`
- ✅ Configuration loader (two-phase) - `pulldb/domain/config.py`
- ✅ Repository layer (Job/User/Host/Settings) - `pulldb/infra/mysql.py`
- ✅ Domain models - `pulldb/domain/models.py`, `pulldb/domain/restore_models.py`
- ✅ Structured JSON logging abstraction - `pulldb/infra/logging.py`
- ✅ Domain error classes - `pulldb/domain/errors.py`
- ✅ S3 client with cross-account support - `pulldb/infra/s3.py`
- ✅ Multi-location S3 backup support via `PULLDB_S3_BACKUP_LOCATIONS`

### Worker Layer (Complete)
- ✅ Worker poll loop with exponential backoff - `pulldb/worker/loop.py`
- ✅ Worker service with graceful shutdown - `pulldb/worker/service.py`
- ✅ Job executor orchestration - `pulldb/worker/executor.py`
- ✅ S3 backup discovery with env filtering - `pulldb/worker/executor.py`
- ✅ Downloader with disk capacity guard - `pulldb/worker/downloader.py`
- ✅ Myloader subprocess wrapper - `pulldb/worker/restore.py`
- ✅ Post-restore SQL executor - `pulldb/worker/post_sql.py`
- ✅ Staging lifecycle (orphan cleanup, name generation) - `pulldb/worker/staging.py`
- ✅ Atomic rename via stored procedure - `pulldb/worker/atomic_rename.py`
- ✅ Metadata injection - `pulldb/worker/metadata.py`, `pulldb/worker/metadata_synthesis.py`
- ✅ Log normalizer for myloader output - `pulldb/worker/log_normalizer.py`
- ✅ Profiling capture - `pulldb/worker/profiling.py`
- ✅ Cleanup module - `pulldb/worker/cleanup.py`

### CLI Layer (Complete)
- ✅ CLI argument parsing with multiple syntax styles - `pulldb/cli/parse.py`
  - `option=value`, `--option=value`, `--option value`
- ✅ Main CLI commands - `pulldb/cli/main.py` (1788 lines)
  - `restore` - Submit restore jobs
  - `status` - View job status (with short ID prefix support)
  - `search` - Search available backups across configured locations
  - `cancel` - Cancel jobs (with short ID prefix support)
  - `events` - View job events (with --follow and --full options)
  - `history` - View job history with filtering
  - `profile` - View job profiling data
- ✅ Admin CLI commands - `pulldb/cli/admin.py`, `pulldb/cli/admin_commands.py`

### API Layer (Complete)
- ✅ FastAPI service - `pulldb/api/main.py` (1618 lines, 18 endpoints)
  - POST /api/jobs - Submit jobs
  - GET /api/jobs - List jobs with filtering
  - GET /api/jobs/{job_id} - Get job details
  - GET /api/jobs/resolve/{prefix} - Resolve job ID prefix
  - GET /api/jobs/search - Search backups
  - GET /api/users/{username} - Get user info
  - GET /api/status - System status
  - GET /api/health - Health check
  - POST /api/jobs/{job_id}/cancel - Cancel job
  - GET /api/jobs/{job_id}/events - Get job events
  - GET /api/jobs/{job_id}/profile - Get job profile
  - GET /api/history - Job history

### Testing (Complete)
- ✅ 328 unit tests passing
- ✅ 7 integration test files covering:
  - Workflow happy path (`test_integration_workflow.py`)
  - Disk insufficient scenarios (`test_integration_disk_insufficient.py`, `test_integration_workflow_disk_insufficient.py`)
  - Missing backup handling (`test_integration_missing_backup.py`)
  - Workflow failure modes (`test_integration_workflow_failures.py`)

### Metrics (Complete)
- ✅ Metrics module - `pulldb/infra/metrics.py`
  - `emit_counter()` - counters (jobs_enqueued, jobs_completed, etc.)
  - `emit_gauge()` - point-in-time values (queue_depth, active_restores)
  - `emit_timer()` - durations (restore_duration_seconds)
  - `emit_event()` - significant occurrences with context
  - `time_operation()` - context manager for timing

### Bootstrap Milestone Scope (All Complete)
1. Logging abstraction + domain error classes – ✅
2. Worker poll loop & basic event emission – ✅
3. S3 backup discovery & selection logic – ✅
4. Downloader (stream + disk capacity preflight + extraction) – ✅
5. myloader subprocess wrapper & restore orchestration – ✅
6. Post-restore SQL executor + results JSON + metadata table – ✅
7. Staging lifecycle (orphan cleanup, name generation, atomic rename) – ✅
8. CLI argument validation + enqueue + status listing – ✅
9. Integration tests (happy path + failure modes) – ✅ (7 test files)
10. Metrics emission (queue depth, restore durations, disk failures) – ✅

Each item must ship with tests and must not regress existing passing suite (100% required). Items may be merged incrementally once their tests pass and documentation sections are updated (README drift ledger + copilot instructions drift tracking).

## Phase 0.5 – Hardening (Future)

Deferred items that can wait until after production use begins:

1. **Tar Extraction Streaming** - Currently extracting archives to disk; could stream directly to myloader
2. **Format Auto-Detection** - Currently assumes single mydumper format; multi-format support deferred
3. **Cross-Account Multi-Source** - Currently single backup source; multi-environment access deferred

### Deferred for Post-Prototype

The following features are documented but intentionally deferred from the prototype:

1. **Multi-Environment Backup Access** - See below for full documentation
2. **Multiple mydumper Format Support** - See below for full documentation

## Multi-Environment Backup Access

### Context

**Current State (as of Oct 2025):**
- **Development environment** needs access to backups from **both staging and production** accounts
- **Staging account** (`333204494849`): Contains newer mydumper format backups
- **Production account** (`448509429610`): Currently contains older mydumper format backups
  - Will migrate to newer mydumper format after pullDB implementation is complete

**Account Relationships:**
```
Dev Account (345321506926)
├── Needs read access → Staging Account (333204494849) - newer mydumper format
└── Needs read access → Production Account (448509429610) - older mydumper format (migrating)
```

### Rationale for Deferral

- Prototype can start with single backup source (staging account recommended for development)
- Staging account contains both older and newer format backups, allowing format testing
- Cross-account setup for second environment can be added later
- Core restore workflow is identical regardless of backup source
- Allows focus on daemon architecture and MySQL coordination

### Implementation Considerations

1. **AWS Profile Configuration**: Dev environment will need two cross-account role configurations:
   ```ini
   [profile pr-prod]
   role_arn = arn:aws:iam::448509429610:role/PullDB-CrossAccount-ReadOnly
   ...

   [profile pr-staging]
   role_arn = arn:aws:iam::333204494849:role/PullDB-CrossAccount-ReadOnly
   ...
   ```

2. **S3 Bucket Discovery**: CLI/daemon needs parameter to specify which environment's backups to use:
   ```bash
   pulldb user=jdoe customer=acme source=staging  # use staging backups
   pulldb user=jdoe customer=acme source=prod     # use production backups
   ```

3. **Configuration**: Extend Config class to support multiple S3 buckets and AWS profiles

### Prerequisites

- [ ] Document staging account S3 bucket name and path structure (DONE: `s3://pestroutesrdsdbs/daily/stg/`)
- [ ] Create staging account cross-account IAM role (mirror production setup)
- [ ] Add staging AWS profile to dev environment
- [ ] Add `source=` CLI parameter validation
- [ ] Add `PULLDB_BACKUP_SOURCE` environment variable support
- [ ] Update configuration-map.md with new parameters

### Documentation Requirements

When implementing multi-environment support:
- Update aws-authentication-setup.md to cover staging account setup
- Add staging bucket details to system-overview.md
- Document source selection logic in implementation-notes.md
- Add source parameter to README.md usage examples

## Multiple mydumper Format Support

### Context

pullDB must support **two different mydumper backup formats**:

1. **Older mydumper format**
   - Available in staging account (for testing)
   - Currently in production account (will migrate after pullDB completion)
   - Format details TBD when implementation begins

2. **Newer mydumper format**
   - Available in staging account (for testing)
   - Production will migrate to this format after pullDB is complete

**Development Strategy**: Use staging account (`333204494849`) for development and testing since it contains **both** backup formats. This allows testing multi-format support without production access.

**Migration Timeline**: Production will adopt newer mydumper format **after** pullDB is fully implemented and deployed.

### Rationale for Deferral

- Format differences are not yet fully documented
- Implementation requires analysis of both backup formats
- Prototype can start with single format support (allows faster delivery)
- Must be completed before production rollout (blocking requirement)
- Provides time to document format differences during prototype phase

### Design Considerations

1. **Format Detection**: Automatically detect backup format from archive structure or manifest files
   - Possible indicators: filename patterns, directory structure, manifest file content
   - Must work without full extraction (efficiency)

2. **Restore Strategy Selection**: Use appropriate myloader version/flags based on detected format
   - Determine if different myloader binaries required or just different flags
   - Encapsulate format-specific logic in dedicated module

3. **Validation**: Ensure restored database is valid regardless of source format
   - Post-restore checks should be format-agnostic
   - Verify table counts, schema integrity, data sampling

4. **Migration Path**: Document testing strategy when production migrates formats
   - Maintain backward compatibility during transition
   - Test both formats in parallel during migration period

### Prerequisites

- [ ] Document older mydumper format structure (filenames, directory layout, manifests)
- [ ] Document newer mydumper format structure (differences from older format)
- [ ] Identify format detection mechanism (propose 2-3 options with pros/cons)
- [ ] Document myloader restore command for older format (binary, flags, options)
- [ ] Document myloader restore command for newer format (binary, flags, options)
- [ ] Acquire sample backups from both formats for testing
- [ ] Create integration test matrix covering both formats
- [ ] Determine if different myloader versions are needed or just different flags

### Documentation Requirements

When implementing multi-format support:
- Create docs/backup-formats.md with format specifications (DONE - placeholder created)
- Add format detection logic to design/implementation-notes.md
- Document myloader version requirements and installation
- Update runbook-restore.md with format-specific troubleshooting steps
- Add format validation to integration test documentation
- Update system-overview.md with format detection architecture

### Success Criteria

Multi-format support is complete when:
- [ ] pullDB can detect backup format without user input
- [ ] Restores succeed from both older and newer formats
- [ ] Integration tests pass with sample backups from both formats
- [ ] Post-restore SQL scripts execute correctly for both formats
- [ ] Staging database rename pattern works with both formats
- [ ] Documentation explains format differences and detection logic
- [ ] Performance is acceptable for both formats (within 10% of each other)

---

## Phase 1 – Operational Enhancements ✅ COMPLETE (v0.0.6)

### Implemented
- ✅ **Cancellation Support**
  - `request_cancellation()`, `mark_job_canceled()`, `is_cancellation_requested()` in `pulldb/infra/mysql.py`
  - CLI `pulldb cancel <job_id>` command with `--force` option
  - Worker checks cancellation at each phase and exits gracefully
  - 7 tests in `pulldb/tests/test_cancellation.py`
  
- ✅ **History Endpoint**
  - `get_history()` method in JobRepository with pagination
  - CLI `pulldb history` command with filtering by status, limit, username
  - API `/history` endpoint
  
- ✅ **Job Events Table**
  - `job_events` table for event storage
  - `append_event()` method in JobRepository
  - CLI `pulldb events <job_id>` command with `--follow` and `--json` options
  - 4 tests in `pulldb/tests/test_job_logs.py`

- ✅ **Scheduled Staging Database Cleanup**
  - `pulldb/worker/cleanup.py` (full module, 23 tests)
  - Background cleanup of abandoned staging databases
  - Query failed jobs and scan each dbhost for orphaned staging databases
  - Safety checks: verify staging matches job record pattern before deletion
  - Audit logging via job_events
  - `CleanupCandidate`, `OrphanDatabase`, `CleanupReport` data classes
  - Orphan detection (no auto-delete, requires manual review)

- ✅ **Configurable Cleanup Age Threshold**
  - `get_staging_cleanup_retention_days()` in SettingsRepository
  - Configurable via `settings` table key `staging_cleanup_retention_days`
  - Default: 7 days. Set to 0 to disable automatic cleanup
  - Schema seed: `schema/pulldb_service/211_seed_cleanup_retention.sql`
  - 4 tests in `pulldb/tests/test_settings_repository.py`

- ✅ **Cleanup Metrics**
  - `staging_cleanup_databases_dropped_total` - counter
  - `staging_cleanup_jobs_archived_total` - counter
  - `staging_cleanup_errors_total` - counter
  - `staging_cleanup_orphans_detected` - gauge

## Phase 2 – Concurrency Controls & Usability ✅ COMPLETE (v0.0.6)

### Implemented
- ✅ **Per-User Active Caps**
  - `get_max_active_jobs_per_user()` in SettingsRepository
  - `get_user_active_job_count()` in JobRepository
  - API enforces limit with 429 response and descriptive message
  - Configurable via `settings` table key `max_active_jobs_per_user`
  
- ✅ **Global Active Caps**
  - `get_max_active_jobs_global()` in SettingsRepository
  - `get_global_active_job_count()` in JobRepository
  - API enforces limit with 429 response
  - Configurable via `settings` table key `max_active_jobs_global`
  
- ✅ **Per-Host Active Caps**
  - Target exclusivity via `SELECT FOR UPDATE SKIP LOCKED`
  - Only one active job per target at a time
  - `running_jobs_by_host()` in JobRepository

- ✅ **Short Hostname Aliases**
  - `host_alias` column added to `db_hosts` table
  - Schema migration: `schema/pulldb_service/031_db_hosts_alias.sql`
  - `get_host_by_alias()` in HostRepository
  - `resolve_hostname()` - resolves alias to canonical hostname
  - DBHost model updated with `host_alias: str | None` field
  - 5 tests in `pulldb/tests/test_host_repository.py`
  - Users can now use `dbhost=dev-db-01` instead of full FQDNs

## Phase 3 – Multi-Daemon & Distributed Locks ✅ COMPLETE (v0.0.5)

Implemented in v0.0.5 (November 2025):

- [x] Atomic job claiming with `SELECT FOR UPDATE SKIP LOCKED` (MySQL native locking)
- [x] Worker ID tracking (`jobs.worker_id` column) for multi-daemon debugging
- [x] Deprecation of unsafe `get_next_queued_job()` + `mark_job_running()` pattern
- [x] New `claim_next_job()` method for safe concurrent operation
- [x] Concurrent worker tests with threading validation
- [x] Schema: `worker_id` column consolidated into `010_jobs.sql`

Decision: Used MySQL `FOR UPDATE SKIP LOCKED` instead of external locking (Consul/DynamoDB)
because MySQL is already the coordination database and this pattern is sufficient for
our scale requirements.

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
  - **Role-Based Access Control (RBAC)**
  - **Admin Role**: Full system access
    - Manage users (add, remove, change roles, enable/disable)
    - View all jobs across all users
    - Cancel any job (including others' jobs)
    - Adjust job priority/queue order
    - Submit jobs on behalf of other users
    - Access system configuration and settings
    - View and manage staging database cleanup
  - **Manager Role**: Operational oversight
    - View all jobs across all users (read-only job list)
    - Cancel jobs (any user's jobs)
    - Adjust job priority/queue order
    - Submit jobs for other users (with proper audit logging)
    - View system metrics and queue health
    - Cannot manage users or change system configuration
  - **User Role** (default): Self-service access
    - Submit own restore jobs
    - View own jobs only (filtered by owner_user_id)
    - Cancel own jobs only
    - View own job history
    - No access to other users' jobs or system operations
  - **Hierarchical Manager-User Relationships (Phase 5)**
    - Add `manager_id` column to `auth_users` table (nullable foreign key to auth_users)
    - Users can be assigned to a specific manager
    - Managers can only manage jobs for their assigned users (not all jobs)
    - Manager permissions scoped to their team:
      - View jobs for assigned users only
      - Cancel jobs for assigned users
      - Adjust priority for assigned users' jobs
      - Submit jobs on behalf of assigned users
    - **Manager-of-Managers** hierarchy:
      - Add `manager_of_managers` table: `(manager_id, subordinate_manager_id, assigned_at)`
      - Senior managers can oversee other managers
      - Inherit visibility of subordinate managers' users
      - Example: Manager A oversees Users 1-5, Manager B oversees Users 6-10, Senior Manager C oversees both Manager A and Manager B → sees Users 1-10
    - **Universal Job Visibility**:
      - All users can view all jobs (read-only)
      - Job list shows: job_id, target, status, owner_username, submitted_at
      - Sensitive details (error_detail, options_json) filtered by permission
      - Manager permissions only control what they can ACTION (cancel, modify), not what they can VIEW
    - **Authorization Rules**:
      - Admin: full access to all users and jobs
      - Manager with team: can action (cancel/modify) only assigned users' jobs, view all jobs
      - Manager without team: same as admin for backwards compatibility (transition period)
      - User: can action only own jobs, view all jobs
    - **Audit Trail**:
      - Track manager assignment changes in job_events
      - Log all manager actions on users' jobs with manager_id context
      - Record manager-of-managers hierarchy changes
  - **Schema Changes**:
    - Add `role` ENUM('user','manager','admin') to `auth_users` table
    - Add `manager_id` CHAR(36) NULL to `auth_users` (foreign key to auth_users.user_id)
    - Add `manager_of_managers` table for hierarchy
    - Default role: 'user'
    - Track role changes in job_events (audit trail)
  - **Authorization Logic**:
    - CLI validates role permissions before job submission
    - Daemon enforces role checks for job cancellation
    - Web interface renders UI based on role capabilities
    - Query filtering for actions: users see own jobs, managers see assigned users' jobs, admins see all
    - Query filtering for viewing: all roles see all jobs (read-only)
  - **Documentation Requirements**:
    - Update security model with RBAC permissions matrix
    - Document role promotion/demotion procedures
    - Add role-based command examples to README
    - Update runbooks with manager troubleshooting workflows
    - Document manager assignment and hierarchy management
    - Explain universal job visibility vs action permissions
- **Migration Strategy**
  - Maintain CLI trusted wrapper authentication for backwards compatibility.
  - Add `auth_credentials` table for web users (hashed passwords, 2FA secrets).
  - Document authentication flow differences between CLI and web interfaces.
  - Migrate existing users to 'user' role by default; manually promote admins/managers.

## Phase 5 – Automation & APIs

- REST/GraphQL API for programmatic job submission and monitoring.
- API token authentication for service accounts.
- Document onboarding flows, rate limits, and security posture.

## Continuous Tasks

- Review backlog items quarterly.
- Keep this roadmap synchronized with `../constitution.md` and product decisions.
- Ensure every phase has clear exit criteria and testing expectations before coding.

---

[← Back to Documentation Index](../docs/START-HERE.md) · [Restore Runbook](runbook-restore.md)
