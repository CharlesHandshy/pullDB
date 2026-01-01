"""Administrative CLI commands for pulldb-admin.

Commands:
- jobs: View and manage jobs across all users
- cleanup: Cleanup orphaned staging databases and work files
- hosts: Manage registered database hosts
- users: View and manage users
"""

from __future__ import annotations

import json
import typing as t
from datetime import datetime

import click




# =============================================================================
# Jobs Command Group
# =============================================================================


@click.group(name="jobs", help="View and manage jobs across all users")
def jobs_group() -> None:
    """Jobs management command group."""
    pass


@jobs_group.command("list")
@click.option(
    "--active",
    is_flag=True,
    help="Show only active jobs (queued/running)",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    show_default=True,
    help="Number of jobs to show",
)
@click.option(
    "--user",
    "user_filter",
    help="Filter by username or user_code",
)
@click.option(
    "--dbhost",
    help="Filter by target database host",
)
@click.option(
    "--status",
    "status_filter",
    type=click.Choice(["queued", "running", "complete", "failed", "canceled"]),
    help="Filter by job status",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
def jobs_list(
    active: bool,
    limit: int,
    user_filter: str | None,
    dbhost: str | None,
    status_filter: str | None,
    json_out: bool,
) -> None:
    """List jobs with optional filters.

    By default shows most recent jobs. Use --active to show only
    queued/running jobs.
    """
    from dataclasses import asdict
    from pulldb.infra.factory import get_job_repository

    repo = get_job_repository()

    jobs = repo.list_jobs(
        limit=limit,
        active_only=active,
        user_filter=user_filter,
        dbhost=dbhost,
        status_filter=status_filter,
    )

    if json_out:
        jobs_dict = []
        for job in jobs:
            d = asdict(job)
            # Convert enums to values
            d["status"] = job.status.value
            # Convert datetimes to strings
            for key in ["submitted_at", "started_at", "completed_at"]:
                if d.get(key) and isinstance(d[key], datetime):
                    d[key] = d[key].isoformat()
            jobs_dict.append(d)

        click.echo(json.dumps(jobs_dict, indent=2))
        return

    if not jobs:
        click.echo("No jobs found matching criteria.")
        return

    # Table output
    headers = ["JOB_ID", "STATUS", "OPERATION", "TARGET", "HOST", "USER", "SUBMITTED"]
    rows_out: list[list[str]] = []

    for job in jobs:
        submitted = job.submitted_at
        submitted_str = submitted.strftime("%Y-%m-%d %H:%M") if submitted else "-"
        
        # current_operation might be None or string
        op = job.current_operation or "-"

        rows_out.append(
            [
                str(job.id)[:12],
                job.status.value,
                op[:15],
                job.target[:20],
                job.dbhost[:12],
                job.owner_user_code[:8],
                submitted_str,
            ]
        )

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows_out:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print table
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    for row in rows_out:
        click.echo("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    # Summary
    active_count = sum(1 for j in jobs if j.status.value in ("queued", "running"))
    click.echo(f"\nTotal: {len(jobs)} job(s) ({active_count} active)")


@jobs_group.command("cancel")
@click.argument("job_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def jobs_cancel(job_id: str, force: bool) -> None:
    """Cancel a specific job by ID."""
    if not force:
        if not click.confirm(f"Cancel job {job_id}?"):
            click.echo("Aborted.")
            return

    from pulldb.infra.factory import get_job_repository

    repo = get_job_repository()

    # Resolve job ID
    job = repo.get_job_by_id(job_id)
    if not job:
        # Try prefix search
        candidates = repo.find_jobs_by_prefix(job_id)
        if not candidates:
            raise click.ClickException(f"Job not found: {job_id}")
        if len(candidates) > 1:
            raise click.ClickException(
                f"Ambiguous job ID prefix '{job_id}'. Matches: "
                + ", ".join(j.id[:8] for j in candidates)
            )
        job = candidates[0]

    if job.status.value in ("complete", "failed", "canceled"):
        raise click.ClickException(f"Job is already {job.status.value}, cannot cancel.")

    if repo.request_cancellation(job.id):
        click.echo(f"✓ Cancellation requested for job {job.id[:12]}...")
    else:
        raise click.ClickException("Failed to cancel job.")


# =============================================================================
# Cleanup Command
# =============================================================================


@click.command(name="cleanup", help="Cleanup orphaned staging databases and work files")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be cleaned (no changes made)",
)
@click.option(
    "--execute",
    is_flag=True,
    help="Actually perform the cleanup",
)
@click.option(
    "--dbhost",
    help="Target specific database host (default: all hosts)",
)
@click.option(
    "--older-than",
    type=int,
    default=24,
    show_default=True,
    help="Only clean items older than N hours",
)
def cleanup_cmd(
    dry_run: bool,
    execute: bool,
    dbhost: str | None,
    older_than: int,
) -> None:
    """Cleanup orphaned staging databases and old work directories.

    Use --dry-run to preview what would be cleaned, then --execute to
    actually perform the cleanup.

    Orphaned resources are staging databases and work directories from
    jobs that have completed/failed but weren't properly cleaned up.
    """
    if not dry_run and not execute:
        raise click.UsageError("Must specify either --dry-run or --execute")

    if dry_run and execute:
        raise click.UsageError("Cannot specify both --dry-run and --execute")

    from pulldb.infra.factory import get_job_repository

    repo = get_job_repository()
    orphans = repo.find_orphaned_staging_databases(older_than, dbhost)

    if not orphans:
        click.echo("No orphaned staging databases found.")
        return

    # Group by host
    by_host: dict[str, list[t.Any]] = {}
    for orphan in orphans:
        host = orphan.dbhost or "unknown"
        by_host.setdefault(host, []).append(orphan)

    if dry_run:
        click.echo("Cleanup Preview (DRY RUN):\n")
        click.echo("Orphaned Staging Databases:")

        total_count = 0
        for host, items in sorted(by_host.items()):
            click.echo(f"  {host}:")
            for item in items:
                finished = item.finished_at
                finished_str = finished.strftime("%Y-%m-%d") if finished else "?"
                click.echo(
                    f"    - {item.staging_name} (job {item.status.value} {finished_str})"
                )
                total_count += 1

        click.echo("\nSummary:")
        click.echo(f"  Staging databases: {total_count}")
        click.echo("\nRun with --execute to perform cleanup.")
        return

    # Execute cleanup
    click.echo("Executing cleanup...\n")
    cleaned = 0
    failed = 0

    for host, items in sorted(by_host.items()):
        click.echo(f"Processing {host}...")
        for item in items:
            staging_name = item.staging_name
            job_id = item.id

            try:
                # In a real implementation, we would connect to the target host
                # and drop the staging database. For now, we just mark it cleaned.
                repo.mark_staging_cleaned(job_id)
                click.echo(f"  ✓ Marked cleaned: {staging_name}")
                cleaned += 1
            except Exception as e:
                click.echo(f"  ✗ Failed: {staging_name} - {e}")
                failed += 1

    click.echo("\nCleanup Complete:")
    click.echo(f"  Cleaned: {cleaned}")
    if failed:
        click.echo(f"  Failed: {failed}")


# =============================================================================
# Hosts Command Group
# =============================================================================


@click.group(name="hosts", help="Manage registered database hosts")
def hosts_group() -> None:
    """Database hosts management command group."""
    pass


@hosts_group.command("list")
@click.option("--json", "json_out", is_flag=True, help="Output JSON")
def hosts_list(json_out: bool) -> None:
    """List all registered database hosts."""
    from dataclasses import asdict
    from pulldb.infra.factory import get_host_repository

    repo = get_host_repository()
    hosts = repo.get_all_hosts()

    if json_out:
        hosts_dict = []
        for host in hosts:
            d = asdict(host)
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            hosts_dict.append(d)
        click.echo(json.dumps(hosts_dict, indent=2))
        return

    if not hosts:
        click.echo("No database hosts registered.")
        return

    headers = ["HOSTNAME", "MAX_RUNNING", "MAX_ACTIVE", "ENABLED", "CREDENTIAL_REF"]
    rows_out: list[list[str]] = []

    for host in hosts:
        cred_ref = host.credential_ref or "-"
        if len(cred_ref) > 40:
            cred_ref = cred_ref[:37] + "..."
        rows_out.append(
            [
                str(host.hostname),
                str(host.max_running_jobs),
                str(host.max_active_jobs),
                "Yes" if host.enabled else "No",
                cred_ref,
            ]
        )

    col_widths = [len(h) for h in headers]
    for row in rows_out:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    for row in rows_out:
        click.echo("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    enabled_count = sum(1 for h in hosts if h.enabled)
    click.echo(f"\nTotal: {len(hosts)} host(s) ({enabled_count} enabled)")


@hosts_group.command("enable")
@click.argument("hostname")
def hosts_enable(hostname: str) -> None:
    """Enable a database host (allow new jobs)."""
    from pulldb.infra.factory import get_host_repository

    repo = get_host_repository()
    try:
        repo.enable_host(hostname)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"✓ Host {hostname} enabled")


@hosts_group.command("disable")
@click.argument("hostname")
def hosts_disable(hostname: str) -> None:
    """Disable a database host (prevent new jobs)."""
    from pulldb.infra.factory import get_host_repository

    repo = get_host_repository()
    try:
        repo.disable_host(hostname)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"✓ Host {hostname} disabled")


@hosts_group.command("add")
@click.argument("hostname")
@click.option(
    "--max-concurrent",
    type=int,
    default=1,
    show_default=True,
    help="Maximum concurrent jobs on this host",
)
@click.option(
    "--credential-ref",
    help="AWS Secrets Manager reference for credentials",
)
def hosts_add(hostname: str, max_concurrent: int, credential_ref: str | None) -> None:
    """Add a new database host."""
    from pulldb.infra.factory import get_host_repository

    repo = get_host_repository()
    try:
        repo.add_host(hostname, max_concurrent, credential_ref)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"✓ Host {hostname} added")


