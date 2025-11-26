# pullDB Workspace Index

> **Purpose**: Comprehensive atomic-level index for AI model searching and navigation.  
> **Last Updated**: 2025-11-26  
> **File Count**: ~297 project files (excluding venv, .git, caches)

---

## Quick Reference

| Category | Count | Primary Path |
|----------|-------|--------------|
| Python Source | 78 | `pulldb/` |
| Tests | 50+ | `pulldb/tests/` |
| Shell Scripts | 33 active | `scripts/` |
| SQL Schema | 10 | `schema/pulldb_service/` |
| Documentation | 35+ | `docs/` |
| Design Docs | 18 | `design/` |
| Copilot Instructions | 6 | `.github/` |

---

## Architecture Overview

```
┌─────────┐    ┌─────────────┐    ┌──────────────────┐
│   CLI   │───►│ API Service │───►│ MySQL Queue      │
└─────────┘    │ (FastAPI)   │    │ (pulldb_service) │
               └─────────────┘    └────────┬─────────┘
                                           │
                                           ▼
                              ┌────────────────────────┐
                              │    Worker Service      │
                              │ ┌─────────┬──────────┐ │
                              │ │Download │ myloader │ │
                              │ │  S3     │ restore  │ │
                              │ └─────────┴──────────┘ │
                              └────────────────────────┘
```

---

## 1. Python Package (`pulldb/`)

### 1.1 Core Modules

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `__init__.py` | Package root | Version export |

### 1.2 API Service (`pulldb/api/`)

| File | Purpose | Key Elements |
|------|---------|--------------|
| `main.py` | FastAPI application | `JobRequest`, `JobResponse`, `JobSummary`, `JobEventResponse`, `APIState`, `create_app()`, `submit_job()`, `list_jobs()`, `health()` |
| `__init__.py` | Package marker | - |

**Endpoints**:
- `POST /jobs` - Submit restore job
- `GET /jobs` - List jobs with filters
- `GET /jobs/active` - Active jobs only
- `GET /jobs/{job_id}/events` - Job event stream
- `GET /health` - Health check
- `GET /status` - System status

### 1.3 CLI (`pulldb/cli/`)

| File | Purpose | Key Elements |
|------|---------|--------------|
| `main.py` | CLI entry point | `cli()`, `restore_cmd()`, `status_cmd()`, `_api_post()`, `_api_get()`, `_JobRow` |
| `parse.py` | Argument parser | `RestoreCLIOptions`, `CLIParseError`, `parse_restore_args()` |
| `settings.py` | Settings management | `settings_group()`, `list_settings()`, `get_setting()`, `set_setting()`, `reset_setting()`, `export_settings()` |
| `__main__.py` | Module execution | CLI bootstrap |
| `__init__.py` | Package marker | - |

**CLI Commands**:
- `pulldb restore <user> customer <name>` - Customer restore
- `pulldb restore <user> qatemplate` - QA template restore
- `pulldb status [--json] [--wide] [--limit N]` - View jobs
- `pulldb settings list|get|set|reset|export` - Settings management

### 1.4 Domain Layer (`pulldb/domain/`)

| File | Purpose | Key Elements |
|------|---------|--------------|
| `models.py` | Domain entities | `JobStatus` (Enum), `User`, `Job`, `JobEvent`, `DBHost`, `Setting` |
| `config.py` | Configuration | `Config`, `S3BackupLocationConfig`, environment variable parsing |
| `errors.py` | Error hierarchy | `JobExecutionError`, `DownloadError`, `ExtractionError`, `DiskCapacityError`, `MyLoaderError`, `PostSQLError`, `AtomicRenameError`, `BackupValidationError`, `BackupDiscoveryError`, `MetadataInjectionError`, `StagingError` |
| `restore_models.py` | Restore DTOs | `MyLoaderSpec`, `MyLoaderResult`, `build_configured_myloader_spec()` |
| `__init__.py` | Package marker | - |

**JobStatus Enum Values**:
- `PENDING` - Awaiting processing
- `RUNNING` - Currently executing
- `COMPLETED` - Successfully finished
- `FAILED` - Error occurred
- `CANCELLED` - User cancelled

