# pullDB Implementation Plan

> **Status**: Ready to begin Phase 0 (Prototype) implementation
> **Start Date**: October 30, 2025
> **Target**: Minimum viable prototype with core restore functionality

## Current State Assessment

### Documentation (Complete ✅)
- [x] `.github/copilot-instructions.md` - AI agent guidance and architecture overview
- [x] `constitution.md` - Coding standards, tooling, KISS principles
- [x] `README.md` - Complete API reference and usage patterns
- [x] `design/system-overview.md` - Component responsibilities
- [x] `design/implementation-notes.md` - Python project structure
- [x] `design/configuration-map.md` - Configuration sources
- [x] `design/roadmap.md` - Phased feature rollout (0-5)
- [x] `design/apptype-analysis.md` - Legacy appType migration
- [x] `design/staging-rename-pattern.md` - Staging database pattern (MANDATORY)
- [x] `docs/mysql-schema.md` - Complete database schema with initialization
- [x] `customers_after_sql/` - 12 post-restore SQL scripts (010-120)
- [x] `qa_template_after_sql/` - README explaining no scripts needed
- [x] `reference/` - Legacy PHP implementations (gitignored, local only)

### Code (Phase 0 Prototype - 85% Complete ✅)
- [x] Python virtual environment created (Python 3.12.3)
- [x] MySQL setup script created (`scripts/setup-mysql.sh`)
- [x] Schema SQL published (`schema/pulldb/` numbered files; legacy shell wrapper archived under `scripts/archived/`)
- [x] AWS installation script created (`scripts/setup-aws.sh`)
- [x] Dependency manifests added (`requirements.txt`, `requirements-dev.txt`, `requirements.lock`)
- [x] Python project structure (complete with 59 files, ~5187 source LOC)
- [x] AWS credential resolution module (`pulldb/infra/secrets.py` - 399 lines, production-ready)
- [x] Configuration module with MySQL settings integration (`pulldb/domain/config.py` - 227 lines)
- [x] MySQL connection pool + 4 repositories (`pulldb/infra/mysql.py` - 975 lines)
- [x] Domain models (`pulldb/domain/models.py` - 192 lines, 5 dataclasses)
- [x] Domain errors (`pulldb/domain/errors.py` - 341 lines, 8 error classes with FAIL HARD)
- [x] S3 discovery & download (`pulldb/infra/s3.py`, `pulldb/worker/downloader.py`)
- [x] Worker poll loop (`pulldb/worker/loop.py` - with backoff & metrics)
- [x] Restore orchestration (`pulldb/worker/restore.py` - end-to-end workflow)
- [x] Post-SQL executor (`pulldb/worker/post_sql.py` - sequential script execution)
- [x] Staging lifecycle (`pulldb/worker/staging.py` - orphan cleanup, name generation)
- [x] Metadata injection (`pulldb/worker/metadata.py` - pullDB table creation)
- [x] Atomic rename module (`pulldb/worker/atomic_rename.py` - procedure invocation)
- [x] CLI parser & validation (`pulldb/cli/parse.py`, `pulldb/cli/main.py` - enqueue logic partial)
- [x] Metrics emission (`pulldb/infra/metrics.py` - logging-based counters/gauges/timers)
- [x] Structured logging (`pulldb/infra/logging.py` - JSON format)
- [x] Stored procedure deployment script (`scripts/deploy_atomic_rename.py` - version validation)
- [x] Benchmark script (`scripts/benchmark_atomic_rename.py` - rename SQL performance)
- [x] Python tests - **170/170 passing, 1 skipped, 1 xpassed** (56.65s with timeout=60s)
  - 87 repository tests (Job, User, Host, Settings, Config integration)
  - 23 worker tests (restore, post-SQL, staging, metadata, atomic rename, downloader)
  - 21 deployment/benchmark tests
  - 14 secrets tests
  - 25+ integration tests (workflow, failures, S3 discovery, disk capacity)

### Infrastructure (Partially Provisioned ⚙️)
- [x] MySQL 8.0.43 server installed and running
- [x] MySQL data directory configured at `/mnt/data/mysql/data`
- [x] MySQL tmpdir configured at `/mnt/data/mysql/tmpdir`
- [x] Python MySQL libraries installed (mysql-connector-python 9.5.0, pymysql 1.4.6)
- [x] AWS CLI v2 installed (script-driven)
- [x] AWS Python libraries installed (boto3 1.40.63, botocore 1.40.63, s3transfer 0.14.0)
- [x] AWS profile/role configuration (EC2 instance profile with pulldb-ec2-service-role)
- [x] AWS Secrets Manager access configured (credential_ref pattern working)
- [x] pulldb coordination database (schema deployed with 3 hosts, 5 settings)
- [x] EC2 instance for daemon (operating on the instance)
- [x] AWS credentials and IAM roles (pulldb-ec2-service-role created in development account)
- [x] AWS Secrets Manager secret created: `/pulldb/mysql/coordination-db`
- [x] Database host registrations (db3-dev, db4-dev, db5-dev credentials in Secrets Manager) ✅
  - **Note**: AWS region (`AWS_DEFAULT_REGION=us-east-1`) must be set for credential resolution

## Phase 0 Goals (Prototype)

**Objective**: Deliver minimal viable restore loop that proves the architecture.

**Success Criteria**:
**Success Criteria** (Status: 4/5 Complete):
1. ✅ User can submit restore job via CLI (validation + enqueue implemented, status listing pending)
2. ✅ Daemon picks up job, downloads from S3, restores to staging, executes post-restore SQL, performs atomic rename (complete workflow orchestrated)
3. ⚠️ Job status visible via `pullDB status` command (CLI status subcommand pending implementation)
4. ✅ All operations logged to files and structured for Datadog ingestion (JSON structured logging complete)
5. ✅ Metrics emitted: queue depth, disk capacity failures (logging-based metrics complete)

**Out of Scope for Phase 0**:

**Current Phase Status**: 85% Complete - Core restore workflow functional, CLI status command and daemon service runner remaining.
## Implementation Order

