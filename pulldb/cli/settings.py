"""Settings management CLI commands.

Provides commands to view, update, and manage pullDB configuration settings.
Settings can be stored in the database (overrides .env) or read from environment.

Usage:
    pulldb-admin settings list           # Show all settings with sources
    pulldb-admin settings get <key>      # Get a specific setting (shows db & env)
    pulldb-admin settings set <key> <value>  # Set in both database AND .env
    pulldb-admin settings reset <key>    # Remove setting from database
    pulldb-admin settings pull           # Sync: database → .env file
    pulldb-admin settings push           # Sync: .env file → database
    pulldb-admin settings diff           # Show differences between db and .env
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import click

# Private import is intentional - we need access to built-in defaults
from pulldb.domain.config import _MYLOADER_DEFAULT_ARGS_BUILTIN


# .env file locations (in priority order)
ENV_FILE_PATHS = [
    Path("/opt/pulldb.service/.env"),  # Installed system
    Path(__file__).parent.parent.parent / ".env",  # Repo root (dev)
]


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
    "work_directory": (
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


def _find_env_file() -> Path | None:
    """Find the .env file to use for read/write operations."""
    for path in ENV_FILE_PATHS:
        if path.exists():
            return path
    return None


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Read settings from .env file.

    Returns:
        Dict mapping env var names to their values.
    """
    settings: dict[str, str] = {}
    if not env_path.exists():
        return settings

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Handle KEY=value format
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove surrounding quotes if present
                if (value.startswith("'") and value.endswith("'")) or (
                    value.startswith('"') and value.endswith('"')
                ):
                    value = value[1:-1]
                settings[key] = value
    return settings


def _write_env_setting(env_path: Path, env_var: str, value: str) -> bool:
    """Write or update a single setting in the .env file.

    Returns:
        True if setting was added/updated, False on error.
    """
    if not env_path.exists():
        click.echo(f"Warning: .env file not found at {env_path}", err=True)
        return False

    lines: list[str] = []
    found = False
    pattern = re.compile(rf"^{re.escape(env_var)}\s*=")

    with open(env_path) as f:
        for line in f:
            if pattern.match(line.strip()):
                # Replace existing line
                lines.append(f"{env_var}={value}\n")
                found = True
            else:
                lines.append(line)

    if not found:
        # Add new setting at end of file
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{env_var}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    return True


def _get_env_value_for_key(key: str, env_settings: dict[str, str]) -> str | None:
    """Get the absolute env value for a setting key."""
    if key not in KNOWN_SETTINGS:
        # Try to guess env var name
        env_var = f"PULLDB_{key.upper()}"
        return env_settings.get(env_var)
    env_var, _, _ = KNOWN_SETTINGS[key]
    return env_settings.get(env_var)


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
    from pulldb.infra.factory import get_settings_repository

    try:
        repo = get_settings_repository()
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
    """Get the value of a specific setting from both database and .env.

    Shows values from both sources so you can see if they differ.
    """
    from pulldb.infra.factory import get_settings_repository

    # Get database value
    db_value: str | None = None
    try:
        repo = get_settings_repository()
        db_settings = repo.get_all_settings()
        db_value = db_settings.get(key)
    except Exception as e:
        click.echo(f"Warning: Could not connect to database: {e}", err=True)

    # Get .env file value
    env_path = _find_env_file()
    env_file_value: str | None = None
    if env_path:
        env_settings = _read_env_file(env_path)
        env_file_value = _get_env_value_for_key(key, env_settings)

    # Get default value
    default_value: str | None = None
    env_var_name = f"PULLDB_{key.upper()}"
    description = ""
    if key in KNOWN_SETTINGS:
        env_var_name, default_value, description = KNOWN_SETTINGS[key]

    # Display results
    click.echo(f"Setting: {key}")
    if description:
        click.echo(f"Description: {description}")
    click.echo(f"Environment variable: {env_var_name}")
    click.echo("")

    # Show both values with tags
    click.echo(f"  db:      {db_value if db_value is not None else '(not set)'}")
    click.echo(
        f"  env:     {env_file_value if env_file_value is not None else '(not set)'}"
    )
    click.echo(
        f"  default: {default_value if default_value is not None else '(not set)'}"
    )

    # Show effective value
    if db_value is not None:
        effective = db_value
        source = "database"
    elif env_file_value is not None:
        effective = env_file_value
        source = "env"
    elif default_value is not None:
        effective = default_value
        source = "default"
    else:
        effective = "(not set)"
        source = "none"

    click.echo("")
    click.echo(f"  effective: {effective} (from {source})")


