# pullDB Workspace Index

[← Back to Documentation Index](START-HERE.md)

> **Purpose**: Comprehensive atomic-level index for AI model searching and navigation.  
> **Last Updated**: 2026-02-18  
> **Version**: 0.5.0  
> **File Count**: ~900 project files (excluding venv, .git, caches)

---

## Quick Reference

| Category | Count | Primary Path |
|----------|-------|--------------|
| Python Source | 230 | `pulldb/` |
| Tests | 177 | `pulldb/tests/`, `tests/` |
| Shell/Python Scripts | 104 | `scripts/` |
| SQL Schema | 25 | `schema/pulldb_service/` |
| Documentation | 139+ | `docs/` |
| Help Pages (HTML) | 14 | `pulldb/web/help/` |
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
| **shared** | `pulldb/auth/`, `pulldb/infra/`, `pulldb/simulation/adapters/`, `pulldb/web/shared/` | 30+ |
| **entities** | `pulldb/domain/`, `pulldb/web/entities/` | 20+ |
| **features** | `pulldb/domain/services/`, `pulldb/simulation/core/`, `pulldb/web/features/`, `pulldb/worker/` | 55+ |
| **widgets** | `pulldb/web/widgets/`, `pulldb/worker/service.py` | 15+ |
| **pages** | `pulldb/api/`, `pulldb/cli/`, `pulldb/simulation/api/`, `pulldb/web/` (top-level) | 25+ |
| **plugins** | `pulldb/binaries/` | 1 |

---

## 1. Package: `pulldb/api/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages | — |
| `auth.py` | pages | `get_api_secret()`, `get_user_for_api_key()`, `verify_signature()`, `validate_signature_timestamp()`, `get_authenticated_user()`, `get_admin_user()`, `get_manager_user()`, `get_optional_user()`, `validate_job_submission_user()` |
| `logic.py` | pages | `validate_job_request()`, `check_host_active_capacity()`, `check_concurrency_limits()`, `enqueue_job()` |
| `main.py` | pages | `create_app()`, `main()`, `main_web()`, `health()`, 56 `@app` route endpoints |
| `overlord.py` | pages | `OverlordClaimRequest`, `OverlordSyncRequest`, `OverlordReleaseRequest`, `SubdomainDuplicateEntry`, `AvailableHost`, `OverlordStateResponse`, `OverlordSyncResponse`, `OverlordReleaseResponse`, `EmployeeRecord`, `EmployeeUpdateRequest`, `create_overlord_router()` (7 route endpoints) |
| `schemas.py` | pages | `JobResponse`, `JobSummary`, `JobHistoryItem`, `JobEventResponse`, `UserLastJobResponse`, `JobMatch`, `JobResolveResponse` |
| `types.py` | pages | `APIState` |

**Total REST API endpoints**: 63 (56 in main.py + 7 in overlord.py)

## 2. Package: `pulldb/auth/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | shared | — |
| `password.py` | shared | `hash_password()`, `verify_password()`, `needs_rehash()` |
| `repository.py` | shared | `AuthRepository` — 37+ methods covering: passwords, TOTP, API keys, sessions, user-host assignments |

