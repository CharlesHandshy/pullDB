# Copilot Instructions for pullDB

## Overview

This document is the **primary reference for AI coding agents** working on pullDB. It distills the essential architecture, patterns, and constraints from the comprehensive documentation. Always read this file first, then consult other documents as needed.

**Related Documents**:
- **`engineering-dna/standards/ai-agent-code-generation.md`** - **MANDATORY for AI agents**: Modern Python patterns, file generation protocols, FAIL HARD standards, anti-patterns to avoid (created Nov 2025)
- **`constitution.md`** - Coding standards, tooling philosophy, and development workflow
- **`docs/coding-standards.md`** - Comprehensive style guidelines for all file types (Python, Markdown, SQL, Shell, YAML, Mermaid)

These documents form the foundation—all other documentation flows from these principles. **AI agents MUST follow the standards in `engineering-dna/standards/ai-agent-code-generation.md` when generating any code.**

## Project Overview

pullDB is a database restoration tool that pulls production MySQL backups from S3 and restores them to development environments. The system follows a **documentation-first, prototype-first** approach with extensive planning before implementation.

**Current Status (Nov 5 2025)**: All Phase 0 milestones complete: credentials/config/repositories, logging abstraction, domain error classes, worker poll loop, S3 backup discovery, downloader, disk capacity guard, myloader subprocess wrapper, post‑SQL executor, staging orphan cleanup, metadata table injection, atomic rename invocation module, restore orchestration (end‑to‑end logical chaining), CLI validation & enqueue & status command, daemon service runner (graceful shutdown + lifecycle metrics), metrics emission scaffolding, installer + packaging (interactive/non‑interactive + Debian maintainer scripts + systemd unit), and comprehensive integration tests (happy path + failure modes). Phase 0: 100% complete. Project in RELEASE FREEZE (bug/security fixes only) as of Nov 3 2025 (see `RELEASE-FREEZE.md`). **Security scan: 0 CVEs** (verified Nov 5 2025).

**Completed Work** (verified Nov 5 2025):
- ✅ MySQL 8.0.43 schema deployed (6 tables, 1 view, 1 trigger)
- ✅ Credential resolution (`pulldb/infra/secrets.py` ~399 lines) with Secrets Manager + SSM support
- ✅ Atomic rename stored procedure SQL file (`docs/atomic_rename_procedure.sql`) added
- ✅ Deployment script validation (dry-run, host conflict, missing SQL file, connection failure, drop failure, create failure, success) via unit tests
- ✅ Test suite (184 tests passed, 1 skipped, 1 xpassed: secrets, config, repos, logging, errors, exec, restore, post-SQL, staging, discovery, downloader, disk capacity integration, atomic rename invocation, CLI parsing + status command, procedure deployment, procedure versioning, preview procedure stripping logic, benchmark script validation, installer flags/validation/root enforcement, worker service lifecycle) – latest run 75.49s
- ✅ Versioned atomic rename stored procedure (header comment `Version: 1.0.0`)
- ✅ Preview stored procedure (`pulldb_atomic_rename_preview`) for safe inspection of atomic RENAME TABLE statement
- ✅ Deployment script enhancements: version validation, preview deployment flag, skip-version-check override, conditional preview stripping
- ✅ Benchmark script for atomic rename SQL build performance (`scripts/benchmark_atomic_rename.py`) with FAIL HARD input validation
- ✅ Expanded deployment + benchmark test coverage (version presence/missing/skip, preview include/exclude, benchmark JSON + error paths)
- ✅ CLI status command with --json, --wide, --limit options (5 tests)
- ✅ AI Agent Code Generation Standards (engineering-dna submodule) with modern Python patterns and FAIL HARD protocols

**Not Yet Implemented (Drift vs Initial Plan)**:
- ✅ Staging DB orphan cleanup (pattern matching + DROP operations) – atomic rename procedure still pending

Implemented Since Original Plan (previously marked missing):
- ✅ Structured JSON logging abstraction (baseline)
- ✅ Worker polling loop + event emission
- ✅ S3 backup discovery & selection logic
- ✅ Downloader (stream + disk space preflight + streaming extraction input)
- ✅ Atomic rename stored procedure deployment validation (script + tests)