### 1.5 Infrastructure (`pulldb/infra/`)

| File | Purpose | Key Elements |
|------|---------|--------------|
| `mysql.py` | Database access | `MySQLPool`, `JobRepository`, `UserRepository`, `HostRepository`, `SettingsRepository`, `build_default_pool()` |
| `s3.py` | S3 operations | `S3Client`, `BackupSpec`, `discover_latest_backup()`, `parse_s3_bucket_path()` |
| `secrets.py` | Credential resolution | `MySQLCredentials`, `CredentialResolver`, `CredentialResolutionError` |
| `logging.py` | JSON structured logging | `JSONFormatter`, `get_logger()` |
| `metrics.py` | Observability | `MetricLabels`, `emit_counter()`, `emit_gauge()`, `emit_timer()`, `time_operation()`, `emit_event()` |
| `exec.py` | Command execution | `CommandResult`, `CommandExecutionError`, `CommandTimeoutError`, `run_command()`, `run_command_streaming()` |
| `__init__.py` | Package marker | - |

**Repository Methods (JobRepository)**:
- `create()` - Insert new job
- `get_by_id()` - Fetch single job
- `list_pending()` - Get queue
- `update_status()` - Transition state
- `add_event()` - Append event log
- `acquire_lock()` / `release_lock()` - Job locking

### 1.6 Worker Service (`pulldb/worker/`)

| File | Purpose | Key Elements |
|------|---------|--------------|
| `service.py` | Worker main | `main()`, `_build_job_repository()`, `_build_job_executor()`, `_register_signal_handlers()`, `_cleanup_zombies()` |
| `loop.py` | Poll loop | `run_poll_loop()`, `_transition_to_running()`, `_execute_job()` |
| `executor.py` | Job orchestrator | `WorkerJobExecutor`, `WorkerExecutorDependencies`, `WorkerExecutorTimeouts`, `WorkerExecutorHooks`, `extract_tar_archive()`, `derive_backup_lookup_target()` |
| `downloader.py` | S3 download | `download_backup()`, `ensure_disk_capacity()`, `_stream_download()` |
| `restore.py` | myloader execution | `RestoreWorkflowSpec`, `build_restore_workflow_spec()`, `run_myloader()`, `orchestrate_restore_workflow()`, `build_myloader_command()` |
| `staging.py` | Staging DB management | `StagingConnectionSpec`, `StagingResult`, `generate_staging_name()`, `find_orphaned_staging_databases()`, `cleanup_orphaned_staging()` |
| `atomic_rename.py` | Rename procedure | `AtomicRenameConnectionSpec`, `AtomicRenameSpec`, `atomic_rename_staging_to_target()` |
| `post_sql.py` | Post-restore SQL | `PostSQLConnectionSpec`, `PostSQLScriptResult`, `PostSQLExecutionResult`, `execute_post_sql()`, `_discover_scripts()` |
| `metadata.py` | Metadata injection | `MetadataConnectionSpec`, `MetadataSpec`, `inject_metadata_table()` |
| `metadata_synthesis.py` | Legacy backup fix | `synthesize_metadata()`, `ensure_compatible_metadata()`, `parse_filename()`, `count_rows_in_file()` |
| `log_normalizer.py` | myloader log parsing | `NormalizedLogEvent`, `normalize_myloader_line()` |
| `__init__.py` | Package marker | - |

**Worker Flow**:
1. Poll for PENDING jobs
2. Acquire lock, transition to RUNNING
3. Download backup from S3
4. Extract archive
5. Run myloader
6. Execute post-restore SQL
7. Atomic rename staging → target
8. Transition to COMPLETED

### 1.7 Binaries (`pulldb/binaries/`)

| File | Purpose |
|------|---------|
| `myloader-0.9.5` | Legacy mydumper binary |
| `myloader-0.19.3-3` | Modern mydumper binary |

### 1.8 SQL Templates

| Directory | Purpose |
|-----------|---------|
| `pulldb/template_after_sql/` | QA template post-SQL scripts |
| `customers_after_sql/` | Customer post-SQL (PII removal) |
| `qa_template_after_sql/` | QA template post-SQL |

