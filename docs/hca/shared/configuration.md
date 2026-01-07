# pullDB Configuration Reference

> Complete reference of all configurable variables organized by HCA layer.
> **Version**: 1.0.0 | **Updated**: January 2026

---

## Configuration Hierarchy

pullDB uses a **three-tier configuration hierarchy** with clear precedence:

```
┌─────────────────────────────────────────────────────┐
│ 1. ENVIRONMENT VARIABLES (highest priority)        │
│    Set via shell, .env file, or systemd            │
├─────────────────────────────────────────────────────┤
│ 2. MySQL SETTINGS TABLE                            │
│    Stored in pulldb_service.settings               │
├─────────────────────────────────────────────────────┤
│ 3. CODE DEFAULTS (lowest priority)                 │
│    Hardcoded in pulldb/domain/config.py            │
└─────────────────────────────────────────────────────┘
```

**Precedence Rule**: Environment variables always override MySQL settings, which override code defaults.

---

## Shared Layer (Infrastructure)

> Code location: `pulldb/infra/`
> These variables configure infrastructure connections.

### MySQL Coordination Database

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_MYSQL_HOST` | env | `localhost` | MySQL server hostname |
| `PULLDB_MYSQL_PORT` | env | `3306` | MySQL server port |
| `PULLDB_MYSQL_DATABASE` | env | `pulldb_service` | Coordination database name |
| `PULLDB_MYSQL_SOCKET` | env | (none) | Unix socket path (overrides host/port) |
| `PULLDB_MYSQL_PASSWORD` | env | (empty) | MySQL password (prefer Secrets Manager) |
| `PULLDB_API_MYSQL_USER` | env | (required) | MySQL user for API service |
| `PULLDB_WORKER_MYSQL_USER` | env | (required) | MySQL user for Worker service |

### AWS Authentication

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_AWS_PROFILE` | env | (default chain) | AWS CLI profile for Secrets Manager |
| `PULLDB_AWS_REGION` | env | `us-east-1` | AWS region for API calls |
| `AWS_DEFAULT_REGION` | env | `us-east-1` | Fallback AWS region |
| `AWS_PROFILE` | env | (default chain) | Standard AWS profile variable |
| `AWS_CONFIG_FILE` | env | `~/.aws/config` | AWS config file location |

### Secrets Manager Credentials

| Secret Path | Format | Fields | Description |
|-------------|--------|--------|-------------|
| `/pulldb/mysql/coordination-db` | JSON | `host`, `password` | Main coordination DB credentials |
| `/pulldb/mysql/{dbhost}` | JSON | `host`, `password`, `port` | Target DB host credentials |

**Credential Reference Format:**
```bash
# Secrets Manager (recommended)
PULLDB_COORDINATION_SECRET="aws-secretsmanager:/pulldb/mysql/coordination-db"

# SSM Parameter Store (alternative)
PULLDB_COORDINATION_SECRET="aws-ssm:/pulldb/mysql/coordination-db"
```

### S3 Access

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_S3_BACKUP_LOCATIONS` | env | **required** | JSON array of S3 backup locations (see env.example) |
| `PULLDB_S3_AWS_PROFILE` | env | (uses PULLDB_AWS_PROFILE) | AWS profile for S3 operations |

### Logging & Metrics

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_LOG_LEVEL` | env | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

---

## Entities Layer (Domain Models)

> Code location: `pulldb/domain/`
> MySQL settings table stores operational configuration.

### MySQL Settings Table

**Table**: `pulldb_service.settings`

| Setting Key | Type | Default | Description |
|-------------|------|---------|-------------|
| `default_dbhost` | string | `localhost` | Default target database host |
| `s3_bucket_path` | string | (varies) | Legacy S3 bucket path (prefer PULLDB_S3_BACKUP_LOCATIONS env var) |
| `work_directory` | path | `/var/lib/pulldb/work/` | Download/extraction directory |
| `customers_after_sql_dir` | path | (code default) | Post-SQL scripts for customers |
| `qa_template_after_sql_dir` | path | (code default) | Post-SQL scripts for QA templates |
| `max_active_jobs_per_user` | int | `0` | Max concurrent jobs per user (0=unlimited) |
| `max_active_jobs_global` | int | `0` | Max concurrent jobs system-wide (0=unlimited) |
| `staging_retention_days` | int | `7` | Days before orphaned staging cleanup |
| `job_log_retention_days` | int | `30` | Days before job logs are pruned |
| `myloader_binary` | path | (code default) | myloader executable path |
| `myloader_default_args` | string | (code default) | Default myloader arguments |
| `myloader_extra_args` | string | (empty) | Additional myloader arguments |
| `myloader_timeout_seconds` | float | `7200` | myloader execution timeout |
| `myloader_threads` | int | `8` | myloader thread count |

