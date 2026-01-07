# pullDB Workspace Index

[← Back to Documentation Index](START-HERE.md)

> **Purpose**: Comprehensive atomic-level index for AI model searching and navigation.  
> **Last Updated**: 2026-01-06  
> **Version**: 0.3.1  
> **File Count**: ~780 project files (excluding venv, .git, caches)

---

## Quick Reference

| Category | Count | Primary Path |
|----------|-------|--------------|
| Python Source | 116 | `pulldb/` |
| Tests | 597 | `pulldb/tests/`, `tests/` |
| Shell Scripts | 42 | `scripts/` |
| SQL Schema | 41 | `schema/pulldb_service/` |
| Documentation | 36+ | `docs/` |
| Help Pages (HTML) | 12 | `pulldb/web/help/` |
| Copilot Instructions | 6 | `.github/` |

---

## Architecture Overview

```
┌─────────┐    ┌─────────────┐    ┌──────────────────┐
│   CLI   │───►│ API Service │───►│ MySQL Queue      │
└─────────┘    │ (FastAPI)   │    │ (pulldb_service) │
               └─────────────┘    └────────┬─────────┘
                     │                     │
                     ▼                     ▼
              ┌─────────────┐   ┌────────────────────────┐
              │   Web UI    │   │    Worker Service      │
              │ (templates) │   │ ┌─────────┬──────────┐ │
              └─────────────┘   │ │Download │ myloader │ │
                                │ │  S3     │ restore  │ │
                                │ └─────────┴──────────┘ │
                                └────────────────────────┘
```

---

## HCA Layer Summary

| Layer | Directories | File Count |
|-------|-------------|------------|
| **shared** | `pulldb/auth/`, `pulldb/infra/`, `pulldb/simulation/adapters/` (+5 more) | 27 |
| **entities** | `pulldb/domain/`, `pulldb/web/entities/` | 13 |
| **features** | `pulldb/domain/services/`, `pulldb/simulation/core/`, `pulldb/web/features/` (+7 more) | 40 |
| **widgets** | `pulldb/web/widgets/`, `pulldb/web/widgets/breadcrumbs/`, `pulldb/web/widgets/bulk_actions/` (+7 more) | 11 |
| **pages** | `pulldb/api/`, `pulldb/cli/`, `pulldb/simulation/api/` (+1 more) | 23 |
| **plugins** | `pulldb/binaries/` | 1 |

---

## 1. Package: `pulldb/api/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages |  |
| `auth.py` | pages | `get_auth_mode()`, `get_current_user_optional()`, `authenticate_user()`, 📍 4 endpoints (+4 more) |
| `logic.py` | pages | `validate_job_request()`, `check_concurrency_limits()`, `enqueue_job()` |
| `main.py` | pages | `UserInfoResponse`, `ChangePasswordRequest`, `UserLastJobResponse`, `get_api_state()`, `health()` (+61 more) |
| `schemas.py` | pages | `JobRequest`, `JobResponse`, `JobSummary` (+3 more) |
| `types.py` | pages | `APIState` |

## 2. Package: `pulldb/auth/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | shared |  |
| `password.py` | shared | `hash_password()`, `verify_password()`, `needs_rehash()` |
| `repository.py` | shared | `AuthRepository`, 📍 5 endpoints |

## 3. Package: `pulldb/cli/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages |  |
| `__main__.py` | pages |  |
| `admin.py` | pages | `cli()`, `main()` |
| `admin_commands.py` | pages | `jobs_group()`, `jobs_list()`, `jobs_cancel()`, 📍 2 endpoints (+9 more) |
| `auth.py` | pages | `get_calling_username()`, `get_api_headers()`, `save_credentials()`, `load_credentials()`, 📍 HMAC authentication |
| `backup_commands.py` | pages | `backups_group()`, `backups_list()`, `backups_search()`, 📦 `BackupStats`, 📍 S3 backup analysis |
| `main.py` | pages | `_APIError`, 🔌 `_JobSummary`, `_JobRow`, `cli()`, `restore_cmd()` (+8 more) |
| `parse.py` | pages | `CLIParseError`, 📦 `RestoreCLIOptions`, `parse_restore_args()` |
| `secrets_commands.py` | pages | 📦 `SecretParams`, `secrets_group()`, `list_secrets()`, `get_secret()`, 📍 25 endpoints (+3 more) |
| `settings.py` | pages | `settings_group()`, `list_settings()`, `get_setting()` (+4 more) |