### Milestone 1: Foundation (Week 1) - ✅ COMPLETE

**Summary**: Project structure, MySQL schema deployment, configuration module, and AWS credential resolution are production-ready. Expanded to 170 tests passing.

**Completion Date**: November 3, 2025 (including Milestone 2)

#### 1.1 Project Structure Setup
```bash
pulldb/
├── pyproject.toml          # Poetry/setuptools configuration
├── setup.py                # Installation script
├── requirements.txt        # Direct dependencies
├── requirements-dev.txt    # Development dependencies
├── .python-version         # Python 3.11+
├── pulldb/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py         # Entry point: pulldb-api service
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py         # Entry point: pullDB command
│   │   ├── validator.py    # Option validation
│   │   └── formatter.py    # Output formatting
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── service.py      # Entry point: pulldb-worker daemon
│   │   ├── downloader.py   # S3 operations
│   │   ├── restore.py      # Orchestrates staging lifecycle
│   │   └── post_sql.py     # Post-restore execution helpers
│   ├── infra/
│   │   ├── __init__.py
│   │   ├── mysql.py        # MySQL connection pool + queries
│   │   ├── s3.py           # S3 client wrapper
│   │   └── logging.py      # Structured JSON logging
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── job.py          # Job dataclass
│   │   ├── user.py         # User dataclass
│   │   └── config.py       # Configuration dataclass
│   └── tests/
│       ├── __init__.py
│       └── *.py             # Pytest suite (unit + integration)
└── scripts/
    ├── setup-mysql.sh               # MySQL 8.x installation script
    ├── install_pulldb.sh            # Post-install customization helper
    └── pulldb-worker.service        # Systemd unit template (installed by package)

schema/
└── pulldb.sql                       # Coordination database schema (canonical)
```

**Tasks**:
- [x] Initialize Python virtual environment (Python 3.12.3)
- [x] Create MySQL installation script with custom data directory setup
- [x] Publish canonical schema SQL (`schema/pulldb/` bundle)
-- [x] Initialize Python project with setuptools (PEP 621 metadata)
-- [x] Create directory structure (`pulldb/` package scaffolding)
- [x] Set up pytest configuration (integration marker registered in pyproject.toml)
- [x] Configure linting (ruff/black) and type checking (mypy)
- [ ] Create basic `__init__.py` files

**Dependencies**:
```python
# requirements.txt
mysql-connector-python>=8.0.0
boto3>=1.28.0
click>=8.1.0  # CLI framework
pydantic>=2.0.0  # Data validation
python-dotenv>=1.0.0  # .env file support
```

#### 1.2 MySQL Schema Deployment ✅

**Artifacts Produced**:
- `scripts/setup-mysql.sh` - Installs MySQL 8.x, configures data directories on `/mnt/data/mysql`
- `schema/pulldb/` - Defines the `pulldb` database with all tables, view, trigger, and seed data (numbered SQL files)

**Tasks**:
- [x] Create MySQL installation script with automated setup
- [x] Configure MySQL data directory: `/mnt/data/mysql/data` (working data)
- [x] Configure MySQL tmpdir: `/mnt/data/mysql/tmpdir` (temporary files)
- [x] Update AppArmor permissions for custom data directory
- [x] Produce schema SQL with trigger and initial data
- [x] Run `sudo scripts/setup-mysql.sh` (completed)
- [x] Apply schema via `cat schema/pulldb/*.sql | mysql -u root -p` (completed)
- [x] Test schema deployment on local/dev MySQL instance (verified)
- [x] Document connection parameters and credential setup (see docs/mysql-setup.md)

**Verification** (completed):
```bash
# Verify schema
sudo mysql -e "USE pulldb; SHOW TABLES;"
sudo mysql -e "USE pulldb; SELECT * FROM settings;"
sudo mysql -e "USE pulldb; SELECT * FROM db_hosts;"
```

**Status**: ✅ Complete - Schema deployed with 6 tables, 1 view, 1 trigger, 3 hosts, 5 settings

#### 1.3 Configuration Module ✅

**File**: `pulldb/domain/config.py` (227 lines)

**Tasks**:
- [x] Implement Configuration dataclass
- [x] Load from environment variables (PULLDB_*)
- [x] Load from MySQL settings table
- [x] Support AWS Parameter Store references (SSM)
- [x] Validate required settings on startup
- [x] Implement two-phase loading pattern (bootstrap → enrich)
- [ ] Implement credential resolution for db_hosts (deferred to Milestone 2.1)

**Implementation Highlights**:
- `Config` dataclass with all required fields (mysql_*, s3_*, paths)
- `_resolve_parameter()` - AWS SSM Parameter Store path resolution
- `minimal_from_env()` - Phase 1 bootstrap from environment variables only
- `from_env_and_mysql()` - Phase 2 enrichment from MySQL settings table (NEW)
- Environment variables take precedence over MySQL settings
- Prefers staging bucket (`s3_bucket_stg`) over production bucket

**Test Coverage**:
- 7 unit tests (mocked MySQL) - all passing
- 3 integration tests (real MySQL with AWS Secrets Manager credentials) - all passing
- Validates: bootstrap, enrichment, precedence, fallbacks, two-phase pattern

**Status**: ✅ Complete - Production-ready with 10/10 tests passing

#### 1.4 AWS Credential Resolution ✅ (Added Milestone)

**File**: `pulldb/infra/secrets.py` (405 lines)

**Tasks**:
- [x] Implement MySQLCredentials dataclass (frozen, slots, password redaction)
- [x] Implement CredentialResolver class with lazy client initialization
- [x] Support AWS Secrets Manager resolution (`aws-secretsmanager:` prefix)
- [x] Support AWS SSM Parameter Store resolution (`aws-ssm:` prefix)
- [x] Implement CredentialResolutionError custom exception
- [x] Add command-line interface for testing credential resolution
- [x] Create comprehensive test suite with moto mocking