@settings_group.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--db-only", is_flag=True, help="Only update database, not .env file")
@click.option("--env-only", is_flag=True, help="Only update .env file, not database")
@click.option("--description", "-d", help="Optional description for the setting")
def set_setting(
    key: str,
    value: str,
    db_only: bool,
    env_only: bool,
    description: str | None,
) -> None:
    """Set a setting value in BOTH database AND .env file.

    By default updates both locations to keep them in sync.
    Use --db-only or --env-only to update only one location.

    Examples:
        pulldb-admin settings set myloader_threads 16
        pulldb-admin settings set myloader_threads 16 --db-only
        pulldb-admin settings set myloader_threads 16 --env-only
    """
    if db_only and env_only:
        raise click.ClickException("Cannot specify both --db-only and --env-only")

    update_db = not env_only
    update_env = not db_only

    # Get env var name
    if key in KNOWN_SETTINGS:
        env_var, _, _ = KNOWN_SETTINGS[key]
    else:
        env_var = f"PULLDB_{key.upper()}"

    results: list[str] = []

    # Update database
    if update_db:
        from pulldb.infra.factory import get_settings_repository

        try:
            repo = get_settings_repository()
            repo.set_setting(key, value, description)
            results.append("✓ Database updated")
        except Exception as e:
            results.append(f"✗ Database failed: {e}")

    # Update .env file
    if update_env:
        env_path = _find_env_file()
        if env_path:
            if _write_env_setting(env_path, env_var, value):
                results.append(f"✓ .env updated ({env_path})")
            else:
                results.append("✗ .env update failed")
        else:
            results.append("✗ No .env file found")

    click.echo(f"Setting '{key}' = '{value}'")
    for result in results:
        click.echo(f"  {result}")

    if update_env:
        click.echo("\nNote: Running services need restart to pick up .env changes.")


@settings_group.command("reset")
@click.argument("key")
@click.confirmation_option(prompt="Are you sure you want to reset this setting?")
def reset_setting(key: str) -> None:
    """Remove a setting from the database.

    After reset, the setting will use its environment variable or default value.
    """
    from pulldb.infra.factory import get_settings_repository

    try:
        repo = get_settings_repository()

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
    from pulldb.infra.factory import get_settings_repository

    try:
        repo = get_settings_repository()
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


@settings_group.command("diff")
def diff_settings() -> None:
    """Show differences between database and .env file settings.

    Compares settings stored in the database versus those in the .env file.
    Useful for auditing configuration drift.
    """
    from pulldb.infra.factory import get_settings_repository

    # Get database settings
    db_settings: dict[str, str] = {}
    try:
        repo = get_settings_repository()
        db_settings = repo.get_all_settings()
    except Exception as e:
        raise click.ClickException(f"Could not connect to database: {e}") from e

    # Get .env file settings
    env_path = _find_env_file()
    if not env_path:
        raise click.ClickException("No .env file found")

    env_file_settings = _read_env_file(env_path)
    click.echo(f"Comparing database vs .env file ({env_path})")
    click.echo("")

    # Track all keys from both sources
    all_keys: set[str] = set()

    # Add known settings keys
    for key in KNOWN_SETTINGS:
        all_keys.add(key)

    # Add database keys
    all_keys.update(db_settings.keys())

    # Map env var names to setting keys for comparison
    env_var_to_key: dict[str, str] = {}
    for key, (env_var, _, _) in KNOWN_SETTINGS.items():
        env_var_to_key[env_var] = key

    differences: list[tuple[str, str | None, str | None]] = []
    matches: list[str] = []
    db_only: list[tuple[str, str]] = []
    env_only: list[tuple[str, str, str]] = []

    for key in sorted(all_keys):
        db_value = db_settings.get(key)

        # Get corresponding env var
        if key in KNOWN_SETTINGS:
            env_var, _, _ = KNOWN_SETTINGS[key]
        else:
            env_var = f"PULLDB_{key.upper()}"

        env_value = env_file_settings.get(env_var)

        if db_value is not None and env_value is not None:
            if db_value == env_value:
                matches.append(key)
            else:
                differences.append((key, db_value, env_value))
        elif db_value is not None:
            db_only.append((key, db_value))
        elif env_value is not None:
            env_only.append((key, env_var, env_value))

    # Display results
    if differences:
        click.echo("DIFFERENCES (db ≠ env):")
        click.echo("-" * 60)
        for key, db_val, env_val in differences:
            click.echo(f"  {key}:")
            db_str = db_val or ""
            env_str = env_val or ""
            db_display = db_str[:50] + "..." if len(db_str) > 50 else db_str
            env_display = env_str[:50] + "..." if len(env_str) > 50 else env_str
            click.echo(f"    db:  {db_display}")
            click.echo(f"    env: {env_display}")
        click.echo("")

    if db_only:
        click.echo("DATABASE ONLY (not in .env):")
        click.echo("-" * 60)
        for key, value in db_only:
            display = value[:50] + "..." if len(value) > 50 else value
            click.echo(f"  {key}: {display}")
        click.echo("")

    if env_only:
        click.echo(".ENV ONLY (not in database):")
        click.echo("-" * 60)
        for key, env_var, value in env_only:
            display = value[:50] + "..." if len(value) > 50 else value
            click.echo(f"  {key} ({env_var}): {display}")
        click.echo("")

    if matches:
        click.echo(f"MATCHING: {len(matches)} setting(s) are in sync")

    # Summary
    click.echo("")
    click.echo("Summary:")
    click.echo(f"  Differences: {len(differences)}")
    click.echo(f"  DB only:     {len(db_only)}")
    click.echo(f"  .env only:   {len(env_only)}")
    click.echo(f"  In sync:     {len(matches)}")

    if differences or db_only or env_only:
        click.echo("\nUse 'pulldb-admin settings pull' to sync db → .env")
        click.echo("Use 'pulldb-admin settings push' to sync .env → db")