**Immediate Milestone Goals (Restore Workflow Bootstrap)**:
1. Introduce logging & domain error classes (FAIL HARD runtime scaffolding)
2. Implement worker poll loop + event emission for `queued`→`running` transitions
3. Add S3 discovery + downloader with disk capacity guard
4. Integrate myloader execution (subprocess wrapper capturing stdout/stderr)
5. Execute post‑SQL scripts + record structured results JSON
6. Implement staging lifecycle (name generation, orphan cleanup, placeholder atomic rename)
7. Wire events + status updates in repositories (failed/complete)
8. Replace CLI placeholders with validation + enqueue + status listing
9. Add integration tests for happy path & failure modes (missing backup, disk insufficient, myloader error, post‑SQL failure)
10. Introduce metrics emission after baseline stability

**Quality Guardrail**: Each milestone increment MUST preserve 100% passing tests and extend coverage for new failure paths (FAIL HARD diagnostics required).

**Environment Context**:
- **Development environment** (`345321506926`) runs pullDB and needs cross-account S3 access to:
  - **Staging backups** (`333204494849`): `s3://pestroutesrdsdbs/daily/stg/` - **Primary for development** - Contains both newer and older mydumper format backups for testing
  - **Production backups** (`448509429610`): `s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/` - Older mydumper format (will migrate to newer format post-implementation)
- **Prototype development**: Use staging backups as primary source (has both formats available)
- Multi-format mydumper support required (deferred feature - see roadmap.md)

## Architecture Principles

- **FAIL HARD Philosophy**: When operations cannot complete as designed, **fail immediately** with comprehensive diagnostics. Never silently degrade or work around issues. Always provide: (1) what was attempted, (2) what failed and why, (3) ranked solutions. See `constitution.md` for complete FAIL HARD requirements.
- **Three-Service Architecture**: CLI (thin client) → API Service (job management) → Worker Service (job execution)
- **API Service**: Accepts HTTP requests, validates input, inserts jobs to MySQL, provides status/discovery endpoints (read-only S3 access for backup listing)
- **Worker Service**: Polls MySQL queue, executes restores via S3 + myloader (full S3 read access for downloads, no HTTP exposure)
- **MySQL as Coordination Layer**: All state, locks, and job tracking via MySQL (accessed by API and Worker services)
- **Download-Per-Job**: No archive reuse in prototype - download fresh each time
- **Per-Target Exclusivity**: MySQL constraints prevent concurrent restores to same target database
- **Independent Services**: API and Worker never communicate directly - only via MySQL queue
- **CLI Capabilities Preserved**: All original functionality available through API service HTTP endpoints

## Key Files & Directory Structure

