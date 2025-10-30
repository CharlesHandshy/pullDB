"""Entry point for the `pulldb` CLI.

Phase 0 prototype: currently provides placeholder commands. Real logic will
be implemented in Milestone 3.
"""

from __future__ import annotations

import sys
import typing as t

import click

from pulldb import __version__


@click.group(help="pullDB - Development database restore tool")
@click.version_option(__version__, prog_name="pulldb")
def cli() -> None:
    """CLI entry point for pullDB commands.

    This is the main Click group that organizes all pullDB subcommands.
    Currently provides placeholder implementations for restore and status
    commands during the prototype phase.
    """
    pass


@cli.command("restore", help="Submit a restore job (prototype placeholder)")
@click.argument("options", nargs=-1)
def restore_cmd(options: tuple[str, ...]) -> None:
    """Submit a restore job (prototype placeholder).

    Args:
        options: Command-line arguments passed to the restore command.
            Expected format: user=<name> [customer=<id>|qatemplate]
            [dbhost=<host>] [overwrite]
    """
    # Placeholder parsing logic; real implementation will validate and enqueue.
    opts_str = " ".join(options)
    click.echo(
        f"[pulldb] restore command not yet implemented. Received options: {opts_str}"
    )


@cli.command("status", help="Show active/queued jobs (prototype placeholder)")
def status_cmd() -> None:
    """Show active and queued jobs (prototype placeholder).

    Displays current restore job status including pending, running, completed,
    and failed jobs from the MySQL queue.
    """
    click.echo("[pulldb] status command not yet implemented.")


def main(argv: t.Sequence[str] | None = None) -> int:
    """Main entry point for pullDB CLI.

    Args:
        argv: Command-line arguments. If None, uses sys.argv.

    Returns:
        Exit code: 0 for success, non-zero for errors.
    """
    try:
        cli.main(args=list(argv) if argv is not None else None, standalone_mode=False)
        return 0
    except SystemExit as exc:  # click may raise SystemExit
        # exc.code can be str | int | None, but we need to return int
        if isinstance(exc.code, int):
            return exc.code
        return 1 if exc.code else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
