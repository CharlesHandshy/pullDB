"""Entry point for the `pulldb` CLI.

Phase 0 prototype: currently provides placeholder commands. Real logic will
be implemented in Milestone 3.
"""

from __future__ import annotations

import json as json_module
import sys
import typing as t
import uuid
from datetime import datetime

import click

from pulldb import __version__
from pulldb.cli.parse import CLIParseError, parse_restore_args
from pulldb.domain.config import Config
from pulldb.domain.models import Job, JobStatus
from pulldb.infra.metrics import MetricLabels, emit_counter, emit_event
from pulldb.infra.mysql import JobRepository, UserRepository, build_default_pool


def _sanitize_letters(value: str) -> str:
    """Extract only letters from string (lowercase).

    Args:
        value: Input string.

    Returns:
        Lowercase letters-only string.
    """
    return "".join(c.lower() for c in value if c.isalpha())


@click.group(help="pullDB - Development database restore tool")
@click.version_option(__version__, prog_name="pulldb")
def cli() -> None:
    """CLI entry point for pullDB commands.

    This is the main Click group that organizes all pullDB subcommands.
    Currently provides placeholder implementations for restore and status
    commands during the prototype phase.
    """
    pass


@cli.command("restore", help="Validate and submit a restore job (enqueue pending)")
@click.argument("options", nargs=-1)
def restore_cmd(options: tuple[str, ...]) -> None:
    """Validate restore CLI arguments and enqueue job to coordination database.

    Parses and validates CLI options, loads configuration, ensures user exists
    (or creates), generates job specification, and enqueues via JobRepository.

    Raises:
        click.UsageError: On validation failures (FAIL HARD).
        click.ClickException: On MySQL/configuration errors.
    """
    # Step 1: Parse and validate CLI arguments
    try:
        parsed = parse_restore_args(options)
    except CLIParseError as e:  # FAIL HARD surface to user
        raise click.UsageError(str(e)) from e

    # Step 2: Load configuration (MySQL coordination DB credentials)
    try:
        config = Config.minimal_from_env()
    except Exception as e:
        raise click.ClickException(
            f"Configuration error: {e}\n"
            f"Ensure PULLDB_MYSQL_* environment variables are set or "
            f"use .env file in repo root."
        ) from e

    # Step 3: Connect to coordination database
    try:
        pool = build_default_pool(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
        )
        user_repo = UserRepository(pool)
        job_repo = JobRepository(pool)
    except Exception as e:
        raise click.ClickException(
            f"Failed to connect to coordination database at "
            f"{config.mysql_host}/{config.mysql_database}: {e}"
        ) from e

    # Step 4: Get or create user (handles user_code collision)
    try:
        user = user_repo.get_or_create_user(username=parsed.username)
    except Exception as e:
        raise click.ClickException(f"User creation/lookup failed: {e}") from e

    # Step 5: Determine target database name (use finalized user_code)
    if parsed.is_qatemplate:
        target = f"{user.user_code}qatemplate"
    else:
        # Sanitize customer_id (already done in parse, but be explicit)
        sanitized = _sanitize_letters(parsed.customer_id or "")
        target = f"{user.user_code}{sanitized}"

    # Step 6: Generate staging name (target + "_" + first 12 chars of job_id)
    # We'll generate UUID here, then truncate for staging
    job_id = str(uuid.uuid4())
    staging_name = f"{target}_{job_id[:12]}"

    # Step 7: Determine dbhost (default from config if not specified)
    dbhost = parsed.dbhost if parsed.dbhost else config.mysql_host

    # Step 8: Build options dict (not JSON string - Job model expects dict)
    options_dict: dict[str, str] = {
        "customer_id": parsed.customer_id or "",
        "is_qatemplate": str(parsed.is_qatemplate),
        "overwrite": str(parsed.overwrite),
        "raw_tokens": " ".join(parsed.raw_tokens),
    }

    # Step 9: Create Job object
    # Note: submitted_at placeholder; MySQL will set UTC_TIMESTAMP(6) on insert
    job = Job(
        id=job_id,
        owner_user_id=user.user_id,
        owner_username=user.username,
        owner_user_code=user.user_code,
        target=target,
        staging_name=staging_name,
        dbhost=dbhost,
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(),
        options_json=options_dict,
        retry_count=0,
    )

    # Step 10: Enqueue job
    try:
        job_repo.enqueue_job(job)
    except ValueError as e:
        # Likely per-target exclusivity violation
        emit_event(
            "job_enqueue_conflict",
            f"Target busy target={target} dbhost={dbhost}",
            labels=MetricLabels(
                job_id=job_id,
                target=target,
                phase="enqueue",
                status="conflict",
            ),
        )
        raise click.ClickException(
            f"Job submission failed: {e}\n"
            f"A restore is already queued or running for target '{target}' "
            f"on host '{dbhost}'.\n"
            f"Use 'pulldb status' to check active jobs."
        ) from e
    except Exception as e:
        emit_event(
            "job_enqueue_error",
            str(e),
            labels=MetricLabels(
                job_id=job_id,
                target=target,
                phase="enqueue",
                status="error",
            ),
        )
        raise click.ClickException(f"Failed to enqueue job: {e}") from e

    # Step 11: Confirm to user
    emit_counter(
        "jobs_enqueued_total",
        labels=MetricLabels(
            job_id=job_id,
            target=target,
            phase="enqueue",
            status="queued",
        ),
    )
    click.echo("Job submitted successfully!")
    click.echo(f"  job_id: {job_id}")
    click.echo(f"  target: {target}")
    click.echo(f"  staging_name: {staging_name}")
    click.echo("  status: queued")
    click.echo(f"  owner: {user.username} (user_code: {user.user_code})")
    click.echo("\nUse 'pulldb status' to monitor progress.")


