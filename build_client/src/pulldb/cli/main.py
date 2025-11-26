"""Entry point for the `pulldb` CLI."""

from __future__ import annotations

import importlib
import json as json_module
import os
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

    # Step 2: Relay request to API service
    payload = {
        "user": parsed.username,
        "customer": parsed.customer_id,
        "qatemplate": parsed.is_qatemplate,
        "dbhost": parsed.dbhost,
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
    help="Realtime mode: stream events for a specific job (requires --job-id).",
)
@click.option(
    "--job-id",
    help="Job ID to filter by or stream events for.",
)
def status_cmd(
    json_out: bool,
    wide: bool,
    limit: int,
    active: bool,
    history: bool,
    filter_json: str | None,
    rt: bool,
    job_id: str | None,
) -> None:
    """Show jobs ordered by submission time.

    Provides a view of work in progress and history. By default outputs a table;
    use --json for machine-readable output.

    FAIL HARD behaviors:
      * Configuration load failures surface with actionable guidance.
      * MySQL connectivity failures include host/database context.
      * Invalid limit (<=0 or >1000) aborts with usage error.

    Args:
        json_out: Emit JSON list of jobs.
        wide: Include staging_name column.
        limit: Max number of rows to display.
        active: Show active jobs.
        history: Show historical jobs.
        filter_json: JSON filter string.
        rt: Realtime event streaming mode.
        job_id: Specific job ID to target.
    """
    if rt:
        if not job_id:
            raise click.UsageError("--rt requires --job-id")
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
    
    # If job_id provided without --rt, filter by it (client-side for now as API doesn't support it directly yet,
    # or we could add it to filter_json)
    if job_id:
        # We can use the filter param logic
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