## 4. Package: `pulldb/domain/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | entities |  |
| `color_schemas.py` | entities | 📦 `SurfaceColors`, 📦 `BackgroundColors`, 📦 `TextColors`, 📦 `StatusColors`, 📦 `ColorSchema`, `get_preset_schemas()` |
| `config.py` | entities | 📦 `S3BackupLocationConfig`, 📦 `Config`, 📍 17 endpoints |
| `errors.py` | entities | `JobExecutionError`, `DownloadError`, `ExtractionError` (+7 more) |
| `interfaces.py` | entities | 🔌 `JobRepository`, 🔌 `AuthRepository`, 🔌 `S3Client` (+2 more) |
| `models.py` | entities | 📊 `JobStatus`, 📊 `UserRole`, 📦 `User` (+6 more) |
| `permissions.py` | entities | `can_view_job()`, `can_cancel_job()`, `can_submit_for_user()` (+7 more) |
| `restore_models.py` | entities | 📦 `MyLoaderSpec`, 📦 `MyLoaderResult`, `build_configured_myloader_spec()` |
| `settings.py` | entities | 📊 `SettingType`, 📊 `SettingCategory`, 📦 `SettingMeta`, `SETTING_REGISTRY` |
| `validation.py` | entities | `DISALLOWED_USERS_HARDCODED`, `validate_username()`, `validate_job_id()`, `is_valid_uuid()` (+3 more) |

### domain/services/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features |  |
| `discovery.py` | features | 📦 `BackupInfo`, 📦 `SearchContext`, `DiscoveryService`, 📍 6 endpoints |
| `provisioning.py` | features | 📦 `ProvisioningStep`, 📦 `ProvisioningResult`, `HostProvisioningService`, 📍 Host setup orchestration |
| `secret_rotation.py` | features | 📦 `RotationResult`, `SecretRotationService`, 📍 Atomic credential rotation |

## 5. Package: `pulldb/infra/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | shared |  |
| `bootstrap.py` | shared | `bootstrap_service_config()`, 📍 Unified service startup |
| `css_writer.py` | shared | `generate_semantic_tokens_css()`, `write_design_tokens()`, 📍 Atomic CSS file updates |
| `exec.py` | shared | `CommandExecutionError`, `CommandTimeoutError`, `SubprocessExecutor`, `run_command()`, `run_command_streaming()` |
| `factory.py` | shared | `get_mode()`, `is_simulation_mode()`, `get_job_repository()` (+3 more) |
| `filter_utils.py` | shared | `parse_multi_value_filter()`, `apply_cascading_filters()`, 📍 LazyTable filter logic |
| `logging.py` | shared | `JSONFormatter`, `get_logger()` |
| `metrics.py` | shared | 📦 `MetricLabels`, `emit_counter()`, `emit_gauge()`, `emit_timer()` (+1 more) |
| `mysql.py` | shared | `MySQLPool`, `JobRepository`, `UserRepository`, `build_default_pool()`, 📍 20 endpoints (+2 more) |
| `mysql_provisioning.py` | shared | 📦 `ProvisioningResult`, `test_admin_connection()`, `create_loader_user()`, `deploy_atomic_rename_procedure()` (+5 more) |
| `s3.py` | shared | 📦 `BackupSpec`, `S3Client`, `parse_s3_bucket_path()`, `discover_latest_backup()`, 📍 5 endpoints |
| `secrets.py` | shared | `CredentialResolver`, `CredentialResolutionError`, 📍 10 endpoints |

## 6. Package: `pulldb/simulation/`

### simulation/adapters/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | shared |  |
| `mock_exec.py` | shared | 📦 `MockCommandConfig`, `MockProcessExecutor` |
| `mock_mysql.py` | shared | `SimulatedJobRepository`, `SimulatedUserRepository`, `SimulatedHostRepository`, 📍 9 endpoints (+1 more) |
| `mock_s3.py` | shared | `S3Error`, `MockStreamingBody`, `MockS3Client` |

### simulation/api/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages |  |
| `router.py` | pages | `SimulationStatusResponse`, `ResetResponse`, `ScenarioInfo`, `get_status()`, `reset_state()` (+29 more) |

