"""Dashboard routes for Web2 interface."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import User, UserRole, JobStatus
from pulldb.web.dependencies import get_api_state, require_login

router = APIRouter(prefix="/web/dashboard", tags=["web-dashboard"])
templates = Jinja2Templates(directory="pulldb/web/templates")


def _get_user_last_job(state: Any, user_code: str) -> Any:
    """Get user's most recent job."""
    if not hasattr(state, "job_repo") or not state.job_repo:
        return None
    
    if hasattr(state.job_repo, "get_user_last_job"):
        return state.job_repo.get_user_last_job(user_code)
    elif hasattr(state.job_repo, "get_last_job_by_user_code"):
        return state.job_repo.get_last_job_by_user_code(user_code)
    else:
        # Fallback: search through all jobs
        all_jobs = list(getattr(state.job_repo, "active_jobs", [])) + list(getattr(state.job_repo, "history_jobs", []))
        user_jobs = [j for j in all_jobs if getattr(j, "owner_user_code", None) == user_code]
        if user_jobs:
            user_jobs.sort(key=lambda j: j.submitted_at or j.created_at, reverse=True)
            return user_jobs[0]
    return None


def _get_user_active_count(state: Any, user_code: str) -> int:
    """Get count of user's active jobs."""
    if not hasattr(state, "job_repo") or not state.job_repo:
        return 0
    
    active_jobs = []
    if hasattr(state.job_repo, "get_active_jobs"):
        active_jobs = state.job_repo.get_active_jobs()
    elif hasattr(state.job_repo, "active_jobs"):
        active_jobs = state.job_repo.active_jobs
    
    return len([j for j in active_jobs if getattr(j, "owner_user_code", None) == user_code])


def _get_user_recent_jobs(state: Any, user_code: str, limit: int = 5) -> list:
    """Get user's recent jobs."""
    if not hasattr(state, "job_repo") or not state.job_repo:
        return []
    
    all_jobs = list(getattr(state.job_repo, "active_jobs", [])) + list(getattr(state.job_repo, "history_jobs", []))
    user_jobs = [j for j in all_jobs if getattr(j, "owner_user_code", None) == user_code]
    user_jobs.sort(key=lambda j: j.submitted_at or j.created_at, reverse=True)
    return user_jobs[:limit]


def _build_user_context(state: Any, user: User) -> dict:
    """Build dashboard context for USER role."""
    return {
        "my_active_count": _get_user_active_count(state, user.user_code),
        "last_job": _get_user_last_job(state, user.user_code),
        "recent_jobs": _get_user_recent_jobs(state, user.user_code, limit=5),
        "refresh_interval": 15,
        "dashboard_type": "user",
    }


def _build_manager_context(state: Any, user: User) -> dict:
    """Build dashboard context for MANAGER role."""
    # Get managed users
    managed_users = []
    if hasattr(state, "user_repo") and state.user_repo:
        if hasattr(state.user_repo, "get_users_managed_by"):
            managed_users = state.user_repo.get_users_managed_by(user.user_id)
    
    managed_user_ids = {u.user_id for u in managed_users}
    managed_user_codes = {u.user_code for u in managed_users}
    # Include self in team
    managed_user_codes.add(user.user_code)
    managed_user_ids.add(user.user_id)
    
    # Get all jobs for team stats
    all_active = []
    all_history = []
    if hasattr(state, "job_repo") and state.job_repo:
        all_active = list(getattr(state.job_repo, "active_jobs", []))
        all_history = list(getattr(state.job_repo, "history_jobs", []))
    
    # Team job stats
    team_active = [j for j in all_active if getattr(j, "owner_user_code", None) in managed_user_codes]
    team_history = [j for j in all_history if getattr(j, "owner_user_code", None) in managed_user_codes]
    
    team_queued = len([j for j in team_active if j.status == JobStatus.QUEUED])
    team_running = len([j for j in team_active if j.status == JobStatus.RUNNING])
    team_completed = len([j for j in team_history if str(j.status.value).lower() in ("complete", "completed")])
    team_failed = len([j for j in team_history if str(j.status.value).lower() == "failed"])
    
    # Team recent jobs (last 5)
    all_team_jobs = team_active + team_history
    all_team_jobs.sort(key=lambda j: j.submitted_at or j.created_at, reverse=True)
    team_recent = all_team_jobs[:5]
    
    # Build user list with active job counts
    users_with_counts = []
    for u in managed_users:
        active_count = len([j for j in all_active if getattr(j, "owner_user_id", None) == u.user_id])
        users_with_counts.append({
            "user": u,
            "active_jobs": active_count,
        })
    
    return {
        "my_active_count": _get_user_active_count(state, user.user_code),
        "last_job": _get_user_last_job(state, user.user_code),
        "refresh_interval": 10,
        "dashboard_type": "manager",
        # Team stats
        "team_stats": {
            "managed_users": len(managed_users),
            "active_users": len([u for u in managed_users if not u.disabled_at]),
            "disabled_users": len([u for u in managed_users if u.disabled_at]),
            "queued_jobs": team_queued,
            "running_jobs": team_running,
            "completed_jobs": team_completed,
            "failed_jobs": team_failed,
        },
        "team_users": users_with_counts,
        "team_recent": team_recent,
    }