## 3. Package: `pulldb/cli/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages | — |
| `__main__.py` | pages | — |
| `admin.py` | pages | `cli()`, `main()` |
| `admin_commands.py` | pages | `jobs_group()`, `jobs_list()`, `jobs_cancel()`, `cleanup_cmd()`, `hosts_group()`, `hosts_list()`, `hosts_enable()`, `hosts_disable()`, `hosts_add()`, `hosts_provision()`, `hosts_test()`, `hosts_remove()`, `hosts_cred()`, `users_group()`, `users_list()`, `users_enable()`, `users_disable()`, `users_show()`, `keys_group()`, `keys_pending()`, `keys_approve()`, `keys_revoke()`, `keys_list()`, `disallow_group()`, `disallow_list()`, `disallow_add()`, `disallow_remove()`, `run_retention_cleanup_cmd()`, `overlord_group()`, `overlord_provision()`, `overlord_test()`, `overlord_deprovision()` |
| `auth.py` | pages | `get_calling_username()`, `save_credentials_to_file()`, `get_api_credentials()`, `has_api_credentials()`, `compute_request_signature()`, `get_signature_timestamp()`, `get_auth_headers()`, `get_current_username()`, 📍 HMAC authentication |
| `backup_commands.py` | pages | `CustomerBackupStats`, `backups_group()`, `backups_list()`, `backups_search()`, 📍 S3 backup analysis |
| `main.py` | pages | `UserState`, `_APIError`, 🔌 `_JobSummary`, `_JobRow`, `cli()`, `restore_cmd()`, `status_cmd()`, `search_cmd()`, `list_cmd()`, `cancel_cmd()`, `events_cmd()`, `history_cmd()`, `profile_cmd()`, `hosts_cmd()`, `register_cmd()`, `setpass_cmd()`, `main()` |
| `parse.py` | pages | `CLIParseError`, 📦 `RestoreCLIOptions`, `parse_restore_args()` |
| `secrets_commands.py` | pages | 📦 `SecretParams`, `secrets_group()`, `list_secrets()`, `get_secret()`, `set_secret()`, `delete_secret()`, `test_secret()`, `rotate_host_secret()` |
| `settings.py` | pages | `settings_group()`, `list_settings()`, `get_setting()`, `set_setting()`, `reset_setting()`, `export_settings()`, `diff_settings()`, `pull_settings()`, `push_settings()` |

