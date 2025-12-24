"""Admin routes for Web2 interface."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pulldb.domain.models import JobStatus, User
from pulldb.web.dependencies import get_api_state, require_admin, templates
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

router = APIRouter(prefix="/web/admin", tags=["web-admin"])


@router.get("/styleguide", response_class=HTMLResponse)
async def styleguide_page(
    request: Request,
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Render the component style guide page (admin-only)."""
    return templates.TemplateResponse(
        "features/admin/styleguide.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "breadcrumbs": get_breadcrumbs("admin_styleguide"),
        },
    )


@router.get("/", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    prune_success: int | None = None,
    prune_jobs: int | None = None,
    prune_error: str | None = None,
) -> HTMLResponse:
    """Render the admin page."""
    # Build flash message from query params (set by prune redirect)
    flash_message = None
    flash_type = None
    if prune_success is not None and prune_jobs is not None:
        flash_message = f"Successfully deleted {prune_success} events from {prune_jobs} job(s)"
        flash_type = "success"
    elif prune_error:
        flash_message = f"Prune failed: {prune_error}"
        flash_type = "error"

    # Gather stats
    users = []
    if hasattr(state.user_repo, "list_users"):
        users = state.user_repo.list_users()

    hosts = []
    if (
        hasattr(state, "host_repo")
        and state.host_repo
        and hasattr(state.host_repo, "list_hosts")
    ):
        hosts = state.host_repo.list_hosts()

    # Get job counts
    active_jobs = []
    if hasattr(state.job_repo, "get_active_jobs"):
        active_jobs = state.job_repo.get_active_jobs()

    stats = {
        "total_users": len(users),
        "admin_users": len([u for u in users if u.is_admin]),
        "total_hosts": len(hosts),
        "enabled_hosts": len([h for h in hosts if getattr(h, "enabled", True)]),
        "active_jobs": len(active_jobs),
        "running_jobs": len([j for j in active_jobs if j.status == JobStatus.RUNNING]),
        "pending_jobs": len([j for j in active_jobs if j.status == JobStatus.QUEUED]),
    }

    return templates.TemplateResponse(
        "features/admin/admin.html",
        {
            "request": request,
            "active_nav": "admin",
            "stats": stats,
            "user": user,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "breadcrumbs": get_breadcrumbs("admin"),
        },
    )


