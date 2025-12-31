"""Entry point for the `pulldb-admin` CLI.

Administrative commands for pullDB system management.
This CLI is intended for server operators, not end users.

Commands:
- settings: Manage configuration settings (list, get, set, reset, export)
- secrets: Manage AWS Secrets Manager credentials (list, get, set, delete, test, rotate)
- jobs: View and manage jobs across all users
- cleanup: Cleanup orphaned staging databases and work files
- run-retention-cleanup: Run database retention cleanup (drop expired databases)
- hosts: Manage registered database hosts
- users: View and manage users
- disallow: Manage disallowed usernames (list, add, remove)
"""

from __future__ import annotations

import os
import sys
import typing as t

import click
from dotenv import load_dotenv


# Load .env file from standard locations
# Priority: /opt/pulldb.service/.env (installed), then .env (dev)
_installed_env = "/opt/pulldb.service/.env"
_repo_env = os.path.join(os.path.dirname(__file__), "..", "..", ".env")

if os.path.exists(_installed_env):
    load_dotenv(_installed_env)
elif os.path.exists(_repo_env):
    load_dotenv(_repo_env)

from pulldb import __version__
from pulldb.cli.admin_commands import (
    cleanup_cmd,
    disallow_group,
    hosts_group,
    jobs_group,
    run_retention_cleanup_cmd,
    users_group,
)
from pulldb.cli.secrets_commands import secrets_group
from pulldb.cli.settings import settings_group


@click.group(help="pullDB Admin - System administration tool")
@click.version_option(__version__, prog_name="pulldb-admin")
def cli() -> None:
    """CLI entry point for pullDB admin commands.

    This is the main Click group that organizes all pullDB admin subcommands.
    Provides access to settings management and other administrative functions.
    """
    pass


# Register command groups
cli.add_command(settings_group)
cli.add_command(secrets_group)
cli.add_command(jobs_group)
cli.add_command(cleanup_cmd)
cli.add_command(run_retention_cleanup_cmd)
cli.add_command(hosts_group)
cli.add_command(users_group)
cli.add_command(disallow_group)


def main(argv: t.Sequence[str] | None = None) -> int:
    """Main entry point for pulldb-admin CLI.

    Args:
        argv: Command-line arguments. If None, uses sys.argv.

    Returns:
        Exit code: 0 for success, non-zero for errors.
    """
    try:
        cli.main(args=list(argv) if argv is not None else None, standalone_mode=False)
        return 0
    except click.exceptions.NoArgsIsHelpError as exc:
        click.echo(exc.ctx.get_help())
        return 1
    except click.exceptions.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 1
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1 if exc.code else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
