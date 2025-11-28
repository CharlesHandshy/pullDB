"""Settings management CLI commands.

Provides commands to view, update, and manage pullDB configuration settings.
Settings can be stored in the database (overrides .env) or read from environment.

Usage:
    pulldb settings list           # Show all settings with sources
    pulldb settings get <key>      # Get a specific setting
    pulldb settings set <key> <value>  # Set a setting in database
    pulldb settings reset <key>    # Remove setting from database (revert to env)
"""

from __future__ import annotations

import json
import os
import typing as t

import click

# Private import is intentional - we need access to built-in defaults
from pulldb.domain.config import _MYLOADER_DEFAULT_ARGS_BUILTIN


# Known settings with their environment variable names and defaults
# Format: (env_var, default_value, description)
KNOWN_SETTINGS: dict[str, tuple[str, str | None, str]] = {
    "myloader_binary": (
        "PULLDB_MYLOADER_BINARY",
        "/opt/pulldb.service/bin/myloader-0.19.3-3",
        "Path to myloader binary",
    ),
    "myloader_default_args": (
        "PULLDB_MYLOADER_DEFAULT_ARGS",
        ",".join(_MYLOADER_DEFAULT_ARGS_BUILTIN),
        "Default myloader arguments (comma-separated)",
    ),
    "myloader_extra_args": (
        "PULLDB_MYLOADER_EXTRA_ARGS",
        "",
        "Additional myloader arguments",
    ),
    "myloader_threads": (
        "PULLDB_MYLOADER_THREADS",
        "8",
        "Number of parallel restore threads",
    ),
    "myloader_timeout_seconds": (
        "PULLDB_MYLOADER_TIMEOUT_SECONDS",
        "7200",
        "Maximum execution time (seconds)",
    ),
    "work_dir": (
        "PULLDB_WORK_DIR",
        "/opt/pulldb.service/work",
        "Working directory for downloads/extraction",
    ),
    "customers_after_sql_dir": (
        "PULLDB_CUSTOMERS_AFTER_SQL_DIR",
        "/opt/pulldb.service/after_sql/customer",
        "Customer post-restore SQL scripts directory",
    ),
    "qa_template_after_sql_dir": (
        "PULLDB_QA_TEMPLATE_AFTER_SQL_DIR",
        "/opt/pulldb.service/after_sql/quality",
        "QA template post-restore SQL scripts directory",
    ),
    "default_dbhost": (
        "PULLDB_DEFAULT_DBHOST",
        None,
        "Default target database host",
    ),
    "s3_bucket_path": (
        "PULLDB_S3_BUCKET_PATH",
        None,
        "S3 bucket path for backups",
    ),
    # Phase 2: Concurrency controls (v0.0.4)
    "max_active_jobs_per_user": (
        "PULLDB_MAX_ACTIVE_JOBS_PER_USER",
        "0",
        "Maximum active jobs per user (0=unlimited)",
    ),
    "max_active_jobs_global": (
        "PULLDB_MAX_ACTIVE_JOBS_GLOBAL",
        "0",
        "Maximum active jobs system-wide (0=unlimited)",
    ),
}


def _get_mysql_pool() -> t.Any:
    """Get MySQL connection pool using bootstrap config.
    
    Uses PULLDB_API_MYSQL_USER for admin CLI operations since we need
    read/write access to the settings table.
    """
    from pulldb.infra.mysql import MySQLPool
    from pulldb.infra.secrets import CredentialResolver

    # Get credentials from Secrets Manager (password only)
    secret_ref = os.getenv(
        "PULLDB_COORDINATION_SECRET",
        "aws-secretsmanager:/pulldb/mysql/coordination-db"
    )
    
    # Use the AWS profile for Secrets Manager
    aws_profile = os.getenv("PULLDB_AWS_PROFILE")
    resolver = CredentialResolver(aws_profile=aws_profile)
    creds = resolver.resolve(secret_ref)
    
    # Use API user for admin operations
    mysql_user = os.getenv("PULLDB_API_MYSQL_USER", "pulldb_api")
    mysql_database = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb_service")
    
    return MySQLPool(
        host=creds.host,
        user=mysql_user,
        password=creds.password,
        database=mysql_database,
        port=creds.port,
    )


def _get_settings_repo() -> t.Any:
    """Get SettingsRepository instance."""
    from pulldb.infra.mysql import SettingsRepository

    pool = _get_mysql_pool()
    return SettingsRepository(pool)


def _get_setting_source(
    key: str, db_settings: dict[str, str]
) -> tuple[str | None, str]:
    """Determine setting value and its source.

    Returns:
        Tuple of (value, source) where source is 'database', 'environment', or 'default'
    """
    # Check database first (highest priority)
    if key in db_settings:
        return db_settings[key], "database"

    # Check environment
    setting_info = KNOWN_SETTINGS.get(key, (f"PULLDB_{key.upper()}", None, ""))
    env_var, default_value, _ = setting_info
    env_value = os.getenv(env_var)
    if env_value is not None:
        return env_value, "environment"

    # Return default
    return default_value, "default"


@click.group(name="settings", help="Manage pullDB configuration settings")
def settings_group() -> None:
    """Settings management command group."""
    pass