@settings_group.command("pull")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be changed without making changes"
)
@click.confirmation_option(prompt="Sync database settings to .env file?")
def pull_settings(dry_run: bool) -> None:
    """Sync settings from database to .env file.

    Copies all settings from the database into the .env file.
    Existing .env values will be overwritten with database values.
    """
    from pulldb.infra.factory import get_settings_repository

    # Get database settings
    try:
        repo = get_settings_repository()
        db_settings = repo.get_all_settings()
    except Exception as e:
        raise click.ClickException(f"Could not connect to database: {e}") from e

    if not db_settings:
        click.echo("No settings in database to sync.")
        return

    # Get .env file
    env_path = _find_env_file()
    if not env_path:
        raise click.ClickException("No .env file found")

    click.echo(f"Syncing database → .env ({env_path})")
    if dry_run:
        click.echo("(DRY RUN - no changes will be made)\n")
    click.echo("")

    updated = 0
    for key, value in sorted(db_settings.items()):
        # Get env var name
        if key in KNOWN_SETTINGS:
            env_var, _, _ = KNOWN_SETTINGS[key]
        else:
            env_var = f"PULLDB_{key.upper()}"

        display = value[:50] + "..." if len(value) > 50 else value

        if dry_run:
            click.echo(f"  Would set {env_var}={display}")
        elif _write_env_setting(env_path, env_var, value):
            click.echo(f"  ✓ {env_var}={display}")
            updated += 1
        else:
            click.echo(f"  ✗ Failed: {env_var}")

    click.echo("")
    if dry_run:
        click.echo(f"Would update {len(db_settings)} setting(s).")
    else:
        click.echo(f"Updated {updated} setting(s).")
        click.echo("\nNote: Restart services to apply .env changes.")


@settings_group.command("push")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be changed without making changes"
)
@click.confirmation_option(prompt="Sync .env settings to database?")
def push_settings(dry_run: bool) -> None:
    """Sync settings from .env file to database.

    Copies pullDB settings from .env file into the database.
    Only PULLDB_* variables are synced.
    """
    # Get .env file settings
    env_path = _find_env_file()
    if not env_path:
        raise click.ClickException("No .env file found")

    env_file_settings = _read_env_file(env_path)

    # Filter to only PULLDB_* settings that map to known keys
    settings_to_push: dict[str, str] = {}

    # Check known settings
    for key, (env_var, _, _) in KNOWN_SETTINGS.items():
        if env_var in env_file_settings:
            settings_to_push[key] = env_file_settings[env_var]

    if not settings_to_push:
        click.echo("No PULLDB_* settings found in .env file.")
        return

    # Get database connection
    from pulldb.infra.factory import get_settings_repository

    try:
        repo = get_settings_repository()
    except Exception as e:
        raise click.ClickException(f"Could not connect to database: {e}") from e

    click.echo(f"Syncing .env ({env_path}) → database")
    if dry_run:
        click.echo("(DRY RUN - no changes will be made)\n")
    click.echo("")

    updated = 0
    for key, value in sorted(settings_to_push.items()):
        display = value[:50] + "..." if len(value) > 50 else value

        if dry_run:
            click.echo(f"  Would set {key}={display}")
        else:
            try:
                repo.set_setting(key, value)
                click.echo(f"  ✓ {key}={display}")
                updated += 1
            except Exception as e:
                click.echo(f"  ✗ Failed {key}: {e}")

    click.echo("")
    if dry_run:
        click.echo(f"Would update {len(settings_to_push)} setting(s).")
    else:
        click.echo(f"Updated {updated} setting(s).")
