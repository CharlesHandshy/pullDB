"""Entry point for the `pulldb` CLI."""

from __future__ import annotations

import fnmatch
import importlib
import json as json_module
import os
import re
import sys
import time
import typing as t
from datetime import datetime
from types import ModuleType

import click

from pulldb import __version__
from pulldb.cli.parse import CLIParseError, parse_restore_args


DEFAULT_API_URL = "http://localhost:8080"
DEFAULT_API_TIMEOUT_SECONDS = 30.0
MAX_STATUS_LIMIT = 1000

if t.TYPE_CHECKING:  # pragma: no cover - typing-only import
    import requests as requests_module
    from requests import RequestException, Response
else:
    requests_module = t.cast(ModuleType, importlib.import_module("requests"))
    RequestException = t.cast(
        type[Exception], requests_module.RequestException
    )
    Response = t.cast(type, requests_module.Response)


class _APIError(RuntimeError):
    """Raised when the API returns an unexpected payload."""


def _load_api_config() -> tuple[str, float]:
    """Resolve API base URL and timeout from environment variables."""
    base_url = os.getenv("PULLDB_API_URL", DEFAULT_API_URL).rstrip("/")
    timeout_raw = os.getenv("PULLDB_API_TIMEOUT", str(DEFAULT_API_TIMEOUT_SECONDS))
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:  # FAIL HARD: invalid timeout configuration
        raise click.ClickException(
            "PULLDB_API_TIMEOUT must be a numeric value (seconds). "
            f"Received '{timeout_raw}'."
        ) from exc
    if timeout <= 0:
        raise click.ClickException(
            "PULLDB_API_TIMEOUT must be greater than zero seconds."
        )
    return base_url, timeout


def _api_post(path: str, payload: dict[str, t.Any]) -> dict[str, t.Any]:
    base_url, timeout = _load_api_config()
    url = f"{base_url}{path}"
    try:
        response = requests_module.post(url, json=payload, timeout=timeout)
    except RequestException as exc:
        raise click.ClickException(
            f"Failed to reach pullDB API at {url}: {exc}. "
            "Ensure the API service is running and reachable."
        ) from exc
    # Handle rate limiting (HTTP 429) with user-friendly message
    if response.status_code == 429:
        detail = ""
        try:
            err_payload = response.json()
            if isinstance(err_payload, dict):
                detail = err_payload.get("detail", "")
        except ValueError:
            pass
        if "User limit" in detail:
            raise click.ClickException(
                f"Rate limited: {detail}\n"
                "Tip: Use 'pulldb status' to see your active jobs."
            )
        elif "System at capacity" in detail:
            raise click.ClickException(
                f"Rate limited: {detail}\n"
                "The system is busy. Please try again in a few minutes."
            )
        else:
            raise click.ClickException(
                f"Rate limited: {detail or 'Too many requests'}\n"
                "Please wait before submitting more jobs."
            )
    if response.status_code >= 400:
        raise click.ClickException(_format_api_error(response))
    payload = _parse_json_response(response)
    if isinstance(payload, dict):
        return payload
    raise click.ClickException("Unexpected API response: expected object payload.")


def _api_get(path: str, params: dict[str, t.Any]) -> list[dict[str, t.Any]]:
    base_url, timeout = _load_api_config()
    url = f"{base_url}{path}"
    try:
        response = requests_module.get(url, params=params, timeout=timeout)
    except RequestException as exc:
        raise click.ClickException(
            f"Failed to reach pullDB API at {url}: {exc}. "
            "Ensure the API service is running and reachable."
        ) from exc
    if response.status_code >= 400:
        raise click.ClickException(_format_api_error(response))
    payload = _parse_json_response(response)
    if isinstance(payload, list):
        return payload
    raise click.ClickException(
        "Unexpected API response: expected list payload from status endpoint."
    )


def _parse_json_response(response: Response) -> t.Any:
    try:
        return response.json()
    except ValueError as exc:
        raise click.ClickException(
            "pullDB API returned a non-JSON response. "
            f"Status {response.status_code}, content: {response.text[:200]}"
        ) from exc