### simulation/core/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features |  |
| `bus.py` | features | 📊 `EventType`, 📦 `SimulationEvent`, `SimulationEventBus`, `get_event_bus()`, `reset_event_bus()` (+1 more) |
| `engine.py` | features | 📦 `SimulationConfig`, `SimulationEngine` |
| `queue_runner.py` | features | 📊 `JobPhase`, 📦 `MockRunnerConfig`, `MockQueueRunner`, `get_mock_queue_runner()` |
| `scenarios.py` | features | 📊 `ScenarioType`, 📦 `ChaosConfig`, 📦 `Scenario`, `get_scenario_manager()`, `reset_scenario_manager()` (+1 more) |
| `seeding.py` | features | `seed_dev_users()`, `seed_dev_hosts()`, `seed_orphan_databases()` (+3 more) |
| `state.py` | features | 📦 `SimulationState`, `get_simulation_state()`, `reset_simulation()` |

## 7. Package: `pulldb/web/`

### web/entities/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | entities |  |

### web/features/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features |  |
| `routes.py` | features | `admin_page()`, `list_users()`, `enable_user()`, 📍 40 endpoints (+25 more) |
| `theme_generator.py` | features | `generate_theme_css()`, `ensure_generated_dir()`, `write_theme_file()` |
| `routes.py` | features | `audit_page()`, `get_audit_logs_api()`, 📍 Audit log browsing |
| `routes.py` | features | `login_page()`, `login_submit()`, `logout()`, 📍 8 endpoints (+1 more) |
| `routes.py` | features | `dashboard()`, 📍 1 endpoints |
| `routes.py` | features | `jobs_page()`, `job_details()`, `cancel_job()`, 📍 3 endpoints |
| `routes.py` | features | `manager_page()`, `reset_team_member_password()`, `clear_team_member_password_reset()`, 📍 5 endpoints |
| `routes.py` | features | `restore_page()`, `search_customers()`, `search_backups()`, 📍 4 endpoints |

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages |  |
| `dependencies.py` | pages | `get_api_state()`, `get_session_user()`, `require_login()`, 📍 25 endpoints |
| `exceptions.py` | pages | `SessionExpiredError`, `PermissionDeniedError`, `ResourceNotFoundError`, `create_session_expired_handler()`, `render_error_page()` |
| `router_registry.py` | pages |  |

### web/shared/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | shared |  |
| `__init__.py` | shared |  |
| `page_contracts.py` | shared | 📦 `PageContext`, 📦 `ErrorPageContext`, 📦 `DashboardContext` (+1 more) |
| `service_contracts.py` | shared | 🔌 `AuthService`, 🔌 `UserRepository`, 🔌 `JobRepository` |
| `__init__.py` | shared |  |
| `__init__.py` | shared |  |
| `__init__.py` | shared |  |

### web/widgets/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | widgets |  |
| `__init__.py` | widgets | 📦 `BreadcrumbItem`, `build_breadcrumbs()`, `get_breadcrumbs()` |
| `__init__.py` | widgets | 📊 `BulkActionType`, 📦 `BulkAction`, 📦 `BulkActionRequest`, `validate_bulk_action()`, `get_action_definition()` (+1 more) |
| `__init__.py` | widgets | 📊 `SortOrder`, 📦 `FilterOption`, 📦 `FilterField`, `get_job_status_options()`, `get_user_role_options()` (+6 more) |
| `__init__.py` | widgets |  |
| `__init__.py` | widgets |  |
| `__init__.py` | widgets | 📊 `SearchTriggerMode`, 📦 `SearchableDropdownOption`, 📦 `SearchableDropdownConfig`, `build_dropdown_config()` |
| `__init__.py` | widgets |  |
| `__init__.py` | widgets |  |