@settings_group.command("list")
@click.option(
    "--all", "show_all", is_flag=True, help="Show all known settings including unset"
)
def list_settings(show_all: bool) -> None:
    """List all settings with their current values and sources.

    Shows the effective value of each setting and where it comes from:
    - database: Stored in settings table (highest priority)
    - environment: Set via environment variable / .env file
    - default: Built-in default value
    """
    try:
        repo = _get_settings_repo()
        db_settings = repo.get_all_settings()
    except Exception as e:
        click.echo(f"Warning: Could not connect to database: {e}", err=True)
        click.echo("Showing environment and default values only.\n", err=True)
        db_settings = {}

    # Collect all settings to display
    settings_to_show: dict[str, tuple[str | None, str, str]] = {}

    # Add known settings
    for key, (_env_var, _default_value, description) in KNOWN_SETTINGS.items():
        value, source = _get_setting_source(key, db_settings)
        if show_all or value is not None:
            settings_to_show[key] = (value, source, description)

    # Add any database settings not in known list
    for key, value in db_settings.items():
        if key not in settings_to_show:
            settings_to_show[key] = (value, "database", "")

    if not settings_to_show:
        click.echo("No settings configured.")
        return

    # Calculate column widths
    key_width = max(len(k) for k in settings_to_show)
    source_width = 11  # "environment" is longest

    # Print header
    click.echo(f"{'SETTING':<{key_width}}  {'SOURCE':<{source_width}}  VALUE")
    click.echo(f"{'-' * key_width}  {'-' * source_width}  {'-' * 40}")

    # Print settings sorted by key
    for key in sorted(settings_to_show.keys()):
        value, source, description = settings_to_show[key]
        display_value = value if value is not None else "(not set)"
        # Truncate long values
        if len(display_value) > 60:
            display_value = display_value[:57] + "..."
        click.echo(f"{key:<{key_width}}  {source:<{source_width}}  {display_value}")

    click.echo(f"\n{len(settings_to_show)} setting(s) displayed.")
    click.echo("\nUse 'pulldb settings get <key>' for full value.")
    click.echo("Use 'pulldb settings set <key> <value>' to override in database.")


@settings_group.command("get")
@click.argument("key")
def get_setting(key: str) -> None:
    """Get the value of a specific setting.

    Shows the effective value and its source (database, environment, or default).
    """
    try:
        repo = _get_settings_repo()
        db_settings = repo.get_all_settings()
    except Exception as e:
        click.echo(f"Warning: Could not connect to database: {e}", err=True)
        db_settings = {}

    value, source = _get_setting_source(key, db_settings)

    if value is None:
        click.echo(f"{key} = (not set)")
        click.echo(f"Source: {source}")
        if key in KNOWN_SETTINGS:
            _, env_var, description = KNOWN_SETTINGS[key]
            click.echo(f"\nDescription: {description}")
            click.echo(f"Environment variable: {env_var}")
    else:
        click.echo(f"{key} = {value}")
        click.echo(f"Source: {source}")
        if key in KNOWN_SETTINGS:
            _, env_var, description = KNOWN_SETTINGS[key]
            click.echo(f"\nDescription: {description}")
            click.echo(f"Environment variable: {env_var}")


@settings_group.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--description", "-d", help="Optional description for the setting")
def set_setting(key: str, value: str, description: str | None) -> None:
    """Set a setting value in the database.

    Database settings override environment variables and defaults.
    The change takes effect immediately for new operations.

    Examples:
        pulldb settings set myloader_threads 16
        pulldb settings set myloader_default_args "--verbose=3,--threads=8"
    """
    try:
        repo = _get_settings_repo()
        repo.set_setting(key, value, description)
        click.echo(f"Setting '{key}' updated to '{value}' (stored in database)")
        click.echo("\nNote: Running services may need restart to pick up changes.")
    except Exception as e:
        raise click.ClickException(f"Failed to set setting: {e}") from e


@settings_group.command("reset")
@click.argument("key")
@click.confirmation_option(prompt="Are you sure you want to reset this setting?")
def reset_setting(key: str) -> None:
    """Remove a setting from the database.

    After reset, the setting will use its environment variable or default value.
    """
    try:
        repo = _get_settings_repo()

        # Check current source before reset
        db_settings = repo.get_all_settings()
        if key not in db_settings:
            click.echo(f"Setting '{key}' is not stored in database.")
            value, source = _get_setting_source(key, {})
            if value is not None:
                click.echo(f"Current value from {source}: {value}")
            return

        deleted = repo.delete_setting(key)
        if deleted:
            # Show what value it will revert to
            value, source = _get_setting_source(key, {})
            if value is not None:
                click.echo(f"Setting '{key}' removed from database.")
                click.echo(f"Now using {source} value: {value}")
            else:
                click.echo(f"Setting '{key}' removed from database.")
                click.echo("No environment or default value configured.")
        else:
            click.echo(f"Setting '{key}' was not found in database.")
    except Exception as e:
        raise click.ClickException(f"Failed to reset setting: {e}") from e


@settings_group.command("export")
@click.option(
    "--format", "output_format", type=click.Choice(["env", "json"]), default="env"
)
def export_settings(output_format: str) -> None:
    """Export all current settings.

    Outputs settings in .env format (default) or JSON format.
    Useful for backup or migration.
    """
    try:
        repo = _get_settings_repo()
        db_settings = repo.get_all_settings()
    except Exception as e:
        click.echo(f"Warning: Could not connect to database: {e}", err=True)
        db_settings = {}

    # Collect all effective settings
    all_settings: dict[str, str | None] = {}
    for key in KNOWN_SETTINGS:
        value, _ = _get_setting_source(key, db_settings)
        all_settings[key] = value

    # Add database-only settings
    for key, value in db_settings.items():
        if key not in all_settings:
            all_settings[key] = value

    if output_format == "json":
        click.echo(json.dumps(all_settings, indent=2))
    else:
        click.echo("# pullDB Settings Export")
        click.echo("# Generated by: pulldb settings export")
        click.echo("")
        for key, value in sorted(all_settings.items()):
            env_var = KNOWN_SETTINGS.get(key, (f"PULLDB_{key.upper()}", None, ""))[0]
            if value is not None:
                click.echo(f"{env_var}={value}")
            else:
                click.echo(f"# {env_var}=")
