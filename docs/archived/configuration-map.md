# Configuration Map

> **Context**: See `../.github/copilot-instructions.md` for configuration philosophy and `../constitution.md` for security requirements.

This guide captures where configuration values live, how they flow into the CLI and daemon, and how they connect to MySQL `settings` entries.

## Sources

1. **Environment Variables**
   - **Daemon Only**:
     - `PULLDB_MYSQL_HOST`: MySQL coordination database host (or AWS Parameter Store path starting with `/`).
     - `PULLDB_API_MYSQL_USER`: MySQL username for API service (required).
     - `PULLDB_WORKER_MYSQL_USER`: MySQL username for Worker service (required).
     - `PULLDB_MYSQL_PASSWORD`: MySQL coordination database password (or AWS Parameter Store path).
     - `PULLDB_MYSQL_DATABASE`: MySQL coordination database name (default: `pulldb_service`).
     - `PULLDB_AWS_PROFILE`: AWS profile name for S3 and Parameter Store access (required, no explicit credentials supported).
     - `PULLDB_S3_BUCKET_PATH`: S3 URI including prefix (e.g., `s3://pestroutesrdsdbs/daily/stg/` for staging, recommended for development).
     - `PULLDB_S3_STAGING_BUCKET_PATH`: S3 URI for staging backups (e.g., `s3://pestroutesrdsdbs/daily/stg/`). **Deferred feature** - will be used when multi-environment support is implemented.
     - `PULLDB_DEFAULT_DBHOST`: default MySQL host for restores.
     - `PULLDB_WORK_DIR`: filesystem workspace for extractions.
     - `PULLDB_CUSTOMERS_AFTER_SQL_DIR`: directory containing post-restore SQL scripts for customer databases.
     - `PULLDB_QA_TEMPLATE_AFTER_SQL_DIR`: directory containing post-restore SQL scripts for QA template databases.
     - `PULLDB_BACKUP_SOURCE`: Which backup environment to use (`production` or `staging`). Default: `staging` (recommended for development). **Deferred feature** - see roadmap.md.
   - **CLI Only**:
     - `PULLDB_API_URL`: Daemon REST API endpoint (e.g., `http://localhost:8080`).
     - `PULLDB_API_TIMEOUT`: HTTP request timeout in seconds (default: 30).
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

Key-value pairs stored in `settings` provide operational overrides that the daemon reads at runtime. CLI does not access MySQL directly.

| Key | Description | Source |
| --- | --- | --- |
| `default_dbhost` | Canonical host when `dbhost=` absent. | Derived from `PULLDB_DEFAULT_DBHOST` or config file. |
| `work_directory` | Absolute path for temp restore workspace. | `PULLDB_WORK_DIR`. |
| `s3_bucket_path` | S3 URI including prefix (staging recommended for dev). | `PULLDB_S3_BUCKET_PATH`. |
| `s3_staging_bucket_path` | S3 URI including prefix (staging). | `PULLDB_S3_STAGING_BUCKET_PATH`. **Deferred**. |
| `backup_source` | Which backup environment to use (`production` or `staging`). | `PULLDB_BACKUP_SOURCE`. Default: `staging`. **Deferred**. |
| `customers_after_sql_dir` | Directory containing post-restore SQL files for customer databases. | Config file entry. |
| `qa_template_after_sql_dir` | Directory containing post-restore SQL files for QA template databases. | Config file entry. |

Populate defaults during migrations; allow environment overrides on startup.

## Flow

1. **CLI**: Loads `PULLDB_API_URL` and `PULLDB_API_TIMEOUT` from environment. Makes HTTP requests to daemon API.
2. **Daemon**: Process-level environment variables bootstrap daemon on startup.
3. **Daemon**: Config class resolves Parameter Store references (values starting with `/`).
4. **Daemon**: Reads MySQL `settings` table for operational overrides on startup and periodically.

## Security Considerations

- **Never store secrets directly in .env or MySQL `settings`** — use AWS Parameter Store paths instead.
- **Profile-only authentication**: pullDB only supports AWS profiles (`PULLDB_AWS_PROFILE`), not explicit credentials.
- **Parameter Store paths**: MySQL credentials can be stored as Parameter Store references (e.g., `/pulldb/prod/mysql/password`).
- **Automatic resolution**: Config class detects paths starting with `/` and fetches actual values via boto3 SSM client.
- **IAM permissions required**: `ssm:GetParameter`, `ssm:GetParameters`, and `kms:Decrypt` (for SecureString parameters).
- **Rotate credentials**: Update Parameter Store values; restart daemon to pick up new credentials.
- Enforce proper MySQL user permissions and access controls for coordination database.