## 8. Package: `pulldb/worker/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features |  |
| `admin_tasks.py` | features | `AdminTaskExecutor`, `PROTECTED_DATABASES`, 📍 Admin background task processing |
| `atomic_rename.py` | features | 📦 `AtomicRenameConnectionSpec`, 📦 `AtomicRenameSpec`, `atomic_rename_staging_to_target()` |
| `cleanup.py` | features | 📦 `CleanupCandidate`, 📦 `OrphanCandidate`, 📦 `OrphanMetadata`, 📦 `TargetProtectionResult`, `is_valid_staging_name()`, `is_target_database_protected()`, `get_orphan_metadata()` (+12 more) |
| `downloader.py` | features | `ensure_disk_capacity()`, `download_backup()`, 📍 2 endpoints |
| `dump_metadata.py` | features | 📦 `TableRowCount`, 📦 `DumpMetadata`, `parse_dump_metadata()`, 📍 Backup metadata parsing |
| `executor.py` | features | 📦 `WorkerExecutorDependencies`, 📦 `WorkerExecutorTimeouts`, 📦 `WorkerExecutorHooks`, `derive_backup_lookup_target()`, `build_lookup_targets_for_location()` (+2 more) |
| `log_normalizer.py` | features | 📦 `NormalizedLogEvent`, `normalize_myloader_line()` |
| `loop.py` | features | `get_worker_id()`, `run_poll_loop()` |
| `metadata.py` | features | 📦 `MetadataConnectionSpec`, 📦 `MetadataSpec`, `inject_metadata_table()` |
| `metadata_synthesis.py` | features | `parse_filename()`, `count_rows_in_file()`, `synthesize_metadata()` |
| `post_sql.py` | features | 📦 `PostSQLScriptResult`, 📦 `PostSQLExecutionResult`, 📦 `PostSQLConnectionSpec`, `execute_post_sql()` |
| `processlist_monitor.py` | features | 📦 `TableProgress`, 📦 `ProcesslistSnapshot`, `ProcesslistMonitor`, 📍 myloader progress tracking |
| `profiling.py` | features | 📊 `RestorePhase`, 📦 `PhaseProfile`, 📦 `RestoreProfile`, `parse_profile_from_event()`, 📍 11 endpoints |
| `restore.py` | features | 📦 `RestoreWorkflowSpec`, `build_restore_workflow_spec()`, `build_myloader_command()`, `run_myloader()` |
| `retention.py` | features | 📦 `RetentionCleanupResult`, 📦 `MaintenanceAction`, `RetentionService`, 📍 Database lifecycle management |
| `service.py` | widgets | `main()` |
| `staging.py` | features | 📦 `StagingConnectionSpec`, 📦 `StagingResult`, `generate_staging_name()`, `find_orphaned_staging_databases()`, `cleanup_orphaned_staging()` |

## 9. Package: `pulldb/binaries/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | plugins |  |

---

## 10. Help Documentation & Screenshots

### Scripts (`scripts/`)

| File | Purpose | Key Functions |
|------|---------|---------------|
| `capture_help_screenshots.py` | Automated Playwright screenshot capture | `capture_page_screenshots()`, `setup_scenario()`, 65 unique screenshots × 2 themes |
| `annotate_screenshots.py` | Add numbered callouts to screenshots | `annotate_image()`, `load_annotations()`, YAML-driven annotation |

### Configuration (`docs/`)

| File | Purpose |
|------|---------|
| `help-screenshot-annotations.yaml` | Annotation definitions for all 65 screenshots |
| `HELP-PAGE-INDEX.md` | Help page inventory and visual audit status |

### Help HTML Pages (`pulldb/web/help/pages/web-ui/`)

| File | Content | Screenshot Count |
|------|---------|------------------|
| `index.html` | Web UI overview, navigation guide | 4 screenshots |
| `dashboard.html` | Dashboard views by role | 5 screenshots |
| `restore.html` | 4-step restore wizard | 6 screenshots |
| `jobs.html` | Job list, filtering, details | 12 screenshots |
| `profile.html` | Account settings, API keys | 6 screenshots |
| `admin.html` | User/host/key management | 23 screenshots |
| `manager.html` | Team management for managers | 4 screenshots |

### Help Styles (`pulldb/web/help/css/`)

| File | Purpose |
|------|---------|
| `help.css` | Main help page stylesheet, responsive layout, screenshot figure styling |

### Screenshot Assets (`pulldb/web/static/help/screenshots/`)

| Directory | Count | Description |
|-----------|-------|-------------|
| `light/` | 65 | Raw light theme screenshots |
| `dark/` | 65 | Raw dark theme screenshots |
| `annotated/light/` | 62 | Annotated light screenshots (excludes error pages) |
| `annotated/dark/` | 62 | Annotated dark screenshots (excludes error pages) |
| **Total** | **254** | All screenshot files |

---

## Test Coverage Mapping