**Implementation Highlights**:
- MySQLCredentials: username, password, host, port, db_cluster_identifier
- CredentialResolver with `resolve(credential_ref)` method
- Lazy boto3 client initialization (creates clients only when needed)
- Support for AWS_PROFILE and PULLDB_AWS_PROFILE environment variables
- Detailed error messages for missing secrets, access denied, invalid format
- Command-line usage: `python3 -m pulldb.infra.secrets <credential_ref>`

**Test Coverage**:
- 14 unit tests with @mock_aws decorator - all passing
- Tests cover: Secrets Manager success/failure, SSM success/failure, error handling
- Moto 5.x compatible (uses unified `mock_aws` decorator)

**Documentation**:
- Complete setup guide: `docs/aws-secrets-manager-setup.md`
- Integration with Config module documented
- credential_ref pattern documented in `docs/mysql-schema.md`

**Status**: ✅ Complete - Production-ready with 14/14 tests passing

### Milestone 2: MySQL Repository Layer (Week 1-2)

> **Detailed Plan**: See `design/milestone-2-plan.md` for comprehensive implementation guide

**Summary**: Implement repository pattern for all MySQL operations with domain models and comprehensive test coverage.

**Files**:
- `pulldb/domain/models.py` (NEW) - Domain dataclasses (Job, User, JobEvent, DBHost, Setting)
- `pulldb/infra/mysql.py` (EXTEND) - Add 4 repository classes
- `pulldb/tests/test_repositories.py` (NEW) - 23+ repository tests

#### 2.1 Domain Models ✅

**File**: `pulldb/domain/models.py` (192 lines)

**Tasks**:
- [x] Create new file for domain dataclasses
- [x] Implement JobStatus enum (queued, running, failed, complete, canceled)
- [x] Implement User dataclass (frozen=True, all fields from auth_users)
- [x] Implement Job dataclass (frozen=True, all fields from jobs table)
- [x] Implement JobEvent dataclass (frozen=True, all fields from job_events)
- [x] Implement DBHost dataclass (frozen=True, all fields from db_hosts)
- [x] Implement Setting dataclass (frozen=True, all fields from settings)
- [x] Add Google-style docstrings to all classes
- [x] Add type hints using modern Python 3.10+ syntax (X | None)

**Status**: ✅ Complete - All 5 dataclasses implemented with comprehensive documentation

#### 2.2 JobRepository ✅

**File**: `pulldb/infra/mysql.py` (465 lines total, 406 lines added)

**Tasks**:
- [x] Implement JobRepository class with MySQLPool dependency
- [x] `enqueue_job(job: Job) -> str` - Insert job, return job_id
- [x] `get_next_queued_job() -> Optional[Job]` - FIFO queue retrieval
- [x] `get_job_by_id(job_id: str) -> Optional[Job]` - Single job lookup
- [x] `mark_job_running(job_id: str)` - Transition to running, set started_at
- [x] `mark_job_complete(job_id: str)` - Transition to complete, set completed_at
- [x] `mark_job_failed(job_id: str, error: str)` - Transition to failed with error
- [x] `get_active_jobs() -> list[Job]` - Use active_jobs view
- [x] `get_jobs_by_user(user_id: str) -> list[Job]` - User job history
- [x] `check_target_exclusivity(target: str, dbhost: str) -> bool` - Per-target lock check
- [x] `append_job_event(job_id: str, event_type: str, detail: str)` - Event logging
- [x] `get_job_events(job_id: str) -> list[JobEvent]` - Event retrieval
- [x] Handle IntegrityError for per-target exclusivity violations
- [x] Convert MySQL rows to Job/JobEvent dataclasses

**Status**: ✅ Complete - 12 public methods + 3 helper methods, comprehensive error handling

#### 2.3 UserRepository

**File**: `pulldb/infra/mysql.py` (extend existing)

**Tasks**:
- [x] Implement UserRepository class with MySQLPool dependency
- [x] `get_user_by_username(username: str) -> Optional[User]` - Username lookup
- [x] `get_user_by_id(user_id: str) -> Optional[User]` - User ID lookup
- [x] `create_user(username: str, user_code: str) -> User` - Insert new user
- [x] `get_or_create_user(username: str) -> User` - Get existing or create with code generation
- [x] `generate_user_code(username: str) -> str` - **CRITICAL**: User code algorithm with collision handling
- [x] `check_user_code_exists(user_code: str) -> bool` - Collision detection
- [x] Implement collision algorithm: try positions 5, 4, 3 (max 3 adjustments)
- [x] Raise ValueError if username has < 6 letters or collision limit exceeded
- [x] Handle IntegrityError for duplicate username/user_code

**User Code Algorithm** (Critical Business Logic):
1. Extract first 6 alphabetic characters (lowercase, letters only)
2. Check if code is unique in database
3. If collision, replace 6th char with next unused letter from username
4. If still collision, try 5th char, then 4th char (max 3 adjustments)
5. Fail if unique code cannot be generated

**Status**: ✅ Complete - 7 public methods + 1 helper method, comprehensive collision handling

#### 2.4 HostRepository

**File**: `pulldb/infra/mysql.py` (extend existing)

**Tasks**:
- [x] Implement HostRepository class with MySQLPool + CredentialResolver dependencies
- [x] `get_host_by_hostname(hostname: str) -> Optional[DBHost]` - Host lookup
- [x] `get_enabled_hosts() -> list[DBHost]` - All enabled hosts
- [x] `get_host_credentials(hostname: str) -> MySQLCredentials` - Resolve credentials via CredentialResolver
- [x] `check_host_capacity(hostname: str) -> bool` - Check running jobs vs max_concurrent_restores
- [x] Integrate with existing CredentialResolver from Milestone 1.4
- [x] Raise ValueError if host not found or disabled
- [x] Let CredentialResolutionError bubble up from secrets module

**Status**: ✅ Complete - 4 public methods + 1 helper method, credential resolution integrated

#### 2.5 SettingsRepository

**File**: `pulldb/infra/mysql.py` (extend existing)