---

## 2. Test Suite (`pulldb/tests/`)

### 2.1 Test Files

| File | Coverage Area | Key Test Classes |
|------|---------------|------------------|
| `conftest.py` | Fixtures | MySQL pool, isolated DB, credentials |
| `test_api_jobs.py` | API endpoints | `FakeUserRepository`, `FakeJobRepository` |
| `test_job_repository.py` | Job CRUD | `TestJobRepository` |
| `test_user_repository.py` | User CRUD | `TestUserRepository` |
| `test_host_repository.py` | Host CRUD | `TestHostRepository` |
| `test_settings_repository.py` | Settings CRUD | `TestSettingsRepository` |
| `test_secrets.py` | Credential resolution | `TestMySQLCredentials`, `TestCredentialResolver` |
| `test_config.py` | Config parsing | `TestMinimalFromEnv`, `TestFromEnvAndMySQL`, `TestS3BackupLocationParsing` |
| `test_config_integration.py` | Config + DB | `TestConfigIntegration` |
| `test_cli_parse.py` | CLI parsing | Argument validation tests |
| `test_cli_status.py` | Status command | Table/JSON output tests |
| `test_downloader.py` | S3 download | Disk capacity, download success/failure |
| `test_restore.py` | myloader execution | Command building, timeout handling |
| `test_restore_models.py` | MyLoaderSpec | Config application tests |
| `test_s3_discovery.py` | Backup discovery | Newest backup selection |
| `test_staging.py` | Staging management | Name generation, orphan cleanup |
| `test_atomic_rename.py` | Rename procedure | Success/failure scenarios |
| `test_atomic_rename_benchmark.py` | Performance | Benchmark validation |
| `test_atomic_rename_deploy.py` | Deployment | Dry-run, host validation |
| `test_post_sql.py` | Post-SQL execution | Script ordering, failure handling |
| `test_post_sql_execution.py` | Script execution | Size limits, read errors |
| `test_metadata_injection.py` | Metadata tables | Create/insert operations |
| `test_worker_service.py` | Worker main | Poll loop, oneshot mode |
| `test_worker_executor.py` | Job executor | Backup target derivation |
| `test_worker_failure_modes.py` | Error paths | DB errors, permission errors |
| `test_worker_log_normalizer.py` | Log parsing | Event extraction |
| `test_loop.py` | Poll loop | Job processing, backoff |
| `test_exec.py` | Command runner | Success, timeout, errors |
| `test_logging.py` | JSON logging | Formatter validation |
| `test_errors.py` | Error classes | Structure, inheritance |
| `test_atoms.py` | Atomic operations | Sanitization, parsing |
| `test_integration_*.py` | Integration | Workflow, disk, backup tests |
| `test_isolation.py` | Fixture isolation | Environment, connection tests |
| `test_installer*.py` | Installer scripts | Validation, help text |
| `test_imports.py` | Import health | Module loading |
| `test_constants.py` | Constants | Value assertions |
| `test_myloader_command.py` | Command building | Arguments validation |

### 2.2 Test Fixtures (conftest.py)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `aws_region` | session | AWS region constant |
| `aws_profile` | session | AWS profile for tests |
| `s3_aws_profile` | session | S3-specific profile |
| `coordination_db_secret` | session | Secret ID |
| `verify_secret_residency` | session | AWS validation |
| `mysql_credentials` | session | DB credentials |
| `ensure_database` | session | DB existence check |
| `mysql_pool` | session | Connection pool |
| `seed_settings` | session | Insert test settings |
| `mysql_network_credentials` | session | Network credentials |
| `isolated_mysql` | function | Isolated DB per test |
| `isolated_worker` | function | Isolated worker process |

---

## 3. Database Schema (`schema/pulldb_service/`)

