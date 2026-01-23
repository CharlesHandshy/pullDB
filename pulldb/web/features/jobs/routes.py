from __future__ import annotations

"""Jobs routes for Web2 interface.

HCA Layer: features (pulldb/web/features/)
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from pulldb.domain.models import JobStatus, User, UserRole
from pulldb.web.dependencies import get_api_state, require_login, templates
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs


router = APIRouter(prefix="/web/jobs", tags=["web-jobs"])


@router.get("/", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    page: int = 1,
    view: str = "active",
    q: str | None = None,
    status: str | None = None,
    host: str | None = None,
    days: int = 30,
    user_code: str | None = None,
    target: str | None = None,
    restore_warning: str | None = Query(None),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the jobs page with Active/History views."""
    page_size = 20
    offset = (page - 1) * page_size
    jobs = []
    hosts = []

    # Get hosts for dropdown
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()

    if hasattr(state, "job_repo") and state.job_repo:
        if view == "history":
            # History view - shows failed, canceled, dropped, superseded jobs
            if hasattr(state.job_repo, "get_job_history_v2"):
                jobs = state.job_repo.get_job_history_v2(
                    limit=page_size,
                    retention_days=days,
                    user_code=user_code if user_code else None,
                    target=target if target else None,
                    dbhost=host if host else None,
                    status=status if status else None,
                )
            elif hasattr(state.job_repo, "get_job_history"):
                # Fallback to old method
                jobs = state.job_repo.get_job_history(
                    limit=page_size,
                    retention_days=days,
                    user_code=user_code if user_code else None,
                    target=target if target else None,
                    dbhost=host if host else None,
                    status=status if status else None,
                )
            else:
                # Fallback for mock
                jobs = getattr(state.job_repo, "history_jobs", [])[:page_size]

                # Apply in-memory filters for mock
                if status:
                    jobs = [
                        j
                        for j in jobs
                        if str(j.status).lower() == status.lower()
                        or j.status.value == status
                    ]
                if host:
                    jobs = [j for j in jobs if j.dbhost == host]
                if user_code:
                    jobs = [
                        j
                        for j in jobs
                        if getattr(j, "owner_user_code", None) == user_code
                    ]
        # Active view - shows owned databases (in-progress + complete but not dropped/superseded)
        elif q and len(q) >= 4:
            # Search mode
            exact = len(q) >= 5
            jobs = state.job_repo.search_jobs(q, limit=page_size, exact=exact)
            # Filter to owned databases only
            jobs = [
                j for j in jobs 
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCELING, JobStatus.DEPLOYED)
            ]
        elif hasattr(state.job_repo, "get_owned_databases"):
            # New method: shows in-progress + complete (not dropped, not superseded)
            jobs = state.job_repo.get_owned_databases(
                limit=page_size,
                user_code=user_code if user_code else None,
                target=target if target else None,
                dbhost=host if host else None,
            )
            # Apply status filter if provided
            if status:
                jobs = [j for j in jobs if j.status.value == status]
        elif hasattr(state.job_repo, "get_active_jobs"):
            # Fallback to old method (only queued/running)
            jobs = state.job_repo.get_active_jobs()

            # Apply filters
            if status:
                jobs = [j for j in jobs if j.status.value == status]
            if host:
                jobs = [j for j in jobs if j.dbhost == host]
        else:
            # Fallback for mock
            jobs = getattr(state.job_repo, "active_jobs", [])

    # Get retention settings for JavaScript
    expiring_warning_days = 7
    max_retention_days = 180
    jobs_refresh_interval = 5
    retention_options: list[tuple[str, str]] = []
    
    settings_repo = getattr(state, "settings_repo", None)
    if settings_repo:
        if hasattr(settings_repo, "get_expiring_warning_days"):
            expiring_warning_days = settings_repo.get_expiring_warning_days()
        if hasattr(settings_repo, "get_max_retention_days"):
            max_retention_days = settings_repo.get_max_retention_days()
        if hasattr(settings_repo, "get_jobs_refresh_interval"):
            jobs_refresh_interval = settings_repo.get_jobs_refresh_interval()
        if hasattr(settings_repo, "get_retention_options"):
            retention_options = settings_repo.get_retention_options(include_now=False)

    return templates.TemplateResponse(
        "features/jobs/jobs.html",
        {
            "request": request,
            "breadcrumbs": get_breadcrumbs("my_jobs"),
            "jobs": jobs,
            "user": user,
            "active_nav": "jobs",
            "page": page,
            "view": view,
            "has_next": len(jobs) == page_size,
            "has_prev": page > 1,
            "q": q,
            "cache_bust": int(__import__('time').time()),
            "status": status,
            "host": host,
            "hosts": hosts,
            "days": days,
            "user_code": user_code,
            "target_filter": target,
            # Role-based filter defaults
            "managed_user_codes": _get_managed_user_codes(state, user),
            "three_days_ago_iso": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
            # Retention settings for JavaScript
            "expiring_warning_days": expiring_warning_days,
            "max_retention_days": max_retention_days,
            "jobs_refresh_interval": jobs_refresh_interval,
            "retention_options": retention_options,
            # Flash messages
            "warning": restore_warning,
        },
    )


def _get_managed_user_codes(state: Any, user: User) -> list[str]:
    """Get user codes that a manager manages, including their own."""
    if user.role != UserRole.MANAGER:
        return []

    managed_codes = [user.user_code]  # Always include self

    if hasattr(state, "user_repo") and state.user_repo:
        if hasattr(state.user_repo, "get_users_managed_by"):
            managed_users = state.user_repo.get_users_managed_by(user.user_id)
            managed_codes.extend(u.user_code for u in managed_users)

    return managed_codes


def _deduplicate_logs(logs: list[Any]) -> list[Any]:
    """Deduplicate consecutive restore_progress events with same percent/status.

    Processlist updates emit events every 2 seconds, creating repetitive entries
    like "52% processlist_update" repeated many times. This collapses consecutive
    duplicates to reduce noise in the execution log display.

    Only deduplicates restore_progress events; other event types pass through unchanged.
    Uses integer percent to avoid float precision issues (51.001 vs 51.002).
    """
    if not logs:
        return logs

    deduplicated: list[Any] = []
    last_key: tuple[str, int, str] | None = None

    for event in logs:
        event_type = getattr(event, "event_type", "")

        # Only deduplicate restore_progress events
        if event_type == "restore_progress":
            detail = getattr(event, "detail", None)
            percent = 0
            status = ""

            if detail:
                parsed = detail
                if isinstance(detail, str):
                    try:
                        parsed = json.loads(detail)
                    except (json.JSONDecodeError, TypeError):
                        parsed = {}
                if isinstance(parsed, dict):
                    # Use integer percent to avoid float precision issues
                    percent = int(parsed.get("percent", 0))
                    detail_info = parsed.get("detail", {})
                    if isinstance(detail_info, dict):
                        status = detail_info.get("status", "")

            current_key = (event_type, percent, status)

            # Skip if same as last restore_progress event
            if current_key == last_key:
                continue

            last_key = current_key
        else:
            # Reset tracking when we see a non-restore_progress event
            last_key = None

        deduplicated.append(event)

    return deduplicated


# Phase definitions for job progress display
JOB_PHASES = [
    ("queued", "Queued"),
    ("discovery", "Discovery"),
    ("download", "Download"),
    ("extraction", "Extraction"),
    ("myloader", "Loading"),
    ("post_sql", "Post-SQL"),
    ("atomic_rename", "Rename"),
    ("complete", "Complete"),
]