**Tasks**:
- [x] Implement SettingsRepository class with MySQLPool dependency
- [x] `get_setting(key: str) -> Optional[str]` - Single setting lookup
- [x] `get_setting_required(key: str) -> str` - Required setting with ValueError
- [x] `set_setting(key: str, value: str, description: Optional[str])` - INSERT or UPDATE
- [x] `get_all_settings() -> dict[str, str]` - Bulk retrieval as dictionary
- [x] Use INSERT ... ON DUPLICATE KEY UPDATE for set_setting

**Status**: ✅ Complete - 4 public methods, simple CRUD operations

#### 2.6 Repository Tests

**File**: `pulldb/tests/test_repositories.py` (NEW)

**Tasks**:
- [ ] Create test database fixture with setup/teardown
- [ ] Create connection pool fixture
- [ ] Test JobRepository (8+ tests):
  - [ ] test_enqueue_job - Basic job insertion
  - [ ] test_get_next_queued_job - FIFO ordering
  - [ ] test_mark_job_running - Status transition
  - [ ] test_mark_job_complete - Completion with timestamp
  - [ ] test_mark_job_failed - Failure with error detail
  - [ ] test_per_target_exclusivity - Constraint violation
  - [ ] test_append_job_event - Event logging
  - [ ] test_get_job_events - Event retrieval
- [ ] Test UserRepository (8+ tests):
  - [ ] test_generate_user_code_basic - First 6 letters
  - [ ] test_generate_user_code_collision_6th_char - Replace position 5
  - [ ] test_generate_user_code_collision_5th_char - Replace position 4
  - [ ] test_generate_user_code_collision_4th_char - Replace position 3
  - [ ] test_generate_user_code_exhausted - All strategies fail
  - [ ] test_generate_user_code_insufficient_letters - < 6 letters
  - [ ] test_get_or_create_user_existing - Existing user
  - [ ] test_get_or_create_user_new - New user with code generation
- [ ] Test HostRepository (3+ tests):
  - [ ] test_get_host_by_hostname - Host lookup
  - [ ] test_get_host_credentials - Credential resolution (mock AWS)
  - [ ] test_check_host_capacity - Capacity checking
- [ ] Test SettingsRepository (4+ tests):
  - [ ] test_get_setting - Single setting
  - [ ] test_set_setting_insert - New setting
  - [ ] test_set_setting_update - Update existing
  - [ ] test_get_all_settings - Bulk retrieval
- [ ] Target: 23+ tests, 100% coverage of repository methods
- [ ] All tests must pass with real MySQL instance

#### 2.7 Integration Updates



**Status**: ✅ Complete (November 1, 2025)

**Audit Summary**:
- Refactored `Config.from_env_and_mysql()` to accept `MySQLPool` instead of direct connection, aligning with repository pattern used across infrastructure layer.
- Eliminated manual cursor management and inline SQL (`SELECT setting_key, setting_value FROM settings`) in favor of `SettingsRepository.get_all_settings()` abstraction.
- Updated all unit and integration tests (5 unit + 3 integration impacted) to pass `MySQLPool` mocks or concrete pool directly. Test suite restored to 28/28 passing.
- Added forward type reference (`if TYPE_CHECKING:`) for `MySQLPool` to avoid runtime import cycles.
- Ensured environment override precedence logic preserved (staging bucket over production, env vars over MySQL settings, default fallbacks intact).
- Verified no regression in two-phase loading pattern (bootstrap via `minimal_from_env()` then enrich via repository-backed method).
- Improved maintainability: future settings changes isolated to `SettingsRepository` without touching configuration domain logic.

### Milestone 2.5: Worker Foundation (Week 2) - ✅ COMPLETE

**Summary**: Implemented S3 discovery/download, worker poll loop, restore orchestration, post-SQL execution, staging lifecycle, metadata injection, and atomic rename.

**Completion Date**: November 3, 2025

**Components Implemented**:
- `pulldb/worker/loop.py` - Poll loop with exponential backoff and metrics
- `pulldb/worker/downloader.py` - S3 backup download with disk capacity checks
- `pulldb/infra/s3.py` - S3 client wrapper with backup discovery
- `pulldb/worker/restore.py` - Complete workflow orchestration (staging → myloader → post-SQL → metadata → atomic rename)
- `pulldb/worker/post_sql.py` - Sequential SQL script execution with FAIL HARD on first error
- `pulldb/worker/staging.py` - Orphan cleanup, staging name generation, collision detection
- `pulldb/worker/metadata.py` - pullDB metadata table injection with JSON script report
- `pulldb/worker/atomic_rename.py` - Stored procedure invocation module
- `pulldb/infra/exec.py` - Subprocess wrapper with timeout handling
- `pulldb/domain/errors.py` - 8 domain error classes with structured FAIL HARD diagnostics
- `pulldb/domain/restore_models.py` - MyLoader and workflow specification dataclasses

**Test Coverage**:
- 23 worker unit tests (restore, post-SQL, staging, metadata, exec)
- 25+ integration tests (workflow happy path, failure modes, disk capacity, S3 discovery)
- All tests passing (170/170)

**Status**: ✅ Complete - End-to-end restore workflow functional

### Milestone 2.6: Atomic Rename Enhancements (Week 2) - ✅ COMPLETE

**Summary**: Added versioned stored procedure, preview procedure, deployment script, and benchmark tooling.

**Completion Date**: November 3, 2025

**Components Added**:
- `docs/atomic_rename_procedure.sql` - Versioned procedure (v1.0.0) + preview procedure
- `scripts/deploy_atomic_rename.py` - Deployment script with version validation and preview flag
- `scripts/benchmark_atomic_rename.py` - Rename SQL build performance benchmarking
- Deployment tests (dry-run, host validation, connection/drop/create failures, version checking)
- Benchmark tests (JSON output, FAIL HARD input validation)