## 4. Package: `pulldb/domain/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | entities | Re-exports 10 Overlord symbols via `__all__` |
| `color_schemas.py` | entities | 📦 `SurfaceColors`, `BackgroundColors`, `TextColors`, `BorderColors`, `StatusColors`, `InteractiveColors`, `InputColors`, `LinkColors`, `CodeColors`, `TableColors`, `ScrollbarColors`, `Shadows`, `ColorSchema` (13 classes); `get_preset_names()`, `get_preset()`, `get_default_schema_json()` |
| `config.py` | entities | 📦 `S3BackupLocationConfig`, `Config`; `parse_s3_bucket_path()`, `build_myloader_args_from_settings()`, `find_location_for_backup_path()`, `parse_backup_path()` |
| `errors.py` | entities | 27 error classes: `JobExecutionError`, `DownloadError`, `ExtractionError`, `DiskCapacityError`, `MyLoaderError`, `PostSQLError`, `AtomicRenameError`, `BackupValidationError`, `BackupDiscoveryError`, `MetadataInjectionError`, `TargetCollisionError`, `StagingError`, `CancellationError`, `LockedUserError`, `KeyPendingApprovalError`, `KeyRevokedError`, `EnqueueError`, `EnqueueValidationError`, `UserDisabledError`, `HostUnauthorizedError`, `JobNotFoundError`, `EnqueueBackupNotFoundError`, `DuplicateJobError`, `DatabaseProtectionError`, `JobLockedError`, `RateLimitError`, `HostUnavailableError` |
| `feature_request.py` | entities | 📊 `FeatureRequestStatus`, 📦 `FeatureRequest`, `FeatureRequestCreate`, `FeatureRequestUpdate`, `FeatureRequestVote`, `VoteInput`, `FeatureRequestStats`, `FeatureRequestNote`, `NoteCreate` |
| `interfaces.py` | entities | 9 Protocol classes: 🔌 `JobRepository`, `S3Client`, `ProcessExecutor`, `UserRepository`, `HostRepository`, `SettingsRepository`, `AuthRepository`, `DisallowedUserRepository`, `AuditRepository` |
| `models.py` | entities | 16 classes: 📊 `JobStatus`, `UserRole`, `AdminTaskType`, `AdminTaskStatus`; 📦 `User`, `Job`, `JobEvent`, `DBHost`, `Setting`, `CommandResult`, `MySQLCredentials`, `UserSummary`, `UserDetail`, `AdminTask`, `MaintenanceItems`, `DisallowedUser` |
| `naming.py` | entities | 📦 `NormalizedCustomerName`; `normalize_customer_name()`, `normalize_customer_name_simple()`, `generate_staging_name()`; constants: `HASH_SUFFIX_LEN`, `MAX_CUSTOMER_LEN`, `TRUNCATE_LEN`, `MAX_DATABASE_NAME_LENGTH`, `STAGING_SUFFIX_LENGTH`, `JOB_ID_PREFIX_LENGTH`, `MAX_TARGET_LENGTH`, `STAGING_PATTERN_TEMPLATE` |
| `overlord.py` | entities | 📊 `OverlordTrackingStatus`; 📦 `OverlordTracking`, `OverlordCompany`; `OverlordError`, `OverlordConnectionError`, `OverlordOwnershipError`, `OverlordAlreadyClaimedError`, `OverlordSafetyError`, `OverlordExternalChangeError`, `OverlordRowDeletedError` (10 classes) |
| `permissions.py` | entities | 13 functions: `can_view_job()`, `can_cancel_job()`, `can_delete_job_database()`, `can_submit_for_user()`, `can_manage_users()`, `can_manage_user()`, `can_reset_password()`, `can_reassign_user()`, `can_bulk_manage_users()`, `can_change_user_role()`, `can_manage_config()`, `can_view_all_jobs()`, `require_role()` |
| `restore_models.py` | entities | 📦 `ExtractionStats`, `MyLoaderSpec`, `MyLoaderResult`; `build_configured_myloader_spec()` |
| `schemas.py` | entities | 📦 `JobRequest` (Pydantic BaseModel) |
| `settings.py` | entities | 📊 `SettingType`, `SettingCategory`; 📦 `SettingMeta`; `SETTING_REGISTRY`; `get_setting_meta()`, `get_settings_by_category()`, `get_all_setting_keys()`, `get_known_settings_compat()` |
| `validation.py` | entities | `ValidationError`, `ValidationResult`; `DISALLOWED_USERS_HARDCODED`, `is_username_disallowed_hardcoded()`, `validate_username_format()`, `validate_username_not_disallowed()`, `is_valid_uuid()`, `validate_uuid()`, `is_valid_uuid_prefix()`, `validate_file_exists()`, `validate_executable()`, `validate_directory()`, `validate_integer()`, `validate_positive_integer()`, `validate_non_negative_integer()`, `try_create_directory()`, `validate_setting_value()` |

### domain/services/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features | Re-exports enqueue symbols |
| `discovery.py` | features | 📦 `BackupInfo`, `BackupSearchResult`, `SearchContext`, `DiscoveryService`; `format_size()` |
| `enqueue.py` | features | 🔌 `EnqueueDeps` (Protocol), 📦 `TargetResult`, `EnqueueResult`; `enqueue_job()`, `validate_job_request()`, `check_host_active_capacity()`, `check_concurrency_limits()` |
| `overlord_provisioning.py` | features | 🔌 `SettingsRepositoryProtocol`, `AuditRepositoryProtocol`; 📦 `ProvisioningStep`, `OverlordProvisioningResult`, `ConnectionTestResult`, `OverlordProvisioningService` |
| `provisioning.py` | features | 🔌 `HostRepositoryProtocol`, `AuditRepositoryProtocol`; 📦 `ProvisioningStep`, `ProvisioningResult`, `ConnectionTestResult`, `DeleteHostResult`, `HostProvisioningService` |
| `secret_rotation.py` | features | 📦 `RotationResult`; `rotate_host_secret()` |

## 5. Package: `pulldb/infra/`

