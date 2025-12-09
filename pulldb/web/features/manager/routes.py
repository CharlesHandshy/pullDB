"""Manager routes for Web2 interface."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import JobStatus, User
from pulldb.web.dependencies import get_api_state, require_manager_or_above

router = APIRouter(prefix="/web/manager", tags=["web-manager"])
templates = Jinja2Templates(directory="pulldb/web/templates")


@router.get("/", response_class=HTMLResponse)
async def manager_page(
    request: Request,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> HTMLResponse:
    """Render the manager page."""
    # Get users managed by this manager
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)

    # Get active jobs for context
    all_jobs = []
    if hasattr(state.job_repo, "active_jobs"):
        all_jobs = list(state.job_repo.active_jobs)
    elif hasattr(state.job_repo, "get_recent_jobs"):
        all_jobs = state.job_repo.get_recent_jobs(limit=200)

    # Compute per-user active job counts
    user_active_jobs = {}
    for mu in managed_users:
        user_active_jobs[mu.user_id] = len([
            j for j in all_jobs
            if j.owner_user_id == mu.user_id
            and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        ])

    # Stats
    stats = {
        "managed_users": len(managed_users),
        "active_users": len([u for u in managed_users if not u.disabled_at]),
        "disabled_users": len([u for u in managed_users if u.disabled_at]),
        "active_jobs": len(
            [
                j
                for j in all_jobs
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            ]
        ),
        "my_team_active_jobs": len(
            [
                j
                for j in all_jobs
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
                and any(u.user_id == j.owner_user_id for u in managed_users)
            ]
        ),
    }

    return templates.TemplateResponse(
        "features/manager/manager.html",
        {
            "request": request,
            "breadcrumbs": [
                {"label": "Dashboard", "url": "/web/dashboard"},
                {"label": "Manager", "url": None},
            ],
            "user": user,
            "managed_users": managed_users,
            "user_active_jobs": user_active_jobs,
            "stats": stats,
        },
    )


@router.post("/my-team/{user_id}/reset-password")
async def reset_team_member_password(
    user_id: str,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> RedirectResponse:
    """Force password reset for a managed user."""
    # Verify user is managed by this manager
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)

    managed_user_ids = {u.user_id for u in managed_users}
    if user_id not in managed_user_ids:
        # Not authorized to manage this user - redirect back
        return RedirectResponse(url="/web/manager/", status_code=303)

    # Mark password reset required
    if hasattr(state.auth_repo, "mark_password_reset"):
        state.auth_repo.mark_password_reset(user_id)

    return RedirectResponse(url="/web/manager/", status_code=303)


@router.post("/my-team/{user_id}/clear-password-reset")
async def clear_team_member_password_reset(
    user_id: str,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> RedirectResponse:
    """Clear password reset requirement for a managed user."""
    # Verify user is managed by this manager
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)

    managed_user_ids = {u.user_id for u in managed_users}
    if user_id not in managed_user_ids:
        return RedirectResponse(url="/web/manager/", status_code=303)

    # Clear password reset requirement
    if hasattr(state.auth_repo, "clear_password_reset"):
        state.auth_repo.clear_password_reset(user_id)

    return RedirectResponse(url="/web/manager/", status_code=303)


@router.post("/my-team/{user_id}/enable")
async def enable_team_member(
    user_id: str,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> RedirectResponse:
    """Enable a disabled managed user."""
    # Verify user is managed by this manager
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)

    managed_user_ids = {u.user_id for u in managed_users}
    if user_id not in managed_user_ids:
        return RedirectResponse(url="/web/manager/", status_code=303)

    # Enable the user
    if hasattr(state.user_repo, "enable_user"):
        state.user_repo.enable_user(user_id)

    return RedirectResponse(url="/web/manager/", status_code=303)


@router.post("/my-team/{user_id}/disable")
async def disable_team_member(
    user_id: str,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> RedirectResponse:
    """Disable a managed user."""
    # Verify user is managed by this manager
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)

    managed_user_ids = {u.user_id for u in managed_users}
    if user_id not in managed_user_ids:
        return RedirectResponse(url="/web/manager/", status_code=303)

    # Disable the user
    if hasattr(state.user_repo, "disable_user"):
        state.user_repo.disable_user(user_id)

    return RedirectResponse(url="/web/manager/", status_code=303)
