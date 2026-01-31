"""Feature Requests CLI commands for pulldb-admin.

Read-only dev tool for reviewing production feature requests.

Commands:
- list: Show feature requests with filtering options
- show: Display detailed view of a single request
- stats: Show aggregate statistics

This is a DEVELOPMENT TOOL that connects to production to READ feature requests.
Phase 1 is READ-ONLY - no modifications to production data.

HCA Layer: pages (pulldb/cli/)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Coroutine
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

import click

from pulldb.domain.feature_request import FeatureRequestStatus
from pulldb.infra.mysql import MySQLPool
from pulldb.infra.secrets import CredentialResolver
from pulldb.worker.feature_request_service import (
    SORT_COLUMN_CREATED_AT,
    SORT_COLUMN_VOTE_SCORE,
    FeatureRequestService,
)

if TYPE_CHECKING:
    from pulldb.domain.feature_request import FeatureRequest


logger = logging.getLogger(__name__)

# UUID length constant
UUID_FULL_LENGTH = 36

T = TypeVar("T")


# =============================================================================
# Database Connection Helper
# =============================================================================


def _get_production_pool() -> MySQLPool:
    """Create MySQL connection pool for production database.

    Uses AWS Secrets Manager credentials via CredentialResolver.

    Returns:
        MySQLPool connected to production coordination database.

    Raises:
        click.ClickException: If connection fails (FAIL HARD principle).
    """
    try:
        # Use same credential pattern as factory.py
        secret_ref = os.getenv(
            "PULLDB_COORDINATION_SECRET",
            "aws-secretsmanager:/pulldb/mysql/coordination-db",
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
    except Exception as e:
        # FAIL HARD - don't silently degrade
        raise click.ClickException(
            click.style("Connection failed: ", fg="red", bold=True)
            + "Cannot connect to production database.\n"
            + click.style("Details: ", fg="yellow")
            + str(e)
        ) from e


def _get_feature_request_service() -> FeatureRequestService:
    """Get FeatureRequestService connected to production.

    Returns:
        FeatureRequestService instance ready for queries.
    """
    pool = _get_production_pool()
    return FeatureRequestService(pool)


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously.

    The FeatureRequestService uses async methods for consistency with the
    web layer, but CLI commands are synchronous.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create a new one
        return asyncio.run(coro)
    else:
        # Already in an async context (shouldn't happen in CLI, but handle it)
        return loop.run_until_complete(coro)


# =============================================================================
# Output Formatting
# =============================================================================


def _format_status(status: FeatureRequestStatus) -> str:
    """Format status with color coding."""
    colors = {
        FeatureRequestStatus.OPEN: "blue",
        FeatureRequestStatus.IN_PROGRESS: "yellow",
        FeatureRequestStatus.COMPLETE: "green",
        FeatureRequestStatus.DECLINED: "red",
    }
    return click.style(status.value, fg=colors.get(status, "white"))


def _format_date(dt: datetime | None) -> str:
    """Format datetime for display."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_date_short(dt: datetime | None) -> str:
    """Format datetime compactly for tables."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d")


def _truncate(text: str | None, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a formatted table to stdout.

    Simple table formatting without external dependencies.
    """
    if not rows:
        click.echo("No results found.")
        return

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            # Strip ANSI codes for width calculation
            clean_cell = click.unstyle(cell) if isinstance(cell, str) else str(cell)
            col_widths[i] = max(col_widths[i], len(clean_cell))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(click.style(header_line, bold=True))
    click.echo("-" * len(click.unstyle(header_line)))

    # Print rows
    for row in rows:
        # Handle styled cells - ljust based on unstyled width
        cells = []
        for i, cell in enumerate(row):
            clean_cell = click.unstyle(cell) if isinstance(cell, str) else str(cell)
            padding = col_widths[i] - len(clean_cell)
            cells.append(str(cell) + " " * padding)
        click.echo("  ".join(cells))


def _print_detail_field(label: str, value: str | None, label_width: int = 12) -> None:
    """Print a labeled field for detail view."""
    click.echo(
        click.style(f"{label}:".ljust(label_width), fg="cyan", bold=True)
        + (value or "-")
    )