```
.github/copilot-instructions.md  # THIS FILE - Primary AI agent reference
constitution.md                   # Coding standards and development workflow (co-primary)
design/
  └── two-service-architecture.md # API Service + Worker Service split (CRITICAL)
docs/
  ├── coding-standards.md         # Comprehensive style guide for all file types
  ├── mysql-schema.md             # Complete database schema with invariants
  ├── testing.md                  # Testing guide with AWS integration (NEW Nov 2025)
 ├── AWS-SETUP.md                # Complete AWS setup and configuration guide
  ├── aws-authentication-setup.md # AWS cross-account setup for EC2 (RECOMMENDED)
  ├── aws-secrets-manager-setup.md # AWS Secrets Manager credential resolution (IMPLEMENTED)
  ├── vscode-diagnostics.md       # VS Code diagnostic integration
  └── parameter-store-setup.md    # Secure credential storage in AWS
pulldb/
  ├── infra/
  │   ├── secrets.py              # IMPLEMENTED - Credential resolution (Secrets Manager + SSM)
  │   ├── mysql.py                # IMPLEMENTED - Repositories (Job/User/Host/Settings) + thin pool wrapper
  │   ├── logging.py              # IMPLEMENTED - Structured JSON logging
  │   ├── s3.py                   # IMPLEMENTED - Backup discovery & selection
  │   └── (exec.py)               # PLANNED – subprocess wrapper (myloader)
  ├── worker/
  │   ├── service.py             # IMPLEMENTED - Poll loop + event emission
  │   ├── downloader.py          # IMPLEMENTED - Stream download + disk capacity guard
  │   └── (restore.py / staging.py / post_sql.py) # PLANNED – remaining workflow pieces
  ├── domain/
  │   ├── config.py               # IMPLEMENTED - Two-phase environment + MySQL settings enrichment
  │   ├── models.py               # IMPLEMENTED - Dataclasses (Job, JobEvent, etc.)
  │   ├── errors.py               # IMPLEMENTED - Structured FAIL HARD runtime errors
  │   └── (restore_models.py)     # PLANNED – myloader + post-SQL DTOs
  └── tests/
      ├── ...                     # Comprehensive suite (unit + integration: discovery, downloader, repos, errors, loop, logging, exec, restore, post_sql, disk capacity)

> Current suite: 181 passing tests (+1 skipped, +1 xpassed) covering discovery, downloader (including disk capacity integration tests), logging, errors, myloader wrapper, post-SQL executor, restore orchestration, metadata injection, atomic rename invocation, CLI parsing, procedure deployment, versioned + preview procedures, benchmark script scenarios, and installer behaviors (flags, systemd skip, validation warnings, root enforcement).
customers_after_sql/              # Post-restore SQL for customer databases (PII removal)
  ├── 010.remove_customer_pii.sql
  ├── 020.remove_billto_info.sql
  └── ... (120.reset_business_registration.sql)
qa_template_after_sql/            # Post-restore SQL for QA templates (currently empty)
  └── README.md                   # Explains no scripts needed for QA templates
reference/                        # Legacy PHP implementations (read-only)
  ├── pullDB-auth                 # Customer restore with obfuscation
  └── pullQA-auth                 # QA template restore
scripts/
  ├── verify-secrets-perms.sh     # Secrets Manager permission verification (Nov 2025)
  └── README.md                   # Script usage documentation
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

## Python Implementation Guidelines
### Test Database Credential Mandate (Effective Nov 2025)

**MANDATORY**: All integration and repository tests must use AWS Secrets Manager for database login. Direct test user logins (e.g., 'pulldb_test'@'localhost') are deprecated and must not be used for DB authentication in tests. Application test users (for business logic) remain valid for app-level testing.

**Implementation Status** (as of November 1, 2025):
- ✅ Test fixtures updated to use AWS Secrets Manager (`pulldb/tests/conftest.py`)
- ✅ Secret residency verification added (`verify_secret_residency` fixture)
- ✅ Graceful degradation for offline development (local override support)
- ✅ Comprehensive test documentation (`docs/testing.md`)
- ✅ All 87 tests passing with AWS integration

**Secret Residency Enforcement**:
- New `verify_secret_residency` fixture validates secrets exist only in development account (345321506926)
- Automatically asserts secret ARN contains correct account ID
- Gracefully skips when AWS unavailable (offline development)
- Fails with clear error message if secret found in wrong account (staging/prod)

**Migration Steps** (COMPLETED):
- ✅ Update all test fixtures to resolve DB credentials via AWS Secrets Manager (use CredentialResolver).
- ✅ Store test DB credentials in `/pulldb/mysql/coordination-db` secret.
- ✅ Remove any direct use of test user credentials in test connection pools.
- ✅ Document this pattern in all setup and test documentation.

**Rationale:**
- Ensures test and production credential resolution paths are identical.
- Prevents drift between test and production authentication logic.
- Simplifies credential rotation and audit.
- Validates secrets exist in correct AWS account (dev-only constraint).

**Reference:** See `docs/testing.md` for complete testing guide and `docs/aws-secrets-manager-setup.md` for credential setup.
#### Development Override (Temporary)

For local development only (never CI or production), a temporary override path
is available when the coordination DB secret hostname is unreachable or AWS
read permissions are pending. The test fixture logic will prefer the following
environment variables when all are set:

- `PULLDB_TEST_MYSQL_HOST`
- `PULLDB_TEST_MYSQL_USER`
- `PULLDB_TEST_MYSQL_PASSWORD`
- `PULLDB_TEST_MYSQL_DATABASE`

This bypass exists solely to keep momentum during secret propagation delays.
It must not be used in committed code examples, CI pipelines, or documentation
outside this section. Remove the override once the canonical secret
(`/pulldb/mysql/coordination-db`) resolves successfully in the development
account. All tests must still exercise the CredentialResolver path by default.

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
  cli/           # Command validation, option parsing, API calls
  api/           # API Service - HTTP endpoints, job creation, status queries
  worker/        # Worker Service - Job polling, S3 download, MySQL restore orchestration
  infra/         # MySQL, S3, logging abstractions (shared by API + Worker)
  domain/        # Job, JobEvent, configuration dataclasses (shared)
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

### Development File Ownership Principle (Effective Nov 2025)

All files created or modified during development inside a user-controlled directory (e.g., `/home/<user>/Projects/.../pullDB`) **must remain owned by that user** (not `root`) unless a specific production packaging or system integration step explicitly requires root ownership (e.g., system-wide install, systemd unit deployment). Root ownership in a development working copy creates friction (sudo required for edits) and increases the risk of accidental permission escalation or silent failures.

Ownership & Permissions Baseline (Current Standard):
- Ownership: `charleshandshy:charleshandshy` (replace with active dev user)
- Directories: `750` (restrict world access; group expansion possible later)
- Executable scripts & entrypoints: `750` (user rwx, group rx)
- Regular source/config files: `640` (user rw, group r)
- Credentials/secrets artifacts: `600` or `640` depending on group read need
- Virtual environment bin contents: `750` (preserve executability)

Rationale:
1. Eliminates sudo dependency for iterative edits (accelerates feedback loop).
2. Preserves FAIL HARD transparency—permission errors now indicate intentional boundaries.
3. Reduces chance of accidentally committing root-owned artifacts that fail CI or block cleanup.
4. Simplifies automation scripts (no conditional sudo logic for normal file writes).

Agent Enforcement Rules:
1. When introducing new files via patches, ensure they inherit non-root ownership (implicitly by creating under the user’s directory).
2. Do NOT chown files to root during development tasks unless explicitly part of packaging or system install instructions.
3. If a script requires elevated operations, prefer targeted `sudo` calls (e.g., `sudo mysql ...`) rather than changing script ownership.
4. Normalize permissions after bulk operations touching venv or extracted artifacts (apply the baseline pattern above).
5. Treat unexpected root ownership as a **diagnostic event**: investigate origin (installation step, manual sudo edit), correct, and record resolution.

FAIL HARD Diagnostic Template (Ownership Drift):
```
Goal: Maintain user-level ownership for development workspace
Problem: Found 12 files owned by root under test-env/ after venv rebuild
Root Cause: Setup script executed under sudo without post-install chown normalization
Solutions:
 1. (Preferred) Add post-setup chown -R <user>:<user> test-env/ (documented in script)
 2. Restrict sudo usage to individual commands instead of whole script execution
 3. Add automated permission audit to pre-commit (future enhancement)
