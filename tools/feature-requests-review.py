#!/usr/bin/env python3
"""Feature Requests Review Tool - Dev/AI Agent Only.

A standalone development tool for reviewing production feature requests.
NOT part of the pullDB package - this is for developer/AI agent workflows only.

Usage:
    python tools/feature-requests-review.py list [--status open] [--limit 20]
    python tools/feature-requests-review.py show <id>
    python tools/feature-requests-review.py stats
    python tools/feature-requests-review.py list --json  # For AI agent parsing

Environment:
    AWS_PROFILE or PULLDB_AWS_PROFILE: AWS profile for credentials
    PULLDB_COORDINATION_SECRET: Secret path (default: see code)
    PULLDB_API_MYSQL_USER: MySQL user (default: pulldb_api)
    PULLDB_MYSQL_DATABASE: Database name (default: pulldb_service)

Example:
    # List open requests sorted by votes
    AWS_PROFILE=pr-dev python tools/feature-requests-review.py list --status open

    # Get JSON output for AI processing
    AWS_PROFILE=pr-dev python tools/feature-requests-review.py list --json

    # Show details of a specific request (partial ID supported)
    AWS_PROFILE=pr-dev python tools/feature-requests-review.py show abc123
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# UUID length constant
UUID_FULL_LENGTH = 36

# =============================================================================
# Minimal Dependencies - Self-Contained
# =============================================================================

try:
    import boto3
    import pymysql
except ImportError as e:
    print(f"Error: Missing dependency - {e}", file=sys.stderr)
    print("Install with: pip install boto3 pymysql", file=sys.stderr)
    sys.exit(1)


# =============================================================================
# JSON Encoder for Decimal/datetime
# =============================================================================


class CustomJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and datetime types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def json_dumps(obj: Any, **kwargs: Any) -> str:
    """JSON dumps with custom encoder for Decimal/datetime."""
    return json.dumps(obj, cls=CustomJSONEncoder, **kwargs)


# =============================================================================
# Domain Models (Minimal, Self-Contained)
# =============================================================================


class FeatureRequestStatus(str, Enum):
    """Status enum matching database ENUM."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    DECLINED = "declined"


@dataclass
class FeatureRequest:
    """Feature request data."""

    request_id: str
    title: str
    description: str | None
    status: FeatureRequestStatus
    vote_score: int
    upvote_count: int
    downvote_count: int
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None
    admin_response: str | None
    submitted_by_user_id: str
    submitted_by_username: str | None
    submitted_by_user_code: str | None


@dataclass
class FeatureRequestNote:
    """Note on a feature request."""

    note_id: str
    note_text: str
    created_at: datetime | None
    username: str | None
    user_code: str | None


@dataclass
class FeatureRequestStats:
    """Aggregate statistics."""

    total: int
    open: int
    in_progress: int
    complete: int
    declined: int


# =============================================================================
# Credential Resolution (Self-Contained)
# =============================================================================


@dataclass
class MySQLCredentials:
    """MySQL connection credentials."""

    host: str
    port: int
    password: str


def resolve_credentials(
    secret_ref: str, aws_profile: str | None = None
) -> MySQLCredentials:
    """Resolve MySQL credentials from AWS Secrets Manager.

    Args:
        secret_ref: Secret reference (aws-secretsmanager:/path/to/secret)
        aws_profile: AWS profile to use (optional)

    Returns:
        MySQLCredentials with host, port, password

    Raises:
        RuntimeError: If credentials cannot be resolved
    """
    if not secret_ref.startswith("aws-secretsmanager:"):
        raise RuntimeError(f"Unsupported secret reference format: {secret_ref}")

    # Extract secret name from reference
    secret_name = secret_ref.replace("aws-secretsmanager:", "")

    # Create boto3 session with profile
    session_kwargs: dict[str, Any] = {}
    if aws_profile:
        session_kwargs["profile_name"] = aws_profile

    try:
        session = boto3.Session(**session_kwargs)
        client = session.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve secret '{secret_name}': {e}") from e

    # Parse secret value (expected JSON format)
    try:
        secret_data = json.loads(response["SecretString"])
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Invalid secret format for '{secret_name}': {e}") from e

    # Extract credentials
    host = secret_data.get("host")
    port = secret_data.get("port", 3306)
    password = secret_data.get("password")

    if not host or not password:
        raise RuntimeError(
            f"Secret '{secret_name}' missing required fields (host, password)"
        )

    return MySQLCredentials(host=host, port=int(port), password=password)


