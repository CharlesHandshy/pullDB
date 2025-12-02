"""Web UI routes for pullDB.

Phase 4: FastAPI routes serving HTML pages with Jinja2 templates.
Uses HTMX for dynamic updates without full page reloads.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import User

if TYPE_CHECKING:
    from pulldb.api.main import APIState


# Template configuration
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Router for web UI routes
router = APIRouter(prefix="/web", tags=["web"])


class SessionExpiredError(Exception):
    """Raised when a session is invalid or expired."""
    
    def __init__(self, is_htmx: bool = False):
        self.is_htmx = is_htmx
        super().__init__("Session expired")


def _render_error_page(
    request: Request,
    user: User | None,
    status_code: int,
    title: str,
    message: str,
    detail: str | None = None,
    suggestions: list[str] | None = None,
    back_url: str | None = None,
) -> Response:
    """Render a user-friendly error page."""
    error_types = {
        404: "warning",
        403: "error",
        500: "error",
    }
    # Use referer header as back URL if not specified
    if back_url is None:
        back_url = request.headers.get("referer")
    
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "user": user,
            "status_code": status_code,
            "title": title,
            "subtitle": message,
            "message": message,
            "detail": detail,
            "error_type": error_types.get(status_code, "warning"),
            "suggestions": suggestions,
            "back_url": back_url,
        },
        status_code=status_code,
    )


def _get_api_state(request: Request) -> "APIState":
    """Get API state from request."""
    from pulldb.api.main import get_api_state
    return get_api_state()


def _get_session_user(
    request: Request,
    state: "APIState" = Depends(_get_api_state),
) -> User | None:
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
    request: Request,
    user: Annotated[User | None, Depends(_get_session_user)],
) -> User:
    """Require authenticated user, redirect to login if not.
    
    Handles both regular requests (via Location header) and HTMX requests
    (via HX-Redirect header) to properly redirect to the login page when
    the session is invalid or expired.
    """
    if not user:
        # Check if this is an HTMX request
        is_htmx = request.headers.get("HX-Request") == "true"
        raise SessionExpiredError(is_htmx=is_htmx)
    return user


def create_session_expired_handler():
    """Create exception handler for SessionExpiredError.
    
    Returns a response that clears the session cookie and redirects to login.
    For HTMX requests, uses HX-Redirect header.
    For regular requests, uses HTTP 303 redirect.
    """
    async def handler(request: Request, exc: SessionExpiredError) -> Response:
        if exc.is_htmx:
            # For HTMX requests, return 200 with HX-Redirect header
            response = Response(
                content="",
                status_code=200,
                headers={"HX-Redirect": "/web/login"},
            )
        else:
            # For regular requests, use HTTP redirect
            response = RedirectResponse(
                url="/web/login",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        # Clear the invalid session cookie
        response.delete_cookie("session_token")
        return response
    
    return handler


# =============================================================================
# Public Routes (No Authentication)
# =============================================================================


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = None,
    user: Annotated[User | None, Depends(_get_session_user)] = None,
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
    user: Annotated[User, Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display user dashboard with active jobs."""
    from pulldb.domain.permissions import can_view_all_jobs
    
    # Get jobs based on user role
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


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: str,
    user: Annotated[User, Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display job details."""
    from pulldb.domain.permissions import can_cancel_job, can_view_job
    from urllib.parse import urlparse, parse_qs
    
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return _render_error_page(
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
        return _render_error_page(
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
    
    # Extract tab from referrer URL to preserve navigation state
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


# =============================================================================
# HTMX Partial Updates
# =============================================================================


@router.get("/partials/active-jobs", response_class=HTMLResponse)
async def partial_active_jobs(
    request: Request,
    user: Annotated[User, Depends(_require_login)],
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
    user: Annotated[User, Depends(_require_login)],
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


# =============================================================================
# User Pages (CLI Command Equivalents)
# =============================================================================


@router.get("/restore", response_class=HTMLResponse)
async def restore_page(
    request: Request,
    user: Annotated[User, Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
    customer: str | None = None,
    date: str | None = None,
    s3env: str | None = None,
) -> Response:
    """Display restore form (equivalent to pulldb restore command).
    
    URL params for pre-filling (from Search page):
      - customer: Pre-fill customer name
      - date: Pre-select backup date (YYYYMMDD format)
      - s3env: Pre-select source environment (staging/prod)
    """
    # Get available hosts for dropdown
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
    
    # Get user's recent restore jobs
    recent_jobs = []
    if hasattr(state, "job_repo") and state.job_repo:
        if hasattr(state.job_repo, "get_user_recent_jobs"):
            recent_jobs = state.job_repo.get_user_recent_jobs(user.user_id, limit=5)
    
    # Pre-fill context for linking from search page
    prefill = {
        "customer": customer or "",
        "date": date or "",
        "s3env": s3env or "",
    }
    
    return templates.TemplateResponse(
        request=request,
        name="restore.html",
        context={
            "user": user,
            "hosts": hosts,
            "recent_jobs": recent_jobs,
            "prefill": prefill,
        },
    )


@router.post("/restore")
async def restore_submit(
    request: Request,
    user: Annotated[User, Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
    customer: str | None = Form(None),
    date: str | None = Form(None),
    s3env: str | None = Form(None),
    qatemplate: str = Form("false"),
    dbhost: str | None = Form(None),
    target: str | None = Form(None),
    overwrite: str | None = Form(None),
) -> Response:
    """Handle restore form submission.
    
    Submits a new restore job and redirects to the job detail page.
    """
    import uuid
    from datetime import UTC, datetime
    
    # Build the job request
    is_qatemplate = qatemplate.lower() == "true"
    
    try:
        # Check if we're in dev server mode (mock state without settings_repo)
        if not hasattr(state, "settings_repo") or state.settings_repo is None:
            # Dev server mock flow - create a simple mock job
            job_id = str(uuid.uuid4())
            
            # Construct target name: user_code + customer (lowercase letters only)
            if is_qatemplate:
                target_name = f"{user.user_code}qatemplate"
            else:
                # Sanitize customer name to lowercase letters only
                clean_customer = "".join(c for c in (customer or "").lower() if c.isalpha())
                target_name = f"{user.user_code}{clean_customer}"
            
            # Create a simple mock job object
            from unittest.mock import MagicMock
            job = MagicMock()
            job.id = job_id
            job.job_id = job_id
            job.target = target_name
            job.staging_name = f"{target_name}_{job_id.replace('-', '')[:12]}"
            job.status = "queued"
            job.owner_user_id = user.user_id
            job.owner_username = user.username
            job.owner_user_code = user.user_code
            job.user_code = user.user_code
            job.username = user.username
            job.created_at = datetime.now(UTC)
            job.submitted_at = datetime.now(UTC)
            job.started_at = None
            job.finished_at = None
            job.completed_at = None
            job.dbhost = dbhost or "localhost"
            job.worker_id = None
            job.error_detail = None
            job.source_customer = customer if not is_qatemplate else "QA Template"
            job.backup_env = s3env if s3env and s3env != "both" else "prd"
            job.backup_file = f"{customer or 'qatemplate'}/{job.backup_env}/{date or 'latest'}/backup.tar.gz"
            job.current_operation = None
            job.options_json = {
                "is_qatemplate": str(is_qatemplate).lower(),
                "customer_id": customer,
                "env": s3env,
                "overwrite": str(overwrite == "true").lower(),
            }
            
            # Add to mock job repo
            if hasattr(state, "job_repo") and hasattr(state.job_repo, "enqueue_job"):
                state.job_repo.enqueue_job(job)
            
            # Redirect to the job detail page
            return RedirectResponse(
                url=f"/web/jobs/{job_id}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        
        # Production flow - use the real API enqueue
        from pulldb.api.main import JobRequest, _enqueue_job
        from starlette.concurrency import run_in_threadpool
        
        req = JobRequest(
            user=user.username,
            customer=customer if not is_qatemplate else None,
            qatemplate=is_qatemplate,
            dbhost=dbhost if dbhost else None,
            date=date,
            env=s3env if s3env and s3env != "both" else None,
            overwrite=overwrite == "true",
        )
        
        job_response = await run_in_threadpool(_enqueue_job, state, req)
        
        # Redirect to the job detail page
        return RedirectResponse(
            url=f"/web/jobs/{job_response.job_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except HTTPException as exc:
        # Show error page with the error detail
        return _render_error_page(
            request=request,
            user=user,
            status_code=exc.status_code,
            title="Job Submission Failed",
            message=exc.detail,
            suggestions=[
                "Check that the customer name and backup date are valid",
                "Ensure you don't already have an active job for this target",
                "Try a different database host if the default is busy",
            ],
            back_url="/web/restore",
        )
    except Exception as exc:
        # Handle unexpected errors
        return _render_error_page(
            request=request,
            user=user,
            status_code=500,
            title="Unexpected Error",
            message=str(exc),
            suggestions=[
                "Try again in a few moments",
                "Contact support if the problem persists",
            ],
            back_url="/web/restore",
        )


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    user: Annotated[User, Depends(_require_login)],
    customer: str | None = None,
    s3env: str = "both",
    date_from: str | None = None,
    limit: int = 10,
) -> Response:
    """Display backup search (equivalent to pulldb search command)."""
    import fnmatch
    import random
    from datetime import timedelta
    
    backups = []
    searched = bool(customer)
    
    if customer:
        # Mock backup data - generate realistic results
        mock_customers = [
            "acmehvac", "acmepest", "actionpest", "actionplumbing",
            "bigcorp", "cleanpro", "deltaplumbing", "eliteelectric",
            "fastfix", "greenscapes", "homeservices", "techcorp",
        ]
        
        # Filter by customer pattern (supports wildcards)
        pattern = customer.replace("*", ".*")
        import re
        matching = [c for c in mock_customers if re.match(f"^{pattern}$", c, re.IGNORECASE)]
        
        # If no wildcard match, try contains
        if not matching and "*" not in customer:
            matching = [c for c in mock_customers if customer.lower() in c.lower()]
        
        # Generate mock backups for matching customers
        base_date = datetime.now(UTC)
        for cust in matching[:5]:  # Limit customers
            for i in range(min(3, limit // len(matching) + 1)):  # 3 backups per customer
                backup_date = base_date - timedelta(days=i)
                env = "staging" if i % 2 == 0 else "prod"
                
                # Apply s3env filter
                if s3env != "both" and env != s3env:
                    continue
                
                size_mb = random.randint(500, 4000)
                size_display = f"{size_mb / 1000:.1f} GB" if size_mb >= 1000 else f"{size_mb} MB"
                
                backups.append({
                    "customer": cust,
                    "date": backup_date.strftime("%b %d, %Y"),
                    "date_raw": backup_date.strftime("%Y%m%d"),
                    "time": backup_date.strftime("%H:%M"),
                    "size_display": size_display,
                    "environment": env,
                    "s3_key": f"s3://pulldb-backups-{env}/{cust}/{backup_date.strftime('%Y%m%d')}/backup.tar.gz",
                })
        
        # Sort by date descending
        backups.sort(key=lambda b: b["date_raw"], reverse=True)
        backups = backups[:limit]
    
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "user": user,
            "backups": backups,
            "customer": customer,
            "s3env": s3env,
            "date_from": date_from,
            "limit": limit,
            "searched": searched,
            "total_count": len(backups),
        },
    )


@router.get("/jobs/{job_id}/profile", response_class=HTMLResponse)
async def job_profile_page(
    request: Request,
    job_id: str,
    user: Annotated[User, Depends(_require_login)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display job profile (equivalent to pulldb profile command)."""
    from pulldb.domain.permissions import can_view_job
    
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return _render_error_page(
            request=request,
            user=user,
            status_code=404,
            title="Job Not Found",
            message=f"The job '{job_id}' could not be found.",
            suggestions=[
                "Check that the job ID is correct",
                "The job may have been purged from the system",
                "Try searching for the job on the dashboard",
            ],
        )
    
    if not can_view_job(user, job.owner_user_id):
        return _render_error_page(
            request=request,
            user=user,
            status_code=403,
            title="Access Denied",
            message="You don't have permission to view this job profile.",
            suggestions=[
                "This job belongs to another user",
                "Contact an administrator if you need access",
            ],
        )
    
    events = state.job_repo.get_job_events(job_id)
    
    # Build profile from events (timing analysis)
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
    
    # Simple phase extraction from events
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
    
    # Calculate percentages
    for phase in phases:
        if total_duration > 0:
            phase["percentage"] = (phase["duration"] / total_duration) * 100
        else:
            phase["percentage"] = 0
    
    return {
        "phases": phases,
        "total_duration": total_duration,
        "formatted_total": f"{int(total_duration // 60)}m {int(total_duration % 60)}s" if total_duration else "N/A",
    }


# =============================================================================
# Admin Routes (Require Admin Role)
# =============================================================================


def _require_admin(
    user: Annotated[User, Depends(_require_login)],
) -> User:
    """Require admin user."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display settings management (equivalent to pulldb-admin settings)."""
    # Mock settings - in real implementation, read from config
    settings = [
        {"key": "myloader_threads", "value": "4", "default": "4", "description": "Number of myloader threads"},
        {"key": "myloader_compress_protocol", "value": "true", "default": "true", "description": "Enable compression"},
        {"key": "work_directory", "value": "/tmp/pulldb", "default": "/tmp/pulldb", "description": "Work directory path"},
        {"key": "customers_after_sql_dir", "value": "/etc/pulldb/after_sql", "default": "", "description": "Custom SQL directory"},
        {"key": "backup_retention_days", "value": "30", "default": "30", "description": "Backup retention period"},
    ]
    
    return templates.TemplateResponse(
        request=request,
        name="admin/settings.html",
        context={
            "user": user,
            "settings": settings,
        },
    )


# Logo configuration file path
LOGO_CONFIG_PATH = Path(__file__).parent.parent / "images" / "logo_config.json"


def _get_logo_config() -> dict:
    """Load logo configuration from JSON file."""
    default_label_style = {
        "x": 0,
        "y": 0,
        "font": "system-ui, -apple-system, sans-serif",
        "size": 20,
        "weight": "700",
        "style": "normal",
        "color": "#1f2937",
        "rotation": 0,
        "spacing": 0,
        "transform": "none",
    }
    
    default_config = {
        "path": "/static/images/pullDB_logo.mp4",
        "type": "video",
        "label": "",
        "logo_scale": 100,
        "crop_top": 13,
        "crop_bottom": 17,
        "crop_left": 0,
        "crop_right": 0,
        "label_style": default_label_style,
    }
    
    if LOGO_CONFIG_PATH.exists():
        try:
            with open(LOGO_CONFIG_PATH) as f:
                config = json.load(f)
                label_style = config.get("labelStyle", {})
                return {
                    "path": config.get("path", default_config["path"]),
                    "type": config.get("type", default_config["type"]),
                    "label": config.get("label", default_config["label"]),
                    "logo_scale": config.get("logoScale", default_config["logo_scale"]),
                    "crop_top": config.get("crop", {}).get("top", default_config["crop_top"]),
                    "crop_bottom": config.get("crop", {}).get("bottom", default_config["crop_bottom"]),
                    "crop_left": config.get("crop", {}).get("left", default_config["crop_left"]),
                    "crop_right": config.get("crop", {}).get("right", default_config["crop_right"]),
                    "label_style": {
                        "x": label_style.get("x", default_label_style["x"]),
                        "y": label_style.get("y", default_label_style["y"]),
                        "font": label_style.get("font", default_label_style["font"]),
                        "size": label_style.get("size", default_label_style["size"]),
                        "weight": label_style.get("weight", default_label_style["weight"]),
                        "style": label_style.get("style", default_label_style["style"]),
                        "color": label_style.get("color", default_label_style["color"]),
                        "rotation": label_style.get("rotation", default_label_style["rotation"]),
                        "spacing": label_style.get("spacing", default_label_style["spacing"]),
                        "transform": label_style.get("transform", default_label_style["transform"]),
                    },
                }
        except Exception:
            pass
    
    return default_config


@router.get("/admin/logo", response_class=HTMLResponse)
async def admin_logo_page(
    request: Request,
    user: Annotated[User, Depends(_require_admin)],
) -> Response:
    """Display logo management screen."""
    logo_config = _get_logo_config()
    
    return templates.TemplateResponse(
        request=request,
        name="admin/logo.html",
        context={
            "user": user,
            "logo_config": logo_config,
        },
    )


@router.post("/admin/logo")
async def save_logo_config(
    request: Request,
    user: Annotated[User, Depends(_require_admin)],
) -> dict:
    """Save logo configuration to JSON file."""
    data = await request.json()
    
    # Ensure directory exists
    LOGO_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Save config
    with open(LOGO_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
    
    return {"status": "success", "message": "Logo configuration saved"}


# Logo upload directory
LOGO_UPLOAD_DIR = Path(__file__).parent.parent / "images"


@router.post("/admin/logo/upload")
async def upload_logo(
    user: Annotated[User, Depends(_require_admin)],
    file: UploadFile = File(...),
) -> JSONResponse:
    """Upload a new logo file."""
    # Validate file type
    allowed_types = ["video/mp4", "video/webm", "image/png", "image/jpeg", "image/svg+xml", "image/gif"]
    if file.content_type not in allowed_types:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid file type: {file.content_type}. Allowed: {', '.join(allowed_types)}"}
        )
    
    # Ensure upload directory exists
    LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    # Generate filename (keep original name but sanitize)
    filename = file.filename or "logo"
    # Sanitize filename - keep only alphanumeric, dash, underscore, dot
    safe_filename = "".join(c for c in filename if c.isalnum() or c in ".-_")
    if not safe_filename:
        safe_filename = "uploaded_logo"
    
    # Add extension if missing
    ext_map = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/svg+xml": ".svg",
        "image/gif": ".gif",
    }
    if not any(safe_filename.lower().endswith(e) for e in ext_map.values()):
        safe_filename += ext_map.get(file.content_type, "")
    
    # Save file
    file_path = LOGO_UPLOAD_DIR / safe_filename
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Return the path to use in config
    return JSONResponse(content={
        "status": "success",
        "path": f"/static/images/{safe_filename}",
        "filename": safe_filename,
        "type": "video" if file.content_type.startswith("video/") else "image"
    })


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display user management (equivalent to pulldb-admin users list)."""
    users = state.user_repo.list_users() if hasattr(state.user_repo, "list_users") else []
    
    # Calculate stats
    stats = {
        "total": len(users),
        "admins": len([u for u in users if u.is_admin]),
        "active": len([u for u in users if not u.disabled_at]),
        "disabled": len([u for u in users if u.disabled_at]),
    }
    
    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "user": user,
            "users": users,
            "stats": stats,
        },
    )


@router.get("/admin/users/{username}", response_class=HTMLResponse)
async def admin_user_detail_page(
    request: Request,
    username: str,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display user detail (equivalent to pulldb-admin users show)."""
    target_user = state.user_repo.get_user_by_username(username)
    if not target_user:
        return _render_error_page(
            request=request,
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
    
    # Get user's jobs
    all_jobs = state.job_repo.get_recent_jobs(limit=100)
    user_jobs = [j for j in all_jobs if j.owner_user_id == target_user.user_id][:10]
    
    # Calculate stats
    stats = {
        "active_jobs": len([j for j in user_jobs if j.status in ("pending", "running")]),
        "total_jobs": len(user_jobs),
        "completed_jobs": len([j for j in user_jobs if j.status == "completed"]),
        "failed_jobs": len([j for j in user_jobs if j.status == "failed"]),
        "cancelled_jobs": len([j for j in user_jobs if j.status == "cancelled"]),
    }
    
    return templates.TemplateResponse(
        request=request,
        name="admin/user_detail.html",
        context={
            "user": target_user,  # The user being viewed
            "current_user": user,  # The logged-in admin
            "jobs": user_jobs,
            "stats": stats,
        },
    )


@router.post("/admin/users/{username}/enable")
async def admin_enable_user(
    request: Request,
    username: str,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Enable a user account."""
    target_user = state.user_repo.get_user_by_username(username)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if hasattr(state.user_repo, "enable_user"):
        state.user_repo.enable_user(target_user.user_id)
    
    return RedirectResponse(url=f"/web/admin/users/{username}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/{username}/disable")
async def admin_disable_user(
    request: Request,
    username: str,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Disable a user account."""
    target_user = state.user_repo.get_user_by_username(username)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if hasattr(state.user_repo, "disable_user"):
        state.user_repo.disable_user(target_user.user_id)
    
    return RedirectResponse(url=f"/web/admin/users/{username}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/hosts", response_class=HTMLResponse)
async def admin_hosts_page(
    request: Request,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display host management (equivalent to pulldb-admin hosts list)."""
    # Mock hosts - in real implementation, read from host_repo
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.list_hosts() if hasattr(state.host_repo, "list_hosts") else []
    
    # Calculate stats
    stats = {
        "total": len(hosts),
        "enabled": len([h for h in hosts if not getattr(h, "disabled", False)]),
        "disabled": len([h for h in hosts if getattr(h, "disabled", False)]),
        "active_restores": 0,  # Would need to calculate from job_repo
    }
    
    return templates.TemplateResponse(
        request=request,
        name="admin/hosts.html",
        context={
            "user": user,
            "hosts": hosts,
            "stats": stats,
        },
    )


@router.get("/admin/jobs", response_class=HTMLResponse)
async def admin_jobs_page(
    request: Request,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
    page: int = 1,
) -> Response:
    """Display all jobs (equivalent to pulldb-admin jobs list)."""
    limit = 50
    # Get both active and recent jobs
    active_jobs = []
    if hasattr(state.job_repo, "get_active_jobs"):
        active_jobs = state.job_repo.get_active_jobs()
    recent_jobs = state.job_repo.get_recent_jobs(limit=limit * page)
    jobs = list(active_jobs) + list(recent_jobs)
    
    # Get users and hosts for filters
    users = state.user_repo.list_users() if hasattr(state.user_repo, "list_users") else []
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        hosts = state.host_repo.list_hosts()
    
    # Calculate stats
    all_jobs = jobs  # Use combined jobs list for stats
    today_jobs = [j for j in all_jobs if j.created_at and j.created_at.date() == datetime.now(UTC).date()]
    
    stats = {
        "running": len([j for j in all_jobs if j.status == "running"]),
        "pending": len([j for j in all_jobs if j.status == "pending"]),
        "completed_today": len([j for j in today_jobs if j.status == "completed"]),
        "failed_today": len([j for j in today_jobs if j.status == "failed"]),
    }
    
    # Pagination
    total_jobs = len(jobs)
    pagination = {
        "page": page,
        "per_page": limit,
        "total": total_jobs,
        "total_pages": (total_jobs // limit) + (1 if total_jobs % limit else 0) if total_jobs else 1,
        "has_prev": page > 1,
        "has_next": total_jobs > limit * page,
    }
    
    return templates.TemplateResponse(
        request=request,
        name="admin/jobs.html",
        context={
            "user": user,
            "jobs": jobs[(page - 1) * limit:page * limit],
            "users": users,
            "hosts": hosts,
            "stats": stats,
            "pagination": pagination,
            "now": datetime.now(UTC),
        },
    )


@router.post("/admin/jobs/{job_id}/cancel")
async def admin_cancel_job(
    request: Request,
    job_id: str,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Cancel a job (admin override)."""
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if hasattr(state.job_repo, "cancel_job"):
        state.job_repo.cancel_job(job_id)
    
    return RedirectResponse(url="/web/admin/jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/cleanup", response_class=HTMLResponse)
async def admin_cleanup_page(
    request: Request,
    user: Annotated[User, Depends(_require_admin)],
    state: "APIState" = Depends(_get_api_state),
) -> Response:
    """Display cleanup page (equivalent to pulldb-admin cleanup)."""
    # Get hosts for dropdown
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        hosts = state.host_repo.list_hosts()
    
    return templates.TemplateResponse(
        request=request,
        name="admin/cleanup.html",
        context={
            "user": user,
            "hosts": hosts,
            "last_cleanup": None,  # Would need to track cleanup history
        },
    )
