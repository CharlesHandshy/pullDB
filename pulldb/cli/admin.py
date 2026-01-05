"""Entry point for the `pulldb-admin` CLI.

Administrative commands for pullDB system management.
This CLI requires the system user to have an admin role in pullDB.

Commands:
- settings: Manage configuration settings (list, get, set, reset, export)
- secrets: Manage AWS Secrets Manager credentials (list, get, set, delete, test, rotate)
- jobs: View and manage jobs across all users
- cleanup: Cleanup orphaned staging databases and work files
- run-retention-cleanup: Run database retention cleanup (drop expired databases)
- hosts: Manage registered database hosts (list, add, enable, disable, cred)
- users: View and manage users
- disallow: Manage disallowed usernames (list, add, remove)
"""

from __future__ import annotations

import getpass
import os
import sys
import typing as t

import click
from dotenv import load_dotenv


# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_UNAUTHORIZED = 2
EXIT_CONNECTION_ERROR = 3


# .env file paths for lazy loading
_INSTALLED_ENV = "/opt/pulldb.service/.env"
_REPO_ENV = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
_env_loaded = False
_env_error: str | None = None


def _ensure_env_loaded() -> None:
    """Load .env file lazily. Only called when config is actually needed."""
    global _env_loaded, _env_error
    
    if _env_loaded:
        return
    
    try:
        if os.path.exists(_INSTALLED_ENV):
            load_dotenv(_INSTALLED_ENV)
        elif os.path.exists(_REPO_ENV):
            load_dotenv(_REPO_ENV)
        _env_loaded = True
    except PermissionError:
        _env_error = _INSTALLED_ENV
        # Don't exit here - let Click show --help if requested

from pulldb import __version__
from pulldb.cli.admin_commands import (
    cleanup_cmd,
    disallow_group,
    hosts_group,
    jobs_group,
    keys_group,
    run_retention_cleanup_cmd,
    users_group,
)
from pulldb.cli.backup_commands import backups_group
from pulldb.cli.secrets_commands import secrets_group
from pulldb.cli.settings import settings_group


def _get_system_username() -> str:
    """Get the current system username.
    
    When running with sudo, returns the original user (SUDO_USER),
    not "root".
    """
    # Check for sudo - get the original user
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return sudo_user
    
    try:
        return getpass.getuser()
    except Exception:
        # Fallback to environment variable
        return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


def _check_admin_authorization(ctx: click.Context) -> None:
    """Verify the system user has admin role in pullDB.

    Raises:
        click.ClickException: If user is not authorized.
    """
    # Skip auth check for --help and --version
    if ctx.resilient_parsing:
        return
    if ctx.invoked_subcommand is None:
        # No subcommand - just showing help
        return

    # Load .env now that we actually need it
    _ensure_env_loaded()
    
    # Check if .env loading failed
    if _env_error:
        raise click.ClickException(
            click.style("Error: ", fg="red", bold=True)
            + f"Permission denied reading {_env_error}\n"
            + click.style("Hint: ", fg="yellow")
            + "Run with: "
            + click.style("pulldb-admin <command>", fg="cyan")
            + " (auto-escalates to pulldb_service user)"
        )

    username = _get_system_username()

    try:
        from pulldb.infra.factory import get_user_repository

        repo = get_user_repository()
        user = repo.get_user_by_username(username)

        if user is None:
            raise click.ClickException(
                click.style("Account not authorized.", fg="red", bold=True)
            )

        # Check for admin/service role (handle both enum and string comparison)
        # SERVICE role has same CLI permissions as admin (for system accounts like pulldb_service)
        is_admin = user.is_admin or str(user.role).lower() in (
            "admin", "userrole.admin", "service", "userrole.service"
        )
        if not is_admin:
            raise click.ClickException(
                click.style("Account not authorized.", fg="red", bold=True)
            )

        if user.disabled_at is not None:
            raise click.ClickException(
                click.style("Account not authorized.", fg="red", bold=True)
            )

    except click.ClickException:
        # Re-raise ClickExceptions as-is
        raise
    except Exception as e:
        # Connection errors, etc.
        raise click.ClickException(
            click.style("Authorization check failed: ", fg="red", bold=True)
            + "Cannot connect to database.\n"
            + click.style("Details: ", fg="yellow")
            + str(e)
        ) from e


@click.group(help="pullDB Admin - System administration tool (requires admin role)")
@click.version_option(__version__, prog_name="pulldb-admin")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """CLI entry point for pullDB admin commands.

    This is the main Click group that organizes all pullDB admin subcommands.
    Requires the system user to have admin role in pullDB.
    """
    _check_admin_authorization(ctx)


# Register command groups
cli.add_command(settings_group)
cli.add_command(secrets_group)
cli.add_command(jobs_group)
cli.add_command(backups_group)
cli.add_command(cleanup_cmd)
cli.add_command(run_retention_cleanup_cmd)
cli.add_command(hosts_group)
cli.add_command(users_group)
cli.add_command(keys_group)
cli.add_command(disallow_group)


def main(argv: t.Sequence[str] | None = None) -> int:
    """Main entry point for pulldb-admin CLI.

    Args:
        argv: Command-line arguments. If None, uses sys.argv.

    Returns:
        Exit code: 0 for success, 1 for errors, 2 for unauthorized.
    """
    try:
        cli.main(args=list(argv) if argv is not None else None, standalone_mode=False)
        return EXIT_SUCCESS
    except click.exceptions.NoArgsIsHelpError as exc:
        click.echo(exc.ctx.get_help())
        return EXIT_ERROR
    except click.exceptions.ClickException as exc:
        exc.show()
        # Use EXIT_UNAUTHORIZED for auth failures
        if "Authorization" in str(exc.message):
            return EXIT_UNAUTHORIZED
        return exc.exit_code if exc.exit_code else EXIT_ERROR
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return EXIT_ERROR
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return EXIT_ERROR if exc.code else EXIT_SUCCESS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