The MySQL subsystem is decomposed into 8 sub-modules + 1 facade (`mysql.py`).

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | shared | — |
| `bootstrap.py` | shared | `bootstrap_service_config()` |
| `css_writer.py` | shared | `generate_semantic_tokens_css()`, `write_design_tokens()`, `sync_design_tokens_from_settings()` |
| `env_file.py` | shared | `find_env_file()`, `read_env_file()`, `read_env_value()`, `write_env_setting()` |
| `exec.py` | shared | `CommandExecutionError`, `CommandTimeoutError`, `CommandAbortedError`, `SubprocessExecutor`; `redact_sensitive_data()`, `run_command()`, `run_command_streaming()` |
| `factory.py` | shared | `get_mode()`, `is_simulation_mode()`, `get_job_repository()`, `get_s3_client()`, `get_process_executor()`, `get_auth_repository()`, `get_user_repository()`, `get_host_repository()`, `get_settings_repository()`, `get_disallowed_user_repository()`, `get_job_history_summary_repository()`, `get_audit_repository()`, `get_provisioning_service()` (13 factory functions) |
| `filter_utils.py` | shared | `parse_multi_value_filter()`, `extract_filter_params()` |
| `logging.py` | shared | `JSONFormatter`, `get_logger()` |
| `metrics.py` | shared | 📦 `MetricLabels`; `emit_counter()`, `emit_gauge()`, `emit_timer()`, `time_operation()`, `emit_event()` |
| `mysql.py` | shared | Facade — re-exports 16 symbols via `__all__`: `DictRow`, `TupleRow`, `MySQLPool`, `TypedDictCursor`, `TypedTupleCursor`, `build_default_pool`, `AdminTaskRepository`, `AuditRepository`, `DisallowedUserRepository`, `HostRepository`, `JobHistorySummaryRepository`, `JobRepository`, `SettingsRepository`, `UserRepository` |
| `mysql_admin.py` | shared | `AdminTaskRepository`, `DisallowedUserRepository` |
| `mysql_audit.py` | shared | `AuditRepository` |
| `mysql_history.py` | shared | `JobHistorySummaryRepository` |
| `mysql_hosts.py` | shared | `HostRepository` |
| `mysql_jobs.py` | shared | `JobRepository` (3473 lines) |
| `mysql_pool.py` | shared | `TypedDictCursor`, `TypedTupleCursor`, `MySQLPool`; `build_default_pool()` |
| `mysql_provisioning.py` | shared | 📦 `ProvisioningResult`; `generate_secure_password()`, `test_admin_connection()`, `create_pulldb_user()`, `create_pulldb_database()`, `deploy_stored_procedure()`, `provision_host_full()`, `sync_mysql_credentials()`, `drop_mysql_user()` |
| `mysql_settings.py` | shared | `SettingsRepository` |
| `mysql_users.py` | shared | `UserRepository` |
| `mysql_utils.py` | shared | `quote_identifier()`, `validate_identifier()`, `quote_string_literal()` |
| `overlord.py` | shared | `OverlordConnection`, `OverlordRepository`, `OverlordTrackingRepository`; re-exports 13 symbols via `__all__` including all Overlord domain types |
| `s3.py` | shared | 🔌 `S3ClientProtocol`, 📦 `BackupSpec`, `S3Client`; `discover_latest_backup()` |
| `secrets.py` | shared | `CredentialResolver`, `CredentialResolutionError`, `SecretExistsResult`, `SecretUpsertResult`; `check_secret_exists()`, `safe_upsert_single_secret()`, `delete_secret_if_new()`, `delete_secret_if_exists()`, `generate_credential_ref()`, `get_secret_path_from_alias()` |
| `timeouts.py` | shared | `get_mysql_connect_timeout_worker()`, `get_mysql_connect_timeout_api()`, `get_mysql_connect_timeout_monitor()` |

## 6. Package: `pulldb/simulation/`

### simulation/adapters/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | shared | — |
| `mock_exec.py` | shared | 📦 `MockCommandConfig`, `MockProcessExecutor` |
| `mock_mysql.py` | shared | `SimulatedJobRepository`, `SimulatedUserRepository`, `SimulatedHostRepository` |
| `mock_s3.py` | shared | `S3Error`, `MockStreamingBody`, `MockS3Client` |

