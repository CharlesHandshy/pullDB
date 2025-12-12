"""Admin routes for Web2 interface."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import JobStatus, User
from pulldb.web.dependencies import get_api_state, require_admin

router = APIRouter(prefix="/web/admin", tags=["web-admin"])
templates = Jinja2Templates(directory="pulldb/web/templates")


@router.get("/", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    prune_success: int | None = None,
    prune_jobs: int | None = None,
    prune_error: str | None = None,
) -> HTMLResponse:
    """Render the admin page."""
    # Build flash message from query params (set by prune redirect)
    flash_message = None
    flash_type = None
    if prune_success is not None and prune_jobs is not None:
        flash_message = f"Successfully deleted {prune_success} events from {prune_jobs} job(s)"
        flash_type = "success"
    elif prune_error:
        flash_message = f"Prune failed: {prune_error}"
        flash_type = "error"

    # Gather stats
    users = []
    if hasattr(state.user_repo, "list_users"):
        users = state.user_repo.list_users()

    hosts = []
    if (
        hasattr(state, "host_repo")
        and state.host_repo
        and hasattr(state.host_repo, "list_hosts")
    ):
        hosts = state.host_repo.list_hosts()

    # Get job counts
    active_jobs = []
    if hasattr(state.job_repo, "get_active_jobs"):
        active_jobs = state.job_repo.get_active_jobs()

    stats = {
        "total_users": len(users),
        "admin_users": len([u for u in users if u.is_admin]),
        "total_hosts": len(hosts),
        "enabled_hosts": len([h for h in hosts if getattr(h, "enabled", True)]),
        "active_jobs": len(active_jobs),
        "running_jobs": len([j for j in active_jobs if j.status == JobStatus.RUNNING]),
        "pending_jobs": len([j for j in active_jobs if j.status == JobStatus.QUEUED]),
    }

    return templates.TemplateResponse(
        "features/admin/admin.html",
        {
            "request": request,
            "stats": stats,
            "user": user,
            "flash_message": flash_message,
            "flash_type": flash_type,
        },
    )


def _enrich_user(user_obj: Any, job_repo: Any) -> dict:
    """Enrich user object with computed fields for template.
    
    Adds: active_jobs, total_jobs, disabled (bool from disabled_at)
    """
    active_jobs = 0
    total_jobs = 0
    
    if job_repo:
        if hasattr(job_repo, "get_active_jobs"):
            active_jobs_list = job_repo.get_active_jobs()
            active_jobs = len([j for j in active_jobs_list 
                              if getattr(j, "owner_user_code", None) == user_obj.user_code])
        if hasattr(job_repo, "count_jobs_by_user"):
            total_jobs = job_repo.count_jobs_by_user(user_obj.user_code)
    
    return {
        "user_id": user_obj.user_id,
        "username": user_obj.username,
        "user_code": user_obj.user_code,
        "is_admin": user_obj.is_admin,
        "role": user_obj.role,
        "manager_id": getattr(user_obj, "manager_id", None),
        "created_at": user_obj.created_at,
        "disabled_at": user_obj.disabled_at,
        "allowed_hosts": getattr(user_obj, "allowed_hosts", None),
        "default_host": getattr(user_obj, "default_host", None),
        # Computed fields
        "active_jobs": active_jobs,
        "total_jobs": total_jobs,
        "disabled": user_obj.disabled_at is not None,
    }


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """List all users with search and filtering."""
    raw_users = []
    if hasattr(state.user_repo, "list_users"):
        raw_users = state.user_repo.list_users()
    
    # Apply search filter
    if q:
        q_lower = q.lower()
        raw_users = [u for u in raw_users if 
                 q_lower in u.username.lower() or 
                 q_lower in (u.user_code or "").lower() or
                 q_lower in u.role.value.lower()]
    
    # Apply role filter
    if role:
        raw_users = [u for u in raw_users if u.role.value.lower() == role.lower()]
    
    # Apply status filter
    if status == "active":
        raw_users = [u for u in raw_users if not u.disabled_at]
    elif status == "disabled":
        raw_users = [u for u in raw_users if u.disabled_at]
    
    # Enrich users with job stats
    users = [_enrich_user(u, state.job_repo) for u in raw_users]

    return templates.TemplateResponse(
        "features/admin/users.html",
        {
            "request": request, 
            "users": users, 
            "user": user,
            "q": q,
            "role": role,
            "status": status,
        },
    )


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Enable a user account."""
    if hasattr(state.user_repo, "enable_user"):
        state.user_repo.enable_user(user_id)
    return RedirectResponse(url="/web/admin/users", status_code=303)


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Disable a user account."""
    if hasattr(state.user_repo, "disable_user"):
        state.user_repo.disable_user(user_id)
    return RedirectResponse(url="/web/admin/users", status_code=303)


@router.post("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    new_role: str = Form(...),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Update a user's role."""
    from pulldb.domain.models import UserRole
    
    try:
        role_enum = UserRole(new_role.lower())
        if hasattr(state.user_repo, "update_role"):
            state.user_repo.update_role(user_id, role_enum)
    except ValueError:
        pass  # Invalid role, ignore
    
    return RedirectResponse(url="/web/admin/users", status_code=303)


