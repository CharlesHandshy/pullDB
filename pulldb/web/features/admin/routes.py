from __future__ import annotations

"""Admin routes for Web2 interface.

HCA Layer: features (pulldb/web/features/)
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pulldb.domain.models import JobStatus, User
from pulldb.infra.timeouts import DEFAULT_MYSQL_CONNECT_TIMEOUT_MONITOR
from pulldb.web.dependencies import get_api_state, require_admin, templates
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

logger = logging.getLogger(__name__)

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

    # Get pending API keys count
    pending_keys_count = 0
    if hasattr(state, "auth_repo") and state.auth_repo:
        try:
            pending_keys = state.auth_repo.get_pending_api_keys()
            pending_keys_count = len(pending_keys)
        except Exception:  # Graceful degradation - pending keys count is informational
            logger.debug("Failed to get pending API keys count", exc_info=True)

    stats = {
        "total_users": len(users),
        "admin_users": len([u for u in users if u.is_admin]),
        "total_hosts": len(hosts),
        "enabled_hosts": len([h for h in hosts if getattr(h, "enabled", True)]),
        "active_jobs": len(active_jobs),
        "running_jobs": len([j for j in active_jobs if j.status == JobStatus.RUNNING]),
        "pending_jobs": len([j for j in active_jobs if j.status == JobStatus.QUEUED]),
        "pending_keys": pending_keys_count,
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
    
    Adds: active_jobs, total_jobs, disabled (bool from disabled_at), locked (bool from locked_at)
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
        "locked_at": getattr(user_obj, "locked_at", None),
        "allowed_hosts": getattr(user_obj, "allowed_hosts", None),
        "default_host": getattr(user_obj, "default_host", None),
        # Computed fields
        "active_jobs": active_jobs,
        "total_jobs": total_jobs,
        "disabled": user_obj.disabled_at is not None,
        "locked": getattr(user_obj, "locked_at", None) is not None,
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
    # Include SERVICE role in managers list as they have similar permissions
    managers = [
        {"user_id": u.user_id, "username": u.username}
        for u in raw_users 
        if u.role.value in ("manager", "admin", "service")
    ]
    
    stats = {
        "total": len(raw_users),
        "admins": len([u for u in raw_users if u.role.value == "admin"]),
        "managers": len([u for u in raw_users if u.role.value == "manager"]),
        "service": len([u for u in raw_users if u.role.value == "service"]),
        "active": len([u for u in raw_users if not u.disabled_at]),
        "disabled": len([u for u in raw_users if u.disabled_at]),
        "locked": len([u for u in raw_users if getattr(u, "locked_at", None)]),
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
        # Get target user for audit context
        target_user = None
        if hasattr(state.user_repo, "get_user_by_id"):
            target_user = state.user_repo.get_user_by_id(user_id)
        
        if hasattr(state.user_repo, "enable_user_by_id"):
            state.user_repo.enable_user_by_id(user_id)
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="user_enabled",
                target_user_id=user_id,
                detail=f"Admin enabled user {target_user.username if target_user else user_id[:12]}",
            )
        
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
        # Get target user for audit context
        target_user = None
        if hasattr(state.user_repo, "get_user_by_id"):
            target_user = state.user_repo.get_user_by_id(user_id)
        
        if hasattr(state.user_repo, "disable_user_by_id"):
            state.user_repo.disable_user_by_id(user_id)
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="user_disabled",
                target_user_id=user_id,
                detail=f"Admin disabled user {target_user.username if target_user else user_id[:12]}",
            )
        
        return {"success": True, "message": "User disabled"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Delete a user and all related records. Returns JSON for AJAX calls.
    
    Only users with NO job history can be deleted. Users with jobs should
    be disabled instead to preserve audit trail.
    """
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot delete your own account"}
    
    try:
        # Get target user for audit context BEFORE deletion
        target_user = None
        if hasattr(state.user_repo, "get_user_by_id"):
            target_user = state.user_repo.get_user_by_id(user_id)
        
        if hasattr(state.user_repo, "delete_user"):
            result = state.user_repo.delete_user(user_id)
            
            # Audit log
            if hasattr(state, "audit_repo") and state.audit_repo:
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="user_deleted",
                    target_user_id=user_id,
                    detail=f"Admin deleted user {target_user.username if target_user else user_id[:12]}",
                    context={"delete_result": result},
                )
            
            return {
                "success": True,
                "message": "User deleted successfully",
                "details": result,
            }
        return {"success": False, "message": "Delete not supported"}
    except ValueError as e:
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": f"Delete failed: {e}"}