# =============================================================================
# Database Connection
# =============================================================================


def get_connection() -> pymysql.Connection:
    """Get MySQL connection to production coordination database.

    Uses AWS Secrets Manager for credentials.

    Returns:
        pymysql.Connection connected to the database

    Raises:
        RuntimeError: If connection fails
    """
    secret_ref = os.getenv(
        "PULLDB_COORDINATION_SECRET",
        "aws-secretsmanager:/pulldb/mysql/coordination-db",
    )
    aws_profile = os.getenv("PULLDB_AWS_PROFILE") or os.getenv("AWS_PROFILE")
    mysql_user = os.getenv("PULLDB_API_MYSQL_USER", "pulldb_api")
    mysql_database = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb_service")

    try:
        creds = resolve_credentials(secret_ref, aws_profile)
    except RuntimeError as e:
        raise RuntimeError(f"Credential resolution failed: {e}") from e

    try:
        return pymysql.connect(
            host=creds.host,
            port=creds.port,
            user=mysql_user,
            password=creds.password,
            database=mysql_database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
    except pymysql.Error as e:
        raise RuntimeError(f"MySQL connection failed: {e}") from e


# =============================================================================
# Database Queries
# =============================================================================


def list_requests(
    conn: pymysql.Connection,
    status_filter: str | None = None,
    sort_by: str = "votes",
    limit: int = 20,
) -> tuple[list[FeatureRequest], int]:
    """List feature requests with optional filtering.

    Args:
        conn: Database connection
        status_filter: Filter by status (optional)
        sort_by: Sort column ("votes" or "date")
        limit: Maximum number of results

    Returns:
        Tuple of (list of requests, total count)
    """
    with conn.cursor() as cursor:
        # Build WHERE clause
        where_clause = ""
        params: list[Any] = []
        if status_filter:
            where_clause = "WHERE fr.status = %s"
            params.append(status_filter)

        # Get total count
        count_sql = f"""
            SELECT COUNT(*) as cnt
            FROM feature_requests fr
            {where_clause}
        """
        cursor.execute(count_sql, params)
        total = cursor.fetchone()["cnt"]

        # Build ORDER BY
        order_by = "fr.vote_score DESC" if sort_by == "votes" else "fr.created_at DESC"

        # Get requests with user info
        query_sql = f"""
            SELECT
                fr.request_id,
                fr.title,
                fr.description,
                fr.status,
                fr.vote_score,
                fr.upvote_count,
                fr.downvote_count,
                fr.created_at,
                fr.updated_at,
                fr.completed_at,
                fr.admin_response,
                fr.submitted_by_user_id,
                au.username AS submitted_by_username,
                au.user_code AS submitted_by_user_code
            FROM feature_requests fr
            LEFT JOIN auth_users au ON fr.submitted_by_user_id = au.user_id
            {where_clause}
            ORDER BY {order_by}
            LIMIT %s
        """
        params.append(limit)
        cursor.execute(query_sql, params)
        rows = cursor.fetchall()

    requests = [
        FeatureRequest(
            request_id=row["request_id"],
            title=row["title"],
            description=row["description"],
            status=FeatureRequestStatus(row["status"]),
            vote_score=row["vote_score"] or 0,
            upvote_count=row["upvote_count"] or 0,
            downvote_count=row["downvote_count"] or 0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            admin_response=row["admin_response"],
            submitted_by_user_id=row["submitted_by_user_id"],
            submitted_by_username=row["submitted_by_username"],
            submitted_by_user_code=row["submitted_by_user_code"],
        )
        for row in rows
    ]

    return requests, total


def get_request(conn: pymysql.Connection, request_id: str) -> FeatureRequest | None:
    """Get a single feature request by ID (supports partial ID).

    Args:
        conn: Database connection
        request_id: Full or partial request ID

    Returns:
        FeatureRequest or None if not found
    """
    with conn.cursor() as cursor:
        # Support partial IDs
        if len(request_id) < UUID_FULL_LENGTH:
            query = """
                SELECT
                    fr.request_id,
                    fr.title,
                    fr.description,
                    fr.status,
                    fr.vote_score,
                    fr.upvote_count,
                    fr.downvote_count,
                    fr.created_at,
                    fr.updated_at,
                    fr.completed_at,
                    fr.admin_response,
                    fr.submitted_by_user_id,
                    au.username AS submitted_by_username,
                    au.user_code AS submitted_by_user_code
                FROM feature_requests fr
                LEFT JOIN auth_users au ON fr.submitted_by_user_id = au.user_id
                WHERE fr.request_id LIKE %s
                LIMIT 1
            """
            cursor.execute(query, (f"{request_id}%",))
        else:
            query = """
                SELECT
                    fr.request_id,
                    fr.title,
                    fr.description,
                    fr.status,
                    fr.vote_score,
                    fr.upvote_count,
                    fr.downvote_count,
                    fr.created_at,
                    fr.updated_at,
                    fr.completed_at,
                    fr.admin_response,
                    fr.submitted_by_user_id,
                    au.username AS submitted_by_username,
                    au.user_code AS submitted_by_user_code
                FROM feature_requests fr
                LEFT JOIN auth_users au ON fr.submitted_by_user_id = au.user_id
                WHERE fr.request_id = %s
            """
            cursor.execute(query, (request_id,))

        row = cursor.fetchone()

    if not row:
        return None

    return FeatureRequest(
        request_id=row["request_id"],
        title=row["title"],
        description=row["description"],
        status=FeatureRequestStatus(row["status"]),
        vote_score=row["vote_score"] or 0,
        upvote_count=row["upvote_count"] or 0,
        downvote_count=row["downvote_count"] or 0,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        admin_response=row["admin_response"],
        submitted_by_user_id=row["submitted_by_user_id"],
        submitted_by_username=row["submitted_by_username"],
        submitted_by_user_code=row["submitted_by_user_code"],
    )


def get_notes(conn: pymysql.Connection, request_id: str) -> list[FeatureRequestNote]:
    """Get notes for a feature request.

    Args:
        conn: Database connection
        request_id: Full request ID

    Returns:
        List of notes
    """
    with conn.cursor() as cursor:
        query = """
            SELECT
                frn.note_id,
                frn.note_text,
                frn.created_at,
                au.username,
                au.user_code
            FROM feature_request_notes frn
            LEFT JOIN auth_users au ON frn.user_id = au.user_id
            WHERE frn.request_id = %s
            ORDER BY frn.created_at ASC
        """
        cursor.execute(query, (request_id,))
        rows = cursor.fetchall()

    return [
        FeatureRequestNote(
            note_id=row["note_id"],
            note_text=row["note_text"],
            created_at=row["created_at"],
            username=row["username"],
            user_code=row["user_code"],
        )
        for row in rows
    ]


def get_stats(conn: pymysql.Connection) -> FeatureRequestStats:
    """Get aggregate statistics.

    Args:
        conn: Database connection

    Returns:
        FeatureRequestStats with counts by status
    """
    with conn.cursor() as cursor:
        query = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) as complete,
                SUM(CASE WHEN status = 'declined' THEN 1 ELSE 0 END) as declined
            FROM feature_requests
        """
        cursor.execute(query)
        row = cursor.fetchone()

    return FeatureRequestStats(
        total=row["total"] or 0,
        open=row["open_count"] or 0,
        in_progress=row["in_progress"] or 0,
        complete=row["complete"] or 0,
        declined=row["declined"] or 0,
    )


# =============================================================================
# Output Formatting
# =============================================================================


def format_date(dt: datetime | None) -> str:
    """Format datetime for display."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M")