**Features**:
- Version header in SQL file enforces deployment compatibility
- Preview procedure for safe SQL inspection without execution
- `--deploy-preview` flag for optional preview deployment
- `--skip-version-check` override for emergency deployments
- Benchmark tool measures rename statement build performance at scale

**Test Coverage**:
- 14 new tests (deployment scenarios + benchmark validation)
- All tests passing

**Status**: ✅ Complete - Production-ready deployment tooling

### Milestone 3: CLI Implementation (Week 2) ✅ Complete

**Completion Date**: November 3, 2025

**Implementation Summary**:
- Click-based CLI framework with restore and status commands
- Full argument parser (`pulldb/cli/parse.py` - 147 lines)
- Option validation (user=, customer=/qatemplate, dbhost=, overwrite)
- User code generation with collision handling via UserRepository
- Target name sanitization and length validation
- Per-target exclusivity check before enqueue
- Job enqueue with metrics emission
- **Status command** with `--json`, `--wide`, `--limit` options
- Table and JSON output formatting
- Empty state messaging

**Tests**: 5 CLI tests (empty state, table output, wide mode, JSON mode, limit truncation)

#### 3.1 CLI Parser and Validator

**File**: `pulldb/cli/main.py`

**Tasks**:
- [x] Implement Click-based CLI with subcommands
- [x] Parse `user=`, `customer=`, `qatemplate`, `dbhost=`, `overwrite` options
- [x] Validate mutually exclusive options (customer/qatemplate)
- [x] Validate user parameter (6+ alphabetic characters)
- [x] Generate user_code with collision detection
- [x] Sanitize customer ID (lowercase, letters only)
- [x] Generate target name (user_code + customer/qatemplate)
- [x] Validate target name length (max 51 chars for staging suffix)
- [x] Check per-target exclusivity before enqueue
- [x] Handle `overwrite` flag for existing targets
- [x] Implement `status` command
- [x] Implement `--help` and error messages

**CLI Interface**:
```bash
# Main restore command
pulldb user=jdoe customer=acme dbhost=db-mysql-db4-dev overwrite

# Status command
pulldb status [--json] [--wide] [--limit N]

# Help
pulldb --help
```

**File**: `pulldb/cli/formatter.py`

**Tasks**:
- [ ] Format job submission confirmation
- [ ] Format status output (table of active jobs)
- [ ] Format error messages
- [ ] Support quiet mode for scripting

### Milestone 4: Daemon Core (Week 2-3) ✅ COMPLETE (Nov 3, 2025)

#### 4.1 Daemon Main Loop

**File**: `pulldb/worker/service.py`

**Implemented**:
- [x] Daemon startup and configuration loading (`Config.minimal_from_env()`)
- [x] Graceful shutdown via SIGTERM/SIGINT (signal handlers + threading.Event)
- [x] Poll loop integration with stop callback (`should_stop` in `run_poll_loop`)
- [x] Lifecycle metrics (worker_active gauge, daemon start/stop events)
- [x] Systemd unit example (`scripts/pulldb-worker.service`)
- [x] Test coverage for stop callback (`test_worker_service.py`)

**Notes**:
- Backoff remains inside poll loop; service re-enters only if interrupted.
- Future enhancement (Phase 1): periodic heartbeat + queue depth gauge outside job acquisition.

**Status**: ✅ Complete – Daemon ready for production deployment.

            # Phase 2: Download
            backup_file = self.downloader.find_latest_backup(job.customer_id)
            local_path = self.downloader.download(backup_file)

            # Phase 3: Restore
            staging_name = self.generate_staging_name(job.target, job.id)
            self.restorer.restore_to_staging(local_path, staging_name, job.dbhost)

            # Phase 4: Post-SQL
            self.cleaner.execute_post_sql(staging_name, job.customer_type, job.dbhost)

            # Phase 5: Metadata
            self.cleaner.add_metadata_table(staging_name, job, backup_file)

            # Phase 6: Rename
            self.restorer.atomic_rename(staging_name, job.target, job.dbhost)

            # Phase 7: Cleanup
            self.cleanup_temp_files(local_path)

            self.job_repo.mark_job_complete(job.id)

        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}")
            self.job_repo.mark_job_failed(job.id, str(e))
```

    ### Milestone 5: S3 Integration (Week 3) ✅ Complete

    **Completion Date**: November 2, 2025

    **Implementation Summary**:
    - S3 client wrapper in `pulldb/infra/s3.py` (137 lines)
    - Backup discovery with pagination (supports large bucket listings)
    - Latest backup selection (sorted by timestamp from filename)
    - Required file validation (`*-schema-create.sql.zst` presence check)
    - Disk capacity preflight check (`tar_size * 1.8` required free space)
    - Streaming download from S3 to local filesystem
    - Integration with worker/downloader.py orchestration

    **Tests**: 25+ integration tests including optional real S3 listing (skips gracefully when offline), disk capacity scenarios, backup selection algorithm, missing file handling.

#### 5.1 S3 Downloader

**File**: `pulldb/daemon/downloader.py`

**Tasks**:
    - [x] Implement boto3 S3 client wrapper
    - [x] List files in S3 bucket with pagination
    - [x] Find latest backup for customer/qatemplate
    - [x] Validate backup has required files (*-schema-create.sql.zst)
    - [x] Check available disk space before download
    - [x] Download with streaming (no separate progress tracking implemented)
    - [x] Extract via worker/restore.py orchestration

**Example**:
```python
class S3Downloader:
    def find_latest_backup(self, customer_id: str) -> str:
        """Find most recent backup file for customer."""
        prefix = f"daily/prod/{customer_id}/"
        response = self.s3_client.list_objects_v2(
            Bucket=self.bucket,
            Prefix=prefix
        )
        # Parse filenames, sort by date, return latest
        pass

    def download(self, s3_key: str, local_path: Path) -> Path:
        """Download and extract backup."""
        # Check disk space
        # Download with boto3
        # Extract tarball
        # Return extracted directory path
        pass
