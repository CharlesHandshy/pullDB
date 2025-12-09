"""Manager routes for Web2 interface."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
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

    # Get recent jobs for context
    all_jobs = []
    if hasattr(state.job_repo, "get_recent_jobs"):
        all_jobs = state.job_repo.get_recent_jobs(limit=200)

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
            "user": user,
            "managed_users": managed_users,
            "stats": stats,
        },
    )
