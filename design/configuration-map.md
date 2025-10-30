# Configuration Map

This guide captures where configuration values live, how they flow into the CLI and daemon, and how they connect to MySQL `settings` entries.

## Sources

1. **Environment Variables**
   - `PULLDB_ENV`: environment label (dev, staging, prod).
   - `PULLDB_MYSQL_HOST`: MySQL coordination database host.
   - `PULLDB_MYSQL_USER`: MySQL coordination database username.
   - `PULLDB_MYSQL_PASSWORD`: MySQL coordination database password.
   - `PULLDB_MYSQL_DATABASE`: MySQL coordination database name.
   - `PULLDB_S3_BUCKET`: default backup bucket.
   - `PULLDB_S3_PREFIX`: base prefix (`daily/prod`).
   - `PULLDB_DEFAULT_DBHOST`: default MySQL host for restores.
   - `PULLDB_WORKDIR`: filesystem workspace for extractions.
2. **Secrets Manager / SSM**
   - MySQL service account credentials (username/password per host).
   - Datadog API key or stats endpoint tokens.
3. **Configuration Files (Optional)**
   - `config/<env>.yaml` may map host-specific overrides (max DB counts, credential refs). Parsed by the daemon on startup.

## MySQL Settings Table

Key-value pairs stored in `settings` provide operational overrides that both CLI and daemon read at runtime.

| Key | Description | Source |
| --- | --- | --- |
| `default_dbhost` | Canonical host when `dbhost=` absent. | Derived from `PULLDB_DEFAULT_DBHOST` or config file. |
| `extraction_directory` | Absolute path for temp restore workspace. | `PULLDB_WORKDIR` or config file. |
| `s3_bucket` | Backup bucket name. | `PULLDB_S3_BUCKET`. |
| `s3_prefix` | Bucket prefix for lookup. | `PULLDB_S3_PREFIX`. |
| `customers_after_sql_dir` | Directory containing post-restore SQL files for customer databases. | Config file entry. |
| `qa_template_after_sql_dir` | Directory containing post-restore SQL files for QA template databases. | Config file entry. |
| `history_retention_days` | Reserved for future cleanup loops. | Config file or default constant. |

Populate defaults during migrations; allow environment overrides on startup.

## Flow

1. Process-level environment variables bootstrap CLI/daemon.
2. Daemon reads optional YAML configuration; merges with environment.
3. Effective configuration updates MySQL `settings` during migration or first run.
4. CLI consults MySQL for dynamic values (e.g., default host) while remaining mostly environment-driven.

## Security Considerations

- Never store secrets directly in MySQL `settings`—store references (e.g., SSM parameter names) instead.
- Enforce proper MySQL user permissions and access controls.
- Rotate credentials out of band; update references and verify through integration tests.
