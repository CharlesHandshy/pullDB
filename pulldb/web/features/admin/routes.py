"""Admin routes for Web2 interface."""

from typing import Any

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
) -> HTMLResponse:
    """Render the admin page."""
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
        "enabled_hosts": len([h for h in hosts if not getattr(h, "disabled", False)]),
        "active_jobs": len(active_jobs),
        "running_jobs": len([j for j in active_jobs if j.status == JobStatus.RUNNING]),
        "pending_jobs": len([j for j in active_jobs if j.status == JobStatus.QUEUED]),
    }

    return templates.TemplateResponse(
        "features/admin/admin.html",
        {"request": request, "stats": stats, "user": user},
    )


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
    users = []
    if hasattr(state.user_repo, "list_users"):
        users = state.user_repo.list_users()
    
    # Apply search filter
    if q:
        q_lower = q.lower()
        users = [u for u in users if 
                 q_lower in u.username.lower() or 
                 q_lower in (u.user_code or "").lower() or
                 q_lower in u.role.value.lower()]
    
    # Apply role filter
    if role:
        users = [u for u in users if u.role.value.lower() == role.lower()]
    
    # Apply status filter
    if status == "active":
        users = [u for u in users if not u.disabled_at]
    elif status == "disabled":
        users = [u for u in users if u.disabled_at]

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
        {"request": request, "user": user, "days": days},
    )


@router.get("/api/prune-candidates")
async def get_prune_candidates(
    days: int = 90,
    offset: int = 0,
    limit: int = 50,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get paginated list of jobs with events to prune."""
    if hasattr(state.job_repo, "get_prune_candidates"):
        return state.job_repo.get_prune_candidates(
            retention_days=days,
            offset=offset,
            limit=limit,
        )
    return {"rows": [], "totalCount": 0, "totalEvents": 0}


@router.post("/prune-logs/execute")
async def prune_logs_execute(
    request: Request,
    days: int = Form(90),
    exclude_ids: str = Form(""),  # Comma-separated job IDs to exclude
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute prune-logs with optional exclusions."""
    exclude_list = [x.strip() for x in exclude_ids.split(",") if x.strip()]
    
    if hasattr(state.job_repo, "prune_job_events_excluding"):
        state.job_repo.prune_job_events_excluding(
            retention_days=days,
            exclude_job_ids=exclude_list,
        )
    elif hasattr(state.job_repo, "prune_job_events"):
        state.job_repo.prune_job_events(retention_days=days)
    
    return RedirectResponse(url="/web/admin/", status_code=303)


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
) -> HTMLResponse:
    """Preview what cleanup-staging will delete."""
    return templates.TemplateResponse(
        "features/admin/cleanup_preview.html",
        {"request": request, "user": user, "days": days},
    )


@router.get("/api/cleanup-candidates")
async def get_cleanup_candidates(
    days: int = 7,
    offset: int = 0,
    limit: int = 50,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get paginated list of staging databases to cleanup."""
    if hasattr(state.job_repo, "get_cleanup_candidates"):
        return state.job_repo.get_cleanup_candidates(
            retention_days=days,
            offset=offset,
            limit=limit,
        )
    return {"rows": [], "totalCount": 0}


@router.post("/cleanup-staging/execute")
async def cleanup_staging_execute(
    request: Request,
    days: int = Form(7),
    exclude_ids: str = Form(""),  # Comma-separated database names to exclude
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute cleanup-staging with optional exclusions."""
    from pulldb.worker.cleanup import run_scheduled_cleanup
    
    exclude_list = [x.strip() for x in exclude_ids.split(",") if x.strip()]
    
    if hasattr(state, "job_repo") and state.job_repo and hasattr(state, "host_repo"):
        # Note: run_scheduled_cleanup doesn't support exclusions yet
        # For now, run without exclusions
        run_scheduled_cleanup(
            job_repo=state.job_repo,
            host_repo=state.host_repo,
            retention_days=days,
            dry_run=False,
        )
    return RedirectResponse(url="/web/admin/", status_code=303)


# Legacy endpoint for backward compatibility
@router.post("/cleanup-staging")
async def cleanup_staging(
    days: int = Form(7),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Cleanup staging databases (legacy - redirects to preview)."""
    return RedirectResponse(url=f"/web/admin/cleanup-staging/preview?days={days}", status_code=303)


@router.get("/orphans", response_class=HTMLResponse)
async def get_orphans(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Get orphan databases report."""
    from pulldb.worker.cleanup import detect_orphaned_databases
    
    reports = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            orphan_report = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            if orphan_report.orphans:
                reports.append({
                    "host": host.hostname,
                    "orphans": orphan_report.orphans
                })

    return templates.TemplateResponse(
        "features/admin/partials/orphans.html",
        {"request": request, "reports": reports}
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