| File | Order | Content |
|------|-------|---------|
| `000_auth_users.sql` | 000 | `auth_users` table |
| `010_jobs.sql` | 010 | `jobs` table with status enum |
| `020_job_events.sql` | 020 | `job_events` table |
| `030_db_hosts.sql` | 030 | `db_hosts` table |
| `040_locks.sql` | 040 | `job_locks` table |
| `050_settings.sql` | 050 | `settings` table |
| `060_active_jobs_view.sql` | 060 | `active_jobs` view |
| `200_seed_db_hosts.sql` | 200 | Default hosts seed |
| `210_seed_settings.sql` | 210 | Default settings seed |
| `300_mysql_users.sql` | 300 | User grants (api/worker/loader) |

### Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `auth_users` | Authorized users | `id`, `user_code`, `user_name`, `email` |
| `jobs` | Job queue | `id`, `user_id`, `status`, `target`, `s3_path`, `options` |
| `job_events` | Event log | `job_id`, `event_type`, `detail`, `created_at` |
| `db_hosts` | Target hosts | `id`, `hostname`, `credential_ref`, `is_default` |
| `job_locks` | Exclusive locks | `job_id`, `acquired_by`, `acquired_at` |
| `settings` | Dynamic config | `key`, `value`, `description`, `is_default` |

### MySQL Users

| User | Purpose | Permissions |
|------|---------|-------------|
| `pulldb_api` | API service | SELECT/INSERT/UPDATE on jobs, job_events, settings |
| `pulldb_worker` | Worker service | All on jobs, job_events; SELECT on db_hosts, settings |
| `pulldb_loader` | myloader restore | All privileges on target databases |

---

## 4. Scripts (`scripts/`)

### 4.1 Packaging (bundled into .deb)

| Script | Purpose |
|--------|---------|
| `install_pulldb.sh` | Main installer |
| `uninstall_pulldb.sh` | Uninstaller |
| `upgrade_pulldb.sh` | Upgrade handler |
| `configure-pulldb.sh` | Interactive configuration |
| `configure_server.sh` | Server AWS setup |
| `merge-config.sh` | Config migration |
| `monitor_jobs.py` | Job/process monitoring |
| `service-validate.sh` | Production validation |

### 4.2 Build

| Script | Purpose |
|--------|---------|
| `build_deb.sh` | Server .deb package |
| `build_client_deb.sh` | Client .deb package |

### 4.3 Infrastructure Setup

| Script | Purpose |
|--------|---------|
| `setup-aws.sh` | AWS CLI install |
| `setup-aws-credentials.sh` | AWS credential validation |
| `setup-mysql.sh` | MySQL install/config |
| `setup-test-environment.sh` | Full test env |
| `setup_test_env.sh` | Python venv only |
| `teardown-test-environment.sh` | Cleanup test env |
| `start-test-services.sh` | Start test services |

### 4.4 Validation

| Script | Purpose |
|--------|---------|
| `pulldb-validate.sh` | Validation orchestrator |
| `verify-secrets-perms.sh` | IAM/Secrets permissions |
| `verify-aws-access.py` | Cross-account S3 |

### 4.5 Operations

| Script | Purpose |
|--------|---------|
| `cleanup_dev_env.py` | Drop test databases |
| `cleanup_system.sh` | System cleanup |
| `deploy-iam-templates.sh` | IAM CLI commands |

### 4.6 Development

| Script | Purpose |
|--------|---------|
| `precommit-verify.py` | Pre-commit gates |
| `validate-knowledge-pool.py` | JSON/MD sync |
| `validate-metrics-emission.py` | Metrics test |
| `ensure_fail_hard.py` | Doc compliance |
| `benchmark_atomic_rename.py` | Performance benchmark |
| `deploy_atomic_rename.py` | Stored procedure deploy |
| `generate_cloudshell.py` | AWS CLI scripts |
| `update-engineering-dna.sh` | Submodule update |
| `audit-permissions.sh` | Permission audit |
| `ci-permissions-check.sh` | CI permission check |

### 4.7 Subdirectories

| Path | Purpose |
|------|---------|
| `scripts/lib/` | Shared shell libraries |
| `scripts/validate/` | Numbered validation phases (00-99) |
| `scripts/archived/` | Historical scripts |

---

## 5. Documentation (`docs/`)

### 5.1 Primary Docs