```

    ### Milestone 6: MySQL Restore (Week 3-4) ✅ Complete

    **Completion Date**: November 3, 2025

    **Implementation Summary**:
    - Staging database name generation in `pulldb/worker/staging.py` (pattern: `{target}_{job_id[:12]}`)
    - Orphaned staging cleanup (DROP databases matching `{target}_[0-9a-f]{12}`)
    - myloader subprocess wrapper in `pulldb/infra/exec.py` with timeout handling
    - Complete restore orchestration in `pulldb/worker/restore.py` (247 lines)
    - Atomic rename via stored procedure (`pulldb/worker/atomic_rename.py`)
    - Comprehensive error handling with FAIL HARD diagnostics
    - Staging database preservation on failure for post-mortem

    **Tests**: Integration tests covering happy path, myloader failures, timeout scenarios, atomic rename invocation, staging cleanup logic.

#### 6.1 Restorer with Staging Pattern

**File**: `pulldb/daemon/restorer.py`

**Tasks**:
    - [x] Implement staging database name generation (target + "_" + job_id[:12])
    - [x] Implement orphaned staging database cleanup
    - [x] Wrap myloader subprocess execution
    - [x] Capture myloader output (stdout/stderr logged, not parsed for progress)
    - [x] Implement atomic rename with stored procedure
    - [x] Handle myloader errors (non-zero exit, timeout)
    - [x] Verify restore completion (implicit via myloader exit code)

**Critical Implementation**:
```python
class MySQLRestorer:
    def cleanup_orphaned_staging(self, target: str, dbhost: str):
        """Drop old staging databases matching target_[0-9a-f]{12} pattern."""
        conn = self.get_host_connection(dbhost)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SCHEMA_NAME
            FROM information_schema.SCHEMATA
            WHERE SCHEMA_NAME REGEXP %s
        """, (f"^{target}_[0-9a-f]{{12}}$",))

        for row in cursor.fetchall():
            staging_db = row['SCHEMA_NAME']
            logger.info(f"Dropping orphaned staging: {staging_db}")
            cursor.execute(f"DROP DATABASE IF EXISTS `{staging_db}`")
            self.job_repo.append_job_event(
                job.id, 'staging_auto_cleanup',
                f"Dropped: {staging_db}"
            )

    def restore_to_staging(self, backup_dir: Path, staging_name: str, dbhost: str):
        """Execute myloader to restore into staging database."""
        host_config = self.host_repo.get_host_config(dbhost)

        cmd = [
            'myloader',
            f'--directory={backup_dir}',
            f'--database={staging_name}',
            f'--host={host_config.host}',
            f'--user={host_config.user}',
            f'--password={host_config.password}',
            '--overwrite-tables',
            '--threads=4',
            '--verbose=3'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"myloader failed: {result.stderr}")

    def atomic_rename(self, staging_name: str, target: str, dbhost: str):
        """Atomically rename staging → target using stored procedure."""
        conn = self.get_host_connection(dbhost)
        cursor = conn.cursor()

        # Drop existing target
        cursor.execute(f"DROP DATABASE IF EXISTS `{target}`")
        cursor.execute(f"CREATE DATABASE `{target}`")

        # Create rename procedure
        cursor.execute("DROP PROCEDURE IF EXISTS RenameDatabase")
        cursor.execute(RENAME_PROCEDURE_SQL)  # From staging-rename-pattern.md

        # Execute rename
        cursor.execute(f"CALL RenameDatabase('{staging_name}', '{target}')")

        # Drop empty staging database
        cursor.execute(f"DROP DATABASE IF EXISTS `{staging_name}`")

        conn.commit()
```

    ### Milestone 7: Post-Restore SQL (Week 4) ✅ Complete

    **Completion Date**: November 2, 2025

    **Implementation Summary**:
    - Post-SQL executor in `pulldb/worker/post_sql.py` (168 lines)
    - Script loading from `customers_after_sql/` or `qa_template_after_sql/` directories
    - Lexicographic execution order (010, 020, 030...)
    - FAIL HARD on first error (aborts job, preserves staging for diagnostics)
    - JSON status report generation (script name, status, timing, row count)
    - Metadata table injection in `pulldb/worker/metadata.py` (85 lines)
    - Job event logging for each script execution

    **Tests**: Unit tests for script execution (success, failure, timing capture), metadata injection, JSON report generation, integration with restore workflow.

#### 7.1 Post-SQL Executor

**File**: `pulldb/daemon/cleaner.py`

**Tasks**:
    - [x] Load SQL files from `customers_after_sql/` or `qa_template_after_sql/`
    - [x] Execute in lexicographic order (010, 020, 030...)
    - [x] Track execution status (success/failed with timing and row counts)
    - [x] Handle SQL execution errors (FAIL HARD on first error)
    - [x] Return JSON status report
    - [x] Add pullDB metadata table to staging database
    - [x] Log execution in job_events

**Example**:
```python
class PostRestoreCleaner:
    def execute_post_sql(self, staging_name: str, customer_type: str, dbhost: str) -> dict:
        """Execute post-restore SQL scripts."""
        if customer_type == 'customer':
            sql_dir = self.config.customers_after_sql_dir
        else:
            sql_dir = self.config.qa_template_after_sql_dir

        conn = self.get_host_connection(dbhost)
        results = {}

        sql_files = sorted(Path(sql_dir).glob('*.sql'))
        for sql_file in sql_files:
            try:
                with open(sql_file) as f:
                    sql = f.read()

                cursor = conn.cursor()
                for statement in sql.split(';'):
                    if statement.strip():
                        cursor.execute(statement)
                conn.commit()
                results[sql_file.name] = 'success'

            except Exception as e:
                conn.rollback()
                results[sql_file.name] = f'failed: {str(e)}'
                raise  # Abort job on SQL failure

        return results

    def add_metadata_table(self, staging_name: str, job: Job,
                          backup_file: str, post_sql_results: dict, dbhost: str):
        """Create pullDB metadata table in staging database."""
        conn = self.get_host_connection(dbhost)
        cursor = conn.cursor()

        cursor.execute(f"USE `{staging_name}`")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pullDB (
                job_id CHAR(36) PRIMARY KEY,
                restored_by VARCHAR(255) NOT NULL,
                restored_at TIMESTAMP(6) NOT NULL,
                backup_file VARCHAR(512) NOT NULL,
                post_restore_sql_status JSON NOT NULL,
                restore_completed_at TIMESTAMP(6) NOT NULL
            )
        """)

        cursor.execute("""
            INSERT INTO pullDB VALUES (%s, %s, UTC_TIMESTAMP(6), %s, %s, UTC_TIMESTAMP(6))
        """, (job.id, job.owner_username, backup_file, json.dumps(post_sql_results)))

        conn.commit()