### simulation/api/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages | — |
| `router.py` | pages | `SimulationStatusResponse`, `ResetResponse`, `ScenarioInfo`, `get_status()`, `reset_state()` |

### simulation/core/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features | — |
| `bus.py` | features | 📊 `EventType`, 📦 `SimulationEvent`, `SimulationEventBus`, `get_event_bus()`, `reset_event_bus()` |
| `engine.py` | features | 📦 `SimulationConfig`, `SimulationEngine` |
| `queue_runner.py` | features | 📊 `JobPhase`, 📦 `MockRunnerConfig`, `MockQueueRunner`, `get_mock_queue_runner()` |
| `scenarios.py` | features | 📊 `ScenarioType`, 📦 `ChaosConfig`, `Scenario`, `get_scenario_manager()`, `reset_scenario_manager()` |
| `seeding.py` | features | `seed_dev_users()`, `seed_dev_hosts()`, `seed_orphan_databases()` |
| `state.py` | features | 📦 `SimulationState`, `get_simulation_state()`, `reset_simulation()` |

## 7. Package: `pulldb/web/`

### web/entities/

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | entities | — |
| `css/` | entities | Component CSS files (avatar.css, etc.) |

### web/features/

| Subpackage | Files | Route Count | Key Elements |
|------------|-------|-------------|--------------|
| `admin/` | 4 files | 107 (98 routes.py + 9 overlord_routes.py) | `admin_page()`, `list_users()`, `enable_user()` + admin CRUD; `overlord_routes.py`: overlord management UI |
| `admin/theme_generator.py` | 1 | — | `generate_theme_css()`, `ensure_generated_dir()`, `write_theme_files()`, `get_theme_version()`, `ensure_theme_files_exist()` |
| `audit/` | 2 files | 3 | `audit_page()`, `get_audit_logs_api()` |
| `auth/` | 2 files | 12 | `login_page()`, `login_submit()`, `logout()` |
| `dashboard/` | 2 files | 1 | `dashboard()` |
| `jobs/` | 2 files | 21 | `jobs_page()`, `job_details()`, `cancel_job()` |
| `manager/` | 2 files | 7 | `manager_page()`, `reset_team_member_password()` |
| `mockup/` | 2 files | 1 | `job_details()` (development only) |
| `requests/` | 2 files | 10 | Feature request board routes |
| `restore/` | 2 files | 4 | `restore_page()`, `search_customers()`, `search_backups()` |

**Total Web UI routes**: 166

### web/ (top-level)

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | pages | — |
| `dependencies.py` | pages | `get_api_state()`, `get_session_user()`, `require_login()`, `CachedOverlordData` |
| `exceptions.py` | pages | `SessionExpiredError`, `PermissionDeniedError`, `ResourceNotFoundError`, `create_session_expired_handler()`, `render_error_page()` |
| `router_registry.py` | pages | Router registration |

### web/shared/

| File | Layer | Key Elements |
|------|-------|--------------|
| `contracts/page_contracts.py` | shared | 📦 `PageContext`, `ErrorPageContext`, `DashboardContext` |
| `contracts/service_contracts.py` | shared | 🔌 `AuthService`, `UserRepository`, `JobRepository` |

### web/widgets/

| Widget | Key Elements |
|--------|--------------|
| `breadcrumbs/` | 📦 `BreadcrumbItem`; `build_breadcrumbs()`, `get_breadcrumbs()` |
| `bulk_actions/` | 📊 `BulkActionType`; 📦 `BulkAction`, `BulkActionRequest`, `BulkActionResult`; `validate_bulk_action()`, `get_action_definition()` |
| `filter_bar/` | 📊 `SortOrder`; 📦 `FilterOption`, `FilterField`, `SortField`, `FilterBarConfig`, `AppliedFilters`; `get_job_status_options()`, `get_user_role_options()`, `get_filter_config()`, `filter_fields_for_role()`, `parse_filter_params()` |
| `lazy_table/` | Template-only widget |
| `searchable_dropdown/` | 📊 `SearchTriggerMode`; 📦 `SearchableDropdownOption`, `SearchableDropdownConfig`; `build_dropdown_config()` |
| `sidebar/` | Template-only widget |
| `virtual_log/` | Template-only widget |
| `virtual_table/` | Template-only widget |

