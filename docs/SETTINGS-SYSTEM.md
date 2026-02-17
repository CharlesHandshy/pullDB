 # pullDB Settings System — Complete Reference

> **Internal engineering document** — Deep analysis of how settings are defined,
> stored, loaded, validated, propagated, and consumed across the entire pullDB
> system. Created 2026-02-12.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Storage Layer — MySQL `settings` Table](#storage-layer)
3. [Storage Layer — `.env` File](#env-file-layer)
4. [Domain Layer — Setting Registry (Single Source of Truth)](#domain-layer)
5. [Domain Layer — Config Dataclass](#config-dataclass)
6. [Infrastructure — Repositories & Factories](#infrastructure)
7. [Bootstrap — Two-Phase Config Loading](#bootstrap)
8. [Priority Cascade (Resolution Order)](#priority-cascade)
9. [Complete Setting Catalog](#setting-catalog)
10. [CLI Interface (`pulldb-admin settings`)](#cli-interface)
11. [Web UI Interface (Admin Settings Page)](#web-ui-interface)
12. [Settings Drift Detection](#drift-detection)
13. [Validation System](#validation-system)
14. [How Settings Flow Into Myloader](#myloader-flow)
15. [How Settings Affect the Worker](#worker-usage)
16. [How Settings Affect the Web UI](#web-ui-usage)
17. [Overlord Settings (db_only Pattern)](#overlord-settings)
18. [Appearance / Theme Settings](#theme-settings)
19. [Audit Trail](#audit-trail)
20. [File Index](#file-index)
21. [Full System Audit: Good / Bad / Better / Missing / Dead](#audit)

---

## 1. Architecture Overview <a name="architecture-overview"></a>

```
┌─────────────────────  SETTING SOURCES  ──────────────────────┐
│                                                               │
│  Environment Variables     .env File        MySQL DB          │
│  (os.environ / PULLDB_*)   (key=value)     (settings table)  │
│        ↑                      ↑  ↕               ↑  ↕        │
│        │                      │  │               │  │        │
│        │              ┌───────┘  │       ┌───────┘  │        │
│        │              │  sync    │       │  sync    │        │
│        │              │  pull ↓  │       │  push ↓  │        │
│        │              │  push ↑  │       │  pull ↑  │        │
│        │              └──────────┘       └──────────┘        │
│                                                               │
└───────────────────────────────────────────────────────────────┘
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │  Config  │   │  CLI     │   │  Web UI  │
    │ dataclass│   │  manage  │   │  admin   │
    │ (runtime)│   │  CRUD    │   │  page    │
    └──────┬───┘   └──────────┘   └──────────┘
           │
    ┌──────┴───────────────────────┐
    │  Worker Service              │
    │  ├─ MyLoaderSpec builder     │
    │  ├─ Restore workflow         │
    │  ├─ Downloader               │
    │  └─ Staging lifecycle        │
    └──────────────────────────────┘
```

**Key principles:**

- **MySQL database is authoritative** — it holds the runtime overrides.
- **Environment variables provide bootstrap** — MySQL creds, AWS profile.
- **`.env` file is a convenience mirror** — kept in sync but not authoritative.
- **`SETTING_REGISTRY`** in `pulldb/domain/settings.py` is the **single source
  of truth** for setting definitions (keys, types, defaults, env var names,
  categories, validators).

---

## 2. Storage Layer — MySQL `settings` Table <a name="storage-layer"></a>

**Schema** (`schema/pulldb_service/00_tables/031_settings.sql`):

```sql
CREATE TABLE settings (
    setting_key   VARCHAR(100) PRIMARY KEY,
    setting_value TEXT NOT NULL,
    description   TEXT,
    updated_at    TIMESTAMP(6) NOT NULL
                  DEFAULT CURRENT_TIMESTAMP(6)
                  ON UPDATE CURRENT_TIMESTAMP(6)
);
```

- All values are stored as `TEXT` (stringly typed).
- Type coercion happens at read time in application code.
- `updated_at` auto-updates on every write.
- `INSERT ... ON DUPLICATE KEY UPDATE` pattern for upsert.

---

## 3. Storage Layer — `.env` File <a name="env-file-layer"></a>

**Implementation**: `pulldb/infra/env_file.py`

**Search order** (via `find_env_file()`):

| Priority | Path | Context |
|----------|------|---------|
| 1 | `PULLDB_ENV_FILE` env var | Explicit override |
| 2 | `/opt/pulldb.service/.env` | Production install |
| 3 | `<repo_root>/.env` | Development |

**Operations:**

| Function | Purpose |
|----------|---------|
| `find_env_file()` | Locate the `.env` file |
| `read_env_file(path)` | Parse all `KEY=VALUE` pairs (strips quotes) |
| `read_env_value(path, var)` | Read single var from file |
| `write_env_setting(path, var, value)` | In-place update or append |

The `.env` file uses standard `KEY=VALUE` format with `#` comments. Quoting
(single or double) is stripped on read.

---

## 4. Domain Layer — Setting Registry <a name="domain-layer"></a>

**File**: `pulldb/domain/settings.py` — HCA Layer: **entities**

### Core Types

```python
class SettingType(str, Enum):
    STRING     = "string"       # Free-form text
    INTEGER    = "integer"      # Numeric
    PATH       = "path"         # File path (must exist)
    DIRECTORY  = "directory"    # Directory path (can be created)
    EXECUTABLE = "executable"   # Must be executable file
    BOOLEAN    = "boolean"      # True/false

class SettingCategory(str, Enum):
    JOB_LIMITS  = "Job Limits"
    PATHS       = "Paths & Directories"
    MYLOADER    = "Myloader Configuration"
    S3_BACKUP   = "S3 & Backup"
    CLEANUP     = "Cleanup & Retention"
    APPEARANCE  = "Appearance"
```

### SettingMeta Dataclass

```python
@dataclass(frozen=True)
class SettingMeta:
    key: str                          # e.g., "myloader_threads"
    env_var: str                      # e.g., "PULLDB_MYLOADER_THREADS"
    default: str | None               # Built-in default
    description: str                  # Human-readable
    setting_type: SettingType         # For validation + UI rendering
    category: SettingCategory         # For UI grouping
    validators: list[str]             # Named validator functions
    db_only: bool = False             # If True, not synced to .env
```

### SETTING_REGISTRY

The **complete `dict[str, SettingMeta]`** is the canonical list. Every setting
that exists in the system MUST be registered here. This registry feeds:

- CLI `KNOWN_SETTINGS` (via `get_known_settings_compat()` backward-compat wrapper)
- Web UI settings page (categories, types, validators)
- Drift detection (env var names)
- Validation pipeline (validators list)

### Helper Functions

| Function | Returns |
|----------|---------|
| `get_setting_meta(key)` | `SettingMeta | None` |
| `get_settings_by_category()` | `dict[SettingCategory, list[SettingMeta]]` |
| `get_all_setting_keys()` | `list[str]` |
| `get_known_settings_compat()` | `dict[str, tuple[env_var, default, desc]]` (legacy) |

---

## 5. Domain Layer — Config Dataclass <a name="config-dataclass"></a>

**File**: `pulldb/domain/config.py` — HCA Layer: **entities**

`Config` is a `@dataclass(slots=True)` holding the **runtime-resolved**
configuration consumed by the worker and API services. It is NOT the same as
the settings registry — it's the **loaded, type-coerced, ready-to-use** form.

### Key Fields

| Field | Type | Default | Source |
|-------|------|---------|--------|
| `mysql_host` | `str` | — | `PULLDB_MYSQL_HOST` |
| `mysql_user` | `str` | — | Service-specific env var |
| `mysql_password` | `str` | — | AWS Secrets Manager or env |
| `mysql_database` | `str` | `"pulldb_service"` | `PULLDB_MYSQL_DATABASE` |
| `mysql_socket` | `str \| None` | `None` | `PULLDB_MYSQL_SOCKET` |
| `s3_bucket_path` | `str \| None` | — | env or DB `s3_bucket_path` |
| `aws_profile` | `str \| None` | — | `PULLDB_AWS_PROFILE` |
| `s3_aws_profile` | `str \| None` | — | `PULLDB_S3_AWS_PROFILE` |
| `default_dbhost` | `str \| None` | — | env or DB `default_dbhost` |
| `work_dir` | `Path` | `/mnt/data/tmp/<user>/pulldb-work` | env or DB `work_directory` |
| `customers_after_sql_dir` | `Path` | `pulldb/template_after_sql/customer` | env or DB |
| `qa_template_after_sql_dir` | `Path` | `pulldb/template_after_sql/quality` | env or DB |
| `myloader_binary` | `str` | `/opt/pulldb.service/bin/myloader-0.21.1-1` | env or DB |
| `myloader_default_args` | `tuple[str, ...]` | *(built from individual settings)* | DB settings or builtin |
| `myloader_extra_args` | `tuple[str, ...]` | `()` | env (deprecated) |
| `myloader_timeout_seconds` | `float` | `86400.0` | env or DB |
| `myloader_threads` | `int` | `4` | env or DB |
| `s3_backup_locations` | `tuple[S3BackupLocationConfig, ...]` | `()` | env or DB (JSON) |

### Two Loading Methods

| Method | Purpose | Phase |
|--------|---------|-------|
| `Config.minimal_from_env()` | Bootstrap from env vars only | Phase 1 |
| `Config.from_env_and_mysql(pool)` | Full load: env + MySQL settings | Phase 2 |

Both support **AWS Parameter Store references** — any value starting with `/`
is resolved via `ssm:GetParameter`.

---

## 6. Infrastructure — Repositories & Factories <a name="infrastructure"></a>

### SettingsRepository (`pulldb/infra/mysql_settings.py`)

HCA Layer: **shared**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `get_setting(key)` | `→ str \| None` | Single key lookup |
| `get(key)` | `→ str \| None` | Alias for `get_setting` |
| `get_setting_required(key)` | `→ str` (raises `ValueError`) | Must-exist lookup |
| `get_all_settings()` | `→ dict[str, str]` | All key-value pairs |
| `get_all_settings_with_metadata()` | `→ list[dict]` | Includes `description`, `updated_at` |
| `set_setting(key, value, desc?)` | `→ None` | INSERT or UPDATE |
| `delete_setting(key)` | `→ bool` | Remove from DB |
| `get_max_active_jobs_per_user()` | `→ int` | With fallback default `0` |
| `get_max_active_jobs_global()` | `→ int` | With fallback default `0` |
| `get_staging_retention_days()` | `→ int` | Default `7` |
| `get_job_log_retention_days()` | `→ int` | Default `30` |
| `get_default_retention_days()` | `→ int` | Default `7` |
| `get_max_retention_days()` | `→ int` | Default `180` |
| `get_expiring_warning_days()` | `→ int` | Default `7` |
| `get_cleanup_grace_days()` | `→ int` | Default `7` |
| `get_jobs_refresh_interval()` | `→ int` | Default `5`, clamped 0–60 |
| `get_retention_options(include_now?)` | `→ list[tuple[str, str]]` | Dropdown options |

All integer getters include **safe fallback defaults** — invalid values silently
fall back to the documented default value (defensive coding).

### Protocol (`pulldb/domain/interfaces.py`)

```python
class SettingsRepository(Protocol):
    def get_setting(self, key: str) -> str | None: ...
    def get_setting_required(self, key: str) -> str: ...
    def get_max_active_jobs_per_user(self) -> int: ...
    def get_max_active_jobs_global(self) -> int: ...
    def get_all_settings(self) -> dict[str, str]: ...
    def set_setting(self, key: str, value: str, description: str | None = None) -> None: ...
    def delete_setting(self, key: str) -> bool: ...
```

### Factory (`pulldb/infra/factory.py`)

```python
def get_settings_repository() -> SettingsRepository:
    # In simulation mode → SimulatedSettingsRepository
    # Otherwise → MySQLSettingsRepository(pool)
```

### APIState (`pulldb/api/types.py`)

The web/API application holds `settings_repo` on the `APIState` NamedTuple,
making it available to all route handlers via `Depends(get_api_state)`:

```python
class APIState(NamedTuple):
    config: Config
    pool: MySQLPool | None
    user_repo: UserRepository
    job_repo: JobRepository
    settings_repo: SettingsRepository   # ← always present
    host_repo: HostRepository
    auth_repo: AuthRepository | None
    audit_repo: AuditRepository | None
    overlord_manager: OverlordManager | None
```

---

## 7. Bootstrap — Two-Phase Config Loading <a name="bootstrap"></a>

**File**: `pulldb/infra/bootstrap.py` — Both API and Worker use this.

```
Phase 1: Config.minimal_from_env()
    └─ Reads PULLDB_MYSQL_* env vars
    └─ Reads PULLDB_AWS_PROFILE
    └─ Optionally resolves AWS Parameter Store references (values starting with /)

Phase 2: Set service-specific MySQL user
    └─ PULLDB_API_MYSQL_USER (API) or PULLDB_WORKER_MYSQL_USER (Worker)

Phase 3: Resolve AWS Secrets Manager credentials
    └─ PULLDB_COORDINATION_SECRET → host + password

Phase 4: Connect to MySQL
    └─ build_default_pool(host, user, password, database)

Phase 5: Config.from_env_and_mysql(pool)
    └─ SettingsRepository(pool).get_all_settings()
    └─ Apply MySQL overrides on top of env values
    └─ Build myloader args from individual settings
    └─ Parse S3 backup locations JSON
```

The result is a `tuple[Config, MySQLPool]` — the fully loaded config and the
connection pool.

---

## 8. Priority Cascade (Resolution Order) <a name="priority-cascade"></a>

When the system resolves the final value for a setting, it follows this
priority (highest wins):

### For `Config.from_env_and_mysql()` (runtime)

```
1. Environment variable (os.getenv)          ← HIGHEST
2. MySQL settings table (via get_all_settings)
3. Built-in default in Config dataclass      ← LOWEST
```

**Why env wins**: Environment variables represent the system operator's
explicit override. MySQL settings represent admin configuration. Defaults
are fallbacks.

### For web UI / CLI display (`_get_setting_source()`)

```
1. Database value (settings table)           ← HIGHEST
2. Environment variable
3. Default from SETTING_REGISTRY             ← LOWEST
```

**Why DB wins here**: In the UI context, database values are the
intentionally-set admin overrides. The UI shows what the admin configured.

> **Important**: These resolution orders are intentionally **different** for
> different contexts. The Config loader gives env vars priority for operational
> safety (operators can always override). The UI shows DB values as primary
> because that's where admins make explicit changes.

---

## 9. Complete Setting Catalog <a name="setting-catalog"></a>

### Myloader Configuration

| Setting Key | Env Var | Default | Type | Validators |
|-------------|---------|---------|------|------------|
| `myloader_binary` | `PULLDB_MYLOADER_BINARY` | `/opt/pulldb.service/bin/myloader-0.21.1-1` | executable | `file_exists`, `is_executable` |
| `myloader_timeout_seconds` | `PULLDB_MYLOADER_TIMEOUT_SECONDS` | `86400` | integer | `is_positive_integer` |
| `myloader_threads` | `PULLDB_MYLOADER_THREADS` | `8` | integer | `is_positive_integer` |
| `myloader_max_threads_per_table` | `PULLDB_MYLOADER_MAX_THREADS_PER_TABLE` | `1` | integer | `is_positive_integer` |
| `myloader_max_threads_index` | `PULLDB_MYLOADER_MAX_THREADS_INDEX` | `1` | integer | `is_positive_integer` |
| `myloader_max_threads_post_actions` | `PULLDB_MYLOADER_MAX_THREADS_POST_ACTIONS` | `1` | integer | `is_positive_integer` |
| `myloader_max_threads_schema` | `PULLDB_MYLOADER_MAX_THREADS_SCHEMA` | `4` | integer | `is_positive_integer` |
| `myloader_rows` | `PULLDB_MYLOADER_ROWS` | `50000` | integer | `is_non_negative_integer` |
| `myloader_queries_per_transaction` | `PULLDB_MYLOADER_QUERIES_PER_TRANSACTION` | `1000` | integer | `is_positive_integer` |
| `myloader_connection_timeout` | `PULLDB_MYLOADER_CONNECTION_TIMEOUT` | `30` | integer | `is_non_negative_integer` |
| `myloader_retry_count` | `PULLDB_MYLOADER_RETRY_COUNT` | `20` | integer | `is_positive_integer` |
| `myloader_throttle_threshold` | `PULLDB_MYLOADER_THROTTLE_THRESHOLD` | `6` | integer | `is_positive_integer` |
| `myloader_optimize_keys` | `PULLDB_MYLOADER_OPTIMIZE_KEYS` | `AFTER_IMPORT_PER_TABLE` | string | — |
| `myloader_checksum` | `PULLDB_MYLOADER_CHECKSUM` | `warn` | string | — |
| `myloader_drop_table_mode` | `PULLDB_MYLOADER_DROP_TABLE_MODE` | `DROP` | string | — |
| `myloader_verbose` | `PULLDB_MYLOADER_VERBOSE` | `3` | integer | `is_non_negative_integer` |
| `myloader_local_infile` | `PULLDB_MYLOADER_LOCAL_INFILE` | `true` | boolean | — |
| `myloader_skip_triggers` | `PULLDB_MYLOADER_SKIP_TRIGGERS` | `false` | boolean | — |
| `myloader_skip_constraints` | `PULLDB_MYLOADER_SKIP_CONSTRAINTS` | `false` | boolean | — |
| `myloader_skip_indexes` | `PULLDB_MYLOADER_SKIP_INDEXES` | `false` | boolean | — |
| `myloader_skip_post` | `PULLDB_MYLOADER_SKIP_POST` | `false` | boolean | — |
| `myloader_skip_definer` | `PULLDB_MYLOADER_SKIP_DEFINER` | `false` | boolean | — |
| `myloader_ignore_errors` | `PULLDB_MYLOADER_IGNORE_ERRORS` | `1146` | string | — |

**Note**: `myloader_connection_timeout` is **DEPRECATED** — myloader 0.20.x
does not support `--connection-timeout`. Preserved for UI compatibility only.

### Paths & Directories

| Setting Key | Env Var | Default | Type | Validators |
|-------------|---------|---------|------|------------|
| `work_directory` | `PULLDB_WORK_DIR` | `/opt/pulldb.service/work` | directory | `directory_exists`, `is_writable` |
| `customers_after_sql_dir` | `PULLDB_CUSTOMERS_AFTER_SQL_DIR` | `/opt/pulldb.service/after_sql/customer` | directory | `directory_exists` |
| `qa_template_after_sql_dir` | `PULLDB_QA_TEMPLATE_AFTER_SQL_DIR` | `/opt/pulldb.service/after_sql/quality` | directory | `directory_exists` |

### S3 & Backup

| Setting Key | Env Var | Default | Type |
|-------------|---------|---------|------|
| `default_dbhost` | `PULLDB_DEFAULT_DBHOST` | `None` | string |
| `s3_bucket_path` | `PULLDB_S3_BUCKET_PATH` | `None` | string |
| `aws_profile` | `PULLDB_AWS_PROFILE` | `pr-dev` | string |

### Job Limits

| Setting Key | Env Var | Default | Type | Validators |
|-------------|---------|---------|------|------------|
| `max_active_jobs_per_user` | `PULLDB_MAX_ACTIVE_JOBS_PER_USER` | `0` | integer | `is_non_negative_integer` |
| `max_active_jobs_global` | `PULLDB_MAX_ACTIVE_JOBS_GLOBAL` | `0` | integer | `is_non_negative_integer` |

### Cleanup & Retention

| Setting Key | Env Var | Default | Type | Validators |
|-------------|---------|---------|------|------------|
| `staging_retention_days` | `PULLDB_STAGING_RETENTION_DAYS` | `7` | integer | `is_non_negative_integer` |
| `job_log_retention_days` | `PULLDB_JOB_LOG_RETENTION_DAYS` | `30` | integer | `is_non_negative_integer` |
| `default_retention_days` | `PULLDB_DEFAULT_RETENTION_DAYS` | `7` | integer | `is_positive_integer` |
| `max_retention_days` | `PULLDB_MAX_RETENTION_DAYS` | `180` | integer | `is_positive_integer` |
| `expiring_warning_days` | `PULLDB_EXPIRING_WARNING_DAYS` | `7` | integer | `is_non_negative_integer` |
| `cleanup_grace_days` | `PULLDB_CLEANUP_GRACE_DAYS` | `7` | integer | `is_non_negative_integer` |
| `jobs_refresh_interval_seconds` | `PULLDB_JOBS_REFRESH_INTERVAL` | `5` | integer | `is_non_negative_integer` |

### Appearance

| Setting Key | Env Var | Default | Type |
|-------------|---------|---------|------|
| `light_theme_schema` | `PULLDB_LIGHT_THEME_SCHEMA` | `None` (uses preset) | string |
| `dark_theme_schema` | `PULLDB_DARK_THEME_SCHEMA` | `None` (uses preset) | string |
| `dark_mode_enabled` | `PULLDB_DARK_MODE_ENABLED` | `false` | boolean |

### Overlord Integration (db_only)

| Setting Key | Env Var | Default | Type | db_only |
|-------------|---------|---------|------|---------|
| `overlord_enabled` | `PULLDB_OVERLORD_ENABLED` | `false` | boolean | **Yes** |
| `overlord_dbhost` | `PULLDB_OVERLORD_DBHOST` | `None` | string | **Yes** |
| `overlord_database` | `PULLDB_OVERLORD_DATABASE` | `overlord` | string | **Yes** |
| `overlord_table` | `PULLDB_OVERLORD_TABLE` | `companies` | string | **Yes** |
| `overlord_credential_ref` | `PULLDB_OVERLORD_CREDENTIAL_REF` | `None` | string | **Yes** |

---

## 10. CLI Interface (`pulldb-admin settings`) <a name="cli-interface"></a>

**File**: `pulldb/cli/settings.py` — HCA Layer: **pages**

### Commands

| Command | Action | Target |
|---------|--------|--------|
| `settings list [--all]` | List all known settings with effective values and sources | Display |
| `settings get <key>` | Show value from DB, ENV, and default | Display |
| `settings set <key> <value>` | Update in **both** DB and `.env` | DB + .env |
| `settings set <key> <value> --db-only` | Update only in database | DB |
| `settings set <key> <value> --env-only` | Update only in `.env` file | .env |
| `settings reset <key>` | Delete from database (reverts to env/default) | DB |
| `settings export [--format=env\|json]` | Export all effective values | Stdout |
| `settings diff` | Compare DB values vs `.env` file values | Display |
| `settings pull [--dry-run]` | Sync database → `.env` file | .env |
| `settings push [--dry-run]` | Sync `.env` file → database | DB |

### Source Priority Display

The CLI shows three sources per setting:
- **database** — Value stored in MySQL `settings` table
- **environment** — Value from `os.environ` / `.env` file
- **default** — Built-in default from `SETTING_REGISTRY`

### Sync Operations

**`pull`** (DB → .env): Copies all DB settings to `.env`. Settings marked
`db_only=True` are **excluded** from sync.

**`push`** (.env → DB): Copies only `PULLDB_*` variables from `.env` to DB.

Both support `--dry-run` for preview and require confirmation prompts.

---

## 11. Web UI Interface (Admin Settings Page) <a name="web-ui-interface"></a>

**Routes** in `pulldb/web/features/admin/routes.py`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/web/admin/settings` | GET | List all settings grouped by category |
| `/web/admin/settings/{key}` | POST | Update a single setting |
| `/web/admin/settings/{key}` | DELETE | Reset a setting to default |
| `/web/admin/settings/{key}/validate` | POST | Validate without saving |
| `/web/admin/settings/{key}/create-directory` | POST | Create directory for path setting |
| `/web/admin/settings/sync-to-env` | POST | Sync all DB settings → .env |
| `/web/admin/settings/{key}/sync` | POST | Sync individual setting (either direction) |
| `/web/admin/settings/myloader-preview` | GET | Preview generated myloader command |
| `/web/admin/settings-sync` | GET | Settings drift notification page |

### Web Update Pattern

When a setting is updated via the web UI (`POST /settings/{key}`):

```
1. Validate value against SettingMeta.validators
2. Get old value for audit trail
3. Save to database via settings_repo.set_setting()
4. If NOT db_only: dual-write to .env file
5. If dual-write succeeds: update os.environ in-memory
6. Log to audit_repo
7. Return updated setting dict for HTMX partial render
```

The **dual-write** pattern (step 4) keeps `.env` automatically in sync when
settings are changed via the web UI, without requiring an explicit "Sync All"
action. This is a non-fatal best-effort operation — the database is
authoritative.

### Category Grouping

Settings are displayed in the UI grouped by `SettingCategory`, in this order:
1. Job Limits
2. Paths & Directories
3. Myloader Configuration
4. S3 & Backup
5. Cleanup & Retention
6. Appearance

### Deprecated Settings

These settings are hidden from the UI display:
- `myloader_default_args` — Replaced by individual `myloader_*` settings
- `myloader_extra_args` — Deprecated passthrough

---

## 12. Settings Drift Detection <a name="drift-detection"></a>

**Implementation**: `pulldb/web/features/admin/routes.py` → `get_settings_drift()`

Drift occurs when a database value differs from the corresponding environment
variable. The detection system:

1. Iterates all settings in `SETTING_REGISTRY`
2. **Skips** settings with `db_only=True` (they don't belong in `.env`)
3. **Skips** settings without a database value (nothing to drift from)
4. Compares `db_value` vs `os.getenv(meta.env_var)`
5. Reports any mismatches

**Where drift is shown**:
- Admin settings page — alerts with individual sync buttons
- Login redirect page — shown to admin users after login
- Settings drift notification page (`/web/admin/settings-sync`)

**Resolution options**:
- **Sync All to .env** — Copies all DB values into `.env` (excluding `db_only`)
- **Individual sync** — Per-setting sync in either direction
- **CLI `settings pull`** — DB → .env (production)
- **CLI `settings push`** — .env → DB (less common)

---

## 13. Validation System <a name="validation-system"></a>

**File**: `pulldb/domain/validation.py` — HCA Layer: **entities**

### ValidationResult

```python
@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None
    warning: str | None = None
    can_create: bool = False   # For directories that can be auto-created
```

### Validation Pipeline

`validate_setting_value(key, value, setting_type, validators)` runs:

1. **Type-based validation** (based on `setting_type`):
   - `integer` → Must parse as valid integer
   - `executable` → File exists + is executable (os.X_OK)
   - `directory` → Directory exists (+ can offer to create)
   - `path` → File exists

2. **Named validators** (from `SettingMeta.validators`):
   - `is_positive_integer` → int > 0
   - `is_non_negative_integer` → int >= 0
   - `file_exists` → os.path.exists + isfile
   - `is_executable` → os.access(X_OK)
   - `directory_exists` → os.path.isdir
   - `is_writable` → os.access(W_OK)

### Smart Directory Handling

If a directory doesn't exist but its parent is writable, validation returns
`can_create=True`. The web UI then offers a "Create Directory" button that calls
`POST /settings/{key}/create-directory`.

---

## 14. How Settings Flow Into Myloader <a name="myloader-flow"></a>

This is one of the most important flows — individual settings get assembled
into the myloader command line used for every restore.

### `build_myloader_args_from_settings()` (`pulldb/domain/config.py`)

```
Individual settings (from DB or defaults)
    │
    ▼
build_myloader_args_from_settings(settings: dict) → tuple[str, ...]
    │
    ├─ --threads={myloader_threads}
    ├─ --max-threads-per-table={myloader_max_threads_per_table}
    ├─ --max-threads-for-index-creation={myloader_max_threads_index}
    ├─ --max-threads-for-post-actions={myloader_max_threads_post_actions}
    ├─ --max-threads-for-schema-creation={myloader_max_threads_schema}
    ├─ --rows={myloader_rows}
    ├─ --queries-per-transaction={myloader_queries_per_transaction}
    ├─ --retry-count={myloader_retry_count}
    ├─ --throttle=Threads_running={myloader_throttle_threshold}
    ├─ --optimize-keys={myloader_optimize_keys}
    ├─ --checksum={myloader_checksum}
    ├─ --drop-table or --drop-table={mode}
    ├─ --verbose={myloader_verbose}
    ├─ --local-infile=TRUE  (if enabled)
    ├─ --skip-triggers      (if enabled)
    ├─ --skip-constraints   (if enabled)
    ├─ --skip-indexes       (if enabled)
    ├─ --skip-post          (if enabled)
    ├─ --skip-definer       (if enabled)
    └─ --ignore-errors={myloader_ignore_errors}
```

### Full Flow: Settings → Config → MyLoaderSpec → Command

```
Step 1: Config.from_env_and_mysql(pool)
    └─ Calls build_myloader_args_from_settings(settings)
    └─ Stores result in config.myloader_default_args

Step 2: build_configured_myloader_spec(config=..., ...)
    └─ Reads config.myloader_binary
    └─ Reads config.myloader_default_args (from step 1)
    └─ Appends config.myloader_extra_args
    └─ Appends any per-job extra_args
    └─ Ensures --threads flag is present
    └─ Returns MyLoaderSpec(binary_path=..., extra_args=(...))

Step 3: _build_command(spec: MyLoaderSpec) → list[str]
    └─ [binary_path, --database=, --host=, --port=, --user=, --password=, --directory=, *extra_args]

Step 4: run_command_streaming(cmd, ...) → Executes the subprocess
```

### Myloader Preview Endpoint

`GET /web/admin/settings/myloader-preview` generates the complete command
based on current DB settings, letting admins see exactly what command line
would be used for the next restore.

---

## 15. How Settings Affect the Worker <a name="worker-usage"></a>

**File**: `pulldb/worker/service.py` — HCA Layer: **widgets**

The worker service loads config at startup via `bootstrap_service_config()` and
uses `Config.from_env_and_mysql(pool)` to get the full config including MySQL
settings overrides.

### Settings Consumed by Worker (via Config)

| Setting | Worker Behavior |
|---------|-----------------|
| `myloader_binary` | Which myloader binary to execute |
| `myloader_threads` | Parallelism for restores |
| `myloader_timeout_seconds` | Maximum restore execution time |
| `myloader_default_args` (built) | All myloader CLI flags |
| `work_dir` | Where downloads & extractions happen |
| `customers_after_sql_dir` | Post-restore SQL scripts for customer DBs |
| `qa_template_after_sql_dir` | Post-restore SQL scripts for QA templates |
| `s3_backup_locations` | S3 bucket configs + target aliases |
| `aws_profile` | AWS credentials profile |
| `s3_aws_profile` | Separate S3 profile (if different from main) |

### Settings Consumed at Runtime (via SettingsRepository)

The web/API layer reads these dynamically from the DB without restart:

| Setting | Runtime Usage |
|---------|---------------|
| `max_active_jobs_per_user` | Job submission gate (checked on each submit) |
| `max_active_jobs_global` | System-wide job submission limit |
| `default_retention_days` | Default expiration for new restores |
| `max_retention_days` | Maximum retention dropdown options |
| `expiring_warning_days` | "Expiring soon" warning threshold |
| `cleanup_grace_days` | Grace period before auto-cleanup |
| `staging_retention_days` | Staging database cleanup age |
| `jobs_refresh_interval_seconds` | Auto-refresh interval on jobs page |
| `overlord_enabled` | Feature flag for overlord integration |

> **Key distinction**: Config fields are loaded once at service startup (static).
> SettingsRepository queries read from the DB on each request (dynamic). Changing
> myloader settings in the database requires a **service restart** to take
> effect in the worker. Changing retention/limit settings takes effect
> **immediately** on the next DB query.

---

## 16. How Settings Affect the Web UI <a name="web-ui-usage"></a>

### Jobs Page

- `jobs_refresh_interval_seconds` → Sets auto-refresh `<meta>` tag interval
- `expiring_warning_days` → Yellow warning badges on expiring databases
- `max_retention_days` → Generates retention dropdown options
- `default_retention_days` → Pre-selected retention value
- `overlord_enabled` → Shows/hides overlord company column

### Dark Mode

- `dark_mode_enabled` → Default theme preference (read in `dependencies.py`
  via `state.settings_repo.get("dark_mode_enabled")`)
- `light_theme_schema` / `dark_theme_schema` → Custom color palettes loaded
  by `ensure_theme_files_exist()` in `theme_generator.py`

### Admin Dashboard

- Drift alert badge on login page if admin
- Settings count and status overview

---

## 17. Overlord Settings (db_only Pattern) <a name="overlord-settings"></a>

The five `overlord_*` settings are marked `db_only=True`, meaning:

1. **Not synced** to `.env` during `settings pull` or "Sync All to .env"
2. **Excluded** from drift detection (no env var comparison)
3. **Cannot be synced** to `.env` via individual sync button
4. Managed exclusively through the **web UI provisioning workflow**

This pattern exists because overlord credentials are configured via a
multi-step setup wizard in the admin UI, and placing them in `.env` would
violate the security model (credentials are in AWS Secrets Manager, referenced
via `overlord_credential_ref`).

---

## 18. Appearance / Theme Settings <a name="theme-settings"></a>

Theme settings store **JSON color schemas** in the database. The
`theme_generator.py` module reads them from `settings_repo` and generates
CSS files.

```
DB: light_theme_schema = "{...json...}"
DB: dark_theme_schema = "{...json...}"
    │
    ▼
ensure_theme_files_exist(settings_repo)
    └─ Reads JSON from DB
    └─ Parses into color schema
    └─ Generates CSS variables
    └─ Writes to static CSS files
```

If no custom schema is stored, built-in preset defaults are used.

---

## 19. Audit Trail <a name="audit-trail"></a>

All settings changes through the web UI are logged via `audit_repo.log_action()`:

| Action | Trigger |
|--------|---------|
| `setting_updated` | Web UI `POST /settings/{key}` |
| `setting_reset` | Web UI `DELETE /settings/{key}` |
| `settings_synced_to_env` | Web UI "Sync All to .env" |
| `setting_synced` | Web UI individual sync |

Each audit entry includes:
- `actor_user_id` — Who made the change
- `detail` — Human-readable description
- `context` — JSON with `key`, `old_value`, `new_value`, `env_synced`, etc.

The settings page displays the 10 most recent settings audit log entries.

CLI operations do **not** produce audit logs (CLI operates as system admin
without user context).

---

## 20. File Index <a name="file-index"></a>

| File | HCA Layer | Role |
|------|-----------|------|
| `pulldb/domain/settings.py` | entities | Setting registry (SSOT), types, categories, metadata |
| `pulldb/domain/config.py` | entities | Config dataclass, `from_env_and_mysql()`, `build_myloader_args_from_settings()` |
| `pulldb/domain/validation.py` | entities | Setting validation rules, `validate_setting_value()` |
| `pulldb/domain/interfaces.py` | entities | `SettingsRepository` protocol type |
| `pulldb/domain/restore_models.py` | entities | `MyLoaderSpec`, `build_configured_myloader_spec()` |
| `pulldb/infra/mysql_settings.py` | shared | `SettingsRepository` MySQL implementation |
| `pulldb/infra/env_file.py` | shared | `.env` file read/write operations |
| `pulldb/infra/factory.py` | shared | `get_settings_repository()` factory |
| `pulldb/infra/bootstrap.py` | shared | Two-phase service config bootstrap |
| `pulldb/cli/settings.py` | pages | CLI `pulldb-admin settings` commands |
| `pulldb/web/features/admin/routes.py` | pages | Web settings CRUD endpoints |
| `pulldb/web/features/admin/theme_generator.py` | features | Theme CSS generation from settings |
| `pulldb/web/dependencies.py` | pages | Dark mode default from settings |
| `pulldb/web/features/jobs/routes.py` | pages | Retention/refresh settings consumption |
| `pulldb/web/features/auth/routes.py` | pages | Drift check on admin login |
| `pulldb/api/types.py` | pages | `APIState` with `settings_repo` field |
| `pulldb/worker/service.py` | widgets | Worker config loading |
| `pulldb/worker/restore.py` | features | Restore workflow using Config |
| `schema/pulldb_service/00_tables/031_settings.sql` | — | Database table DDL |
| `tests/qa/admin/test_settings.py` | — | CLI settings command tests |

---

---

## 21. Full System Audit: Good / Bad / Better / Missing / Dead <a name="audit"></a>

> Audit performed 2026-02-12 by cross-referencing every claim in this document
> against the actual codebase. Graded on five axes:
>
> - **GOOD** — Working correctly, well-designed
> - **BAD** — Bugs, inconsistencies, or incorrect behavior
> - **BETTER** — Works but could be improved
> - **MISSING** — Functionality that should exist but doesn't
> - **DEAD** — Code/settings that exist but serve no purpose

---

### GOOD

#### G1. Single Source of Truth — `SETTING_REGISTRY`
The `SETTING_REGISTRY` in `pulldb/domain/settings.py` is genuinely the canonical
list and is consumed by both CLI (via `get_known_settings_compat()`) and web UI
(directly). No parallel registry exists. All 45+ settings are defined once.

#### G2. Dual-Write Pattern on Web Update
When a setting is updated via `POST /settings/{key}`, the code correctly:
1. Validates → 2. Saves to DB → 3. Dual-writes to `.env` (non-fatal) →
4. Updates `os.environ` in-memory → 5. Audit logs.
This keeps `.env` in sync without an explicit "Sync All" step. `.env` write
failure is non-fatal — the DB is authoritative.

#### G3. `db_only` Flag Consistently Enforced
The `db_only=True` flag on overlord settings is respected everywhere:
- `pull_settings` CLI excludes them ([settings.py L517](pulldb/cli/settings.py#L517))
- `diff` CLI excludes them ([settings.py L398](pulldb/cli/settings.py#L398))
- `sync_all_settings_to_env` web route skips them ([routes.py L3117](pulldb/web/features/admin/routes.py#L3117))
- `sync_single_setting` web route rejects `db_to_env` for them ([routes.py L3440](pulldb/web/features/admin/routes.py#L3440))
- Drift detection excludes them ([routes.py L2893](pulldb/web/features/admin/routes.py#L2893))

#### G4. Myloader Args Assembly
`build_myloader_args_from_settings()` correctly translates 20+ individual
settings into `--flag=value` arguments. The web preview endpoint
(`GET /settings/myloader-preview`) lets admins verify the generated command.

#### G5. Validation Pipeline
The `validate_setting_value()` function is well-designed: type-based validation
first, then named validators. The `can_create` pattern for directories with
auto-creation is a thoughtful UX feature.

#### G6. CLI Completeness
All 8 CLI commands (`list`, `get`, `set`, `reset`, `export`, `diff`, `pull`,
`push`) work correctly and share infrastructure via the `env_file` module.
Push/pull both support `--dry-run` with confirmation prompts.

#### G7. Audit Logging on Web Changes
Settings changes via the web UI are logged with `actor_user_id`, `old_value`,
`new_value`, and whether `.env` was synced. The settings page shows the 10
most recent audit entries.

#### G8. Seed SQL Uses `ON DUPLICATE KEY UPDATE`
Retention-related seed entries use `ON DUPLICATE KEY UPDATE setting_key =
setting_key` (no-op on collision), preventing overwrites of admin-configured
values during re-seeding.

---

### BAD

#### B1. **Priority Cascade Inversion — UI Lies About Effective Value** (HIGH)
The runtime config loader (`Config.from_env_and_mysql()`) uses **env > DB >
default** priority:
```python
# config.py L325
s3_bucket_path = os.getenv("PULLDB_S3_BUCKET_PATH") or settings.get("s3_bucket_path")
```

But the web UI and CLI display functions (`_get_setting_source()`) use
**DB > env > default** priority:
```python
# routes.py L2830
if db_value is not None:
    return db_value, "database"   # Shows as "active"
```

**Impact**: If an admin saves `myloader_threads=16` in the database AND
`PULLDB_MYLOADER_THREADS=8` is set as an env var, the UI will show "16
(database)" as the effective value, but the **worker will actually use 8**
(the env var). The UI is lying about what value is in effect.

This is consistently wrong across ALL settings loaded in `from_env_and_mysql()`:
`s3_bucket_path`, `default_dbhost`, `work_dir`, `customers_after_sql_dir`,
`qa_template_after_sql_dir`, `myloader_binary`, `myloader_timeout_seconds`,
`myloader_threads`, `s3_backup_locations`.

#### B2. **Default Mismatches Between Registry and Config** (HIGH)

| Setting | Registry Default | Config Default | Location |
|---------|-----------------|----------------|----------|
| `myloader_threads` | `"8"` | `4` (field default) | [config.py L168](pulldb/domain/config.py#L168) |
| `work_directory` | `"/opt/pulldb.service/work"` | `"/mnt/data/tmp/{user}/pulldb-work"` | [config.py L155](pulldb/domain/config.py#L155) |
| `customers_after_sql_dir` | `"/opt/pulldb.service/after_sql/customer"` | `<source_tree>/template_after_sql/customer` | [config.py L157](pulldb/domain/config.py#L157) |
| `qa_template_after_sql_dir` | `"/opt/pulldb.service/after_sql/quality"` | `<source_tree>/template_after_sql/quality` | [config.py L160](pulldb/domain/config.py#L160) |

The Registry says one default, but if you construct `Config()` directly or
use `minimal_from_env()` without env vars set, you get a different default.
The UI shows the registry default as "what you'll get if you reset", but
the system actually falls back to the Config field default.

For `myloader_threads`: the Config field says `4` with the comment "Reduced
from 8 to prevent OOM". The registry was never updated to match.

#### B3. **Seed SQL Uses Obsolete Key Names** (MEDIUM)

The seed file `schema/pulldb_service/02_seed/004_seed_settings.sql` contains
these **ghost entries** that no longer match any registry key:

| Seed Key | Current Registry Key | Status |
|----------|---------------------|--------|
| `max_retention_months` | `max_retention_days` | **Name changed, unit changed** |
| `max_retention_increment` | *(none)* | **Removed entirely** |
| `expiring_notice_days` | `expiring_warning_days` | **Renamed** |

These rows get inserted into the `settings` table but nothing reads them.
They sit as dead data in the database.

The seed file also has different default paths:
- `work_directory` seeded as `"/var/lib/pulldb/work/"` — registry says
  `"/opt/pulldb.service/work"` — Config says `"/mnt/data/tmp/{user}/pulldb-work"`.
  Three different "defaults" for the same setting.

#### B4. **`default_retention_days` Read Bypasses Repository** (MEDIUM)

The `default_retention_days` setting is read via **raw SQL** embedded in
[mysql_jobs.py L504-508](pulldb/infra/mysql_jobs.py#L504-L508):
```sql
SELECT COALESCE(
    (SELECT CAST(setting_value AS UNSIGNED) FROM settings
     WHERE setting_key = 'default_retention_days'), 7
) AS retention_days
```

This bypasses `SettingsRepository.get_default_retention_days()` entirely.
Meanwhile, `get_default_retention_days()` exists in the MySQL implementation
and the simulation adapter but has **zero callers**. The raw SQL query is
fragile — it won't work in simulation mode (which doesn't have a real
`settings` table).

#### B5. **Env Var Name Inconsistency** (LOW)

Two settings break the `PULLDB_{KEY.upper()}` naming convention:

| Setting Key | Expected | Actual |
|-------------|----------|--------|
| `jobs_refresh_interval_seconds` | `PULLDB_JOBS_REFRESH_INTERVAL_SECONDS` | `PULLDB_JOBS_REFRESH_INTERVAL` |
| `work_directory` | `PULLDB_WORK_DIRECTORY` | `PULLDB_WORK_DIR` |

Not a runtime bug, but makes the mapping unpredictable.

#### B6. **Legacy `myloader_default_args` Tuple Is Stale** (LOW)

The `Config` dataclass field default for `myloader_default_args` at
[config.py L163](pulldb/domain/config.py#L163) uses outdated values
(`--rows=100000`, `--queries-per-transaction=5000`) that differ from both the
registry defaults (`50000`, `1000`) and the `_MYLOADER_DEFAULT_ARGS_BUILTIN`
tuple (`50000`, `1000`). This tuple is only used if `Config()` is constructed
directly without calling `from_env_and_mysql()`.

---

### BETTER

#### BT1. **Protocol Completeness**
5 methods exist in both `SettingsRepository` implementations (MySQL and
Simulation) but are **missing from the Protocol** in
[interfaces.py](pulldb/domain/interfaces.py):

| Method | In MySQL Impl | In Simulation | In Protocol |
|--------|--------------|---------------|-------------|
| `get_all_settings_with_metadata()` | Yes (L230) | Yes (L2772) | **NO** |
| `get_default_retention_days()` | Yes (L251) | Yes (L2804) | **NO** |
| `get_max_retention_days()` | Yes (L265) | Yes (L2818) | **NO** |
| `get_job_log_retention_days()` | Yes (L136) | Yes (L2758) | **NO** |
| `get_jobs_refresh_interval()` | Yes (L307) | Yes (L2885) | **NO** |

Web routes work around this with defensive `hasattr()` checks:
```python
if hasattr(settings_repo, "get_expiring_warning_days"):
    expiring_warning_days = settings_repo.get_expiring_warning_days()
```

These should be added to the Protocol to eliminate the `hasattr()` guards.

#### BT2. **String Settings Need Enum Validators**
Several string settings accept a fixed set of values but have no validator to
enforce them. Invalid values would pass validation and crash `myloader` at
runtime:

| Setting | Valid Values | Has Validator? |
|---------|-------------|---------------|
| `myloader_optimize_keys` | `AFTER_IMPORT_PER_TABLE`, `AFTER_IMPORT_ALL_TABLES`, `SKIP` | No |
| `myloader_checksum` | `skip`, `fail`, `warn` | No |
| `myloader_drop_table_mode` | `FAIL`, `NONE`, `DROP`, `TRUNCATE`, `DELETE` | No |

Adding an `is_enum` or `is_one_of` validator type would catch these before
values reach `myloader`.

#### BT3. **Boolean Type Not Handled in Generic Template**
The generic settings template ([settings.html](pulldb/web/templates/features/admin/settings.html))
renders `BOOLEAN` settings as `<input type="text">` instead of a dropdown.
Currently no BOOLEAN settings use the generic template (they all have
category-specific partials like `_myloader.html` that handle it), so this is
a latent bug — it would surface if a BOOLEAN setting is added to "Cleanup &
Retention" or "Paths & Directories" categories.

#### BT4. **Theme JSON Settings Lack JSON Validation**
`light_theme_schema` and `dark_theme_schema` hold JSON strings but use
`SettingType.STRING` with no validator. Invalid JSON would be saved and then
cause errors when `theme_generator.py` tries to parse it.

#### BT5. **CLI Does Not Update `os.environ` In-Memory**
The CLI `set` command writes to DB and `.env` but does NOT update `os.environ`
in-memory (unlike the web UI update path which does). This means subsequent
CLI commands in the same process won't see the new value from `os.getenv()`.
Small issue since CLI commands are typically short-lived.

#### BT6. **`default_retention_days` Should Use Repository, Not Raw SQL**
The raw SQL in `mysql_jobs.py` that reads `default_retention_days` directly
from the `settings` table should call `SettingsRepository.get_default_retention_days()`
instead. This would work in simulation mode and keep the data access pattern
consistent.

---

### MISSING

#### M1. **`s3_backup_locations` Not in Registry**
`Config.from_env_and_mysql()` reads `settings.get("s3_backup_locations")` at
[config.py L377](pulldb/domain/config.py#L377), but this key has **no entry**
in `SETTING_REGISTRY`. It has no `SettingMeta`, no env var mapping, no
validators, no UI widget, and no category. It's readable from the DB via raw
`get_all_settings()` but invisible in the admin UI.

#### M2. **No Feature: Job Log Pruning**
The `job_log_retention_days` setting exists in the registry, DB seed, and
has a repository accessor method (`get_job_log_retention_days()`), but **no
code ever prunes job logs**. The entire feature was defined in the settings
layer but never implemented in the worker or cleanup layer. The setting is
configurable via UI/CLI but does nothing.

#### M3. **No Validation for `myloader_ignore_errors`**
This setting accepts a comma-separated list of MySQL error codes (e.g.,
`"1146"` or `"1146,1050"`), but there's no validator to ensure the format.
An admin could enter `"abc"` and it would be saved without error.

#### M4. **No Hostname Validator for `default_dbhost` and `overlord_dbhost`**
These accept any string. A typo like `localhost:3306` (including port in the
hostname field) would be saved without validation.

#### M5. **No S3 Path Validator for `s3_bucket_path`**
The `parse_s3_bucket_path()` function in `config.py` validates at load time,
but the settings UI allows saving any string without upfront validation.

#### M6. **No `overlord_credential_ref` Format Validator**
Should validate the `aws-secretsmanager:/path` prefix format before saving.

#### M7. **No Migration Script for Seed Key Renames**
The seed SQL still inserts `max_retention_months`, `max_retention_increment`,
and `expiring_notice_days`. Existing production databases may have these old
keys sitting in the `settings` table with no code reading them. There's no
migration to rename or remove them.

#### M8. **No Startup Warning for Priority Cascade Conflict**
When a setting exists in both DB and environment, the system silently uses
the environment value at runtime but shows the DB value in the UI. There's
no warning or log entry about this conflict.

---

### DEAD

#### D1. **`myloader_connection_timeout` — Deprecated, Does Nothing**
- **Registry**: [settings.py L160](pulldb/domain/settings.py#L160), description
  explicitly says `"[DEPRECATED - not used]"`
- **`build_myloader_args_from_settings()`**: Comment at [config.py L505](pulldb/domain/config.py#L505)
  says *"preserved for UI compatibility but not added to args"*
- **Status**: Renders in admin UI, can be edited and validated, takes space in
  the DB, but generates **no myloader flag**. Should be removed from the
  registry or hidden from the UI.

#### D2. **`job_log_retention_days` — Setting Without a Feature**
- **Registry**: [settings.py L375](pulldb/domain/settings.py#L375)
- **Repository method**: [mysql_settings.py L136](pulldb/infra/mysql_settings.py#L136)
  `get_job_log_retention_days()` — **never called** by any code
- **Seeded**: [004_seed_settings.sql L28](schema/pulldb_service/02_seed/004_seed_settings.sql#L28)
- **Impact**: Admin can change this setting; nothing happens. The job log
  pruning feature was never implemented.

#### D3. **`get_default_retention_days()` Method — Never Called**
- **Location**: [mysql_settings.py L251](pulldb/infra/mysql_settings.py#L251) and
  [mock_mysql.py L2804](pulldb/simulation/adapters/mock_mysql.py#L2804)
- **The setting itself is alive** — it's read via raw SQL in `mysql_jobs.py`.
  But the typed accessor method is dead code.

#### D4. **Seed Entries: `max_retention_months`, `max_retention_increment`, `expiring_notice_days`**
- **Location**: [004_seed_settings.sql L31-43](schema/pulldb_service/02_seed/004_seed_settings.sql#L31-L43)
- These key names were renamed during development. The seed still inserts them
  into the `settings` table, but no code reads these keys. They're ghost data.

#### D5. **CLI Unused Imports: `re`, `Path`**
- [settings.py L22](pulldb/cli/settings.py#L22): `import re` — no `re.` usage
- [settings.py L23](pulldb/cli/settings.py#L23): `from pathlib import Path` — no
  `Path(...)` construction

#### D6. **Legacy `Config.myloader_default_args` Field Default**
- [config.py L163-172](pulldb/domain/config.py#L163-L172): The hardcoded tuple
  has stale values (`--rows=100000`, `--queries-per-transaction=5000`) that
  differ from both the registry and `_MYLOADER_DEFAULT_ARGS_BUILTIN`. This
  default is only used if `Config()` is constructed directly (very rare path).
  The `_MYLOADER_DEFAULT_ARGS_BUILTIN` at L443-455 is the actual fallback used
  by `minimal_from_env()`.

---

### Audit Summary Matrix

| # | Category | Severity | Finding |
|---|----------|----------|---------|
| B1 | BAD | **HIGH** | Priority cascade inversion — UI shows DB value as "active" but worker uses env var |
| B2 | BAD | **HIGH** | Default mismatches between Registry and Config (myloader_threads: 8 vs 4) |
| B3 | BAD | MEDIUM | Seed SQL uses obsolete key names (ghost data in production) |
| B4 | BAD | MEDIUM | `default_retention_days` read via raw SQL, bypassing repository |
| B5 | BAD | LOW | 2 env var names break naming convention |
| B6 | BAD | LOW | Legacy myloader_default_args tuple is stale |
| M1 | MISSING | MEDIUM | `s3_backup_locations` read from DB but not in SETTING_REGISTRY |
| M2 | MISSING | MEDIUM | Job log pruning feature never implemented |
| M3-M6 | MISSING | LOW | Validators for ignore_errors, hostname, S3 path, credential_ref |
| M7 | MISSING | LOW | No migration to clean up renamed seed keys |
| M8 | MISSING | LOW | No warning when env var overrides DB value |
| BT1 | BETTER | MEDIUM | 5 methods missing from Protocol (hasattr guards) |
| BT2 | BETTER | MEDIUM | Enum validators needed for string settings |
| BT3 | BETTER | LOW | Generic template doesn't handle BOOLEAN type |
| BT4 | BETTER | LOW | Theme JSON settings lack JSON validator |
| BT5 | BETTER | LOW | CLI doesn't update os.environ in-memory |
| BT6 | BETTER | LOW | default_retention_days should use repository |
| D1 | DEAD | LOW | `myloader_connection_timeout` deprecated, does nothing |
| D2 | DEAD | MEDIUM | `job_log_retention_days` setting + method, no pruning code |
| D3 | DEAD | LOW | `get_default_retention_days()` method never called |
| D4 | DEAD | LOW | 3 ghost seed entries with obsolete key names |
| D5 | DEAD | LOW | Unused `re` and `Path` imports in CLI |
| D6 | DEAD | LOW | Stale `Config.myloader_default_args` field default |
| G1-G8 | GOOD | — | 8 areas working correctly (see GOOD section) |

---

## Appendix: Environment Variables (Non-Setting)

These env vars bootstrap the system but are **not** managed through the
settings system:

| Variable | Purpose |
|----------|---------|
| `PULLDB_MYSQL_HOST` | Coordination DB hostname |
| `PULLDB_MYSQL_PASSWORD` | Coordination DB password |
| `PULLDB_MYSQL_DATABASE` | Coordination DB name (default: pulldb_service) |
| `PULLDB_MYSQL_SOCKET` | Unix socket path (optional) |
| `PULLDB_MYSQL_PORT` | MySQL port |
| `PULLDB_API_MYSQL_USER` | API service MySQL user |
| `PULLDB_WORKER_MYSQL_USER` | Worker service MySQL user |
| `PULLDB_COORDINATION_SECRET` | AWS Secrets Manager path for DB credentials |
| `PULLDB_S3_AWS_PROFILE` | Separate AWS profile for S3 access |
| `PULLDB_S3_BACKUP_LOCATIONS` | JSON array of S3 backup location configs |
| `PULLDB_ENV_FILE` | Override `.env` file location |
| `PULLDB_MYLOADER_DEFAULT_ARGS` | Legacy monolithic args string (deprecated) |
| `PULLDB_MYLOADER_EXTRA_ARGS` | Legacy extra args passthrough (deprecated) |
| `PULLDB_API_KEY` / `PULLDB_API_SECRET` | API authentication credentials |
| `PULLDB_API_KEY_USER` | User identity for API key auth |
| `PULLDB_API_HOST` / `PULLDB_API_PORT` | API server bind address |
| `PULLDB_WEB_HOST` / `PULLDB_WEB_PORT` | Web server bind address |
| `PULLDB_WEB_ENABLED` | Enable web UI |
| `PULLDB_API_URL` / `PULLDB_API_TIMEOUT` | CLI client config |
| `PULLDB_S3ENV_DEFAULT` | Default S3 environment |
| `PULLDB_AWS_REGION` | AWS region |
| `PULLDB_MODE` | `REAL` vs `SIMULATION` mode |
| `PULLDB_LOG_LEVEL` | Logging level |
| `PULLDB_WORKER_ID` | Worker instance identifier |
| `PULLDB_WORKER_POLL_INTERVAL` | Worker queue poll interval |
| `PULLDB_AUTH_MODE` | Authentication mode |
| `PULLDB_MYSQL_CONNECT_TIMEOUT_WORKER` | MySQL connect timeout (worker) |
| `PULLDB_MYSQL_CONNECT_TIMEOUT_API` | MySQL connect timeout (API) |
| `PULLDB_MYSQL_CONNECT_TIMEOUT_MONITOR` | MySQL connect timeout (monitor) |