# Map event types to phases
EVENT_TO_PHASE: dict[str, str] = {
    "queued": "queued",
    "running": "discovery",
    "backup_selected": "discovery",
    "download_started": "download",
    "download_progress": "download",
    "download_complete": "download",
    "extraction_started": "extraction",
    "extraction_progress": "extraction",
    "extraction_complete": "extraction",
    "extraction_failed": "extraction",
    "format_detected": "extraction",
    "restore_started": "myloader",
    "staging_cleanup_started": "myloader",
    "staging_drop_started": "myloader",
    "staging_drop_complete": "myloader",
    "staging_drop_skipped": "myloader",
    "staging_cleanup_complete": "myloader",
    "myloader_started": "myloader",
    "restore_progress": "myloader",
    # Index rebuild events - still in myloader phase
    "table_data_progress": "myloader",
    "table_index_rebuild_queued": "myloader",
    "table_index_rebuild_started": "myloader",
    "table_index_rebuild_confirmed": "myloader",
    "table_index_rebuild_progress": "myloader",
    "table_restore_complete": "myloader",
    "restore_complete": "post_sql",
    # ANALYZE TABLE events
    "table_analyze_started": "post_sql",
    "table_analyze_complete": "post_sql",
    "analyze_batch_started": "post_sql",
    "analyze_batch_complete": "post_sql",
    "post_sql_started": "post_sql",
    "post_sql_script_complete": "post_sql",
    "post_sql_complete": "post_sql",
    "metadata_started": "atomic_rename",
    "metadata_complete": "atomic_rename",
    "atomic_rename_started": "atomic_rename",
    "atomic_rename_complete": "atomic_rename",
    "staging_cleanup": "atomic_rename",
    "complete": "complete",
    "failed": "failed",
    "canceled": "canceled",
}


def _derive_current_phase(
    logs: list[Any], job_status: str
) -> tuple[str, list[dict[str, Any]]]:
    """Derive current phase from job events and build phase list with states.

    Returns:
        Tuple of (current_phase_id, phase_list) where phase_list has
        entries with 'id', 'label', and 'state' (pending/active/complete/failed).
    """
    # Determine the actual phase from events
    current_phase = "queued"
    for event in reversed(logs):
        event_type = getattr(event, "event_type", "")
        if event_type in EVENT_TO_PHASE:
            current_phase = EVENT_TO_PHASE[event_type]
            break

    # For completed/deployed jobs, the phase is "complete"
    if job_status in ("deployed", "complete"):
        current_phase = "complete"

    # Determine if this is a terminal failure/cancel state
    # (but keep the actual phase where it failed)
    is_failed = job_status == "failed"
    is_canceled = job_status == "canceled"

    # Build phase list with states
    phase_list = []
    found_current = False
    for phase_id, phase_label in JOB_PHASES:
        if phase_id == current_phase:
            # This is the current/failed phase
            if is_failed:
                state = "failed"
            elif is_canceled:
                state = "failed"  # Show canceled phase as failed (red X)
            elif job_status in ("running", "queued"):
                state = "active"
            else:
                state = "complete"
            found_current = True
        elif found_current:
            # Phases after current: pending (never reached)
            state = "pending"
        else:
            # Phases before current: complete
            state = "complete"
        phase_list.append({"id": phase_id, "label": phase_label, "state": state})

    return current_phase, phase_list


def _get_retention_options(state: Any) -> list[dict[str, Any]]:
    """Get retention extension options from settings.
    
    Returns a list of dicts with 'months' and 'label' keys.
    Falls back to default options if settings unavailable.
    """
    if hasattr(state, "settings_repo") and state.settings_repo:
        if hasattr(state.settings_repo, "get_retention_options"):
            result: list[dict[str, Any]] = state.settings_repo.get_retention_options()
            return result
    
    # Default fallback
    return [
        {"months": 1, "label": "1 month"},
        {"months": 3, "label": "3 months"},
        {"months": 6, "label": "6 months"},
    ]


def _get_expiring_warning_days(state: Any) -> int:
    """Get days before expiry to show warning notice.
    
    Returns:
        Number of days. Default: 7.
    """
    if hasattr(state, "settings_repo") and state.settings_repo:
        if hasattr(state.settings_repo, "get_expiring_warning_days"):
            return state.settings_repo.get_expiring_warning_days()
    return 7


def _calculate_download_stats(logs: list[Any]) -> dict[str, Any] | None:
    """Extract latest download progress stats from job events.

    Scans events for download_progress and download_complete to build
    stats dict with: downloaded_bytes, total_bytes, percent_complete,
    elapsed_seconds, speed_bps, eta_seconds, is_complete, duration_seconds.

    Returns None if no download progress events found.
    """
    from datetime import datetime

    latest_progress: dict[str, Any] | None = None
    is_complete = False
    started_at: datetime | None = None
    completed_at: datetime | None = None

    for event in logs:
        event_type = getattr(event, "event_type", "")
        detail = getattr(event, "detail", None)
        logged_at = getattr(event, "logged_at", None)

        if event_type == "download_started":
            started_at = logged_at

        if event_type == "download_complete":
            is_complete = True
            completed_at = logged_at

        if event_type == "download_progress" and detail:
            # Track first progress as start if no explicit started event
            if started_at is None:
                started_at = logged_at
            # detail is dict or JSON string with: downloaded_bytes, total_bytes, percent_complete, elapsed_seconds
            parsed_detail = detail
            if isinstance(detail, str):
                try:
                    parsed_detail = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    parsed_detail = None
            if isinstance(parsed_detail, dict):
                latest_progress = parsed_detail

    if not latest_progress:
        return None

    downloaded = latest_progress.get("downloaded_bytes", 0)
    total = latest_progress.get("total_bytes", 0)
    elapsed = latest_progress.get("elapsed_seconds", 0)
    percent = latest_progress.get("percent_complete", 0.0)

    # Calculate speed and ETA
    speed_bps = downloaded / elapsed if elapsed > 0 else 0
    remaining_bytes = max(0, total - downloaded)
    eta_seconds = remaining_bytes / speed_bps if speed_bps > 0 else 0

    # Calculate duration_seconds from timestamps if complete
    duration_seconds: float | None = None
    if is_complete and started_at and completed_at:
        duration_seconds = (completed_at - started_at).total_seconds()
    elif elapsed > 0:
        # Use elapsed_seconds from progress for in-progress phases
        duration_seconds = elapsed

    return {
        "downloaded_bytes": downloaded,
        "total_bytes": total,
        "percent_complete": percent if not is_complete else 100.0,
        "elapsed_seconds": elapsed,
        "duration_seconds": duration_seconds,
        "speed_bps": speed_bps,
        "eta_seconds": eta_seconds,
        "is_complete": is_complete,
    }


