"""Setting metadata and validation for pullDB configuration.

This module defines the type metadata, validation rules, and categorization
for all configurable settings in pullDB. It provides a single source of truth
for setting definitions used by both CLI and Web interfaces.

HCA Layer: entities (pulldb/domain/)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Import built-in defaults from config
from pulldb.domain.config import _MYLOADER_DEFAULT_ARGS_BUILTIN  # noqa: PLC2701



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
    # Myloader Configuration
    # -------------------------------------------------------------------------
    "myloader_binary": SettingMeta(
        key="myloader_binary",
        env_var="PULLDB_MYLOADER_BINARY",
        default="/opt/pulldb.service/bin/myloader-0.19.3-3",
        description="Path to myloader binary",
        setting_type=SettingType.EXECUTABLE,
        category=SettingCategory.MYLOADER,
        dangerous=True,
        validators=["file_exists", "is_executable"],
    ),
    "myloader_default_args": SettingMeta(
        key="myloader_default_args",
        env_var="PULLDB_MYLOADER_DEFAULT_ARGS",
        default=",".join(_MYLOADER_DEFAULT_ARGS_BUILTIN),
        description="Default myloader arguments (comma-separated)",
        setting_type=SettingType.STRING,
        category=SettingCategory.MYLOADER,
        dangerous=True,
    ),
    "myloader_extra_args": SettingMeta(
        key="myloader_extra_args",
        env_var="PULLDB_MYLOADER_EXTRA_ARGS",
        default="",
        description="Additional myloader arguments",
        setting_type=SettingType.STRING,
        category=SettingCategory.MYLOADER,
        dangerous=False,
    ),
    "myloader_threads": SettingMeta(
        key="myloader_threads",
        env_var="PULLDB_MYLOADER_THREADS",
        default="8",
        description="Number of parallel restore threads",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "myloader_timeout_seconds": SettingMeta(
        key="myloader_timeout_seconds",
        env_var="PULLDB_MYLOADER_TIMEOUT_SECONDS",
        default="7200",
        description="Maximum execution time (seconds)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.MYLOADER,
        dangerous=False,
        validators=["is_positive_integer"],
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
    "max_retention_months": SettingMeta(
        key="max_retention_months",
        env_var="PULLDB_MAX_RETENTION_MONTHS",
        default="6",
        description="Default expiration for new restores; maximum extension allowed (1-12 months)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "max_retention_increment": SettingMeta(
        key="max_retention_increment",
        env_var="PULLDB_MAX_RETENTION_INCREMENT",
        default="3",
        description="Step size for retention dropdown options (1, 2, 3, 4, or 5 months)",
        setting_type=SettingType.INTEGER,
        category=SettingCategory.CLEANUP,
        dangerous=False,
        validators=["is_positive_integer"],
    ),
    "expiring_notice_days": SettingMeta(
        key="expiring_notice_days",
        env_var="PULLDB_EXPIRING_NOTICE_DAYS",
        default="7",
        description="Days before expiry to show database in Expiring Soon notice",
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