| File | Purpose | Status |
|------|---------|--------|
| `AWS-SETUP.md` | Comprehensive AWS setup | Canonical |
| `mysql-setup.md` | MySQL installation and config | Canonical |
| `mysql-schema.md` | Schema documentation | Canonical |
| `testing.md` | Test suite documentation | Canonical |
| `KNOWLEDGE-POOL.md` | Quick reference facts | Canonical |
| `KNOWLEDGE-POOL.json` | Machine-readable facts | Canonical |

### 5.2 Reference Docs

| File | Purpose |
|------|---------|
| `backup-formats.md` | S3 backup structure |
| `coding-standards.md` | Python/SQL style guide |
| `restore-execution.md` | Restore workflow details |
| `security-controls.md` | Security model |
| `test-environment.md` | Test env setup |

### 5.3 Design/Analysis

| File | Purpose |
|------|---------|
| `TRUTH-MATRIX.md` | Feature/behavior matrix |
| `WORKER-ATOM-EVALUATION.md` | Worker design analysis |
| `appalachian_workflow_plan.md` | Integration planning |
| `atomic_rename_procedure.sql` | Stored procedure source |
| `plan-metadata-synthesis.md` | Metadata design |
| `research-myloader-unification.md` | myloader analysis |
| `pulldb_program_flow_workbook.md` | Flow documentation |

### 5.4 Generated/Operational

| File | Purpose |
|------|---------|
| `cloudshell-commands-summary.md` | AWS CLI commands |
| `scripts-audit-report.md` | Scripts analysis |
| `drift-resolution-checklist.md` | Doc alignment |
| `vscode-diagnostics.md` | VS Code setup |

### 5.5 Subdirectories

| Path | Purpose |
|------|---------|
| `docs/archived/` | Historical docs |
| `docs/generated/` | Auto-generated content |
| `docs/policies/` | IAM policy examples |
| `docs/terraform/` | Terraform snippets |

---

## 6. Design Documents (`design/`)

| File | Purpose |
|------|---------|
| `two-service-architecture.md` | API/Worker split design |
| `system-overview.md` | High-level architecture |
| `security-model.md` | Security design |
| `configuration-map.md` | Config variable mapping |
| `staging-rename-pattern.md` | Staging DB naming |
| `implementation-notes.md` | Implementation details |
| `reference-analysis.md` | Legacy PHP analysis |
| `roadmap.md` | Feature roadmap |
| `worker_build_plan.md` | Worker implementation plan |
| `milestone-2-plan.md` | Phase 2 planning |
| `PHASE1-PLANNING.md` | Phase 1 planning |
| `restore-workflow-questionnaire.md` | Requirements gathering |
| `apptype-analysis.md` | Application type analysis |
| `engineering-dna-adoption.md` | Standards adoption |
| `runbook-failure.md` | Failure handling |
| `runbook-restore.md` | Restore procedures |

---

## 7. Copilot Instructions (`.github/`)

| File | Purpose |
|------|---------|
| `copilot-instructions.md` | Main instructions (slim) |
| `copilot-instructions-behavior.md` | AI agent behavior |
| `copilot-instructions-business-logic.md` | Domain logic |
| `copilot-instructions-python.md` | Python patterns |
| `copilot-instructions-status.md` | Progress tracking |
| `copilot-instructions-testing.md` | Test writing guide |

---

## 8. Packaging (`packaging/`)

| Path | Purpose |
|------|---------|
| `packaging/debian/` | Debian package config |
| `packaging/debian/control` | Package metadata |
| `packaging/debian/postinst` | Post-install script |
| `packaging/debian/prerm` | Pre-remove script |
| `packaging/debian/postrm` | Post-remove script |
| `packaging/debian/conffiles` | Config file list |

---

## 9. Configuration Files (Root)

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python project config |
| `setup.py` | Legacy setup script |
| `requirements.txt` | Production dependencies |
| `requirements-dev.txt` | Development dependencies |
| `requirements-test.txt` | Test dependencies |
| `Makefile` | Build automation |
| `MANIFEST.in` | Package manifest |
| `constitution.md` | Project standards |
| `README.md` | Project overview |
| `CHANGELOG.md` | Version history |

---

## 10. Environment Variables

### Required