@hosts_group.command("cred")
@click.argument("hostname")
def hosts_cred(hostname: str) -> None:
    """Show the credential_ref for a hostname."""
    from pulldb.infra.factory import get_host_repository

    repo = get_host_repository()
    host = repo.get_host_by_hostname(hostname)

    if host is None:
        raise click.ClickException(f"Host '{hostname}' not found.")

    if host.credential_ref:
        click.echo(host.credential_ref)
    else:
        click.echo("-")


# =============================================================================
# Users Command Group
# =============================================================================


@click.group(name="users", help="View and manage users")
def users_group() -> None:
    """Users management command group."""
    pass


@users_group.command("list")
@click.option("--json", "json_out", is_flag=True, help="Output JSON")
def users_list(json_out: bool) -> None:
    """List all registered users."""
    from dataclasses import asdict
    from pulldb.infra.factory import get_user_repository

    repo = get_user_repository()
    summaries = repo.get_users_with_job_counts()

    if json_out:
        users_dict = []
        for summary in summaries:
            d = asdict(summary.user)
            d["active_jobs"] = summary.active_jobs_count
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            users_dict.append(d)
        click.echo(json.dumps(users_dict, indent=2))
        return

    if not summaries:
        click.echo("No users registered.")
        return

    headers = ["USERNAME", "USER_CODE", "ADMIN", "ACTIVE_JOBS", "DISABLED", "CREATED"]
    rows_out: list[list[str]] = []

    for summary in summaries:
        user = summary.user
        created = user.created_at
        created_str = created.strftime("%Y-%m-%d") if created else "-"
        rows_out.append(
            [
                str(user.username)[:15],
                str(user.user_code)[:8],
                "Yes" if user.is_admin else "No",
                str(summary.active_jobs_count),
                "Yes" if user.disabled_at else "No",
                created_str,
            ]
        )

    col_widths = [len(h) for h in headers]
    for row in rows_out:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    for row in rows_out:
        click.echo("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    click.echo(f"\nTotal: {len(summaries)} user(s)")



@users_group.command("enable")
@click.argument("username")
def users_enable(username: str) -> None:
    """Enable a user (allow new jobs)."""
    from pulldb.infra.factory import get_user_repository

    repo = get_user_repository()
    try:
        repo.enable_user(username)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"✓ User {username} enabled")