def format_date_short(dt: datetime | None) -> str:
    """Format datetime compactly for tables."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d")


def truncate(text: str | None, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a formatted table to stdout."""
    if not rows:
        print("No results found.")
        return

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))

    # Print rows
    for row in rows:
        cells = [str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)]
        print("  ".join(cells))


def status_display(status: FeatureRequestStatus) -> str:
    """Format status for display."""
    return status.value.replace("_", " ").title()


# =============================================================================
# Commands
# =============================================================================


def cmd_list(args: argparse.Namespace) -> int:
    """Execute the 'list' command."""
    try:
        conn = get_connection()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        requests, total = list_requests(
            conn,
            status_filter=args.status,
            sort_by=args.sort,
            limit=args.limit,
        )
    finally:
        conn.close()

    if args.json:
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
                    "downvote_count": r.downvote_count,
                    "submitted_by": r.submitted_by_user_code or r.submitted_by_username,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in requests
            ],
        }
        print(json_dumps(output, indent=2))
        return 0

    if not requests:
        print("No feature requests found matching criteria.")
        return 0

    # Summary line
    print(f"Feature Requests (showing {len(requests)} of {total})")
    print()

    # Table output
    headers = ["ID", "VOTES", "STATUS", "DATE", "USER", "TITLE"]
    rows: list[list[str]] = []

    for r in requests:
        rows.append([
            r.request_id[:8],
            str(r.vote_score),
            status_display(r.status),
            format_date_short(r.created_at),
            (r.submitted_by_user_code or r.submitted_by_username or "-")[:8],
            truncate(r.title, 50),
        ])

    print_table(headers, rows)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Execute the 'show' command."""
    try:
        conn = get_connection()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        request = get_request(conn, args.request_id)
        if request is None:
            print(
                f"Error: No feature request found with ID '{args.request_id}'",
                file=sys.stderr,
            )
            return 1

        notes = get_notes(conn, request.request_id)
    finally:
        conn.close()

    if args.json:
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
                "created_at": (
                    request.created_at.isoformat() if request.created_at else None
                ),
                "updated_at": (
                    request.updated_at.isoformat() if request.updated_at else None
                ),
                "completed_at": (
                    request.completed_at.isoformat() if request.completed_at else None
                ),
                "admin_response": request.admin_response,
            },
            "notes": [
                {
                    "note_id": n.note_id,
                    "user": n.user_code or n.username,
                    "note_text": n.note_text,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
                for n in notes
            ],
        }
        print(json_dumps(output, indent=2))
        return 0

    # Formatted detail view
    print()
    print("═══ Feature Request " + "═" * 40)
    print()
    print(f"ID:          {request.request_id}")
    print(f"Status:      {status_display(request.status)}")
    votes = f"{request.vote_score} (↑{request.upvote_count} ↓{request.downvote_count})"
    print(f"Votes:       {votes}")
    submitted = request.submitted_by_user_code or request.submitted_by_username or "-"
    print(f"Submitted:   {submitted}")
    print(f"Created:     {format_date(request.created_at)}")
    print(f"Updated:     {format_date(request.updated_at)}")
    if request.completed_at:
        print(f"Completed:   {format_date(request.completed_at)}")

    print()
    print("═══ Title " + "═" * 50)
    print(request.title)

    if request.description:
        print()
        print("═══ Description " + "═" * 44)
        print(request.description)

    if request.admin_response:
        print()
        print("═══ Admin Response " + "═" * 41)
        print(request.admin_response)

    if notes:
        print()
        print(f"═══ Notes ({len(notes)}) " + "═" * 46)
        for note in notes:
            user = note.user_code or note.username or "unknown"
            date = format_date(note.created_at)
            print()
            print(f"[{user}] {date}")
            print(f"  {note.note_text}")
    else:
        print()
        print("No notes.")

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Execute the 'stats' command."""
    try:
        conn = get_connection()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        stats = get_stats(conn)

        # Also get top voted for display
        top_requests, _ = list_requests(
            conn,
            status_filter=None,
            sort_by="votes",
            limit=5,
        )
        # Filter to open/in_progress
        active_statuses = (FeatureRequestStatus.OPEN, FeatureRequestStatus.IN_PROGRESS)
        top_requests = [
            r for r in top_requests if r.status in active_statuses
        ][:5]
    finally:
        conn.close()

    if args.json:
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
        print(json_dumps(output, indent=2))
        return 0

    # Formatted stats view
    print()
    print("═══ Feature Request Statistics " + "═" * 29)
    print()
    print(f"Total:         {stats.total}")
    print(f"Open:          {stats.open}")
    print(f"In Progress:   {stats.in_progress}")
    print(f"Complete:      {stats.complete}")
    print(f"Declined:      {stats.declined}")

    if top_requests:
        print()
        print("═══ Top Voted (Open/In Progress) " + "═" * 27)
        print()

        headers = ["VOTES", "STATUS", "TITLE"]
        rows: list[list[str]] = []

        for r in top_requests:
            rows.append([
                str(r.vote_score),
                status_display(r.status),
                truncate(r.title, 60),
            ])

        print_table(headers, rows)
    else:
        print()
        print("No open or in-progress requests.")

    return 0


