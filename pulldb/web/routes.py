"""Web UI routes for pullDB.

Phase 4: FastAPI routes serving HTML pages with Jinja2 templates.
Uses HTMX for dynamic updates without full page reloads.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


if TYPE_CHECKING:
    from pulldb.api.main import APIState
    from pulldb.domain.models import User


# Template configuration
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Router for web UI routes
router = APIRouter(prefix="/web", tags=["web"])


def _get_api_state(request: Request) -> "APIState":
    """Get API state from request."""
    from pulldb.api.main import get_api_state
    return get_api_state()


def _get_session_user(
    request: Request,
    state: "APIState" = Depends(_get_api_state),
) -> "User | None":
    """Get current user from session cookie if valid."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return None
    
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return None
    
    user_id = state.auth_repo.validate_session(session_token)
    if not user_id:
        return None
    
    return state.user_repo.get_user_by_id(user_id)


def _require_login(
    user: Annotated["User | None", Depends(_get_session_user)],
) -> "User":
    """Require authenticated user, redirect to login if not."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/web/login"},
        )
    return user


# =============================================================================
# Public Routes (No Authentication)
# =============================================================================


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = None,
    user: Annotated["User | None", Depends(_get_session_user)] = None,
) -> Response:
    """Display login form."""
    # If already logged in, redirect to dashboard
    if user:
        return RedirectResponse(url="/web/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Process login form submission."""
    from pulldb.auth.password import verify_password
    
    # Look up user
    user = state.user_repo.get_user_by_username(username)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    
    # Check if user is disabled
    if user.disabled_at:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Account is disabled"},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    
    # Check password
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Authentication not configured"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    
    password_hash = state.auth_repo.get_password_hash(user.user_id)
    if not password_hash or not verify_password(password, password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    
    # Create session
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    _, session_token = state.auth_repo.create_session(
        user.user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    
    # Set cookie and redirect
    response = RedirectResponse(url="/web/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=os.getenv("PULLDB_SECURE_COOKIES", "false").lower() == "true",
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


@router.get("/logout")
async def logout(
    request: Request,
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Log out user and clear session."""
    session_token = request.cookies.get("session_token")
    
    if session_token and hasattr(state, "auth_repo") and state.auth_repo:
        state.auth_repo.invalidate_session_by_token(session_token)
    
    response = RedirectResponse(url="/web/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_token")
    return response


# =============================================================================
# Protected Routes (Require Authentication)
# =============================================================================


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: Annotated["User", Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display user dashboard with active jobs."""
    from pulldb.domain.permissions import can_view_all_jobs
    
    # Get jobs based on user role
    if can_view_all_jobs(user):
        active_jobs = state.job_repo.get_active_jobs()
        recent_jobs = state.job_repo.get_recent_jobs(limit=10)
    else:
        active_jobs = [
            j for j in state.job_repo.get_active_jobs()
            if j.owner_user_id == user.user_id
        ]
        recent_jobs = [
            j for j in state.job_repo.get_recent_jobs(limit=50)
            if j.owner_user_id == user.user_id
        ][:10]
    
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


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_list(
    request: Request,
    user: Annotated["User", Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
    status_filter: str | None = None,
    limit: int = 50,
) -> Response:
    """Display job history with optional filtering."""
    from pulldb.domain.permissions import can_view_all_jobs
    
    # Determine status filter
    statuses = None
    if status_filter and status_filter != "all":
        statuses = [status_filter]
    
    # Get jobs based on user role
    if can_view_all_jobs(user):
        jobs = state.job_repo.get_recent_jobs(limit=limit, statuses=statuses)
    else:
        all_jobs = state.job_repo.get_recent_jobs(limit=limit * 2, statuses=statuses)
        jobs = [j for j in all_jobs if j.owner_user_id == user.user_id][:limit]
    
    return templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context={
            "user": user,
            "jobs": jobs,
            "status_filter": status_filter or "all",
            "now": datetime.now(UTC),
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: str,
    user: Annotated["User", Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display job details."""
    from pulldb.domain.permissions import can_cancel_job, can_view_job
    
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not can_view_job(user, job.owner_user_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    events = state.job_repo.get_job_events(job_id)
    
    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "user": user,
            "job": job,
            "events": events,
            "can_cancel": can_cancel_job(user, job.owner_user_id),
            "now": datetime.now(UTC),
        },
    )


# =============================================================================
# HTMX Partial Updates
# =============================================================================


@router.get("/partials/active-jobs", response_class=HTMLResponse)
async def partial_active_jobs(
    request: Request,
    user: Annotated["User", Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
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


@router.get("/partials/job-events/{job_id}", response_class=HTMLResponse)
async def partial_job_events(
    request: Request,
    job_id: str,
    user: Annotated["User", Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
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