MAX_STATUS_LIMIT = 1000


@cli.command("status", help="Show active (queued/running) jobs")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
@click.option(
    "--wide",
    is_flag=True,
    help="Show additional columns",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    show_default=True,
    help="Limit number of rows",
)
def status_cmd(json_out: bool, wide: bool, limit: int) -> None:
    """Show active jobs (queued or running) ordered by submission time.

    Provides a quick view of work in progress. By default outputs a table; use
    --json for machine-readable output.

    FAIL HARD behaviors:
      * Configuration load failures surface with actionable guidance.
      * MySQL connectivity failures include host/database context.
      * Invalid limit (<=0 or >1000) aborts with usage error.

    Args:
        json_out: Emit JSON list of jobs.
        wide: Include staging_name column.
        limit: Max number of rows to display (guard against runaway output).
    """
    if limit <= 0 or limit > MAX_STATUS_LIMIT:
        raise click.UsageError(f"--limit must be between 1 and {MAX_STATUS_LIMIT}")

    # Load minimal configuration (same path as restore)
    try:
        config = Config.minimal_from_env()
    except Exception as e:  # FAIL HARD surface
        raise click.ClickException(
            f"Configuration error: {e}\n"
            f"Ensure PULLDB_MYSQL_* environment variables are set or use .env file."
        ) from e

    # Connect to coordination database
    try:
        pool = build_default_pool(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
        )
        job_repo = JobRepository(pool)
    except Exception as e:
        raise click.ClickException(
            f"Failed to connect to coordination database at "
            f"{config.mysql_host}/{config.mysql_database}: {e}"
        ) from e

    # Fetch active jobs (queued or running)
    try:
        jobs = job_repo.get_active_jobs()[:limit]
    except Exception as e:
        raise click.ClickException(f"Failed querying active jobs: {e}") from e

    if not jobs:
        click.echo(
            "No active jobs. Submit a restore with:\n"
            "  pullDB user=<username> customer=<id>"
        )
        return

    if json_out:
        # Emit compact JSON objects
        out: list[dict[str, t.Any]] = []
        for j in jobs:
            started_dt = getattr(j, "started_at", None)
            out.append(
                {
                    "id": j.id,
                    "target": j.target,
                    "status": j.status.value,
                    "user_code": j.owner_user_code,
                    "submitted_at": (
                        j.submitted_at.isoformat() if j.submitted_at else None
                    ),
                    "started_at": (
                        started_dt.isoformat() if started_dt is not None else None
                    ),
                    **(
                        {"staging_name": j.staging_name}
                        if wide and getattr(j, "staging_name", None)
                        else {}
                    ),
                }
            )
        click.echo(json_module.dumps(out, separators=(",", ":")))
        return

    # Table output
    # Determine column widths
    def _fmt_dt(dt: datetime | None) -> str:
        return dt.isoformat(timespec="seconds") if dt else "—"

    rows: list[tuple[str, str, str, str, str, str]] = []
    for j in jobs:
        rows.append(
            (
                j.status.value,
                j.id[:8],
                j.target,
                j.owner_user_code,
                _fmt_dt(j.submitted_at),
                _fmt_dt(getattr(j, "started_at", None)),
            )
        )

    headers = ["STATUS", "JOB_ID", "TARGET", "USER", "SUBMITTED", "STARTED"]
    if wide:
        headers.append("STAGING")
    # Compute widths
    col_widths = [
        max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers[:6])
    ]
    if wide:
        staging_vals = [getattr(j, "staging_name", "") for j in jobs]
        col_widths.append(max(len("STAGING"), *(len(v) for v in staging_vals)))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for idx, row in enumerate(rows):
        line = "  ".join(row[i].ljust(col_widths[i]) for i in range(len(row)))
        if wide:
            staging_val = getattr(jobs[idx], "staging_name", "")
            line = f"{line}  {staging_val.ljust(col_widths[-1])}"
        click.echo(line)

    click.echo(f"\n{len(rows)} active job(s) displayed (limit={limit}).")


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