@router.get("/users/{user_id}/force-delete-preview")
async def force_delete_preview(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Get preview data for force-deleting a user with job history.
    
    Returns user info, job count, job-based databases, and live-scanned databases.
    Live scanning finds all databases on user's accessible hosts that have
    the user's user_code prefix - these may have no job history.
    """
    from pulldb.worker.cleanup import scan_databases_for_user_code
    
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot delete your own account"}
    
    try:
        # Get user info
        user = state.user_repo.get_user_by_id(user_id)
        if not user:
            return {"success": False, "message": "User not found"}
        
        # Get job count
        job_count = 0
        if hasattr(state.job_repo, "count_jobs_by_user"):
            job_count = state.job_repo.count_jobs_by_user(user.user_code)
        
        # Get unique databases from job history
        databases_from_jobs = []
        if hasattr(state.job_repo, "get_user_target_databases"):
            databases_from_jobs = state.job_repo.get_user_target_databases(user_id)
        
        # Live scan for databases on user's accessible hosts
        # This catches databases with no job history (deleted history, old data, etc.)
        live_scanned_databases = []
        scan_hosts = None
        if hasattr(state, "host_repo") and state.host_repo:
            # Get user's allowed hosts (or all enabled hosts if not restricted)
            if user.allowed_hosts:
                scan_hosts = user.allowed_hosts
            
            # Scan for databases with this user's code
            try:
                scanned_results = scan_databases_for_user_code(
                    user_code=user.user_code,
                    host_repo=state.host_repo,
                    specific_hosts=scan_hosts,
                )
                # Convert to list of dicts
                for hostname, db_name in scanned_results:
                    live_scanned_databases.append({
                        "name": db_name,
                        "host": hostname,
                        "source": "live_scan",
                    })
            except Exception as e:
                # Log but don't fail - job-based results are still valid
                import logging
                logging.getLogger(__name__).warning(
                    f"Live database scan failed for user {user.user_code}: {e}"
                )
        
        # Merge databases: use live scan as authoritative, mark those also in job history
        job_db_set = {(d["host"], d["name"]) for d in databases_from_jobs}
        merged_databases = []
        seen = set()
        
        # First add live scanned (they actually exist)
        for db in live_scanned_databases:
            key = (db["host"], db["name"])
            if key not in seen:
                seen.add(key)
                in_history = key in job_db_set
                merged_databases.append({
                    "name": db["name"],
                    "host": db["host"],
                    "in_job_history": in_history,
                    "exists": True,  # Live scanned means it exists
                })
        
        # Then add any from job history not found in live scan
        # These may be on hosts we couldn't scan or already deleted
        for db in databases_from_jobs:
            key = (db["host"], db["name"])
            if key not in seen:
                seen.add(key)
                merged_databases.append({
                    "name": db["name"],
                    "host": db["host"],
                    "in_job_history": True,
                    "exists": False,  # Not found in live scan
                })
        
        return {
            "success": True,
            "user": {
                "user_id": user.user_id,
                "username": user.username,
                "user_code": user.user_code,
            },
            "job_count": job_count,
            "databases": merged_databases,
            "databases_from_jobs": len(databases_from_jobs),
            "databases_from_scan": len(live_scanned_databases),
        }
    except Exception as e:
        return {"success": False, "message": f"Preview failed: {e}"}


@router.post("/users/{user_id}/force-delete")
async def force_delete_user(
    user_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Force delete a user with job history, optionally dropping databases.
    
    Creates an async admin task that will be processed by the worker.
    """
    from pulldb.domain.models import AdminTaskType
    from pulldb.infra.mysql import AdminTaskRepository
    
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot delete your own account"}
    
    try:
        # Parse JSON body
        body = await request.json()
        confirm_username = body.get("confirm_username", "")
        skip_database_drops = body.get("skip_database_drops", False)
        databases_to_drop = body.get("databases_to_drop", [])
        
        # Get user to validate confirm_username
        user = state.user_repo.get_user_by_id(user_id)
        if not user:
            return {"success": False, "message": "User not found"}
        
        # Validate confirmation
        if confirm_username != user.username:
            return {
                "success": False,
                "message": f"Username confirmation doesn't match. Expected '{user.username}'",
            }
        
        # Create admin task
        admin_task_repo = AdminTaskRepository(state.job_repo.pool)
        
        # Build parameters
        parameters = {
            "target_username": user.username,
            "target_user_code": user.user_code,
            "databases_to_drop": [] if skip_database_drops else databases_to_drop,
        }
        
        try:
            task_id = admin_task_repo.create_task(
                task_type=AdminTaskType.FORCE_DELETE_USER,
                requested_by=admin.user_id,
                target_user_id=user_id,
                parameters=parameters,
            )
        except ValueError as e:
            # A task is already running
            return {"success": False, "message": str(e)}
        
        return {
            "success": True,
            "message": "Force delete task created",
            "task_id": task_id,
        }
    except Exception as e:
        return {"success": False, "message": f"Force delete failed: {e}"}


@router.get("/admin-tasks/{task_id}/json")
async def get_admin_task_json(
    task_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Get admin task status as JSON for API polling."""
    from pulldb.infra.mysql import AdminTaskRepository
    
    try:
        admin_task_repo = AdminTaskRepository(state.job_repo.pool)
        task = admin_task_repo.get_task(task_id)
        
        if not task:
            return {"success": False, "message": "Task not found"}
        
        return {
            "success": True,
            "task": {
                "task_id": task.task_id,
                "task_type": task.task_type.value,
                "status": task.status.value,
                "requested_by": task.requested_by,
                "target_user_id": task.target_user_id,
                "parameters": task.parameters_json,
                "result": task.result_json,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "error_detail": task.error_detail,
            },
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to get task: {e}"}


@router.get("/admin-tasks/{task_id}", response_class=HTMLResponse)
async def get_admin_task_page(
    request: Request,
    task_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> Response:
    """Render admin task status page with HTMX polling."""
    from pulldb.infra.mysql import AdminTaskRepository
    
    admin_task_repo = AdminTaskRepository(state.job_repo.pool)
    task = admin_task_repo.get_task(task_id)
    
    if not task:
        return RedirectResponse(url="/web/admin/users", status_code=303)
    
    # Resolve target username for display
    target_username = None
    if task.target_user_id:
        target_user = state.user_repo.get_user_by_id(task.target_user_id)
        if target_user:
            target_username = target_user.username
    
    # Build enhanced parameters for template (don't mutate dataclass)
    enhanced_params = dict(task.parameters_json) if task.parameters_json else {}
    enhanced_params["target_username"] = target_username or task.target_user_id
    
    return templates.TemplateResponse(
        "features/admin/admin_task_status.html",
        {
            "request": request,
            "task": task,
            "task_params": enhanced_params,
            "user": admin,
            "active_nav": "admin",
            "breadcrumbs": get_breadcrumbs("admin_users"),
        },
    )


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
        # Get target user for audit context
        target_user = None
        old_role = None
        if hasattr(state.user_repo, "get_user_by_id"):
            target_user = state.user_repo.get_user_by_id(user_id)
            old_role = target_user.role.value if target_user else None
        
        role_enum = UserRole(new_role.lower())
        if hasattr(state.user_repo, "update_user_role"):
            state.user_repo.update_user_role(user_id, role_enum)
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="role_changed",
                target_user_id=user_id,
                detail=f"Changed role from {old_role} to {new_role} for {target_user.username if target_user else user_id[:12]}",
                context={"old_role": old_role, "new_role": new_role},
            )
        
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
    if not username or len(username) < 6 or len(username) > 50:
        return {"success": False, "message": "Username must be 6-50 characters"}
    
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
        try:
            user_code = state.user_repo.generate_user_code(username)
        except ValueError as e:
            return {"success": False, "message": str(e)}
    
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
    
    # Audit log
    if hasattr(state, "audit_repo") and state.audit_repo:
        state.audit_repo.log_action(
            actor_user_id=admin.user_id,
            action="user_created",
            target_user_id=new_user.user_id,
            detail=f"Admin created user {username} with role {role}",
            context={
                "username": username,
                "user_code": user_code,
                "role": role,
                "manager_id": actual_manager_id,
            },
        )
    
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
    # Get target user and old manager for audit context
    target_user = None
    old_manager_id = None
    if hasattr(state.user_repo, "get_user_by_id"):
        target_user = state.user_repo.get_user_by_id(user_id)
        old_manager_id = target_user.manager_id if target_user else None
    
    if hasattr(state.user_repo, "set_user_manager"):
        actual_manager_id = manager_id if manager_id else None
        state.user_repo.set_user_manager(user_id, actual_manager_id)
        
        # Audit log - use distinct action for assignment vs unassignment
        if hasattr(state, "audit_repo") and state.audit_repo:
            if actual_manager_id:
                # Manager assigned
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="manager_assigned",
                    target_user_id=user_id,
                    detail=f"Assigned manager for {target_user.username if target_user else user_id[:12]}",
                    context={
                        "old_manager_id": old_manager_id,
                        "new_manager_id": actual_manager_id,
                    },
                )
            else:
                # Manager unassigned (set to None)
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="manager_unassigned",
                    target_user_id=user_id,
                    detail=f"Removed manager from {target_user.username if target_user else user_id[:12]}",
                    context={
                        "old_manager_id": old_manager_id,
                    },
                )
        
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
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="force_password_reset",
                target_user_id=user_id,
                detail=f"Forced password reset for {target_user.username}",
            )
        
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
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="clear_password_reset",
                target_user_id=user_id,
                detail=f"Cleared password reset for {target_user.username}",
            )
        
        return {"success": True, "message": "Password reset cleared"}
    return {"success": False, "message": "Could not clear password reset"}


@router.post("/users/{user_id}/assign-temp-password")
async def assign_temp_password(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Assign a temporary password to a user.
    
    Generates a random password, updates the user's credentials, marks password
    reset required, and returns the temp password to the admin (shown once).
    Audit logs the action WITHOUT storing the password or hash.
    """
    import secrets
    import string
    from pulldb.auth.password import hash_password
    
    if user_id == admin.user_id:
        return {"success": False, "message": "Cannot modify your own account"}
    
    # Get the target user
    target_user = None
    if hasattr(state.user_repo, "get_user_by_id"):
        target_user = state.user_repo.get_user_by_id(user_id)
    
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
            actor_user_id=admin.user_id,
            action="temp_password_assigned",
            target_user_id=user_id,
            detail=f"Admin assigned temporary password to {target_user.username}",
        )
    
    return {
        "success": True,
        "message": "Temporary password assigned",
        "temp_password": temp_password,
        "username": target_user.username,
    }


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
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            # Get target user for audit context
            target_user = None
            if hasattr(state.user_repo, "get_user_by_id"):
                target_user = state.user_repo.get_user_by_id(user_id)
            
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="user_hosts_updated",
                target_user_id=user_id,
                detail=f"Updated host assignments for {target_user.username if target_user else user_id[:12]}",
                context={
                    "host_ids": host_ids,
                    "default_host_id": default_host_id,
                },
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
        
        # Count pending API keys for this user
        pending_keys_count = 0
        if hasattr(state, "auth_repo") and hasattr(state.auth_repo, "count_pending_api_keys_by_user"):
            pending_keys_count = state.auth_repo.count_pending_api_keys_by_user(u.user_id)
        
        all_users.append({
            "user_id": u.user_id,
            "username": u.username,
            "user_code": u.user_code,
            "role": u.role.value,
            "manager_id": u.manager_id,
            "manager_username": manager_username,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "disabled": u.disabled_at is not None,
            "locked": getattr(u, "locked_at", None) is not None,
            "status": "locked" if getattr(u, "locked_at", None) else ("disabled" if u.disabled_at else "enabled"),
            "password_reset_pending": password_reset_pending,
            "active_jobs": job_counts.get(u.user_code, 0),
            "pending_keys_count": pending_keys_count,
        })
    
    total_count = len(all_users)
    
    # Compute stats before filtering (for real-time stat pill updates)
    stats = {
        "total": total_count,
        "admins": len([u for u in all_users if u["role"] == "admin"]),
        "managers": len([u for u in all_users if u["role"] == "manager"]),
        "service": len([u for u in all_users if u["role"] == "service"]),
        "active": len([u for u in all_users if not u["disabled"] and not u["locked"]]),
        "disabled": len([u for u in all_users if u["disabled"]]),
        "locked": len([u for u in all_users if u["locked"]]),
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
                # Special handling for manager_username "None" filter
                if col == "manager_username":
                    cell_val = u.get(col) or ""
                    cell_lower = cell_val.lower() if cell_val else "none"
                    if not any(v in cell_lower for v in vals):
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
    if sortColumn in ("username", "user_code", "role", "manager_username", "created_at", "disabled", "status"):
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
        locked = getattr(u, "locked_at", None) is not None
        users_data.append({
            "username": u.username,
            "user_code": u.user_code,
            "role": u.role.value,
            "status": "locked" if locked else ("disabled" if u.disabled_at else "enabled"),
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
            else:
                values.add("None")
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
            "status": "enabled" if h["enabled"] else "disabled",
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
                if col in ("enabled", "status"):
                    status = h["status"]
                    if not any(v in status for v in vals):
                        match = False
                        break
                elif col == "hostname" or col == "display_name":
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
    sortable_cols = ("display_name", "hostname", "enabled", "status", "running_count", "active_restores", "total_restores", "created_at")
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


@router.get("/api/hosts/paginated/distinct")
async def api_hosts_distinct(
    request: Request,
    column: str,
    filter_order: str | None = None,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> list:
    """Get distinct values for host filter dropdowns."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo and hasattr(state.host_repo, "list_hosts"):
        raw_hosts = state.host_repo.list_hosts()
        hosts = [_enrich_host(h, state.job_repo) for h in raw_hosts]
    
    # Build host data with status field
    hosts_data = []
    for h in hosts:
        hosts_data.append({
            "display_name": h["host_alias"] or h["hostname"],
            "hostname": h["hostname"],
            "host_alias": h["host_alias"],
            "enabled": h["enabled"],
            "status": "enabled" if h["enabled"] else "disabled",
        })
    
    # Collect distinct values based on column
    values = set()
    for h in hosts_data:
        if column in ("enabled", "status"):
            values.add(h["status"])
        elif column == "display_name":
            values.add(h["display_name"])
        elif column == "hostname":
            values.add(h["hostname"])
    
    return sorted(values)


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
            "credential_secrets": list_mysql_credential_secrets(),
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
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="host_enabled",
                detail=f"Enabled database host {hostname}",
                context={"hostname": hostname},
            )
    
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
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="host_disabled",
                detail=f"Disabled database host {hostname}",
                context={"hostname": hostname},
            )
    
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
            
            # Audit log
            if hasattr(state, "audit_repo") and state.audit_repo:
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="host_disabled",
                    detail=f"Disabled database host {host.hostname}",
                    context={"host_id": host_id, "hostname": host.hostname},
                )
            
            return {"success": True, "message": f"Host '{host.hostname}' disabled", "enabled": False}
        else:
            if hasattr(state.host_repo, "enable_host"):
                state.host_repo.enable_host(host.hostname)
            
            # Audit log
            if hasattr(state, "audit_repo") and state.audit_repo:
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="host_enabled",
                    detail=f"Enabled database host {host.hostname}",
                    context={"host_id": host_id, "hostname": host.hostname},
                )
            
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


def list_mysql_credential_secrets(prefix: str = "/pulldb/mysql/") -> list[dict[str, str]]:
    """List available MySQL credential secrets from AWS Secrets Manager.

    Args:
        prefix: Secret name prefix to filter (default: /pulldb/mysql/).

    Returns:
        List of dicts with 'name' (full path) and 'display' (short name) keys.
    """
    import boto3

    # Secrets to exclude (service credentials, not host credentials)
    EXCLUDED_NAMES = {"coordination-db", "worker", "loader", "api"}

    try:
        region = get_aws_region()
        client = boto3.client("secretsmanager", region_name=region)
        
        secrets = []
        paginator = client.get_paginator("list_secrets")
        
        for page in paginator.paginate(
            Filters=[{"Key": "name", "Values": [prefix]}],
            SortOrder="asc",
        ):
            for secret in page.get("SecretList", []):
                name = secret["Name"]
                # Create display name (last part of path)
                display = name.split("/")[-1] if "/" in name else name
                # Skip service credentials
                if display.lower() in EXCLUDED_NAMES:
                    continue
                secrets.append({
                    "name": f"aws-secretsmanager:{name}",
                    "display": display,
                })
        
        return secrets
    except Exception:
        # Fail gracefully - return empty list if AWS access fails
        logger.debug("Failed to list MySQL credential secrets from AWS", exc_info=True)
        return []


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
        if max_active_jobs < 0:
            raise ValueError("max_active_jobs cannot be negative")
        if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
            raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        # Check if hostname already exists (pre-validation)
        if hasattr(state, "host_repo") and state.host_repo:
            if hasattr(state.host_repo, "get_host_by_hostname"):
                existing = state.host_repo.get_host_by_hostname(hostname)
                if existing:
                    raise ValueError(f"Host '{hostname}' already exists. Use a different hostname.")

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
            
            # Audit log
            if hasattr(state, "audit_repo") and state.audit_repo:
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="host_created",
                    detail=f"Added database host {hostname}",
                    context={
                        "host_id": host_id,
                        "hostname": hostname,
                        "host_alias": host_alias,
                        "max_running_jobs": max_running_jobs,
                        "max_active_jobs": max_active_jobs,
                    },
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
    secret_updated: int | None = None,
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
            "features/errors/404.html",
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
    elif secret_updated:
        flash_message = "AWS secret updated successfully"
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

    # Resolve credential_ref to get actual host URI and credential data
    resolved_host_uri = None
    credential_error = None
    secret_path = None
    aws_secret_url = None
    credential_data = None  # For editing AWS secret values

    credential_ref = host.get("credential_ref")
    if credential_ref:
        try:
            resolver = CredentialResolver()
            secret_path = resolver.get_secret_path(credential_ref)
            if secret_path:
                aws_secret_url = get_secrets_manager_console_url(secret_path)

            # Try to resolve credentials to get actual host URI and full data
            try:
                creds = resolver.resolve(credential_ref)
                resolved_host_uri = creds.host
                # Store credential data for editing (password masked)
                credential_data = {
                    "host": creds.host,
                    "port": creds.port,
                    "username": creds.username or "",
                }
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
        except Exception:  # User assignment table may not exist in all deployments
            logger.debug("Failed to fetch assigned users (table may not exist)", exc_info=True)
    elif hasattr(state, "auth_repo") and state.auth_repo:
        # For simulated mode, try get_users_for_host if available
        if hasattr(state.auth_repo, "get_users_for_host"):
            try:
                assigned_users = state.auth_repo.get_users_for_host(host["id"])
            except Exception:  # Graceful degradation for simulation mode
                logger.debug("Failed to get users for host in simulation", exc_info=True)

    return {
        **host,
        "running_count": running_count,
        "queued_count": queued_count,
        "active_restores": running_count + queued_count,
        "total_restores": total_restores,
        "resolved_host_uri": resolved_host_uri,
        "credential_error": credential_error,
        "credential_data": credential_data,
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
        if max_active_jobs < 0:
            raise ValueError("max_active_jobs cannot be negative")
        if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
            raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        existing = None
        if hasattr(state, "host_repo") and state.host_repo:
            # First verify host exists
            if hasattr(state.host_repo, "get_host_by_id"):
                existing = state.host_repo.get_host_by_id(host_id)
                if not existing:
                    raise ValueError(f"Host not found: {host_id}")
            
            # Use update_host_config if available, else fall back to raw SQL
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
            
            # Audit log
            if hasattr(state, "audit_repo") and state.audit_repo:
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="host_updated",
                    detail=f"Updated database host {existing.hostname if existing else host_id[:12]}",
                    context={
                        "host_id": host_id,
                        "hostname": existing.hostname if existing else None,
                        "host_alias": host_alias,
                        "max_running_jobs": max_running_jobs,
                        "max_active_jobs": max_active_jobs,
                    },
                )

        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?updated=1", status_code=303
        )
    except Exception as e:
        error_msg = url_quote(str(e))
        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?error={error_msg}", status_code=303
        )


@router.post("/hosts/{host_id}/update-secret")
async def update_host_secret(
    host_id: str,
    secret_host: str = Form(...),
    secret_port: int = Form(3306),
    secret_username: str = Form(...),
    secret_password: str = Form(None),
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    """Update MySQL credentials - syncs both MySQL server and AWS Secrets Manager.
    
    This endpoint:
    1. Validates current credentials can connect to MySQL
    2. Checks for duplicate MySQL host (no two hosts can point to same server)
    3. Detects what changed (password, username, or both)
    4. Updates MySQL server first (ALTER USER or CREATE/DROP for rename)
    5. Updates AWS Secrets Manager only after MySQL succeeds
    
    FAIL HARD: If MySQL update succeeds but AWS fails, returns error with
    manual fix instructions (no automatic rollback).
    """
    from pulldb.infra.secrets import (
        CredentialResolver,
        safe_upsert_single_secret,
    )
    from pulldb.infra.mysql_provisioning import sync_mysql_credentials

    try:
        # Get host to find its credential_ref
        host = None
        if hasattr(state, "host_repo") and state.host_repo:
            if hasattr(state.host_repo, "get_host_by_id"):
                host = state.host_repo.get_host_by_id(host_id)

        if not host:
            raise ValueError("Host not found")

        credential_ref = host.credential_ref
        if not credential_ref or not credential_ref.startswith("aws-secretsmanager:"):
            raise ValueError("Host does not have an AWS Secrets Manager credential reference")

        # Extract secret path from credential_ref
        resolver = CredentialResolver()
        secret_path = resolver.get_secret_path(credential_ref)
        if not secret_path:
            raise ValueError("Could not determine secret path from credential reference")

        # Get existing credentials - REQUIRED for sync
        try:
            existing_creds = resolver.resolve(credential_ref)
        except Exception as e:
            raise ValueError(
                f"Cannot read current credentials from AWS: {e}. "
                "Fix the secret in AWS console first, or re-provision the host."
            )

        # Determine what changed
        current_username = existing_creds.username
        current_password = existing_creds.password
        current_host = existing_creds.host
        current_port = existing_creds.port

        # Detect changes
        host_changed = secret_host != current_host
        port_changed = secret_port != current_port

        # Check for duplicate MySQL host if host/port changed
        if host_changed or port_changed:
            # Get all other hosts and check their credentials
            all_hosts = state.host_repo.get_all_hosts()
            for other_host in all_hosts:
                if other_host.id == host_id:
                    continue  # Skip self
                if not other_host.credential_ref:
                    continue
                try:
                    other_creds = resolver.resolve(other_host.credential_ref)
                    if other_creds.host == secret_host and other_creds.port == secret_port:
                        raise ValueError(
                            f"MySQL server {secret_host}:{secret_port} is already in use "
                            f"by host '{other_host.hostname}'. Each host must point to a unique MySQL server."
                        )
                except ValueError:
                    # Re-raise our duplicate error
                    raise
                except Exception:
                    # Skip hosts with unresolvable credentials - likely misconfigured
                    logger.debug("Skipping host %s with unresolvable credentials", other_host.hostname, exc_info=True)
                    continue

        username_changed = secret_username != current_username
        password_changed = bool(secret_password) and secret_password != current_password

        # If username or password changed, sync to MySQL first
        if username_changed or password_changed:
            # Sync MySQL credentials
            sync_result = sync_mysql_credentials(
                mysql_host=current_host,  # Use current host to connect
                mysql_port=current_port,
                current_username=current_username,
                current_password=current_password,
                new_username=secret_username if username_changed else None,
                new_password=secret_password if password_changed else None,
            )

            if not sync_result.success:
                error_detail = sync_result.error or sync_result.message
                suggestions = sync_result.suggestions or []
                raise ValueError(
                    f"MySQL credential update failed: {error_detail}. "
                    f"Suggestions: {'; '.join(suggestions)}"
                )

        # Build secret data for AWS
        password_to_use = secret_password if secret_password else current_password
        secret_data = {
            "host": secret_host,
            "port": secret_port,
            "username": secret_username,
            "password": password_to_use,
        }

        # Update AWS Secrets Manager
        result = safe_upsert_single_secret(
            secret_path=secret_path,
            secret_data=secret_data,
            update_only=True,
        )

        if not result.success:
            # MySQL was updated but AWS failed - provide manual fix instructions
            if username_changed or password_changed:
                raise ValueError(
                    f"WARNING: MySQL credentials were updated but AWS Secrets Manager failed: {result.error}. "
                    f"MANUAL FIX REQUIRED: Update AWS secret '{secret_path}' with username='{secret_username}' "
                    f"and the new password via AWS console."
                )
            raise ValueError(result.error or "Failed to update AWS secret")

        # Build success message
        changes = []
        if username_changed:
            changes.append("username")
        if password_changed:
            changes.append("password")
        if host_changed:
            changes.append("host")
        if port_changed:
            changes.append("port")
        
        change_msg = f"Updated: {', '.join(changes)}" if changes else "No changes"

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="host_secret_updated",
                detail=f"Updated credentials for host {host.hostname}: {change_msg}",
                context={
                    "host_id": host_id,
                    "hostname": host.hostname,
                    "changes": changes,
                    "username_changed": username_changed,
                    "password_changed": password_changed,
                    "host_changed": host_changed,
                    "port_changed": port_changed,
                },
            )

        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?secret_updated=1&msg={url_quote(change_msg)}", 
            status_code=303
        )
    except Exception as e:
        error_msg = url_quote(str(e))
        return RedirectResponse(
            url=f"/web/admin/hosts/{host_id}?error={error_msg}", status_code=303
        )


@router.get("/hosts/{host_id}/delete-preview")
async def host_delete_preview(
    host_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Get preview data for host deletion.
    
    Returns information about what will be affected by deleting the host:
    - Users assigned to this host (will lose access)
    - Total historical job count
    - Active job count (blocks deletion)
    - Host details for confirmation
    
    The frontend uses this to populate the delete confirmation modal.
    """
    try:
        if not hasattr(state, "host_repo") or not state.host_repo:
            return {"success": False, "error": "Host repository not available"}
        
        # Get host details
        host = state.host_repo.get_host_by_id(host_id)
        if not host:
            return {"success": False, "error": "Host not found"}
        
        hostname = host.hostname
        host_alias = host.host_alias or hostname
        
        # Count assigned users
        assigned_user_count = 0
        assigned_users: list[dict] = []
        if hasattr(state, "auth_repo") and state.auth_repo:
            if hasattr(state.auth_repo, "count_users_for_host"):
                assigned_user_count = state.auth_repo.count_users_for_host(host_id)
            if hasattr(state.auth_repo, "get_users_for_host"):
                assigned_users = state.auth_repo.get_users_for_host(host_id)
        
        # Count jobs
        total_job_count = 0
        active_job_count = 0
        if state.job_repo:
            if hasattr(state.job_repo, "count_jobs_by_host"):
                total_job_count = state.job_repo.count_jobs_by_host(hostname)
            if hasattr(state.job_repo, "get_active_jobs"):
                active_jobs = state.job_repo.get_active_jobs()
                active_job_count = len([j for j in active_jobs if getattr(j, "dbhost", None) == hostname])
        
        # Check if host is enabled
        can_delete = not host.enabled and active_job_count == 0
        block_reason = None
        if host.enabled:
            block_reason = "Host must be disabled before deletion"
        elif active_job_count > 0:
            block_reason = f"Host has {active_job_count} active job(s). Wait for completion or cancel them."
        
        return {
            "success": True,
            "host_id": host_id,
            "hostname": hostname,
            "host_alias": host_alias,
            "enabled": host.enabled,
            "can_delete": can_delete,
            "block_reason": block_reason,
            "assigned_user_count": assigned_user_count,
            "assigned_users": assigned_users[:10],  # Limit to 10 for UI
            "total_job_count": total_job_count,
            "active_job_count": active_job_count,
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/hosts/{host_id}/delete")
async def delete_host(
    host_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    """Full host deletion with cleanup.
    
    This endpoint performs a complete cleanup:
    1. Validates host is disabled
    2. Validates no active jobs exist for this host
    3. Attempts to DROP USER on the target MySQL server (best effort)
    4. Immediately deletes the AWS Secrets Manager secret (no recovery)
    5. Hard-deletes the db_hosts record
    
    Steps 3-4 are best-effort: failures are logged but don't block deletion.
    The record is always deleted if the host is disabled with no active jobs.
    """
    from pulldb.infra.secrets import CredentialResolver
    from pulldb.infra.mysql_provisioning import drop_mysql_user
    import boto3

    cleanup_warnings: list[str] = []

    try:
        if not hasattr(state, "host_repo") or not state.host_repo:
            raise ValueError("Host repository not available")

        # Get host by ID first
        host = state.host_repo.get_host_by_id(host_id)
        if not host:
            raise ValueError("Host not found")
        hostname = host.hostname
        host_alias = host.host_alias or hostname

        # Check host is disabled - HARD BLOCK
        if host.enabled:
            raise ValueError(
                f"Host '{host_alias}' must be disabled before deletion. "
                "Disable the host first."
            )

        # Check for active jobs - HARD BLOCK
        if state.job_repo and hasattr(state.job_repo, "get_active_jobs"):
            active_jobs = state.job_repo.get_active_jobs()
            host_jobs = [j for j in active_jobs if getattr(j, "dbhost", None) == hostname]
            if host_jobs:
                raise ValueError(
                    f"Cannot delete host with {len(host_jobs)} active job(s). "
                    "Wait for jobs to complete or cancel them first."
                )

        # Step 1: Try to resolve credentials and DROP MySQL user
        credential_ref = host.credential_ref
        mysql_user = None
        mysql_host = None
        mysql_port = None
        mysql_password = None
        resolver = None

        if credential_ref and credential_ref.startswith("aws-secretsmanager:"):
            try:
                resolver = CredentialResolver()
                creds = resolver.resolve(credential_ref)
                mysql_user = creds.username
                mysql_host = creds.host
                mysql_port = creds.port
                mysql_password = creds.password

                # Try to drop the MySQL user using its own credentials
                # This works if the user has DROP USER privilege on itself
                drop_result = drop_mysql_user(
                    mysql_host=mysql_host,
                    mysql_port=mysql_port,
                    admin_username=mysql_user,
                    admin_password=mysql_password,
                    user_to_drop=mysql_user,
                )

                if not drop_result.success:
                    cleanup_warnings.append(
                        f"Could not drop MySQL user '{mysql_user}': {drop_result.error}. "
                        f"Manual cleanup may be required on {mysql_host}:{mysql_port}."
                    )
            except Exception as e:
                cleanup_warnings.append(
                    f"Could not resolve credentials for MySQL cleanup: {e}. "
                    "Manual MySQL user cleanup may be required."
                )

            # Step 2: Delete the AWS secret IMMEDIATELY (no recovery window)
            if resolver:
                try:
                    secret_path = resolver.get_secret_path(credential_ref)
                    if secret_path:
                        client = resolver._get_secrets_manager_client()
                        # Force delete without recovery window (immediate)
                        client.delete_secret(
                            SecretId=secret_path,
                            ForceDeleteWithoutRecovery=True,
                        )
                except Exception as e:
                    # Check if it's a ResourceNotFoundException (secret doesn't exist)
                    error_name = getattr(type(e), "__name__", "")
                    if "ResourceNotFound" in error_name or "ResourceNotFound" in str(e):
                        # Secret already doesn't exist - that's fine
                        pass
                    else:
                        cleanup_warnings.append(
                            f"Could not delete AWS secret: {e}. "
                            f"Manual cleanup may be required in AWS Secrets Manager."
                        )

        # Step 3: Hard delete the host record - this should always succeed
        state.host_repo.hard_delete_host(host_id)

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="host_deleted",
                detail=f"Deleted database host {host_alias} ({hostname})",
                context={
                    "host_id": host_id,
                    "hostname": hostname,
                    "host_alias": host_alias,
                    "cleanup_warnings": cleanup_warnings,
                },
            )

        # Build success message with any warnings
        if cleanup_warnings:
            warning_msg = " | ".join(cleanup_warnings)
            return RedirectResponse(
                url=f"/web/admin/hosts?deleted=1&warnings={url_quote(warning_msg)}",
                status_code=303,
            )

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
    - pulldb_db_valid: pulldb_service database exists
    - sproc_valid: pulldb_atomic_rename procedure exists
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
                connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_MONITOR,
            )
            checks["connection_valid"] = True
            checks["connection_message"] = f"Connected to {creds.host}:{creds.port}"
        except mysql.connector.Error as e:
            checks["connection_message"] = f"Connection failed: {e}"
            result["message"] = "MySQL connection failed"
            if test_conn:
                test_conn.close()
            return result

        # Check 3: pulldb_service database exists
        try:
            cursor = test_conn.cursor()
            cursor.execute("SHOW DATABASES LIKE 'pulldb_service'")
            db_exists = cursor.fetchone()
            cursor.close()
            if db_exists:
                checks["pulldb_db_valid"] = True
                checks["pulldb_db_message"] = "pulldb_service database exists"
            else:
                checks["pulldb_db_message"] = "pulldb_service database not found - create with: CREATE DATABASE pulldb_service;"
        except mysql.connector.Error as e:
            checks["pulldb_db_message"] = f"Could not check database: {e}"

        # Check 4: Stored procedure exists (only if pulldb_service database exists)
        if checks["pulldb_db_valid"]:
            try:
                cursor = test_conn.cursor()
                cursor.execute("""
                    SELECT ROUTINE_NAME FROM information_schema.ROUTINES 
                    WHERE ROUTINE_SCHEMA = 'pulldb_service' 
                    AND ROUTINE_NAME = 'pulldb_atomic_rename' 
                    AND ROUTINE_TYPE = 'PROCEDURE'
                """)
                sproc_exists = cursor.fetchone()
                cursor.close()
                if sproc_exists:
                    checks["sproc_valid"] = True
                    checks["sproc_message"] = "pulldb_atomic_rename procedure found"
                else:
                    # Auto-deploy the stored procedure
                    from pulldb.infra.mysql_provisioning import deploy_stored_procedure
                    deploy_result = deploy_stored_procedure(
                        host=creds.host,
                        port=creds.port,
                        username=creds.username or "pulldb_loader",
                        password=creds.password,
                        database="pulldb_service",
                    )
                    if deploy_result.success:
                        checks["sproc_valid"] = True
                        checks["sproc_message"] = "pulldb_atomic_rename procedure deployed successfully"
                    else:
                        checks["sproc_message"] = f"Failed to deploy procedure: {deploy_result.error or deploy_result.message}"
            except mysql.connector.Error as e:
                checks["sproc_message"] = f"Could not check procedure: {e}"
        else:
            checks["sproc_message"] = "Skipped - pulldb_service database required first"

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
                missing.append("pulldb_service database")
            if not checks["sproc_valid"]:
                missing.append("stored procedure")
            result["message"] = f"Connected successfully, but missing: {', '.join(missing)}"

        return result

    except Exception as e:
        result["message"] = str(e)
        return result


# =============================================================================
# Host Secret Rotation - API endpoint for Web UI
# =============================================================================


@router.post("/api/hosts/{host_id}/rotate-secret")
async def api_rotate_host_secret(
    host_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Rotate the MySQL password for a host and update AWS Secrets Manager.
    
    This is the Web UI API endpoint that wraps the secret rotation service.
    Returns JSON with rotation result, timing information, and any error details.
    """
    from pulldb.domain.services.secret_rotation import rotate_host_secret
    import time

    result_data: dict[str, Any] = {
        "success": False,
        "message": "",
        "timing": {},
    }

    try:
        # Parse request body
        body = await request.json()
        password_length = body.get("password_length", 32)

        # Get host using repository method
        host_obj = None
        if hasattr(state, "host_repo") and state.host_repo:
            host_obj = state.host_repo.get_host_by_id(host_id)

        if not host_obj:
            result_data["message"] = f"Host not found: {host_id}"
            return result_data

        # Call the rotation service
        rotation_result = rotate_host_secret(
            host_id=host_id,
            hostname=host_obj.hostname,
            credential_ref=host_obj.credential_ref,
            password_length=password_length,
        )

        # Build response
        result_data["success"] = rotation_result.success
        result_data["message"] = rotation_result.message
        result_data["timing"] = rotation_result.timing

        if not rotation_result.success:
            result_data["phase"] = rotation_result.phase
            result_data["error"] = rotation_result.error
            if rotation_result.suggestions:
                result_data["suggestions"] = rotation_result.suggestions
            result_data["manual_fix_required"] = rotation_result.manual_fix_required
            if rotation_result.manual_fix_instructions:
                result_data["manual_fix_instructions"] = rotation_result.manual_fix_instructions

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="host_secret_rotated" if rotation_result.success else "host_secret_rotation_failed",
                detail=f"{'Rotated' if rotation_result.success else 'Failed to rotate'} secret for host {host_obj.hostname}",
                context={
                    "host_id": host_id,
                    "hostname": host_obj.hostname,
                    "credential_ref": host_obj.credential_ref,
                    "success": rotation_result.success,
                    "phase": rotation_result.phase,
                },
            )

        return result_data

    except Exception as e:
        result_data["message"] = str(e)
        return result_data


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
    
    This endpoint uses the HostProvisioningService to:
    1. Check if host alias already exists (reuses if so)
    2. Test admin MySQL connection
    3. Create pulldb_loader user (or updates password)
    4. Create pulldb database if needed
    5. Deploy stored procedure
    6. Create AWS secret (only if new, never overwrites others)
    7. Register/update host in database
    
    On failure, rolls back only newly-created resources:
    - Deletes AWS secret only if it was created in this operation
    - Leaves pre-existing users/databases/secrets untouched
    
    Returns JSON with step-by-step results for UI display.
    """
    from pulldb.infra.factory import is_simulation_mode, get_provisioning_service
    
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
    
    # Check for simulation mode - handle specially
    if is_simulation_mode():
        import uuid as uuid_module
        
        steps: list[dict[str, Any]] = []
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "host_id": None,
            "steps": steps,
            "rollback_performed": False,
        }
        
        steps.append({"name": "Check Host", "success": True, 
                     "message": f"New host '{host_alias}'", "details": None})
        steps.append({"name": "Check Secret", "success": True,
                     "message": "No existing credentials (simulated)",
                     "details": f"Will create: /pulldb/mysql/{host_alias}"})
        steps.append({"name": "MySQL Setup", "success": True,
                     "message": "User created, database exists, procedure deployed (simulated)",
                     "details": "User: pulldb_loader"})
        steps.append({"name": "AWS Secret", "success": True,
                     "message": "Credentials created (simulated)",
                     "details": f"Path: /pulldb/mysql/{host_alias}"})
        
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
                max_active_jobs=max_active_jobs,
            )
            steps.append({"name": "Register Host", "success": True,
                         "message": "Host registered successfully (simulated)",
                         "details": None})
        
        result["success"] = True
        result["host_id"] = host_id
        result["message"] = "Host provisioned successfully (simulation mode)"
        result["simulation_mode"] = True
        return result
    
    # Use HostProvisioningService for real mode
    service = get_provisioning_service(admin.user_id)
    
    prov_result = service.provision_host(
        host_alias=host_alias,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        admin_username=admin_username,
        admin_password=admin_password,
        max_running_jobs=max_running_jobs,
        max_active_jobs=max_active_jobs,
    )
    
    # Convert service result to API response format
    steps_out: list[dict[str, Any]] = []
    if prov_result.steps:
        for step in prov_result.steps:
            steps_out.append({
                "name": step.name,
                "success": step.success,
                "message": step.message,
                "details": step.details,
            })
    
    return {
        "success": prov_result.success,
        "message": prov_result.message,
        "host_id": prov_result.host_id,
        "steps": steps_out,
        "rollback_performed": prov_result.rollback_performed,
    }


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


def get_settings_drift(db_settings: dict[str, str]) -> list[dict]:
    """Detect settings that differ between database and environment.

    Compares database values against current environment variables.
    Only checks settings defined in SETTING_REGISTRY with a database value.

    Args:
        db_settings: Dict of setting_key -> value from database

    Returns:
        List of dicts with keys: setting_key, db_value, env_value, description
        Only includes settings where db_value != env_value
    """
    differences = []
    for key, meta in SETTING_REGISTRY.items():
        db_value = db_settings.get(key)
        if db_value is None:
            # No database value, nothing to drift from
            continue

        env_value = _os.getenv(meta.env_var)
        if env_value is None:
            # env not set, but db has value = drift
            differences.append({
                "setting_key": key,
                "db_value": db_value,
                "env_value": "(not set)",
                "env_var": meta.env_var,
                "description": meta.description,
            })
        elif db_value != env_value:
            # Different values = drift
            differences.append({
                "setting_key": key,
                "db_value": db_value,
                "env_value": env_value,
                "env_var": meta.env_var,
                "description": meta.description,
            })

    return differences


def check_settings_drift(settings_repo: Any) -> list[dict]:
    """Check for settings drift using a settings repository.

    Wrapper around get_settings_drift that handles repository access.

    Args:
        settings_repo: SettingsRepository instance

    Returns:
        List of drift entries (empty if no drift detected)
    """
    if settings_repo is None:
        return []

    try:
        db_settings = settings_repo.get_all_settings()
    except Exception:
        # Graceful degradation: can't check drift if DB access fails
        logger.debug("Failed to get settings from DB for drift check", exc_info=True)
        return []

    return get_settings_drift(db_settings)


@router.get("/settings-sync", response_class=HTMLResponse)
async def settings_sync_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Show settings sync notification page.

    Displays settings that differ between database and environment,
    requiring admin acknowledgment before continuing.
    """
    from fastapi.concurrency import run_in_threadpool

    # Get drift information
    drift_items = []
    if hasattr(state, "settings_repo") and state.settings_repo:
        drift_items = await run_in_threadpool(
            check_settings_drift, state.settings_repo
        )

    return templates.TemplateResponse(
        "features/admin/settings_sync.html",
        {
            "request": request,
            "user": user,
            "drift_items": drift_items,
            "active_nav": None,  # No nav highlighting for modal-like pages
        },
    )


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
            # Graceful degradation: audit logs are informational, page works without
            logger.debug("Failed to get audit logs for settings page", exc_info=True)

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
            # Audit is best-effort - don't fail main operation
            logger.debug("Failed to log audit for setting update", exc_info=True)

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
            # Audit is best-effort - don't fail main operation
            logger.debug("Failed to log audit for setting reset", exc_info=True)

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
                # Audit is best-effort - don't fail main operation
                logger.debug("Failed to log audit for directory creation", exc_info=True)

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
    sortColumn: str | None = None,
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
    sortColumn: str | None = None,
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
    scan_error: str | None = None
    try:
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
    except Exception as e:
        scan_error = f"Failed to scan hosts: {e}"

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
        **(({"error": scan_error} if scan_error else {})),
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
    try:
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
    except Exception:
        # Graceful degradation: return empty list for filter options
        logger.debug("Failed to detect orphaned databases for distinct values", exc_info=True)
        return []  # Return empty list on error - UI will show empty state
    
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
# User Orphans (databases from deleted users)
# =============================================================================


@router.get("/user-orphans", response_class=HTMLResponse)
async def user_orphans_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    delete_success: int | None = None,
    delete_error: str | None = None,
) -> HTMLResponse:
    """Render the user-orphan databases preview page.
    
    User orphans are databases that belong to users who no longer exist.
    The user_code prefix in the database name doesn't match any user in auth_users.
    """
    flash_message = None
    flash_type = None
    if delete_success is not None:
        flash_message = f"Successfully deleted {delete_success} orphan database(s)"
        flash_type = "success"
    elif delete_error:
        flash_message = f"Orphan deletion failed: {delete_error}"
        flash_type = "error"

    return templates.TemplateResponse(
        "features/admin/user_orphans.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "breadcrumbs": get_breadcrumbs("admin_user_orphans"),
        },
    )


@router.get("/api/user-orphan-candidates")
async def api_user_orphan_candidates(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = Query(50, ge=10, le=200, description="Page size"),
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict[str, Any]:
    """Get paginated user-orphan candidates for LazyTable.
    
    Returns all user-orphan databases from all hosts in a flat list.
    User orphans are databases with user_codes not in auth_users.
    """
    from pulldb.worker.cleanup import (
        detect_user_orphaned_databases,
        get_all_user_codes,
    )
    from datetime import datetime

    # Get all valid user codes
    valid_user_codes: frozenset[str] = frozenset()
    if hasattr(state.user_repo, "list_users"):
        valid_user_codes = get_all_user_codes(state.user_repo)

    # Collect all user-orphans from all hosts
    all_orphans: list[dict[str, Any]] = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_user_orphaned_databases(
                dbhost=host.hostname,
                host_repo=state.host_repo,
                valid_user_codes=valid_user_codes,
            )
            # Skip hosts with connection errors
            if isinstance(result, str):
                continue
            if result.error:
                continue
            for oc in result.orphans:
                all_orphans.append({
                    "database_name": oc.database_name,
                    "dbhost": oc.dbhost,
                    "extracted_user_code": oc.extracted_user_code,
                    "restored_at": oc.restored_at.isoformat() if oc.restored_at else None,
                    "restored_by": oc.restored_by,
                    "size_mb": oc.size_mb,
                })

    total_count = len(all_orphans)

    # Extract filter params from query string
    text_filters: dict[str, list[str]] = {}
    date_after: dict[str, str] = {}
    date_before: dict[str, str] = {}
    date_columns = ["restored_at"]
    
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            
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
            
            text_filters[col_key] = [v.strip().lower() for v in value.split(',') if v.strip()]

    # Apply filters
    if text_filters or date_after or date_before:
        filtered_orphans: list[dict[str, Any]] = []
        for orphan_item in all_orphans:
            match = True
            
            # Check text filters
            for col_key, filter_vals in text_filters.items():
                cell_val = str(orphan_item.get(col_key, "")).lower()
                if not any(fv in cell_val for fv in filter_vals):
                    match = False
                    break
            
            # Check date filters
            if match:
                for col_key, after_str in date_after.items():
                    date_val = orphan_item.get(col_key)
                    if date_val:
                        try:
                            cell_dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
                            after_dt = datetime.fromisoformat(after_str)
                            if cell_dt < after_dt:
                                match = False
                        except (ValueError, TypeError):
                            pass
            
            if match:
                for col_key, before_str in date_before.items():
                    date_val = orphan_item.get(col_key)
                    if date_val:
                        try:
                            cell_dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
                            before_dt = datetime.fromisoformat(before_str)
                            if cell_dt > before_dt:
                                match = False
                        except (ValueError, TypeError):
                            pass
            
            if match:
                filtered_orphans.append(orphan_item)
        
        all_orphans = filtered_orphans

    filtered_count = len(all_orphans)

    # Apply sorting
    if sortColumn and sortDirection in ("asc", "desc"):
        reverse = (sortDirection == "desc")
        all_orphans.sort(
            key=lambda x: (x.get(sortColumn) is None, x.get(sortColumn) or ""),
            reverse=reverse,
        )

    # Apply pagination
    start_idx = page * pageSize
    end_idx = start_idx + pageSize
    page_data = all_orphans[start_idx:end_idx]

    return {
        "data": page_data,
        "total": total_count,
        "filtered": filtered_count,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/api/user-orphan-candidates/distinct")
async def api_user_orphan_distinct_values(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    column: str = Query(..., description="Column to get distinct values for"),
) -> dict[str, Any]:
    """Get distinct values for a column in user-orphan candidates.
    
    Used by LazyTable multi-select filters.
    """
    from pulldb.worker.cleanup import (
        detect_user_orphaned_databases,
        get_all_user_codes,
    )

    valid_user_codes: frozenset[str] = frozenset()
    if hasattr(state.user_repo, "list_users"):
        valid_user_codes = get_all_user_codes(state.user_repo)

    all_values: set[str] = set()
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
        for host in hosts:
            result = detect_user_orphaned_databases(
                dbhost=host.hostname,
                host_repo=state.host_repo,
                valid_user_codes=valid_user_codes,
            )
            if isinstance(result, str) or result.error:
                continue
            for oc in result.orphans:
                if column == "dbhost":
                    all_values.add(oc.dbhost)
                elif column == "extracted_user_code":
                    all_values.add(oc.extracted_user_code)
                elif column == "database_name":
                    all_values.add(oc.database_name)

    return {
        "values": sorted(list(all_values)),
        "column": column,
    }


@router.post("/user-orphans/scan")
async def start_user_orphan_scan(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Start a background task to scan all hosts for user-orphan databases.
    
    Creates an async admin task that will be processed by the worker.
    Returns immediately with task_id for status polling.
    """
    from pulldb.domain.models import AdminTaskType
    from pulldb.infra.mysql import AdminTaskRepository
    
    try:
        body = await request.json()
        specific_hosts = body.get("hosts")  # Optional: limit to specific hosts
        
        admin_task_repo = AdminTaskRepository(state.job_repo.pool)
        
        parameters = {}
        if specific_hosts:
            parameters["hosts"] = specific_hosts
        
        try:
            task_id = admin_task_repo.create_task(
                task_type=AdminTaskType.SCAN_USER_ORPHANS,
                requested_by=admin.user_id,
                target_user_id=None,
                parameters=parameters if parameters else None,
            )
        except ValueError as e:
            # A task is already running
            return {"success": False, "message": str(e)}
        
        return {
            "success": True,
            "message": "User orphan scan task created",
            "task_id": task_id,
        }
    except Exception as e:
        return {"success": False, "message": f"Scan failed: {e}"}


@router.post("/user-orphans/delete")
async def delete_user_orphan(
    dbhost: str = Form(...),
    database_name: str = Form(...),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Delete a user-orphan database."""
    from pulldb.worker.cleanup import admin_delete_user_orphan_databases
    
    if hasattr(state, "host_repo") and state.host_repo:
        admin_delete_user_orphan_databases(
            dbhost=dbhost,
            database_names=[database_name],
            host_repo=state.host_repo,
            admin_user=user.username,
        )
    
    return RedirectResponse(
        url="/web/admin/user-orphans?delete_success=1",
        status_code=303,
    )


@router.post("/jobs/{job_id}/force-complete-delete")
async def force_complete_deletion(
    job_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Force-complete a stuck job deletion when host unavailable.
    
    Used when a job is stuck in 'deleting' status because the host
    was deleted from the system. Marks the job as deleted without
    attempting database verification.
    
    Args:
        job_id: Job UUID to force-complete.
        state: API state with repositories.
        admin: Admin user performing the action.
    
    Returns:
        JSON response with success status and message.
    """
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return {"success": False, "message": "Job not found"}
    
    if job.status not in ("deleting", "failed"):
        return {
            "success": False,
            "message": f"Job not stuck in deletion (status: {job.status})"
        }
    
    # Mark as deleted with admin override
    state.job_repo.mark_job_deleted(
        job_id,
        f"Force-completed by admin {admin.username} - host unavailable"
    )
    state.job_repo.append_job_event(
        job_id,
        "force_deleted",
        f'{{"admin": "{admin.username}", "reason": "host_unavailable"}}'
    )
    
    # Audit log
    if hasattr(state, "audit_repo") and state.audit_repo:
        state.audit_repo.log_action(
            actor_user_id=admin.user_id,
            action="job_force_delete",
            target_user_id=job.owner_user_id,
            detail=f"Force-completed deletion for job {job_id[:12]} (host: {job.dbhost})",
            context={
                "job_id": job_id,
                "target": job.target,
                "dbhost": job.dbhost,
                "previous_status": job.status,
            }
        )
    
    return {
        "success": True,
        "message": f"Job {job_id[:12]} marked as deleted"
    }


@router.post("/user-orphans/execute")
async def execute_user_orphan_deletion(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    """Execute bulk deletion of selected user-orphan databases.
    
    Expects form data with selected_orphans as JSON array of 
    [{dbhost: string, database_name: string}, ...]
    """
    from pulldb.worker.cleanup import admin_delete_user_orphan_databases
    
    form_data = await request.form()
    selected_orphans_raw = form_data.get("selected_orphans", "[]")
    # form_data.get() can return UploadFile | str; ensure we have str
    selected_orphans_json = str(selected_orphans_raw) if selected_orphans_raw else "[]"
    
    try:
        selected_orphans = json.loads(selected_orphans_json)
    except json.JSONDecodeError:
        return RedirectResponse(
            url="/web/admin/user-orphans?delete_error=Invalid+selection+format",
            status_code=303,
        )
    
    if not selected_orphans:
        return RedirectResponse(
            url="/web/admin/user-orphans?delete_error=No+databases+selected",
            status_code=303,
        )
    
    # Group by host for efficient deletion
    by_host: dict[str, list[str]] = {}
    for item in selected_orphans:
        host = item.get("dbhost")
        db_name = item.get("database_name")
        if host and db_name:
            if host not in by_host:
                by_host[host] = []
            by_host[host].append(db_name)
    
    total_deleted = 0
    total_failed = 0
    
    if hasattr(state, "host_repo") and state.host_repo:
        for dbhost, db_names in by_host.items():
            results = admin_delete_user_orphan_databases(
                dbhost=dbhost,
                database_names=db_names,
                host_repo=state.host_repo,
                admin_user=admin.username,
            )
            for success in results.values():
                if success:
                    total_deleted += 1
                else:
                    total_failed += 1
    
    if total_failed > 0:
        return RedirectResponse(
            url=f"/web/admin/user-orphans?delete_success={total_deleted}&delete_error={total_failed}+databases+failed",
            status_code=303,
        )
    
    return RedirectResponse(
        url=f"/web/admin/user-orphans?delete_success={total_deleted}",
        status_code=303,
    )


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
            light_json = state.settings_repo.get_setting("light_theme_schema")
            if light_json:
                light_schema = ColorSchema.from_json(light_json)
        except (ValueError, TypeError, KeyError):
            pass  # Use default on error
        
        try:
            dark_json = state.settings_repo.get_setting("dark_theme_schema")
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


@router.get("/api/saved-theme-schemas")
async def get_saved_theme_schemas(
    state: Any = Depends(get_api_state),
) -> dict:
    """Get the currently saved theme schemas from the database.
    
    Returns the light and dark theme schemas as currently saved,
    falling back to defaults if not yet customized.
    
    Returns:
        Dict with 'light' and 'dark' keys containing saved schemas.
    """
    from pulldb.domain.color_schemas import LIGHT_PRESETS, DARK_PRESETS, ColorSchema
    
    # Start with complete defaults for each mode
    light_schema = LIGHT_PRESETS["Default"]
    dark_schema = DARK_PRESETS["Default"]
    
    if hasattr(state, "settings_repo") and state.settings_repo:
        try:
            light_json = state.settings_repo.get_setting("light_theme_schema")
            if light_json:
                # Merge saved values with LIGHT defaults (not dataclass defaults)
                light_schema = ColorSchema.from_json_with_defaults(
                    light_json, LIGHT_PRESETS["Default"]
                )
        except (ValueError, TypeError, KeyError):
            pass  # Use default on error
        
        try:
            dark_json = state.settings_repo.get_setting("dark_theme_schema")
            if dark_json:
                # Merge saved values with DARK defaults (not light dataclass defaults!)
                dark_schema = ColorSchema.from_json_with_defaults(
                    dark_json, DARK_PRESETS["Default"]
                )
        except (ValueError, TypeError, KeyError):
            pass  # Use default on error
    
    return {
        "light": _schema_to_dict(light_schema),
        "dark": _schema_to_dict(dark_schema),
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
    
    # Start with complete defaults for each mode
    light_schema = LIGHT_PRESETS["Default"]
    dark_schema = DARK_PRESETS["Default"]
    
    if hasattr(state, "settings_repo") and state.settings_repo:
        try:
            light_json = state.settings_repo.get_setting("light_theme_schema")
            if light_json:
                # Merge saved values with LIGHT defaults
                light_schema = ColorSchema.from_json_with_defaults(
                    light_json, LIGHT_PRESETS["Default"]
                )
        except (ValueError, TypeError, KeyError):
            pass
        
        try:
            dark_json = state.settings_repo.get_setting("dark_theme_schema")
            if dark_json:
                # Merge saved values with DARK defaults (critical!)
                dark_schema = ColorSchema.from_json_with_defaults(
                    dark_json, DARK_PRESETS["Default"]
                )
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


# =============================================================================
# Disallowed Users Management
# =============================================================================


@router.get("/api/disallowed-users")
async def api_get_disallowed_users(
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Get all disallowed usernames from database.
    
    Returns both hardcoded and admin-added entries.
    """
    from pulldb.infra.mysql import DisallowedUserRepository
    
    if not hasattr(state, "job_repo") or not state.job_repo:
        return {"success": False, "message": "Database not available"}
    
    try:
        repo = DisallowedUserRepository(state.job_repo.pool)
        users = repo.get_all()
        
        return {
            "success": True,
            "users": [
                {
                    "username": u.username,
                    "reason": u.reason,
                    "is_hardcoded": u.is_hardcoded,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "created_by": u.created_by,
                }
                for u in users
            ],
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/api/disallowed-users")
async def api_add_disallowed_user(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Add a username to the disallowed list.
    
    Request body: {"username": "...", "reason": "..."}
    """
    from pulldb.infra.mysql import DisallowedUserRepository
    
    if not hasattr(state, "job_repo") or not state.job_repo:
        return {"success": False, "message": "Database not available"}
    
    try:
        body = await request.json()
        username = body.get("username", "").strip().lower()
        reason = body.get("reason", "").strip() or None
        
        if not username:
            return {"success": False, "message": "Username is required"}
        
        if len(username) < 2:
            return {"success": False, "message": "Username must be at least 2 characters"}
        
        repo = DisallowedUserRepository(state.job_repo.pool)
        
        # Check if already exists
        if repo.exists(username):
            return {"success": False, "message": f"Username '{username}' is already disallowed"}
        
        success = repo.add(username, reason, admin.user_id)
        
        if success:
            # Audit log
            if hasattr(state, "audit_repo") and state.audit_repo:
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="disallowed_user_added",
                    detail=f"Added '{username}' to disallowed users list",
                    context={"username": username, "reason": reason},
                )
            
            return {"success": True, "message": f"Username '{username}' added to disallowed list"}
        else:
            return {"success": False, "message": f"Failed to add username '{username}'"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.delete("/api/disallowed-users/{username}")
async def api_remove_disallowed_user(
    username: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Remove a username from the disallowed list.
    
    Only non-hardcoded entries can be removed.
    """
    from pulldb.infra.mysql import DisallowedUserRepository
    
    if not hasattr(state, "job_repo") or not state.job_repo:
        return {"success": False, "message": "Database not available"}
    
    try:
        repo = DisallowedUserRepository(state.job_repo.pool)
        success, message = repo.remove(username.lower())
        
        if success:
            # Audit log
            if hasattr(state, "audit_repo") and state.audit_repo:
                state.audit_repo.log_action(
                    actor_user_id=admin.user_id,
                    action="disallowed_user_removed",
                    detail=f"Removed '{username}' from disallowed users list",
                    context={"username": username},
                )
        
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/disallowed-users", response_class=HTMLResponse)
async def disallowed_users_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Display the disallowed users management page.
    
    Shows hardcoded system accounts (read-only) and database entries (editable).
    """
    from pulldb.domain.validation import (
        DISALLOWED_USERS_HARDCODED,
        MIN_USERNAME_LENGTH,
    )
    from pulldb.infra.mysql import DisallowedUserRepository
    
    # Get database entries
    database_users = []
    if hasattr(state, "job_repo") and state.job_repo:
        try:
            repo = DisallowedUserRepository(state.job_repo.pool)
            all_entries = repo.get_all()
            # Filter to non-hardcoded entries (database-added only)
            database_users = [
                u for u in all_entries 
                if u.username.lower() not in DISALLOWED_USERS_HARDCODED
            ]
        except Exception:
            # Graceful degradation: show page with empty database list
            logger.debug("Failed to get disallowed users from database", exc_info=True)
    
    # Sort hardcoded users alphabetically
    hardcoded_users = sorted(DISALLOWED_USERS_HARDCODED)
    
    return templates.TemplateResponse(
        "features/admin/disallowed_users.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "hardcoded_users": hardcoded_users,
            "hardcoded_count": len(hardcoded_users),
            "database_users": database_users,
            "database_count": len(database_users),
            "min_length": MIN_USERNAME_LENGTH,
            "breadcrumbs": get_breadcrumbs("admin_disallowed_users"),
        },
    )


# =============================================================================
# Locked Databases Management
# =============================================================================


@router.get("/locked-databases", response_class=HTMLResponse)
async def locked_databases_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """View all locked databases across the system.
    
    Shows databases that users have locked to prevent automatic cleanup.
    Admins can unlock these databases if needed.
    """
    locked_jobs = []
    
    if hasattr(state, "job_repo") and state.job_repo:
        if hasattr(state.job_repo, "get_all_locked_databases"):
            locked_jobs = state.job_repo.get_all_locked_databases()
    
    # Enrich with user info
    locked_databases = []
    for job in locked_jobs:
        owner = None
        if hasattr(state, "user_repo") and state.user_repo:
            owner = state.user_repo.get_user_by_id(job.owner_user_id)
        
        locked_by_user = None
        if job.locked_by and hasattr(state, "user_repo") and state.user_repo:
            locked_by_user = state.user_repo.get_user_by_id(job.locked_by)
        
        locked_databases.append({
            "job": job,
            "owner": owner,
            "locked_by_user": locked_by_user,
        })
    
    return templates.TemplateResponse(
        "features/admin/locked_databases.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "locked_databases": locked_databases,
            "total_count": len(locked_databases),
            "breadcrumbs": get_breadcrumbs("admin_locked_databases"),
        },
    )


@router.post("/locked-databases/{job_id}/unlock")
async def admin_unlock_database(
    job_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Admin action to unlock a database."""
    from urllib.parse import urlencode
    from fastapi.concurrency import run_in_threadpool

    base_url = "/web/admin/locked-databases"

    if not hasattr(state, "job_repo") or not state.job_repo:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'error': 'Job repository unavailable'})}",
            status_code=303,
        )

    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'error': 'Job not found'})}",
            status_code=303,
        )

    try:
        from pulldb.worker.retention import RetentionService
        from pulldb.infra.mysql import SettingsRepository

        settings_repo = getattr(state, "settings_repo", None)
        if not isinstance(settings_repo, SettingsRepository):
            return RedirectResponse(
                url=f"{base_url}?{urlencode({'error': 'Settings repository not available'})}",
                status_code=303,
            )
        retention_service = RetentionService(
            job_repo=state.job_repo,
            user_repo=state.user_repo,
            settings_repo=settings_repo,
        )
        await run_in_threadpool(
            retention_service.unlock_job,
            job_id,
            user.user_id,
        )
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'success': f'Unlocked database {job.target}'})}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'error': str(e)})}",
            status_code=303,
        )


# =============================================================================
# API Keys Management
# =============================================================================


@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Render the API Keys management page.
    
    Lists all pending API keys for admin approval, and provides
    ability to approve or revoke keys.
    """
    pending_keys = []
    all_keys_count = 0
    
    if hasattr(state, "auth_repo") and state.auth_repo:
        # Get pending keys (awaiting approval)
        pending_keys = state.auth_repo.get_pending_api_keys()
        
        # Enrich with username lookups
        for key in pending_keys:
            if "username" not in key and "user_id" in key:
                key_user = state.user_repo.get_user_by_id(key["user_id"])
                key["username"] = key_user.username if key_user else "unknown"
    
    stats = {
        "pending": len(pending_keys),
    }
    
    return templates.TemplateResponse(
        "features/admin/api_keys.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "pending_keys": pending_keys,
            "stats": stats,
            "breadcrumbs": get_breadcrumbs("admin_api_keys"),
        },
    )


@router.post("/api-keys/{key_id}/approve")
async def approve_api_key(
    key_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Approve a pending API key. Returns JSON for AJAX calls."""
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return {"success": False, "message": "Authentication service not available"}
    
    try:
        # Get key info for audit
        key_info = state.auth_repo.get_api_key_info(key_id)
        if not key_info:
            return {"success": False, "message": f"API key '{key_id}' not found"}
        
        if key_info.get("approved_at"):
            return {"success": False, "message": "Key is already approved"}
        
        # Approve the key
        success = state.auth_repo.approve_api_key(key_id, admin.user_id)
        if not success:
            return {"success": False, "message": "Failed to approve key"}
        
        # Get target user info for message
        target_user = state.user_repo.get_user_by_id(key_info["user_id"])
        target_name = target_user.username if target_user else "unknown"
        host_name = key_info.get("host_name") or "unknown"
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="api_key_approved",
                target_user_id=key_info["user_id"],
                detail=f"Admin {admin.username} approved API key for {target_name} (host: {host_name})",
            )
        
        return {
            "success": True,
            "message": f"API key approved for {target_name} ({host_name})",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key_web(
    key_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Revoke an API key. Returns JSON for AJAX calls."""
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return {"success": False, "message": "Authentication service not available"}
    
    try:
        # Get key info for audit
        key_info = state.auth_repo.get_api_key_info(key_id)
        if not key_info:
            return {"success": False, "message": f"API key '{key_id}' not found"}
        
        # Revoke the key
        success = state.auth_repo.revoke_api_key(key_id)
        if not success:
            return {"success": False, "message": "Failed to revoke key"}
        
        # Get target user info for message
        target_user = state.user_repo.get_user_by_id(key_info["user_id"])
        target_name = target_user.username if target_user else "unknown"
        host_name = key_info.get("host_name") or "unknown"
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="api_key_revoked",
                target_user_id=key_info["user_id"],
                detail=f"Admin {admin.username} revoked API key for {target_name} (host: {host_name})",
            )
        
        return {
            "success": True,
            "message": f"API key revoked for {target_name} ({host_name})",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.delete("/api-keys/{key_id}")
async def delete_api_key_web(
    key_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Permanently delete an API key. Returns JSON for AJAX calls.
    
    Unlike revoke, this removes the key from the database entirely.
    The key cannot be reactivated after deletion.
    """
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return {"success": False, "message": "Authentication service not available"}
    
    try:
        # Get key info for audit before deletion
        key_info = state.auth_repo.get_api_key_info(key_id)
        if not key_info:
            return {"success": False, "message": f"API key '{key_id}' not found"}
        
        # Store info for audit logging before we delete
        target_user_id = key_info["user_id"]
        target_user = state.user_repo.get_user_by_id(target_user_id)
        target_name = target_user.username if target_user else "unknown"
        host_name = key_info.get("host_name") or "unknown"
        
        # Delete the key permanently
        success = state.auth_repo.delete_api_key(key_id)
        if not success:
            return {"success": False, "message": "Failed to delete key"}
        
        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="api_key_deleted",
                target_user_id=target_user_id,
                detail=f"Admin {admin.username} deleted API key for {target_name} (host: {host_name})",
            )
        
        return {
            "success": True,
            "message": f"API key deleted for {target_name} ({host_name})",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/api-keys/user/{user_id}")
async def get_user_keys(
    user_id: str,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Get all API keys for a specific user. Returns JSON."""
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return {"success": False, "message": "Authentication service not available", "keys": []}
    
    try:
        keys = state.auth_repo.get_api_keys_for_user(user_id)
        
        # Enrich with status info
        enriched_keys = []
        for key in keys:
            enriched_keys.append({
                "key_id": key["key_id"],
                "name": key.get("name"),
                "host_name": key.get("host_name"),
                "created_at": key["created_at"].isoformat() if key.get("created_at") else None,
                "created_from_ip": key.get("created_from_ip"),
                "last_used_at": key["last_used_at"].isoformat() if key.get("last_used_at") else None,
                "last_used_ip": key.get("last_used_ip"),
                "is_active": bool(key.get("is_active", False)),
                "is_approved": key.get("approved_at") is not None,
                "approved_at": key["approved_at"].isoformat() if key.get("approved_at") else None,
            })
        
        return {"success": True, "keys": enriched_keys}
    except Exception as e:
        return {"success": False, "message": str(e), "keys": []}


# =============================================================================
# Job History Summary - Admin Management
# =============================================================================

@router.get("/job-history", response_class=HTMLResponse)
async def job_history_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    prune_success: int | None = None,
    prune_error: str | None = None,
) -> HTMLResponse:
    """Render the job history management page."""
    from datetime import date

    from pulldb.infra.factory import get_job_history_summary_repository

    # Build flash message from query params
    flash_message = None
    flash_type = None
    if prune_success is not None:
        flash_message = f"Successfully deleted {prune_success} history record(s)"
        flash_type = "success"
    elif prune_error:
        flash_message = f"Prune failed: {prune_error}"
        flash_type = "error"

    # Get stats
    try:
        history_repo = get_job_history_summary_repository()
        stats = history_repo.get_stats()
    except Exception as e:
        logger.warning("Failed to get job history stats: %s", e)
        stats = {
            "total_records": 0,
            "oldest_record": None,
            "newest_record": None,
            "complete_count": 0,
            "failed_count": 0,
            "canceled_count": 0,
        }

    return templates.TemplateResponse(
        "features/admin/job_history.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "stats": stats,
            "today": date.today().isoformat(),
            "flash_message": flash_message,
            "flash_type": flash_type,
            "breadcrumbs": get_breadcrumbs("admin_job_history"),
        },
    )


@router.get("/api/job-history/stats")
async def get_job_history_stats(
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get job history summary statistics."""
    from pulldb.infra.factory import get_job_history_summary_repository

    try:
        history_repo = get_job_history_summary_repository()
        if history_repo is None:
            # Simulation mode - return empty stats
            return {
                "success": True,
                "stats": {
                    "total_records": 0,
                    "oldest_record": None,
                    "newest_record": None,
                    "complete_count": 0,
                    "failed_count": 0,
                    "canceled_count": 0,
                },
            }
        stats = history_repo.get_stats()
        # Convert datetime objects for JSON
        return {
            "success": True,
            "stats": {
                "total_records": stats.get("total_records", 0),
                "oldest_record": (
                    stats["oldest_record"].isoformat()
                    if stats.get("oldest_record") else None
                ),
                "newest_record": (
                    stats["newest_record"].isoformat()
                    if stats.get("newest_record") else None
                ),
                "complete_count": stats.get("complete_count", 0),
                "failed_count": stats.get("failed_count", 0),
                "canceled_count": stats.get("canceled_count", 0),
            },
        }
    except Exception as e:
        logger.warning("Failed to get job history stats: %s", e)
        return {"success": False, "message": str(e)}


@router.get("/api/job-history/count")
async def get_job_history_count(
    before: str | None = Query(None, description="Filter before date (ISO format)"),
    status: str | None = Query(None, description="Filter by status"),
    username: str | None = Query(None, description="Filter by username"),
    dbhost: str | None = Query(None, description="Filter by database host"),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get count of history records matching filters (for preview before delete)."""
    from datetime import datetime
    from pulldb.infra.factory import get_job_history_summary_repository

    try:
        history_repo = get_job_history_summary_repository()
        if history_repo is None:
            # Simulation mode - return zero count
            return {"success": True, "count": 0}

        # Parse before date if provided
        before_dt = None
        if before:
            try:
                before_dt = datetime.fromisoformat(before.replace('Z', '+00:00'))
            except ValueError:
                return {"success": False, "message": f"Invalid date format: {before}"}

        count = history_repo.count_matching(
            before=before_dt,
            status=status,
            username=username,
            dbhost=dbhost,
        )
        return {"success": True, "count": count}
    except Exception as e:
        logger.warning("Failed to count job history records: %s", e)
        return {"success": False, "message": str(e)}


@router.post("/api/job-history/prune")
async def prune_job_history(
    before: str | None = Form(None, description="Filter before date (ISO format)"),
    status: str | None = Form(None, description="Filter by status"),
    username: str | None = Form(None, description="Filter by username"),
    dbhost: str | None = Form(None, description="Filter by database host"),
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    """Delete job history records matching filters."""
    from datetime import datetime
    from urllib.parse import quote
    from pulldb.infra.factory import get_job_history_summary_repository

    try:
        history_repo = get_job_history_summary_repository()
        if history_repo is None:
            # Simulation mode - no-op
            return RedirectResponse(
                url="/web/admin/job-history?prune_error=" + quote("Not available in simulation mode"),
                status_code=303,
            )

        # Parse before date if provided
        before_dt = None
        if before:
            try:
                before_dt = datetime.fromisoformat(before.replace('Z', '+00:00'))
            except ValueError:
                return RedirectResponse(
                    url=f"/web/admin/job-history?prune_error={quote(f'Invalid date: {before}')}",
                    status_code=303,
                )

        # Must have at least one filter
        if not any([before_dt, status, username, dbhost]):
            return RedirectResponse(
                url="/web/admin/job-history?prune_error=" + quote("At least one filter required"),
                status_code=303,
            )

        # Validate status if provided
        if status and status not in ("complete", "failed", "canceled"):
            return RedirectResponse(
                url=f"/web/admin/job-history?prune_error={quote(f'Invalid status: {status}')}",
                status_code=303,
            )

        # Delete based on filters (priority order)
        deleted = 0
        if username:
            deleted = history_repo.delete_by_user(username=username, before=before_dt)
        elif dbhost:
            deleted = history_repo.delete_by_host(dbhost=dbhost, before=before_dt)
        elif status:
            deleted = history_repo.delete_by_status(status=status, before=before_dt)
        elif before_dt:
            deleted = history_repo.delete_by_date(before=before_dt)

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            detail = f"Admin {admin.username} pruned {deleted} job history records"
            if before:
                detail += f" (before={before})"
            if status:
                detail += f" (status={status})"
            if username:
                detail += f" (username={username})"
            if dbhost:
                detail += f" (dbhost={dbhost})"
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="job_history_pruned",
                detail=detail,
            )

        return RedirectResponse(
            url=f"/web/admin/job-history?prune_success={deleted}",
            status_code=303,
        )
    except Exception as e:
        logger.exception("Failed to prune job history")
        return RedirectResponse(
            url=f"/web/admin/job-history?prune_error={quote(str(e))}",
            status_code=303,
        )


@router.get("/api/job-history/records")
async def get_job_history_records(
    before: str | None = Query(None, description="Filter before date (ISO format)"),
    after: str | None = Query(None, description="Filter after date (ISO format)"),
    status: str | None = Query(None, description="Filter by status"),
    username: str | None = Query(None, description="Filter by username"),
    dbhost: str | None = Query(None, description="Filter by database host"),
    page: int | None = Query(None, ge=0, description="Page number (0-indexed)"),
    pageSize: int | None = Query(None, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Get paginated job history records."""
    from datetime import datetime
    from pulldb.infra.factory import get_job_history_summary_repository
    import sys

    print(f"DEBUG job-history: page={page}, pageSize={pageSize}, offset={offset}, limit={limit}", file=sys.stderr, flush=True)

    # Support both page/pageSize and offset/limit params (LazyTable uses page/pageSize)
    if page is not None and pageSize is not None:
        offset = page * pageSize
        limit = pageSize
        print(f"DEBUG job-history: adjusted offset={offset}, limit={limit}", file=sys.stderr, flush=True)

    try:
        history_repo = get_job_history_summary_repository()
        if history_repo is None:
            # Simulation mode - return empty records
            return {
                "success": True,
                "rows": [],
                "totalCount": 0,
                "offset": offset,
                "limit": limit,
            }

        # Parse dates if provided
        before_dt = None
        after_dt = None
        if before:
            try:
                before_dt = datetime.fromisoformat(before.replace('Z', '+00:00'))
            except ValueError:
                return {"success": False, "message": f"Invalid date format: {before}"}
        if after:
            try:
                after_dt = datetime.fromisoformat(after.replace('Z', '+00:00'))
            except ValueError:
                return {"success": False, "message": f"Invalid date format: {after}"}

        records = history_repo.get_records(
            before=before_dt,
            after=after_dt,
            status=status,
            username=username,
            dbhost=dbhost,
            offset=offset,
            limit=limit,
        )
        print(f"DEBUG job-history: get_records returned {len(records)} records", file=sys.stderr, flush=True)

        # Convert datetime and Decimal objects for JSON serialization
        from decimal import Decimal
        serialized = []
        for rec in records:
            item = dict(rec)
            for key, val in item.items():
                # Convert datetime to ISO string
                if hasattr(val, "isoformat"):
                    item[key] = val.isoformat()
                # Convert Decimal to float
                elif isinstance(val, Decimal):
                    item[key] = float(val)
            serialized.append(item)

        total = history_repo.count_matching(
            before=before_dt,
            after=after_dt,
            status=status,
            username=username,
            dbhost=dbhost,
        )

        logger.info("job-history API: returning %d rows, totalCount=%d", len(serialized), total)
        response = {
            "success": True,
            "rows": serialized,
            "totalCount": total,
            "offset": offset,
            "limit": limit,
        }
        print(f"DEBUG job-history: returning response with {len(response.get('rows', []))} rows", file=sys.stderr, flush=True)
        return response
    except Exception as e:
        logger.warning("Failed to get job history records: %s", e)
        return {"success": False, "message": str(e)}