def _calculate_extraction_stats(logs: list[Any]) -> dict[str, Any] | None:
    """Extract latest extraction progress stats from job events.

    Scans events for extraction_started, extraction_progress, and
    extraction_complete to build stats dict with: extracted_bytes, total_bytes,
    percent_complete, elapsed_seconds, files_extracted, total_files,
    speed_bps, eta_seconds, is_complete, duration_seconds.

    Returns None if no extraction progress events found.
    """
    from datetime import datetime

    extracted_bytes = 0
    total_bytes = 0
    percent_complete = 0.0
    elapsed_seconds = 0.0
    files_extracted = 0
    total_files = 0
    is_complete = False
    has_failed = False
    started = False
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    for event in logs:
        event_type = getattr(event, "event_type", "")
        detail = getattr(event, "detail", None)
        logged_at = getattr(event, "logged_at", None)

        if event_type == "extraction_started":
            started = True
            started_at = logged_at
            if detail:
                parsed = detail if isinstance(detail, dict) else None
                if isinstance(detail, str):
                    try:
                        parsed = json.loads(detail)
                    except (json.JSONDecodeError, TypeError):
                        parsed = None
                if isinstance(parsed, dict):
                    total_bytes = parsed.get("archive_size", 0)

        elif event_type == "extraction_progress" and detail:
            started = True
            parsed = detail if isinstance(detail, dict) else None
            if isinstance(detail, str):
                try:
                    parsed = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    parsed = None
            if isinstance(parsed, dict):
                extracted_bytes = parsed.get("extracted_bytes", 0)
                total_bytes = parsed.get("total_bytes", total_bytes)
                percent_complete = parsed.get("percent_complete", 0.0)
                elapsed_seconds = parsed.get("elapsed_seconds", 0.0)
                files_extracted = parsed.get("files_extracted", 0)
                total_files = parsed.get("total_files", 0)

        elif event_type == "extraction_complete":
            is_complete = True
            percent_complete = 100.0
            completed_at = logged_at

        elif event_type == "extraction_failed":
            has_failed = True
            if detail:
                parsed = detail if isinstance(detail, dict) else None
                if isinstance(detail, str):
                    try:
                        parsed = json.loads(detail)
                    except (json.JSONDecodeError, TypeError):
                        parsed = None
                if isinstance(parsed, dict):
                    error_message = parsed.get("error")

    if not started:
        return None

    # Calculate speed and ETA
    speed_bps = int(extracted_bytes / elapsed_seconds) if elapsed_seconds > 0 else 0
    remaining_bytes = total_bytes - extracted_bytes
    eta_seconds = int(remaining_bytes / speed_bps) if speed_bps > 0 and not is_complete else 0

    # Calculate duration_seconds from timestamps if complete
    duration_seconds: float | None = None
    if is_complete and started_at and completed_at:
        duration_seconds = (completed_at - started_at).total_seconds()
    elif elapsed_seconds > 0:
        # Use elapsed_seconds from progress for in-progress phases
        duration_seconds = elapsed_seconds

    return {
        "extracted_bytes": extracted_bytes,
        "total_bytes": total_bytes,
        "percent_complete": percent_complete,
        "elapsed_seconds": elapsed_seconds,
        "duration_seconds": duration_seconds,
        "files_extracted": files_extracted,
        "total_files": total_files,
        "speed_bps": speed_bps,
        "eta_seconds": eta_seconds,
        "is_complete": is_complete,
        "has_failed": has_failed,
        "error_message": error_message,
    }


def _calculate_restore_stats(logs: list[Any]) -> dict[str, Any] | None:
    """Extract latest restore progress stats from job events.

    Scans events for restore_progress and restore_complete to build
    stats dict with: percent_complete, current_file, is_complete,
    active_threads, per-table progress from processlist, and duration_seconds.

    Returns None if no restore progress events found.
    """
    from datetime import datetime

    latest_progress: dict[str, Any] | None = None
    is_complete = False
    has_restoring_event = False
    started_at: datetime | None = None
    completed_at: datetime | None = None

    for event in logs:
        event_type = getattr(event, "event_type", "")
        detail = getattr(event, "detail", None)
        logged_at = getattr(event, "logged_at", None)

        if event_type == "restoring":
            has_restoring_event = True
            started_at = logged_at

        if event_type == "restore_complete":
            is_complete = True
            completed_at = logged_at

        if event_type == "restore_progress" and detail:
            # Track first progress as start if no explicit restoring event
            if started_at is None:
                started_at = logged_at
            parsed_detail = detail
            if isinstance(detail, str):
                try:
                    parsed_detail = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    parsed_detail = None
            if isinstance(parsed_detail, dict):
                latest_progress = parsed_detail

    # If we have restoring event but no progress, show indeterminate state
    if not latest_progress:
        if has_restoring_event and not is_complete:
            return {
                "percent_complete": 0.0,
                "current_file": "",
                "status": "Loading...",
                "is_complete": False,
                "active_threads": 0,
                "tables": {},
                "rows_per_second": 0,
                "eta_seconds": None,
                "rows_restored": 0,
                "total_rows": 0,
                "duration_seconds": None,
            }
        return None

    # Extract overall percent
    percent = latest_progress.get("percent", 0.0)
    
    # Extract detail info - contains file info AND processlist data
    detail_info = latest_progress.get("detail", {})
    if not isinstance(detail_info, dict):
        detail_info = {}
    
    current_file = detail_info.get("file", "")
    status = detail_info.get("status", "")
    
    # Extract processlist-based progress from detail (new format)
    active_threads = detail_info.get("active_threads", 0)
    tables_data = detail_info.get("tables", {})
    
    # Extract throughput stats
    rows_per_second = detail_info.get("rows_per_second", 0)
    eta_seconds = detail_info.get("eta_seconds")
    rows_restored = detail_info.get("rows_restored", 0)
    total_rows = detail_info.get("total_rows", 0)
    tables_completed = detail_info.get("tables_completed", 0)
    tables_total = detail_info.get("tables_total", 0)
    
    # Normalize tables data for template
    # Only include tables that are NOT complete (active in processlist)
    # Tables disappear from UI when their thread finishes
    tables = {}
    if isinstance(tables_data, dict):
        for table_name, table_info in tables_data.items():
            if isinstance(table_info, dict):
                # Skip completed tables - only show active ones
                if table_info.get("is_complete", False):
                    continue
                tables[table_name] = {
                    "percent": min(100.0, table_info.get("percent_complete", 0.0)),
                    "phase": table_info.get("phase", "loading"),
                    "is_complete": False,  # We filtered these out above
                }
            elif isinstance(table_info, (int, float)):
                tables[table_name] = {
                    "percent": min(100.0, float(table_info)),
                    "phase": "loading",
                    "is_complete": False,
                }

    # Calculate duration_seconds from timestamps if complete
    duration_seconds: float | None = None
    if is_complete and started_at and completed_at:
        duration_seconds = (completed_at - started_at).total_seconds()

    return {
        "percent_complete": min(100.0, percent) if not is_complete else 100.0,
        "current_file": current_file,
        "status": status,
        "is_complete": is_complete,
        "active_threads": active_threads,
        "tables": tables,
        "rows_per_second": rows_per_second,
        "eta_seconds": eta_seconds,
        "rows_restored": rows_restored,
        "total_rows": total_rows,
        "tables_completed": tables_completed,
        "tables_total": tables_total,
        "duration_seconds": duration_seconds,
    }

