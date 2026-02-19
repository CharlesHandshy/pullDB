from __future__ import annotations

"""Manager routes for Web2 interface.

HCA Layer: features (pulldb/web/features/)
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from pulldb.domain.models import JobStatus, User
from pulldb.web.dependencies import get_api_state, require_manager_or_above, templates
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

router = APIRouter(prefix="/web/manager", tags=["web-manager"])


@router.get("/api/team")
async def api_team_paginated(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_manager_or_above),
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict:
    """Get paginated team members for LazyTable."""
    # Get users managed by this manager
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)

    # Get active job counts per user
    user_active_jobs: dict[str, int] = {}
    for mu in managed_users:
        jobs = state.job_repo.get_jobs_by_user(mu.user_id)
        user_active_jobs[mu.user_id] = len([
            j for j in jobs
            if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        ])

    # Check password reset status per user
    user_password_reset: dict[str, bool] = {}
    for mu in managed_users:
        if state.auth_repo and hasattr(state.auth_repo, "is_password_reset_required"):
            user_password_reset[mu.user_id] = state.auth_repo.is_password_reset_required(mu.user_id)
        else:
            user_password_reset[mu.user_id] = False

    # Build enriched user list
    all_users = []
    for u in managed_users:
        all_users.append({
            "user_id": u.user_id,
            "username": u.username,
            "user_code": u.user_code,
            "active_jobs": user_active_jobs.get(u.user_id, 0),
            "disabled_at": u.disabled_at.isoformat() if u.disabled_at else None,
            "status": "disabled" if u.disabled_at else "active",
            "password_reset_pending": user_password_reset.get(u.user_id, False),
        })

    total_count = len(all_users)
    
    # Apply filters
    text_filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]

    if text_filters:
        filtered = []
        for u in all_users:
            match = True
            for col, vals in text_filters.items():
                cell = str(u.get(col, "")).lower()
                if not any(v in cell for v in vals):
                    match = False
                    break
            if match:
                filtered.append(u)
        all_users = filtered

    filtered_count = len(all_users)

    # Apply sorting
    if sortColumn and sortDirection:
        reverse = sortDirection == "desc"
        sort_keys: dict[str, Any] = {
            "username": lambda u: (u.get("username") or "").lower(),
            "user_code": lambda u: (u.get("user_code") or "").lower(),
            "active_jobs": lambda u: u.get("active_jobs", 0),
            "status": lambda u: 0 if u.get("disabled_at") else 1,
        }
        if sortColumn in sort_keys:
            all_users = sorted(all_users, key=sort_keys[sortColumn], reverse=reverse)

    # Paginate
    offset = page * pageSize
    page_users = all_users[offset : offset + pageSize]

    return {
        "rows": page_users,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "page": page,
        "pageSize": pageSize,
    }


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
            "active_nav": "manager",
            "breadcrumbs": get_breadcrumbs("manager"),
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

    # Get target user for audit context
    target_user = next((u for u in managed_users if u.user_id == user_id), None)

    # Mark password reset required
    if hasattr(state.auth_repo, "mark_password_reset"):
        state.auth_repo.mark_password_reset(user_id)
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="team_password_reset",
                target_user_id=user_id,
                detail=f"Manager forced password reset for {target_user.username if target_user else user_id[:12]}",
            )

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

    # Get target user for audit context
    target_user = next((u for u in managed_users if u.user_id == user_id), None)

    # Clear password reset requirement
    if hasattr(state.auth_repo, "clear_password_reset"):
        state.auth_repo.clear_password_reset(user_id)
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="team_clear_password_reset",
                target_user_id=user_id,
                detail=f"Manager cleared password reset for {target_user.username if target_user else user_id[:12]}",
            )

    return RedirectResponse(url="/web/manager/", status_code=303)


@router.post("/my-team/{user_id}/enable")
async def enable_team_member(
    user_id: str,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> dict:
    """Enable a disabled managed user."""
    try:
        # Verify user is managed by this manager
        managed_users = []
        if hasattr(state.user_repo, "get_users_managed_by"):
            managed_users = state.user_repo.get_users_managed_by(user.user_id)

        managed_user_ids = {u.user_id for u in managed_users}
        if user_id not in managed_user_ids:
            return {"success": False, "message": "User is not managed by you"}

        # Get target user for audit context
        target_user = next((u for u in managed_users if u.user_id == user_id), None)

        # Enable the user
        if hasattr(state.user_repo, "enable_user_by_id"):
            state.user_repo.enable_user_by_id(user_id)
        elif hasattr(state.user_repo, "enable_user"):
            state.user_repo.enable_user(user_id)

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="team_user_enabled",
                target_user_id=user_id,
                detail=f"Manager enabled team member {target_user.username if target_user else user_id[:12]}",
            )

        return {"success": True, "message": "User enabled successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/my-team/{user_id}/disable")
async def disable_team_member(
    user_id: str,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> dict:
    """Disable a managed user."""
    try:
        # Prevent self-modification
        if user_id == user.user_id:
            return {"success": False, "message": "Cannot disable your own account"}

        # Verify user is managed by this manager
        managed_users = []
        if hasattr(state.user_repo, "get_users_managed_by"):
            managed_users = state.user_repo.get_users_managed_by(user.user_id)

        managed_user_ids = {u.user_id for u in managed_users}
        if user_id not in managed_user_ids:
            return {"success": False, "message": "User is not managed by you"}

        # Get target user for audit context
        target_user = next((u for u in managed_users if u.user_id == user_id), None)

        # Disable the user
        if hasattr(state.user_repo, "disable_user_by_id"):
            state.user_repo.disable_user_by_id(user_id)
        elif hasattr(state.user_repo, "disable_user"):
            state.user_repo.disable_user(user_id)

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="team_user_disabled",
                target_user_id=user_id,
                detail=f"Manager disabled team member {target_user.username if target_user else user_id[:12]}",
            )

        return {"success": True, "message": "User disabled successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/my-team/{user_id}/assign-temp-password")
async def assign_team_member_temp_password(
    user_id: str,
    user: User = Depends(require_manager_or_above),
    state: Any = Depends(get_api_state),
) -> dict:
    """Assign a temporary password to a managed user.
    
    Generates a random password, updates the user's credentials, marks password
    reset required, and returns the temp password to the manager (shown once).
    Audit logs the action WITHOUT storing the password or hash.
    """
    import secrets
    import string
    from pulldb.auth.password import hash_password
    
    # Prevent self-modification
    if user_id == user.user_id:
        return {"success": False, "message": "Cannot modify your own account"}
    
    # Verify user is managed by this manager
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)
    
    managed_user_ids = {u.user_id for u in managed_users}
    if user_id not in managed_user_ids:
        return {"success": False, "message": "User is not managed by you"}
    
    # Get target user
    target_user = next((u for u in managed_users if u.user_id == user_id), None)
    if not target_user:
        return {"success": False, "message": "User not found"}
    
    # Generate random password (12 chars, mix of letters/digits/symbols)
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
    
    # Hash and set the password
    password_hash = hash_password(temp_password)
    if hasattr(state.auth_repo, "set_password_hash"):
        state.auth_repo.set_password_hash(user_id, password_hash)
    else:
        return {"success": False, "message": "Cannot set password"}
    
    # Mark for password reset on next login
    if hasattr(state.auth_repo, "mark_password_reset"):
        state.auth_repo.mark_password_reset(user_id)
    
    # Audit log - DO NOT log password or hash, only actor/target/timestamp
    if hasattr(state, "audit_repo") and state.audit_repo:
        state.audit_repo.log_action(
            actor_user_id=user.user_id,
            action="team_temp_password_assigned",
            target_user_id=user_id,
            detail=f"Manager assigned temporary password to {target_user.username}",
        )
    
    return {
        "success": True,
        "message": "Temporary password assigned",
        "temp_password": temp_password,
        "username": target_user.username,
    }


# =============================================================================
# Team Member Host Assignment Routes
# =============================================================================


def _get_managed_user_ids(state: Any, manager_user_id: str) -> set[str]:
    """Get set of user IDs managed by this manager."""
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(manager_user_id)
    return {u.user_id for u in managed_users}


@router.get("/api/hosts")
async def api_manager_hosts_list(
    state: Any = Depends(get_api_state),
    user: User = Depends(require_manager_or_above),
) -> dict:
    """Get database hosts available to this manager.

    Managers can only assign hosts they themselves are authorized to use.
    This prevents privilege escalation.
    """
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        all_hosts = state.host_repo.list_hosts()
        # Filter to only hosts the manager can use
        manager_allowed = set(user.allowed_hosts or [])
        hosts = [
            h for h in all_hosts
            if h.hostname in manager_allowed
        ]

    return {
        "success": True,
        "hosts": [
            {
                "id": str(h.id),
                "hostname": h.hostname,
                "host_alias": getattr(h, "host_alias", None),
                "display_name": getattr(h, "host_alias", None) or h.hostname,
                "enabled": getattr(h, "enabled", True),
            }
            for h in hosts
        ],
    }


@router.get("/my-team/{user_id}/hosts")
async def get_team_member_hosts(
    user_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_manager_or_above),
) -> dict:
    """Get database hosts assigned to a managed team member."""
    # Verify user is managed by this manager
    managed_user_ids = _get_managed_user_ids(state, user.user_id)
    if user_id not in managed_user_ids:
        return {"success": False, "message": "User is not managed by you"}

    if not hasattr(state.auth_repo, "get_user_hosts"):
        return {"success": False, "message": "Host assignment not supported"}

    try:
        hosts = state.auth_repo.get_user_hosts(user_id)
        host_ids = [h[0] for h in hosts]
        default_host_id = None
        for h in hosts:
            if h[2]:  # is_default
                default_host_id = h[0]
                break

        return {
            "success": True,
            "host_ids": host_ids,
            "default_host_id": default_host_id,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/my-team/{user_id}/hosts")
async def set_team_member_hosts(
    user_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_manager_or_above),
) -> dict:
    """Set database hosts for a managed team member.

    Managers can only assign hosts they themselves are authorized to use.
    """
    # Verify user is managed by this manager
    managed_user_ids = _get_managed_user_ids(state, user.user_id)
    if user_id not in managed_user_ids:
        return {"success": False, "message": "User is not managed by you"}

    if not hasattr(state.auth_repo, "set_user_hosts"):
        return {"success": False, "message": "Host assignment not supported"}

    try:
        body = await request.json()
        host_ids: list[str] = body.get("host_ids", [])
        default_host_id: str | None = body.get("default_host_id")

        # Validate default is in host_ids if provided
        if default_host_id and default_host_id not in host_ids:
            return {"success": False, "message": "Default host must be in assigned hosts"}

        # Validate all hosts exist, are enabled, AND the manager is authorized
        if host_ids and hasattr(state, "host_repo") and state.host_repo:
            all_hosts = state.host_repo.list_hosts()
            host_map = {str(h.id): h for h in all_hosts}
            manager_allowed = set(user.allowed_hosts or [])

            for host_id in host_ids:
                host = host_map.get(host_id)
                if not host:
                    return {"success": False, "message": f"Host '{host_id}' not found"}
                if not host.enabled:
                    display = getattr(host, "host_alias", None) or host.hostname
                    return {"success": False, "message": f"Cannot assign inactive host '{display}'"}
                if host.hostname not in manager_allowed:
                    display = getattr(host, "host_alias", None) or host.hostname
                    return {"success": False, "message": f"You are not authorized to assign host '{display}'"}

            # Validate default host is enabled if provided
            if default_host_id:
                default_host = host_map.get(default_host_id)
                if default_host and not default_host.enabled:
                    display = getattr(default_host, "host_alias", None) or default_host.hostname
                    return {"success": False, "message": f"Cannot set inactive host '{display}' as default"}

        state.auth_repo.set_user_hosts(
            user_id=user_id,
            host_ids=host_ids,
            default_host_id=default_host_id,
            assigned_by=user.user_id,
        )

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            target_user = None
            if hasattr(state.user_repo, "get_user_by_id"):
                target_user = state.user_repo.get_user_by_id(user_id)

            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="team_hosts_updated",
                target_user_id=user_id,
                detail=f"Manager updated host assignments for {target_user.username if target_user else user_id[:12]}",
                context={
                    "host_ids": host_ids,
                    "default_host_id": default_host_id,
                },
            )

        return {"success": True, "message": "Host assignments updated"}
    except Exception as e:
        return {"success": False, "message": str(e)}