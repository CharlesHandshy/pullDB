"""Setting metadata and validation for pullDB configuration.

This module defines the type metadata, validation rules, and categorization
for all configurable settings in pullDB. It provides a single source of truth
for setting definitions used by both CLI and Web interfaces.

HCA Layer: entities (pulldb/domain/)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SettingType(str, Enum):
    """Type of setting value for appropriate input rendering."""

    STRING = "string"  # Free-form text
    INTEGER = "integer"  # Numeric (threads, timeouts, limits)
    PATH = "path"  # File path (must exist)
    DIRECTORY = "directory"  # Directory path (can be created)
    EXECUTABLE = "executable"  # File path that must be executable
    BOOLEAN = "boolean"  # True/false


class SettingCategory(str, Enum):
    """Category for grouping settings in UI."""

    JOB_LIMITS = "Job Limits"
    PATHS = "Paths & Directories"
    MYLOADER = "Myloader Configuration"
    S3_BACKUP = "S3 & Backup"
    CLEANUP = "Cleanup & Retention"
    APPEARANCE = "Appearance"


@dataclass(frozen=True)
class SettingMeta:
    """Metadata for a configuration setting.

    Attributes:
        key: Setting key name (e.g., 'myloader_threads')
        env_var: Environment variable name (e.g., 'PULLDB_MYLOADER_THREADS')
        default: Default value (None if no default)
        description: Human-readable description
        setting_type: Type for input rendering and validation
        category: UI grouping category
        dangerous: Whether changing this setting could break the system
        validators: List of validator function names to apply
    """

    key: str
    env_var: str
    default: str | None
    description: str
    setting_type: SettingType = SettingType.STRING
    category: SettingCategory = SettingCategory.PATHS
    dangerous: bool = False
    validators: list[str] = field(default_factory=list)


# =============================================================================
# Setting Registry - Single Source of Truth
# =============================================================================

SETTING_REGISTRY: dict[str, SettingMeta] = {
    # -------------------------------------------------------------------------
    # Myloader Configuration - Binary & Timeout
    # -------------------------------------------------------------------------
    "myloader_binary": SettingMeta(
        key="myloader_binary",
        env_var="PULLDB_MYLOADER_BINARY",
        default="/opt/pulldb.service/bin/myloader-0.21.1-1",
        description="Path to myloader binary",
        setting_type=SettingType.EXECUTABLE,
        category=SettingCategory.MYLOADER,
        dangerous=True,
        validators=["file_exists", "is_executable"],
    ),
    "myloader_timeout_seconds": SettingMeta(
        key="myloader_timeout_seconds",
        env_var="PULLDB_MYLOADER_TIMEOUT_SECONDS",
        default="86400",
        description="Maximum execution time in seconds (86400 = 24 hours)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    # -------------------------------------------------------------------------
    # Myloader Configuration - Thread Settings
    # -------------------------------------------------------------------------
    "myloader_threads": SettingMeta(
        key="myloader_threads",
        env_var="PULLDB_MYLOADER_THREADS",
        default="8",
        description="Number of parallel restore threads (--threads). More threads = faster restore but higher memory usage.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "myloader_max_threads_per_table": SettingMeta(
        key="myloader_max_threads_per_table",
        env_var="PULLDB_MYLOADER_MAX_THREADS_PER_TABLE",
        default="1",
        description="Maximum threads working on a single table (--max-threads-per-table). Keep at 1 to prevent table-level contention.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "myloader_max_threads_index": SettingMeta(
        key="myloader_max_threads_index",
        env_var="PULLDB_MYLOADER_MAX_THREADS_INDEX",
        default="1",
        description="Maximum threads for index creation (--max-threads-for-index-creation). ⚠️ Keep at 1 to prevent OOM during index rebuilds.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "myloader_max_threads_post_actions": SettingMeta(
        key="myloader_max_threads_post_actions",
        env_var="PULLDB_MYLOADER_MAX_THREADS_POST_ACTIONS",
        default="1",
        description="Maximum threads for post-actions like constraints, views, triggers (--max-threads-for-post-actions).",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "myloader_max_threads_schema": SettingMeta(
        key="myloader_max_threads_schema",
        env_var="PULLDB_MYLOADER_MAX_THREADS_SCHEMA",
        default="4",
        description="Maximum threads for schema/table creation (--max-threads-for-schema-creation).",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    # -------------------------------------------------------------------------
    # Myloader Configuration - Performance Tuning
    # -------------------------------------------------------------------------
    "myloader_rows": SettingMeta(
        key="myloader_rows",
        env_var="PULLDB_MYLOADER_ROWS",
        default="50000",
        description="Split INSERT statements into this many rows (--rows). Lower values reduce memory per thread.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    "myloader_queries_per_transaction": SettingMeta(
        key="myloader_queries_per_transaction",
        env_var="PULLDB_MYLOADER_QUERIES_PER_TRANSACTION",
        default="1000",
        description="Number of queries per transaction (--queries-per-transaction). Lower values = smaller transactions.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "myloader_connection_timeout": SettingMeta(
        key="myloader_connection_timeout",
        env_var="PULLDB_MYLOADER_CONNECTION_TIMEOUT",
        default="30",
        description="[DEPRECATED - not used] myloader 0.20.x does not support connection timeout.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    "myloader_retry_count": SettingMeta(
        key="myloader_retry_count",
        env_var="PULLDB_MYLOADER_RETRY_COUNT",
        default="20",
        description="Lock wait timeout retry count (--retry-count). Higher values help with busy databases.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "myloader_throttle_threshold": SettingMeta(
        key="myloader_throttle_threshold",
        env_var="PULLDB_MYLOADER_THROTTLE_THRESHOLD",
        default="6",
        description="Auto-throttle when MySQL Threads_running exceeds this value (--throttle). Prevents server overload.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    # -------------------------------------------------------------------------
    # Myloader Configuration - Behavior Options
    # -------------------------------------------------------------------------
    "myloader_optimize_keys": SettingMeta(
        key="myloader_optimize_keys",
        env_var="PULLDB_MYLOADER_OPTIMIZE_KEYS",
        default="AFTER_IMPORT_PER_TABLE",
        description="When to create indexes (--optimize-keys). Options: AFTER_IMPORT_PER_TABLE, AFTER_IMPORT_ALL_TABLES, SKIP.",
        setting_type=SettingType.STRING,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_checksum": SettingMeta(
        key="myloader_checksum",
        env_var="PULLDB_MYLOADER_CHECKSUM",
        default="warn",
        description="Checksum handling (--checksum). Options: skip, fail, warn.",
        setting_type=SettingType.STRING,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_drop_table_mode": SettingMeta(
        key="myloader_drop_table_mode",
        env_var="PULLDB_MYLOADER_DROP_TABLE_MODE",
        default="DROP",
        description="Action when table exists (--drop-table). Options: FAIL, NONE, DROP, TRUNCATE, DELETE.",
        setting_type=SettingType.STRING,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_verbose": SettingMeta(
        key="myloader_verbose",
        env_var="PULLDB_MYLOADER_VERBOSE",
        default="3",
        description="Verbosity level (--verbose). 0=silent, 1=errors, 2=warnings, 3=info.",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    # -------------------------------------------------------------------------
    # Myloader Configuration - Feature Flags
    # -------------------------------------------------------------------------
    "myloader_local_infile": SettingMeta(
        key="myloader_local_infile",
        env_var="PULLDB_MYLOADER_LOCAL_INFILE",
        default="true",
        description="Enable LOAD DATA LOCAL INFILE (--local-infile). Usually faster for large imports.",
        setting_type=SettingType.BOOLEAN,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_skip_triggers": SettingMeta(
        key="myloader_skip_triggers",
        env_var="PULLDB_MYLOADER_SKIP_TRIGGERS",
        default="false",
        description="Skip importing triggers (--skip-triggers).",
        setting_type=SettingType.BOOLEAN,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_skip_constraints": SettingMeta(
        key="myloader_skip_constraints",
        env_var="PULLDB_MYLOADER_SKIP_CONSTRAINTS",
        default="false",
        description="Skip importing constraints (--skip-constraints). May speed up import but lose referential integrity.",
        setting_type=SettingType.BOOLEAN,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_skip_indexes": SettingMeta(
        key="myloader_skip_indexes",
        env_var="PULLDB_MYLOADER_SKIP_INDEXES",
        default="false",
        description="Skip importing secondary indexes (--skip-indexes). Faster import but slower queries.",
        setting_type=SettingType.BOOLEAN,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_skip_post": SettingMeta(
        key="myloader_skip_post",
        env_var="PULLDB_MYLOADER_SKIP_POST",
        default="false",
        description="Skip events, stored procedures, and functions (--skip-post).",
        setting_type=SettingType.BOOLEAN,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_skip_definer": SettingMeta(
        key="myloader_skip_definer",
        env_var="PULLDB_MYLOADER_SKIP_DEFINER",
        default="false",
        description="Remove DEFINER from CREATE statements (--skip-definer). Useful when user doesn't exist on target.",
        setting_type=SettingType.BOOLEAN,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    # -------------------------------------------------------------------------
    # Myloader Configuration - Advanced
    # -------------------------------------------------------------------------
    "myloader_ignore_errors": SettingMeta(
        key="myloader_ignore_errors",
        env_var="PULLDB_MYLOADER_IGNORE_ERRORS",
        default="1146",
        description="Comma-separated MySQL error codes to ignore (--ignore-errors). 1146 = table doesn't exist.",
        setting_type=SettingType.STRING,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    # -------------------------------------------------------------------------
    # Paths & Directories
    # -------------------------------------------------------------------------
    "work_directory": SettingMeta(
        key="work_directory",
        env_var="PULLDB_WORK_DIR",
        default="/opt/pulldb.service/work",
        description="Working directory for downloads/extraction",
        setting_type=SettingType.DIRECTORY,
        category=SettingCategory.PATHS,
        dangerous=True,
        validators=["directory_exists", "is_writable"],
    ),
    "customers_after_sql_dir": SettingMeta(
        key="customers_after_sql_dir",
        env_var="PULLDB_CUSTOMERS_AFTER_SQL_DIR",
        default="/opt/pulldb.service/after_sql/customer",
        description="Customer post-restore SQL scripts directory",
        setting_type=SettingType.DIRECTORY,
        category=SettingCategory.PATHS,
        dangerous=False,
        validators=["directory_exists"],
    ),
    "qa_template_after_sql_dir": SettingMeta(
        key="qa_template_after_sql_dir",
        env_var="PULLDB_QA_TEMPLATE_AFTER_SQL_DIR",
        default="/opt/pulldb.service/after_sql/quality",
        description="QA template post-restore SQL scripts directory",
        setting_type=SettingType.DIRECTORY,
        category=SettingCategory.PATHS,
        dangerous=False,
        validators=["directory_exists"],
    ),
    # -------------------------------------------------------------------------
    # S3 & Backup
    # -------------------------------------------------------------------------
    "default_dbhost": SettingMeta(
        key="default_dbhost",
        env_var="PULLDB_DEFAULT_DBHOST",
        default=None,
        description="Default target database host",
        setting_type=SettingType.STRING,
        category=SettingCategory.S3_BACKUP,
        dangerous=False,
    ),
    "s3_bucket_path": SettingMeta(
        key="s3_bucket_path",
        env_var="PULLDB_S3_BUCKET_PATH",
        default=None,
        description="S3 bucket path for backups",
        setting_type=SettingType.STRING,
        category=SettingCategory.S3_BACKUP,
        dangerous=False,
    ),
    "aws_profile": SettingMeta(
        key="aws_profile",
        env_var="PULLDB_AWS_PROFILE",
        default="pr-dev",
        description="AWS profile for Secrets Manager access",
        setting_type=SettingType.STRING,
        category=SettingCategory.S3_BACKUP,
        dangerous=False,
    ),
    # -------------------------------------------------------------------------
    # Job Limits
    # -------------------------------------------------------------------------
    "max_active_jobs_per_user": SettingMeta(
        key="max_active_jobs_per_user",
        env_var="PULLDB_MAX_ACTIVE_JOBS_PER_USER",
        default="0",
        description="Maximum active jobs per user (0=unlimited)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.JOB_LIMITS,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    "max_active_jobs_global": SettingMeta(
        key="max_active_jobs_global",
        env_var="PULLDB_MAX_ACTIVE_JOBS_GLOBAL",
        default="0",
        description="Maximum active jobs system-wide (0=unlimited)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.JOB_LIMITS,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    # -------------------------------------------------------------------------
    # Cleanup & Retention
    # -------------------------------------------------------------------------
    "staging_retention_days": SettingMeta(
        key="staging_retention_days",
        env_var="PULLDB_STAGING_RETENTION_DAYS",
        default="7",
        description="Days before staging databases are cleaned up",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    "job_log_retention_days": SettingMeta(
        key="job_log_retention_days",
        env_var="PULLDB_JOB_LOG_RETENTION_DAYS",
        default="30",
        description="Days before job logs are pruned",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    "default_retention_days": SettingMeta(
        key="default_retention_days",
        env_var="PULLDB_DEFAULT_RETENTION_DAYS",
        default="7",
        description="Default expiration for new restores in days (7 = 1 week)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "max_retention_days": SettingMeta(
        key="max_retention_days",
        env_var="PULLDB_MAX_RETENTION_DAYS",
        default="180",
        description="Maximum retention allowed in days (180 = ~6 months)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "expiring_warning_days": SettingMeta(
        key="expiring_warning_days",
        env_var="PULLDB_EXPIRING_WARNING_DAYS",
        default="7",
        description="Days before expiry to show yellow 'will expire soon' warning",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    "cleanup_grace_days": SettingMeta(
        key="cleanup_grace_days",
        env_var="PULLDB_CLEANUP_GRACE_DAYS",
        default="7",
        description="Days after expiry before database is automatically cleaned up",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    "jobs_refresh_interval_seconds": SettingMeta(
        key="jobs_refresh_interval_seconds",
        env_var="PULLDB_JOBS_REFRESH_INTERVAL",
        default="5",
        description="Auto-refresh interval for jobs page in seconds (0 to disable)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_non_negative_integer"],
    ),
    # -------------------------------------------------------------------------
    # Appearance
    # -------------------------------------------------------------------------
    # Appearance - Theme Schemas (JSON)
    # -------------------------------------------------------------------------
    "light_theme_schema": SettingMeta(
        key="light_theme_schema",
        env_var="PULLDB_LIGHT_THEME_SCHEMA",
        default=None,  # Will use LIGHT_PRESETS["Default"] from color_schemas
        description="Light mode color schema (JSON)",
        setting_type=SettingType.STRING,
        category=SettingCategory.APPEARANCE,
        dangerous=False,
    ),
    "dark_theme_schema": SettingMeta(
        key="dark_theme_schema",
        env_var="PULLDB_DARK_THEME_SCHEMA",
        default=None,  # Will use DARK_PRESETS["Default"] from color_schemas
        description="Dark mode color schema (JSON)",
        setting_type=SettingType.STRING,
        category=SettingCategory.APPEARANCE,
        dangerous=False,
    ),
    "dark_mode_enabled": SettingMeta(
        key="dark_mode_enabled",
        env_var="PULLDB_DARK_MODE_ENABLED",
        default="false",
        description="Enable dark mode by default",
        setting_type=SettingType.BOOLEAN,
        category=SettingCategory.APPEARANCE,
        dangerous=False,
    ),
}


def get_setting_meta(key: str) -> SettingMeta | None:
    """Get metadata for a setting by key.

    Args:
        key: Setting key name.

    Returns:
        SettingMeta if found, None otherwise.
    """
    return SETTING_REGISTRY.get(key)


def get_settings_by_category() -> dict[SettingCategory, list[SettingMeta]]:
    """Get all settings grouped by category.

    Returns:
        Dict mapping categories to their settings.
    """
    result: dict[SettingCategory, list[SettingMeta]] = {}
    for meta in SETTING_REGISTRY.values():
        if meta.category not in result:
            result[meta.category] = []
        result[meta.category].append(meta)
    return result


def get_all_setting_keys() -> list[str]:
    """Get all known setting keys.

    Returns:
        List of setting key names.
    """
    return list(SETTING_REGISTRY.keys())


# =============================================================================
# Legacy Compatibility - KNOWN_SETTINGS format
# =============================================================================

def get_known_settings_compat() -> dict[str, tuple[str, str | None, str]]:
    """Get settings in legacy KNOWN_SETTINGS format for backward compatibility.

    Returns:
        Dict mapping key to (env_var, default, description) tuples.
    """
    return {
        meta.key: (meta.env_var, meta.default, meta.description)
        for meta in SETTING_REGISTRY.values()
    }