def _calculate_atomic_rename_stats(logs: list[Any]) -> dict[str, Any] | None:
    """Extract latest atomic rename progress stats from job events.

    Scans events for atomic_rename_progress and atomic_rename_complete to build
    stats dict with: percent_complete, current_table, tables_renamed, total_tables,
    is_complete, and duration_seconds.

    Returns None if no atomic rename progress events found.
    """
    from datetime import datetime

    latest_progress: dict[str, Any] | None = None
    final_progress: dict[str, Any] | None = None
    is_complete = False
    has_executing_event = False
    started_at: datetime | None = None
    completed_at: datetime | None = None

    for event in logs:
        event_type = getattr(event, "event_type", "")
        detail = getattr(event, "detail", None)
        logged_at = getattr(event, "logged_at", None)

        if event_type == "atomic_rename_executing":
            has_executing_event = True
            started_at = logged_at

        if event_type == "atomic_rename_complete":
            is_complete = True
            completed_at = logged_at
            # Capture the last progress before completion
            if latest_progress:
                final_progress = latest_progress.copy()

        if event_type == "atomic_rename_progress" and detail:
            # Track first progress as start if no explicit executing event
            if started_at is None:
                started_at = logged_at
            parsed_detail = detail
            if isinstance(detail, str):
                try:
                    parsed_detail = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    parsed_detail = None
            if isinstance(parsed_detail, dict):
                latest_progress = parsed_detail

    # If we have executing event but no progress, don't show anything yet
    # Progress bar will appear once first progress event arrives
    if not latest_progress:
        return None

    # Use final progress if complete, otherwise latest
    progress_data = final_progress if is_complete and final_progress else latest_progress

    # Extract progress data - handle both old and new field names
    percent = progress_data.get("percent", 0.0)
    
    # Worker emits 'tables_renamed' and 'total_tables' (new format)
    # But some old events may have 'progress' and 'total'
    tables_renamed = progress_data.get("tables_renamed", progress_data.get("progress", 0))
    total_tables = progress_data.get("total_tables", progress_data.get("total", 0))
    
    # Try to extract current table from message or table field
    current_table = progress_data.get("message", progress_data.get("table", ""))
    if not current_table:
        detail_info = progress_data.get("detail", {})
        if isinstance(detail_info, dict):
            current_table = detail_info.get("table", "")

    # Calculate duration_seconds from timestamps if complete
    duration_seconds: float | None = None
    if is_complete and started_at and completed_at:
        duration_seconds = (completed_at - started_at).total_seconds()

    return {
        "percent_complete": 100.0 if is_complete else percent,
        "current_table": current_table if not is_complete else "",
        "tables_renamed": tables_renamed,
        "total_tables": total_tables,
        "is_complete": is_complete,
        "duration_seconds": duration_seconds,
    }


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_details(
    request: Request,
    job_id: str,
    cancel_error: str | None = Query(None),
    cancel_success: str | None = Query(None),
    delete_error: str | None = Query(None),
    delete_success: str | None = Query(None),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the job details page."""
    from pulldb.domain.permissions import can_cancel_job

    job = None
    logs = []
    profile = None
    job_can_cancel = False
    current_phase = "queued"
    phase_list: list[dict[str, Any]] = []
    download_stats: dict[str, Any] | None = None
    extraction_stats: dict[str, Any] | None = None
    restore_stats: dict[str, Any] | None = None
    atomic_rename_stats: dict[str, Any] | None = None

    if hasattr(state, "job_repo") and state.job_repo:
        job = state.job_repo.get_job_by_id(job_id)
        if job:
            raw_logs = state.job_repo.get_job_events(job_id)

            # Derive current phase for progress indicator (uses raw logs)
            current_phase, phase_list = _derive_current_phase(raw_logs, job.status.value)

            # Calculate download progress stats for progress bar (uses raw logs)
            download_stats = _calculate_download_stats(raw_logs)

            # Calculate extraction progress stats for progress bar (uses raw logs)
            extraction_stats = _calculate_extraction_stats(raw_logs)

            # Calculate restore progress stats for progress bar (uses raw logs)
            restore_stats = _calculate_restore_stats(raw_logs)

            # Calculate atomic rename progress stats for progress bar (uses raw logs)
            atomic_rename_stats = _calculate_atomic_rename_stats(raw_logs)

            # Deduplicate logs for display (collapse repetitive processlist updates)
            logs = _deduplicate_logs(raw_logs)

            # Compute can_cancel for this user
            # Must have permission AND job must still be in cancelable state
            job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
            job_owner_manager_id = job_owner.manager_id if job_owner else None
            has_cancel_permission = can_cancel_job(
                user, job.owner_user_id, job_owner_manager_id
            )
            # Job is cancelable if: permission + status + can_cancel flag
            job_can_cancel = (
                has_cancel_permission
                and job.can_cancel
                and job.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            )

            # Try to get profile if job is complete
            if job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
                from pulldb.worker.profiling import parse_profile_from_event

                for event in logs:
                    if event.event_type == "restore_profile" and event.detail:
                        profile = parse_profile_from_event(event.detail)
                        break

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if cancellation was requested
    cancel_requested_at = None
    if hasattr(state.job_repo, "_cancel_requested"):
        cancel_requested_at = state.job_repo._cancel_requested.get(job_id)
    elif hasattr(state.job_repo, "get_cancel_requested_at"):
        cancel_requested_at = state.job_repo.get_cancel_requested_at(job_id)

    # Build flash message from query params (cancel or delete)
    flash_message = None
    flash_type = None
    if cancel_error:
        flash_message = cancel_error
        flash_type = "error"
    elif cancel_success:
        flash_message = cancel_success
        flash_type = "success"
    elif delete_error:
        flash_message = delete_error
        flash_type = "error"
    elif delete_success:
        flash_message = delete_success
        flash_type = "success"

    return templates.TemplateResponse(
        "features/jobs/details.html",
        {
            "request": request,
            "breadcrumbs": get_breadcrumbs("job_detail", job=job_id[:8]),
            "job": job,
            "logs": logs,
            "profile": profile,
            "user": user,
            "active_nav": "jobs",
            "can_cancel": job_can_cancel,
            "cancel_requested_at": cancel_requested_at,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "current_phase": current_phase,
            "phase_list": phase_list,
            "download_stats": download_stats,
            "extraction_stats": extraction_stats,
            "restore_stats": restore_stats,
            "atomic_rename_stats": atomic_rename_stats,
            # Retention management
            "can_manage_retention": (
                job.owner_user_id == user.user_id or user.is_admin
            ) if job else False,
            "retention_options": _get_retention_options(state),
            "expiring_warning_days": _get_expiring_warning_days(state),
        },
    )


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> RedirectResponse:
    """Cancel a running job."""
    from urllib.parse import urlencode

    from pulldb.domain.permissions import can_cancel_job

    base_url = f"/web/jobs/{job_id}"

    def redirect_error(msg: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'cancel_error': msg})}",
            status_code=303,
        )

    def redirect_success(msg: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'cancel_success': msg})}",
            status_code=303,
        )

    if not hasattr(state, "job_repo") or not state.job_repo:
        return redirect_error("Job repository unavailable")

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return redirect_error("Job not found")

    # Check if job is in cancelable state FIRST
    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        return redirect_error(f"Cannot cancel job (status: {job.status.value})")

    # Check if job has already entered loading phase (can_cancel = False)
    if not job.can_cancel:
        return redirect_error("Cannot cancel: job has entered loading phase")

    # Authorization check: lookup job owner to get their manager_id
    job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
    job_owner_manager_id = job_owner.manager_id if job_owner else None

    if not can_cancel_job(user, job.owner_user_id, job_owner_manager_id):
        return redirect_error("You do not have permission to cancel this job")

    # Request cancellation
    was_requested = state.job_repo.request_cancellation(job_id)

    if was_requested:
        state.job_repo.append_job_event(
            job_id=job_id,
            event_type="cancel_requested",
            detail=f"User {user.username} requested job cancellation",
        )

        # Audit log job cancellation
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="job_canceled",
                target_user_id=job.owner_user_id,
                detail=f"Canceled job {job_id[:12]} (status was {job.status.value})",
                context={
                    "job_id": job_id,
                    "previous_status": job.status.value,
                    "target": job.target,
                },
            )

        if job.status == JobStatus.QUEUED:
            state.job_repo.mark_job_canceled(
                job_id, "Canceled before execution started"
            )
            return redirect_success("Job canceled successfully")
        else:
            msg = "Cancellation requested - worker will stop at next checkpoint"
            return redirect_success(msg)
    else:
        # Cancellation failed - could be: already requested, job completed,
        # or job entered loading phase between our check and the update
        refreshed_job = state.job_repo.get_job_by_id(job_id)
        if refreshed_job and not refreshed_job.can_cancel:
            return redirect_error("Cannot cancel: job has entered loading phase")
        return redirect_error("Cancellation already requested or job completed")


@router.post("/{job_id}/delete-database")
async def delete_job_database(
    job_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> RedirectResponse:
    """Delete databases for a completed job (staging + target).
    
    Supports soft delete (status=deleted) or hard delete (remove record).
    """
    from urllib.parse import urlencode

    from pulldb.domain.permissions import can_delete_job_database
    from pulldb.worker.cleanup import delete_job_databases

    base_url = f"/web/jobs/{job_id}"

    def redirect_error(msg: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': msg})}",
            status_code=303,
        )

    def redirect_success(msg: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_success': msg})}",
            status_code=303,
        )

    if not hasattr(state, "job_repo") or not state.job_repo:
        return redirect_error("Job repository unavailable")

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return redirect_error("Job not found")

    # Must be in terminal state to delete (not active, not already deleting)
    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        return redirect_error(f"Cannot delete active job (status: {job.status.value})")

    # Block if already in deleting status (worker will retry)
    if job.status == JobStatus.DELETING:
        return redirect_error("Delete already in progress - worker will retry automatically")
    
    # Block if delete already failed (exhausted retries)
    # Only block if error_detail indicates delete failure, not other failures
    # (e.g., zombie detection, restore failure, etc. can still be deleted)
    if job.status == JobStatus.FAILED:
        error_detail = job.error_detail or ""
        if error_detail.startswith("Delete failed"):
            return redirect_error("Delete failed after max retries - contact admin for manual cleanup")
        # Otherwise, job failed for other reasons (zombie, restore error, etc.)
        # Allow deletion to proceed - databases may or may not exist

    # If already soft-deleted, force hard delete on second attempt
    force_hard_delete = job.status == JobStatus.DELETED

    # Authorization check
    job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
    job_owner_manager_id = job_owner.manager_id if job_owner else None

    if not can_delete_job_database(user, job.owner_user_id, job_owner_manager_id):
        return redirect_error("You do not have permission to delete this job")

    # Parse form data for hard_delete option
    form_data = await request.form()
    hard_delete_val = form_data.get("hard_delete", "")
    # Handle both str and UploadFile (which shouldn't happen for checkboxes)
    if isinstance(hard_delete_val, str):
        hard_delete = hard_delete_val.lower() in ("true", "1", "on")
    else:
        hard_delete = False
    
    # Parse skip_database_drops option (for inaccessible hosts)
    skip_drops_val = form_data.get("skip_database_drops", "")
    if isinstance(skip_drops_val, str):
        skip_database_drops = skip_drops_val.lower() in ("true", "1", "on")
    else:
        skip_database_drops = False

    # Force hard delete if job was already soft-deleted
    if force_hard_delete:
        hard_delete = True

    # Get job owner's user_code for validation
    job_owner_user_code = job_owner.user_code if job_owner else None

    # SUPERSEDED jobs: Skip database deletion entirely
    # When a job is superseded, its staging DB was already cleaned up by the
    # newer job's restore, and it no longer owns the target DB. No work to do.
    # Check both status AND the superseded_at flag (status may not be updated
    # if the job was in a transient state when superseded).
    skip_database_deletion = (
        job.status == JobStatus.SUPERSEDED or job.is_superseded
    )

    if skip_database_deletion:
        # Create a dummy result for audit logging
        from pulldb.worker.cleanup import JobDeleteResult
        result = JobDeleteResult(
            job_id=job_id,
            staging_name=job.staging_name,
            target_name=job.target,
            dbhost=job.dbhost,
        )
        result.staging_existed = False
        result.target_existed = False
        # Log that we skipped deletion
        state.job_repo.append_job_event(
            job_id, "delete_skipped", 
            '{"reason": "superseded_job_no_databases_owned"}'
        )
    else:
        # Mark job as deleting FIRST (enables worker recovery if request times out)
        # This sets started_at for stale detection and increments retry_count
        state.job_repo.mark_job_deleting(job_id)

        # Perform the delete synchronously
        result = delete_job_databases(
            job_id=job_id,
            staging_name=job.staging_name,
            target_name=job.target,
            owner_user_code=job_owner_user_code or "",
            dbhost=job.dbhost,
            host_repo=state.host_repo,
            job_repo=state.job_repo,
            skip_database_drops=skip_database_drops,
            custom_target=job.custom_target,
        )

    # Audit log the delete operation
    if hasattr(state, "audit_repo") and state.audit_repo:
        state.audit_repo.log_action(
            actor_user_id=user.user_id,
            action="job_delete_requested",
            target_user_id=job.owner_user_id,
            detail=f"{'Hard' if hard_delete else 'Soft'} delete job {job_id[:12]} target={job.target}",
            context={
                "job_id": job_id,
                "hard_delete": hard_delete,
                "target": job.target,
                "owner_user_code": job_owner_user_code,
                "staging_existed": result.staging_existed,
                "staging_dropped": result.staging_dropped,
                "target_existed": result.target_existed,
                "target_dropped": result.target_dropped,
                "error": result.error,
            },
        )

    if hard_delete:
        # Hard delete: remove the job record entirely
        state.job_repo.hard_delete_job(job_id)
        # Build descriptive message
        if result.staging_existed or result.target_existed:
            msg = f"Job {job_id[:12]} hard deleted"
            details = []
            if result.staging_existed:
                details.append(f"staging={'dropped' if result.staging_dropped else 'failed to drop'}")
            if result.target_existed:
                details.append(f"target={'dropped' if result.target_dropped else 'failed to drop'}")
            msg += f" ({', '.join(details)})"
        else:
            msg = f"Job {job_id[:12]} hard deleted (databases did not exist)"
        # Redirect to jobs list since detail page won't exist
        return RedirectResponse(
            url=f"/web/jobs?view=history&{urlencode({'delete_success': msg})}",
            status_code=303,
        )
    else:
        # Soft delete: mark status as deleted
        state.job_repo.mark_job_deleted(job_id)

        # Build detailed event log entry
        if result.staging_existed or result.target_existed:
            details = []
            if result.staging_existed:
                details.append(f"staging={'dropped' if result.staging_dropped else 'failed'}")
            else:
                details.append("staging=did not exist")
            if result.target_existed:
                details.append(f"target={'dropped' if result.target_dropped else 'failed'}")
            else:
                details.append("target=did not exist")
            event_detail = f"User {user.username} deleted databases ({', '.join(details)})"
            msg = f"Databases deleted ({', '.join(details)})"
        else:
            event_detail = f"User {user.username} marked job deleted (databases did not exist)"
            msg = "Job marked deleted (databases did not exist)"

        state.job_repo.append_job_event(
            job_id=job_id,
            event_type="deleted",
            detail=event_detail,
        )
        return redirect_success(msg)


@router.get("/api/paginated")
async def api_jobs_paginated(
    request: Request,
    view: str = Query("active", description="View: 'active' or 'history'"),
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: str | None = None,
    sortDirection: str = "asc",
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Get paginated jobs for LazyTable.
    
    Returns jobs based on view (active or history) with filtering/sorting.
    
    Active view: Owned databases (in-progress + complete not dropped/superseded)
    History view: Failed, canceled, dropped, superseded jobs
    """
    jobs = []
    
    if not hasattr(state, "job_repo") or not state.job_repo:
        return {"rows": [], "totalCount": 0, "filteredCount": 0}
    
    # Fetch jobs based on view
    if view == "history":
        # History: failed, canceled, deleted, or dropped/superseded complete jobs
        if hasattr(state.job_repo, "get_job_history_v2"):
            jobs = state.job_repo.get_job_history_v2(limit=10000)
        elif hasattr(state.job_repo, "get_recent_jobs"):
            jobs = state.job_repo.get_recent_jobs(limit=10000)
            # Filter to terminal statuses or dropped/superseded
            jobs = [
                j for j in jobs 
                if j.status in (JobStatus.FAILED, JobStatus.CANCELED, JobStatus.DELETED, JobStatus.DELETING, JobStatus.COMPLETE)
            ]
        else:
            jobs = list(getattr(state.job_repo, "history_jobs", []))
    else:  # active
        # Active: owned databases (in-progress + complete not dropped/superseded)
        if hasattr(state.job_repo, "get_owned_databases"):
            jobs = state.job_repo.get_owned_databases(limit=10000)
        elif hasattr(state.job_repo, "get_active_jobs"):
            jobs = state.job_repo.get_active_jobs()
        else:
            jobs = list(getattr(state.job_repo, "active_jobs", []))
    
    # Convert to dicts for filtering/sorting
    all_rows = []
    for j in jobs:
        # Determine if user can cancel this job
        # Requires: correct status + can_cancel flag from DB + permission
        can_cancel = False
        if j.status in (JobStatus.QUEUED, JobStatus.RUNNING) and j.can_cancel:
            if user.is_admin:
                can_cancel = True
            elif j.owner_user_id == user.user_id:
                can_cancel = True
            elif user.role == UserRole.MANAGER:
                # Check if job owner is managed by this user
                job_owner = state.user_repo.get_user_by_id(j.owner_user_id) if state.user_repo else None
                if job_owner and job_owner.manager_id == user.user_id:
                    can_cancel = True
        
        # Determine if user can delete this job (terminal jobs only)
        # Also allow for 'deleted' status to enable hard delete (remove job record)
        can_delete = False
        if j.status not in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DELETING):
            if user.is_admin:
                can_delete = True
            elif j.owner_user_id == user.user_id:
                can_delete = True
            elif user.role == UserRole.MANAGER:
                # Check if job owner is managed by this user
                job_owner = state.user_repo.get_user_by_id(j.owner_user_id) if state.user_repo else None
                if job_owner and job_owner.manager_id == user.user_id:
                    can_delete = True
        
        cancel_requested_at = None
        if hasattr(state.job_repo, "get_cancel_requested_at"):
            cancel_requested_at = state.job_repo.get_cancel_requested_at(j.id)
        
        all_rows.append({
            "id": j.id,
            "owner_user_id": j.owner_user_id,
            "owner_username": getattr(j, "owner_username", None),
            "owner_user_code": getattr(j, "owner_user_code", None),
            "target": j.target,
            "dbhost": j.dbhost,
            "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            "submitted_at": j.submitted_at.isoformat() if j.submitted_at else None,
            "started_at": j.started_at.isoformat() if getattr(j, "started_at", None) else None,
            "completed_at": j.completed_at.isoformat() if getattr(j, "completed_at", None) else None,
            "can_cancel": can_cancel,
            "can_delete": can_delete,
            "cancel_requested_at": cancel_requested_at.isoformat() if cancel_requested_at else None,
            # Retention fields (use walrus operator to avoid repeated getattr)
            "expires_at": (exp := getattr(j, "expires_at", None)) and exp.isoformat(),
            "locked_at": (lock := getattr(j, "locked_at", None)) and lock.isoformat(),
            "is_locked": getattr(j, "locked_at", None) is not None,
            "db_dropped_at": (drop := getattr(j, "db_dropped_at", None)) and drop.isoformat(),
            "superseded_at": (sup := getattr(j, "superseded_at", None)) and sup.isoformat(),
        })
    
    total_count = len(all_rows)
    
    # Apply filters from query params
    text_filters: dict[str, list[str]] = {}
    date_after: dict[str, str] = {}
    date_before: dict[str, str] = {}
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
            # Handle date range filters
            if col_key.endswith("_after"):
                base_col = col_key[:-6]
                date_after[base_col] = value
                continue
            if col_key.endswith("_before"):
                base_col = col_key[:-7]
                date_before[base_col] = value
                continue
            
            # Text/multi-value filter
            text_filters[col_key] = [v.strip().lower() for v in value.split(",") if v.strip()]
    
    if text_filters or date_after or date_before:
        filtered = []
        for row in all_rows:
            match = True
            
            # Text filters
            for col, vals in text_filters.items():
                cell = str(row.get(col, "")).lower()
                # Support wildcard patterns
                if any("*" in v for v in vals):
                    import fnmatch
                    if not any(fnmatch.fnmatch(cell, v) for v in vals):
                        match = False
                        break
                else:
                    if not any(v in cell for v in vals):
                        match = False
                        break
            
            # Date range filters
            for col, after_date in date_after.items():
                cell_val = row.get(col)
                if cell_val and cell_val < after_date:
                    match = False
                    break
            
            for col, before_date in date_before.items():
                cell_val = row.get(col)
                if cell_val and cell_val > before_date:
                    match = False
                    break
            
            if match:
                filtered.append(row)
        all_rows = filtered
    
    filtered_count = len(all_rows)
    
    # Apply sorting
    sortable_cols = ("id", "owner_user_code", "status", "submitted_at", "started_at", "completed_at", "dbhost", "target")
    if sortColumn in sortable_cols:
        reverse = sortDirection == "desc"
        all_rows.sort(
            key=lambda r: (r.get(sortColumn) is None, str(r.get(sortColumn) or "").lower()),
            reverse=reverse,
        )
    
    # Paginate
    start = page * pageSize
    page_rows = all_rows[start:start + pageSize]
    
    return {
        "rows": page_rows,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/api/paginated/distinct")
async def api_jobs_distinct(
    request: Request,
    column: str,
    view: str = "active",
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> list:
    """Get distinct values for a column (for filter dropdowns)."""
    jobs = []
    
    if not hasattr(state, "job_repo") or not state.job_repo:
        return []
    
    # Fetch jobs based on view
    if view == "history":
        if hasattr(state.job_repo, "get_recent_jobs"):
            jobs = state.job_repo.get_recent_jobs(limit=10000)
            jobs = [j for j in jobs if j.status not in (JobStatus.QUEUED, JobStatus.RUNNING)]
        else:
            jobs = list(getattr(state.job_repo, "history_jobs", []))
    else:
        if hasattr(state.job_repo, "get_active_jobs"):
            jobs = state.job_repo.get_active_jobs()
        else:
            jobs = list(getattr(state.job_repo, "active_jobs", []))
    
    # Extract distinct values
    values = set()
    for j in jobs:
        if column == "status":
            val = j.status.value if hasattr(j.status, "value") else str(j.status)
        elif column == "dbhost":
            val = j.dbhost
        elif column == "owner_user_code":
            val = getattr(j, "owner_user_code", None)
        elif column == "target":
            val = j.target
        else:
            val = getattr(j, column, None)
        
        if val:
            values.add(val)
    
    return sorted(values)


@router.post("/bulk-delete")
async def bulk_delete_jobs(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Create a bulk delete admin task for multiple jobs.
    
    Validates permissions upfront for ALL jobs before creating task.
    Returns task_id for polling status.
    """
    from pulldb.domain.permissions import can_delete_job_database

    if not hasattr(state, "job_repo") or not state.job_repo:
        return {"error": "Job repository unavailable", "success": False}

    # Parse JSON body
    try:
        body = await request.json()
        job_ids = body.get("job_ids", [])
        hard_delete = body.get("hard_delete", False)
        skip_database_drops = body.get("skip_database_drops", False)
    except Exception:
        logger.debug("Invalid JSON in bulk delete request", exc_info=True)
        return {"error": "Invalid JSON body", "success": False}

    if not job_ids:
        return {"error": "No jobs specified", "success": False}

    if len(job_ids) > 500:
        return {"error": "Maximum 500 jobs per bulk delete", "success": False}

    # Validate ALL permissions upfront
    job_infos = []
    permission_errors = []
    skipped_already_deleted = 0

    for job_id in job_ids:
        job = state.job_repo.get_job_by_id(job_id)
        if not job:
            permission_errors.append(f"Job {job_id[:12]} not found")
            continue

        # Must be in terminal state
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            permission_errors.append(
                f"Job {job_id[:12]} is active (status: {job.status.value})"
            )
            continue

        # Already soft-deleted? Skip for soft delete, allow for hard delete
        if job.status == JobStatus.DELETED and not hard_delete:
            # Track skipped jobs - user needs to enable hard_delete to remove records
            skipped_already_deleted += 1
            continue

        # Check permission
        job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
        job_owner_manager_id = job_owner.manager_id if job_owner else None

        if not can_delete_job_database(user, job.owner_user_id, job_owner_manager_id):
            owner_code = job_owner.user_code if job_owner else "unknown"
            permission_errors.append(
                f"No permission to delete job {job_id[:12]} (owner: {owner_code})"
            )
            continue

        # Collect info for task (all fields needed by admin_tasks executor)
        job_infos.append({
            "job_id": job_id,
            "staging_name": job.staging_name,
            "target": job.target,
            "owner_user_code": job_owner.user_code if job_owner else "",
            "owner_user_id": job.owner_user_id,
            "dbhost": job.dbhost,
        })

    # If any permission errors, fail the whole request
    if permission_errors:
        return {
            "error": "Permission check failed",
            "details": permission_errors,
            "success": False,
        }

    # All validated - create admin task
    if not job_infos:
        if skipped_already_deleted > 0:
            # Informational: jobs exist but are already soft-deleted
            return {
                "success": True,
                "message": f"{skipped_already_deleted} job(s) already deleted. Enable 'Remove job history records' to permanently remove them.",
                "skipped_count": skipped_already_deleted,
            }
        return {"error": "No deletable jobs found", "success": False}

    # Audit log the bulk delete request
    if hasattr(state, "audit_repo") and state.audit_repo:
        state.audit_repo.log_action(
            actor_user_id=user.user_id,
            action="bulk_delete_jobs_requested",
            detail=f"Bulk {'hard' if hard_delete else 'soft'} delete {len(job_infos)} jobs",
            context={
                "job_count": len(job_infos),
                "hard_delete": hard_delete,
                "job_ids": [ji["job_id"] for ji in job_infos],
            },
        )

    # Create admin task
    from pulldb.infra.mysql import AdminTaskRepository
    admin_task_repo = AdminTaskRepository(state.job_repo.pool)
    task_id = admin_task_repo.create_bulk_delete_task(
        requested_by=user.user_id,
        job_infos=job_infos,
        hard_delete=hard_delete,
        skip_database_drops=skip_database_drops,
    )

    return {
        "success": True,
        "task_id": task_id,
        "job_count": len(job_infos),
    }


@router.get("/bulk-delete/{task_id}/status")
async def bulk_delete_status(
    task_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Get status of a bulk delete task for polling."""
    if not hasattr(state, "job_repo") or not state.job_repo:
        return {"error": "Job repository unavailable"}

    from pulldb.infra.mysql import AdminTaskRepository
    admin_task_repo = AdminTaskRepository(state.job_repo.pool)
    task = admin_task_repo.get_task(task_id)
    if not task:
        return {"error": "Task not found"}

    # Only task creator or admin can view status
    if task.requested_by != user.user_id and not user.is_admin:
        return {"error": "Access denied"}

    # Parse result_json for progress
    result = task.result_json or {}
    progress = result.get("progress", {})

    return {
        "task_id": task_id,
        "status": task.status.value,
        "total": progress.get("total", 0),
        "processed": progress.get("processed", 0),
        "soft_deleted": progress.get("soft_deleted", 0),
        "hard_deleted": progress.get("hard_deleted", 0),
        "errors": progress.get("errors", []),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


# =============================================================================
# Database Retention Actions (extend, lock, unlock)
# =============================================================================


@router.post("/{job_id}/extend")
async def extend_job_retention(
    request: Request,
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> RedirectResponse:
    """Extend the retention period for a job's database."""
    from urllib.parse import urlencode
    from fastapi.concurrency import run_in_threadpool

    base_url = f"/web/jobs/{job_id}"

    # Parse form data - now expects days instead of months
    form = await request.form()
    days_str = form.get("days", form.get("months", "7"))  # Support both for compatibility
    try:
        days = int(str(days_str))
    except (TypeError, ValueError):
        days = 7  # Default to 1 week

    if not hasattr(state, "job_repo") or not state.job_repo:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Job repository unavailable'})}",
            status_code=303,
        )

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Job not found'})}",
            status_code=303,
        )

    # Authorization: job owner or admin
    if job.owner_user_id != user.user_id and not user.is_admin:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Permission denied'})}",
            status_code=303,
        )

    try:
        from pulldb.worker.retention import RetentionService

        settings_repo = getattr(state, "settings_repo", None)
        retention_service = RetentionService(
            job_repo=state.job_repo,
            user_repo=state.user_repo,
            settings_repo=settings_repo,  # type: ignore[arg-type]
        )
        await run_in_threadpool(
            retention_service.extend_job,
            job_id,
            days,
            user.user_id,
        )
        # Format duration for message
        if days == 0:
            duration_msg = "set to expire now"
        elif days == 1:
            duration_msg = "extended by 1 day"
        elif days < 7:
            duration_msg = f"extended by {days} days"
        elif days == 7:
            duration_msg = "extended by 1 week"
        elif days < 30:
            duration_msg = f"extended by {days // 7} weeks"
        elif days < 60:
            duration_msg = "extended by 1 month"
        else:
            duration_msg = f"extended by {days // 30} months"
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_success': f'Retention {duration_msg}'})}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': str(e)})}",
            status_code=303,
        )


