"""Audit routes for Web2 interface.

HCA Layer: features
Purpose: Admin-only audit log browsing with LazyTable pagination.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from pulldb.domain.models import User
from pulldb.web.dependencies import get_api_state, require_admin, templates

router = APIRouter(prefix="/web/admin/audit", tags=["web-admin-audit"])


@router.get("/", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    actor_id: str | None = None,
    target_id: str | None = None,
) -> HTMLResponse:
    """Render the audit log page with LazyTable.
    
    Supports pre-applied filters via query params:
    - actor_id: Filter logs by who performed the action
    - target_id: Filter logs by who was affected
    """
    # Get users list for filter dropdowns
    users_list = []
    if hasattr(state.user_repo, "list_users"):
        raw_users = state.user_repo.list_users()
        users_list = [
            {"user_id": u.user_id, "username": u.username}
            for u in raw_users
        ]
    
    # Get distinct action types for filter
    action_types = []
    if hasattr(state, "audit_repo") and state.audit_repo:
        try:
            # Get sample logs to extract action types
            sample_logs = state.audit_repo.get_audit_logs(limit=500)
            action_types = sorted(set(log.get("action", "") for log in sample_logs if log.get("action")))
        except Exception:
            pass
    
    # Get total count for stats
    total_count = 0
    if hasattr(state, "audit_repo") and state.audit_repo:
        try:
            total_count = state.audit_repo.get_audit_logs_count(
                actor_user_id=actor_id,
                target_user_id=target_id,
            )
        except Exception:
            pass

    return templates.TemplateResponse(
        "features/audit/index.html",
        {
            "request": request,
            "active_nav": "audit",
            "user": user,
            "users_list": users_list,
            "action_types": action_types,
            "filter_actor_id": actor_id,
            "filter_target_id": target_id,
            "total_count": total_count,
        },
    )


@router.get("/api/logs")
async def get_audit_logs_api(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    actor_id: str | None = None,
    target_id: str | None = None,
    action: str | None = None,
) -> dict:
    """API endpoint for LazyTable pagination.
    
    Returns:
        {
            "rows": [...],
            "total": int,
            "limit": int,
            "offset": int
        }
    """
    if not hasattr(state, "audit_repo") or not state.audit_repo:
        return {
            "rows": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "error": "Audit logging not available",
        }
    
    try:
        # Get logs with filters
        logs = state.audit_repo.get_audit_logs(
            actor_user_id=actor_id,
            target_user_id=target_id,
            action=action,
            limit=limit,
            offset=offset,
        )
        
        # Get total count for pagination
        total = state.audit_repo.get_audit_logs_count(
            actor_user_id=actor_id,
            target_user_id=target_id,
            action=action,
        )
        
        # Transform for frontend
        rows = []
        for log in logs:
            rows.append({
                "audit_id": log.get("audit_id"),
                "created_at": log.get("created_at").isoformat() if log.get("created_at") else None,
                "actor_user_id": log.get("actor_user_id"),
                "actor_username": log.get("actor_username") or "(unknown)",
                "action": log.get("action"),
                "target_user_id": log.get("target_user_id"),
                "target_username": log.get("target_username") or "-",
                "detail": log.get("detail") or "-",
                "context": log.get("context") or {},
            })
        
        return {
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        
    except Exception as e:
        return {
            "rows": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "error": str(e),
        }
