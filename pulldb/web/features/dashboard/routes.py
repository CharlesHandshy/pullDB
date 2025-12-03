"""Dashboard routes for pullDB web UI.

HCA Feature Module: dashboard
Handles: main dashboard, active jobs partial
Size: ~70 lines (HCA compliant)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse

from pulldb.web.dependencies import (
    get_api_state,
    templates,
    AuthenticatedUser,
)

if TYPE_CHECKING:
    from pulldb.api.main import APIState

router = APIRouter(prefix="/web", tags=["web-dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: AuthenticatedUser,
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display user dashboard with active jobs."""
    from pulldb.domain.permissions import can_view_all_jobs
    
    if can_view_all_jobs(user):
        active_jobs = state.job_repo.get_active_jobs()
        recent_jobs = state.job_repo.get_recent_jobs(limit=400)
    else:
        active_jobs = [
            j for j in state.job_repo.get_active_jobs()
            if j.owner_user_id == user.user_id
        ]
        recent_jobs = [
            j for j in state.job_repo.get_recent_jobs(limit=400)
            if j.owner_user_id == user.user_id
        ]
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "active_jobs": active_jobs,
            "recent_jobs": recent_jobs,
            "now": datetime.now(UTC),
        },
    )


@router.get("/partials/active-jobs", response_class=HTMLResponse)
async def partial_active_jobs(
    request: Request,
    user: AuthenticatedUser,
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Return active jobs partial for HTMX updates."""
    from pulldb.domain.permissions import can_view_all_jobs
    
    if can_view_all_jobs(user):
        active_jobs = state.job_repo.get_active_jobs()
    else:
        active_jobs = [
            j for j in state.job_repo.get_active_jobs()
            if j.owner_user_id == user.user_id
        ]
    
    return templates.TemplateResponse(
        request=request,
        name="partials/active_jobs.html",
        context={
            "active_jobs": active_jobs,
            "now": datetime.now(UTC),
        },
    )