| Source Module | Test File(s) | Coverage Area |
|---------------|--------------|---------------|
| `auth.py` | `test_api_auth_integration.py`, `test_auth_repository.py` (+2) | api |
| `password.py` | `test_password.py` | auth |
| `repository.py` | `test_auth_repository.py`, `test_host_repository.py` (+6) | auth |
| `admin.py` | `test_admin.py` | cli |
| `parse.py` | `test_cli_parse.py` | cli |
| `settings.py` | `test_settings_repository.py`, `test_settings.py` | cli |
| `config.py` | `test_config.py`, `test_config_integration.py` | domain |
| `errors.py` | `test_errors.py` | domain |
| `models.py` | `test_models.py`, `test_models_role.py` (+1) | domain |
| `permissions.py` | `test_permissions.py`, `test_permissions_integration.py` | domain |
| `restore_models.py` | `test_restore_models.py` | domain |
| `discovery.py` | `test_s3_discovery.py` | domain |
| `exec.py` | `test_exec.py`, `test_post_sql_execution.py` (+3) | infra |
| `logging.py` | `test_logging.py` | infra |
| `mysql.py` | `test_mock_mysql.py` | infra |
| `s3.py` | `test_s3_discovery.py`, `test_s3_real_listing_optional.py` (+1) | infra |
| `secrets.py` | `test_secrets.py` | infra |
| `mock_exec.py` | `test_mock_exec.py` | simulation |
| `mock_mysql.py` | `test_mock_mysql.py` | simulation |
| `mock_s3.py` | `test_mock_s3.py` | simulation |
| `routes.py` | `test_web_routes.py`, `test_routes.py` | web |
| `routes.py` | `test_web_routes.py`, `test_routes.py` | web |
| `routes.py` | `test_web_routes.py`, `test_routes.py` | web |
| `routes.py` | `test_web_routes.py`, `test_routes.py` | web |
| `routes.py` | `test_web_routes.py`, `test_routes.py` | web |
| `routes.py` | `test_web_routes.py`, `test_routes.py` | web |
| `atomic_rename.py` | `test_atomic_rename.py`, `test_atomic_rename_benchmark.py` (+1) | worker |
| `cleanup.py` | `test_cleanup.py`, `test_stale_running_recovery.py` (+1) | worker |
| `downloader.py` | `test_downloader.py`, `test_downloader.py` | worker |
| `executor.py` | `test_worker_executor.py`, `test_executor.py` | worker |
| ... | (9 more mappings) | ... |

---

## Database Schema

| File | Purpose |
|------|---------|
| `00000_auth_users.sql` | auth_users |
| `00100_jobs.sql` | jobs |
| `00200_job_events.sql` | job_events |
| `00300_db_hosts.sql` | db_hosts |
| `00400_locks.sql` | locks |
| `00500_settings.sql` | settings |
| `00600_active_jobs_view.sql` | active_jobs_view |
| `00700_auth_users_role.sql` | auth_users_role |
| `00710_auth_credentials.sql` | auth_credentials |
| `00715_api_keys.sql` | api_keys (CLI registration) |
| `00720_password_reset.sql` | password_reset |
| `00720_sessions.sql` | sessions |
| `00730_manager_user_relationship.sql` | manager_user_relationship |
| `00740_audit_logs.sql` | audit_logs |
| `00750_user_hosts.sql` | user_hosts |
| `00760_job_limits.sql` | job_limits |
| `00770_admin_tasks.sql` | admin_tasks |
| `00800_job_delete_support.sql` | job_delete_support (deleting/deleted) |
| `00810_disallowed_users.sql` | disallowed_users |
| `00820_job_canceling_status.sql` | job_canceling_status (canceling) |
| `00830_database_retention.sql` | database_retention |
| `00840_retention_cleanup_task.sql` | retention_cleanup_task |
| `00850_deployed_status.sql` | deployed_status |
| `00860_active_jobs_can_cancel.sql` | active_jobs_can_cancel view |
| `00860_expired_status.sql` | expired_status |
| `00870_superseded_status.sql` | superseded_status |
| `00880_can_cancel_column.sql` | can_cancel column |
| `00890_user_locked_service_role.sql` | locked_at column + SERVICE role |
| `02000_seed_db_hosts.sql` | seed_db_hosts |
| `02040_seed_admin_account.sql` | seed admin user |
| `02050_seed_service_account.sql` | seed service account (pulldb_service) |
| `02100_seed_settings.sql` | seed_settings |
| `03000_mysql_users.sql` | mysql_users (api, worker, loader) |

---