# =============================================================================
# Hosts Management
# =============================================================================

def _enrich_host(host: Any, job_repo: Any) -> dict:
    """Enrich host object with computed fields for template.
    
    Adds: running_count, queued_count, active_restores, total_restores
    """
    # Get job counts for this host
    running_count = 0
    queued_count = 0
    total_restores = 0
    
    if job_repo and hasattr(job_repo, "get_active_jobs"):
        active_jobs = job_repo.get_active_jobs()
        for job in active_jobs:
            if getattr(job, "dbhost", None) == host.hostname:
                if job.status == JobStatus.RUNNING:
                    running_count += 1
                elif job.status == JobStatus.QUEUED:
                    queued_count += 1
    
    if job_repo and hasattr(job_repo, "count_jobs_by_host"):
        total_restores = job_repo.count_jobs_by_host(host.hostname)
    
    return {
        "id": host.id,
        "hostname": host.hostname,
        "host_alias": getattr(host, "host_alias", None),
        "credential_ref": getattr(host, "credential_ref", None),
        "max_concurrent_restores": getattr(host, "max_concurrent_restores", 2),
        "enabled": getattr(host, "enabled", True),
        "created_at": getattr(host, "created_at", None),
        # Computed fields
        "running_count": running_count,
        "queued_count": queued_count,
        "active_restores": running_count,  # Same as running_count
        "total_restores": total_restores,
    }