```

Future Enhancements:
- Add a `--normalize-perms` flag to `setup-test-environment.sh` to enforce baseline automatically.
- Integrate a lightweight permission audit command (`scripts/audit-permissions.sh`) with CI warning if drift detected.
- Add `permissions-audit` GitHub Action workflow to enforce zero root-owned artifacts and drift-free `test-env` when present.
- Add local pre-commit hook (`permission-audit`) invoking `scripts/audit-permissions.sh test-env`.

Commit Tag Convention:
- When correcting ownership/permission drift include `PermFix:` line summarizing scope (e.g., `PermFix: normalized test-env (23 files)`).
- When adding automation around ownership/permissions include `PermGuard:` tag for traceability.

Agents MUST apply this principle whenever creating or modifying development artifacts. Root-owned development files are considered **hygiene debt** and should be corrected immediately.

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

### Implementation Drift Tracking (Nov 2 2025)

Maintain a living drift ledger until restore workflow is complete:
- Repositories & credential/config layers: ✅ Implemented
- Logging abstraction & domain error classes: ✅ Implemented (item 1 complete)
- Worker poll loop & event emission: ✅ Implemented (item 2 complete)
- S3 discovery & downloader (disk capacity guard + streaming): ✅ Implemented (item 3 complete)
- CLI validation & enqueue & status: ✅ Implemented (argument parsing, validation, enqueue, status command with --json/--wide/--limit)
- myloader execution subprocess wrapper: ✅ Implemented (command building, timeout + non‑zero translation)
- Post‑SQL executor: ✅ Implemented (sequential script execution, FAIL HARD on first error, timing + rowcount capture)
- Engineering-dna freshness CI gate: ✅ Implemented (workflow enforces submodule up-to-date)
- Engineering-dna baseline commit gate: ✅ Implemented (pre-commit + CI enforce tag-based baseline)
- Restore orchestration (staging lifecycle integration + post‑SQL chaining): ✅ Implemented (atomic rename module + stored procedure deployment validated with tests)
- Metadata table injection: ✅ Implemented (staging metadata table creation + JSON script report)
- Staging lifecycle: ✅ Orphan cleanup implemented (drop‑all); ✅ Atomic rename invocation module added (procedure existence validated at runtime); ✅ Stored procedure deployment script and tests implemented
- Integration tests (end‑to‑end restore workflow incl. failure modes: missing backup, disk insufficient, myloader error, post‑SQL failure): ✅ Implemented (happy path, optional real S3 listing, myloader failure, post‑SQL failure, disk insufficient, missing backup). Stored procedure deployment covered via unit tests (non-network fakes) ensuring FAIL HARD diagnostics.
- Metrics emission (queue depth, restore durations, disk failures): ✅ Implemented (logging-based counters/gauges/timers/events)

Test Suite Expansion: Current suite has grown from initial 9 tests to 181 passing tests (adds exec + myloader wrapper + post-SQL executor tests for success, non-zero exit, timeout, large output truncation, script failure; downloader disk capacity unit + integration tests; restore orchestration happy path & failure modes; atomic rename invocation module; CLI parsing + status command tests; stored procedure deployment script tests; daemon stop callback test; installer flag parsing, validation, systemd skip, root requirement enforcement). Future hardening deferred until post-freeze (Phase 1) focusing on staging cutover edge cases and performance profiling.

Testing Note (myloader wrapper): We deliberately monkeypatch `run_command` in restore tests to keep them deterministic and OS/binary agnostic—no dependency on a real `myloader` binary while still exercising error translation paths.

Testing Note (atomic rename deployment): Deployment script tests isolate behaviors without real MySQL by faking `mysql.connector.connect` and cursor execution paths, asserting FAIL HARD diagnostics for each failure mode before success.

Agents MUST update this section when a missing component lands (replace ❌/🚧 with ✅ and retain remaining incomplete rows). Do not remove incomplete rows prematurely; always preserve chronological progress for audit.

## AI Agent FAIL HARD Mandate

**CRITICAL**: When debugging issues or implementing features, AI agents must follow the FAIL HARD philosophy (see `constitution.md` for complete requirements).

### Diagnostic Protocol

When encountering failures, AI agents must:

1. **Detect the Failure**
   - Use `get_errors` tool to check VS Code diagnostics
   - Run commands and verify exit codes
   - Read logs and error messages completely
   - Don't assume - verify actual state

2. **Research Root Cause**
   - Gather context: read relevant files, check configuration, verify permissions
   - Use appropriate tools: `grep_search`, `read_file`, `run_in_terminal`
   - Trace the failure path back to the originating condition
   - Validate hypothesis with concrete evidence (don't speculate)

3. **Present Structured Findings**

   **Goal**: What was the intended outcome?
   - Example: "Configure test suite to use AWS Secrets Manager for MySQL credentials"

   **Problem**: What actually happened? (Be specific)
   - Example: "All 50 tests skipped with message 'Cannot verify secret residency: Secrets Manager can't find the specified secret'"

   **Root Cause**: Why did it fail? (Validated diagnosis)
   - Example: "Tests running without AWS credentials (AWS_PROFILE not set). The `verify_secret_residency` fixture calls boto3.client() which defaults to looking for credentials in standard locations. When no credentials found, boto3 raises NoCredentialsError, caught by fixture's broad exception handler, triggering skip."

   **Solutions** (ranked by effectiveness):
   1. **Best Solution**: "Set AWS_PROFILE environment variable to 'default' before running tests. This uses EC2 instance profile credentials."
      - Pros: Matches production authentication, validates full AWS integration
      - Cons: Requires AWS access
   2. **Alternative**: "Use local override variables (PULLDB_TEST_MYSQL_*) to bypass AWS entirely"
      - Pros: Works offline, faster test execution
      - Cons: Doesn't validate AWS integration path, skips residency check
   3. **Workaround**: "Mock boto3 client in tests to simulate secret retrieval"
      - Pros: No AWS dependency
      - Cons: Doesn't validate real AWS behavior, test complexity increases

4. **Implement and Verify**
   - Apply the chosen solution
   - Run verification commands to confirm fix
   - Check for regressions using `get_errors`
   - Document the resolution if it reveals architectural decisions

### Prohibited Behaviors

**NEVER**:
- ❌ Silently catch exceptions without logging or user notification
- ❌ Add `try/except: pass` blocks that hide failures
- ❌ Return empty results or None when operation fails
- ❌ Implement workarounds without explaining why direct fix isn't used
- ❌ Skip diagnostic steps and jump to solutions
- ❌ Present speculation as fact ("this might be because...")

**ALWAYS**:
- ✅ Use specific exception types in error handling
- ✅ Preserve stack traces with `raise ... from e`
- ✅ Log failures with context (job_id, operation, inputs)
- ✅ Return errors to caller, don't swallow them
- ✅ Verify root cause before proposing solutions
- ✅ Present evidence-based diagnosis

### Warning Eradication Principle (NEW Nov 3 2025)

Treat every warning (lint, type-check, schema, formatting) as an **incubating error** that will become
harder and more expensive to fix later. Agents must prefer **eliminating** the underlying cause over
silencing it. This principle extends FAIL HARD: silent deferral of minor issues violates forward
stability. Acceptable responses to warnings:

1. Remove the root cause (refactor, annotate, tighten types, adjust schema).
2. Strengthen validation (add explicit guards, TypeGuards, assertions) so tools gain certainty.
3. Document the limitation AND open a tracked work item when immediate removal is impossible.

Unacceptable responses:
- Adding broad `type: ignore` or blanket suppression without justification.
- Leaving a warning unaddressed in production code because it is "low priority".
- Converting warnings into ignores in bulk commits.

Narrow (scoped) ignores are permitted only when:
- Tooling exhibits a verified false positive AND
- A precise, single‑line ignore is annotated with a rationale AND
- A follow‑up improvement path is documented (e.g., pending library stub update).

Metric: Warning count in critical paths (infra/, domain/, worker/, cli/) SHOULD trend to **zero**.
Test files may carry temporary structured ignores only when they exercise intentionally invalid
inputs. Each ignore must include a justification string.

Commit Message Tag: When removing warnings, include `WarnFix:` line summarizing count reduced.

### Error Message Standards

Code must produce actionable error messages:

```python
# ❌ BAD: Vague, no context, no solution
raise Exception("Operation failed")

