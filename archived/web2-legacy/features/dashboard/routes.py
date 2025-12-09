"""Dashboard routes for Web2 interface."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import User
from pulldb.web.dependencies import get_api_state, require_login

router = APIRouter(prefix="/web/dashboard", tags=["web-dashboard"])
templates = Jinja2Templates(directory="pulldb/web/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the dashboard page."""
    stats = {
        "active_jobs": 0,
        "completed_today": 0,
        "failed_jobs": 0,
    }

    if hasattr(state, "job_repo") and state.job_repo:
        stats["active_jobs"] = len(state.job_repo.active_jobs)
        
        # Simple counting for now
        for job in state.job_repo.history_jobs:
            status = str(job.status).lower()
            if status == "failed":
                stats["failed_jobs"] += 1
            elif status == "complete" or status == "completed":
                # In a real app, we'd filter by date here
                stats["completed_today"] += 1

    return templates.TemplateResponse(
        "features/dashboard/dashboard.html",
        {
            "request": request,
            "user": user,
            "active_nav": "dashboard",
            "stats": stats,
        },
    )
