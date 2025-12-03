"""Job view routes for pullDB web UI.

HCA Feature Module: job_view
Handles: job detail, job profile, job events partial
Size: ~180 lines (HCA compliant)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from pulldb.web.dependencies import (
    AuthenticatedUser,
    get_api_state,
    templates,
)
from pulldb.web.exceptions import render_error_page

if TYPE_CHECKING:
    from pulldb.api.main import APIState

router = APIRouter(prefix="/web", tags=["web-jobs"])


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: str,
    user: AuthenticatedUser,
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display job details."""
    from pulldb.domain.permissions import can_cancel_job, can_view_job
    
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return render_error_page(
            request=request,
            user=user,
            status_code=404,
            title="Job Not Found",
            message=f"The job '{job_id}' could not be found.",
            suggestions=[
                "Check that the job ID is correct",
                "The job may have been deleted or expired",
                "Return to the dashboard to see your active jobs",
            ],
        )
    
    if not can_view_job(user, job.owner_user_id):
        return render_error_page(
            request=request,
            user=user,
            status_code=403,
            title="Access Denied",
            message="You don't have permission to view this job.",
            suggestions=[
                "You can only view jobs that you created",
                "Contact an administrator if you need access",
            ],
        )
    
    events = state.job_repo.get_job_events(job_id) if hasattr(state.job_repo, 'get_job_events') else []
    
    back_tab = None
    referer = request.headers.get("referer", "")
    if referer:
        parsed = urlparse(referer)
        query_params = parse_qs(parsed.query)
        if "tab" in query_params:
            back_tab = query_params["tab"][0]
    
    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "user": user,
            "job": job,
            "events": events or [],
            "can_cancel": can_cancel_job(user, job.owner_user_id),
            "now": datetime.now(UTC),
            "back_tab": back_tab,
        },
    )


@router.get("/partials/job-events/{job_id}", response_class=HTMLResponse)
async def partial_job_events(
    request: Request,
    job_id: str,
    user: AuthenticatedUser,
    state: "APIState" = Depends(get_api_state),
    since_id: int | None = None,
) -> Response:
    """Return job events partial for HTMX updates."""
    from pulldb.domain.permissions import can_view_job
    
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not can_view_job(user, job.owner_user_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    events = state.job_repo.get_job_events(job_id, since_id=since_id)
    
    return templates.TemplateResponse(
        request=request,
        name="partials/job_events.html",
        context={
            "events": events,
            "job": job,
        },
    )


@router.get("/jobs/{job_id}/profile", response_class=HTMLResponse)
async def job_profile_page(
    request: Request,
    job_id: str,
    user: AuthenticatedUser,
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Display job profile (timing analysis)."""
    from pulldb.domain.permissions import can_view_job
    
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return render_error_page(
            request=request,
            user=user,
            status_code=404,
            title="Job Not Found",
            message=f"The job '{job_id}' could not be found.",
        )
    
    if not can_view_job(user, job.owner_user_id):
        return render_error_page(
            request=request,
            user=user,
            status_code=403,
            title="Access Denied",
            message="You don't have permission to view this job profile.",
        )
    
    events = state.job_repo.get_job_events(job_id)
    profile = _build_job_profile(events)
    
    return templates.TemplateResponse(
        request=request,
        name="job_profile.html",
        context={
            "user": user,
            "job": job,
            "events": events,
            "profile": profile,
            "now": datetime.now(UTC),
        },
    )


def _build_job_profile(events: list) -> dict:
    """Build timing profile from job events."""
    phases = []
    total_duration = 0
    phase_starts = {}
    
    for event in events:
        msg = event.message.lower() if hasattr(event, "message") else ""
        
        if "starting" in msg or "began" in msg:
            phase_name = msg.replace("starting", "").replace("began", "").strip()
            phase_starts[phase_name] = event.created_at if hasattr(event, "created_at") else None
        elif "completed" in msg or "finished" in msg:
            phase_name = msg.replace("completed", "").replace("finished", "").strip()
            if phase_name in phase_starts and phase_starts[phase_name]:
                end_time = event.created_at if hasattr(event, "created_at") else None
                if end_time and phase_starts[phase_name]:
                    duration = (end_time - phase_starts[phase_name]).total_seconds()
                    phases.append({
                        "name": phase_name.title() or "Phase",
                        "duration": duration,
                        "formatted_duration": f"{int(duration)}s",
                    })
                    total_duration += duration
    
    for phase in phases:
        phase["percentage"] = (phase["duration"] / total_duration * 100) if total_duration > 0 else 0
    
    return {
        "phases": phases,
        "total_duration": total_duration,
        "formatted_total": f"{int(total_duration // 60)}m {int(total_duration % 60)}s" if total_duration else "N/A",
    }