**Query settings:**
```sql
SELECT setting_key, setting_value, description 
FROM pulldb_service.settings 
ORDER BY setting_key;
```

**Update setting:**
```sql
UPDATE pulldb_service.settings 
SET setting_value = 'new_value' 
WHERE setting_key = 'setting_name';
```

---

## Features Layer (Business Logic)

> Code location: `pulldb/worker/`
> These variables control restore operations.

### myloader Configuration

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_MYLOADER_BINARY` | env, mysql | `/opt/pulldb.service/bin/myloader-0.19.3-3` | myloader executable path |
| `PULLDB_MYLOADER_DEFAULT_ARGS` | env, mysql | (see below) | Default myloader CLI arguments |
| `PULLDB_MYLOADER_EXTRA_ARGS` | env, mysql | (empty) | Additional myloader arguments |
| `PULLDB_MYLOADER_THREADS` | env, mysql | `8` | Thread count for parallel restore |
| `PULLDB_MYLOADER_TIMEOUT_SECONDS` | env, mysql | `7200` | Maximum restore duration (seconds) |

**Default myloader arguments:**
```
--max-threads-for-post-actions=1
--rows=100000
--queries-per-transaction=5000
--optimize-keys=AFTER_IMPORT_PER_TABLE
--checksum=warn
--retry-count=20
--local-infile=TRUE
--ignore-errors=1146
--overwrite-tables
--verbose=3
--max-threads-per-table=1
```

### Working Directories

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_WORK_DIR` | env, mysql | `/mnt/data/tmp/{user}/pulldb-work` | Download/extraction directory |
| `PULLDB_CUSTOMERS_AFTER_SQL_DIR` | env, mysql | `pulldb/template_after_sql/customer` | Customer post-SQL scripts |
| `PULLDB_QA_TEMPLATE_AFTER_SQL_DIR` | env, mysql | `pulldb/template_after_sql/quality` | QA template post-SQL scripts |

### S3 Backup Discovery

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_S3_BUCKET_PATH` | env, mysql | (none) | S3 path: `s3://bucket/prefix/` |
| `PULLDB_S3_BACKUP_LOCATIONS` | env, mysql | (none) | JSON array of backup locations |
| `PULLDB_S3ENV_DEFAULT` | env | `prod` | Default S3 environment filter |

**S3 Backup Locations JSON Format:**
```json
[
  {
    "name": "production",
    "bucket_path": "s3://prod-bucket/daily/prod/",
    "format": "modern",
    "profile": "pr-prod",
    "target_aliases": {
      "acme": ["acme_prod", "acme_production"]
    }
  },
  {
    "name": "staging",
    "bucket_path": "s3://staging-bucket/daily/stg/",
    "format": "legacy",
    "profile": "pr-staging"
  }
]
```

---

## Widgets Layer (Service Orchestration)

> Code location: `pulldb/worker/service.py`, `pulldb/api/main.py`
> These variables control service behavior.

### Worker Service

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_WORKER_POLL_INTERVAL` | env | `5` | Seconds between queue polls |
| `PULLDB_COORDINATION_SECRET` | env | `aws-secretsmanager:/pulldb/mysql/coordination-db` | Credential reference |
| `PULLDB_DEFAULT_DBHOST` | env, mysql | (from settings) | Default target host |

### API Service

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_API_HOST` | env | `0.0.0.0` | API server bind address |
| `PULLDB_API_PORT` | env | `8080` | API server port |
| `PULLDB_COORDINATION_SECRET` | env | `aws-secretsmanager:/pulldb/mysql/coordination-db` | Credential reference |
| `PULLDB_AUTH_MODE` | env | `trusted` | Authentication mode |
| `PULLDB_ENABLE_WEB_UI` | env | `false` | Enable web UI routes |

### Simulation Mode

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_MODE` | env | `REAL` | Operation mode: `REAL` or `SIMULATION` |

---

## Pages Layer (User Interfaces)

> Code location: `pulldb/cli/`, `pulldb/web/`
> These variables control CLI and web behavior.

### CLI Configuration

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_API_URL` | env | `http://localhost:8080` | API endpoint URL |
| `PULLDB_API_TIMEOUT` | env | `30` | API request timeout (seconds) |
| `PULLDB_DEFAULT_DBHOST` | env | (from API) | Default target host for CLI |

---

## Plugins Layer (External Tools)

> Code location: `pulldb/binaries/`
> External tool configuration.