## 8. Package: `pulldb/worker/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features | — |
| `admin_tasks.py` | features | `AdminTaskExecutor`; `PROTECTED_DATABASES` |
| `atomic_rename.py` | features | 📦 `AtomicRenameConnectionSpec`, `AtomicRenameSpec`; `atomic_rename_staging_to_target()`, `ensure_atomic_rename_procedure()` |
| `backup_metadata.py` | features | 📊 `MetadataFormat`; 📦 `BinlogPosition`, `TableRowEstimate`, `BackupMetadata`; `ensure_myloader_compatibility()`, `get_backup_metadata()`, `get_table_row_estimates()`, `parse_binlog_position()` |
| `cleanup.py` | features | 📦 `CleanupCandidate`, `OrphanCandidate`, `OrphanMetadata`, `CleanupResult`, `OrphanReport`, `ScheduledCleanupSummary`, `TargetProtectionResult`, `PullDBOwnerInfo`, `JobDeleteResult`, `DeleteJobResult`, `StaleRunningCleanupResult`, `UserOrphanCandidate`, `UserOrphanReport`; `is_valid_staging_name()`, `is_target_database_protected()`, `get_orphan_metadata()`, `delete_job_databases()`, `execute_stale_running_cleanup()`, `execute_delete_job()`, `detect_orphaned_databases()`, `admin_delete_orphan_databases()`, `run_scheduled_cleanup()`, `detect_user_orphaned_databases()`, `admin_delete_user_orphan_databases()` |
| `downloader.py` | features | `ensure_disk_capacity()`, `download_backup()` |
| `early_analyze.py` | features | 📦 `EarlyAnalyzeStats`; `EarlyAnalyzeWorker` |
| `executor.py` | features | 📦 `WorkerExecutorDependencies`, `WorkerExecutorTimeouts`, `WorkerExecutorHooks`; `WorkerJobExecutor`; `derive_backup_lookup_target()`, `pre_flight_verify_target_overwrite_safe()`, `build_lookup_targets_for_location()`, `extract_tar_archive()` |
| `feature_request_service.py` | features | `FeatureRequestService` (async methods: `get_stats()`, `list_requests()`, `create_request()`, `vote()`, etc.) |
| `heartbeat.py` | features | `HeartbeatThread`, `HeartbeatContext` |
| `history_backfill.py` | features | 📦 `BackfillResult`, `OrphanJob`; `HistoryBackfillTracker`; `find_orphan_jobs()`, `backfill_orphan_job()`, `run_history_backfill()`, `try_run_history_backfill()` |
| `log_normalizer.py` | features | 📦 `NormalizedLogEvent`; `normalize_myloader_line()` |
| `loop.py` | features | `get_worker_id()`, `run_poll_loop()` |
| `metadata.py` | features | 📦 `MetadataConnectionSpec`, `MetadataSpec`, `InitialMetadataSpec`; `pre_create_metadata_table()`, `update_metadata_completion()`, `inject_metadata_table()` |
| `myloader_log_parser.py` | features | 📊 `TablePhase`; 📦 `TableState`, `LogParseResult`; `MyloaderLogParser` |
| `overlord_manager.py` | features | 📊 `ReleaseAction`; 📦 `ReleaseResult`, `ExternalStateCheck`; `OverlordManager` (methods: `claim()`, `sync()`, `release()`, `verify_ownership()`) |
| `post_sql.py` | features | 📦 `PostSQLScriptResult`, `PostSQLExecutionResult`, `PostSQLConnectionSpec`; `execute_post_sql()` |
| `processlist_monitor.py` | features | 📦 `TableProgress`, `ProcesslistSnapshot`, `ProcesslistMonitorConfig`; `ProcesslistMonitor`; `poll_processlist_once()` |
| `profiling.py` | features | 📊 `RestorePhase`; 📦 `PhaseProfile`, `RestoreProfile`; `RestoreProfiler`; `parse_profile_from_event()` |
| `restore.py` | features | 📦 `RestoreWorkflowSpec`; `build_restore_workflow_spec()`, `build_myloader_command()`, `run_myloader()`, `orchestrate_restore_workflow()` |
| `restore_progress.py` | features | 📦 `TableProgressInfo`, `ThroughputStats`, `RestoreProgress`; `RestoreProgressTracker`; `create_progress_tracker()` |
| `restore_state_tracker.py` | features | 📊 `CombinedPhase`; 📦 `CombinedTableState`; `RestoreStateTracker` |
| `retention.py` | features | 📦 `RetentionCleanupResult`, `MaintenanceAction`; `RetentionService` |
| `service.py` | widgets | `main()` — worker entry point |
| `staging.py` | features | 📦 `StagingConnectionSpec`, `StagingResult`; `generate_staging_name()` (re-export from domain), `find_orphaned_staging_databases()`, `cleanup_orphaned_staging()` |
| `table_analyzer.py` | features | 📊 `AnalyzeStatus`; 📦 `AnalyzeResult`, `AnalyzeBatchResult`; `analyze_table()`, `analyze_tables()`, `analyze_database_tables()` |