@router.post("/{job_id}/lock")
async def lock_job_database(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> RedirectResponse:
    """Lock a job's database to prevent automatic cleanup."""
    from urllib.parse import urlencode
    from fastapi.concurrency import run_in_threadpool

    base_url = f"/web/jobs/{job_id}"

    if not hasattr(state, "job_repo") or not state.job_repo:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Job repository unavailable'})}",
            status_code=303,
        )

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Job not found'})}",
            status_code=303,
        )

    # Authorization: job owner or admin
    if job.owner_user_id != user.user_id and not user.is_admin:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Permission denied'})}",
            status_code=303,
        )

    try:
        from pulldb.worker.retention import RetentionService

        settings_repo = getattr(state, "settings_repo", None)
        retention_service = RetentionService(
            job_repo=state.job_repo,
            user_repo=state.user_repo,
            settings_repo=settings_repo,  # type: ignore[arg-type]
        )
        await run_in_threadpool(
            retention_service.lock_job,
            job_id,
            user.user_id,
            "Locked via job detail page",
        )
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_success': 'Database locked'})}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': str(e)})}",
            status_code=303,
        )


@router.post("/{job_id}/unlock")
async def unlock_job_database(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> RedirectResponse:
    """Unlock a job's database to allow automatic cleanup."""
    from urllib.parse import urlencode
    from fastapi.concurrency import run_in_threadpool

    base_url = f"/web/jobs/{job_id}"

    if not hasattr(state, "job_repo") or not state.job_repo:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Job repository unavailable'})}",
            status_code=303,
        )

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Job not found'})}",
            status_code=303,
        )

    # Authorization: admin only for unlock (managers can lock for team but admin for unlock)
    # Actually, for simplicity, allow job owner or admin to unlock
    if job.owner_user_id != user.user_id and not user.is_admin:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': 'Permission denied'})}",
            status_code=303,
        )

    try:
        from pulldb.worker.retention import RetentionService

        settings_repo = getattr(state, "settings_repo", None)
        retention_service = RetentionService(
            job_repo=state.job_repo,
            user_repo=state.user_repo,
            settings_repo=settings_repo,  # type: ignore[arg-type]
        )
        await run_in_threadpool(
            retention_service.unlock_job,
            job_id,
            user.user_id,
        )
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_success': 'Database unlocked'})}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'delete_error': str(e)})}",
            status_code=303,
        )