# ❌ BAD: Swallows original error
try:
    operation()
except Exception:
    raise ValueError("Something went wrong")

# ✅ GOOD: Specific, contextualized, actionable
try:
    client.describe_secret(SecretId=secret_id)
except ClientError as e:
    if e.response["Error"]["Code"] == "ResourceNotFoundException":
        raise SecretNotFoundError(
            f"Secret '{secret_id}' does not exist in AWS Secrets Manager. "
            f"Create it with: aws secretsmanager create-secret "
            f"--name {secret_id} --secret-string '{{...}}' "
            f"See docs/aws-secrets-manager-setup.md for complete setup."
        ) from e
    elif e.response["Error"]["Code"] == "AccessDenied":
        raise PermissionError(
            f"Access denied reading secret '{secret_id}'. "
            f"Ensure IAM role has 'secretsmanager:GetSecretValue' permission. "
            f"Verify policy attachment: aws iam list-attached-role-policies "
            f"--role-name pulldb-ec2-service-role"
        ) from e
    else:
        raise  # Unexpected error - preserve original
```

### Test Fixture Behavior

Test fixtures must fail with clear messages, not silently skip:

```python
# ❌ BAD: Silent degradation
def mysql_credentials():
    try:
        return resolver.resolve(secret_id)
    except:
        return MySQLCredentials("localhost", "root", "")  # Hides failure

