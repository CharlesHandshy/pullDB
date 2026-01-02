CHANGELOG
=========

v0.2.0 - 2026-01-02
-------------------
### Real-Time Restore Progress & UI Polish

Major release bringing live per-table progress tracking, inline progress bar percentages, and comprehensive status lifecycle improvements.

### Highlights
- **Processlist Monitoring**: Live per-table progress during myloader execution via MySQL SHOW PROCESSLIST
- **Inline Progress Percentages**: Download/Restore progress bars now show % at end (matching table bars)
- **LOAD DATA Support**: Processlist monitor handles both INSERT and LOAD DATA statements
- **Database Retention Lifecycle**: Expiration, locking, extension for deployed databases
- **Cancel Safety**: Jobs locked during restore cannot be canceled (protects myloader)
- **Failed Job Cleanup**: Failed jobs release locks and become deletable

### Added
- `ProcesslistMonitor` class polls MySQL processlist for `/* Completed: XX% */` comments
- `RE_LOAD_TABLE` regex for extracting table names from `LOAD DATA` statements
- Per-table progress bars in restore UI showing individual table completion
- `rows_per_second`, `eta_seconds`, `active_threads` in restore progress events
- Database retention columns: `expires_at`, `locked_at`, `locked_by`, `db_dropped_at`
- `can_cancel` flag prevents cancellation once restore begins
- Schema migration `00830_database_retention.sql` for lifecycle tracking
- Schema migration `00860_active_jobs_can_cancel.sql` for view update

### Changed
- Progress bars use flexbox row layout with percentage inline at end
- `_calculate_restore_stats()` extracts nested processlist data from events
- `mark_job_failed()` clears lock fields so failed jobs can be deleted
- Processlist query detection requires both data operation AND completion comment
- All job SELECT queries now include `can_cancel`, `cancel_requested_at`

### Fixed
- Processlist monitor detecting queries starting with `/* Completed: XX% */` comment
- INSERT detection changed from `startswith()` to `in` check for comment prefix
- Progress bar percentage positioned inline instead of below bar

---

### Canceling Intermediate State

- **CANCELING status**: New intermediate state for jobs being canceled
- **Myloader protection**: Cancel blocked once restore starts (myloader cannot be safely interrupted)
- **Race condition fix**: Eliminates orphan myloader issues when submitting new jobs

### Added
- `CANCELING` status in JobStatus enum (between RUNNING and FAILED)
- `has_restore_started()` method in JobRepository to check if myloader began
- `mark_job_canceling()` method to transition running jobs to canceling
- Schema migration `00820_job_canceling_status.sql`:
  - Adds 'canceling' to jobs.status ENUM
  - Updates active_jobs view to include canceling jobs
  - Updates active_target_key virtual column to block new submissions
- UI badge styling for canceling status (amber/warning color)

### Changed
- Cancel endpoint logic:
  - QUEUED jobs: immediate cancellation (unchanged)
  - RUNNING + pre-restore: transitions to CANCELING, returns 202
  - RUNNING + restore started: rejects with 409 (cannot interrupt myloader)
- `has_active_jobs_for_target()` simplified - now checks queued/running/canceling (removes 30-min heuristic)
- `is_cancellation_requested()` checks both timestamp and 'canceling' status

---

### Remove Host Feature (Admin)

- **Full host removal**: Admin UI now supports permanently deleting database hosts
- **Type-to-confirm**: Users must type the host alias to confirm deletion
- **Immediate secret deletion**: AWS Secrets Manager secret deleted with `ForceDeleteWithoutRecovery`
- **Impact preview**: Shows affected users and historical job counts before deletion

### Added
- `DELETE /web/admin/hosts/{host_id}/delete` - Full host deletion endpoint
- `GET /web/admin/hosts/{host_id}/delete-preview` - Pre-deletion impact summary
- `count_users_for_host()` and `get_users_for_host()` in AuthRepository
- `hard_delete_host()` in SimulatedHostRepository for simulation mode
- Danger Zone card in host detail page with delete confirmation modal

### Changed
- Host deletion requires host to be disabled first (safety check)
- AWS secret deletion now immediate (no 7-day recovery window)

---

### Job Delete Services Fix & Status Lifecycle

- **Single delete instant**: Direct database deletion via routes (fixed signature mismatch)
- **Bulk delete queued**: Admin task with progress tracking (fixed result structure)
- **Deleting status**: New intermediate status during async bulk delete operations
- **Deleted status**: Final state after databases successfully dropped

### Added
- `DELETING` status in JobStatus enum for visibility during bulk operations
- `mark_job_deleting()` method in JobRepository
- Schema migration `00800_job_delete_support.sql` adds `deleting` to status ENUM
- `.badge-pulse` animation for visual feedback during deletion
- Unit tests for `delete_job_databases` function

### Fixed
- Single delete route signature mismatch (now passes staging_name, dbhost, host_repo)
- Bulk delete result structure alignment between worker and status polling endpoint
- Bulk delete now collects all required job fields (staging_name, dbhost, owner_user_code)

