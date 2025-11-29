CHANGELOG
=========

Unreleased
---------
- **BREAKING**: `PULLDB_MYSQL_USER` is deprecated and no longer supported
  - Services must use per-service MySQL user environment variables:
    - `PULLDB_API_MYSQL_USER` for API service
    - `PULLDB_WORKER_MYSQL_USER` for Worker service
  - This implements least-privilege MySQL access per service component
  - See `design/mysql-user-separation.md` for full details

v0.0.7 - 2025-11-28
-------------------
- **Short Job ID Prefixes**: All CLI commands accepting job_id now support 8+ character prefixes
  - Commands updated: `status`, `cancel`, `events`, `profile`
  - New API endpoint: `GET /api/jobs/resolve/{job_id_prefix}`
  - New repository method: `JobRepository.find_jobs_by_prefix()`
  - Interactive disambiguation when multiple jobs match a prefix
  - Minimum prefix length: 8 characters
- **User Identity Display**: CLI shows username and user_code when running commands
  - New API endpoint: `GET /api/users/{username}`
  - CLI displays "User: username (code: 6char)" at startup

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
  - `worker_id` column consolidated into `010_jobs.sql` (removed `017_jobs_worker_id.sql`)
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

