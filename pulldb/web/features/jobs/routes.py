"""Jobs routes for Web2 interface."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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
            # History view - use get_job_history with filters
            if hasattr(state.job_repo, "get_job_history"):
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
        # Active view
        elif q and len(q) >= 4:
            # Search mode
            exact = len(q) >= 5
            jobs = state.job_repo.search_jobs(q, limit=page_size, exact=exact)
            # Filter to active only
            jobs = [
                j for j in jobs if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            ]
        elif hasattr(state.job_repo, "get_active_jobs"):
            jobs = state.job_repo.get_active_jobs()

            # Apply filters
            if status:
                jobs = [j for j in jobs if j.status.value == status]
            if host:
                jobs = [j for j in jobs if j.dbhost == host]
        else:
            # Fallback for mock
            jobs = getattr(state.job_repo, "active_jobs", [])

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
            "status": status,
            "host": host,
            "hosts": hosts,
            "days": days,
            "user_code": user_code,
            "target_filter": target,
            # Role-based filter defaults
            "managed_user_codes": _get_managed_user_codes(state, user),
            "three_days_ago_iso": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
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
    "extraction_complete": "extraction",
    "format_detected": "extraction",
    "restore_started": "myloader",
    "restore_progress": "myloader",
    "restore_complete": "post_sql",
    "post_sql_started": "post_sql",
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
    current_phase = "queued"
    for event in reversed(logs):
        event_type = getattr(event, "event_type", "")
        if event_type in EVENT_TO_PHASE:
            current_phase = EVENT_TO_PHASE[event_type]
            break

    # Override for terminal states
    if job_status == "complete":
        current_phase = "complete"
    elif job_status == "failed":
        current_phase = "failed"
    elif job_status == "canceled":
        current_phase = "canceled"

    # Build phase list with states
    phase_list = []
    found_current = False
    for phase_id, phase_label in JOB_PHASES:
        if phase_id == current_phase:
            # Active state for running OR queued jobs on their respective phases
            if job_status in ("running", "queued"):
                state = "active"
            elif job_status == "failed":
                state = "failed"
            else:
                state = "complete"
            found_current = True
        elif found_current:
            state = "pending"
        else:
            state = "complete"
        phase_list.append({"id": phase_id, "label": phase_label, "state": state})

    return current_phase, phase_list


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_details(
    request: Request,
    job_id: str,
    cancel_error: str | None = Query(None),
    cancel_success: str | None = Query(None),
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

    if hasattr(state, "job_repo") and state.job_repo:
        job = state.job_repo.get_job_by_id(job_id)
        if job:
            logs = state.job_repo.get_job_events(job_id)

            # Derive current phase for progress indicator
            current_phase, phase_list = _derive_current_phase(logs, job.status.value)

            # Compute can_cancel for this user
            job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
            job_owner_manager_id = job_owner.manager_id if job_owner else None
            job_can_cancel = can_cancel_job(
                user, job.owner_user_id, job_owner_manager_id
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

    # Build flash message from query params
    flash_message = None
    flash_type = None
    if cancel_error:
        flash_message = cancel_error
        flash_type = "error"
    elif cancel_success:
        flash_message = cancel_success
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

        if job.status == JobStatus.QUEUED:
            state.job_repo.mark_job_canceled(
                job_id, "Canceled before execution started"
            )
            return redirect_success("Job canceled successfully")
        else:
            msg = "Cancellation requested - worker will stop at next checkpoint"
            return redirect_success(msg)
    else:
        # Cancellation was already requested or job state changed
        return redirect_error("Cancellation already requested or job completed")


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
    """
    jobs = []
    
    if not hasattr(state, "job_repo") or not state.job_repo:
        return {"rows": [], "totalCount": 0, "filteredCount": 0}
    
    # Fetch jobs based on view
    if view == "history":
        if hasattr(state.job_repo, "get_recent_jobs"):
            jobs = state.job_repo.get_recent_jobs(limit=10000)  # Get all for filtering
            # Filter to terminal statuses only
            jobs = [j for j in jobs if j.status not in (JobStatus.QUEUED, JobStatus.RUNNING)]
        else:
            jobs = list(getattr(state.job_repo, "history_jobs", []))
    else:  # active
        if hasattr(state.job_repo, "get_active_jobs"):
            jobs = state.job_repo.get_active_jobs()
        else:
            jobs = list(getattr(state.job_repo, "active_jobs", []))
    
    # Convert to dicts for filtering/sorting
    all_rows = []
    for j in jobs:
        # Determine if user can cancel this job
        can_cancel = False
        if j.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            if user.is_admin:
                can_cancel = True
            elif j.owner_user_id == user.user_id:
                can_cancel = True
            elif user.role == UserRole.MANAGER:
                # Check if job owner is managed by this user
                job_owner = state.user_repo.get_user_by_id(j.owner_user_id) if state.user_repo else None
                if job_owner and job_owner.manager_id == user.user_id:
                    can_cancel = True
        
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
            "cancel_requested_at": cancel_requested_at.isoformat() if cancel_requested_at else None,
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