### Removed
- `jobs_old.html` orphaned template file

### User Database Orphan Detection & Hosts Command

- **User orphan detection**: Admin UI can now detect orphaned databases by user
- **Host alias support**: CLI `pulldb hosts` command shows available database hosts with aliases
- **Alias resolution**: `dbhost=<alias>` now works in restore commands, resolving to hostname

### Added
- `pulldb hosts` CLI command to list available database hosts
- `GET /api/hosts` endpoint returning enabled hosts with aliases
- Host alias resolution in job submission (`_select_dbhost` in logic.py)
- `restored_at` and `restored_by` columns in user orphan detection (from pullDB metadata table)
- `_has_pulldb_table()` check validates databases have pullDB marker before flagging as orphan

### Changed
- User orphan detection now shows "Restored" date from pullDB metadata table
- Unregistered users see only registration instructions instead of full CLI help
- CSS uses semantic design tokens for proper light/dark mode support

v0.1.0 - 2025-12-26
-------------------
### User Registration & Access Control

This release introduces self-service user registration with admin approval workflow.

### Highlights
- **Self-registration**: New `pulldb register` command for users to create accounts
- **Gated CLI access**: Unregistered users can only use `register`, `setpass`, and `--help`
- **Disabled-by-default**: New registrations require admin/manager approval
- **Removed auto-create**: Users must explicitly register before submitting jobs
- **API enhancements**: New `/api/auth/register` endpoint, extended user info response

### Added
- `pulldb register` CLI command with password setup
- `POST /api/auth/register` endpoint for self-registration
- `is_disabled` and `has_password` fields in user lookup API
- `create_user_with_code()` repository method
- CLI gating based on user registration state

### Changed
- Job submission now requires registered, enabled user (no auto-create)
- `setpass` command validates user is registered first
- Help text clarifies `user=` option is admin-only

### Security
- New accounts disabled until admin approval
- Clear separation of registered vs enabled states

v0.0.12 - 2025-12-24
--------------------
### Package & Installation Improvements

This release improves the installation experience with automatic database setup and admin user creation.

### Highlights
- **Automatic database schema**: Fresh installs create `pulldb_service` database and apply all migrations
- **Initial admin user**: Auto-generated with random 16-character password displayed at install
- **Credentials file**: Password saved to `/opt/pulldb.service/ADMIN_CREDENTIALS.txt` (root-only)
- **Web assets in wheel**: Fixed missing `web/static/**`, `web/templates/**`, `template_after_sql/**`
- **Separate API/Web ports**: API on 8080, Web UI on 8000
- **Three systemd services**: `pulldb-worker`, `pulldb-api`, `pulldb-web` all in main package

### Fixed
- Missing `__init__.py` files in `pulldb/web/features/` subdirectories
- Web templates and static files not included in wheel build

### Changed
- Consolidated webclient package into main pulldb package
- `pulldb-api` entry point now disables web routes by default (use `pulldb-web` for UI)
- Documentation updated for new installation flow

v0.0.11 - 2025-12-15
--------------------
### GUI Migration Complete (PRs 14-20)

This release completes the GUI migration project that began with v0.0.10's baseline.

### Highlights
- **~5,400 lines inline CSS** extracted to centralized `components.css`
- **HCA-compliant template organization** with Layer 2 feature styles
- **Accessibility improvements**: skip links, aria-labels, keyboard navigation
- **Component documentation**: Live styleguide at `/admin/styleguide`
- **Dark mode support**: Theme toggle with system preference detection
- **Skeleton loading states**: Shimmer animations for async content

### PR Summary
- **PR 14**: Accessibility & skip link
- **PR 15**: Audit feature with paginated log browser
- **PR 16**: JS render function CSS classes
- **PR 17**: Skeleton loading states with shimmer animation
- **PR 18**: Component documentation page (`/admin/styleguide`)
- **PR 19**: Batch style block extraction (~5,400 lines → components.css)
- **PR 20**: File cleanup & archive

### Breaking Changes
- Error templates moved: `error.html` → `features/errors/error.html`
- Migration docs deleted (preserved in git history at v0.0.10)
- `archived/web2-legacy/` deleted

### Files Changed
- `components.css`: 1,512 → 5,186 lines (HCA Layer 2 features)
- 14 templates: inline `<style>` blocks removed
- New: `features/errors/404.html` dedicated 404 template

v0.0.10 - 2025-12-15
--------------------
### Pre-GUI Migration Baseline

This release establishes a stable baseline before the GUI migration project begins.
Versions 0.0.8 and 0.0.9 were internal development iterations that were never formally
released. This release consolidates all development work since v0.0.7.

### Features
- **GUI Migration Planning**: Complete 14-PR migration plan documented in `.pulldb/gui-migration/`
  - Executive summary, architecture decisions, PR breakdown with dependencies
  - Step-by-step implementation instructions per PR
  - Testing protocol and troubleshooting guide
  - Appendices with code samples (icon macros, theme endpoint, dark mode CSS)
