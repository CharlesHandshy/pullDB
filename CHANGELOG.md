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