## 9. Package: `pulldb/audit/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | features | Package exports |
| `__main__.py` | features | `main()` — CLI entry point for audits |
| `agent.py` | features | `DocumentationAuditAgent` |
| `analyzers.py` | features | `ExtractedFact`, `BaseAnalyzer`, `PythonAnalyzer`, `CSSAnalyzer`, `JavaScriptAnalyzer`, `SQLAnalyzer`, `FileCountAnalyzer`; `get_analyzer()` |
| `drift.py` | features | 📊 `DriftType`; 📦 `DriftAlert`; `DriftDetector` |
| `inventory.py` | features | 📊 `FileCategory`; 📦 `FileInventoryItem`; `FileInventory` |
| `knowledge_pool.py` | features | `DocumentedFact`, `KnowledgePoolParser`, `KnowledgePoolUpdater` |
| `mappings.py` | features | `DocCodeMapping`; `get_mappings_for_file()`, `get_mappings_by_section()`, `get_all_mappings()` |
| `report.py` | features | 📊 `FindingSeverity`; 📦 `AuditFinding`, `AuditReport` |

## 10. Package: `pulldb/binaries/`

| File | Layer | Key Elements |
|------|-------|--------------|
| `__init__.py` | plugins | — |

---

## 11. Help Documentation & Screenshots

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

## Database Schema

Schema files are organized in `schema/pulldb_service/` subdirectories:

### Tables (`00_tables/`) — 17 files

| File | Table |
|------|-------|
| `001_auth_users.sql` | `auth_users` - User accounts with RBAC |
| `002_auth_credentials.sql` | `auth_credentials` - Passwords and TOTP |
| `003_sessions.sql` | `sessions` - Web sessions |
| `004_api_keys.sql` | `api_keys` - API keys with approval workflow |
| `010_db_hosts.sql` | `db_hosts` - Target database hosts |
| `011_user_hosts.sql` | `user_hosts` - Host access assignments |
| `020_jobs.sql` | `jobs` - Restore job queue |
| `021_job_events.sql` | `job_events` - Job event log |
| `022_job_events_offset_index.sql` | Index on `job_events` for offset-based pagination |
| `022_job_history_summary.sql` | `job_history_summary` - Materialized job history |
| `030_locks.sql` | `locks` - Distributed locking |
| `031_settings.sql` | `settings` - Application settings |
| `040_admin_tasks.sql` | `admin_tasks` - Background admin tasks |
| `041_audit_logs.sql` | `audit_logs` - Admin action audit trail |
| `042_procedure_deployments.sql` | `procedure_deployments` - Stored proc tracking |
| `050_disallowed_users.sql` | `disallowed_users` - Username blacklist |
| `060_feature_requests.sql` | `feature_requests`, `feature_request_votes`, `feature_request_notes` |
| `099_schema_migrations.sql` | `schema_migrations` - Migration tracking |