| Variable | Service | Purpose |
|----------|---------|---------|
| `PULLDB_API_MYSQL_USER` | API | MySQL username |
| `PULLDB_WORKER_MYSQL_USER` | Worker | MySQL username |
| `PULLDB_MYSQL_HOST` | Both | MySQL host |
| `PULLDB_MYSQL_DATABASE` | Both | Database name |
| `PULLDB_WORK_DIR` | Worker | Working directory |
| `PULLDB_S3_BUCKET` | Worker | Backup bucket |
| `PULLDB_S3_PREFIX` | Worker | Backup prefix |

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `PULLDB_MYSQL_PORT` | 3306 | MySQL port |
| `PULLDB_API_HOST` | 0.0.0.0 | API bind host |
| `PULLDB_API_PORT` | 8080 | API port |
| `PULLDB_AWS_PROFILE` | None | AWS profile |
| `PULLDB_S3_AWS_PROFILE` | None | S3-specific profile |
| `PULLDB_MYLOADER_BINARY` | myloader | Binary path |
| `PULLDB_MYLOADER_THREADS` | 4 | Thread count |
| `PULLDB_LOG_LEVEL` | INFO | Logging level |

### Test Overrides

| Variable | Purpose |
|----------|---------|
| `PULLDB_TEST_MYSQL_HOST` | Test MySQL host |
| `PULLDB_TEST_MYSQL_USER` | Test MySQL user |
| `PULLDB_TEST_MYSQL_PASSWORD` | Test MySQL password |

---

## 11. AWS Resources

### Accounts

| Environment | Account ID |
|-------------|------------|
| Development | 345321506926 |
| Staging | 333204494849 |
| Production | 448509429610 |

### S3 Buckets

| Environment | Bucket | Prefix |
|-------------|--------|--------|
| Staging | `pestroutesrdsdbs` | `daily/stg/` |
| Production | `pestroutes-rds-backup-prod-vpc-us-east-1-s3` | `daily/prod/` |

### Secrets

| Secret | Purpose |
|--------|---------|
| `/pulldb/mysql/api` | API service credentials |
| `/pulldb/mysql/worker` | Worker service credentials |
| `/pulldb/mysql/loader` | myloader credentials |

### IAM Roles

| Role | Purpose |
|------|---------|
| `pulldb-ec2-service-role` | EC2 instance role |
| `pulldb-cross-account-readonly` | Cross-account access |

---

## 12. Search Tips for AI Models

### Finding by Purpose

- **Job creation**: Search `JobRepository.create`, `submit_job`, `_enqueue_job`
- **Job processing**: Search `run_poll_loop`, `_execute_job`, `WorkerJobExecutor`
- **S3 download**: Search `download_backup`, `S3Client`, `discover_latest_backup`
- **myloader**: Search `run_myloader`, `build_myloader_command`, `MyLoaderSpec`
- **Post-SQL**: Search `execute_post_sql`, `PostSQLConnectionSpec`
- **Atomic rename**: Search `atomic_rename_staging_to_target`, `AtomicRenameSpec`
- **Configuration**: Search `Config`, `from_env`, `S3BackupLocationConfig`
- **Error handling**: Search `JobExecutionError`, error class names
- **Credentials**: Search `CredentialResolver`, `MySQLCredentials`

### Finding by Pattern

- **All repository classes**: Grep `class.*Repository`
- **All error classes**: Grep `class.*Error.*Exception`
- **All specs/DTOs**: Grep `class.*Spec|class.*Result`
- **All test functions**: Grep `^def test_`
- **All fixtures**: Grep `@pytest.fixture`

### File Type Quick Access

- **Python source**: `pulldb/**/*.py` (exclude `venv/`, `tests/`)
- **Tests only**: `pulldb/tests/*.py`
- **SQL files**: `schema/**/*.sql`, `docs/*.sql`
- **Shell scripts**: `scripts/*.sh`
- **Markdown docs**: `docs/*.md`, `design/*.md`
- **Config files**: `*.toml`, `*.json`, `*.yaml`

---

## 13. Key Invariants