- **Audit Scripts**: Three new validation scripts in `scripts/`:
  - `audit_inline_svgs.py` - Finds 101 unique icons across 354 instances
  - `audit_inline_css.py` - Finds 10,193 lines inline CSS across 36 blocks
  - `validate_template_paths.py` - Enforces HCA-compliant template paths
- **E2E Tests in CI**: Playwright-based end-to-end tests now run in release workflow
  - Added `playwright` and `pytest-playwright` to test dependencies
  - Self-contained tests with simulation mode server

### Infrastructure
- **MySQL User Separation**: Per-service MySQL credentials (`PULLDB_API_MYSQL_USER`, `PULLDB_WORKER_MYSQL_USER`)
- **Debian Package Sync**: Server and client packages now at v0.0.10

v0.0.7 - 2025-11-29
-------------------
### Features
- **Multi-Location S3 Backup Support**: Configurable via `PULLDB_S3_BACKUP_LOCATIONS` JSON array
  - Worker filters S3 locations by job's `s3env` option (staging/prod)
  - CLI search command uses configured locations
  - Supports named locations with different AWS profiles
- **CLI Syntax Flexibility**: Three option styles now supported:
  - `option=value` (original)
  - `--option=value` (GNU-style)
  - `--option value` (space-separated)
- **Short Job ID Prefixes**: All CLI commands accepting job_id now support 8+ character prefixes
  - Commands updated: `status`, `cancel`, `events`, `profile`
  - New API endpoint: `GET /api/jobs/resolve/{job_id_prefix}`
  - New repository method: `JobRepository.find_jobs_by_prefix()`
  - Interactive disambiguation when multiple jobs match a prefix
- **User Identity Display**: CLI shows username and user_code when running commands
  - New API endpoint: `GET /api/users/{username}`

### Fixes
- Fixed MySQL credential resolution (username now read from secret JSON)
- Fixed duplicate return statement in parse.py `_tokenize()`
- Deployed `pulldb_atomic_rename` stored procedure

### Schema
- Consolidated schema files (removed redundant migrations)
- Schema now includes all columns in base files

### Tests
- 328 tests passing (was 310+)
- Updated test_cli_parse.py for new parser behavior
- Updated test_atoms.py for new _tokenize signature

v0.0.6 - 2025-11-28
-------------------
- **Phase 1-2 Complete**: Operational enhancements and concurrency controls
- Configurable cleanup retention via `staging_cleanup_retention_days` setting
- Cleanup metrics: `staging_databases_dropped_total`, `staging_jobs_archived_total`, `staging_cleanup_errors_total`, `staging_orphans_detected_total`
- Host aliases: `host_alias` column in db_hosts for multi-name resolution
- New HostRepository methods: `get_host_by_alias()`, `resolve_hostname()`
- Schema changes:
  - `031_db_hosts_alias.sql` - host_alias column with unique index
  - `211_seed_cleanup_retention.sql` - seeds default retention (7 days)
  - `worker_id` column consolidated into `00100_jobs.sql` (removed `017_jobs_worker_id.sql`)
- Code quality fixes from QA audit

v0.0.5 - 2025-11-28
-------------------
- **Phase 3 Complete**: Multi-daemon support with safe concurrent job claiming
- Atomic job claiming with `SELECT FOR UPDATE SKIP LOCKED`
- Worker ID tracking (`jobs.worker_id` column) for debugging
- New `claim_next_job()` method for safe concurrent operation
- Concurrent worker tests with threading validation

v0.0.2 - 2025-11-26
-------------------
- **BREAKING**: Secrets Manager/SSM secrets now only store `host` and `password`
  - `username`, `port`, `database` come from environment variables:
    - `PULLDB_API_MYSQL_USER` or `PULLDB_WORKER_MYSQL_USER` (required, per-service)
    - `PULLDB_MYSQL_PORT` (optional, default 3306)
    - `PULLDB_MYSQL_DATABASE` (optional, default `pulldb_service`)
- Dual-service architecture: separate `pulldb-api` and `pulldb-worker` services
- Updated packaging:
  - Systemd units use `EnvironmentFile` from `.env`
  - Added `env.example` and `aws.config.example` templates
  - Added `SERVICE-README.md` and `CLIENT-README.md` operation guides
  - postinst/postrm handle both services, preserve config on uninstall
- Updated test fixtures for new credential structure
- Added `.backup-config/` to .gitignore

v0.0.1 - 2025-11-03
-------------------
- Initial release baseline
  - mypy fixes for `pulldb/infra/s3.py`
  - Exposed `MyLoaderSpec.binary_path` + `build_myloader_command` helper
  - Installer help/docs: clarified `--aws-profile` & `--secret` flags
  - Added `docs/aws-quickstart.md`; expanded Debian README AWS flag guidance
  - Added `scripts/setup_test_env.sh` for reproducible test env provisioning
  - Added tests: installer help reference + test env dry-run script
  - Debian packaging: version bump to 0.0.1 / release branch created