@router.get("/hosts", response_class=HTMLResponse)
async def list_hosts(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """List all database hosts with enriched stats."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        raw_hosts = state.host_repo.list_hosts()
        hosts = [_enrich_host(h, state.job_repo) for h in raw_hosts]
    
    # Calculate stats
    stats = {
        "total": len(hosts),
        "enabled": len([h for h in hosts if h["enabled"]]),
        "disabled": len([h for h in hosts if not h["enabled"]]),
        "active_restores": sum(h["active_restores"] for h in hosts),
    }
    
    return templates.TemplateResponse(
        "admin/hosts.html",
        {"request": request, "hosts": hosts, "stats": stats, "user": user},
    )


@router.post("/hosts/{hostname}/enable")
async def enable_host(
    hostname: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Enable a database host."""
    if hasattr(state.host_repo, "enable_host"):
        state.host_repo.enable_host(hostname)
    return RedirectResponse(url="/web/admin/hosts", status_code=303)


@router.post("/hosts/{hostname}/disable")
async def disable_host(
    hostname: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Disable a database host."""
    if hasattr(state.host_repo, "disable_host"):
        state.host_repo.disable_host(hostname)
    return RedirectResponse(url="/web/admin/hosts", status_code=303)


# =============================================================================
# Settings Management
# =============================================================================

# Default values for settings (used for comparison in UI)
SETTINGS_DEFAULTS = {
    "myloader_threads": "4",
    "myloader_overwrite": "true",
    "retention_days": "90",
    "staging_retention_days": "7",
    "max_active_jobs_global": "0",
    "max_active_jobs_per_user": "5",
    "s3_bucket_path": "",
    "work_dir": "/tmp/pulldb",
}


def _enrich_setting(setting: Any) -> dict:
    """Enrich setting object with default value for template."""
    key = getattr(setting, "setting_key", "")
    return {
        "setting_key": key,
        "setting_value": getattr(setting, "setting_value", ""),
        "description": getattr(setting, "description", None),
        "updated_at": getattr(setting, "updated_at", None),
        # Computed field
        "default": SETTINGS_DEFAULTS.get(key, ""),
    }


@router.get("/settings", response_class=HTMLResponse)
async def list_settings(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """List all system settings."""
    settings = []
    if hasattr(state, "settings_repo") and state.settings_repo and hasattr(state.settings_repo, "list_settings"):
        raw_settings = state.settings_repo.list_settings()
        settings = [_enrich_setting(s) for s in raw_settings]
    
    return templates.TemplateResponse(
        "admin/settings.html",
        {"request": request, "settings": settings, "user": user},
    )


# =============================================================================
# Prune Logs - Preview and Execute
# =============================================================================

@router.get("/prune-logs/preview", response_class=HTMLResponse)
async def prune_logs_preview(
    request: Request,
    days: int = 90,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Preview what prune-logs will delete."""
    return templates.TemplateResponse(
        "features/admin/prune_preview.html",
        {
            "request": request,
            "user": user,
            "days": days,
            "breadcrumbs": [
                {"label": "Dashboard", "url": "/web/dashboard"},
                {"label": "Admin", "url": "/web/admin/"},
                {"label": "Prune Logs", "url": None},
            ],
        },
    )


@router.get("/api/prune-candidates")
async def get_prune_candidates(
    request: Request,
    days: int = 90,
    page: int = 1,
    pageSize: int = 50,
    sortColumn: Optional[str] = None,
    sortDirection: str = "asc",
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get paginated list of jobs with events to prune.
    
    Supports LazyTable params: page, pageSize, sortColumn, sortDirection, filter_*
    """
    if not hasattr(state.job_repo, "get_prune_candidates"):
        return {"rows": [], "totalCount": 0, "filteredCount": 0, "totalEvents": 0}
    
    # Get all candidates (we'll filter/sort in memory)
    result = state.job_repo.get_prune_candidates(
        retention_days=days,
        offset=0,
        limit=10000,  # Get all for filtering
    )
    
    rows = result.get("rows", [])
    total_count = len(rows)
    
    # Extract filter params from query string
    text_filters = {}  # column -> [values]
    date_after = {}    # column -> ISO date string
    date_before = {}   # column -> ISO date string
    date_columns = ["oldest_event", "newest_event"]
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
            # Check for date range suffixes
            if col_key.endswith("_after"):
                base_col = col_key[:-6]
                if base_col in date_columns:
                    date_after[base_col] = value
                    continue
            if col_key.endswith("_before"):
                base_col = col_key[:-7]
                if base_col in date_columns:
                    date_before[base_col] = value
                    continue
            
            # Regular filter (could be multi-value comma-separated)
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]
    
    # Apply filters
    if text_filters or date_after or date_before:
        from datetime import datetime
        filtered_rows = []
        for row in rows:
            match = True
            
            # Check text filters (any of the values match)
            for col_key, filter_vals in text_filters.items():
                cell_val = str(row.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            
            # Check date after filters
            if match:
                for col_key, after_val in date_after.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(after_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt < cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            # Check date before filters
            if match:
                for col_key, before_val in date_before.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(before_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt > cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            if match:
                filtered_rows.append(row)
        rows = filtered_rows
    
    filtered_count = len(rows)
    
    # Apply sorting
    if sortColumn and sortColumn in ["job_id", "target", "user_code", "status", "oldest_event", "event_count"]:
        reverse = sortDirection.lower() == "desc"
        rows = sorted(rows, key=lambda r: (r.get(sortColumn) is None, r.get(sortColumn, "")), reverse=reverse)
    
    # Apply pagination (LazyTable sends 0-indexed page)
    offset = page * pageSize
    paginated_rows = rows[offset:offset + pageSize]
    
    return {
        "rows": paginated_rows,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "totalEvents": result.get("totalEvents", 0),
    }


@router.get("/api/prune-candidates/distinct")
async def get_prune_distinct_values(
    column: str,
    days: int = 90,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> list:
    """Get distinct values for filter dropdowns."""
    if not hasattr(state.job_repo, "get_prune_candidates"):
        return []
    result = state.job_repo.get_prune_candidates(retention_days=days, offset=0, limit=10000)
    rows = result.get("rows", [])
    values = set()
    for row in rows:
        val = row.get(column)
        if val is not None:
            values.add(str(val))
    return sorted(values)


@router.post("/prune-logs/execute")
async def prune_logs_execute(
    request: Request,
    days: int = Form(90),
    include_ids: str = Form(""),  # Comma-separated job IDs to prune
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute prune-logs on specific job IDs."""
    include_list = [x.strip() for x in include_ids.split(",") if x.strip()]
    
    deleted_count = 0
    job_count = len(include_list)
    error_msg = None

    if include_list:
        try:
            if hasattr(state.job_repo, "prune_job_events_by_ids"):
                deleted_count = state.job_repo.prune_job_events_by_ids(job_ids=include_list)
            elif hasattr(state.job_repo, "prune_job_events_excluding"):
                # Fallback: get all candidates, compute exclude list
                result = state.job_repo.get_prune_candidates(retention_days=days, offset=0, limit=10000)
                all_ids = {row["job_id"] for row in result.get("rows", [])}
                exclude_list = list(all_ids - set(include_list))
                deleted_count = state.job_repo.prune_job_events_excluding(
                    retention_days=days,
                    exclude_job_ids=exclude_list,
                )
        except Exception as e:
            error_msg = str(e)

    # Redirect with feedback params
    if error_msg:
        from urllib.parse import quote
        return RedirectResponse(
            url=f"/web/admin/?prune_error={quote(error_msg)}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/web/admin/?prune_success={deleted_count}&prune_jobs={job_count}",
        status_code=303,
    )


# Legacy endpoint for backward compatibility
@router.post("/prune-logs")
async def prune_logs(
    days: int = Form(90),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Prune old logs (legacy - redirects to preview)."""
    return RedirectResponse(url=f"/web/admin/prune-logs/preview?days={days}", status_code=303)


# =============================================================================
# Cleanup Staging - Preview and Execute
# =============================================================================

@router.get("/cleanup-staging/preview", response_class=HTMLResponse)
async def cleanup_staging_preview(
    request: Request,
    days: int = 7,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    cleanup_success: int | None = None,
    cleanup_total: int | None = None,
    cleanup_skipped: int | None = None,
    cleanup_error: str | None = None,
) -> HTMLResponse:
    """Preview what cleanup-staging will delete."""
    # Build flash message from query params (set by cleanup execute redirect)
    flash_message = None
    flash_type = None
    if cleanup_success is not None and cleanup_total is not None:
        if cleanup_skipped:
            flash_message = f"Dropped {cleanup_success} of {cleanup_total} databases ({cleanup_skipped} skipped - active jobs)"
        else:
            flash_message = f"Successfully dropped {cleanup_success} staging database(s)"
        flash_type = "success"
    elif cleanup_error:
        flash_message = f"Cleanup failed: {cleanup_error}"
        flash_type = "error"
    
    return templates.TemplateResponse(
        "features/admin/cleanup_preview.html",
        {
            "request": request,
            "user": user,
            "days": days,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "breadcrumbs": [
                {"label": "Dashboard", "url": "/web/dashboard"},
                {"label": "Admin", "url": "/web/admin/"},
                {"label": "Cleanup Staging", "url": None},
            ],
        },
    )


@router.get("/api/cleanup-candidates")
async def get_cleanup_candidates(
    request: Request,
    days: int = 7,
    page: int = 1,
    pageSize: int = 50,
    sortColumn: Optional[str] = None,
    sortDirection: str = "asc",
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get paginated list of staging databases to cleanup.
    
    Supports LazyTable params: page, pageSize, sortColumn, sortDirection, filter_*
    """
    if not hasattr(state.job_repo, "get_cleanup_candidates"):
        return {"rows": [], "totalCount": 0, "filteredCount": 0}
    
    # Get all candidates (we'll filter/sort in memory)
    result = state.job_repo.get_cleanup_candidates(
        retention_days=days,
        offset=0,
        limit=10000,  # Get all for filtering
    )
    
    rows = result.get("rows", [])
    total_count = len(rows)
    
    # Extract filter params from query string
    text_filters = {}  # column -> [values]
    date_after = {}    # column -> ISO date string
    date_before = {}   # column -> ISO date string
    date_columns = ["completed_at"]
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
            # Check for date range suffixes
            if col_key.endswith("_after"):
                base_col = col_key[:-6]
                if base_col in date_columns:
                    date_after[base_col] = value
                    continue
            if col_key.endswith("_before"):
                base_col = col_key[:-7]
                if base_col in date_columns:
                    date_before[base_col] = value
                    continue
            
            # Regular filter (could be multi-value comma-separated)
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]
    
    # Apply filters
    if text_filters or date_after or date_before:
        from datetime import datetime
        filtered_rows = []
        for row in rows:
            match = True
            
            # Check text filters (any of the values match)
            for col_key, filter_vals in text_filters.items():
                cell_val = str(row.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            
            # Check date after filters
            if match:
                for col_key, after_val in date_after.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(after_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt < cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            # Check date before filters
            if match:
                for col_key, before_val in date_before.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(before_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt > cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            if match:
                filtered_rows.append(row)
        rows = filtered_rows
    
    filtered_count = len(rows)
    
    # Apply sorting
    if sortColumn and sortColumn in ["database_name", "target", "dbhost", "user_code", "job_status", "completed_at"]:
        reverse = sortDirection.lower() == "desc"
        rows = sorted(rows, key=lambda r: (r.get(sortColumn) is None, r.get(sortColumn, "")), reverse=reverse)
    
    # Apply pagination (LazyTable sends 0-indexed page)
    offset = page * pageSize
    paginated_rows = rows[offset:offset + pageSize]
    
    return {
        "rows": paginated_rows,
        "totalCount": total_count,
        "filteredCount": filtered_count,
    }


@router.get("/api/cleanup-candidates/distinct")
async def get_cleanup_distinct_values(
    column: str,
    days: int = 7,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> list:
    """Get distinct values for filter dropdowns."""
    if not hasattr(state.job_repo, "get_cleanup_candidates"):
        return []
    result = state.job_repo.get_cleanup_candidates(retention_days=days, offset=0, limit=10000)
    rows = result.get("rows", [])
    values = set()
    for row in rows:
        val = row.get(column)
        if val is not None:
            values.add(str(val))
    return sorted(values)


@router.post("/cleanup-staging/execute")
async def cleanup_staging_execute(
    request: Request,
    days: int = Form(7),
    include_ids: str = Form(""),  # Comma-separated database names to drop
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute cleanup-staging on specific databases."""
    from pulldb.infra.factory import is_simulation_mode
    
    include_list = [x.strip() for x in include_ids.split(",") if x.strip()]
    
    if not include_list:
        return RedirectResponse(
            url="/web/admin/cleanup-staging/preview?cleanup_error=No+databases+selected",
            status_code=303,
        )
    
    try:
        if is_simulation_mode():
            # Use mock method directly
            if hasattr(state.job_repo, "cleanup_staging_by_names"):
                result = state.job_repo.cleanup_staging_by_names(database_names=include_list)
                dropped = result.get("dropped_count", 0)
                skipped = result.get("skipped_count", 0)
            elif hasattr(state.job_repo, "drop_staging_databases_by_names"):
                result = state.job_repo.drop_staging_databases_by_names(database_names=include_list)
                dropped = result.get("dropped_count", 0)
                skipped = result.get("skipped_count", 0)
            else:
                # Fallback for dev mode
                import logging
                logging.info(f"Would drop staging databases: {include_list}")
                dropped = len(include_list)
                skipped = 0
        else:
            # Use worker cleanup function for real database access
            from pulldb.worker.cleanup import cleanup_specific_databases
            cleanup_result = cleanup_specific_databases(
                database_names=include_list,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            dropped = cleanup_result.databases_dropped
            skipped = cleanup_result.databases_skipped
        
        total = len(include_list)
        return RedirectResponse(
            url=f"/web/admin/cleanup-staging/preview?cleanup_success={dropped}&cleanup_total={total}&cleanup_skipped={skipped}",
            status_code=303,
        )
    except Exception as e:
        import logging
        logging.exception("Failed to cleanup staging databases")
        error_msg = str(e).replace(" ", "+")[:100]  # Truncate for URL safety
        return RedirectResponse(
            url=f"/web/admin/cleanup-staging/preview?cleanup_error={error_msg}",
            status_code=303,
        )


# Legacy endpoint for backward compatibility
@router.post("/cleanup-staging")
async def cleanup_staging(
    days: int = Form(7),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Cleanup staging databases (legacy - redirects to preview)."""
    return RedirectResponse(url=f"/web/admin/cleanup-staging/preview?days={days}", status_code=303)


@router.get("/orphans/preview", response_class=HTMLResponse)
async def orphan_preview_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    orphan_success: int | None = None,
    orphan_error: str | None = None,
) -> HTMLResponse:
    """Render the orphan database deletion preview page."""
    flash_message = None
    flash_type = None
    if orphan_success is not None:
        flash_message = f"Successfully deleted {orphan_success} orphan database(s)"
        flash_type = "success"
    elif orphan_error:
        flash_message = f"Orphan deletion failed: {orphan_error}"
        flash_type = "error"

    return templates.TemplateResponse(
        "features/admin/orphan_preview.html",
        {
            "request": request,
            "user": user,
            "flash_message": flash_message,
            "flash_type": flash_type,
        },
    )


@router.get("/api/orphan-candidates")
async def api_orphan_candidates(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    pageIndex: int = 0,
    pageSize: int = 50,
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict:
    """Get paginated orphan candidates for LazyTable.
    
    Returns all orphans from all hosts in a flat list with dbhost included.
    Supports multi-select filters (filter_<column>) and date range (filter_<column>_after/before).
    """
    from pulldb.worker.cleanup import detect_orphaned_databases
    from datetime import datetime

    # Collect all orphans from all hosts
    all_orphans = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            # Skip hosts with connection errors
            if isinstance(result, str):
                continue
            for orphan in result.orphans:
                all_orphans.append({
                    "database_name": orphan.database_name,
                    "dbhost": orphan.dbhost,
                    "target_name": orphan.target_name,
                    "job_id_prefix": orphan.job_id_prefix,
                    "discovered_at": orphan.discovered_at.isoformat() if orphan.discovered_at else None,
                    "size_mb": orphan.size_mb,
                })

    total_count = len(all_orphans)

    # Extract filter params from query string
    text_filters: dict[str, list[str]] = {}  # column -> [values]
    date_after: dict[str, str] = {}    # column -> ISO date string
    date_before: dict[str, str] = {}   # column -> ISO date string
    date_columns = ["discovered_at"]
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
            # Check for date range suffixes
            if col_key.endswith("_after"):
                base_col = col_key[:-6]
                if base_col in date_columns:
                    date_after[base_col] = value
                    continue
            if col_key.endswith("_before"):
                base_col = col_key[:-7]
                if base_col in date_columns:
                    date_before[base_col] = value
                    continue
            
            # Regular filter (could be multi-value comma-separated)
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]

    # Apply filters
    if text_filters or date_after or date_before:
        filtered_orphans = []
        for orphan in all_orphans:
            match = True
            
            # Check text filters (any of the values match)
            for col_key, filter_vals in text_filters.items():
                cell_val = str(orphan.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            
            # Check date after filters
            if match:
                for col_key, after_val in date_after.items():
                    cell_val = orphan.get(col_key)
                    if cell_val:
                        try:
                            cell_date = datetime.fromisoformat(cell_val.replace('Z', '+00:00'))
                            after_date = datetime.fromisoformat(after_val)
                            if cell_date.date() < after_date.date():
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            # Check date before filters
            if match:
                for col_key, before_val in date_before.items():
                    cell_val = orphan.get(col_key)
                    if cell_val:
                        try:
                            cell_date = datetime.fromisoformat(cell_val.replace('Z', '+00:00'))
                            before_date = datetime.fromisoformat(before_val)
                            if cell_date.date() > before_date.date():
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            if match:
                filtered_orphans.append(orphan)
        
        all_orphans = filtered_orphans

    filtered_count = len(all_orphans)

    # Apply sorting
    if sortColumn and sortColumn in ("database_name", "dbhost", "target_name", "discovered_at", "size_mb"):
        reverse = sortDirection == "desc"
        all_orphans.sort(
            key=lambda o: (o.get(sortColumn) is None, o.get(sortColumn) or ""),
            reverse=reverse
        )
    
    # Apply pagination
    start = pageIndex * pageSize
    end = start + pageSize
    page_orphans = all_orphans[start:end]

    return {
        "rows": page_orphans,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "pageIndex": pageIndex,
        "pageSize": pageSize,
    }


@router.get("/api/orphan-candidates/distinct")
async def get_orphan_distinct_values(
    request: Request,
    column: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> list:
    """Get distinct values for filter dropdowns.
    
    Applies current filters (excluding the requested column) so that
    filter options update based on other active filters.
    """
    from pulldb.worker.cleanup import detect_orphaned_databases
    
    all_orphans = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            if isinstance(result, str):
                continue
            for orphan in result.orphans:
                all_orphans.append({
                    "database_name": orphan.database_name,
                    "dbhost": orphan.dbhost,
                    "target_name": orphan.target_name,
                })
    
    # Extract filter params from query string (excluding the column we're getting distinct values for)
    text_filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            # Skip date range suffixes and the column being queried
            if col_key.endswith("_after") or col_key.endswith("_before"):
                continue
            if col_key == column:
                continue
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]
    
    # Apply filters to narrow down distinct values
    if text_filters:
        filtered_orphans = []
        for orphan in all_orphans:
            match = True
            for col_key, filter_vals in text_filters.items():
                cell_val = str(orphan.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            if match:
                filtered_orphans.append(orphan)
        all_orphans = filtered_orphans
    
    values = set()
    for orphan in all_orphans:
        val = orphan.get(column)
        if val is not None:
            values.add(str(val))
    return sorted(values)


@router.post("/orphans/execute")
async def execute_orphan_deletion(
    selected_orphans: str = Form(""),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute deletion of selected orphan databases.
    
    selected_orphans is a comma-separated list of "dbhost|database_name" keys.
    Groups by dbhost for efficient credential lookup and deletion.
    """
    from pulldb.worker.cleanup import admin_delete_orphan_databases

    if not selected_orphans.strip():
        return RedirectResponse(
            url="/web/admin/orphans/preview?orphan_error=No+orphans+selected",
            status_code=303,
        )

    # Parse selected keys and group by dbhost
    by_host: dict[str, list[str]] = {}
    for key in selected_orphans.split(","):
        key = key.strip()
        if "|" not in key:
            continue
        dbhost, database_name = key.split("|", 1)
        if dbhost not in by_host:
            by_host[dbhost] = []
        by_host[dbhost].append(database_name)

    if not by_host:
        return RedirectResponse(
            url="/web/admin/orphans/preview?orphan_error=Invalid+selection+format",
            status_code=303,
        )

    # Delete orphans grouped by host
    total_deleted = 0
    errors = []
    
    try:
        for dbhost, database_names in by_host.items():
            if hasattr(state, "host_repo") and state.host_repo:
                results = admin_delete_orphan_databases(
                    dbhost=dbhost,
                    database_names=database_names,
                    host_repo=state.host_repo,
                    admin_user=user.username,
                )
                # results is dict[str, bool] mapping database_name to success
                for db_name, success in results.items():
                    if success:
                        total_deleted += 1
                    else:
                        errors.append(f"{dbhost}:{db_name}")

        if errors:
            error_msg = f"Deleted+{total_deleted},+failed:+" + ",".join(errors[:3])
            if len(errors) > 3:
                error_msg += f"+and+{len(errors)-3}+more"
            return RedirectResponse(
                url=f"/web/admin/orphans/preview?orphan_error={error_msg}",
                status_code=303,
            )

        return RedirectResponse(
            url=f"/web/admin/orphans/preview?orphan_success={total_deleted}",
            status_code=303,
        )

    except Exception as e:
        error_msg = str(e).replace(" ", "+")[:100]
        return RedirectResponse(
            url=f"/web/admin/orphans/preview?orphan_error={error_msg}",
            status_code=303,
        )


@router.get("/orphans", response_class=HTMLResponse)
async def get_orphans(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Get orphan databases report."""
    from pulldb.worker.cleanup import detect_orphaned_databases, OrphanReport
    
    reports = []
    errors = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            # Handle error string return (connection failure)
            if isinstance(result, str):
                errors.append({"host": host.hostname, "message": result})
                continue
            # Handle successful OrphanReport
            orphan_report: OrphanReport = result
            if orphan_report.orphans:
                reports.append({
                    "host": host.hostname,
                    "orphans": orphan_report.orphans
                })

    return templates.TemplateResponse(
        "features/admin/partials/orphans.html",
        {"request": request, "reports": reports, "errors": errors}
    )


@router.post("/orphans/delete")
async def delete_orphans(
    dbhost: str = Form(...),
    database_name: str = Form(...),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Delete an orphan database."""
    from pulldb.worker.cleanup import admin_delete_orphan_databases
    
    if hasattr(state, "host_repo") and state.host_repo:
        admin_delete_orphan_databases(
            dbhost=dbhost,
            database_names=[database_name],
            host_repo=state.host_repo,
            admin_user=user.username,
        )
    
    return RedirectResponse(url="/web/admin/", status_code=303)