def _format_api_error(response: Response) -> str:
    detail: str | None = None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        raw_detail = payload.get("detail") or payload.get("message")
        if isinstance(raw_detail, str) and raw_detail.strip():
            detail = raw_detail.strip()
    if detail:
        return f"API error ({response.status_code}): {detail}"
    text = response.text.strip()
    if text:
        return f"API error ({response.status_code}): {text[:200]}"
    return f"API error ({response.status_code}): {response.reason}"


def _parse_iso(value: t.Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        iso_value = value.strip()
        if not iso_value:
            return None
        if iso_value.endswith("Z"):
            iso_value = iso_value[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(iso_value)
        except ValueError:
            return None
    return None


class _JobSummary(t.Protocol):
    id: str
    target: str
    status: str
    user_code: str
    submitted_at: datetime | None
    started_at: datetime | None
    staging_name: str | None


class _JobRow(t.NamedTuple):
    id: str
    target: str
    status: str
    user_code: str
    submitted_at: datetime | None
    started_at: datetime | None
    staging_name: str | None
    current_operation: str | None
    dbhost: str | None
    source: str | None


def _job_row_from_payload(payload: dict[str, t.Any]) -> _JobRow:
    try:
        job_id = str(payload["id"])
        target = str(payload["target"])
        status = str(payload["status"])
        user_code = str(payload["user_code"])
    except KeyError as exc:
        raise _APIError(f"Missing field in API response: {exc.args[0]}") from exc

    submitted_at = _parse_iso(payload.get("submitted_at"))
    started_at = _parse_iso(payload.get("started_at"))
    staging_name_value = payload.get("staging_name")
    staging_name = str(staging_name_value) if staging_name_value else None
    current_operation = payload.get("current_operation")
    if current_operation:
        current_operation = str(current_operation)
    
    dbhost = payload.get("dbhost")
    if dbhost:
        dbhost = str(dbhost)
    
    source = payload.get("source")
    if source:
        source = str(source)

    return _JobRow(
        id=job_id,
        target=target,
        status=status,
        user_code=user_code,
        submitted_at=submitted_at,
        started_at=started_at,
        staging_name=staging_name,
        current_operation=current_operation,
        dbhost=dbhost,
        source=source,
    )


@click.group(help="pullDB - Development database restore tool")
@click.version_option(__version__, prog_name="pulldb")
def cli() -> None:
    """CLI entry point for pullDB commands.

    This is the main Click group that organizes all pullDB subcommands.
    Provides restore and status commands for end users.

    Note: Administrative commands (settings) are available via pulldb-admin.
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

    # Step 2: Relay request to API service
    payload = {
        "user": parsed.username,
        "customer": parsed.customer_id,
        "qatemplate": parsed.is_qatemplate,
        "dbhost": parsed.dbhost,
        "date": parsed.date,
        "overwrite": parsed.overwrite,
    }

    api_response = _api_post("/api/jobs", payload)

    if not isinstance(api_response, dict):
        raise click.ClickException("Unexpected API response when submitting job.")

    job_id = str(api_response.get("job_id", ""))
    target = str(api_response.get("target", ""))
    staging_name = str(api_response.get("staging_name", ""))
    status = str(api_response.get("status", "")) or "queued"
    owner_username = str(api_response.get("owner_username", parsed.username))
    owner_user_code = str(api_response.get("owner_user_code", ""))

    if not job_id or not target:
        raise click.ClickException("API response missing job_id or target fields.")

    click.echo("Job submitted successfully!")
    click.echo(f"  job_id: {job_id}")
    click.echo(f"  target: {target}")
    if staging_name:
        click.echo(f"  staging_name: {staging_name}")
    click.echo(f"  status: {status}")
    click.echo(
        f"  owner: {owner_username} "
        f"(user_code: {owner_user_code if owner_user_code else 'unknown'})"
    )
    click.echo("\nUse 'pulldb status' to monitor progress.")


@cli.command("status", help="Show active (queued/running) jobs")
@click.argument("job_id", required=False)
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
@click.option(
    "--active",
    is_flag=True,
    help="Show active jobs (queued/running). Default if no other filter specified.",
)
@click.option(
    "--history",
    is_flag=True,
    help="Show historical jobs (completed/failed/canceled).",
)
@click.option(
    "--filter",
    "filter_json",
    help="JSON string to filter results by column values (e.g. '{\"status\": \"failed\"}').",
)
@click.option(
    "--rt",
    is_flag=True,
    help="Realtime mode: stream events for the specified job.",
)
def status_cmd(
    job_id: str | None,
    json_out: bool,
    wide: bool,
    limit: int,
    active: bool,
    history: bool,
    filter_json: str | None,
    rt: bool,
) -> None:
    """Show jobs ordered by submission time.

    Provides a view of work in progress and history. By default outputs a table;
    use --json for machine-readable output. Pass a JOB_ID to filter by that job.

    FAIL HARD behaviors:
      * Configuration load failures surface with actionable guidance.
      * MySQL connectivity failures include host/database context.
      * Invalid limit (<=0 or >1000) aborts with usage error.

    Args:
        job_id: Optional job ID to filter by or stream events for.
        json_out: Emit JSON list of jobs.
        wide: Include staging_name column.
        limit: Max number of rows to display.
        active: Show active jobs.
        history: Show historical jobs.
        filter_json: JSON filter string.
        rt: Realtime event streaming mode.
    """
    if rt:
        if not job_id:
            raise click.UsageError("--rt requires a job_id argument")
        _stream_job_events(job_id)
        return

    if limit <= 0 or limit > MAX_STATUS_LIMIT:
        raise click.UsageError(f"--limit must be between 1 and {MAX_STATUS_LIMIT}")

    params: dict[str, t.Any] = {"limit": limit}
    if active:
        params["active"] = "true"
    if history:
        params["history"] = "true"
    if filter_json:
        params["filter"] = filter_json
    
    # If job_id provided, filter by it
    if job_id:
        current_filter = {}
        if filter_json:
            try:
                current_filter = json_module.loads(filter_json)
            except ValueError:
                pass
        current_filter["id"] = job_id
        params["filter"] = json_module.dumps(current_filter)

    try:
        payloads = _api_get("/api/jobs", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    summaries: list[_JobRow] = []
    for payload in payloads[:limit]:
        try:
            summaries.append(_job_row_from_payload(payload))
        except _APIError as exc:
            raise click.ClickException(str(exc)) from exc

    if not summaries:
        click.echo(
            "No matching jobs found. Submit a restore with:\n"
            "  pullDB user=<username> customer=<id>"
        )
        return

    if json_out:
        if wide:
            filtered = payloads[:limit]
        else:
            filtered = [
                {key: value for key, value in entry.items() if key != "staging_name"}
                for entry in payloads[:limit]
            ]
        click.echo(json_module.dumps(filtered, separators=(",", ":")))
        return

    # Table output
    # Determine column widths
    def _fmt_dt(dt: datetime | None) -> str:
        return dt.isoformat(timespec="seconds") if dt else "—"

    primary_rows: list[list[str]] = []
    staging_values: list[str] = []
    for summary in summaries:
        primary_rows.append(
            [
                summary.status,
                summary.current_operation or "—",
                summary.id[:8],
                summary.source or "—",
                summary.target,
                summary.dbhost or "—",
                summary.user_code,
                _fmt_dt(summary.submitted_at),
                _fmt_dt(summary.started_at),
            ]
        )
        staging_values.append(summary.staging_name or "")

    headers = ["STATUS", "OPERATION", "JOB_ID", "SOURCE", "TARGET", "DB", "USER", "SUBMITTED", "STARTED"]
    if wide:
        headers.append("STAGING")
    # Compute widths
    col_widths: list[int] = []
    for idx, header in enumerate(headers[:9]):
        col_widths.append(max(len(header), *(len(row[idx]) for row in primary_rows)))
    if wide:
        col_widths.append(max(len("STAGING"), *(len(v) for v in staging_values)))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for idx, entry in enumerate(primary_rows):
        line = "  ".join(entry[i].ljust(col_widths[i]) for i in range(9))
        if wide:
            staging_val = staging_values[idx]
            line = f"{line}  {staging_val.ljust(col_widths[-1])}"
        click.echo(line)

    click.echo(f"\n{len(primary_rows)} recent job(s) displayed (limit={limit}).")


@cli.command("search", help="Search for available backups by customer name")
@click.argument("customer")
@click.option(
    "--date",
    "start_date",
    help="Start date in YYYYMMDD format (show backups from this date onwards)",
)
@click.option(
    "--limit",
    type=int,
    default=5,
    show_default=True,
    help="Maximum number of backups to show",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
@click.option(
    "--env",
    "environment",
    type=click.Choice(["staging", "prod", "both"]),
    default="both",
    show_default=True,
    help="Which S3 environment to search",
)
def search_cmd(
    customer: str,
    start_date: str | None,
    limit: int,
    json_out: bool,
    environment: str,
) -> None:
    """Search for available backups by customer name.

    Supports wildcard patterns (e.g., 'acme*' to match all customers starting
    with 'acme'). Shows the most recent backups first.

    Examples:
        pulldb search actionpest           # Last 5 backups for actionpest
        pulldb search action*              # Last 5 backups matching action*
        pulldb search actionpest --date 20251101  # Backups from Nov 1, 2025 onwards
        pulldb search actionpest --limit 10       # Last 10 backups
    """
    # Validate date format if provided
    filter_date: datetime | None = None
    if start_date:
        if not re.match(r"^\d{8}$", start_date):
            raise click.UsageError(
                f"Invalid date format: '{start_date}'. Use YYYYMMDD (e.g., 20251101)"
            )
        try:
            filter_date = datetime.strptime(start_date, "%Y%m%d")
        except ValueError as e:
            raise click.UsageError(f"Invalid date: {start_date}") from e

    if limit <= 0 or limit > 100:
        raise click.UsageError("--limit must be between 1 and 100")

    # Determine if customer contains a wildcard
    has_wildcard = "*" in customer or "?" in customer

    # Import S3 utilities
    from pulldb.infra.s3 import S3Client, BACKUP_FILENAME_REGEX

    # Get S3 configuration from environment
    s3_profile = os.getenv("PULLDB_S3_AWS_PROFILE") or os.getenv("PULLDB_AWS_PROFILE")

    # Define bucket configurations
    buckets: list[tuple[str, str, str, str | None]] = []  # (name, bucket, prefix, profile)
    
    if environment in ("staging", "both"):
        buckets.append((
            "staging",
            "pestroutesrdsdbs",
            "daily/stg/",
            os.getenv("PULLDB_S3_STAGING_PROFILE", "pr-staging"),
        ))
    
    if environment in ("prod", "both"):
        buckets.append((
            "production",
            "pestroutes-rds-backup-prod-vpc-us-east-1-s3",
            "daily/prod/",
            os.getenv("PULLDB_S3_PROD_PROFILE", "pr-prod"),
        ))

    s3 = S3Client(profile=s3_profile)

    all_backups: list[dict[str, t.Any]] = []

    for env_name, bucket, prefix, profile in buckets:
        try:
            if has_wildcard:
                # For wildcards, we need to list all directories and filter
                # List the prefix to get customer directories
                click.echo(f"Searching {env_name} bucket for '{customer}'...", err=True)
                keys = s3.list_keys(bucket, prefix, profile=profile)
                
                # Extract unique customer names from keys
                customer_dirs: set[str] = set()
                for key in keys:
                    # Keys look like: daily/stg/customerX/daily_mydumper_customerX_...
                    parts = key[len(prefix):].split("/")
                    if parts:
                        customer_dirs.add(parts[0])
                
                # Filter by wildcard pattern
                matching_customers = [
                    c for c in customer_dirs
                    if fnmatch.fnmatch(c.lower(), customer.lower())
                ]
                
                if not matching_customers:
                    continue
                
                # Search each matching customer
                for cust in matching_customers[:20]:  # Limit to avoid too many API calls
                    _search_customer_backups(
                        s3, bucket, prefix, cust, profile, env_name,
                        filter_date, all_backups
                    )
            else:
                # Direct search for specific customer
                _search_customer_backups(
                    s3, bucket, prefix, customer, profile, env_name,
                    filter_date, all_backups
                )
        except Exception as e:
            click.echo(f"Warning: Error searching {env_name}: {e}", err=True)

    if not all_backups:
        click.echo(f"No backups found for '{customer}'")
        if has_wildcard:
            click.echo("Try a more specific pattern or check the customer name.")
        return

    # Sort by timestamp descending (newest first)
    all_backups.sort(key=lambda x: x["timestamp"], reverse=True)

    # Apply date filter if provided
    if filter_date:
        all_backups = [
            b for b in all_backups
            if b["timestamp"] >= filter_date
        ]
        if not all_backups:
            click.echo(f"No backups found for '{customer}' on or after {start_date}")
            return

    # Limit results
    all_backups = all_backups[:limit]

    if json_out:
        # Convert datetime to ISO string for JSON
        output = []
        for b in all_backups:
            output.append({
                "customer": b["customer"],
                "timestamp": b["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "date": b["timestamp"].strftime("%Y%m%d"),
                "size_mb": round(b["size_bytes"] / (1024 * 1024), 1),
                "environment": b["environment"],
                "key": b["key"],
            })
        click.echo(json_module.dumps(output, indent=2))
        return

    # Table output
    click.echo(f"\nBackups matching '{customer}':\n")
    
    headers = ["CUSTOMER", "DATE", "TIME (UTC)", "SIZE", "ENV", "FILENAME"]
    rows: list[list[str]] = []
    
    for b in all_backups:
        ts = b["timestamp"]
        size_mb = b["size_bytes"] / (1024 * 1024)
        if size_mb >= 1024:
            size_str = f"{size_mb / 1024:.1f} GB"
        else:
            size_str = f"{size_mb:.1f} MB"
        
        filename = b["key"].rsplit("/", 1)[-1]
        # Truncate long filenames
        if len(filename) > 50:
            filename = filename[:47] + "..."
        
        rows.append([
            b["customer"],
            ts.strftime("%Y-%m-%d"),
            ts.strftime("%H:%M:%S"),
            size_str,
            b["environment"][:4],  # stag or prod
            filename,
        ])

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for row in rows:
        click.echo("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    click.echo(f"\n{len(rows)} backup(s) found.")
    if len(all_backups) == limit:
        click.echo(f"(showing first {limit}, use --limit to see more)")


def _search_customer_backups(
    s3: t.Any,
    bucket: str,
    prefix: str,
    customer: str,
    profile: str | None,
    env_name: str,
    filter_date: datetime | None,
    results: list[dict[str, t.Any]],
) -> None:
    """Search for backups of a specific customer and append to results."""
    from pulldb.infra.s3 import BACKUP_FILENAME_REGEX

    search_prefix = f"{prefix}{customer}/daily_mydumper_{customer}_"
    
    try:
        keys = s3.list_keys(bucket, search_prefix, profile=profile)
    except Exception as e:
        # Silently skip customers we can't access
        return

    for key in keys:
        filename = key.rsplit("/", 1)[-1]
        match = BACKUP_FILENAME_REGEX.match(filename)
        if not match:
            continue
        
        ts_str = match.group("ts")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%SZ")
        except ValueError:
            continue

        # Get size via HEAD (only for recent backups to avoid too many API calls)
        # Skip if we have a date filter and this is before the filter
        if filter_date and ts < filter_date:
            continue

        try:
            head = s3.head_object(bucket, key, profile=profile)
            size_bytes = int(head.get("ContentLength", 0))
        except Exception:
            size_bytes = 0

        results.append({
            "customer": customer,
            "timestamp": ts,
            "size_bytes": size_bytes,
            "environment": env_name,
            "bucket": bucket,
            "key": key,
        })


def _stream_job_events(job_id: str) -> None:
    last_id: int | None = None
    click.echo(f"Streaming events for job {job_id} (Ctrl+C to stop)...")
    while True:
        params: dict[str, t.Any] = {}
        if last_id is not None:
            params["since_id"] = last_id
        
        try:
            events = _api_get(f"/api/jobs/{job_id}/events", params)
        except _APIError as exc:
             click.echo(f"Error fetching events: {exc}")
             time.sleep(5)
             continue

        for event in events:
            ts = _parse_iso(event.get("logged_at"))
            ts_str = ts.strftime("%H:%M:%S") if ts else "??:??:??"
            event_type = event.get("event_type", "unknown")
            detail = event.get("detail") or ""
            click.echo(f"[{ts_str}] {event_type}: {detail}")
            last_id = int(event["id"])
        
        time.sleep(2)


@cli.command("cancel", help="Cancel a queued or running job")
@click.argument("job_id")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompt",
)
def cancel_cmd(job_id: str, force: bool) -> None:
    """Request cancellation of a job.

    For queued jobs, cancellation is immediate.
    For running jobs, the worker will stop at the next checkpoint
    (between major operations like download, restore, post-SQL).

    Args:
        job_id: UUID of the job to cancel (can use short prefix).
        force: Skip confirmation prompt.

    Examples:
        pulldb cancel abc12345-6789-...   # Full job ID
        pulldb cancel abc12345            # Short prefix (will validate)
        pulldb cancel abc12345 --force    # Skip confirmation
    """
    # Validate job_id format (at least 8 chars for short form)
    if len(job_id) < 8:
        raise click.UsageError(
            "Job ID must be at least 8 characters. "
            "Use 'pulldb status' to find job IDs."
        )

    # Confirm unless --force
    if not force:
        click.echo(f"Requesting cancellation for job: {job_id}")
        if not click.confirm("Are you sure you want to cancel this job?"):
            click.echo("Aborted.")
            return

    try:
        response = _api_post(f"/api/jobs/{job_id}/cancel", {})
    except click.ClickException:
        # Re-raise click exceptions (404, 409, etc. formatted by _api_post)
        raise

    status = response.get("status", "unknown")
    message = response.get("message", "")

    if status == "canceled":
        click.echo(f"✓ Job {job_id[:8]}... canceled successfully.")
        click.echo(f"  {message}")
    elif status == "pending":
        click.echo(f"⏳ Cancellation requested for job {job_id[:8]}...")
        click.echo(f"  {message}")
        click.echo("\nUse 'pulldb status --job-id {job_id}' to monitor.")
    else:
        click.echo(f"Unexpected status: {status}")
        click.echo(f"  {message}")


@cli.command("events", help="Show event log for a job")
@click.argument("job_id")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Follow mode: stream new events as they occur (Ctrl+C to stop)",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    show_default=True,
    help="Maximum number of events to show",
)
def events_cmd(job_id: str, json_out: bool, follow: bool, limit: int) -> None:
    """Show detailed event log for a job.

    Displays timestamped events including job state transitions, progress
    updates, and any errors. Use --follow to stream events in realtime.

    Args:
        job_id: UUID of the job (can use short prefix, minimum 8 chars).
        json_out: Output raw JSON instead of formatted table.
        follow: Stream events as they occur (Ctrl+C to stop).
        limit: Maximum number of events to retrieve.

    Examples:
        pulldb events abc12345-6789-...   # Show all events
        pulldb events abc12345 --follow   # Stream events
        pulldb events abc12345 --json     # JSON output
    """
    # Validate job_id format
    if len(job_id) < 8:
        raise click.UsageError(
            "Job ID must be at least 8 characters. "
            "Use 'pulldb status' to find job IDs."
        )

    if follow:
        _stream_job_events(job_id)
        return

    # Fetch events
    params: dict[str, t.Any] = {"limit": limit}
    try:
        events = _api_get(f"/api/jobs/{job_id}/events", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    if not events:
        click.echo(f"No events found for job {job_id[:8]}...")
        return

    if json_out:
        click.echo(json_module.dumps(events, indent=2, default=str))
        return

    # Table output
    click.echo(f"Events for job {job_id[:8]}...\n")

    headers = ["TIMESTAMP", "EVENT TYPE", "DETAIL"]
    rows: list[list[str]] = []

    for event in events:
        ts = _parse_iso(event.get("logged_at"))
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "-"
        event_type = event.get("event_type", "unknown")
        detail = event.get("detail") or "-"
        # Truncate long details
        if len(detail) > 60:
            detail = detail[:57] + "..."
        rows.append([ts_str, event_type, detail])

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for row in rows:
        line = "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        click.echo(line)

    click.echo(f"\nTotal: {len(events)} event(s)")


@cli.command("history", help="Show job history (completed/failed/canceled jobs)")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Limit number of rows",
)
@click.option(
    "--days",
    type=int,
    default=30,
    show_default=True,
    help="Show jobs from last N days",
)
@click.option(
    "--user",
    "user_code",
    help="Filter by user code",
)
@click.option(
    "--target",
    help="Filter by target database name",
)
@click.option(
    "--dbhost",
    help="Filter by database host",
)
@click.option(
    "--status",
    "job_status",
    type=click.Choice(["complete", "failed", "canceled"]),
    help="Filter by job status",
)
@click.option(
    "--wide",
    is_flag=True,
    help="Show additional columns including error details",
)
def history_cmd(
    json_out: bool,
    limit: int,
    days: int,
    user_code: str | None,
    target: str | None,
    dbhost: str | None,
    job_status: str | None,
    wide: bool,
) -> None:
    """Show job history with filtering options.

    By default shows the last 30 days of completed, failed, and canceled jobs.
    Use --status to filter by specific outcome. Use --wide for error details.

    Examples:
        pulldb history                    # Last 30 days
        pulldb history --days 7           # Last week
        pulldb history --status failed    # Only failed jobs
        pulldb history --user jdoe        # Jobs by user code
        pulldb history --wide             # Include error details
    """
    if limit <= 0 or limit > 1000:
        raise click.UsageError("--limit must be between 1 and 1000")

    if days <= 0 or days > 365:
        raise click.UsageError("--days must be between 1 and 365")

    # Build query params
    params: dict[str, t.Any] = {
        "limit": limit,
        "days": days,
    }
    if user_code:
        params["user_code"] = user_code
    if target:
        params["target"] = target
    if dbhost:
        params["dbhost"] = dbhost
    if job_status:
        params["status"] = job_status

    try:
        history = _api_get("/api/jobs/history", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    if not history:
        click.echo("No job history found matching filters.")
        return

    if json_out:
        click.echo(json_module.dumps(history, indent=2, default=str))
        return

    # Table output
    def _fmt_dt(dt_str: str | None) -> str:
        if not dt_str:
            return "-"
        dt = _parse_iso(dt_str)
        if dt:
            return dt.strftime("%Y-%m-%d %H:%M")
        return "-"

    def _fmt_duration(seconds: float | None) -> str:
        if seconds is None:
            return "-"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            return f"{seconds / 60:.1f}m"
        return f"{seconds / 3600:.1f}h"

    def _status_icon(status: str) -> str:
        if status == "complete":
            return "✓"
        if status == "failed":
            return "✗"
        if status == "canceled":
            return "○"
        return "?"

    # Determine columns
    headers = ["STATUS", "JOB_ID", "TARGET", "USER", "COMPLETED", "DURATION"]
    if wide:
        headers.append("ERROR")

    rows: list[list[str]] = []
    for item in history:
        status_val = item.get("status", "?")
        row = [
            f"{_status_icon(status_val)} {status_val}",
            item.get("id", "")[:12],
            item.get("target", "")[:20],
            item.get("user_code", "")[:6],
            _fmt_dt(item.get("completed_at")),
            _fmt_duration(item.get("duration_seconds")),
        ]
        if wide:
            error = item.get("error_detail") or "-"
            if len(error) > 40:
                error = error[:37] + "..."
            row.append(error)
        rows.append(row)

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for row in rows:
        line = "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        click.echo(line)

    # Summary
    complete_count = sum(1 for item in history if item.get("status") == "complete")
    failed_count = sum(1 for item in history if item.get("status") == "failed")
    canceled_count = sum(1 for item in history if item.get("status") == "canceled")

    click.echo(f"\n{len(history)} job(s): {complete_count} complete, {failed_count} failed, {canceled_count} canceled")
    click.echo(f"(showing last {days} days, limit {limit})")


@cli.command("profile", help="Show performance profile for a completed job")
@click.argument("job_id")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of formatted display",
)
def profile_cmd(job_id: str, json_out: bool) -> None:
    """Show performance profile for a completed job.

    Displays timing breakdown by restore phase (discovery, download,
    extraction, myloader, post_sql, metadata, atomic_rename) with
    throughput metrics for data-intensive phases.

    Profile data is available after a job completes (success or failure).

    Args:
        job_id: UUID of the job to get profile for (can use short prefix).
        json_out: Output raw JSON instead of formatted display.

    Examples:
        pulldb profile abc12345-6789-...   # Full job ID
        pulldb profile abc12345            # Short prefix
        pulldb profile abc12345 --json     # Raw JSON output
    """
    # Validate job_id format (at least 8 chars for short form)
    if len(job_id) < 8:
        raise click.UsageError(
            "Job ID must be at least 8 characters. "
            "Use 'pulldb status' or 'pulldb history' to find job IDs."
        )

    base_url, timeout = _load_api_config()
    url = f"{base_url}/api/jobs/{job_id}/profile"
    try:
        response = requests_module.get(url, timeout=timeout)
    except RequestException as exc:
        raise click.ClickException(
            f"Failed to reach pullDB API: {exc}. "
            "Ensure the API service is running and reachable."
        ) from exc

    if response.status_code == 404:
        error_detail = response.json().get("detail", "Not found")
        raise click.ClickException(error_detail)
    if response.status_code >= 400:
        raise click.ClickException(_format_api_error(response))

    profile = _parse_json_response(response)
    if not isinstance(profile, dict):
        raise click.ClickException("Unexpected API response: expected object payload.")

    if json_out:
        click.echo(json_module.dumps(profile, indent=2, default=str))
        return

    # Formatted display
    job_id_short = profile.get("job_id", "unknown")[:12]
    total_duration = profile.get("total_duration_seconds")
    total_bytes = profile.get("total_bytes", 0)
    error = profile.get("error")

    click.echo(f"Performance Profile: {job_id_short}...")
    click.echo("=" * 60)

    if error:
        click.echo(f"Status: Failed - {error}")
    else:
        click.echo("Status: Complete")

    if total_duration:
        click.echo(f"Total Duration: {_format_profile_duration(total_duration)}")
    if total_bytes:
        click.echo(f"Total Data: {_format_bytes(total_bytes)}")

    click.echo("\nPhase Breakdown:")
    click.echo("-" * 60)

    # Table headers
    click.echo(f"{'PHASE':<16} {'DURATION':>12} {'%':>8} {'THROUGHPUT':>12}")
    click.echo(f"{'-'*16} {'-'*12} {'-'*8} {'-'*12}")

    phases = profile.get("phases", {})
    breakdown = profile.get("phase_breakdown_percent", {})

    # Order phases logically
    phase_order = [
        "discovery",
        "download",
        "extraction",
        "myloader",
        "post_sql",
        "metadata",
        "atomic_rename",
    ]

    for phase_name in phase_order:
        if phase_name not in phases:
            continue
        phase = phases[phase_name]
        duration = phase.get("duration_seconds")
        pct = breakdown.get(phase_name, 0)
        mbps = phase.get("mbps")

        duration_str = _format_profile_duration(duration) if duration else "-"
        pct_str = f"{pct:.1f}%" if pct else "-"
        throughput_str = f"{mbps:.1f} MB/s" if mbps else "-"

        click.echo(f"{phase_name:<16} {duration_str:>12} {pct_str:>8} {throughput_str:>12}")

    click.echo("-" * 60)

    # Tips based on profile
    if breakdown:
        slowest = max(breakdown.items(), key=lambda x: x[1])
        if slowest[1] > 50:
            click.echo(f"\n💡 Tip: {slowest[0]} took {slowest[1]:.0f}% of total time.")


def _format_profile_duration(seconds: float | None) -> str:
    """Format duration for profile display."""
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.0f}s"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    return f"{hours}h {mins}m"


def _format_bytes(num_bytes: int) -> str:
    """Format bytes for human-readable display."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


# NOTE: Admin-only commands (prune-logs, cleanup-staging, orphan-report, delete-orphans)
# are NOT exposed in the user-facing pulldb CLI.
# They will be available via the pulldb-admin CLI.
# See docs/KNOWLEDGE-POOL.md "CLI Architecture & Scope" for rationale.


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
    except SystemExit as exc:  # click may raise SystemExit
        # exc.code can be str | int | None, but we need to return int
        if isinstance(exc.code, int):
            return exc.code
        return 1 if exc.code else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