def _print_section_header(title: str) -> None:
    """Print a section header."""
    click.echo()
    click.echo(click.style(f"═══ {title} ", fg="cyan", bold=True) + "═" * 40)


# =============================================================================
# CLI Commands
# =============================================================================


@click.group(
    name="feature-requests",
    help="View production feature requests (read-only)",
)
def feature_requests_group() -> None:
    """Feature requests command group.

    Development tool for reviewing feature requests submitted by users.
    """
    pass


@feature_requests_group.command("list")
@click.option(
    "--status",
    "status_filter",
    type=click.Choice(["open", "in_progress", "complete", "declined"]),
    help="Filter by status",
)
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["votes", "date"]),
    default="votes",
    show_default=True,
    help="Sort order",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    show_default=True,
    help="Number of requests to show",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
def list_requests(
    status_filter: str | None,
    sort_by: str,
    limit: int,
    json_out: bool,
) -> None:
    """List feature requests with optional filters.

    Shows ID, vote count, status, date, and title.
    Default sort is by vote count (highest first).
    """
    service = _get_feature_request_service()

    # Map CLI options to service parameters
    sort_column = (
        SORT_COLUMN_VOTE_SCORE if sort_by == "votes" else SORT_COLUMN_CREATED_AT
    )
    status_list = [status_filter] if status_filter else None

    requests, total = _run_async(
        service.list_requests(
            status_filter=status_list,
            sort_by=sort_column,
            sort_order="desc",
            limit=limit,
        )
    )

    if json_out:
        output = {
            "total": total,
            "showing": len(requests),
            "requests": [
                {
                    "request_id": r.request_id,
                    "title": r.title,
                    "status": r.status.value,
                    "vote_score": r.vote_score,
                    "upvote_count": r.upvote_count,
                    "submitted_by": r.submitted_by_user_code or r.submitted_by_username,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in requests
            ],
        }
        click.echo(json.dumps(output, indent=2))
        return

    if not requests:
        click.echo("No feature requests found matching criteria.")
        return

    # Summary line
    click.echo(
        click.style("Feature Requests ", bold=True)
        + f"(showing {len(requests)} of {total})"
    )
    click.echo()

    # Table output
    headers = ["ID", "VOTES", "STATUS", "DATE", "USER", "TITLE"]
    rows: list[list[str]] = []

    for r in requests:
        rows.append([
            r.request_id[:8],
            str(r.vote_score),
            _format_status(r.status),
            _format_date_short(r.created_at),
            (r.submitted_by_user_code or r.submitted_by_username or "-")[:8],
            _truncate(r.title, 50),
        ])

    _print_table(headers, rows)


@feature_requests_group.command("show")
@click.argument("request_id")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of formatted view",
)
def show_request(request_id: str, json_out: bool) -> None:
    """Show detailed view of a feature request.

    Displays full title, description, vote counts, notes, and admin response.

    REQUEST_ID can be the full UUID or just the first 8 characters.
    """
    service = _get_feature_request_service()

    # Try to find the request - support partial IDs
    request: FeatureRequest | None = _run_async(service.get_request(request_id))

    # If not found with partial ID, try a search
    if request is None and len(request_id) < UUID_FULL_LENGTH:
        # Search for requests starting with this prefix
        requests, _ = _run_async(service.list_requests(limit=100))
        for r in requests:
            if r.request_id.startswith(request_id):
                request = r
                break

    if request is None:
        raise click.ClickException(
            click.style("Not found: ", fg="red", bold=True)
            + f"No feature request found with ID starting with '{request_id}'"
        )

    # Get notes for this request
    notes = _run_async(service.list_notes(request.request_id))

    if json_out:
        created_at_iso = (
            request.created_at.isoformat() if request.created_at else None
        )
        updated_at_iso = (
            request.updated_at.isoformat() if request.updated_at else None
        )
        completed_at_iso = (
            request.completed_at.isoformat() if request.completed_at else None
        )
        output = {
            "request": {
                "request_id": request.request_id,
                "title": request.title,
                "description": request.description,
                "status": request.status.value,
                "vote_score": request.vote_score,
                "upvote_count": request.upvote_count,
                "downvote_count": request.downvote_count,
                "submitted_by_user_id": request.submitted_by_user_id,
                "submitted_by_username": request.submitted_by_username,
                "submitted_by_user_code": request.submitted_by_user_code,
                "created_at": created_at_iso,
                "updated_at": updated_at_iso,
                "completed_at": completed_at_iso,
                "admin_response": request.admin_response,
            },
            "notes": [
                {
                    "note_id": n.note_id,
                    "user_code": n.user_code or n.username,
                    "note_text": n.note_text,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
                for n in notes
            ],
        }
        click.echo(json.dumps(output, indent=2))
        return

    # Formatted detail view
    _print_section_header("Feature Request")

    _print_detail_field("ID", request.request_id)
    _print_detail_field("Status", _format_status(request.status))
    votes_str = (
        f"{request.vote_score} "
        f"(↑{request.upvote_count} ↓{request.downvote_count})"
    )
    _print_detail_field("Votes", votes_str)
    submitted_by = (
        request.submitted_by_user_code or request.submitted_by_username or "-"
    )
    _print_detail_field("Submitted By", submitted_by)
    _print_detail_field("Created", _format_date(request.created_at))
    _print_detail_field("Updated", _format_date(request.updated_at))

    if request.completed_at:
        _print_detail_field("Completed", _format_date(request.completed_at))

    _print_section_header("Title")
    click.echo(request.title)

    if request.description:
        _print_section_header("Description")
        click.echo(request.description)

    if request.admin_response:
        _print_section_header("Admin Response")
        click.echo(click.style(request.admin_response, fg="green"))

    if notes:
        _print_section_header(f"Notes ({len(notes)})")
        for note in notes:
            user = note.user_code or note.username or "unknown"
            date = _format_date(note.created_at)
            click.echo()
            click.echo(
                click.style(f"[{user}] ", fg="yellow", bold=True)
                + click.style(date, fg="white", dim=True)
            )
            click.echo(f"  {note.note_text}")
    else:
        click.echo()
        click.echo(click.style("No notes.", dim=True))


@feature_requests_group.command("stats")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of formatted view",
)
def show_stats(json_out: bool) -> None:
    """Show feature request statistics.

    Displays total count, breakdown by status, and top voted requests.
    """
    service = _get_feature_request_service()

    stats = _run_async(service.get_stats())

    # Get top 5 voted open requests
    top_requests, _ = _run_async(
        service.list_requests(
            status_filter=["open", "in_progress"],
            sort_by=SORT_COLUMN_VOTE_SCORE,
            sort_order="desc",
            limit=5,
        )
    )

    if json_out:
        output = {
            "statistics": {
                "total": stats.total,
                "open": stats.open,
                "in_progress": stats.in_progress,
                "complete": stats.complete,
                "declined": stats.declined,
            },
            "top_voted": [
                {
                    "request_id": r.request_id,
                    "title": r.title,
                    "vote_score": r.vote_score,
                    "status": r.status.value,
                }
                for r in top_requests
            ],
        }
        click.echo(json.dumps(output, indent=2))
        return

    # Formatted stats view
    _print_section_header("Feature Request Statistics")

    click.echo()
    _print_detail_field("Total", str(stats.total), label_width=14)
    _print_detail_field(
        "Open", click.style(str(stats.open), fg="blue"), label_width=14
    )
    _print_detail_field(
        "In Progress",
        click.style(str(stats.in_progress), fg="yellow"),
        label_width=14,
    )
    _print_detail_field(
        "Complete",
        click.style(str(stats.complete), fg="green"),
        label_width=14,
    )
    _print_detail_field(
        "Declined",
        click.style(str(stats.declined), fg="red"),
        label_width=14,
    )

    if top_requests:
        _print_section_header("Top Voted (Open/In Progress)")
        click.echo()

        headers = ["VOTES", "STATUS", "TITLE"]
        rows: list[list[str]] = []

        for r in top_requests:
            rows.append([
                str(r.vote_score),
                _format_status(r.status),
                _truncate(r.title, 60),
            ])

        _print_table(headers, rows)
    else:
        click.echo()
        click.echo(click.style("No open or in-progress requests.", dim=True))