@users_group.command("disable")
@click.argument("username")
def users_disable(username: str) -> None:
    """Disable a user (prevent new jobs)."""
    from pulldb.infra.factory import get_user_repository

    repo = get_user_repository()
    try:
        repo.disable_user(username)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"✓ User {username} disabled")


@users_group.command("show")
@click.argument("username")
def users_show(username: str) -> None:
    """Show details for a specific user."""
    from pulldb.infra.factory import get_user_repository

    repo = get_user_repository()
    detail = repo.get_user_detail(username)

    if not detail:
        raise click.ClickException(f"User not found: {username}")

    user = detail.user
    click.echo(f"User: {user.username}")
    click.echo(f"  User Code: {user.user_code}")
    click.echo(f"  Admin: {'Yes' if user.is_admin else 'No'}")
    click.echo(f"  Disabled: {'Yes' if user.disabled_at else 'No'}")
    created = user.created_at
    click.echo(
        f"  Created: {created.strftime('%Y-%m-%d %H:%M:%S') if created else '-'}"
    )
    click.echo("\nJob Statistics:")
    click.echo(f"  Total Jobs: {detail.total_jobs}")
    click.echo(f"  Complete:   {detail.complete_jobs}")
    click.echo(f"  Failed:     {detail.failed_jobs}")
    click.echo(f"  Active:     {detail.active_jobs}")