def _build_admin_context(state: Any, user: User) -> dict:
    """Build dashboard context for ADMIN role."""
    # Get all users
    all_users = []
    if hasattr(state, "user_repo") and state.user_repo:
        if hasattr(state.user_repo, "get_users_with_job_counts"):
            all_users = state.user_repo.get_users_with_job_counts()
        elif hasattr(state.user_repo, "users"):
            all_users = state.user_repo.users
    
    # Get all hosts
    all_hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        if hasattr(state.host_repo, "get_all_hosts"):
            all_hosts = state.host_repo.get_all_hosts()
        elif hasattr(state.host_repo, "hosts"):
            all_hosts = state.host_repo.hosts
    
    # Get all jobs
    all_active = []
    all_history = []
    if hasattr(state, "job_repo") and state.job_repo:
        all_active = list(getattr(state.job_repo, "active_jobs", []))
        all_history = list(getattr(state.job_repo, "history_jobs", []))
    
    # System stats
    system_queued = len([j for j in all_active if j.status == JobStatus.QUEUED])
    system_running = len([j for j in all_active if j.status == JobStatus.RUNNING])
    system_completed = len([j for j in all_history if str(j.status.value).lower() in ("complete", "completed")])
    system_failed = len([j for j in all_history if str(j.status.value).lower() == "failed"])
    
    # Host health - count active restores per host with queue warnings
    host_health = []
    for host in all_hosts:
        # Use host_alias if available, else hostname (real DBHost attributes only)
        host_name = getattr(host, "host_alias", None) or getattr(host, "hostname", "unknown")
        hostname_fqdn = getattr(host, "hostname", "")
        
        # Count jobs targeting this host (match on hostname or alias)
        jobs_on_host = [j for j in all_active 
                        if getattr(j, "dbhost", None) in (host_name, hostname_fqdn)]
        queued_count = len([j for j in jobs_on_host if j.status == JobStatus.QUEUED])
        running_count = len([j for j in jobs_on_host if j.status == JobStatus.RUNNING])
        
        host_health.append({
            "host": host,
            "name": host_name,
            "hostname": hostname_fqdn,
            "active_restores": len(jobs_on_host),
            "queued_count": queued_count,
            "running_count": running_count,
            "capacity": getattr(host, "max_concurrent_restores", 5),
            "enabled": getattr(host, "enabled", True),  # Pre-computed for template
        })
    
    # System recent jobs (last 10)
    all_jobs = all_active + all_history
    all_jobs.sort(key=lambda j: j.submitted_at or j.created_at, reverse=True)
    system_recent = all_jobs[:10]
    
    return {
        "my_active_count": _get_user_active_count(state, user.user_code),
        "last_job": _get_user_last_job(state, user.user_code),
        "refresh_interval": 5,
        "dashboard_type": "admin",
        # System stats
        "system_stats": {
            "total_users": len(all_users),
            "active_users": len([u for u in all_users if not getattr(u, "disabled_at", None)]),
            "disabled_users": len([u for u in all_users if getattr(u, "disabled_at", None)]),
            "total_hosts": len(all_hosts),
            "enabled_hosts": len([h for h in all_hosts if getattr(h, "enabled", True)]),
            "disabled_hosts": len([h for h in all_hosts if not getattr(h, "enabled", True)]),
            "queued_jobs": system_queued,
            "running_jobs": system_running,
            "completed_jobs": system_completed,
            "failed_jobs": system_failed,
        },
        "host_health": host_health,
        "system_recent": system_recent,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the role-specific dashboard page."""
    # Build context based on user role
    if user.role == UserRole.ADMIN:
        context = _build_admin_context(state, user)
    elif user.role == UserRole.MANAGER:
        context = _build_manager_context(state, user)
    else:
        context = _build_user_context(state, user)
    
    return templates.TemplateResponse(
        "features/dashboard/dashboard.html",
        {
            "request": request,
            "user": user,
            "active_nav": "dashboard",
            **context,
        },
    )
