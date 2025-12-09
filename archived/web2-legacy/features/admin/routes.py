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
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """List all users."""
    users = []
    if hasattr(state.user_repo, "list_users"):
        users = state.user_repo.list_users()

    return templates.TemplateResponse(
        "features/admin/users.html",
        {"request": request, "users": users, "user": user},
    )


@router.post("/prune-logs")
async def prune_logs(
    days: int = Form(90),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Prune old logs."""
    if hasattr(state, "job_repo") and state.job_repo:
        state.job_repo.prune_job_events(retention_days=days)
    return RedirectResponse(url="/web/admin", status_code=303)


@router.post("/cleanup-staging")
async def cleanup_staging(
    days: int = Form(7),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Cleanup staging databases."""
    from pulldb.worker.cleanup import run_scheduled_cleanup
    
    if hasattr(state, "job_repo") and state.job_repo and hasattr(state, "host_repo"):
        run_scheduled_cleanup(
            job_repo=state.job_repo,
            host_repo=state.host_repo,
            retention_days=days,
            dry_run=False,
        )
    return RedirectResponse(url="/web/admin", status_code=303)


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
    
    return RedirectResponse(url="/web/admin", status_code=303)