def update_feature_request_status(
    conn: pymysql.Connection, request_id: str, new_status: str
) -> bool:
    """Update a feature request's status.
    
    Args:
        conn: Database connection
        request_id: Full or partial request ID
        new_status: New status value (open, in_progress, complete, declined)
    
    Returns:
        True if updated, False if not found
    """
    # Resolve partial ID to full ID via get_request
    request = get_request(conn, request_id)
    if not request:
        return False
    
    full_id = request.request_id
    
    with conn.cursor() as cursor:
        # Set completed_at if marking complete
        if new_status == "complete":
            query = """
                UPDATE feature_requests 
                SET status = %s, completed_at = NOW(), updated_at = NOW()
                WHERE request_id = %s
            """
        else:
            query = """
                UPDATE feature_requests 
                SET status = %s, completed_at = NULL, updated_at = NOW()
                WHERE request_id = %s
            """
        cursor.execute(query, (new_status, full_id))
        conn.commit()
        return cursor.rowcount > 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update a feature request's status."""
    conn = get_connection()
    
    # Get current state (also validates ID)
    request = get_request(conn, args.request_id)
    if not request:
        print(f"Error: Feature request not found: {args.request_id}", file=sys.stderr)
        return 1
    
    old_status = request.status.value
    new_status = args.status
    
    if old_status == new_status:
        print(f"Status already '{new_status}' - no change needed.")
        return 0
    
    # Perform update
    success = update_feature_request_status(conn, request.request_id, new_status)
    
    if success:
        print(f"✅ Updated feature request {args.request_id[:8]}")
        print(f"   Status: {old_status} → {new_status}")
        return 0
    else:
        print(f"Error: Failed to update feature request", file=sys.stderr)
        return 1