```

    ### Milestone 8: Logging & Metrics (Week 4) ✅ Complete

    **Completion Date**: November 2, 2025

    **Implementation Summary**:
    - Structured JSON logging in `pulldb/infra/logging.py` (88 lines)
    - Standard fields: timestamp, level, job_id, phase, message, logger
    - Metrics emission framework in `pulldb/infra/metrics.py` (132 lines)
    - Logging-based metrics (counters, gauges, timers, events)
    - Context manager for timing operations
    - Labels/tags system for dimensional metrics
    - Ready for Datadog ingestion (structured JSON + metric events)

    **Metrics Implemented**:
    - Counters: jobs_enqueued_total, restore_attempts_total, restore_failed_total, restore_succeeded_total
    - Gauges: queue_depth, active_restores, backoff_interval_seconds
    - Timers: restore_duration_seconds, download_duration_seconds, myloader_duration_seconds, post_sql_duration_seconds
    - Events: disk_capacity_insufficient, myloader_error, post_sql_error, atomic_rename_error

#### 8.1 Structured Logging

**File**: `pulldb/infra/logging.py`

**Tasks**:
    - [x] Implement JSON structured logging
    - [x] Include standard fields: timestamp, level, job_id, phase, message
    - [ ] Configure file rotation (deferred - Python logging module supports this)
    - [ ] Configure log levels per environment (deferred - hardcoded INFO for prototype)
    - [x] Prepare for Datadog ingestion (JSON format ready)

**Example**:
```python
import logging
import json

class StructuredLogger:
    def __init__(self, name: str, log_file: Path):
        self.logger = logging.getLogger(name)
        handler = logging.FileHandler(log_file)
        handler.setFormatter(self.JSONFormatter())
        self.logger.addHandler(handler)

    class JSONFormatter(logging.Formatter):
        def format(self, record):
            log_obj = {
                'timestamp': self.formatTime(record),
                'level': record.levelname,
                'message': record.getMessage(),
                'logger': record.name
            }
            if hasattr(record, 'job_id'):
                log_obj['job_id'] = record.job_id
            if hasattr(record, 'phase'):
                log_obj['phase'] = record.phase
            return json.dumps(log_obj)
```

#### 8.2 Metrics Emission

**Tasks**:
- [ ] Implement Datadog metric emission (StatsD protocol)
- [ ] Emit queue depth metric
- [ ] Emit disk capacity failure metric
- [ ] Track phase durations
### Milestone 9: Testing (Week 5) ✅ Complete

**Completion Date**: November 3, 2025

**Test Suite Summary**: 170 tests passing, 1 skipped, 1 xpassed (56.65s, timeout=60s per test)

**Test Coverage by Category**:
- 87 repository + integration tests (user code collisions, credential resolution, MySQL CRUD)
- 23 worker unit tests (downloader, staging, post_sql, restore orchestration)
- 25+ integration tests (happy path, myloader failure, post-SQL failure, disk insufficient, missing backup)
- 14 deployment + benchmark tests (atomic rename procedure deployment, version validation, performance)
- 14 secrets tests (AWS Secrets Manager, SSM Parameter Store resolution)
- 7 config tests (two-phase loading, environment + MySQL enrichment)

**Testing Infrastructure**:
- pytest with real MySQL 8.0.43 instances
- AWS Secrets Manager integration (graceful degradation when offline)
- moto for S3 mocking
- Optional real S3 listing test (skips when AWS unavailable)
- Monkeypatching for subprocess calls (no myloader binary dependency)
- Comprehensive failure mode coverage
### Milestone 9: Testing (Week 5)

#### 9.1 Unit Tests

- [x] Test user_code generation with collision handling (positions 6, 5, 4)
- [x] Test target name sanitization (lowercase, letters only, length validation)
- [x] Test staging name generation (pattern validation, collision detection)
- [x] Test MySQL repositories with test database (87 tests)
- [x] Test configuration loading (two-phase env + MySQL enrichment)
- [x] Mock S3 operations with moto
- [x] Mock subprocess calls for myloader (monkeypatch run_command)
- [ ] Mock subprocess calls for myloader

#### 9.2 Integration Tests

- [x] Test complete restore flow end-to-end (logical happy path)
- [x] Test orphaned staging database cleanup
- [x] Test atomic rename pattern (procedure invocation module)
- [x] Test post-restore SQL execution (sequential, fail-on-first-error)
- [x] Test error handling and rollback (myloader failure, post-SQL failure, disk insufficient)
- [x] Test per-target exclusivity (active_target_key constraint)
- [x] Test per-target exclusivity (active_target_key constraint)

### Milestone 10: Deployment (Week 5-6) ⚠️ Partial

**Status**: Documentation complete, deployment artifacts pending

**Completed**:
- [x] IAM role requirements documented (`docs/aws-ec2-deployment-setup.md`)
- [x] MySQL credentials setup guide (`docs/aws-secrets-manager-setup.md`)
- [x] Operational runbooks (`design/runbook-restore.md`, `design/runbook-failure.md`)
- [x] Atomic rename procedure deployment script (`scripts/deploy_atomic_rename.py`)
- [x] Systemd worker service unit (`scripts/pulldb-worker.service`)
- [x] Worker service entry point (`pulldb/worker/service.py`)
- [x] Installer customization script (`scripts/install_pulldb.sh`)

**Pending** (estimated 2-3 days):
- [ ] Monitoring dashboard template (Datadog)
- [ ] Initial production deployment + 2-week stability monitoring

#### 10.1 Deployment Package

**Tasks**:
- [x] Create systemd service file for worker (scripts/pulldb-worker.service)
- [x] Create installer/deployment script (`scripts/install_pulldb.sh`)
- [x] Document IAM role requirements
- [x] Document MySQL credentials setup
- [ ] Create monitoring dashboard template (pending - metrics framework ready)
- [x] Write operational runbook

**Example systemd service**:
```ini
[Unit]
Description=pullDB Worker Service
After=network.target

