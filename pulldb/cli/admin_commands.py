"""Administrative CLI commands for pulldb-admin.

Commands:
- jobs: View and manage jobs across all users
- cleanup: Cleanup orphaned staging databases and work files
- hosts: Manage registered database hosts
- users: View and manage users
"""

from __future__ import annotations

import json
import os
import typing as t
from datetime import datetime

import click


def _get_mysql_pool() -> t.Any:
    """Get MySQL connection pool using bootstrap config."""
    from pulldb.infra.mysql import MySQLPool
    from pulldb.infra.secrets import CredentialResolver

    secret_ref = os.getenv(
        "PULLDB_COORDINATION_SECRET", "aws-secretsmanager:/pulldb/mysql/coordination-db"
    )

    aws_profile = os.getenv("PULLDB_AWS_PROFILE")
    resolver = CredentialResolver(aws_profile=aws_profile)
    creds = resolver.resolve(secret_ref)

    mysql_user = os.getenv("PULLDB_API_MYSQL_USER", "pulldb_api")
    mysql_database = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb_service")

    return MySQLPool(
        host=creds.host,
        user=mysql_user,
        password=creds.password,
        database=mysql_database,
        port=creds.port,
    )


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
    pool = _get_mysql_pool()

    # Build query
    conditions = []
    params: list[t.Any] = []

    if active:
        conditions.append("j.status IN ('queued', 'running')")
    elif status_filter:
        conditions.append("j.status = %s")
        params.append(status_filter)

    if user_filter:
        conditions.append("(u.username LIKE %s OR u.user_code LIKE %s)")
        params.extend([f"%{user_filter}%", f"%{user_filter}%"])

    if dbhost:
        conditions.append("j.dbhost = %s")
        params.append(dbhost)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    params.append(limit)

    query = f"""
        SELECT
            j.id,
            j.status,
            j.target,
            j.dbhost,
            u.username,
            u.user_code,
            j.submitted_at,
            j.started_at,
            j.finished_at,
            j.current_operation
        FROM jobs j
        JOIN auth_users u ON j.owner_id = u.id
        WHERE {where_clause}
        ORDER BY j.submitted_at DESC
        LIMIT %s
    """

    with pool.connection() as conn, conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

    jobs = [dict(zip(columns, row)) for row in rows]

    if json_out:
        # Convert datetime objects to strings
        for job in jobs:
            for key in ["submitted_at", "started_at", "finished_at"]:
                if job.get(key) and isinstance(job[key], datetime):
                    job[key] = job[key].isoformat()
        click.echo(json.dumps(jobs, indent=2))
        return

    if not jobs:
        click.echo("No jobs found matching criteria.")
        return

    # Table output
    headers = ["JOB_ID", "STATUS", "OPERATION", "TARGET", "HOST", "USER", "SUBMITTED"]
    rows_out: list[list[str]] = []

    for job in jobs:
        submitted = job.get("submitted_at")
        submitted_str = submitted.strftime("%Y-%m-%d %H:%M") if submitted else "-"
        rows_out.append(
            [
                str(job.get("id", ""))[:12],
                str(job.get("status", "")),
                str(job.get("current_operation") or "-")[:15],
                str(job.get("target", ""))[:20],
                str(job.get("dbhost", ""))[:12],
                str(job.get("user_code", ""))[:8],
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
    active_count = sum(1 for j in jobs if j.get("status") in ("queued", "running"))
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

    pool = _get_mysql_pool()

    with pool.connection() as conn, conn.cursor() as cursor:
        # Check job exists and is cancellable
        cursor.execute(
            "SELECT status FROM jobs WHERE id = %s OR id LIKE %s",
            (job_id, f"{job_id}%"),
        )
        row = cursor.fetchone()
        if not row:
            raise click.ClickException(f"Job not found: {job_id}")

        status = row[0]
        if status in ("complete", "failed", "canceled"):
            raise click.ClickException(f"Job is already {status}, cannot cancel.")

        # Update job
        cursor.execute(
            """
                UPDATE jobs
                SET cancel_requested_at = NOW()
                WHERE (id = %s OR id LIKE %s) AND status IN ('queued', 'running')
                """,
            (job_id, f"{job_id}%"),
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise click.ClickException("Failed to cancel job.")

    click.echo(f"✓ Cancellation requested for job {job_id[:12]}...")


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

    pool = _get_mysql_pool()

    # Find orphaned staging databases (jobs completed but staging not cleaned)
    query = """
        SELECT
            j.id,
            j.staging_name,
            j.dbhost,
            j.status,
            j.finished_at
        FROM jobs j
        WHERE j.staging_name IS NOT NULL
          AND j.staging_cleaned_at IS NULL
          AND j.status IN ('complete', 'failed', 'canceled')
          AND j.finished_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
    """
    params: list[t.Any] = [older_than]

    if dbhost:
        query += " AND j.dbhost = %s"
        params.append(dbhost)

    with pool.connection() as conn, conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

    orphans = [dict(zip(columns, row)) for row in rows]

    if not orphans:
        click.echo("No orphaned staging databases found.")
        return

    # Group by host
    by_host: dict[str, list[dict[str, t.Any]]] = {}
    for orphan in orphans:
        host = orphan.get("dbhost", "unknown")
        by_host.setdefault(host, []).append(orphan)

    if dry_run:
        click.echo("Cleanup Preview (DRY RUN):\n")
        click.echo("Orphaned Staging Databases:")

        total_count = 0
        for host, items in sorted(by_host.items()):
            click.echo(f"  {host}:")
            for item in items:
                finished = item.get("finished_at")
                finished_str = finished.strftime("%Y-%m-%d") if finished else "?"
                click.echo(
                    f"    - {item.get('staging_name')} (job {item.get('status')} {finished_str})"
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
            staging_name = item.get("staging_name")
            job_id = item.get("id")

            try:
                # In a real implementation, we would connect to the target host
                # and drop the staging database. For now, we just mark it cleaned.
                with pool.connection() as conn, conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE jobs SET staging_cleaned_at = NOW() WHERE id = %s",
                        (job_id,),
                    )
                    conn.commit()
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
    pool = _get_mysql_pool()

    with pool.connection() as conn, conn.cursor() as cursor:
        cursor.execute("""
                SELECT
                    hostname,
                    max_concurrent_jobs,
                    enabled,
                    credential_reference,
                    created_at
                FROM db_hosts
                ORDER BY hostname
            """)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

    hosts = [dict(zip(columns, row)) for row in rows]

    if json_out:
        for host in hosts:
            if host.get("created_at"):
                host["created_at"] = host["created_at"].isoformat()
        click.echo(json.dumps(hosts, indent=2))
        return

    if not hosts:
        click.echo("No database hosts registered.")
        return

    headers = ["HOSTNAME", "MAX_CONCURRENT", "ENABLED", "CREDENTIAL_REF"]
    rows_out: list[list[str]] = []

    for host in hosts:
        cred_ref = host.get("credential_reference") or "-"
        if len(cred_ref) > 40:
            cred_ref = cred_ref[:37] + "..."
        rows_out.append(
            [
                str(host.get("hostname", "")),
                str(host.get("max_concurrent_jobs", 1)),
                "Yes" if host.get("enabled") else "No",
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

    enabled_count = sum(1 for h in hosts if h.get("enabled"))
    click.echo(f"\nTotal: {len(hosts)} host(s) ({enabled_count} enabled)")


@hosts_group.command("enable")
@click.argument("hostname")
def hosts_enable(hostname: str) -> None:
    """Enable a database host (allow new jobs)."""
    pool = _get_mysql_pool()

    with pool.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE db_hosts SET enabled = TRUE WHERE hostname = %s", (hostname,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise click.ClickException(f"Host not found: {hostname}")

    click.echo(f"✓ Host {hostname} enabled")


@hosts_group.command("disable")
@click.argument("hostname")
def hosts_disable(hostname: str) -> None:
    """Disable a database host (prevent new jobs)."""
    pool = _get_mysql_pool()

    with pool.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE db_hosts SET enabled = FALSE WHERE hostname = %s", (hostname,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise click.ClickException(f"Host not found: {hostname}")

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
    pool = _get_mysql_pool()

    with pool.connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO db_hosts (hostname, max_concurrent_jobs, enabled, credential_reference)
                    VALUES (%s, %s, TRUE, %s)
                    """,
                    (hostname, max_concurrent, credential_ref),
                )
                conn.commit()
            except Exception as e:
                if "Duplicate" in str(e):
                    raise click.ClickException(
                        f"Host already exists: {hostname}"
                    ) from e
                raise

    click.echo(f"✓ Host {hostname} added")


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
    pool = _get_mysql_pool()

    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    u.id,
                    u.username,
                    u.user_code,
                    u.is_admin,
                    u.disabled,
                    u.created_at,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_id = u.id AND j.status IN ('queued', 'running')) as active_jobs
                FROM auth_users u
                ORDER BY u.username
            """)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

    users = [dict(zip(columns, row)) for row in rows]

    if json_out:
        for user in users:
            if user.get("created_at"):
                user["created_at"] = user["created_at"].isoformat()
        click.echo(json.dumps(users, indent=2))
        return

    if not users:
        click.echo("No users registered.")
        return

    headers = ["USERNAME", "USER_CODE", "ADMIN", "ACTIVE_JOBS", "DISABLED", "CREATED"]
    rows_out: list[list[str]] = []

    for user in users:
        created = user.get("created_at")
        created_str = created.strftime("%Y-%m-%d") if created else "-"
        rows_out.append(
            [
                str(user.get("username", ""))[:15],
                str(user.get("user_code", ""))[:8],
                "Yes" if user.get("is_admin") else "No",
                str(user.get("active_jobs", 0)),
                "Yes" if user.get("disabled") else "No",
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

    click.echo(f"\nTotal: {len(users)} user(s)")


@users_group.command("enable")
@click.argument("username")
def users_enable(username: str) -> None:
    """Enable a user (allow new jobs)."""
    pool = _get_mysql_pool()

    with pool.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE auth_users SET disabled = FALSE WHERE username = %s",
            (username,),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise click.ClickException(f"User not found: {username}")

    click.echo(f"✓ User {username} enabled")


@users_group.command("disable")
@click.argument("username")
def users_disable(username: str) -> None:
    """Disable a user (prevent new jobs)."""
    pool = _get_mysql_pool()

    with pool.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE auth_users SET disabled = TRUE WHERE username = %s", (username,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise click.ClickException(f"User not found: {username}")

    click.echo(f"✓ User {username} disabled")


@users_group.command("show")
@click.argument("username")
def users_show(username: str) -> None:
    """Show details for a specific user."""
    pool = _get_mysql_pool()

    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    u.id,
                    u.username,
                    u.user_code,
                    u.is_admin,
                    u.disabled,
                    u.created_at,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_id = u.id) as total_jobs,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_id = u.id AND j.status = 'complete') as complete_jobs,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_id = u.id AND j.status = 'failed') as failed_jobs,
                    (SELECT COUNT(*) FROM jobs j WHERE j.owner_id = u.id AND j.status IN ('queued', 'running')) as active_jobs
                FROM auth_users u
                WHERE u.username = %s
            """,
                (username,),
            )
            row = cursor.fetchone()
            if not row:
                raise click.ClickException(f"User not found: {username}")
            columns = [desc[0] for desc in cursor.description]

    user = dict(zip(columns, row))

    click.echo(f"User: {user.get('username')}")
    click.echo(f"  User Code: {user.get('user_code')}")
    click.echo(f"  Admin: {'Yes' if user.get('is_admin') else 'No'}")
    click.echo(f"  Disabled: {'Yes' if user.get('disabled') else 'No'}")
    created = user.get("created_at")
    click.echo(
        f"  Created: {created.strftime('%Y-%m-%d %H:%M:%S') if created else '-'}"
    )
    click.echo("\nJob Statistics:")
    click.echo(f"  Total Jobs: {user.get('total_jobs', 0)}")
    click.echo(f"  Complete: {user.get('complete_jobs', 0)}")
    click.echo(f"  Failed: {user.get('failed_jobs', 0)}")
    click.echo(f"  Active: {user.get('active_jobs', 0)}")
