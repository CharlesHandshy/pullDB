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
    pass


@cli.command("restore", help="Submit a restore job (prototype placeholder)")
@click.argument("options", nargs=-1)
def restore_cmd(options: tuple[str, ...]) -> None:
    # Placeholder parsing logic; real implementation will validate and enqueue.
    click.echo("[pulldb] restore command not yet implemented. Received options: " + " ".join(options))


@cli.command("status", help="Show active/queued jobs (prototype placeholder)")
def status_cmd() -> None:
    click.echo("[pulldb] status command not yet implemented.")


def main(argv: t.Sequence[str] | None = None) -> int:
    try:
        cli.main(args=list(argv) if argv is not None else None, standalone_mode=True)
        return 0
    except SystemExit as exc:  # click may raise SystemExit
        return exc.code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