def _enrich_user(user_obj: Any, job_repo: Any) -> dict:
    """Enrich user object with computed fields for template.
    
    Adds: active_jobs, total_jobs, disabled (bool from disabled_at)
    """
    active_jobs = 0
    total_jobs = 0
    
    if job_repo:
        if hasattr(job_repo, "get_active_jobs"):
            active_jobs_list = job_repo.get_active_jobs()
            active_jobs = len([j for j in active_jobs_list 
                              if getattr(j, "owner_user_code", None) == user_obj.user_code])
        if hasattr(job_repo, "count_jobs_by_user"):
            total_jobs = job_repo.count_jobs_by_user(user_obj.user_code)
    
    return {
        "user_id": user_obj.user_id,
        "username": user_obj.username,
        "user_code": user_obj.user_code,
        "is_admin": user_obj.is_admin,
        "role": user_obj.role,
        "manager_id": getattr(user_obj, "manager_id", None),
        "created_at": user_obj.created_at,
        "disabled_at": user_obj.disabled_at,
        "allowed_hosts": getattr(user_obj, "allowed_hosts", None),
        "default_host": getattr(user_obj, "default_host", None),
        # Computed fields
        "active_jobs": active_jobs,
        "total_jobs": total_jobs,
        "disabled": user_obj.disabled_at is not None,
    }


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Render the users management page with LazyTable."""
    # Get stats and managers for the page
    raw_users = []
    if hasattr(state.user_repo, "list_users"):
        raw_users = state.user_repo.list_users()
    
    # Convert managers to simple dicts for JSON serialization
    managers = [
        {"user_id": u.user_id, "username": u.username}
        for u in raw_users 
        if u.role.value in ("manager", "admin")
    ]
    
    stats = {
        "total": len(raw_users),
        "admins": len([u for u in raw_users if u.role.value == "admin"]),
        "managers": len([u for u in raw_users if u.role.value == "manager"]),
        "active": len([u for u in raw_users if not u.disabled_at]),
        "disabled": len([u for u in raw_users if u.disabled_at]),
    }

    return templates.TemplateResponse(
        "features/admin/users.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "stats": stats,
            "managers": managers,
            "breadcrumbs": get_breadcrumbs("admin_users"),
        },
    )


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Enable a user account. Returns JSON for AJAX calls."""
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot modify your own account"}
    
    try:
        if hasattr(state.user_repo, "enable_user_by_id"):
            state.user_repo.enable_user_by_id(user_id)
        return {"success": True, "message": "User enabled"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Disable a user account. Returns JSON for AJAX calls."""
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot disable your own account"}
    
    try:
        if hasattr(state.user_repo, "disable_user_by_id"):
            state.user_repo.disable_user_by_id(user_id)
        return {"success": True, "message": "User disabled"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    new_role: str = Form(...),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Update a user's role. Returns JSON for AJAX calls."""
    from pulldb.domain.models import UserRole
    
    # Prevent self-modification
    if user_id == user.user_id:
        return {"success": False, "message": "Cannot modify your own role"}
    
    try:
        role_enum = UserRole(new_role.lower())
        if hasattr(state.user_repo, "update_user_role"):
            state.user_repo.update_user_role(user_id, role_enum)
        return {"success": True, "message": "Role updated"}
    except ValueError:
        return {"success": False, "message": "Invalid role"}


@router.post("/users/add")
async def add_user(
    username: str = Form(...),
    role: str = Form("user"),
    manager_id: str = Form(None),
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Create a new user with random password. Returns JSON with password."""
    import secrets
    import string
    from pulldb.auth.password import hash_password
    from pulldb.domain.models import UserRole
    
    # Validate username format
    username = username.strip().lower()
    if not username or len(username) < 3 or len(username) > 50:
        return {"success": False, "message": "Username must be 3-50 characters"}
    
    import re
    if not re.match(r'^[a-z0-9_-]+$', username):
        return {"success": False, "message": "Username can only contain lowercase letters, numbers, underscore, and hyphen"}
    
    # Check if username already exists
    existing = None
    if hasattr(state.user_repo, "get_user_by_username"):
        existing = state.user_repo.get_user_by_username(username)
    if existing:
        return {"success": False, "message": f"Username '{username}' already exists"}
    
    # Generate user code
    user_code = username[:6].upper()
    if hasattr(state.user_repo, "generate_user_code"):
        user_code = state.user_repo.generate_user_code(username)
    
    # Create user
    actual_manager_id = manager_id if manager_id else None
    new_user = None
    if hasattr(state.user_repo, "create_user"):
        new_user = state.user_repo.create_user(username, user_code, actual_manager_id)
    
    if not new_user:
        return {"success": False, "message": "Failed to create user"}
    
    # Set role if not default 'user'
    if role != "user":
        try:
            role_enum = UserRole(role.lower())
            if hasattr(state.user_repo, "update_user_role"):
                state.user_repo.update_user_role(new_user.user_id, role_enum)
        except ValueError:
            pass  # Invalid role, keep default
    
    # Generate random password (12 chars, mix of letters/digits/symbols)
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    random_password = ''.join(secrets.choice(alphabet) for _ in range(12))
    
    # Set password hash
    password_hash = hash_password(random_password)
    if hasattr(state.auth_repo, "set_password_hash"):
        state.auth_repo.set_password_hash(new_user.user_id, password_hash)
    
    # Mark for password reset on first login
    if hasattr(state.auth_repo, "mark_password_reset"):
        state.auth_repo.mark_password_reset(new_user.user_id)
    
    return {
        "success": True,
        "message": "User created successfully",
        "user_id": new_user.user_id,
        "username": username,
        "user_code": user_code,
        "password": random_password,
    }


@router.post("/users/{user_id}/manager")
async def update_user_manager(
    user_id: str,
    manager_id: str = Form(None),
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Update a user's manager assignment. Returns JSON for AJAX calls."""
    if hasattr(state.user_repo, "set_user_manager"):
        actual_manager_id = manager_id if manager_id else None
        state.user_repo.set_user_manager(user_id, actual_manager_id)
        return {"success": True, "message": "Manager updated"}
    return {"success": True, "message": "Manager updated (simulation)"}


@router.post("/users/{user_id}/force-password-reset")
async def force_password_reset(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Force a password reset for a user. Returns JSON for AJAX calls."""
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot modify your own account"}
    
    # Get the user to find their username
    target_user = None
    if hasattr(state.user_repo, "get_user_by_id"):
        target_user = state.user_repo.get_user_by_id(user_id)
    
    if target_user and hasattr(state.auth_repo, "mark_password_reset"):
        state.auth_repo.mark_password_reset(target_user.user_id)
        return {"success": True, "message": "Password reset required on next login"}
    return {"success": False, "message": "Could not set password reset"}


@router.post("/users/{user_id}/clear-password-reset")
async def clear_password_reset(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Clear a pending password reset for a user. Returns JSON for AJAX calls."""
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot modify your own account"}
    
    # Get the user to find their username
    target_user = None
    if hasattr(state.user_repo, "get_user_by_id"):
        target_user = state.user_repo.get_user_by_id(user_id)
    
    if target_user and hasattr(state.auth_repo, "clear_password_reset"):
        state.auth_repo.clear_password_reset(target_user.user_id)
        return {"success": True, "message": "Password reset cleared"}
    return {"success": False, "message": "Could not clear password reset"}


# =============================================================================
# User Host Assignment Routes
# =============================================================================

@router.get("/users/{user_id}/hosts")
async def get_user_hosts(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Get database hosts assigned to a user. Returns JSON for AJAX calls."""
    if not hasattr(state.auth_repo, "get_user_hosts"):
        return {"success": False, "message": "Host assignment not supported"}
    
    try:
        # Returns list of (host_id, hostname, is_default)
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


@router.post("/users/{user_id}/hosts")
async def set_user_hosts(
    user_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Set database hosts for a user. Accepts JSON body. Returns JSON for AJAX calls."""
    if not hasattr(state.auth_repo, "set_user_hosts"):
        return {"success": False, "message": "Host assignment not supported"}
    
    try:
        body = await request.json()
        host_ids: list[str] = body.get("host_ids", [])
        default_host_id: str | None = body.get("default_host_id")
        
        # Validate default is in host_ids if provided
        if default_host_id and default_host_id not in host_ids:
            return {"success": False, "message": "Default host must be in assigned hosts"}
        
        # Validate all hosts exist and are active (enabled)
        if host_ids and hasattr(state, "host_repo") and state.host_repo:
            all_hosts = state.host_repo.list_hosts()
            host_map = {str(h.id): h for h in all_hosts}
            
            for host_id in host_ids:
                host = host_map.get(host_id)
                if not host:
                    return {"success": False, "message": f"Host '{host_id}' not found"}
                if not host.enabled:
                    display = getattr(host, "host_alias", None) or host.hostname
                    return {"success": False, "message": f"Cannot assign inactive host '{display}'"}
            
            # Validate default host is active if provided
            if default_host_id:
                default_host = host_map.get(default_host_id)
                if default_host and not default_host.enabled:
                    display = getattr(default_host, "host_alias", None) or default_host.hostname
                    return {"success": False, "message": f"Cannot set inactive host '{display}' as default"}
        
        state.auth_repo.set_user_hosts(
            user_id=user_id,
            host_ids=host_ids,
            default_host_id=default_host_id,
            assigned_by=admin.user_id,
        )
        
        return {"success": True, "message": "Host assignments updated"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/api/hosts")
async def api_hosts_list(
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Get all database hosts for admin UI. Returns JSON."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        hosts = state.host_repo.list_hosts()
    
    return {
        "success": True,
        "hosts": [
            {
                "id": str(h.id),  # Explicit string for JSON consistency
                "hostname": h.hostname,
                "host_alias": getattr(h, "host_alias", None),
                "display_name": getattr(h, "host_alias", None) or h.hostname,
                "enabled": getattr(h, "enabled", True),
            }
            for h in hosts
        ],
    }


@router.get("/api/users")
async def api_users_paginated(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict:
    """Get paginated users for LazyTable."""
    raw_users = []
    if hasattr(state.user_repo, "list_users"):
        raw_users = state.user_repo.list_users()
    
    user_map = {u.user_id: u for u in raw_users}
    
    # Get active job counts
    job_counts: dict[str, int] = {}
    if hasattr(state.job_repo, "get_active_jobs"):
        for job in state.job_repo.get_active_jobs():
            code = getattr(job, "owner_user_code", None)
            if code:
                job_counts[code] = job_counts.get(code, 0) + 1
    
    # Get managers for dropdown
    managers = [u for u in raw_users if u.role.value in ("manager", "admin")]
    
    # Build enriched user list
    all_users = []
    for u in raw_users:
        manager_username = None
        if u.manager_id and u.manager_id in user_map:
            manager_username = user_map[u.manager_id].username
        
        # Check password reset status
        password_reset_pending = False
        if hasattr(state, "auth_repo") and hasattr(state.auth_repo, "is_password_reset_required"):
            password_reset_pending = state.auth_repo.is_password_reset_required(u.user_id)
        
        all_users.append({
            "user_id": u.user_id,
            "username": u.username,
            "user_code": u.user_code,
            "role": u.role.value,
            "manager_id": u.manager_id,
            "manager_username": manager_username,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "disabled": u.disabled_at is not None,
            "password_reset_pending": password_reset_pending,
            "active_jobs": job_counts.get(u.user_code, 0),
        })
    
    total_count = len(all_users)
    
    # Compute stats before filtering (for real-time stat pill updates)
    stats = {
        "total": total_count,
        "admins": len([u for u in all_users if u["role"] == "admin"]),
        "managers": len([u for u in all_users if u["role"] == "manager"]),
        "active": len([u for u in all_users if not u["disabled"]]),
        "disabled": len([u for u in all_users if u["disabled"]]),
    }
    
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
                if col == "status":
                    status = "disabled" if u["disabled"] else "enabled"
                    if not any(v in status for v in vals):
                        match = False
                        break
                else:
                    cell = str(u.get(col, "")).lower()
                    if not any(v in cell for v in vals):
                        match = False
                        break
            if match:
                filtered.append(u)
        all_users = filtered
    
    filtered_count = len(all_users)
    
    # Apply sorting
    if sortColumn in ("username", "user_code", "role", "manager_username", "created_at", "disabled"):
        reverse = sortDirection == "desc"
        all_users.sort(
            key=lambda u: (u.get(sortColumn) is None, str(u.get(sortColumn) or "").lower()),
            reverse=reverse
        )
    
    # Paginate
    start = page * pageSize
    page_users = all_users[start:start + pageSize]
    
    return {
        "rows": page_users,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "page": page,
        "pageSize": pageSize,
        "managers": [{"user_id": m.user_id, "username": m.username} for m in managers],
        "stats": stats,
    }


@router.get("/api/users/distinct")
async def api_users_distinct(
    request: Request,
    column: str,
    filter_order: str | None = None,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> list:
    """Get distinct values for user filter dropdowns.
    
    Supports cascading filters:
    - If column is NOT in filter_order: apply ALL filters
    - If column IS in filter_order: only apply filters preceding it
    """
    from pulldb.infra.filter_utils import parse_multi_value_filter
    
    raw_users = []
    if hasattr(state.user_repo, "list_users"):
        raw_users = state.user_repo.list_users()
    
    user_map = {u.user_id: u for u in raw_users}
    
    # Parse filter order and determine which filters should apply
    order_list = [c.strip() for c in filter_order.split(",") if c.strip()] if filter_order else []
    column_in_order = column in order_list
    column_idx = order_list.index(column) if column_in_order else -1
    
    # If column is in order, only apply prior filters; otherwise apply ALL filters
    if column_in_order:
        applicable_cols = set(order_list[:column_idx]) if column_idx > 0 else set()
    else:
        applicable_cols = set(order_list)
    
    # Extract filter params from request
    filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value and key != "filter_order":
            col_key = key[7:]
            if col_key in applicable_cols:
                filters[col_key] = parse_multi_value_filter(value)
    
    # Build user dicts for filtering
    users_data = []
    for u in raw_users:
        manager_username = ""
        if u.manager_id and u.manager_id in user_map:
            manager_username = user_map[u.manager_id].username
        users_data.append({
            "username": u.username,
            "user_code": u.user_code,
            "role": u.role.value,
            "status": "disabled" if u.disabled_at else "enabled",
            "manager_username": manager_username,
            "_user": u,  # Keep reference to original
        })
    
    # Apply cascading filters
    if filters:
        filtered = []
        for ud in users_data:
            match = True
            for col_key, filter_vals in filters.items():
                cell_val = str(ud.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            if match:
                filtered.append(ud)
        users_data = filtered
    
    # Collect distinct values
    values = set()
    for ud in users_data:
        if column == "role":
            values.add(ud["role"])
        elif column == "status":
            values.add(ud["status"])
        elif column == "manager_username":
            if ud["manager_username"]:
                values.add(ud["manager_username"])
        elif column == "username":
            values.add(ud["username"])
        elif column == "user_code":
            values.add(ud["user_code"])
    
    return sorted(values)


# =============================================================================
# Hosts Management
# =============================================================================

def _enrich_host(host: Any, job_repo: Any) -> dict:
    """Enrich host object with computed fields for template.
    
    Adds: running_count, queued_count, active_restores, total_restores
    """
    # Get job counts for this host
    running_count = 0
    queued_count = 0
    total_restores = 0
    
    if job_repo and hasattr(job_repo, "get_active_jobs"):
        active_jobs = job_repo.get_active_jobs()
        for job in active_jobs:
            if getattr(job, "dbhost", None) == host.hostname:
                if job.status == JobStatus.RUNNING:
                    running_count += 1
                elif job.status == JobStatus.QUEUED:
                    queued_count += 1
    
    if job_repo and hasattr(job_repo, "count_jobs_by_host"):
        total_restores = job_repo.count_jobs_by_host(host.hostname)
    
    return {
        "id": host.id,
        "hostname": host.hostname,
        "host_alias": getattr(host, "host_alias", None),
        "credential_ref": getattr(host, "credential_ref", None),
        "max_running_jobs": getattr(host, "max_running_jobs", 1),
        "max_active_jobs": getattr(host, "max_active_jobs", 10),
        "enabled": getattr(host, "enabled", True),
        "created_at": getattr(host, "created_at", None),
        # Computed fields
        "running_count": running_count,
        "queued_count": queued_count,
        "active_restores": running_count,  # Same as running_count
        "total_restores": total_restores,
    }


@router.get("/api/hosts/paginated")
async def api_hosts_paginated(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict:
    """Get paginated hosts for LazyTable."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        raw_hosts = state.host_repo.list_hosts()
        hosts = [_enrich_host(h, state.job_repo) for h in raw_hosts]
    
    total_count = len(hosts)
    
    # Compute stats before filtering
    stats = {
        "total": total_count,
        "enabled": len([h for h in hosts if h["enabled"]]),
        "disabled": len([h for h in hosts if not h["enabled"]]),
        "active_restores": sum(h["active_restores"] for h in hosts),
    }
    
    # Serialize hosts for JSON (convert datetime)
    all_hosts = []
    for h in hosts:
        all_hosts.append({
            "id": str(h["id"]),
            "hostname": h["hostname"],
            "host_alias": h["host_alias"],
            "display_name": h["host_alias"] or h["hostname"],
            "credential_ref": h["credential_ref"],
            "max_running_jobs": h["max_running_jobs"],
            "max_active_jobs": h["max_active_jobs"],
            "enabled": h["enabled"],
            "created_at": h["created_at"].isoformat() if h["created_at"] else None,
            "running_count": h["running_count"],
            "queued_count": h["queued_count"],
            "active_restores": h["active_restores"],
            "total_restores": h["total_restores"],
        })
    
    # Apply filters
    text_filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]
    
    if text_filters:
        filtered = []
        for h in all_hosts:
            match = True
            for col, vals in text_filters.items():
                if col == "status":
                    status = "enabled" if h["enabled"] else "disabled"
                    if not any(v in status for v in vals):
                        match = False
                        break
                elif col == "hostname":
                    # Search both hostname and alias
                    combined = f"{h['hostname']} {h['host_alias'] or ''}".lower()
                    if not any(v in combined for v in vals):
                        match = False
                        break
                else:
                    cell = str(h.get(col, "")).lower()
                    if not any(v in cell for v in vals):
                        match = False
                        break
            if match:
                filtered.append(h)
        all_hosts = filtered
    
    filtered_count = len(all_hosts)
    
    # Apply sorting
    sortable_cols = ("display_name", "hostname", "enabled", "running_count", "active_restores", "total_restores", "created_at")
    if sortColumn in sortable_cols:
        reverse = sortDirection == "desc"
        if sortColumn in ("running_count", "active_restores", "total_restores"):
            all_hosts.sort(key=lambda h: h.get(sortColumn) or 0, reverse=reverse)
        else:
            all_hosts.sort(
                key=lambda h: (h.get(sortColumn) is None, str(h.get(sortColumn) or "").lower()),
                reverse=reverse
            )
    
    # Paginate
    start = page * pageSize
    page_hosts = all_hosts[start:start + pageSize]
    
    return {
        "rows": page_hosts,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "page": page,
        "pageSize": pageSize,
        "stats": stats,
    }


@router.get("/hosts", response_class=HTMLResponse)
async def list_hosts(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    error: str | None = None,
    deleted: int | None = None,
) -> HTMLResponse:
    """List all database hosts - page shell for LazyTable."""
    # Get initial stats for server-side render
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        raw_hosts = state.host_repo.list_hosts()
        hosts = [_enrich_host(h, state.job_repo) for h in raw_hosts]
    
    stats = {
        "total": len(hosts),
        "enabled": len([h for h in hosts if h["enabled"]]),
        "disabled": len([h for h in hosts if not h["enabled"]]),
        "active_restores": sum(h["active_restores"] for h in hosts),
    }

    # Build flash message
    flash_message = None
    flash_type = None
    if deleted:
        flash_message = "Host disabled successfully"
        flash_type = "success"
    elif error:
        flash_message = error
        flash_type = "error"
    
    return templates.TemplateResponse(
        "features/admin/hosts.html",
        {
            "request": request,
            "active_nav": "admin",
            "stats": stats,
            "user": user,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "aws_create_secret_url": get_secrets_manager_create_url(),
            "breadcrumbs": get_breadcrumbs("admin_hosts"),
        },
    )


@router.post("/hosts/{hostname}/enable")
async def enable_host(
    hostname: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Enable a database host (form POST redirect)."""
    if hasattr(state.host_repo, "enable_host"):
        state.host_repo.enable_host(hostname)
    return RedirectResponse(url="/web/admin/hosts", status_code=303)


@router.post("/hosts/{hostname}/disable")
async def disable_host(
    hostname: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Disable a database host."""
    if hasattr(state.host_repo, "disable_host"):
        state.host_repo.disable_host(hostname)
    return RedirectResponse(url="/web/admin/hosts", status_code=303)


@router.post("/api/hosts/{host_id}/toggle")
async def api_toggle_host(
    host_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Toggle host enabled/disabled status. Returns JSON for LazyTable actions."""
    try:
        # Find host by ID
        host = None
        if hasattr(state, "host_repo") and state.host_repo:
            if hasattr(state.host_repo, "get_host_by_id"):
                host = state.host_repo.get_host_by_id(host_id)
        
        if not host:
            return {"success": False, "message": "Host not found"}
        
        # Toggle status
        if getattr(host, "enabled", True):
            if hasattr(state.host_repo, "disable_host"):
                state.host_repo.disable_host(host.hostname)
            return {"success": True, "message": f"Host '{host.hostname}' disabled", "enabled": False}
        else:
            if hasattr(state.host_repo, "enable_host"):
                state.host_repo.enable_host(host.hostname)
            return {"success": True, "message": f"Host '{host.hostname}' enabled", "enabled": True}
    except Exception as e:
        return {"success": False, "message": str(e)}


# =============================================================================
# Host Management - Add, Edit, Delete, Test Connection
# =============================================================================

import os
import uuid
from urllib.parse import quote as url_quote


def get_aws_region() -> str:
    """Get AWS region using pullDB's established fallback chain."""
    return (
        os.getenv("PULLDB_AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def get_secrets_manager_console_url(secret_path: str, region: str | None = None) -> str:
    """Build AWS Secrets Manager console URL for a secret.

    Args:
        secret_path: The secret path (e.g., "/pulldb/mysql/dev-db-01").
        region: AWS region. If None, uses fallback chain.

    Returns:
        Console URL to view/edit the secret.
    """
    region = region or get_aws_region()
    encoded_path = url_quote(secret_path, safe="")
    return f"https://{region}.console.aws.amazon.com/secretsmanager/secret?name={encoded_path}&region={region}"


def get_secrets_manager_create_url(region: str | None = None) -> str:
    """Build AWS Secrets Manager console URL for creating a new secret.

    Args:
        region: AWS region. If None, uses fallback chain.

    Returns:
        Console URL to create a new secret.
    """
    region = region or get_aws_region()
    return f"https://{region}.console.aws.amazon.com/secretsmanager/newsecret?region={region}"


@router.post("/hosts/add")
async def add_host(
    request: Request,
    hostname: str = Form(...),
    host_alias: str = Form(None),
    credential_ref: str = Form(...),
    max_running_jobs: int = Form(1),
    max_active_jobs: int = Form(10),
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    """Add a new database host."""
    try:
        # Validate limits
        if max_running_jobs < 1:
            raise ValueError("max_running_jobs must be at least 1")
        if max_active_jobs < 1:
            raise ValueError("max_active_jobs must be at least 1")
        if max_running_jobs > max_active_jobs:
            raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        # Generate UUID for new host
        host_id = str(uuid.uuid4())

        # Insert via repository
        if hasattr(state, "host_repo") and state.host_repo:
            state.host_repo.add_host(
                hostname=hostname,
                max_concurrent=max_running_jobs,  # Legacy param
                credential_ref=credential_ref,
                host_id=host_id,
                host_alias=host_alias or None,
                max_running_jobs=max_running_jobs,
                max_active_jobs=max_active_jobs,
            )

        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?added=1", status_code=303
        )
    except Exception as e:
        # On error, redirect back to hosts list with error message
        error_msg = url_quote(str(e))
        return RedirectResponse(
            url=f"/web/admin/hosts?error={error_msg}", status_code=303
        )


@router.get("/hosts/{host_id}", response_class=HTMLResponse)
async def host_detail(
    host_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    added: int | None = None,
    updated: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Render host detail/edit page."""
    from pulldb.infra.secrets import CredentialResolver, CredentialResolutionError

    # Get host by ID using repository method
    host_obj = None
    if hasattr(state, "host_repo") and state.host_repo:
        if hasattr(state.host_repo, "get_host_by_id"):
            host_obj = state.host_repo.get_host_by_id(host_id)

    if not host_obj:
        return templates.TemplateResponse(
            "errors/404.html",
            {"request": request, "user": user, "message": "Host not found"},
            status_code=404,
        )

    # Convert DBHost to dict for template
    from dataclasses import asdict
    host = asdict(host_obj)

    # Enrich host with computed fields
    enriched_host = _enrich_host_detail(host, state)

    # Build flash message
    flash_message = None
    flash_type = None
    if added:
        flash_message = "Host added successfully"
        flash_type = "success"
    elif updated:
        flash_message = "Host updated successfully"
        flash_type = "success"
    elif error:
        flash_message = error
        flash_type = "error"

    return templates.TemplateResponse(
        "features/admin/host_detail.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "host": enriched_host,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "aws_create_secret_url": get_secrets_manager_create_url(),
            "breadcrumbs": get_breadcrumbs("admin_host_detail", host=enriched_host.get("hostname", "Host")),
        },
    )


def _enrich_host_detail(host: dict, state: Any) -> dict:
    """Enrich host dict with computed fields for detail template."""
    from pulldb.infra.secrets import CredentialResolver, CredentialResolutionError

    # Get job counts
    running_count = 0
    queued_count = 0
    total_restores = 0

    if state.job_repo and hasattr(state.job_repo, "get_active_jobs"):
        active_jobs = state.job_repo.get_active_jobs()
        for job in active_jobs:
            if getattr(job, "dbhost", None) == host["hostname"]:
                if job.status == JobStatus.RUNNING:
                    running_count += 1
                elif job.status == JobStatus.QUEUED:
                    queued_count += 1

    if state.job_repo and hasattr(state.job_repo, "count_jobs_by_host"):
        total_restores = state.job_repo.count_jobs_by_host(host["hostname"])

    # Resolve credential_ref to get actual host URI
    resolved_host_uri = None
    credential_error = None
    secret_path = None
    aws_secret_url = None

    credential_ref = host.get("credential_ref")
    if credential_ref:
        try:
            resolver = CredentialResolver()
            secret_path = resolver.get_secret_path(credential_ref)
            if secret_path:
                aws_secret_url = get_secrets_manager_console_url(secret_path)

            # Try to resolve credentials to get actual host URI
            try:
                creds = resolver.resolve(credential_ref)
                resolved_host_uri = creds.host
            except CredentialResolutionError as e:
                credential_error = str(e)
        except Exception as e:
            credential_error = str(e)

    # Get assigned users
    assigned_users = []
    # Try using pool from host_repo if available (real MySQL)
    pool = None
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "pool"):
        pool = state.host_repo.pool
    elif hasattr(state, "auth_repo") and state.auth_repo and hasattr(state.auth_repo, "pool"):
        pool = state.auth_repo.pool
    
    if pool:
        try:
            with pool.connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    """
                    SELECT u.user_id, u.username, u.user_code, uh.is_default
                    FROM user_hosts uh
                    JOIN auth_users u ON u.user_id = uh.user_id
                    WHERE uh.host_id = %s
                    ORDER BY u.username
                    """,
                    (host["id"],),
                )
                assigned_users = cursor.fetchall()
        except Exception:
            pass  # User assignment table may not exist
    elif hasattr(state, "auth_repo") and state.auth_repo:
        # For simulated mode, try get_users_for_host if available
        if hasattr(state.auth_repo, "get_users_for_host"):
            try:
                assigned_users = state.auth_repo.get_users_for_host(host["id"])
            except Exception:
                pass

    return {
        **host,
        "running_count": running_count,
        "queued_count": queued_count,
        "active_restores": running_count + queued_count,
        "total_restores": total_restores,
        "resolved_host_uri": resolved_host_uri,
        "credential_error": credential_error,
        "secret_path": secret_path,
        "aws_secret_url": aws_secret_url,
        "assigned_users": assigned_users,
    }


@router.post("/hosts/{host_id}/update")
async def update_host(
    host_id: str,
    host_alias: str = Form(None),
    credential_ref: str = Form(...),
    max_running_jobs: int = Form(1),
    max_active_jobs: int = Form(10),
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    """Update host configuration."""
    try:
        # Validate limits
        if max_running_jobs < 1:
            raise ValueError("max_running_jobs must be at least 1")
        if max_active_jobs < 1:
            raise ValueError("max_active_jobs must be at least 1")
        if max_running_jobs > max_active_jobs:
            raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        if hasattr(state, "host_repo") and state.host_repo:
            # Use update_host_config if available (simulated), else fall back to raw SQL
            if hasattr(state.host_repo, "update_host_config"):
                state.host_repo.update_host_config(
                    host_id,
                    host_alias=host_alias or None,
                    credential_ref=credential_ref,
                    max_running_jobs=max_running_jobs,
                    max_active_jobs=max_active_jobs,
                )
            else:
                # Fall back to direct database access for real repository
                with state.host_repo.pool.connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE db_hosts 
                        SET host_alias = %s, credential_ref = %s, 
                            max_running_jobs = %s, max_active_jobs = %s
                        WHERE id = %s
                        """,
                        (host_alias or None, credential_ref, max_running_jobs,
                         max_active_jobs, host_id),
                    )
                    conn.commit()
                    if cursor.rowcount == 0:
                        raise ValueError("Host not found")

        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?updated=1", status_code=303
        )
    except Exception as e:
        error_msg = url_quote(str(e))
        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?error={error_msg}", status_code=303
        )


@router.post("/hosts/{host_id}/delete")
async def delete_host(
    host_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    """Soft delete (disable) a host. Validates no active jobs exist."""
    try:
        if hasattr(state, "host_repo") and state.host_repo:
            # Get host by ID first
            host = state.host_repo.get_host_by_id(host_id)
            if not host:
                raise ValueError("Host not found")
            hostname = host.hostname

            # Check for active jobs
            if state.job_repo and hasattr(state.job_repo, "get_active_jobs"):
                active_jobs = state.job_repo.get_active_jobs()
                host_jobs = [j for j in active_jobs if getattr(j, "dbhost", None) == hostname]
                if host_jobs:
                    raise ValueError(
                        f"Cannot delete host with {len(host_jobs)} active job(s). "
                        "Wait for jobs to complete or cancel them first."
                    )

            # Soft delete by disabling
            state.host_repo.disable_host(hostname)

        return RedirectResponse(url="/web/admin/hosts?deleted=1", status_code=303)
    except Exception as e:
        error_msg = url_quote(str(e))
        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?error={error_msg}", status_code=303
        )


@router.post("/hosts/{host_id}/test-connection")
async def test_host_connection(
    host_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Test MySQL connection to a host with comprehensive pre-flight checks.
    
    Returns JSON with connection status and setup validation:
    - credential_valid: AWS secret exists and contains required fields
    - connection_valid: Can connect to MySQL server
    - sproc_valid: pulldb_atomic_rename procedure exists
    - pulldb_db_valid: pulldb database exists
    """
    from pulldb.infra.secrets import CredentialResolver, CredentialResolutionError
    import mysql.connector

    checks: dict[str, bool | str] = {
        "credential_valid": False,
        "credential_message": "",
        "connection_valid": False,
        "connection_message": "",
        "pulldb_db_valid": False,
        "pulldb_db_message": "",
        "sproc_valid": False,
        "sproc_message": "",
    }
    result: dict[str, Any] = {
        "success": False,
        "message": "",
        "checks": checks,
    }

    try:
        # Get host using repository method
        host_obj = None
        if hasattr(state, "host_repo") and state.host_repo:
            host_obj = state.host_repo.get_host_by_id(host_id)

        if not host_obj:
            result["message"] = "Host not found"
            return result

        # Detect simulation mode (mock credentials)
        is_mock = host_obj.credential_ref.startswith("mock/")
        if is_mock:
            # Return simulated success with transparent messaging
            result["success"] = True
            result["message"] = "Simulation mode - all checks simulated"
            result["simulation_mode"] = True
            result["checks"] = {
                "credential_valid": True,
                "credential_message": "Mock credentials (simulation mode)",
                "connection_valid": True,
                "connection_message": "Simulated connection - no actual MySQL call",
                "pulldb_db_valid": True,
                "pulldb_db_message": "Simulated - pulldb database assumed present",
                "sproc_valid": True,
                "sproc_message": "Simulated - stored procedure assumed deployed",
            }
            return result

        # Check 1: Resolve credentials
        resolver = CredentialResolver()
        creds = None
        try:
            creds = resolver.resolve(host_obj.credential_ref)
            checks["credential_valid"] = True
            checks["credential_message"] = "AWS secret resolved successfully"
        except CredentialResolutionError as e:
            checks["credential_message"] = f"Credential error: {e}"
            result["message"] = "Credential resolution failed"
            return result

        # Check 2: MySQL connection
        test_conn = None
        try:
            test_conn = mysql.connector.connect(
                host=creds.host,
                port=creds.port,
                user=creds.username or "pulldb_loader",
                password=creds.password,
                connection_timeout=5,
            )
            checks["connection_valid"] = True
            checks["connection_message"] = f"Connected to {creds.host}:{creds.port}"
        except mysql.connector.Error as e:
            checks["connection_message"] = f"Connection failed: {e}"
            result["message"] = "MySQL connection failed"
            if test_conn:
                test_conn.close()
            return result

        # Check 3: pulldb database exists
        try:
            cursor = test_conn.cursor()
            cursor.execute("SHOW DATABASES LIKE 'pulldb'")
            db_exists = cursor.fetchone()
            cursor.close()
            if db_exists:
                checks["pulldb_db_valid"] = True
                checks["pulldb_db_message"] = "pulldb database exists"
            else:
                checks["pulldb_db_message"] = "pulldb database not found - create with: CREATE DATABASE pulldb;"
        except mysql.connector.Error as e:
            checks["pulldb_db_message"] = f"Could not check database: {e}"

        # Check 4: Stored procedure exists (only if pulldb database exists)
        if checks["pulldb_db_valid"]:
            try:
                cursor = test_conn.cursor()
                cursor.execute("""
                    SELECT ROUTINE_NAME FROM information_schema.ROUTINES 
                    WHERE ROUTINE_SCHEMA = 'pulldb' 
                    AND ROUTINE_NAME = 'pulldb_atomic_rename' 
                    AND ROUTINE_TYPE = 'PROCEDURE'
                """)
                sproc_exists = cursor.fetchone()
                cursor.close()
                if sproc_exists:
                    checks["sproc_valid"] = True
                    checks["sproc_message"] = "pulldb_atomic_rename procedure found"
                else:
                    checks["sproc_message"] = "Stored procedure not found - deploy with: python scripts/deploy_atomic_rename.py"
            except mysql.connector.Error as e:
                checks["sproc_message"] = f"Could not check procedure: {e}"
        else:
            checks["sproc_message"] = "Skipped - pulldb database required first"

        test_conn.close()

        # Determine overall success
        all_valid = all([
            checks["credential_valid"],
            checks["connection_valid"],
            checks["pulldb_db_valid"],
            checks["sproc_valid"],
        ])

        if all_valid:
            result["success"] = True
            result["message"] = "All pre-flight checks passed"
        else:
            # Build message about what's missing
            missing = []
            if not checks["pulldb_db_valid"]:
                missing.append("pulldb database")
            if not checks["sproc_valid"]:
                missing.append("stored procedure")
            result["message"] = f"Connected successfully, but missing: {', '.join(missing)}"

        return result

    except Exception as e:
        result["message"] = str(e)
        return result


# =============================================================================
# Host Provisioning - Automated Setup Flow
# =============================================================================

from pydantic import BaseModel


class ProvisionHostRequest(BaseModel):
    """Request model for automated host provisioning."""
    host_alias: str
    mysql_host: str
    mysql_port: int = 3306
    admin_username: str
    admin_password: str
    max_running_jobs: int = 1
    max_active_jobs: int = 10


@router.post("/hosts/check-alias")
async def check_host_alias(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Check if a host alias exists and if credentials already exist.
    
    Returns JSON for HTMX to update status badges:
    - host_exists: Whether host with this alias is already registered
    - host_id: Existing host ID if found
    - secret_exists: Whether AWS secret exists for this alias
    - secret_path: The computed secret path
    """
    from pulldb.infra.secrets import check_secret_exists, get_secret_path_from_alias
    
    form_data = await request.form()
    host_alias_val = form_data.get("host_alias", "")
    host_alias = str(host_alias_val).strip() if host_alias_val else ""
    
    result: dict[str, Any] = {
        "host_alias": host_alias,
        "host_exists": False,
        "host_id": None,
        "secret_exists": False,
        "secret_path": None,
        "status": "new",  # new, existing, credentials_found
        "message": "",
    }
    
    if not host_alias:
        result["message"] = "Enter a host alias"
        return result
    
    # Check if host alias already exists in database
    if hasattr(state, "host_repo") and state.host_repo:
        if hasattr(state.host_repo, "get_host_by_alias"):
            existing_host = state.host_repo.get_host_by_alias(host_alias)
            if existing_host:
                result["host_exists"] = True
                result["host_id"] = existing_host.id
                result["status"] = "existing"
                result["message"] = f"Host exists (will update)"
    
    # Check if AWS secret exists for this alias
    secret_path = get_secret_path_from_alias(host_alias)
    result["secret_path"] = secret_path
    
    secret_check = check_secret_exists(secret_path)
    if secret_check.exists:
        result["secret_exists"] = True
        if not result["host_exists"]:
            result["status"] = "credentials_found"
            result["message"] = "Credentials found (will reuse)"
    
    if result["status"] == "new":
        result["message"] = "New host"
    
    return result


@router.post("/hosts/provision")
async def provision_host(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Provision a new host with automated MySQL setup.
    
    This endpoint:
    1. Checks if host alias already exists (reuses if so)
    2. Tests admin MySQL connection
    3. Creates pulldb_loader user (or updates password)
    4. Creates pulldb database if needed
    5. Deploys stored procedure
    6. Creates AWS secret (only if new, never overwrites others)
    7. Registers/updates host in database
    
    On failure, rolls back only newly-created resources:
    - Deletes AWS secret only if it was created in this operation
    - Leaves pre-existing users/databases/secrets untouched
    
    Returns JSON with step-by-step results for UI display.
    """
    from pulldb.infra.secrets import (
        check_secret_exists,
        safe_upsert_single_secret,
        delete_secret_if_new,
        generate_credential_ref,
        get_secret_path_from_alias,
    )
    from pulldb.infra.mysql_provisioning import provision_host_full
    
    # Parse form data with proper type handling
    form_data = await request.form()
    
    def get_form_str(key: str, default: str = "") -> str:
        val = form_data.get(key, default)
        return str(val).strip() if val else default
    
    def get_form_int(key: str, default: int) -> int:
        val = form_data.get(key, str(default))
        return int(str(val)) if val else default
    
    host_alias = get_form_str("host_alias")
    mysql_host = get_form_str("mysql_host")
    mysql_port = get_form_int("mysql_port", 3306)
    admin_username = get_form_str("admin_username")
    admin_password = get_form_str("admin_password")
    max_running_jobs = get_form_int("max_running_jobs", 1)
    max_active_jobs = get_form_int("max_active_jobs", 10)
    
    steps: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "success": False,
        "message": "",
        "host_id": None,
        "steps": steps,
        "rollback_performed": False,
    }
    
    def add_step(name: str, success: bool, message: str, details: str | None = None) -> None:
        steps.append({
            "name": name,
            "success": success,
            "message": message,
            "details": details,
        })
    
    # Validate inputs
    if not host_alias:
        result["message"] = "Host alias is required"
        return result
    if not mysql_host:
        result["message"] = "MySQL host is required"
        return result
    if not admin_username or not admin_password:
        result["message"] = "Admin credentials are required"
        return result
    if max_running_jobs < 1 or max_active_jobs < 1:
        result["message"] = "Job limits must be at least 1"
        return result
    if max_running_jobs > max_active_jobs:
        result["message"] = "max_running_jobs cannot exceed max_active_jobs"
        return result
    
    # Check for simulation mode
    from pulldb.infra.factory import is_simulation_mode
    
    if is_simulation_mode():
        # Simulate successful provisioning without real MySQL/AWS calls
        import uuid as uuid_module
        
        add_step("Check Host", True, f"New host '{host_alias}'")
        add_step("Check Secret", True, "No existing credentials (simulated)", 
                 f"Will create: /pulldb/mysql/{host_alias}")
        add_step("MySQL Setup", True, 
                 "User created, database exists, procedure deployed (simulated)",
                 "User: pulldb_loader")
        add_step("AWS Secret", True, "Credentials created (simulated)", 
                 f"Path: /pulldb/mysql/{host_alias}")
        
        # Actually register host in simulated repo
        host_id = str(uuid_module.uuid4())
        credential_ref = f"mock/pulldb/mysql/{host_alias}"
        
        if hasattr(state, "host_repo") and state.host_repo:
            state.host_repo.add_host(
                hostname=mysql_host,
                max_concurrent=max_running_jobs,
                credential_ref=credential_ref,
                host_id=host_id,
                host_alias=host_alias,
                max_running_jobs=max_running_jobs,
                max_active_jobs=max_active_jobs,
            )
            add_step("Register Host", True, "Host registered successfully (simulated)")
        
        result["success"] = True
        result["host_id"] = host_id
        result["message"] = "Host provisioned successfully (simulation mode)"
        result["simulation_mode"] = True
        return result
    
    # Track what was newly created for rollback
    secret_was_new = False
    created_secret_path = None
    
    try:
        # Step 1: Check existing host
        existing_host = None
        if hasattr(state, "host_repo") and state.host_repo:
            if hasattr(state.host_repo, "get_host_by_alias"):
                existing_host = state.host_repo.get_host_by_alias(host_alias)
        
        if existing_host:
            add_step("Check Host", True, f"Host '{host_alias}' exists, will update")
            result["host_id"] = existing_host.id
        else:
            add_step("Check Host", True, f"New host '{host_alias}'")
        
        # Step 2: Check existing AWS secret
        secret_path = get_secret_path_from_alias(host_alias)
        credential_ref = generate_credential_ref(host_alias)
        
        secret_check = check_secret_exists(secret_path, fetch_value=True)
        if secret_check.error:
            add_step("Check Secret", False, "Error checking AWS secret", secret_check.error)
            result["message"] = f"AWS error: {secret_check.error}"
            return result
        
        if secret_check.exists:
            add_step("Check Secret", True, "Existing credentials found", 
                     f"Secret: {secret_path}")
        else:
            add_step("Check Secret", True, "No existing credentials", 
                     f"Will create: {secret_path}")
        
        # Step 3: Provision MySQL (test connection, create user, db, sproc)
        prov_result, created_resources = provision_host_full(
            mysql_host=mysql_host,
            mysql_port=mysql_port,
            admin_username=admin_username,
            admin_password=admin_password,
        )
        
        if not prov_result.success:
            add_step("MySQL Setup", False, prov_result.message, 
                     prov_result.error or "")
            if prov_result.suggestions:
                result["message"] = f"{prov_result.message}. Try: {prov_result.suggestions[0]}"
            else:
                result["message"] = prov_result.message
            return result
        
        # prov_result.data is guaranteed non-None after success check
        prov_data = prov_result.data or {}
        loader_username = prov_data.get("loader_username", "pulldb_loader")
        loader_password = prov_data.get("loader_password", "")
        
        user_action = "created" if created_resources["user_created"] else "updated"
        db_action = "created" if created_resources["database_created"] else "exists"
        
        add_step("MySQL Setup", True, 
                 f"User {user_action}, database {db_action}, procedure deployed",
                 f"User: {loader_username}")
        
        # Step 4: Create or update AWS secret
        secret_data = {
            "host": mysql_host,
            "password": loader_password,
            "username": loader_username,
            "port": mysql_port,
        }
        
        upsert_result = safe_upsert_single_secret(
            secret_path=secret_path,
            secret_data=secret_data,
        )
        
        if not upsert_result.success:
            add_step("AWS Secret", False, "Failed to save credentials", 
                     upsert_result.error or "")
            result["message"] = f"AWS error: {upsert_result.error}"
            return result
        
        secret_was_new = upsert_result.was_new
        created_secret_path = secret_path
        
        secret_action = "created" if upsert_result.was_new else "updated"
        add_step("AWS Secret", True, f"Credentials {secret_action}", 
                 f"Path: {secret_path}")
        
        # Step 5: Register or update host in database
        host_id = str(result["host_id"]) if result["host_id"] else str(uuid.uuid4())
        
        if hasattr(state, "host_repo") and state.host_repo:
            if existing_host:
                # Update existing host
                if hasattr(state.host_repo, "update_host_config"):
                    state.host_repo.update_host_config(
                        host_id,
                        host_alias=host_alias,
                        credential_ref=credential_ref,
                        max_running_jobs=max_running_jobs,
                        max_active_jobs=max_active_jobs,
                    )
                add_step("Register Host", True, "Host configuration updated")
            else:
                # Add new host
                state.host_repo.add_host(
                    hostname=mysql_host,
                    max_concurrent=max_running_jobs,
                    credential_ref=credential_ref,
                    host_id=host_id,
                    host_alias=host_alias,
                    max_running_jobs=max_running_jobs,
                    max_active_jobs=max_active_jobs,
                )
                result["host_id"] = host_id
                add_step("Register Host", True, "Host registered successfully")
        
        result["success"] = True
        result["message"] = "Host provisioned successfully"
        return result
        
    except Exception as e:
        # Rollback: Delete secret only if it was newly created
        if secret_was_new and created_secret_path:
            delete_secret_if_new(created_secret_path, was_new=True)
            result["rollback_performed"] = True
            add_step("Rollback", True, "Cleaned up newly-created secret", 
                     f"Deleted: {created_secret_path}")
        
        result["message"] = f"Unexpected error: {e}"
        add_step("Error", False, str(e))
        return result


# =============================================================================
# Settings Management
# =============================================================================

import os as _os
from pulldb.domain.settings import (
    SETTING_REGISTRY,
    SettingCategory,
    SettingMeta,
    SettingType,
    get_setting_meta,
    get_settings_by_category,
)
from pulldb.domain.validation import (
    ValidationResult,
    validate_setting_value,
    try_create_directory,
)


def _get_setting_source(
    key: str,
    db_value: str | None,
    meta: SettingMeta | None,
) -> tuple[str | None, str]:
    """Determine setting's effective value and source.

    Priority: database > environment > default

    Returns:
        Tuple of (effective_value, source) where source is 'database', 'environment', or 'default'.
    """
    # Database has highest priority
    if db_value is not None:
        return db_value, "database"

    # Check environment
    if meta:
        env_value = _os.getenv(meta.env_var)
        if env_value is not None:
            return env_value, "environment"
        # Return default
        return meta.default, "default"

    return None, "none"


def _build_setting_dict(
    key: str,
    db_settings: dict[str, str],
    meta: SettingMeta | None,
) -> dict:
    """Build a complete setting dictionary for template rendering."""
    db_value = db_settings.get(key)
    effective_value, source = _get_setting_source(key, db_value, meta)

    return {
        "setting_key": key,
        "setting_value": effective_value or "",
        "db_value": db_value,
        "env_value": _os.getenv(meta.env_var) if meta else None,
        "default": meta.default if meta else None,
        "description": meta.description if meta else "",
        "setting_type": meta.setting_type.value if meta else "string",
        "category": meta.category.value if meta else "Paths & Directories",
        "dangerous": meta.dangerous if meta else False,
        "source": source,
        "env_var": meta.env_var if meta else f"PULLDB_{key.upper()}",
    }


@router.get("/settings", response_class=HTMLResponse)
async def list_settings(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """List all system settings grouped by category."""
    # Get all database settings
    db_settings: dict[str, str] = {}
    if hasattr(state, "settings_repo") and state.settings_repo:
        db_settings = state.settings_repo.get_all_settings()

    # Build settings list from registry
    settings_list = []
    for key, meta in SETTING_REGISTRY.items():
        settings_list.append(_build_setting_dict(key, db_settings, meta))

    # Also include any database settings not in registry
    for key in db_settings:
        if key not in SETTING_REGISTRY:
            settings_list.append(_build_setting_dict(key, db_settings, None))

    # Group by category
    categories: dict[str, list[dict]] = {}
    category_order = [
        SettingCategory.JOB_LIMITS.value,
        SettingCategory.PATHS.value,
        SettingCategory.MYLOADER.value,
        SettingCategory.S3_BACKUP.value,
        SettingCategory.CLEANUP.value,
        SettingCategory.APPEARANCE.value,
    ]

    for cat in category_order:
        categories[cat] = []

    for setting in settings_list:
        cat = setting["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(setting)

    # Get recent audit logs for settings
    audit_logs = []
    if hasattr(state, "audit_repo") and state.audit_repo:
        try:
            all_logs = state.audit_repo.get_audit_logs(limit=50)
            audit_logs = [
                log for log in all_logs
                if log.get("action") in ("setting_updated", "setting_reset")
            ][:10]  # Last 10 settings changes
        except Exception:
            pass  # Audit logs are optional

    return templates.TemplateResponse(
        "features/admin/settings.html",
        {
            "request": request,
            "active_nav": "admin",
            "categories": categories,
            "category_order": category_order,
            "settings": settings_list,  # Flat list for search
            "audit_logs": audit_logs,
            "user": user,
            "breadcrumbs": get_breadcrumbs("admin_settings"),
        },
    )


@router.post("/settings/{key}")
async def update_setting(
    key: str,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    value: str = Form(...),
) -> dict:
    """Update a setting value.

    Validates the value, saves to database, and logs the change.
    Returns JSON for HTMX partial update.
    """
    meta = get_setting_meta(key)

    # Validate value
    if meta:
        result = validate_setting_value(
            key=key,
            value=value,
            setting_type=meta.setting_type.value,
            validators=list(meta.validators),
        )
        if not result.valid:
            return {
                "success": False,
                "error": result.error,
                "can_create": result.can_create,
            }

    # Get old value for audit
    old_value = None
    if hasattr(state, "settings_repo") and state.settings_repo:
        old_value = state.settings_repo.get_setting(key)

    # Save new value
    try:
        description = meta.description if meta else None
        state.settings_repo.set_setting(key, value, description)
    except Exception as e:
        return {"success": False, "error": f"Failed to save: {e}"}

    # Audit log
    if hasattr(state, "audit_repo") and state.audit_repo:
        try:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="setting_updated",
                detail=f"Setting '{key}' updated",
                context={
                    "key": key,
                    "old_value": old_value,
                    "new_value": value,
                },
            )
        except Exception:
            pass  # Audit is best-effort

    # Return updated setting data
    db_settings = state.settings_repo.get_all_settings()
    setting_dict = _build_setting_dict(key, db_settings, meta)

    return {
        "success": True,
        "setting": setting_dict,
        "message": f"Setting '{key}' updated successfully",
    }


@router.delete("/settings/{key}")
async def reset_setting(
    key: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Reset a setting to its default value by deleting from database.

    Returns JSON for HTMX partial update.
    """
    meta = get_setting_meta(key)

    # Get old value for audit
    old_value = None
    if hasattr(state, "settings_repo") and state.settings_repo:
        old_value = state.settings_repo.get_setting(key)

    if old_value is None:
        return {"success": False, "error": "Setting not found in database"}

    # Delete from database
    try:
        deleted = state.settings_repo.delete_setting(key)
        if not deleted:
            return {"success": False, "error": "Setting could not be deleted"}
    except Exception as e:
        return {"success": False, "error": f"Failed to delete: {e}"}

    # Audit log
    if hasattr(state, "audit_repo") and state.audit_repo:
        try:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="setting_reset",
                detail=f"Setting '{key}' reset to default",
                context={
                    "key": key,
                    "old_value": old_value,
                },
            )
        except Exception:
            pass  # Audit is best-effort

    # Return updated setting data (now showing env/default)
    db_settings = state.settings_repo.get_all_settings()
    setting_dict = _build_setting_dict(key, db_settings, meta)

    return {
        "success": True,
        "setting": setting_dict,
        "message": f"Setting '{key}' reset to default",
    }


@router.post("/settings/{key}/validate")
async def validate_setting(
    key: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    value: str = Form(...),
) -> dict:
    """Validate a setting value without saving.

    Returns validation result for HTMX feedback.
    """
    meta = get_setting_meta(key)

    if not meta:
        return {"valid": True, "message": "Unknown setting, no validation rules"}

    result = validate_setting_value(
        key=key,
        value=value,
        setting_type=meta.setting_type.value,
        validators=list(meta.validators),
    )

    return {
        "valid": result.valid,
        "error": result.error,
        "warning": result.warning,
        "can_create": result.can_create,
    }


@router.post("/settings/{key}/create-directory")
async def create_setting_directory(
    key: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    path: str = Form(...),
) -> dict:
    """Create a directory for a setting.

    Used when validation fails because directory doesn't exist but can be created.
    """
    meta = get_setting_meta(key)

    if not meta or meta.setting_type != SettingType.DIRECTORY:
        return {"success": False, "error": "Setting is not a directory type"}

    success, error = try_create_directory(path)

    if success:
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            try:
                state.audit_repo.log_action(
                    actor_user_id=user.user_id,
                    action="setting_updated",
                    detail=f"Directory created for setting '{key}'",
                    context={
                        "key": key,
                        "directory_created": path,
                    },
                )
            except Exception:
                pass  # Audit is best-effort

        return {"success": True, "message": f"Directory created: {path}"}

    return {"success": False, "error": error}


# =============================================================================
# Prune Logs - Preview and Execute
# =============================================================================

@router.get("/prune-logs/preview", response_class=HTMLResponse)
async def prune_logs_preview(
    request: Request,
    days: int = 90,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Preview what prune-logs will delete."""
    return templates.TemplateResponse(
        "features/admin/prune_preview.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "days": days,
            "breadcrumbs": get_breadcrumbs("admin_prune"),
        },
    )


@router.get("/api/prune-candidates")
async def get_prune_candidates(
    request: Request,
    days: int = 90,
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: Optional[str] = None,
    sortDirection: str = "asc",
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get paginated list of jobs with events to prune.
    
    Supports LazyTable params: page, pageSize, sortColumn, sortDirection, filter_*
    """
    if not hasattr(state.job_repo, "get_prune_candidates"):
        return {"rows": [], "totalCount": 0, "filteredCount": 0, "totalEvents": 0}
    
    # Get all candidates (we'll filter/sort in memory)
    result = state.job_repo.get_prune_candidates(
        retention_days=days,
        offset=0,
        limit=10000,  # Get all for filtering
    )
    
    rows = result.get("rows", [])
    total_count = len(rows)
    
    # Extract filter params from query string
    text_filters = {}  # column -> [values]
    date_after = {}    # column -> ISO date string
    date_before = {}   # column -> ISO date string
    date_columns = ["oldest_event", "newest_event"]
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
            # Check for date range suffixes
            if col_key.endswith("_after"):
                base_col = col_key[:-6]
                if base_col in date_columns:
                    date_after[base_col] = value
                    continue
            if col_key.endswith("_before"):
                base_col = col_key[:-7]
                if base_col in date_columns:
                    date_before[base_col] = value
                    continue
            
            # Regular filter (could be multi-value comma-separated)
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]
    
    # Apply filters
    if text_filters or date_after or date_before:
        from datetime import datetime
        filtered_rows = []
        for row in rows:
            match = True
            
            # Check text filters (any of the values match)
            for col_key, filter_vals in text_filters.items():
                cell_val = str(row.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            
            # Check date after filters
            if match:
                for col_key, after_val in date_after.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(after_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt < cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            # Check date before filters
            if match:
                for col_key, before_val in date_before.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(before_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt > cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            if match:
                filtered_rows.append(row)
        rows = filtered_rows
    
    filtered_count = len(rows)
    
    # Apply sorting
    if sortColumn and sortColumn in ["job_id", "target", "user_code", "status", "oldest_event", "event_count"]:
        reverse = sortDirection.lower() == "desc"
        rows = sorted(rows, key=lambda r: (r.get(sortColumn) is None, r.get(sortColumn, "")), reverse=reverse)
    
    # Apply pagination (LazyTable sends 0-indexed page)
    offset = page * pageSize
    paginated_rows = rows[offset:offset + pageSize]
    
    return {
        "rows": paginated_rows,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "totalEvents": result.get("totalEvents", 0),
    }


@router.get("/api/prune-candidates/distinct")
async def get_prune_distinct_values(
    request: Request,
    column: str,
    days: int = 90,
    filter_order: str | None = None,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> list:
    """Get distinct values for filter dropdowns.
    
    Supports cascading filters:
    - If column is NOT in filter_order: apply ALL filters
    - If column IS in filter_order: only apply filters preceding it
    """
    from pulldb.infra.filter_utils import parse_multi_value_filter
    
    if not hasattr(state.job_repo, "get_prune_candidates"):
        return []
    result = state.job_repo.get_prune_candidates(retention_days=days, offset=0, limit=10000)
    rows = result.get("rows", [])
    
    # Parse filter order and determine which filters should apply
    order_list = [c.strip() for c in filter_order.split(",") if c.strip()] if filter_order else []
    column_in_order = column in order_list
    column_idx = order_list.index(column) if column_in_order else -1
    
    # If column is in order, only apply prior filters; otherwise apply ALL filters
    if column_in_order:
        applicable_cols = set(order_list[:column_idx]) if column_idx > 0 else set()
    else:
        applicable_cols = set(order_list)
    
    # Extract filter params from request
    filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value and key != "filter_order":
            col_key = key[7:]
            if col_key in applicable_cols:
                filters[col_key] = parse_multi_value_filter(value)
    
    # Apply cascading filters
    if filters:
        filtered = []
        for row in rows:
            match = True
            for col_key, filter_vals in filters.items():
                cell_val = str(row.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            if match:
                filtered.append(row)
        rows = filtered
    
    values = set()
    for row in rows:
        val = row.get(column)
        if val is not None:
            values.add(str(val))
    return sorted(values)


@router.post("/prune-logs/execute")
async def prune_logs_execute(
    request: Request,
    days: int = Form(90),
    include_ids: str = Form(""),  # Comma-separated job IDs to prune
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute prune-logs on specific job IDs."""
    include_list = [x.strip() for x in include_ids.split(",") if x.strip()]
    
    deleted_count = 0
    job_count = len(include_list)
    error_msg = None

    if include_list:
        try:
            if hasattr(state.job_repo, "prune_job_events_by_ids"):
                deleted_count = state.job_repo.prune_job_events_by_ids(job_ids=include_list)
            elif hasattr(state.job_repo, "prune_job_events_excluding"):
                # Fallback: get all candidates, compute exclude list
                result = state.job_repo.get_prune_candidates(retention_days=days, offset=0, limit=10000)
                all_ids = {row["job_id"] for row in result.get("rows", [])}
                exclude_list = list(all_ids - set(include_list))
                deleted_count = state.job_repo.prune_job_events_excluding(
                    retention_days=days,
                    exclude_job_ids=exclude_list,
                )
        except Exception as e:
            error_msg = str(e)

    # Redirect with feedback params
    if error_msg:
        from urllib.parse import quote
        return RedirectResponse(
            url=f"/web/admin/?prune_error={quote(error_msg)}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/web/admin/?prune_success={deleted_count}&prune_jobs={job_count}",
        status_code=303,
    )


# Legacy endpoint for backward compatibility
@router.post("/prune-logs")
async def prune_logs(
    days: int = Form(90),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Prune old logs (legacy - redirects to preview)."""
    return RedirectResponse(url=f"/web/admin/prune-logs/preview?days={days}", status_code=303)


# =============================================================================
# Cleanup Staging - Preview and Execute
# =============================================================================

@router.get("/cleanup-staging/preview", response_class=HTMLResponse)
async def cleanup_staging_preview(
    request: Request,
    days: int = 7,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    cleanup_success: int | None = None,
    cleanup_total: int | None = None,
    cleanup_skipped: int | None = None,
    cleanup_error: str | None = None,
) -> HTMLResponse:
    """Preview what cleanup-staging will delete."""
    # Build flash message from query params (set by cleanup execute redirect)
    flash_message = None
    flash_type = None
    if cleanup_success is not None and cleanup_total is not None:
        if cleanup_skipped:
            flash_message = f"Dropped {cleanup_success} of {cleanup_total} databases ({cleanup_skipped} skipped - active jobs)"
        else:
            flash_message = f"Successfully dropped {cleanup_success} staging database(s)"
        flash_type = "success"
    elif cleanup_error:
        flash_message = f"Cleanup failed: {cleanup_error}"
        flash_type = "error"
    
    return templates.TemplateResponse(
        "features/admin/cleanup_preview.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "days": days,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "breadcrumbs": get_breadcrumbs("admin_cleanup"),
        },
    )


@router.get("/api/cleanup-candidates")
async def get_cleanup_candidates(
    request: Request,
    days: int = 7,
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: Optional[str] = None,
    sortDirection: str = "asc",
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get paginated list of staging databases to cleanup.
    
    Supports LazyTable params: page, pageSize, sortColumn, sortDirection, filter_*
    """
    if not hasattr(state.job_repo, "get_cleanup_candidates"):
        return {"rows": [], "totalCount": 0, "filteredCount": 0}
    
    # Get all candidates (we'll filter/sort in memory)
    result = state.job_repo.get_cleanup_candidates(
        retention_days=days,
        offset=0,
        limit=10000,  # Get all for filtering
    )
    
    rows = result.get("rows", [])
    total_count = len(rows)
    
    # Extract filter params from query string
    text_filters = {}  # column -> [values]
    date_after = {}    # column -> ISO date string
    date_before = {}   # column -> ISO date string
    date_columns = ["completed_at"]
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
            # Check for date range suffixes
            if col_key.endswith("_after"):
                base_col = col_key[:-6]
                if base_col in date_columns:
                    date_after[base_col] = value
                    continue
            if col_key.endswith("_before"):
                base_col = col_key[:-7]
                if base_col in date_columns:
                    date_before[base_col] = value
                    continue
            
            # Regular filter (could be multi-value comma-separated)
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]
    
    # Apply filters
    if text_filters or date_after or date_before:
        from datetime import datetime
        filtered_rows = []
        for row in rows:
            match = True
            
            # Check text filters (any of the values match)
            for col_key, filter_vals in text_filters.items():
                cell_val = str(row.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            
            # Check date after filters
            if match:
                for col_key, after_val in date_after.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(after_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt < cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            # Check date before filters
            if match:
                for col_key, before_val in date_before.items():
                    cell_val = row.get(col_key)
                    if cell_val:
                        try:
                            cutoff = datetime.fromisoformat(before_val.replace('Z', '+00:00'))
                            cell_dt = datetime.fromisoformat(str(cell_val).replace('Z', '+00:00'))
                            if cell_dt > cutoff:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            if match:
                filtered_rows.append(row)
        rows = filtered_rows
    
    filtered_count = len(rows)
    
    # Apply sorting
    if sortColumn and sortColumn in ["database_name", "target", "dbhost", "user_code", "job_status", "completed_at"]:
        reverse = sortDirection.lower() == "desc"
        rows = sorted(rows, key=lambda r: (r.get(sortColumn) is None, r.get(sortColumn, "")), reverse=reverse)
    
    # Apply pagination (LazyTable sends 0-indexed page)
    offset = page * pageSize
    paginated_rows = rows[offset:offset + pageSize]
    
    return {
        "rows": paginated_rows,
        "totalCount": total_count,
        "filteredCount": filtered_count,
    }


@router.get("/api/cleanup-candidates/distinct")
async def get_cleanup_distinct_values(
    request: Request,
    column: str,
    days: int = 7,
    filter_order: str | None = None,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> list:
    """Get distinct values for filter dropdowns.
    
    Supports cascading filters:
    - If column is NOT in filter_order: apply ALL filters
    - If column IS in filter_order: only apply filters preceding it
    """
    from pulldb.infra.filter_utils import parse_multi_value_filter
    
    if not hasattr(state.job_repo, "get_cleanup_candidates"):
        return []
    result = state.job_repo.get_cleanup_candidates(retention_days=days, offset=0, limit=10000)
    rows = result.get("rows", [])
    
    # Parse filter order and determine which filters should apply
    order_list = [c.strip() for c in filter_order.split(",") if c.strip()] if filter_order else []
    column_in_order = column in order_list
    column_idx = order_list.index(column) if column_in_order else -1
    
    # If column is in order, only apply prior filters; otherwise apply ALL filters
    if column_in_order:
        applicable_cols = set(order_list[:column_idx]) if column_idx > 0 else set()
    else:
        applicable_cols = set(order_list)
    
    # Extract filter params from request
    filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value and key != "filter_order":
            col_key = key[7:]
            if col_key in applicable_cols:
                filters[col_key] = parse_multi_value_filter(value)
    
    # Apply cascading filters
    if filters:
        filtered = []
        for row in rows:
            match = True
            for col_key, filter_vals in filters.items():
                cell_val = str(row.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            if match:
                filtered.append(row)
        rows = filtered
    
    values = set()
    for row in rows:
        val = row.get(column)
        if val is not None:
            values.add(str(val))
    return sorted(values)


@router.post("/cleanup-staging/execute")
async def cleanup_staging_execute(
    request: Request,
    days: int = Form(7),
    include_ids: str = Form(""),  # Comma-separated database names to drop
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute cleanup-staging on specific databases."""
    from pulldb.infra.factory import is_simulation_mode
    
    include_list = [x.strip() for x in include_ids.split(",") if x.strip()]
    
    if not include_list:
        return RedirectResponse(
            url="/web/admin/cleanup-staging/preview?cleanup_error=No+databases+selected",
            status_code=303,
        )
    
    try:
        if is_simulation_mode():
            # Use mock method directly
            if hasattr(state.job_repo, "cleanup_staging_by_names"):
                result = state.job_repo.cleanup_staging_by_names(database_names=include_list)
                dropped = result.get("dropped_count", 0)
                skipped = result.get("skipped_count", 0)
            elif hasattr(state.job_repo, "drop_staging_databases_by_names"):
                result = state.job_repo.drop_staging_databases_by_names(database_names=include_list)
                dropped = result.get("dropped_count", 0)
                skipped = result.get("skipped_count", 0)
            else:
                # Fallback for dev mode
                import logging
                logging.info(f"Would drop staging databases: {include_list}")
                dropped = len(include_list)
                skipped = 0
        else:
            # Use worker cleanup function for real database access
            from pulldb.worker.cleanup import cleanup_specific_databases
            cleanup_result = cleanup_specific_databases(
                database_names=include_list,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            dropped = cleanup_result.databases_dropped
            skipped = cleanup_result.databases_skipped
        
        total = len(include_list)
        return RedirectResponse(
            url=f"/web/admin/cleanup-staging/preview?cleanup_success={dropped}&cleanup_total={total}&cleanup_skipped={skipped}",
            status_code=303,
        )
    except Exception as e:
        import logging
        logging.exception("Failed to cleanup staging databases")
        error_msg = str(e).replace(" ", "+")[:100]  # Truncate for URL safety
        return RedirectResponse(
            url=f"/web/admin/cleanup-staging/preview?cleanup_error={error_msg}",
            status_code=303,
        )


# Legacy endpoint for backward compatibility
@router.post("/cleanup-staging")
async def cleanup_staging(
    days: int = Form(7),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Cleanup staging databases (legacy - redirects to preview)."""
    return RedirectResponse(url=f"/web/admin/cleanup-staging/preview?days={days}", status_code=303)


@router.get("/orphans/preview", response_class=HTMLResponse)
async def orphan_preview_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    orphan_success: int | None = None,
    orphan_error: str | None = None,
) -> HTMLResponse:
    """Render the orphan database deletion preview page."""
    flash_message = None
    flash_type = None
    if orphan_success is not None:
        flash_message = f"Successfully deleted {orphan_success} orphan database(s)"
        flash_type = "success"
    elif orphan_error:
        flash_message = f"Orphan deletion failed: {orphan_error}"
        flash_type = "error"

    return templates.TemplateResponse(
        "features/admin/orphan_preview.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "breadcrumbs": get_breadcrumbs("admin_orphans"),
        },
    )


@router.get("/api/orphan-candidates")
async def api_orphan_candidates(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict[str, Any]:
    """Get paginated orphan candidates for LazyTable.
    
    Returns all orphans from all hosts in a flat list with dbhost included.
    Supports multi-select filters (filter_<column>) and date range (filter_<column>_after/before).
    """
    from pulldb.worker.cleanup import detect_orphaned_databases
    from datetime import datetime

    # Collect all orphans from all hosts
    all_orphans: list[dict[str, Any]] = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            # Skip hosts with connection errors
            if isinstance(result, str):
                continue
            for oc in result.orphans:
                all_orphans.append({
                    "database_name": oc.database_name,
                    "dbhost": oc.dbhost,
                    "target_name": oc.target_name,
                    "job_id_prefix": oc.job_id_prefix,
                    "discovered_at": oc.discovered_at.isoformat() if oc.discovered_at else None,
                    "size_mb": oc.size_mb,
                })

    total_count = len(all_orphans)

    # Extract filter params from query string
    text_filters: dict[str, list[str]] = {}  # column -> [values]
    date_after: dict[str, str] = {}    # column -> ISO date string
    date_before: dict[str, str] = {}   # column -> ISO date string
    date_columns = ["discovered_at"]
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
            # Check for date range suffixes
            if col_key.endswith("_after"):
                base_col = col_key[:-6]
                if base_col in date_columns:
                    date_after[base_col] = value
                    continue
            if col_key.endswith("_before"):
                base_col = col_key[:-7]
                if base_col in date_columns:
                    date_before[base_col] = value
                    continue
            
            # Regular filter (could be multi-value comma-separated)
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]

    # Apply filters
    if text_filters or date_after or date_before:
        filtered_orphans: list[dict[str, Any]] = []
        orphan_item: dict[str, Any]
        for orphan_item in all_orphans:
            match = True
            
            # Check text filters (any of the values match)
            for col_key, filter_vals in text_filters.items():
                cell_val = str(orphan_item.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            
            # Check date after filters
            if match:
                for col_key, after_val in date_after.items():
                    cell_val_date = orphan_item.get(col_key)
                    if cell_val_date:
                        try:
                            cell_date = datetime.fromisoformat(str(cell_val_date).replace('Z', '+00:00'))
                            after_date = datetime.fromisoformat(after_val)
                            if cell_date.date() < after_date.date():
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            # Check date before filters
            if match:
                for col_key, before_val in date_before.items():
                    cell_val_date = orphan_item.get(col_key)
                    if cell_val_date:
                        try:
                            cell_date = datetime.fromisoformat(str(cell_val_date).replace('Z', '+00:00'))
                            before_date = datetime.fromisoformat(before_val)
                            if cell_date.date() > before_date.date():
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
            
            if match:
                filtered_orphans.append(orphan_item)
        
        all_orphans = filtered_orphans

    filtered_count = len(all_orphans)

    # Apply sorting
    if sortColumn and sortColumn in ("database_name", "dbhost", "target_name", "discovered_at", "size_mb"):
        reverse = sortDirection == "desc"
        all_orphans.sort(
            key=lambda o: (o.get(sortColumn) is None, o.get(sortColumn) or ""),
            reverse=reverse
        )
    
    # Apply pagination
    start = page * pageSize
    end = start + pageSize
    page_orphans = all_orphans[start:end]

    return {
        "rows": page_orphans,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "pageIndex": page,
        "pageSize": pageSize,
    }


@router.get("/api/orphan-candidates/distinct")
async def get_orphan_distinct_values(
    request: Request,
    column: str,
    filter_order: str | None = None,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> list[str]:
    """Get distinct values for filter dropdowns.
    
    Supports cascading filters:
    - If column is NOT in filter_order: apply ALL filters
    - If column IS in filter_order: only apply filters preceding it
    """
    from pulldb.infra.filter_utils import parse_multi_value_filter
    from pulldb.worker.cleanup import detect_orphaned_databases
    
    all_orphans: list[dict[str, Any]] = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            if isinstance(result, str):
                continue
            for oc in result.orphans:
                all_orphans.append({
                    "database_name": oc.database_name,
                    "dbhost": oc.dbhost,
                    "target_name": oc.target_name,
                })
    
    # Parse filter order and determine which filters should apply
    order_list = [c.strip() for c in filter_order.split(",") if c.strip()] if filter_order else []
    column_in_order = column in order_list
    column_idx = order_list.index(column) if column_in_order else -1
    
    # If column is in order, only apply prior filters; otherwise apply ALL filters
    if column_in_order:
        applicable_cols = set(order_list[:column_idx]) if column_idx > 0 else set()
    else:
        applicable_cols = set(order_list)
    
    # Extract filter params (only from applicable columns)
    text_filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value and key != "filter_order":
            col_key = key[7:]  # Remove "filter_" prefix
            # Skip date range suffixes
            if col_key.endswith("_after") or col_key.endswith("_before"):
                continue
            # Only include filters from applicable columns
            if col_key in applicable_cols:
                text_filters[col_key] = parse_multi_value_filter(value)
    
    # Apply cascading filters
    if text_filters:
        filtered_orphans: list[dict[str, Any]] = []
        orphan_item: dict[str, Any]
        for orphan_item in all_orphans:
            match = True
            for col_key, filter_vals in text_filters.items():
                cell_val = str(orphan_item.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            if match:
                filtered_orphans.append(orphan_item)
        all_orphans = filtered_orphans
    
    values: set[str] = set()
    for orphan_item in all_orphans:
        val = orphan_item.get(column)
        if val is not None:
            values.add(str(val))
    return sorted(values)


@router.post("/orphans/execute")
async def execute_orphan_deletion(
    selected_orphans: str = Form(""),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute deletion of selected orphan databases.
    
    selected_orphans is a comma-separated list of "dbhost|database_name" keys.
    Groups by dbhost for efficient credential lookup and deletion.
    """
    from pulldb.worker.cleanup import admin_delete_orphan_databases

    if not selected_orphans.strip():
        return RedirectResponse(
            url="/web/admin/orphans/preview?orphan_error=No+orphans+selected",
            status_code=303,
        )

    # Parse selected keys and group by dbhost
    by_host: dict[str, list[str]] = {}
    for key in selected_orphans.split(","):
        key = key.strip()
        if "|" not in key:
            continue
        dbhost, database_name = key.split("|", 1)
        if dbhost not in by_host:
            by_host[dbhost] = []
        by_host[dbhost].append(database_name)

    if not by_host:
        return RedirectResponse(
            url="/web/admin/orphans/preview?orphan_error=Invalid+selection+format",
            status_code=303,
        )

    # Delete orphans grouped by host
    total_deleted = 0
    errors = []
    
    try:
        for dbhost, database_names in by_host.items():
            if hasattr(state, "host_repo") and state.host_repo:
                results = admin_delete_orphan_databases(
                    dbhost=dbhost,
                    database_names=database_names,
                    host_repo=state.host_repo,
                    admin_user=user.username,
                )
                # results is dict[str, bool] mapping database_name to success
                for db_name, success in results.items():
                    if success:
                        total_deleted += 1
                    else:
                        errors.append(f"{dbhost}:{db_name}")

        if errors:
            error_msg = f"Deleted+{total_deleted},+failed:+" + ",".join(errors[:3])
            if len(errors) > 3:
                error_msg += f"+and+{len(errors)-3}+more"
            return RedirectResponse(
                url=f"/web/admin/orphans/preview?orphan_error={error_msg}",
                status_code=303,
            )

        return RedirectResponse(
            url=f"/web/admin/orphans/preview?orphan_success={total_deleted}",
            status_code=303,
        )

    except Exception as e:
        error_msg = str(e).replace(" ", "+")[:100]
        return RedirectResponse(
            url=f"/web/admin/orphans/preview?orphan_error={error_msg}",
            status_code=303,
        )


@router.get("/orphans", response_class=HTMLResponse)
async def get_orphans(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Get orphan databases report."""
    from pulldb.worker.cleanup import detect_orphaned_databases, OrphanReport
    
    reports = []
    errors = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_orphaned_databases(
                dbhost=host.hostname,
                job_repo=state.job_repo,
                host_repo=state.host_repo,
            )
            # Handle error string return (connection failure)
            if isinstance(result, str):
                errors.append({"host": host.hostname, "message": result})
                continue
            # Handle successful OrphanReport
            orphan_report: OrphanReport = result
            if orphan_report.orphans:
                reports.append({
                    "host": host.hostname,
                    "orphans": orphan_report.orphans
                })

    return templates.TemplateResponse(
        "features/admin/partials/orphans.html",
        {"request": request, "reports": reports, "errors": errors}
    )


@router.post("/orphans/delete")
async def delete_orphans(
    dbhost: str = Form(...),
    database_name: str = Form(...),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Delete an orphan database."""
    from pulldb.worker.cleanup import admin_delete_orphan_databases
    
    if hasattr(state, "host_repo") and state.host_repo:
        admin_delete_orphan_databases(
            dbhost=dbhost,
            database_names=[database_name],
            host_repo=state.host_repo,
            admin_user=user.username,
        )
    
    return RedirectResponse(url="/web/admin/", status_code=303)


# =============================================================================
# Theme CSS Endpoint
# =============================================================================


@router.get("/api/theme.css")
async def get_theme_css(
    state: Any = Depends(get_api_state),
) -> Response:
    """Generate dynamic CSS custom properties from admin appearance settings.
    
    Returns CSS with both light and dark mode variables, populated from
    JSON color schemas stored in the database. Falls back to default
    presets if no custom schemas are configured.
    
    The response includes:
    - :root { /* light mode variables */ }
    - [data-theme="dark"] { /* dark mode variables */ }
    
    All color tokens follow the --color-* naming convention.
    
    Returns:
        text/css response with CSS custom properties for theming.
    """
    from pulldb.domain.color_schemas import (
        ColorSchema,
        LIGHT_PRESETS,
        DARK_PRESETS,
    )
    
    # Load schemas from database, falling back to defaults
    light_schema = LIGHT_PRESETS["Default"]
    dark_schema = DARK_PRESETS["Default"]
    
    if hasattr(state, "settings_repo") and state.settings_repo:
        try:
            light_json = state.settings_repo.get("light_theme_schema")
            if light_json:
                light_schema = ColorSchema.from_json(light_json)
        except (ValueError, TypeError, KeyError):
            pass  # Use default on error
        
        try:
            dark_json = state.settings_repo.get("dark_theme_schema")
            if dark_json:
                dark_schema = ColorSchema.from_json(dark_json)
        except (ValueError, TypeError, KeyError):
            pass  # Use default on error
    
    # Generate CSS variables for both modes
    light_vars = light_schema.to_css_variables()
    dark_vars = dark_schema.to_css_variables()
    
    # Build light mode CSS
    light_css_lines = [f"    {name}: {value};" for name, value in light_vars.items()]
    light_css = "\n".join(light_css_lines)
    
    # Build dark mode CSS
    dark_css_lines = [f"    {name}: {value};" for name, value in dark_vars.items()]
    dark_css = "\n".join(dark_css_lines)
    
    css = f"""/* pullDB Dynamic Theme - Generated from Database Settings */
/* Light Theme: {light_schema.name} | Dark Theme: {dark_schema.name} */

:root {{
{light_css}
}}

[data-theme="dark"],
.dark {{
{dark_css}
}}
"""
    
    return Response(
        content=css,
        media_type="text/css",
        headers={
            "Cache-Control": "public, max-age=60",  # Cache for 1 minute
        },
    )


@router.get("/api/color-preset")
async def get_color_preset(
    mode: str,
    name: str,
    state: Any = Depends(get_api_state),
) -> dict:
    """Get a color preset schema by mode and name.
    
    Args:
        mode: 'light' or 'dark'
        name: Preset name (e.g., 'Default', 'Midnight Blue')
        
    Returns:
        JSON schema object with color values.
    """
    from pulldb.domain.color_schemas import LIGHT_PRESETS, DARK_PRESETS
    
    presets = LIGHT_PRESETS if mode == "light" else DARK_PRESETS
    schema = presets.get(name)
    
    if not schema:
        # Fall back to default
        schema = presets.get("Default")
    
    if not schema:
        return {"error": "Preset not found"}
    
    # Return simplified schema for frontend
    return {
        "name": schema.name,
        "surface": {
            "base": schema.surface.base,
            "hover": schema.surface.hover,
            "active": schema.surface.active,
        },
        "background": {
            "primary": schema.background.primary,
            "secondary": schema.background.secondary,
            "elevated": schema.background.elevated,
        },
        "text": {
            "primary": schema.text.primary,
            "secondary": schema.text.secondary,
            "muted": schema.text.muted,
        },
        "border": {
            "default": schema.border.default,
            "hover": schema.border.hover,
            "focus": schema.border.focus,
        },
        "interactive": {
            "primary": schema.interactive.primary,
            "primary_hover": schema.interactive.primary_hover,
            "danger": schema.interactive.danger,
        },
        "status": {
            "success": schema.status.success,
            "warning": schema.status.warning,
            "error": schema.status.error,
            "info": schema.status.info,
        },
    }


def _schema_to_dict(schema: Any) -> dict:
    """Convert ColorSchema to frontend-compatible dict."""
    return {
        "name": schema.name,
        "surface": {
            "base": schema.surface.base,
            "hover": schema.surface.hover,
            "active": schema.surface.active,
        },
        "background": {
            "primary": schema.background.primary,
            "secondary": schema.background.secondary,
            "elevated": schema.background.elevated,
        },
        "text": {
            "primary": schema.text.primary,
            "secondary": schema.text.secondary,
            "muted": schema.text.muted,
        },
        "border": {
            "default": schema.border.default,
            "hover": schema.border.hover,
            "focus": schema.border.focus,
        },
        "interactive": {
            "primary": schema.interactive.primary,
            "primary_hover": schema.interactive.primary_hover,
            "danger": schema.interactive.danger,
        },
        "status": {
            "success": schema.status.success,
            "warning": schema.status.warning,
            "error": schema.status.error,
            "info": schema.status.info,
        },
    }


@router.get("/api/color-presets")
async def get_all_color_presets(
    state: Any = Depends(get_api_state),
) -> dict:
    """Get all color presets for both light and dark modes.
    
    Returns all presets in a single request, eliminating the need
    for multiple sequential API calls. This is the preferred endpoint
    for loading preset options in the appearance settings UI.
    
    Returns:
        Dict with 'light' and 'dark' keys, each containing a dict
        of preset name -> schema.
    """
    from pulldb.domain.color_schemas import LIGHT_PRESETS, DARK_PRESETS
    
    return {
        "light": {
            name: _schema_to_dict(schema)
            for name, schema in LIGHT_PRESETS.items()
        },
        "dark": {
            name: _schema_to_dict(schema)
            for name, schema in DARK_PRESETS.items()
        },
    }


# =============================================================================
# Theme File Generation Endpoints
# =============================================================================


@router.post("/api/generate-manifest")
async def generate_manifest(
    state: Any = Depends(get_api_state),
) -> dict:
    """Generate static CSS files from saved theme schemas.
    
    Reads light_theme_schema and dark_theme_schema from database,
    generates manifest-light.css and manifest-dark.css in the
    static/css/generated/ directory.
    
    Returns:
        Dict with version timestamp for cache-busting.
    """
    from pulldb.domain.color_schemas import (
        ColorSchema,
        LIGHT_PRESETS,
        DARK_PRESETS,
    )
    from pulldb.web.features.admin.theme_generator import write_theme_files
    
    # Load schemas from database, falling back to defaults
    light_schema = LIGHT_PRESETS["Default"]
    dark_schema = DARK_PRESETS["Default"]
    
    if hasattr(state, "settings_repo") and state.settings_repo:
        try:
            light_json = state.settings_repo.get("light_theme_schema")
            if light_json:
                light_schema = ColorSchema.from_json(light_json)
        except (ValueError, TypeError, KeyError):
            pass
        
        try:
            dark_json = state.settings_repo.get("dark_theme_schema")
            if dark_json:
                dark_schema = ColorSchema.from_json(dark_json)
        except (ValueError, TypeError, KeyError):
            pass
    
    # Generate and write theme files
    result = write_theme_files(light_schema, dark_schema)
    
    return {"success": True, "version": result["version"]}


@router.get("/api/theme-version")
async def get_theme_version() -> dict:
    """Get current theme CSS version for cache-busting.
    
    Returns:
        Dict with version timestamp.
    """
    from pulldb.web.features.admin.theme_generator import get_theme_version as get_version
    
    return {"version": get_version()}
