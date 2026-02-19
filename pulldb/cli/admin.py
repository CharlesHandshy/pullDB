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

Note: To submit jobs on behalf of other users, use:
  pulldb restore <customer> user=<username>

HCA Layer: pages
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from collections.abc import Sequence

logger = logging.getLogger(__name__)

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
    overlord_group,
    run_retention_cleanup_cmd,
    run_terminal_cleanup_cmd,
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
        # Fallback to environment variable if getpass fails
        logger.debug("getpass.getuser() failed, falling back to env", exc_info=True)
        return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


def _check_admin_authorization() -> None:
    """Verify the system user has admin role in pullDB.

    SECURITY: This runs unconditionally — no help, no command listing,
    no subcommand details are shown to unauthorized users.

    Raises:
        click.ClickException: If user is not authorized.
    """
    # Load .env
    _ensure_env_loaded()

    # Check if .env loading failed
    if _env_error:
        raise click.ClickException(
            click.style("Account not authorized.", fg="red", bold=True)
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

        # Check for admin/service role
        # SERVICE role has same CLI permissions as admin (for system accounts like pulldb_service)
        from pulldb.domain.models import UserRole
        if user.role not in (UserRole.ADMIN, UserRole.SERVICE):
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
    except Exception:
        # Connection errors, etc. — give nothing away
        raise click.ClickException(
            click.style("Account not authorized.", fg="red", bold=True)
        )


class _AuthGroup(click.Group):
    """Click Group that enforces admin authorization before ANY output.

    SECURITY: Auth is required for ALL operations — no exceptions.
    Unauthorized users receive only "Account not authorized." regardless
    of what flags or subcommands they attempt.
    """

    def invoke(self, ctx: click.Context) -> None:
        _check_admin_authorization()
        super().invoke(ctx)

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # Auth before parsing — blocks --help, bare invocation, everything
        if "--help" in args or not args:
            _check_admin_authorization()
        return super().parse_args(ctx, args)


@click.group(cls=_AuthGroup, help="pullDB Admin - System administration tool (requires admin role)")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """CLI entry point for pullDB admin commands.

    This is the main Click group that organizes all pullDB admin subcommands.
    Requires the system user to have admin role in pullDB.
    """
    pass


# Register command groups
cli.add_command(settings_group)
cli.add_command(secrets_group)
cli.add_command(jobs_group)
cli.add_command(backups_group)
cli.add_command(cleanup_cmd)
cli.add_command(run_retention_cleanup_cmd)
cli.add_command(run_terminal_cleanup_cmd)
cli.add_command(hosts_group)
cli.add_command(users_group)
cli.add_command(keys_group)
cli.add_command(disallow_group)
cli.add_command(overlord_group)


def main(argv: Sequence[str] | None = None) -> int:
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