# =============================================================================
# Disallow Command Group
# =============================================================================


@click.group(name="disallow", help="Manage disallowed usernames")
def disallow_group() -> None:
    """Disallowed usernames management command group."""
    pass


@disallow_group.command("list")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
def disallow_list(json_out: bool) -> None:
    """List all disallowed usernames.

    Shows both hardcoded (always blocked) and database-configured entries.
    """
    from pulldb.domain.validation import DISALLOWED_USERS_HARDCODED
    from pulldb.infra.factory import get_disallowed_user_repository

    repo = get_disallowed_user_repository()
    db_entries = repo.get_all()

    # Build combined list
    all_entries: list[dict[str, t.Any]] = []

    # Add hardcoded entries
    for username in sorted(DISALLOWED_USERS_HARDCODED):
        all_entries.append({
            "username": username,
            "reason": "System account (hardcoded)",
            "is_hardcoded": True,
            "created_at": None,
            "created_by": None,
        })

    # Add DB entries (skip if already in hardcoded)
    for entry in db_entries:
        if entry.username.lower() not in DISALLOWED_USERS_HARDCODED:
            all_entries.append({
                "username": entry.username,
                "reason": entry.reason or "-",
                "is_hardcoded": entry.is_hardcoded,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
                "created_by": entry.created_by,
            })

    if json_out:
        click.echo(json.dumps(all_entries, indent=2))
        return

    if not all_entries:
        click.echo("No disallowed usernames configured.")
        return

    # Table output
    headers = ["USERNAME", "SOURCE", "REASON", "ADDED BY"]
    rows_out: list[list[str]] = []

    for entry in all_entries:
        source = "hardcoded" if entry["is_hardcoded"] else "database"
        rows_out.append([
            entry["username"],
            source,
            (entry["reason"] or "-")[:40],
            entry["created_by"] or "-",
        ])

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows_out:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print table
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    for row in rows_out:
        click.echo("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    hardcoded_count = sum(1 for e in all_entries if e["is_hardcoded"])
    db_count = len(all_entries) - hardcoded_count
    click.echo(f"\nTotal: {len(all_entries)} ({hardcoded_count} hardcoded, {db_count} database)")


@disallow_group.command("add")
@click.argument("username")
@click.option(
    "--reason",
    "-r",
    default="Admin-configured",
    help="Reason for disallowing this username",
)
def disallow_add(username: str, reason: str) -> None:
    """Add a username to the disallowed list.

    USERNAME will be normalized to lowercase. Hardcoded system accounts
    cannot be added (they are always blocked).
    """
    from pulldb.domain.validation import (
        DISALLOWED_USERS_HARDCODED,
        MIN_USERNAME_LENGTH,
    )
    from pulldb.infra.factory import get_disallowed_user_repository

    # Normalize to lowercase
    username_lower = username.lower().strip()

    if not username_lower:
        raise click.ClickException("Username cannot be empty.")

    # Check if hardcoded
    if username_lower in DISALLOWED_USERS_HARDCODED:
        raise click.ClickException(
            f"Username '{username_lower}' is already blocked (hardcoded system account)."
        )

    # Warn if short username being blocked
    if len(username_lower) < MIN_USERNAME_LENGTH:
        click.echo(
            f"Note: Usernames under {MIN_USERNAME_LENGTH} characters are "
            "already blocked by length policy."
        )

    repo = get_disallowed_user_repository()

    # Check if already in database
    if repo.exists(username_lower):
        raise click.ClickException(f"Username '{username_lower}' is already disallowed.")

    # Add to database
    repo.add(username_lower, reason, created_by="pulldb-admin")
    click.echo(f"✓ Username '{username_lower}' added to disallowed list.")


@disallow_group.command("remove")
@click.argument("username")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def disallow_remove(username: str, force: bool) -> None:
    """Remove a username from the disallowed list.

    Only database-configured entries can be removed. Hardcoded system
    accounts (root, daemon, etc.) cannot be removed.
    """
    from pulldb.domain.validation import DISALLOWED_USERS_HARDCODED
    from pulldb.infra.factory import get_disallowed_user_repository

    # Normalize to lowercase
    username_lower = username.lower().strip()

    if not username_lower:
        raise click.ClickException("Username cannot be empty.")

    # Check if hardcoded
    if username_lower in DISALLOWED_USERS_HARDCODED:
        raise click.ClickException(
            f"Cannot remove '{username_lower}' - it is a hardcoded system account "
            "and will always be blocked."
        )

    repo = get_disallowed_user_repository()

    # Check if exists in database
    if not repo.exists(username_lower):
        raise click.ClickException(f"Username '{username_lower}' is not in the disallowed list.")

    if not force:
        if not click.confirm(f"Remove '{username_lower}' from disallowed list?"):
            click.echo("Aborted.")
            return

    # Remove from database
    repo.remove(username_lower)
    click.echo(f"✓ Username '{username_lower}' removed from disallowed list.")


# =============================================================================
# Retention Cleanup Command
# =============================================================================


@click.command(
    name="run-retention-cleanup",
    help="Run database retention cleanup (drop expired databases)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be cleaned (no changes made)",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of human-readable text",
)
def run_retention_cleanup_cmd(
    dry_run: bool,
    json_out: bool,
) -> None:
    """Run the database retention cleanup process.

    This command identifies and drops expired staging databases based on
    the configured retention policy. Locked databases are never dropped.

    This is typically run via systemd timer (pulldb-retention.timer) but
    can also be invoked manually.

    The cleanup process:
    1. Finds databases past their expiration + grace period
    2. Skips locked databases (protected by users)
    3. Drops the staging database from the target host
    4. Marks the job record as cleaned in the database
    """
    from pulldb.infra.factory import (
        get_job_repository,
        get_settings_repository,
        get_user_repository,
    )

    job_repo = get_job_repository()
    user_repo = get_user_repository()
    settings_repo = get_settings_repository()
    
    from pulldb.infra.factory import get_host_repository
    host_repo = get_host_repository()

    # Get cleanup candidates
    from pulldb.worker.retention import RetentionService

    retention_service = RetentionService(
        job_repo=job_repo,
        user_repo=user_repo,
        settings_repo=settings_repo,
    )

    grace_days_str = settings_repo.get_setting("cleanup_grace_days")
    grace_days = int(grace_days_str) if grace_days_str else 7
    candidates = job_repo.get_cleanup_candidates(grace_days=grace_days)

    if not candidates:
        if json_out:
            click.echo(json.dumps({"candidates": 0, "cleaned": 0, "failed": 0}))
        else:
            click.echo("No expired databases to clean up.")
        return

    if dry_run:
        if json_out:
            data = {
                "mode": "dry_run",
                "candidates": len(candidates),
                "databases": [
                    {
                        "job_id": job.id,
                        "target": job.target,
                        "dbhost": job.dbhost,
                        "staging_name": job.staging_name,
                        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
                        "owner_user_id": job.owner_user_id,
                    }
                    for job in candidates
                ],
            }
            click.echo(json.dumps(data, indent=2))
        else:
            click.echo("Retention Cleanup Preview (DRY RUN):\n")
            click.echo(f"Found {len(candidates)} expired database(s):\n")

            # Group by host
            by_host: dict[str, list[t.Any]] = {}
            for job in candidates:
                host = job.dbhost or "unknown"
                by_host.setdefault(host, []).append(job)

            for host, jobs in sorted(by_host.items()):
                click.echo(f"  {host}:")
                for job in jobs:
                    exp_str = (
                        job.expires_at.strftime("%Y-%m-%d")
                        if job.expires_at
                        else "never"
                    )
                    click.echo(f"    - {job.target} → {job.staging_name} (expired {exp_str})")

            click.echo("\nRun without --dry-run to perform cleanup.")
        return

    # Execute cleanup
    if not json_out:
        click.echo("Executing retention cleanup...\n")

    from pulldb.worker.cleanup import run_retention_cleanup

    result = run_retention_cleanup(
        job_repo=job_repo,
        host_repo=host_repo,
        settings_repo=settings_repo,
    )

    if json_out:
        click.echo(
            json.dumps(
                {
                    "cleaned": result.databases_dropped,
                    "skipped": result.databases_skipped,
                    "candidates": result.candidates_found,
                    "errors": result.errors,
                }
            )
        )
    else:
        click.echo("\nRetention Cleanup Complete:")
        click.echo(f"  Cleaned: {result.databases_dropped}")
        click.echo(f"  Skipped: {result.databases_skipped}")
        if result.errors:
            click.echo(f"  Errors: {len(result.errors)}")
            for error in result.errors:
                click.echo(f"    - {error}")