# ✅ GOOD: Explicit skip with diagnostic message
def mysql_credentials():
    try:
        return resolver.resolve(secret_id)
    except NoCredentialsError as e:
        pytest.skip(
            f"AWS credentials not configured. "
            f"Set AWS_PROFILE environment variable or configure "
            f"~/.aws/credentials. See docs/testing.md for setup. "
            f"Original error: {e}"
        )
```

## Pre-Commit Hygiene Protocol

**Purpose**: Guarantee every commit preserves code quality, test integrity, documentation accuracy (drift ledger + README status), and excludes transient artifacts. Integrates with FAIL HARD—any failed step aborts with actionable diagnostics.

### Ordered Checklist (Abort on First Failure)
1. Working tree sanity: `git status` shows only intended changes; no stray large archives or dumps.
2. Formatting: `ruff format .` (must produce no diffs on second run).
3. Lint: `ruff check .` (zero errors/warnings required for commit).
4. Types: `mypy .` (no errors; introduce stubs or refactors instead of ignoring).
5. Tests: `pytest -q --timeout=60 --timeout-method=thread` (all pass; invoke Timeout Monitoring Protocol if timeouts).
6. Drift ledger sync: Update in `copilot-instructions.md`—Completed Work + Not Yet Implemented + Implementation Drift Tracking—reflect new components or status changes (add ✅/❌ transitions only with evidence).
7. Test count & duration: Capture latest line (e.g., `112 passed in 55.3s`) and ensure commit message includes it.
8. .gitignore audit: Confirm newly introduced transient patterns are ignored (extraction dirs, profiling output) and no essential assets are accidentally excluded.
9. README status block: Update only if milestone progress (feature implemented or promoted from pending).
10. Commit message uses standard template (see below).

### Commit Message Template
```
pullDB: <component>: <short summary>