## Known HCA Violations (Technical Debt Baseline)

Established: 2025-12-12

| File | Violation | Detail |
|------|-----------|--------|
| `pulldb/infra/exec.py` | upward_import | Imports 'pulldb.domain.models' (entities) from sha... |
| `pulldb/infra/factory.py` | upward_import | Imports 'pulldb.domain.interfaces' (entities) from... |
| `pulldb/infra/mysql.py` | upward_import | Imports 'pulldb.domain.models' (entities) from sha... |
| `pulldb/infra/s3.py` | upward_import | Imports 'pulldb.domain.errors' (entities) from sha... |
| `pulldb/infra/secrets.py` | upward_import | Imports 'pulldb.domain.models' (entities) from sha... |
| `pulldb/simulation/adapters/mock_exec.py` | upward_import | Imports 'pulldb.domain.models' (entities) from sha... |
| `pulldb/simulation/adapters/mock_exec.py` | upward_import | Imports 'pulldb.simulation.core.bus' (features) fr... |
| `pulldb/simulation/adapters/mock_exec.py` | upward_import | Imports 'pulldb.simulation.core.state' (features) ... |
| `pulldb/simulation/adapters/mock_mysql.py` | upward_import | Imports 'pulldb.domain.models' (entities) from sha... |
| `pulldb/simulation/adapters/mock_mysql.py` | upward_import | Imports 'pulldb.simulation.core.bus' (features) fr... |
| `pulldb/simulation/adapters/mock_mysql.py` | upward_import | Imports 'pulldb.simulation.core.state' (features) ... |
| `pulldb/simulation/adapters/mock_s3.py` | upward_import | Imports 'pulldb.simulation.core.bus' (features) fr... |
| `pulldb/simulation/adapters/mock_s3.py` | upward_import | Imports 'pulldb.simulation.core.state' (features) ... |
| `pulldb/web/features/admin/routes.py` | upward_import | Imports 'pulldb.web.dependencies' (pages) from fea... |
| `pulldb/web/features/auth/routes.py` | upward_import | Imports 'pulldb.web.dependencies' (pages) from fea... |
| `pulldb/web/features/dashboard/routes.py` | upward_import | Imports 'pulldb.web.dependencies' (pages) from fea... |
| `pulldb/web/features/jobs/routes.py` | upward_import | Imports 'pulldb.web.dependencies' (pages) from fea... |
| `pulldb/web/features/manager/routes.py` | upward_import | Imports 'pulldb.web.dependencies' (pages) from fea... |
| `pulldb/web/features/restore/routes.py` | upward_import | Imports 'pulldb.api.logic' (pages) from features l... |
| `pulldb/web/features/restore/routes.py` | upward_import | Imports 'pulldb.api.schemas' (pages) from features... |
| ... | 3 more violations | See JSON for full list |

---

## Search Patterns

| Topic | Search Terms |
|-------|--------------|
| Authentication | `AuthRepository`, `hash_password`, `verify_password`, `SessionManager` |
| RBAC | `permissions.py`, `check_permission`, `UserRole`, `require_permission` |
| Job Creation | `JobRepository.create`, `submit_job`, `_enqueue_job` |
| Job Processing | `run_poll_loop`, `_execute_job`, `WorkerJobExecutor` |
| S3 Download | `download_backup`, `S3Client`, `discover_latest_backup` |
| myloader | `run_myloader`, `build_myloader_command`, `MyLoaderSpec` |
| Staging | `generate_staging_name`, `cleanup_orphaned_staging`, `StagingResult` |
| Atomic Rename | `atomic_rename_staging_to_target`, `AtomicRenameSpec` |
| Simulation | `MockJobRepository`, `SimulationEngine`, `ScenarioRunner` |
| Web UI | `router_registry`, `dependencies.py`, `templates/` |

---

## Key Invariants

1. MySQL is the only coordinator
2. Per-target exclusivity (one restore per database at a time)
3. Download per job (no archive reuse)
4. Staging prefix: `stg_`
5. Service-specific MySQL users (api, worker, loader)
6. Fail hard - never silent degradation
7. Post-SQL lexicographic ordering
8. Atomic rename via stored procedure
9. HCA layer isolation (import only from same or lower layers)

---

*Generated by `scripts/generate_workspace_index.py` on 2026-01-06*

**Remember to update the README.md badge when regenerating!**
Badge date: `2026-01-06`