[Service]
Type=simple
User=pulldb
WorkingDirectory=/opt/pulldb
ExecStart=/opt/pulldb/venv/bin/pulldb-worker
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 10.2 Initial Deployment

**Tasks**:
- [ ] Deploy MySQL coordination database
- [ ] Populate db_hosts table with db3, db4, db5
- [ ] Populate settings table with defaults
- [ ] Deploy worker service to EC2 instance
- [ ] Configure AWS credentials and IAM
- [ ] Deploy CLI to jump box / developer machines
- [ ] Test end-to-end restore with real backup
- [ ] Monitor metrics in Datadog

## Testing Strategy

### Pre-Production Testing

1. **Local Development Testing**:
   - Use local MySQL instance
   - Mock S3 with moto
   - Test against small synthetic backups
   - Verify all unit tests pass

2. **Staging Environment Testing**:
   - Use dedicated staging MySQL coordination database
   - Use staging S3 bucket with test backups
   - Restore to isolated database server
   - Verify metrics emission
   - Test failure scenarios

3. **Production Verification**:
   - Deploy daemon to production EC2
   - Test with single real customer backup
   - Verify post-restore SQL execution
   - Verify atomic rename
   - Verify cleanup
   - Monitor logs and metrics

### Acceptance Criteria

- [ ] User can submit restore job: `pullDB user=testuser customer=testcust`
- [ ] Daemon processes job successfully
- [ ] Staging database created with pattern `testusertestcust_<job_id_short>`
- [ ] Orphaned staging databases auto-cleaned before restore
- [ ] Post-restore SQL scripts execute (verify with `SELECT * FROM pullDB`)
- [ ] Atomic rename completes without downtime
- [ ] Target database contains all expected tables and data
- [ ] Job status visible: `pullDB status`
- [ ] Logs contain structured JSON with all phases
- [ ] Metrics visible in Datadog: queue_depth, disk_failures
- [ ] Error handling preserves staging database for inspection
- [ ] Per-target exclusivity prevents concurrent restores

## Risk Mitigation

### Technical Risks

1. **myloader Compatibility**:
   - Risk: myloader version incompatibility
   - Mitigation: Pin mydumper 0.9.5, test in staging first

2. **Disk Space Exhaustion**:
   - Risk: Large backups fill disk during extraction
   - Mitigation: Pre-check available space (tar_size * 2.8), emit metrics

3. **Atomic Rename Failure**:
   - Risk: Stored procedure fails mid-rename
   - Mitigation: Preserve staging database, document manual recovery in runbook

4. **Network Interruptions**:
   - Risk: S3 download interrupted
   - Mitigation: Retry logic with exponential backoff, cleanup partial downloads

### Operational Risks

1. **Daemon Crashes**:
   - Risk: Daemon dies mid-restore
   - Mitigation: Systemd auto-restart, job stays in 'running' status for investigation

2. **Database Credentials Rotation**:
   - Risk: Credentials expire mid-restore
   - Mitigation: Use AWS Secrets Manager with auto-refresh

3. **Per-Target Lock Deadlock**:
   - Risk: Job stuck in 'running' status forever
   - Mitigation: Manual intervention documented in runbook, add watchdog in Phase 1

## Timeline

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 1 | Foundation + MySQL | Project structure, schema deployed, config module |
| 2 | CLI + Daemon Core | Working CLI, daemon polling loop |
| 3 | S3 + Restore | S3 download, myloader integration, staging pattern |
| 4 | Post-SQL + Logging | Post-restore scripts, metadata table, structured logs |
| 5 | Testing | Unit tests, integration tests passing |
| 6 | Deployment | Daemon running in production, first successful restore |

**Total**: 6 weeks to production-ready prototype

## Success Metrics

### Week 6 Goals
- [ ] 10 successful restores completed
- [ ] Zero unhandled exceptions in daemon logs
- [ ] Average job duration < 30 minutes for typical customer database
- [ ] Queue depth metric accurate in Datadog
- [ ] All 12 post-restore SQL scripts executing successfully
- [ ] Staging database auto-cleanup working (verified via manual inspection)

### Phase 0 Exit Criteria
- [ ] Prototype stable for 2 weeks in production
- [ ] No critical bugs reported
- [ ] Documentation updated with any design changes
- [ ] Operational runbook tested and validated
- [ ] Ready to begin Phase 1 (cancellation, history, scheduled cleanup)

## Next Steps

1. **Immediate**: Create GitHub project board with tasks from this plan
2. **Day 1**: Set up Python project structure and dependencies
3. **Day 2**: Deploy MySQL schema to dev environment
4. **Day 3**: Begin CLI implementation
5. **Week 2**: Begin daemon implementation
6. **Week 4**: Begin end-to-end testing
7. **Week 6**: Production deployment

## References

- Primary: `.github/copilot-instructions.md` - Architecture and constraints
- Standards: `constitution.md` - KISS principles, tooling, workflow
- API: `README.md` - Complete usage patterns and examples
- Schema: `docs/mysql-schema.md` - Database design and initialization
- Staging: `design/staging-rename-pattern.md` - MANDATORY restore pattern
- Legacy: `design/apptype-analysis.md` - appType → dbhost mapping

---

**Status**: Ready to begin implementation
**Approval Required**: Review and approve this plan before starting
**Questions**: Document any questions or concerns before proceeding