@router.post("/{job_id}/user-complete")
async def user_complete_job(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> JSONResponse:
    """Mark a deployed job as complete (user is done with the database).
    
    Moves the job from Active view to History view.
    The database remains until cleanup runs based on retention settings.
    """
    from fastapi.concurrency import run_in_threadpool

    if not hasattr(state, "job_repo") or not state.job_repo:
        return JSONResponse(
            content={"detail": "Job repository unavailable"},
            status_code=503,
        )

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return JSONResponse(
            content={"detail": "Job not found"},
            status_code=404,
        )

    # Only deployed jobs can be marked complete
    if job.status != JobStatus.DEPLOYED:
        return JSONResponse(
            content={"detail": f"Cannot mark {job.status.value} job as complete"},
            status_code=400,
        )

    # Authorization: job owner, manager, or admin
    if job.owner_user_id != user.user_id and not user.is_admin and user.role != UserRole.MANAGER:
        return JSONResponse(
            content={"detail": "Permission denied"},
            status_code=403,
        )

    try:
        await run_in_threadpool(
            state.job_repo.mark_job_user_completed,
            job_id,
        )
        return JSONResponse(
            content={"status": "ok", "message": "Job marked as complete"},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            content={"detail": str(e)},
            status_code=500,
        )


@router.post("/api/{job_id}/lock")
async def api_lock_job(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> JSONResponse:
    """Lock a job's database via API (for AJAX calls)."""
    from fastapi.concurrency import run_in_threadpool

    if not hasattr(state, "job_repo") or not state.job_repo:
        return JSONResponse(
            content={"detail": "Job repository unavailable"},
            status_code=503,
        )

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return JSONResponse(
            content={"detail": "Job not found"},
            status_code=404,
        )

    # Authorization: job owner, manager, or admin
    if job.owner_user_id != user.user_id and not user.is_admin and user.role != UserRole.MANAGER:
        return JSONResponse(
            content={"detail": "Permission denied"},
            status_code=403,
        )

    try:
        from pulldb.worker.retention import RetentionService

        settings_repo = getattr(state, "settings_repo", None)
        retention_service = RetentionService(
            job_repo=state.job_repo,
            user_repo=state.user_repo,
            settings_repo=settings_repo,  # type: ignore[arg-type]
        )
        success = await run_in_threadpool(
            retention_service.lock_job,
            job_id,
            user.user_id,
            "Locked via Jobs page",
        )
        if not success:
            return JSONResponse(
                content={"detail": "Database could not be locked (may already be locked or not deployed)"},
                status_code=400,
            )
        return JSONResponse(
            content={"status": "ok", "message": "Database locked"},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            content={"detail": str(e)},
            status_code=500,
        )


@router.post("/api/{job_id}/unlock")
async def api_unlock_job(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> JSONResponse:
    """Unlock a job's database via API (for AJAX calls)."""
    from fastapi.concurrency import run_in_threadpool

    if not hasattr(state, "job_repo") or not state.job_repo:
        return JSONResponse(
            content={"detail": "Job repository unavailable"},
            status_code=503,
        )

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return JSONResponse(
            content={"detail": "Job not found"},
            status_code=404,
        )

    # Authorization: job owner, manager, or admin
    if job.owner_user_id != user.user_id and not user.is_admin and user.role != UserRole.MANAGER:
        return JSONResponse(
            content={"detail": "Permission denied"},
            status_code=403,
        )

    try:
        from pulldb.worker.retention import RetentionService

        settings_repo = getattr(state, "settings_repo", None)
        retention_service = RetentionService(
            job_repo=state.job_repo,
            user_repo=state.user_repo,
            settings_repo=settings_repo,  # type: ignore[arg-type]
        )
        success = await run_in_threadpool(
            retention_service.unlock_job,
            job_id,
            user.user_id,
        )
        if not success:
            return JSONResponse(
                content={"detail": "Database could not be unlocked (may already be unlocked or not found)"},
                status_code=400,
            )
        return JSONResponse(
            content={"status": "ok", "message": "Database unlocked"},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            content={"detail": str(e)},
            status_code=500,
        )


@router.post("/api/mark-expired")
async def api_mark_jobs_expired(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> JSONResponse:
    """Mark expired deployed jobs as 'expired' status.
    
    Called by frontend when it detects jobs with expires_at in the past.
    Updates status from 'deployed' to 'expired' which moves them to History.
    """
    from fastapi.concurrency import run_in_threadpool

    if not hasattr(state, "job_repo") or not state.job_repo:
        return JSONResponse(
            content={"detail": "Job repository unavailable"},
            status_code=503,
        )

    try:
        body = await request.json()
        job_ids = body.get("job_ids", [])
        
        if not job_ids:
            return JSONResponse(
                content={"updated": 0},
                status_code=200,
            )
        
        # Use batch method to update all at once
        updated = await run_in_threadpool(
            state.job_repo.mark_jobs_expired_batch,
            job_ids,
        )
        
        return JSONResponse(
            content={"updated": updated},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            content={"detail": str(e)},
            status_code=500,
        )
