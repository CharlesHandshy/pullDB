"""Jobs routes for Web2 interface."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import JobStatus, User, UserRole
from pulldb.web.dependencies import get_api_state, require_login


router = APIRouter(prefix="/web/jobs", tags=["web-jobs"])
templates = Jinja2Templates(directory="pulldb/web/templates")


@router.get("/", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    page: int = 1,
    view: str = "active",
    q: str | None = None,
    status: str | None = None,
    host: str | None = None,
    days: int = 30,
    user_code: str | None = None,
    target: str | None = None,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the jobs page with Active/History views."""
    page_size = 20
    offset = (page - 1) * page_size
    jobs = []
    hosts = []

    # Get hosts for dropdown
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()

    if hasattr(state, "job_repo") and state.job_repo:
        if view == "history":
            # History view - use get_job_history with filters
            if hasattr(state.job_repo, "get_job_history"):
                jobs = state.job_repo.get_job_history(
                    limit=page_size,
                    retention_days=days,
                    user_code=user_code if user_code else None,
                    target=target if target else None,
                    dbhost=host if host else None,
                    status=status if status else None,
                )
            else:
                # Fallback for mock
                jobs = getattr(state.job_repo, "history_jobs", [])[:page_size]

                # Apply in-memory filters for mock
                if status:
                    jobs = [
                        j
                        for j in jobs
                        if str(j.status).lower() == status.lower()
                        or j.status.value == status
                    ]
                if host:
                    jobs = [j for j in jobs if j.dbhost == host]
                if user_code:
                    jobs = [
                        j
                        for j in jobs
                        if getattr(j, "owner_user_code", None) == user_code
                    ]
        # Active view
        elif q and len(q) >= 4:
            # Search mode
            exact = len(q) >= 5
            jobs = state.job_repo.search_jobs(q, limit=page_size, exact=exact)
            # Filter to active only
            jobs = [
                j for j in jobs if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            ]
        elif hasattr(state.job_repo, "get_active_jobs"):
            jobs = state.job_repo.get_active_jobs()

            # Apply filters
            if status:
                jobs = [j for j in jobs if j.status.value == status]
            if host:
                jobs = [j for j in jobs if j.dbhost == host]
        else:
            # Fallback for mock
            jobs = getattr(state.job_repo, "active_jobs", [])

    return templates.TemplateResponse(
        "features/jobs/jobs.html",
        {
            "request": request,
            "breadcrumbs": [
                {"label": "Dashboard", "url": "/web/dashboard"},
                {"label": "Jobs", "url": None},
            ],
            "jobs": jobs,
            "user": user,
            "active_nav": "jobs",
            "page": page,
            "view": view,
            "has_next": len(jobs) == page_size,
            "has_prev": page > 1,
            "q": q,
            "status": status,
            "host": host,
            "hosts": hosts,
            "days": days,
            "user_code": user_code,
            "target_filter": target,
            # Role-based filter defaults
            "managed_user_codes": _get_managed_user_codes(state, user),
            "three_days_ago_iso": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
        },
    )


def _get_managed_user_codes(state: Any, user: User) -> list[str]:
    """Get user codes that a manager manages, including their own."""
    if user.role != UserRole.MANAGER:
        return []

    managed_codes = [user.user_code]  # Always include self

    if hasattr(state, "user_repo") and state.user_repo:
        if hasattr(state.user_repo, "get_users_managed_by"):
            managed_users = state.user_repo.get_users_managed_by(user.user_id)
            managed_codes.extend(u.user_code for u in managed_users)

    return managed_codes


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_details(
    request: Request,
    job_id: str,
    cancel_error: str | None = Query(None),
    cancel_success: str | None = Query(None),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the job details page."""
    from pulldb.domain.permissions import can_cancel_job

    job = None
    logs = []
    profile = None
    job_can_cancel = False

    if hasattr(state, "job_repo") and state.job_repo:
        job = state.job_repo.get_job_by_id(job_id)
        if job:
            logs = state.job_repo.get_job_events(job_id)

            # Compute can_cancel for this user
            job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
            job_owner_manager_id = job_owner.manager_id if job_owner else None
            job_can_cancel = can_cancel_job(
                user, job.owner_user_id, job_owner_manager_id
            )

            # Try to get profile if job is complete
            if job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
                from pulldb.worker.profiling import parse_profile_from_event

                for event in logs:
                    if event.event_type == "restore_profile" and event.detail:
                        profile = parse_profile_from_event(event.detail)
                        break

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if cancellation was requested
    cancel_requested_at = None
    if hasattr(state.job_repo, "_cancel_requested"):
        cancel_requested_at = state.job_repo._cancel_requested.get(job_id)
    elif hasattr(state.job_repo, "get_cancel_requested_at"):
        cancel_requested_at = state.job_repo.get_cancel_requested_at(job_id)

    # Build flash message from query params
    flash_message = None
    flash_type = None
    if cancel_error:
        flash_message = cancel_error
        flash_type = "error"
    elif cancel_success:
        flash_message = cancel_success
        flash_type = "success"

    return templates.TemplateResponse(
        "features/jobs/details.html",
        {
            "request": request,
            "breadcrumbs": [
                {"label": "Dashboard", "url": "/web/dashboard"},
                {"label": "Jobs", "url": "/web/jobs"},
                {"label": job_id[:8], "url": None},
            ],
            "job": job,
            "logs": logs,
            "profile": profile,
            "user": user,
            "active_nav": "jobs",
            "can_cancel": job_can_cancel,
            "cancel_requested_at": cancel_requested_at,
            "flash_message": flash_message,
            "flash_type": flash_type,
        },
    )


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> RedirectResponse:
    """Cancel a running job."""
    from urllib.parse import urlencode

    from pulldb.domain.permissions import can_cancel_job

    base_url = f"/web/jobs/{job_id}"

    def redirect_error(msg: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'cancel_error': msg})}",
            status_code=303,
        )

    def redirect_success(msg: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'cancel_success': msg})}",
            status_code=303,
        )

    if not hasattr(state, "job_repo") or not state.job_repo:
        return redirect_error("Job repository unavailable")

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return redirect_error("Job not found")

    # Check if job is in cancelable state FIRST
    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        return redirect_error(f"Cannot cancel job (status: {job.status.value})")

    # Authorization check: lookup job owner to get their manager_id
    job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
    job_owner_manager_id = job_owner.manager_id if job_owner else None

    if not can_cancel_job(user, job.owner_user_id, job_owner_manager_id):
        return redirect_error("You do not have permission to cancel this job")

    # Request cancellation
    was_requested = state.job_repo.request_cancellation(job_id)

    if was_requested:
        state.job_repo.append_job_event(
            job_id=job_id,
            event_type="cancel_requested",
            detail=f"User {user.username} requested job cancellation",
        )

        if job.status == JobStatus.QUEUED:
            state.job_repo.mark_job_canceled(
                job_id, "Canceled before execution started"
            )
            return redirect_success("Job canceled successfully")
        else:
            msg = "Cancellation requested - worker will stop at next checkpoint"
            return redirect_success(msg)
    else:
        # Cancellation was already requested or job state changed
        return redirect_error("Cancellation already requested or job completed")
