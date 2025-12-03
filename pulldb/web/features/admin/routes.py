"""Admin routes for pullDB web UI.

HCA Feature Module: admin
Handles: admin pages for settings, users, hosts, jobs, cleanup
Size: ~320 lines (HCA compliant - single cohesive admin feature)

Note: Logo management is in a separate admin_logo.py module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from pulldb.domain.models import JobStatus
from pulldb.web.dependencies import (
    get_api_state,
    templates,
    require_admin,
)
from pulldb.web.exceptions import render_error_page

if TYPE_CHECKING:
    from pulldb.api.main import APIState
    from pulldb.auth.models import User

router = APIRouter(prefix="/web/admin", tags=["web-admin"])


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display settings management."""
    settings = [
        {
            "key": "myloader_threads",
            "value": "4",
            "default": "4",
            "description": "Number of myloader threads",
        },
        {
            "key": "myloader_compress_protocol",
            "value": "true",
            "default": "true",
            "description": "Enable compression",
        },
        {
            "key": "work_directory",
            "value": "/tmp/pulldb",
            "default": "/tmp/pulldb",
            "description": "Work directory path",
        },
        {
            "key": "customers_after_sql_dir",
            "value": "/etc/pulldb/after_sql",
            "default": "",
            "description": "Custom SQL directory",
        },
        {
            "key": "backup_retention_days",
            "value": "30",
            "default": "30",
            "description": "Backup retention period",
        },
    ]

    return templates.TemplateResponse(
        request=request,
        name="admin/settings.html",
        context={"user": user, "settings": settings},
    )


@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display user management."""
    repo = state.user_repo
    users = repo.list_users() if hasattr(repo, "list_users") else []

    stats = {
        "total": len(users),
        "admins": len([u for u in users if u.is_admin]),
        "active": len([u for u in users if not u.disabled_at]),
        "disabled": len([u for u in users if u.disabled_at]),
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={"user": user, "users": users, "stats": stats},
    )


@router.get("/users/{username}", response_class=HTMLResponse)
async def admin_user_detail_page(
    request: Request,
    username: str,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display user detail."""
    target_user = state.user_repo.get_user_by_username(username)
    if not target_user:
        return render_error_page(
            request=request,
            templates=templates,
            user=user,
            status_code=404,
            title="User Not Found",
            message=f"The user '{username}' could not be found.",
            suggestions=[
                "Check that the username is spelled correctly",
                "The user may have been deleted",
                "Go back to the users list to find the correct user",
            ],
        )

    all_jobs = state.job_repo.get_recent_jobs(limit=100)
    user_jobs = [j for j in all_jobs if j.owner_user_id == target_user.user_id][:10]

    stats = {
        "active_jobs": len([j for j in user_jobs if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)]),
        "total_jobs": len(user_jobs),
        "completed_jobs": len([j for j in user_jobs if j.status == JobStatus.COMPLETE]),
        "failed_jobs": len([j for j in user_jobs if j.status == JobStatus.FAILED]),
        "cancelled_jobs": len([j for j in user_jobs if j.status == JobStatus.CANCELED]),
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/user_detail.html",
        context={
            "user": target_user,
            "current_user": user,
            "jobs": user_jobs,
            "stats": stats,
        },
    )


@router.post("/users/{username}/enable")
async def admin_enable_user(
    request: Request,
    username: str,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Enable a user account."""
    target_user = state.user_repo.get_user_by_username(username)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if hasattr(state.user_repo, "enable_user"):
        state.user_repo.enable_user(target_user.user_id)

    return RedirectResponse(
        url=f"/web/admin/users/{username}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{username}/disable")
async def admin_disable_user(
    request: Request,
    username: str,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Disable a user account."""
    target_user = state.user_repo.get_user_by_username(username)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if hasattr(state.user_repo, "disable_user"):
        state.user_repo.disable_user(target_user.user_id)

    return RedirectResponse(
        url=f"/web/admin/users/{username}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/hosts", response_class=HTMLResponse)
async def admin_hosts_page(
    request: Request,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display host management."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        if hasattr(state.host_repo, "list_hosts"):
            hosts = state.host_repo.list_hosts()

    stats = {
        "total": len(hosts),
        "enabled": len([h for h in hosts if not getattr(h, "disabled", False)]),
        "disabled": len([h for h in hosts if getattr(h, "disabled", False)]),
        "active_restores": 0,
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/hosts.html",
        context={"user": user, "hosts": hosts, "stats": stats},
    )


@router.get("/jobs", response_class=HTMLResponse)
async def admin_jobs_page(
    request: Request,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
    page: int = 1,
) -> Response:
    """Display all jobs."""
    limit = 50
    active_jobs = []
    if hasattr(state.job_repo, "get_active_jobs"):
        active_jobs = state.job_repo.get_active_jobs()
    recent_jobs = state.job_repo.get_recent_jobs(limit=limit * page)
    jobs = list(active_jobs) + list(recent_jobs)

    users = []
    if hasattr(state.user_repo, "list_users"):
        users = state.user_repo.list_users()
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        if hasattr(state.host_repo, "list_hosts"):
            hosts = state.host_repo.list_hosts()

    today = datetime.now(UTC).date()
    today_jobs = [j for j in jobs if j.created_at and j.created_at.date() == today]

    stats = {
        "running": len([j for j in jobs if j.status == JobStatus.RUNNING]),
        "pending": len([j for j in jobs if j.status == JobStatus.QUEUED]),
        "completed_today": len([j for j in today_jobs if j.status == JobStatus.COMPLETE]),
        "failed_today": len([j for j in today_jobs if j.status == JobStatus.FAILED]),
    }

    total_jobs = len(jobs)
    total_pages = (total_jobs // limit) + (1 if total_jobs % limit else 0)
    pagination = {
        "page": page,
        "per_page": limit,
        "total": total_jobs,
        "total_pages": total_pages if total_jobs else 1,
        "has_prev": page > 1,
        "has_next": total_jobs > limit * page,
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/jobs.html",
        context={
            "user": user,
            "jobs": jobs[(page - 1) * limit : page * limit],
            "users": users,
            "hosts": hosts,
            "stats": stats,
            "pagination": pagination,
            "now": datetime.now(UTC),
        },
    )


@router.post("/jobs/{job_id}/cancel")
async def admin_cancel_job(
    request: Request,
    job_id: str,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Cancel a job (admin override)."""
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if hasattr(state.job_repo, "cancel_job"):
        state.job_repo.cancel_job(job_id)

    return RedirectResponse(
        url="/web/admin/jobs",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/cleanup", response_class=HTMLResponse)
async def admin_cleanup_page(
    request: Request,
    user: "User" = Depends(require_admin),
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display cleanup page."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        if hasattr(state.host_repo, "list_hosts"):
            hosts = state.host_repo.list_hosts()

    return templates.TemplateResponse(
        request=request,
        name="admin/cleanup.html",
        context={
            "user": user,
            "hosts": hosts,
            "last_cleanup": None,
        },
    )