### Views (`01_views/`) — 1 file

| File | View |
|------|------|
| `001_active_jobs_view.sql` | `active_jobs` - Queued/running/deployed jobs |

### Seed Data (`02_seed/`) — 5 files

| File | Purpose |
|------|---------|
| `001_seed_db_hosts.sql` | Default database hosts |
| `002_seed_admin_account.sql` | Admin user creation |
| `003_seed_service_account.sql` | Service account (pulldb_service) |
| `004_seed_settings.sql` | Default settings values |
| `005_seed_disallowed_users.sql` | Hardcoded blocked usernames |

### MySQL Users (`03_users/`) — 1 file

| File | Purpose |
|------|---------|
| `001_mysql_users.sql` | GRANT statements for api, worker, loader users |

**Total SQL files**: 25

---

## Known HCA Violations (Technical Debt Baseline)

Established: 2025-12-12

| File | Violation | Detail |
|------|-----------|--------|
| `pulldb/infra/exec.py` | upward_import | Imports 'pulldb.domain.models' (entities) from shared |
| `pulldb/infra/factory.py` | upward_import | Imports 'pulldb.domain.interfaces' (entities) from shared |
| `pulldb/infra/mysql.py` | upward_import | Imports 'pulldb.domain.models' (entities) from shared |
| `pulldb/infra/s3.py` | upward_import | Imports 'pulldb.domain.errors' (entities) from shared |
| `pulldb/infra/secrets.py` | upward_import | Imports 'pulldb.domain.models' (entities) from shared |
| `pulldb/simulation/adapters/*` | upward_import | Imports from entities and features layers |
| `pulldb/web/features/*/routes.py` | upward_import | Imports 'pulldb.web.dependencies' (pages) from features layer |
| `pulldb/web/features/restore/routes.py` | upward_import | Imports 'pulldb.api.logic' and 'pulldb.api.schemas' (pages) from features |

---

## Search Patterns

| Topic | Search Terms |
|-------|--------------|
| Authentication | `AuthRepository`, `hash_password`, `verify_password`, `get_authenticated_user` |
| RBAC | `permissions.py`, `can_cancel_job`, `UserRole`, `require_role` |
| Job Creation | `enqueue_job`, `validate_job_request`, `EnqueueDeps` |
| Job Processing | `run_poll_loop`, `WorkerJobExecutor`, `HeartbeatThread` |
| S3 Download | `download_backup`, `S3Client`, `discover_latest_backup` |
| myloader | `run_myloader`, `build_myloader_command`, `MyLoaderSpec`, `MyloaderLogParser` |
| Staging | `generate_staging_name`, `cleanup_orphaned_staging`, `StagingResult` |
| Atomic Rename | `atomic_rename_staging_to_target`, `AtomicRenameSpec` |
| Simulation | `SimulatedJobRepository`, `SimulationEngine`, `ScenarioManager` |
| Web UI | `router_registry`, `dependencies.py`, `templates/` |
| Overlord | `OverlordManager`, `OverlordRepository`, `overlord_routes.py` |
| Cleanup | `cleanup.py`, `detect_orphaned_databases`, `run_scheduled_cleanup` |
| Profiling | `RestoreProfiler`, `parse_profile_from_event`, `RestorePhase` |
| Feature Requests | `FeatureRequestService`, `feature_request.py` |

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

*Generated on 2026-02-18*

**Remember to update the README.md badge when regenerating!**
Badge date: `2026-02-18`