Component: <files/modules>
Change-Type: feature|fix|refactor|docs|hygiene
Tests: <N> tests passing in <S.SS>s (timeout=60s)
Drift: Updated <sections touched>
Hygiene: ruff+mypy+pytest clean; gitignore audited; docs synced
```

### Artifact Classification
| Category | Tracked | Ignored |
|----------|---------|---------|
| Source & Domain | `pulldb/`, design docs, SQL scripts in `customers_after_sql/`, `qa_template_after_sql/` | Generated caches (`__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`) |
| Backups / Dumps | (Never) | `*.sql*`, `*.tar*`, `*.dump`, extracted working dirs (`pulldb_work_*`) |
| Environment | Required examples in docs | `.env`, local overrides, virtual env dirs (`venv/`, `.venv/`) |
| Diagnostics | FAIL HARD logs embedded in exceptions | `*.log`, profiling (`profile/`, `profiling/`), benchmarking (`.benchmarks/`) |
| Processes | N/A | PID/trace artifacts (`*.pid`, `*.out`, `*.trace`, `*.stackdump`) |

### Failure Protocol (Example)
```
Goal: Run mypy type checks pre-commit
Problem: mypy reported 2 incompatible type errors in staging.py
Root Cause: Row access uses generic Any without explicit tuple type; missing cast/ignore
Solutions:
 1. Add typed protocol or cast for cursor.fetchall rows (preferred)
 2. Introduce TypedDict/NamedTuple for database rows
 3. As last resort, narrow ignore with type: ignore[index] and explain in code comment
