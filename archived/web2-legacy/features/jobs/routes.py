"""Jobs routes for Web2 interface."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import User, JobStatus
from pulldb.web.dependencies import get_api_state, require_login
from pulldb.infra.metrics import emit_event, MetricLabels, emit_counter

router = APIRouter(prefix="/web/jobs", tags=["web-jobs"])
templates = Jinja2Templates(directory="pulldb/web/templates")


@router.get("/", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    page: int = 1,
    q: str | None = None,
    status: str | None = None,
    host: str | None = None,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the jobs page."""
    page_size = 20
    offset = (page - 1) * page_size
    jobs = []
    hosts = []
    
    # Get hosts for dropdown
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()

    if hasattr(state, "job_repo") and state.job_repo:
        if q and len(q) >= 4:
            # Search mode
            exact = len(q) >= 5
            jobs = state.job_repo.search_jobs(q, limit=page_size, exact=exact)
            
            # In-memory filtering for search results
            if status:
                jobs = [j for j in jobs if j.status.value == status]
            if host:
                jobs = [j for j in jobs if j.dbhost == host]
                
        elif status or host:
            # Filter mode using list_jobs
            # list_jobs(limit, active_only, user_filter, dbhost, status_filter)
            # Note: list_jobs might not support offset in all implementations, but let's check
            # The implementation I saw earlier didn't have offset in list_jobs signature!
            # It was: list_jobs(limit=20, active_only=False, user_filter=None, dbhost=None, status_filter=None)
            # So pagination might be broken for filtered views if I use list_jobs.
            # But get_recent_jobs supports offset.
            # get_recent_jobs(limit, offset, statuses)
            
            if host:
                # If host is filtered, we must use list_jobs (no offset support) or get_job_history (no active jobs?)
                # Let's use list_jobs and accept no pagination for now, or implement manual pagination
                # But list_jobs returns mixed active/history? Yes.
                
                jobs = state.job_repo.list_jobs(
                    limit=page_size,
                    dbhost=host,
                    status_filter=status
                )
            else:
                # Only status filter? get_recent_jobs supports statuses list
                if status:
                    try:
                        jobs = state.job_repo.get_recent_jobs(
                            limit=page_size, 
                            offset=offset, 
                            statuses=[status]
                        )
                    except TypeError:
                        # Fallback if signature doesn't match
                        jobs = state.job_repo.get_recent_jobs(limit=page_size)
                else:
                    # Should not happen due to elif condition
                    jobs = state.job_repo.get_recent_jobs(limit=page_size, offset=offset)

        else:
            # List mode (default)
            try:
                jobs = state.job_repo.get_recent_jobs(limit=page_size, offset=offset)
            except TypeError:
                jobs = state.job_repo.get_recent_jobs(limit=page_size)

    return templates.TemplateResponse(
        "features/jobs/jobs.html",
        {
            "request": request,
            "jobs": jobs,
            "user": user,
            "active_nav": "jobs",
            "page": page,
            "has_next": len(jobs) == page_size,
            "has_prev": page > 1,
            "q": q,
            "status": status,
            "host": host,
            "hosts": hosts,
        },
    )


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_details(
    request: Request,
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the job details page."""
    job = None
    logs = []
    profile = None
    
    if hasattr(state, "job_repo") and state.job_repo:
        job = state.job_repo.get_job_by_id(job_id)
        if job:
            logs = state.job_repo.get_job_events(job_id)
            
            # Try to get profile if job is complete
            if job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
                from pulldb.worker.profiling import parse_profile_from_event
                for event in logs:
                    if event.event_type == "restore_profile" and event.detail:
                        profile = parse_profile_from_event(event.detail)
                        break
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return templates.TemplateResponse(
        "features/jobs/details.html",
        {
            "request": request,
            "job": job,
            "logs": logs,
            "profile": profile,
            "user": user,
            "active_nav": "jobs",
        },
    )


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> RedirectResponse:
    """Cancel a running job."""
    if hasattr(state, "job_repo") and state.job_repo:
        job = state.job_repo.get_job_by_id(job_id)
        if job and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            # Request cancellation
            was_requested = state.job_repo.request_cancellation(job_id)
            
            if was_requested:
                state.job_repo.append_job_event(
                    job_id=job_id,
                    event_type="cancel_requested",
                    detail=f"User {user.username} requested job cancellation",
                )
                
                if job.status == JobStatus.QUEUED:
                    state.job_repo.mark_job_canceled(job_id, "Canceled before execution started")
    
    return RedirectResponse(url=f"/web/jobs/{job_id}", status_code=303)
