"""Administrative CLI commands for pulldb-admin.

Commands:
- jobs: View and manage jobs across all users
- cleanup: Cleanup orphaned staging databases and work files
- hosts: Manage registered database hosts
- users: View and manage users

Note: To submit jobs on behalf of other users, use:
  pulldb restore <customer> user=<username>

HCA Layer: pages
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from datetime import datetime

logger = logging.getLogger(__name__)

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
    type=click.Choice(["queued", "running", "deployed", "complete", "failed", "canceled"]),
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

    if job.status.value in ("deployed", "complete", "failed", "canceled"):
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
    by_host: dict[str, list[Any]] = {}
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
                finished = item.completed_at
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
    """Add a new database host (simple registration only).
    
    For full provisioning with MySQL setup, use 'hosts provision' instead.
    """
    from pulldb.infra.factory import get_host_repository

    repo = get_host_repository()
    try:
        repo.add_host(hostname, max_concurrent, credential_ref)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"✓ Host {hostname} added")


@hosts_group.command("provision")
@click.argument("host_alias")
@click.option(
    "--mysql-host",
    required=True,
    help="MySQL server hostname or IP address",
)
@click.option(
    "--mysql-port",
    type=int,
    default=3306,
    show_default=True,
    help="MySQL port",
)
@click.option(
    "--admin-user",
    required=True,
    help="MySQL admin username with CREATE USER privilege",
)
@click.option(
    "--admin-password",
    help="MySQL admin password (will prompt if not provided)",
)
@click.option(
    "--max-running",
    type=int,
    default=1,
    show_default=True,
    help="Maximum concurrent running jobs",
)
@click.option(
    "--max-active",
    type=int,
    default=10,
    show_default=True,
    help="Maximum queued + running jobs",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of step-by-step progress",
)
def hosts_provision(
    host_alias: str,
    mysql_host: str,
    mysql_port: int,
    admin_user: str,
    admin_password: str | None,
    max_running: int,
    max_active: int,
    json_out: bool,
) -> None:
    """Provision a new target host with complete MySQL setup.
    
    This command performs all setup steps:
    
    \b
    1. Test admin MySQL connection
    2. Create pulldb_loader user on target host
    3. Create pulldb_service database on target
    4. Deploy pulldb_atomic_rename stored procedure
    5. Store credentials in AWS Secrets Manager
    6. Register host in pulldb database
    
    The admin credentials are only used during setup and not stored.
    
    Example:
    
    \b
        pulldb-admin hosts provision dev-db-01 \\
            --mysql-host 10.0.1.50 \\
            --admin-user root
    """
    from dataclasses import asdict
    from pulldb.infra.factory import get_provisioning_service, get_user_repository

    # Prompt for password if not provided
    if admin_password is None:
        admin_password = click.prompt("MySQL admin password", hide_input=True)
    assert admin_password is not None  # Assured by click.prompt above

    # Get actor user_id (CLI runs as admin)
    user_repo = get_user_repository()
    admin_user_record = user_repo.get_user_by_username("admin")
    if admin_user_record is None:
        raise click.ClickException(
            "Admin user not found. Ensure database is properly initialized."
        )

    service = get_provisioning_service(admin_user_record.user_id)

    if not json_out:
        click.echo(f"Provisioning host '{host_alias}' ({mysql_host}:{mysql_port})...")
        click.echo()

    result = service.provision_host(
        host_alias=host_alias,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        admin_username=admin_user,
        admin_password=admin_password,
        max_running_jobs=max_running,
        max_active_jobs=max_active,
    )

    if json_out:
        output: dict[str, Any] = {
            "success": result.success,
            "message": result.message,
            "host_id": result.host_id,
            "rollback_performed": result.rollback_performed,
        }
        if result.steps:
            output["steps"] = [
                {
                    "name": step.name,
                    "success": step.success,
                    "message": step.message,
                    "details": step.details,
                }
                for step in result.steps
            ]
        if result.error:
            output["error"] = result.error
        if result.suggestions:
            output["suggestions"] = result.suggestions
        click.echo(json.dumps(output, indent=2))
    else:
        # Step-by-step output
        if result.steps:
            for step in result.steps:
                status = "✓" if step.success else "✗"
                click.echo(f"  {status} {step.name}: {step.message}")
                if step.details and not step.success:
                    click.echo(f"      {step.details}")

        click.echo()
        if result.success:
            click.echo(f"✓ Host '{host_alias}' provisioned successfully")
            click.echo(f"  Host ID: {result.host_id}")
        else:
            click.echo(f"✗ Provisioning failed: {result.message}")
            if result.suggestions:
                click.echo("  Suggestions:")
                for suggestion in result.suggestions:
                    click.echo(f"    - {suggestion}")
            if result.rollback_performed:
                click.echo("  (Rollback performed - newly created resources cleaned up)")

    if not result.success:
        raise SystemExit(1)


@hosts_group.command("test")
@click.argument("mysql_host")
@click.option(
    "--mysql-port",
    type=int,
    default=3306,
    show_default=True,
    help="MySQL port",
)
@click.option(
    "--username",
    required=True,
    help="MySQL username to test",
)
@click.option(
    "--password",
    help="MySQL password (will prompt if not provided)",
)
def hosts_test(
    mysql_host: str,
    mysql_port: int,
    username: str,
    password: str | None,
) -> None:
    """Test MySQL connection to a host.
    
    Used to verify admin credentials before provisioning.
    """
    from pulldb.infra.mysql_provisioning import test_admin_connection

    # Prompt for password if not provided
    if password is None:
        password = click.prompt("MySQL password", hide_input=True)
    assert password is not None  # Assured by click.prompt above

    click.echo(f"Testing connection to {mysql_host}:{mysql_port} as {username}...")

    result = test_admin_connection(
        host=mysql_host,
        port=mysql_port,
        username=username,
        password=password,
    )

    if result.success:
        click.echo(f"✓ {result.message}")
    else:
        click.echo(f"✗ {result.message}")
        if result.error:
            click.echo(f"  Error: {result.error}")
        if result.suggestions:
            click.echo("  Suggestions:")
            for suggestion in result.suggestions:
                click.echo(f"    - {suggestion}")
        raise SystemExit(1)


@hosts_group.command("remove")
@click.argument("hostname")
@click.option(
    "--delete-secret",
    is_flag=True,
    help="Also delete AWS secret (credentials)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation",
)
def hosts_remove(hostname: str, delete_secret: bool, force: bool) -> None:
    """Remove a host from pulldb.
    
    By default only removes the database entry. Use --delete-secret
    to also remove the AWS secret (credentials).
    """
    from pulldb.infra.factory import get_provisioning_service, get_user_repository

    # Confirm deletion
    if not force:
        msg = f"Remove host '{hostname}'"
        if delete_secret:
            msg += " and AWS secret"
        if not click.confirm(f"{msg}?"):
            click.echo("Aborted.")
            return

    # Get actor user_id (CLI runs as admin)
    user_repo = get_user_repository()
    admin_user = user_repo.get_user_by_username("admin")
    if admin_user is None:
        raise click.ClickException(
            "Admin user not found. Ensure database is properly initialized."
        )

    service = get_provisioning_service(admin_user.user_id)

    result = service.delete_host(
        hostname=hostname,
        delete_secret=delete_secret,
        force=force,
    )

    if result.success:
        click.echo(f"✓ {result.message}")
        if result.secret_deleted:
            click.echo("  AWS secret also deleted")
    else:
        click.echo(f"✗ {result.message}")
        if result.error:
            click.echo(f"  Error: {result.error}")
        raise SystemExit(1)


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
            if d.get("disabled_at"):
                d["disabled_at"] = d["disabled_at"].isoformat()
            # Convert UserRole enum to string for JSON serialization
            if d.get("role"):
                d["role"] = d["role"].value
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
    from pulldb.infra.factory import get_auth_repository, get_user_repository

    repo = get_user_repository()
    try:
        repo.enable_user(username)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"✓ User {username} enabled")

    # Check if user has pending API keys that also need approval
    try:
        auth_repo = get_auth_repository()
        user = repo.get_user_by_username(username)
        if user:
            user_keys = auth_repo.get_api_keys_for_user(user.user_id)
            pending_keys = [k for k in user_keys if k.get("approved_at") is None]
            if pending_keys:
                click.echo("")
                click.echo(f"⚠ User has {len(pending_keys)} pending API key(s):")
                for key in pending_keys:
                    host = key.get("host_name") or "unknown"
                    click.echo(f"   - {key['key_id']} (host: {host})")
                click.echo("")
                click.echo("Use 'pulldb-admin keys approve <key_id>' to approve CLI access.")
    except Exception:
        # Don't fail the enable command if key check fails
        logger.debug("Failed to check pending API keys during user enable", exc_info=True)


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


@users_group.command("reset-password")
@click.argument("username")
@click.option(
    "--password",
    default=None,
    help="Set an explicit password instead of generating one.",
)
def users_reset_password(username: str, password: str | None) -> None:
    """Reset a user's password.

    Generates a temporary password (or uses --password) and marks
    the account for password reset on next login.

    Examples:

        pulldb-admin users reset-password admin

        pulldb-admin users reset-password jdoe --password 'MyP@ss123'
    """
    import secrets
    import string

    from pulldb.auth.password import hash_password
    from pulldb.infra.factory import get_auth_repository, get_user_repository

    user_repo = get_user_repository()
    user = user_repo.get_user_by_username(username)
    if not user:
        raise click.ClickException(f"User not found: {username}")

    if password:
        temp_password = password
    else:
        alphabet = string.ascii_letters + string.digits + "!@#$%&*"
        temp_password = "".join(secrets.choice(alphabet) for _ in range(12))

    password_hash = hash_password(temp_password)

    auth_repo = get_auth_repository()
    auth_repo.set_password_hash(user.user_id, password_hash)
    auth_repo.mark_password_reset(user.user_id)

    click.echo(f"✓ Password reset for user: {username}")
    click.echo(f"  Temporary password: {temp_password}")
    click.echo("  User must change password on next login.")


# =============================================================================
# API Keys Command Group
# =============================================================================


@click.group(name="keys", help="Manage API keys for CLI authentication")
def keys_group() -> None:
    """API Keys management command group."""
    pass


@keys_group.command("pending")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
def keys_pending(json_out: bool) -> None:
    """List API keys pending approval.

    Shows keys that have been requested but not yet approved by an admin.
    """
    from pulldb.infra.factory import get_auth_repository, get_user_repository

    auth_repo = get_auth_repository()
    user_repo = get_user_repository()

    pending = auth_repo.get_pending_api_keys()

    # Build username lookup
    user_ids = list({k["user_id"] for k in pending})
    user_lookup: dict[str, str] = {}
    for uid in user_ids:
        u = user_repo.get_user_by_id(uid)
        if u:
            user_lookup[uid] = u.username

    if json_out:
        output = []
        for key in pending:
            output.append(
                {
                    "key_id": key["key_id"],
                    "username": user_lookup.get(key["user_id"], "unknown"),
                    "host_name": key.get("host_name"),
                    "created_from_ip": key.get("created_from_ip"),
                    "created_at": key["created_at"].isoformat() if key.get("created_at") else None,
                }
            )
        click.echo(json.dumps(output, indent=2))
        return

    if not pending:
        click.echo("No pending API keys.")
        return

    click.echo("Pending API Keys:\n")
    click.echo(f"{'KEY_ID':<40} {'USERNAME':<15} {'HOSTNAME':<20} {'CREATED':<20}")
    click.echo("-" * 95)

    for key in pending:
        username = user_lookup.get(key["user_id"], "unknown")
        host = key.get("host_name") or "-"
        created = key.get("created_at")
        created_str = created.strftime("%Y-%m-%d %H:%M") if created else "-"
        click.echo(f"{key['key_id']:<40} {username:<15} {host:<20} {created_str:<20}")

    click.echo(f"\nTotal: {len(pending)} pending key(s)")
    click.echo("\nUse 'pulldb-admin keys approve <key_id>' to approve a key.")


@keys_group.command("approve")
@click.argument("key_id")
def keys_approve(key_id: str) -> None:
    """Approve a pending API key.

    After approval, the key can be used for CLI authentication.
    """
    from pulldb.infra.factory import get_auth_repository, get_user_repository

    auth_repo = get_auth_repository()
    user_repo = get_user_repository()

    # Get admin user ID (current system user)
    import os

    admin_username = os.environ.get("SUDO_USER") or os.environ.get("USER") or "admin"
    admin_user = user_repo.get_user_by_username(admin_username)
    if not admin_user:
        raise click.ClickException(f"Admin user '{admin_username}' not found in pullDB")
    if not admin_user.is_admin:
        raise click.ClickException(f"User '{admin_username}' is not an admin")

    # Get key info first
    key_info = auth_repo.get_api_key_info(key_id)
    if not key_info:
        raise click.ClickException(f"API key '{key_id}' not found")

    if key_info.get("approved_at"):
        raise click.ClickException(f"API key '{key_id}' is already approved")

    # Approve the key
    success = auth_repo.approve_api_key(key_id, admin_user.user_id)
    if not success:
        raise click.ClickException(f"Failed to approve API key '{key_id}'")

    # Get target user info
    target_user = user_repo.get_user_by_id(key_info["user_id"])
    target_name = target_user.username if target_user else "unknown"
    host_name = key_info.get("host_name") or "unknown"

    click.echo(f"✓ API key '{key_id}' approved")
    click.echo(f"  User: {target_name}")
    click.echo(f"  Host: {host_name}")
    click.echo(f"\nThe user can now use the CLI from '{host_name}'.")


@keys_group.command("revoke")
@click.argument("key_id")
@click.option(
    "--reason",
    default=None,
    help="Reason for revocation (logged for audit)",
)
def keys_revoke(key_id: str, reason: str | None) -> None:
    """Revoke an API key.

    The key will no longer work for authentication.
    """
    from pulldb.infra.factory import get_auth_repository, get_user_repository

    auth_repo = get_auth_repository()
    user_repo = get_user_repository()

    # Get key info first
    key_info = auth_repo.get_api_key_info(key_id)
    if not key_info:
        raise click.ClickException(f"API key '{key_id}' not found")

    # Revoke the key
    success = auth_repo.revoke_api_key(key_id)
    if not success:
        raise click.ClickException(f"Failed to revoke API key '{key_id}'")

    # Get target user info
    target_user = user_repo.get_user_by_id(key_info["user_id"])
    target_name = target_user.username if target_user else "unknown"
    host_name = key_info.get("host_name") or "unknown"

    click.echo(f"✓ API key '{key_id}' revoked")
    click.echo(f"  User: {target_name}")
    click.echo(f"  Host: {host_name}")
    if reason:
        click.echo(f"  Reason: {reason}")


@keys_group.command("list")
@click.argument("username", required=False)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show all keys (including revoked)",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
def keys_list(username: str | None, show_all: bool, json_out: bool) -> None:
    """List API keys for a user (or all users).

    Without arguments, lists all active keys.
    With USERNAME, lists keys for that user only.
    """
    from pulldb.infra.factory import get_auth_repository, get_user_repository

    auth_repo = get_auth_repository()
    user_repo = get_user_repository()

    # If username provided, get user_id
    user_id: str | None = None
    if username:
        user = user_repo.get_user_by_username(username)
        if not user:
            raise click.ClickException(f"User '{username}' not found")
        user_id = user.user_id

    # Get keys
    keys = auth_repo.get_all_api_keys(
        user_id=user_id,
        include_inactive=show_all,
    )

    # Build username lookup
    user_ids = list({k["user_id"] for k in keys})
    user_lookup: dict[str, str] = {}
    for uid in user_ids:
        u = user_repo.get_user_by_id(uid)
        if u:
            user_lookup[uid] = u.username

    if json_out:
        output = []
        for key in keys:
            output.append(
                {
                    "key_id": key["key_id"],
                    "username": user_lookup.get(key["user_id"], "unknown"),
                    "host_name": key.get("host_name"),
                    "is_active": bool(key.get("is_active")),
                    "approved": key.get("approved_at") is not None,
                    "last_used_at": key["last_used_at"].isoformat() if key.get("last_used_at") else None,
                    "created_at": key["created_at"].isoformat() if key.get("created_at") else None,
                }
            )
        click.echo(json.dumps(output, indent=2))
        return

    if not keys:
        if username:
            click.echo(f"No API keys found for user '{username}'.")
        else:
            click.echo("No API keys found.")
        return

    click.echo("API Keys:\n")
    click.echo(f"{'KEY_ID':<40} {'USERNAME':<15} {'HOST':<15} {'STATUS':<12} {'LAST_USED':<20}")
    click.echo("-" * 102)

    for key in keys:
        uname = user_lookup.get(key["user_id"], "unknown")
        host = (key.get("host_name") or "-")[:15]
        
        # Determine status
        if not key.get("is_active"):
            status = "revoked"
        elif key.get("approved_at"):
            status = "active"
        else:
            status = "pending"
        
        last_used = key.get("last_used_at")
        last_used_str = last_used.strftime("%Y-%m-%d %H:%M") if last_used else "never"
        
        click.echo(f"{key['key_id']:<40} {uname:<15} {host:<15} {status:<12} {last_used_str:<20}")

    click.echo(f"\nTotal: {len(keys)} key(s)")


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
    all_entries: list[dict[str, Any]] = []

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
    short_help="Drop expired databases past retention",
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
        job_repo=job_repo,  # type: ignore[arg-type]
        user_repo=user_repo,  # type: ignore[arg-type]
        settings_repo=settings_repo,  # type: ignore[arg-type]
    )

    grace_days_str = settings_repo.get_setting("cleanup_grace_days")
    grace_days = int(grace_days_str) if grace_days_str else 7
    candidates = job_repo.get_expired_cleanup_candidates(grace_days=grace_days)  # type: ignore[attr-defined]

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
            by_host: dict[str, list[Any]] = {}
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
        job_repo=job_repo,  # type: ignore[arg-type]
        host_repo=host_repo,  # type: ignore[arg-type]
        settings_repo=settings_repo,  # type: ignore[arg-type]
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

    # Also run terminal job cleanup (failed/canceled record purge)
    from pulldb.worker.cleanup import run_terminal_job_cleanup

    terminal_result = run_terminal_job_cleanup(
        job_repo=job_repo,  # type: ignore[arg-type]
        settings_repo=settings_repo,  # type: ignore[arg-type]
        dry_run=dry_run,
    )

    if terminal_result.candidates_found > 0:
        if json_out:
            click.echo(
                json.dumps(
                    {
                        "terminal_purged": terminal_result.jobs_purged,
                        "terminal_skipped": terminal_result.jobs_skipped,
                        "terminal_candidates": terminal_result.candidates_found,
                        "terminal_errors": terminal_result.errors,
                    }
                )
            )
        else:
            click.echo(f"\nTerminal Job Cleanup:")
            click.echo(f"  Purged: {terminal_result.jobs_purged}")
            click.echo(f"  Skipped: {terminal_result.jobs_skipped}")
            if terminal_result.errors:
                click.echo(f"  Errors: {len(terminal_result.errors)}")
                for error in terminal_result.errors:
                    click.echo(f"    - {error}")


# =============================================================================
# Terminal Job Cleanup Command
# =============================================================================


@click.command(
    name="run-terminal-cleanup",
    short_help="Purge expired failed/canceled job records",
    help="Clean up expired failed/canceled job records from History",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be purged (no changes made)",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of human-readable text",
)
def run_terminal_cleanup_cmd(
    dry_run: bool,
    json_out: bool,
) -> None:
    """Purge expired failed/canceled job records from History.

    This command finds failed and canceled jobs that are past their
    expiration date + grace period and marks them as 'deleted' so
    they no longer clutter the History view.

    Unlike retention cleanup, this does NOT drop any databases —
    failed/canceled jobs never had a live database.

    The cleanup process:
    1. Finds failed/canceled jobs past their expires_at + grace period
    2. Marks each as 'deleted' (soft delete)
    3. Records are preserved for audit but leave the active History view
    """
    from pulldb.infra.factory import get_job_repository, get_settings_repository

    job_repo = get_job_repository()
    settings_repo = get_settings_repository()

    grace_days_str = settings_repo.get_setting("cleanup_grace_days")
    grace_days = int(grace_days_str) if grace_days_str else 7
    candidates = job_repo.get_expired_terminal_job_candidates(grace_days=grace_days)  # type: ignore[attr-defined]

    if not candidates:
        if json_out:
            click.echo(json.dumps({"candidates": 0, "purged": 0}))
        else:
            click.echo("No expired terminal jobs to clean up.")
        return

    if dry_run:
        if json_out:
            data = {
                "mode": "dry_run",
                "candidates": len(candidates),
                "jobs": [
                    {
                        "job_id": job.id,
                        "status": job.status.value,
                        "target": job.target,
                        "owner": job.owner_username,
                        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
                        "error": job.error_detail,
                    }
                    for job in candidates
                ],
            }
            click.echo(json.dumps(data, indent=2))
        else:
            click.echo("Terminal Job Cleanup Preview (DRY RUN):\n")
            click.echo(f"Found {len(candidates)} expired terminal job(s):\n")
            for job in candidates:
                exp_str = (
                    job.expires_at.strftime("%Y-%m-%d")
                    if job.expires_at
                    else "never"
                )
                click.echo(
                    f"  - [{job.status.value}] {job.id[:8]} "
                    f"{job.owner_username}/{job.target} (expired {exp_str})"
                )
            click.echo("\nRun without --dry-run to perform cleanup.")
        return

    # Execute cleanup
    if not json_out:
        click.echo("Executing terminal job cleanup...\n")

    from pulldb.worker.cleanup import run_terminal_job_cleanup

    result = run_terminal_job_cleanup(
        job_repo=job_repo,  # type: ignore[arg-type]
        settings_repo=settings_repo,  # type: ignore[arg-type]
    )

    if json_out:
        click.echo(
            json.dumps(
                {
                    "purged": result.jobs_purged,
                    "skipped": result.jobs_skipped,
                    "candidates": result.candidates_found,
                    "errors": result.errors,
                }
            )
        )
    else:
        click.echo("\nTerminal Job Cleanup Complete:")
        click.echo(f"  Purged: {result.jobs_purged}")
        click.echo(f"  Skipped: {result.jobs_skipped}")
        if result.errors:
            click.echo(f"  Errors: {len(result.errors)}")
            for error in result.errors:
                click.echo(f"    - {error}")


# =============================================================================
# Overlord Command Group
# =============================================================================


@click.group(name="overlord", help="Manage overlord database integration")
def overlord_group() -> None:
    """Overlord integration command group.
    
    Commands for setting up and managing pullDB's access to an external
    overlord database for updating company routing records.
    """
    pass


@overlord_group.command("provision")
@click.option(
    "--host",
    "overlord_host",
    required=True,
    help="Overlord MySQL server hostname",
)
@click.option(
    "--port",
    "overlord_port",
    type=int,
    default=3306,
    show_default=True,
    help="Overlord MySQL port",
)
@click.option(
    "--database",
    "overlord_database",
    default="overlord",
    show_default=True,
    help="Overlord database name",
)
@click.option(
    "--table",
    "overlord_table",
    default="companies",
    show_default=True,
    help="Overlord table name",
)
@click.option(
    "--admin-user",
    required=True,
    help="Admin username with GRANT privilege (not stored)",
)
@click.option(
    "--admin-password",
    default=None,
    help="Admin password (prompts if not provided, not stored)",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output in JSON format",
)
def overlord_provision(
    overlord_host: str,
    overlord_port: int,
    overlord_database: str,
    overlord_table: str,
    admin_user: str,
    admin_password: str | None,
    json_out: bool,
) -> None:
    """Provision pullDB access to overlord database.
    
    This command sets up secure access to an external overlord database:
    
    \b
    1. Test admin MySQL connection
    2. Create pulldb_overlord user with minimal privileges (SELECT, UPDATE)
    3. Store credentials in AWS Secrets Manager
    4. Update pullDB settings with credential reference
    5. Enable overlord integration
    
    The admin credentials are ONLY used to create the service user.
    They are NEVER stored. Users never see the service user password.
    
    Example:
    
    \b
        pulldb-admin overlord provision \\
            --host overlord.example.com \\
            --admin-user root
    """
    from pulldb.domain.services.overlord_provisioning import (
        OverlordProvisioningService,
    )
    from pulldb.infra.factory import (
        get_settings_repository,
        get_user_repository,
        get_audit_repository,
    )

    # Prompt for password if not provided
    if admin_password is None:
        admin_password = click.prompt(
            "MySQL admin password (not stored)",
            hide_input=True,
        )
    assert admin_password is not None

    # Get actor user_id (CLI runs as admin)
    user_repo = get_user_repository()
    admin_user_record = user_repo.get_user_by_username("admin")
    if admin_user_record is None:
        raise click.ClickException(
            "Admin user not found. Ensure database is properly initialized."
        )

    settings_repo = get_settings_repository()
    audit_repo = get_audit_repository()

    service = OverlordProvisioningService(
        settings_repo=settings_repo,
        audit_repo=audit_repo,
        actor_user_id=admin_user_record.user_id,
    )

    if not json_out:
        click.echo(f"Provisioning overlord access to {overlord_host}:{overlord_port}...")
        click.echo()

    result = service.provision(
        overlord_host=overlord_host,
        overlord_port=overlord_port,
        overlord_database=overlord_database,
        overlord_table=overlord_table,
        admin_username=admin_user,
        admin_password=admin_password,
    )

    if json_out:
        output: dict[str, Any] = {
            "success": result.success,
            "message": result.message,
            "rollback_performed": result.rollback_performed,
        }
        if result.steps:
            output["steps"] = [
                {
                    "name": step.name,
                    "success": step.success,
                    "message": step.message,
                    "details": step.details,
                }
                for step in result.steps
            ]
        if result.error:
            output["error"] = result.error
        if result.suggestions:
            output["suggestions"] = result.suggestions
        click.echo(json.dumps(output, indent=2))
    else:
        # Step-by-step output
        if result.steps:
            for step in result.steps:
                status = "✓" if step.success else "✗"
                click.echo(f"  {status} {step.name}: {step.message}")
                if step.details and not step.success:
                    click.echo(f"      {step.details}")

        click.echo()
        if result.success:
            click.echo("✓ Overlord access provisioned successfully")
            click.echo("  Feature is now enabled.")
        else:
            click.echo(f"✗ Provisioning failed: {result.message}")
            if result.suggestions:
                click.echo("  Suggestions:")
                for suggestion in result.suggestions:
                    click.echo(f"    - {suggestion}")
            if result.rollback_performed:
                click.echo("  (Rollback performed - newly created resources cleaned up)")

    if not result.success:
        raise SystemExit(1)


@overlord_group.command("test")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output in JSON format",
)
def overlord_test(json_out: bool) -> None:
    """Test connection to overlord using stored credentials.
    
    Tests connectivity using the configured credential_ref from settings.
    """
    from pulldb.domain.services.overlord_provisioning import (
        OverlordProvisioningService,
    )
    from pulldb.infra.factory import (
        get_settings_repository,
        get_user_repository,
    )

    user_repo = get_user_repository()
    admin_user_record = user_repo.get_user_by_username("admin")
    if admin_user_record is None:
        raise click.ClickException("Admin user not found.")

    settings_repo = get_settings_repository()
    service = OverlordProvisioningService(
        settings_repo=settings_repo,
        audit_repo=None,
        actor_user_id=admin_user_record.user_id,
    )

    result = service.test_connection()

    if json_out:
        click.echo(json.dumps({
            "success": result.success,
            "message": result.message,
            "error": result.error,
            "suggestions": result.suggestions,
        }))
    else:
        if result.success:
            click.echo(f"✓ {result.message}")
        else:
            click.echo(f"✗ {result.message}")
            if result.error:
                click.echo(f"  Error: {result.error}")
            if result.suggestions:
                click.echo("  Suggestions:")
                for suggestion in result.suggestions:
                    click.echo(f"    - {suggestion}")

    if not result.success:
        raise SystemExit(1)


@overlord_group.command("deprovision")
@click.option(
    "--admin-user",
    required=True,
    help="Admin username with DROP USER privilege",
)
@click.option(
    "--admin-password",
    default=None,
    help="Admin password (prompts if not provided)",
)
@click.option(
    "--keep-user",
    is_flag=True,
    help="Don't drop the MySQL user (keep for audit/recovery)",
)
@click.option(
    "--keep-secret",
    is_flag=True,
    help="Don't delete the AWS secret (keep for audit/recovery)",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output in JSON format",
)
@click.confirmation_option(prompt="Remove overlord access? This will disable the integration.")
def overlord_deprovision(
    admin_user: str,
    admin_password: str | None,
    keep_user: bool,
    keep_secret: bool,
    json_out: bool,
) -> None:
    """Remove pullDB access to overlord database.
    
    This command removes the overlord integration:
    
    \b
    1. Drop the pulldb_overlord MySQL user (unless --keep-user)
    2. Delete AWS secret (unless --keep-secret)
    3. Clear overlord settings
    4. Disable overlord feature
    """
    from pulldb.domain.services.overlord_provisioning import (
        OverlordProvisioningService,
    )
    from pulldb.infra.factory import (
        get_settings_repository,
        get_user_repository,
        get_audit_repository,
    )

    # Prompt for password if not provided and we need to drop the user
    if admin_password is None and not keep_user:
        admin_password = click.prompt(
            "MySQL admin password",
            hide_input=True,
        )
    
    # Use empty string if keeping user (won't be used)
    if admin_password is None:
        admin_password = ""

    user_repo = get_user_repository()
    admin_user_record = user_repo.get_user_by_username("admin")
    if admin_user_record is None:
        raise click.ClickException("Admin user not found.")

    settings_repo = get_settings_repository()
    audit_repo = get_audit_repository()

    service = OverlordProvisioningService(
        settings_repo=settings_repo,
        audit_repo=audit_repo,
        actor_user_id=admin_user_record.user_id,
    )

    if not json_out:
        click.echo("Removing overlord access...")
        click.echo()

    result = service.deprovision(
        admin_username=admin_user,
        admin_password=admin_password,
        delete_user=not keep_user,
        delete_secret=not keep_secret,
    )

    if json_out:
        output: dict[str, Any] = {
            "success": result.success,
            "message": result.message,
        }
        if result.steps:
            output["steps"] = [
                {
                    "name": step.name,
                    "success": step.success,
                    "message": step.message,
                    "details": step.details,
                }
                for step in result.steps
            ]
        click.echo(json.dumps(output, indent=2))
    else:
        if result.steps:
            for step in result.steps:
                status = "✓" if step.success else "✗"
                click.echo(f"  {status} {step.name}: {step.message}")

        click.echo()
        if result.success:
            click.echo("✓ Overlord access removed")
        else:
            click.echo(f"✗ Deprovisioning failed: {result.message}")

    if not result.success:
        raise SystemExit(1)