### myloader Binary

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `PULLDB_MYLOADER_BINARY` | env, mysql | `/opt/pulldb.service/bin/myloader-0.19.3-3` | myloader executable |

**Supported myloader versions:**
- `0.19.3-3` (default, recommended)
- `0.9.x` (legacy format support)

---

## Testing Variables

> Used only in test environments.

| Variable | Source | Description |
|----------|--------|-------------|
| `PULLDB_TEST_MYSQL_HOST` | env | Test MySQL host |
| `PULLDB_TEST_MYSQL_USER` | env | Test MySQL user |
| `PULLDB_TEST_MYSQL_PASSWORD` | env | Test MySQL password |
| `PULLDB_TEST_MYSQL_SOCKET` | env | Test MySQL socket |
| `PULLDB_TEST_MYSQL_DATABASE` | env | Test MySQL database |
| `PULLDB_INSTALLER_ALLOW_NON_ROOT` | env | Allow non-root installation |

---

## Configuration Examples

### Minimal Development Setup

```bash
# .env file
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_DATABASE=pulldb_service
PULLDB_MYSQL_PASSWORD=devpassword
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker
PULLDB_AWS_PROFILE=dev
```

### Production Setup

```bash
# /etc/pulldb/api.env
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_AWS_PROFILE=production
PULLDB_API_HOST=0.0.0.0
PULLDB_API_PORT=8080
PULLDB_AUTH_MODE=password
PULLDB_ENABLE_WEB_UI=true

# /etc/pulldb/worker.env
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db
PULLDB_WORKER_MYSQL_USER=pulldb_worker
PULLDB_AWS_PROFILE=production
PULLDB_S3_AWS_PROFILE=pr-prod
PULLDB_WORK_DIR=/var/lib/pulldb/work
```

### Secrets Manager Secret Format

```json
{
  "host": "mysql.example.com",
  "password": "secure_password_here",
  "port": 3306
}
```

---

## See Also

- [Deployment Guide](widgets/deployment.md) - Service installation
- [Admin Guide](pages/admin-guide.md) - Settings management
- [Architecture](widgets/architecture.md) - System design

---

## Configuration Management CLI

> CLI commands for managing configuration, settings, and secrets.

### Settings CLI (`pulldb-admin settings`)

Manage MySQL settings table and .env file:

```bash
# List all settings
pulldb-admin settings list

# Get a specific setting
pulldb-admin settings get myloader_threads

# Set a value (updates both MySQL and .env)
pulldb-admin settings set myloader_threads 16

# Reset to default
pulldb-admin settings reset myloader_threads

# Export settings to file
pulldb-admin settings export --format=json > settings.json

# Diff local vs database
pulldb-admin settings diff

# Sync operations
pulldb-admin settings pull    # DB → .env
pulldb-admin settings push    # .env → DB
```

### Secrets CLI (`pulldb-admin secrets`)

Manage AWS Secrets Manager credentials:

```bash
# List all pullDB secrets
pulldb-admin secrets list
pulldb-admin secrets list --prefix=/pulldb/mysql/ --json

# Get secret details
pulldb-admin secrets get /pulldb/mysql/coordination-db
pulldb-admin secrets get /pulldb/mysql/coordination-db --show-password

# Create/update secret
pulldb-admin secrets set /pulldb/mysql/myhost \
  --host=mysql.example.com \
  --password=secret123 \
  --port=3306

# Use stdin for password
echo "mypassword" | pulldb-admin secrets set /pulldb/mysql/myhost \
  --host=mysql.example.com \
  --password=-

# Test secret connectivity
pulldb-admin secrets test /pulldb/mysql/coordination-db --username=pulldb_api

# Delete secret (with recovery window)
pulldb-admin secrets delete /pulldb/mysql/old-secret
pulldb-admin secrets delete /pulldb/mysql/old-secret --force  # immediate

# Rotate host credentials (atomic MySQL + AWS update)
pulldb-admin secrets rotate-host mydb              # By alias or hostname
pulldb-admin secrets rotate-host --length 48 mydb  # Custom password length
pulldb-admin secrets rotate-host --json mydb       # JSON output for scripting
```

**Secrets JSON Format:**
```json
{
  "host": "mysql.example.com",
  "password": "secure_password",
  "port": 3306,
  "username": "optional_username"
}
```

### AWS Options

Both CLI groups support AWS profile and region options:

```bash
# Use specific AWS profile
pulldb-admin --profile=production secrets list

# Use specific region
pulldb-admin --region=us-west-2 secrets list
```

Environment variables:
- `PULLDB_AWS_PROFILE` - Default AWS profile
- `PULLDB_AWS_REGION` - Default AWS region