def add_note(conn: pymysql.Connection, request_id: str, note_text: str) -> bool:
    """Add a note to a feature request.
    
    Args:
        conn: Database connection
        request_id: Full request ID
        note_text: Note content
    
    Returns:
        True if added successfully
    """
    import uuid
    
    note_id = str(uuid.uuid4())
    # Use a system user ID for AI/dev tool notes
    system_user_id = "00000000-0000-0000-0000-000000000000"
    
    with conn.cursor() as cursor:
        # Check if system user exists, create if not
        cursor.execute(
            "SELECT user_id FROM auth_users WHERE user_id = %s",
            (system_user_id,)
        )
        if not cursor.fetchone():
            cursor.execute(
                """INSERT INTO auth_users (user_id, username, user_code, role, created_at)
                   VALUES (%s, 'system', 'SYSTEM', 'service', NOW())
                   ON DUPLICATE KEY UPDATE username = username""",
                (system_user_id,)
            )
        
        cursor.execute(
            """INSERT INTO feature_request_notes 
               (note_id, request_id, user_id, note_text, created_at)
               VALUES (%s, %s, %s, %s, NOW())""",
            (note_id, request_id, system_user_id, note_text)
        )
        conn.commit()
        return cursor.rowcount > 0


def cmd_note(args: argparse.Namespace) -> int:
    """Add a note to a feature request."""
    conn = get_connection()
    
    # Get request (validates ID)
    request = get_request(conn, args.request_id)
    if not request:
        print(f"Error: Feature request not found: {args.request_id}", file=sys.stderr)
        return 1
    
    success = add_note(conn, request.request_id, args.text)
    
    if success:
        print(f"✅ Added note to feature request {args.request_id[:8]}")
        return 0
    else:
        print(f"Error: Failed to add note", file=sys.stderr)
        return 1


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Feature Requests Review Tool - Dev/AI Agent Only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List all open requests
    python tools/feature-requests-review.py list --status open

    # Get JSON for AI processing
    python tools/feature-requests-review.py list --json

    # Show a specific request (partial ID supported)
    python tools/feature-requests-review.py show abc12345

    # View statistics
    python tools/feature-requests-review.py stats

