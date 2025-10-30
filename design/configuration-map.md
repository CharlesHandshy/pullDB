# Configuration Map

> **Context**: See `../.github/copilot-instructions.md` for configuration philosophy and `../constitution.md` for security requirements.

This guide captures where configuration values live, how they flow into the CLI and daemon, and how they connect to MySQL `settings` entries.

## Sources

1. **Environment Variables**
   - `PULLDB_MYSQL_HOST`: MySQL coordination database host (or AWS Parameter Store path starting with `/`).
   - `PULLDB_MYSQL_USER`: MySQL coordination database username (or AWS Parameter Store path).
   - `PULLDB_MYSQL_PASSWORD`: MySQL coordination database password (or AWS Parameter Store path).
   - `PULLDB_MYSQL_DATABASE`: MySQL coordination database name.
   - `PULLDB_AWS_PROFILE`: AWS profile name for S3 and Parameter Store access (required, no explicit credentials supported).
   - `PULLDB_S3_BUCKET_PATH`: S3 bucket path including prefix (e.g., `pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod`).
   - `PULLDB_DEFAULT_DBHOST`: default MySQL host for restores.
   - `PULLDB_WORK_DIR`: filesystem workspace for extractions.
   - `PULLDB_CUSTOMERS_AFTER_SQL_DIR`: directory containing post-restore SQL scripts for customer databases.
   - `PULLDB_QA_TEMPLATE_AFTER_SQL_DIR`: directory containing post-restore SQL scripts for QA template databases.
2. **AWS Parameter Store** (recommended for production)
   - Values starting with `/` are automatically fetched from AWS Systems Manager Parameter Store.
   - Example: `PULLDB_MYSQL_PASSWORD=/pulldb/prod/mysql/password`
   - Supports SecureString type for encrypted storage.
   - Requires IAM permissions: `ssm:GetParameter` and `kms:Decrypt`.
3. **.env File** (local development)
   - Gitignored file containing environment variables.
   - Template available in `.env.example`.
   - Loaded automatically by `python-dotenv` in Config class.

## MySQL Settings Table

Key-value pairs stored in `settings` provide operational overrides that both CLI and daemon read at runtime.

| Key | Description | Source |
| --- | --- | --- |
| `default_dbhost` | Canonical host when `dbhost=` absent. | Derived from `PULLDB_DEFAULT_DBHOST` or config file. |
| `work_directory` | Absolute path for temp restore workspace. | `PULLDB_WORK_DIR`. |
| `s3_bucket_path` | S3 bucket path including prefix. | `PULLDB_S3_BUCKET_PATH`. |
| `customers_after_sql_dir` | Directory containing post-restore SQL files for customer databases. | Config file entry. |
| `qa_template_after_sql_dir` | Directory containing post-restore SQL files for QA template databases. | Config file entry. |

Populate defaults during migrations; allow environment overrides on startup.

## Flow

1. Process-level environment variables bootstrap CLI/daemon.
2. Config class resolves Parameter Store references (values starting with `/`).
3. Daemon reads MySQL `settings` table for operational overrides.
4. CLI consults MySQL for dynamic values (e.g., default host) while remaining environment-driven.

## Security Considerations

- **Never store secrets directly in .env or MySQL `settings`** — use AWS Parameter Store paths instead.
- **Profile-only authentication**: pullDB only supports AWS profiles (`PULLDB_AWS_PROFILE`), not explicit credentials.
- **Parameter Store paths**: MySQL credentials can be stored as Parameter Store references (e.g., `/pulldb/prod/mysql/password`).
- **Automatic resolution**: Config class detects paths starting with `/` and fetches actual values via boto3 SSM client.
- **IAM permissions required**: `ssm:GetParameter`, `ssm:GetParameters`, and `kms:Decrypt` (for SecureString parameters).
- **Rotate credentials**: Update Parameter Store values; restart daemon to pick up new credentials.
- Enforce proper MySQL user permissions and access controls for coordination database.