```

### Safeguards
- Never ignore business SQL sanitization scripts.
- Do not auto-commit if test count decreased without explicit rationale.
- Avoid broad patterns (e.g., `*work*`)—use specific prefixes (`pulldb_work_`).
- Re-run ruff and mypy after doc edits (docs can introduce trailing whitespace issues).

### Future Extensions
- Add `scripts/precommit-verify.py` to automate checklist (planned).
- Integrate performance baseline alerts (average test duration trending upward >10%).
- Security scan injection (dependency vulnerability checks) after core workflow completes.

### Success Criteria
- All steps green.
- Commit message contains hygiene block.
- Drift ledger and test count correct.
- No transient artifacts added.


## Test Timeout Monitoring Protocol

**CRITICAL**: All test executions must include timeout monitoring to detect hanging tests, resource leaks, and deadlocks early. This protocol ensures test suite reliability and provides diagnostic data for FAIL HARD resolution.

### Standard Test Execution

**Command** (all test runs):
```bash
pytest -q --timeout=60 --timeout-method=thread
```

**Configuration**:
- **Timeout**: 60 seconds per test (default for unit tests)
- **Method**: Thread-based timeout (reliable across platforms, works with subprocess calls)
- **Exit behavior**: Non-zero exit code with "TIMEOUT" in output when test exceeds limit

**Timeout Thresholds by Test Type**:
- Unit tests: 60 seconds (current suite averages 2-3s per test)
- Integration tests: 120 seconds (real AWS/MySQL operations)
- End-to-end restore tests: 300 seconds (S3 download, myloader, post-SQL)

### Timeout Detection and Escalation

**When timeout occurs**, automatically invoke diagnostic protocol:

1. **Identify timed-out test** from pytest output:
   ```
   FAILED test_module.py::test_function - Failed: Timeout >60.0s
   ```

2. **Execute diagnostic re-run** with verbose flags:
   ```bash
   pytest -vv -s --timeout=120 --timeout-method=thread -p no:xdist test_module.py::test_function
   ```

3. **Diagnostic flags explained**:
   - `-vv`: Very verbose (show fixture setup/teardown, test progress)
   - `-s`: Disable output capture (see real-time logging, print statements)
   - `--timeout=120`: Double timeout for observation
   - `-p no:xdist`: Disable parallel execution (run serially for isolation)
   - `--tb=long`: Long traceback format (optional, add if needed)

4. **Collect resource state**:
   ```bash
   # Check for orphaned processes
   ps aux | grep -E "(myloader|pytest|python)" | grep -v grep

   # Check for unclosed MySQL connections
   mysql -e "SHOW PROCESSLIST" | grep pulldb

   # Check for open file handles (if test PID known)
   lsof -p <pytest_pid>

   # Check for temp files not cleaned up
   ls -la /tmp/*pulldb* 2>/dev/null
   ```

5. **Present structured FAIL HARD report**:
   ```
   TIMEOUT DETECTED
   ================
   Test: test_module.py::test_function_name
   Timeout: 60 seconds
   Last Output: [captured output before timeout]

   DIAGNOSTIC RE-RUN
   =================
   Command: pytest -vv -s --timeout=120 -p no:xdist test_module.py::test_function_name
   Result: [timeout again | passed | failed with error]
   Duration: [actual time if completed]

   ROOT CAUSE ANALYSIS
   ===================
   [Evidence-based diagnosis: which operation hung, resource state]

   RECOMMENDED SOLUTIONS
   =====================
   1. [Most effective fix with code example]
   2. [Alternative approach]
   3. [Workaround if needed]
   ```

### Common Timeout Causes and Prevention

**Frequent culprits**:
- **Unclosed database connections**: Connection pool exhaustion
  - Prevention: Always use `with` statements or fixtures with proper teardown
- **Subprocess not terminated**: Orphaned myloader/mysqld processes
  - Prevention: Use `timeout` parameter in `subprocess.run`, ensure SIGTERM handling
- **Infinite retry loops**: Network operations without timeout
  - Prevention: Set explicit `timeout` on boto3 calls, mysql.connector operations
- **File handle leaks**: Open files never closed
  - Prevention: Use `with open(...)` or ensure `finally` blocks close resources
- **Deadlocks**: Threading/async coordination issues
  - Prevention: Avoid shared state, use thread-safe primitives, test with `-p no:xdist`

**Prevention checklist** (pre-commit):
- [ ] All file operations use `with` statements
- [ ] All database connections properly closed (fixtures or context managers)
- [ ] All subprocess calls have `timeout` parameter
- [ ] All network operations have explicit timeout (S3, MySQL)
- [ ] No global mutable state shared across tests
- [ ] Fixtures have proper teardown/cleanup

### Resource Cleanup Verification

**After any test run** (especially after timeout), verify:
```bash
# No orphaned MySQL connections
mysql -e "SHOW PROCESSLIST" | grep pulldb
# Expected: Empty output or only current connection

# No orphaned processes
ps aux | grep -E "(myloader|pytest)" | grep -v grep
# Expected: Empty output (all tests completed)

# No temp directories lingering
ls -la /tmp/*pulldb* 2>/dev/null | wc -l
# Expected: 0 (or small number if tests just ran)
```

### Integration into AI Agent Workflow

**Standard test execution workflow**:
1. Make code changes
2. Run: `pytest -q --timeout=60 --timeout-method=thread`
3. Check result:
   - **Pass** (exit 0, duration < 60s) → Report success with duration
   - **Timeout detected** → Invoke diagnostic protocol (steps 1-5 above)
   - **Other failure** → Report failures normally with traceback
4. Verify cleanup: No orphaned processes/connections/temp files
5. Document duration in commit messages: "98 tests passing in 12.3s"

**When to apply timeout monitoring**:
- ✅ Always: Full test suite after code changes
- ✅ Always: When user requests "run tests" or "proceed with tests"
- ✅ Always: During milestone completion verification
- ✅ Always: After modifying resource management code (database, subprocess, file I/O)
- ❌ Optional: Single test quick validation (unless that test previously timed out)

**Timeout threshold tuning**:
- Use `@pytest.mark.timeout(120)` for known slow integration tests
- Use `@pytest.mark.timeout(300)` for end-to-end restore workflow tests
- Document rationale in test docstring when using non-standard timeout

### Dependencies

**Required**: `pytest-timeout` plugin
```bash
pip install pytest-timeout
```

**Verification**:
```bash
pytest --version  # Should show pytest-timeout in plugins list
```

**Configuration** (optional `pytest.ini` or `pyproject.toml`):
```ini
[tool:pytest]
timeout = 60
timeout_method = thread
```

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

Read `README.md` first for complete context, then refer to specific design documents for implementation details.