Environment Variables:
    AWS_PROFILE              AWS profile for credentials
    PULLDB_AWS_PROFILE       Alternative to AWS_PROFILE
    PULLDB_COORDINATION_SECRET  Secret path (default: see code)
    PULLDB_API_MYSQL_USER    MySQL user (default: pulldb_api)
    PULLDB_MYSQL_DATABASE    Database name (default: pulldb_service)
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # List command
    list_parser = subparsers.add_parser("list", help="List feature requests")
    list_parser.add_argument(
        "--status",
        choices=["open", "in_progress", "complete", "declined"],
        help="Filter by status",
    )
    list_parser.add_argument(
        "--sort",
        choices=["votes", "date"],
        default="votes",
        help="Sort order (default: votes)",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of requests to show (default: 20)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON for programmatic use",
    )
    list_parser.set_defaults(func=cmd_list)

    # Show command
    show_parser = subparsers.add_parser(
        "show", help="Show details of a feature request"
    )
    show_parser.add_argument(
        "request_id",
        help="Request ID (full UUID or first 8+ characters)",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON for programmatic use",
    )
    show_parser.set_defaults(func=cmd_show)

    # Stats command
    stats_parser = subparsers.add_parser(
        "stats", help="Show feature request statistics"
    )
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON for programmatic use",
    )
    stats_parser.set_defaults(func=cmd_stats)

    # Update command
    update_parser = subparsers.add_parser(
        "update", help="Update a feature request's status"
    )
    update_parser.add_argument(
        "request_id",
        help="Request ID (full UUID or first 8+ characters)",
    )
    update_parser.add_argument(
        "--status",
        choices=["open", "in_progress", "complete", "declined"],
        required=True,
        help="New status to set",
    )
    update_parser.set_defaults(func=cmd_update)

    # Note command
    note_parser = subparsers.add_parser(
        "note", help="Add a note to a feature request"
    )
    note_parser.add_argument(
        "request_id",
        help="Request ID (full UUID or first 8+ characters)",
    )
    note_parser.add_argument(
        "--text",
        required=True,
        help="Note text to add",
    )
    note_parser.set_defaults(func=cmd_note)

    args = parser.parse_args()
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