1. **MySQL is the only coordinator** - No Redis, no file locks
2. **Per-target exclusivity** - One job per target database at a time
3. **Download per job** - No archive reuse between jobs
4. **Staging prefix** - All staging DBs use `stg_` prefix
5. **Service-specific users** - API, Worker, Loader have separate credentials
6. **Fail hard** - Never silently degrade, always surface errors
7. **Post-SQL ordering** - Scripts execute in lexicographic order
8. **Atomic rename** - Uses stored procedure for zero-downtime swap

---

## 14. Version Information

| Component | Version |
|-----------|---------|
| Python | 3.12+ |
| mydumper/myloader | 0.9.5, 0.19.3-3 |
| MySQL | 8.0+ |
| FastAPI | 0.100+ |
| Pydantic | 2.0+ |

---

## Appendix A: Complete File Listing

### Python Modules (78 files)

```
pulldb/__init__.py
pulldb/api/__init__.py
pulldb/api/main.py
pulldb/binaries/__init__.py
pulldb/cli/__init__.py
pulldb/cli/__main__.py
pulldb/cli/main.py
pulldb/cli/parse.py
pulldb/cli/settings.py
pulldb/domain/__init__.py
pulldb/domain/config.py
pulldb/domain/errors.py
pulldb/domain/models.py
pulldb/domain/restore_models.py
pulldb/infra/__init__.py
pulldb/infra/exec.py
pulldb/infra/logging.py
pulldb/infra/metrics.py
pulldb/infra/mysql.py
pulldb/infra/s3.py
pulldb/infra/secrets.py
pulldb/worker/__init__.py
pulldb/worker/atomic_rename.py
pulldb/worker/downloader.py
pulldb/worker/executor.py
pulldb/worker/log_normalizer.py
pulldb/worker/loop.py
pulldb/worker/metadata.py
pulldb/worker/metadata_synthesis.py
pulldb/worker/post_sql.py
pulldb/worker/restore.py
pulldb/worker/service.py
pulldb/worker/staging.py
```

### Test Files (50 files in pulldb/tests/)

```
pulldb/tests/__init__.py
pulldb/tests/conftest.py
pulldb/tests/test_api_jobs.py
pulldb/tests/test_atomic_rename.py
pulldb/tests/test_atomic_rename_benchmark.py
pulldb/tests/test_atomic_rename_deploy.py
pulldb/tests/test_atoms.py
pulldb/tests/test_cli_parse.py
pulldb/tests/test_cli_status.py
pulldb/tests/test_config.py
pulldb/tests/test_config_integration.py
pulldb/tests/test_constants.py
pulldb/tests/test_downloader.py
pulldb/tests/test_errors.py
pulldb/tests/test_exec.py
pulldb/tests/test_host_repository.py
pulldb/tests/test_imports.py
pulldb/tests/test_installer.py
pulldb/tests/test_installer_help.py
pulldb/tests/test_integration_disk_insufficient.py
pulldb/tests/test_integration_missing_backup.py
pulldb/tests/test_integration_workflow.py
pulldb/tests/test_integration_workflow_disk_insufficient.py
pulldb/tests/test_integration_workflow_failures.py
pulldb/tests/test_isolation.py
pulldb/tests/test_job_repository.py
pulldb/tests/test_logging.py
pulldb/tests/test_loop.py
pulldb/tests/test_metadata_injection.py
pulldb/tests/test_myloader_command.py
pulldb/tests/test_post_sql.py
pulldb/tests/test_post_sql_execution.py
pulldb/tests/test_restore.py
pulldb/tests/test_restore_models.py
pulldb/tests/test_s3_discovery.py
pulldb/tests/test_s3_real_listing_optional.py
pulldb/tests/test_secrets.py
pulldb/tests/test_settings_repository.py
pulldb/tests/test_setup_test_env_script.py
pulldb/tests/test_staging.py
pulldb/tests/test_user_repository.py
pulldb/tests/test_worker_executor.py
pulldb/tests/test_worker_failure_modes.py
pulldb/tests/test_worker_log_normalizer.py
pulldb/tests/test_worker_service.py
```

---

*This index is designed for AI model context retrieval. For human navigation, start with `README.md` and `docs/KNOWLEDGE-POOL.md`.*
