from __future__ import annotations

"""Audit routes for Web2 interface.

HCA Layer: features
Purpose: Admin-only audit log browsing with LazyTable pagination.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from pulldb.domain.models import User
from pulldb.infra.filter_utils import parse_multi_value_filter
from pulldb.web.dependencies import get_api_state, require_admin, templates
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

router = APIRouter(prefix="/web/admin/audit", tags=["web-admin-audit"])


@router.get("/", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Render the audit log page with LazyTable.
    
    Filters are handled client-side via LazyTable's built-in filterable columns.
    """
    # Build stats dict (matching users page pattern)
    stats = {
        "total": 0,
        "user_actions": 0,
        "system_actions": 0,
    }
    
    if hasattr(state, "audit_repo") and state.audit_repo:
        try:
            all_logs = state.audit_repo.get_audit_logs(limit=10000)
            stats["total"] = len(all_logs)
            # Count user vs system actions
            for log in all_logs:
                if log.get("actor_user_id"):
                    stats["user_actions"] += 1
                else:
                    stats["system_actions"] += 1
        except Exception:
            # Graceful degradation: stats are informational, page works without them
            logger.debug("Failed to get audit stats", exc_info=True)

    return templates.TemplateResponse(
        "features/audit/index.html",
        {
            "request": request,
            "active_nav": "audit",
            "user": user,
            "stats": stats,
            "breadcrumbs": get_breadcrumbs("audit_logs"),
        },
    )


@router.get("/api/logs")
async def get_audit_logs_api(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=50, ge=1, le=500),
    sortColumn: str = Query(default="created_at"),
    sortDirection: str = Query(default="desc"),
) -> dict:
    """API endpoint for LazyTable pagination.
    
    Supports:
    - page/pageSize pagination
    - sortColumn/sortDirection sorting
    - filter_* params for column filtering
    
    Returns:
        {
            "rows": [...],
            "totalCount": int,
            "filteredCount": int,
            "pageIndex": int,
            "pageSize": int
        }
    """
    if not hasattr(state, "audit_repo") or not state.audit_repo:
        return {
            "rows": [],
            "totalCount": 0,
            "filteredCount": 0,
            "pageIndex": page,
            "pageSize": pageSize,
            "error": "Audit logging not available",
        }
    
    try:
        # Get all logs (we'll filter/sort in memory for simplicity)
        all_logs = state.audit_repo.get_audit_logs(limit=10000)
        total_count = len(all_logs)
        
        # Transform for frontend
        rows = []
        for log in all_logs:
            context_data = log.get("context") or {}
            context_str = ""
            if context_data:
                # Format context as readable string
                try:
                    context_str = json.dumps(context_data, indent=2)
                except Exception:
                    context_str = str(context_data)
            
            rows.append({
                "audit_id": log.get("audit_id"),
                "created_at": log.get("created_at").isoformat() if log.get("created_at") else None,
                "actor_user_id": log.get("actor_user_id"),
                "actor_username": log.get("actor_username") or "(unknown)",
                "action": log.get("action"),
                "target_user_id": log.get("target_user_id"),
                "target_username": log.get("target_username") or "-",
                "detail": log.get("detail") or "-",
                "context": context_str,
            })
        
        # Extract filter params
        text_filters: dict[str, list[str]] = {}
        date_range_filter: tuple[str | None, str | None] | None = None
        
        for key, value in request.query_params.items():
            if key.startswith("filter_") and value and key != "filter_order":
                col_key = key[7:]  # Remove "filter_" prefix
                
                # Date range filter for created_at (format: "fromISO,toISO")
                if col_key == "created_at":
                    parts = value.split(",")
                    from_date = parts[0] if parts[0] else None
                    to_date = parts[1] if len(parts) > 1 and parts[1] else None
                    date_range_filter = (from_date, to_date)
                else:
                    text_filters[col_key] = parse_multi_value_filter(value)
        
        # Apply date range filter
        if date_range_filter:
            from_date, to_date = date_range_filter
            filtered_rows = []
            for row in rows:
                created_at = row.get("created_at")
                if not created_at:
                    continue
                # Compare ISO strings directly (they sort lexicographically)
                if from_date and created_at < from_date:
                    continue
                if to_date and created_at > to_date:
                    continue
                filtered_rows.append(row)
            rows = filtered_rows
        
        # Apply text filters (multi-select checkbox filters)
        if text_filters:
            filtered_rows = []
            for row in rows:
                match = True
                for col_key, filter_vals in text_filters.items():
                    cell_val = str(row.get(col_key, "")).lower()
                    # For multi-select, check if cell value matches ANY of the selected values
                    if not any(fv.lower() == cell_val for fv in filter_vals):
                        match = False
                        break
                if match:
                    filtered_rows.append(row)
            rows = filtered_rows
        
        filtered_count = len(rows)
        
        # Apply sorting
        if sortColumn:
            reverse = sortDirection == "desc"
            rows.sort(
                key=lambda r: (r.get(sortColumn) is None, r.get(sortColumn) or ""),
                reverse=reverse
            )
        
        # Apply pagination
        start = page * pageSize
        end = start + pageSize
        page_rows = rows[start:end]
        
        # Count user vs system actions for stats
        user_actions = sum(1 for r in rows if r.get("actor_user_id"))
        system_actions = len(rows) - user_actions
        
        return {
            "rows": page_rows,
            "totalCount": total_count,
            "filteredCount": filtered_count,
            "page": page,
            "pageSize": pageSize,
            "stats": {
                "total": total_count,
                "user_actions": user_actions,
                "system_actions": system_actions,
            },
        }
        
    except Exception as e:
        return {
            "rows": [],
            "totalCount": 0,
            "filteredCount": 0,
            "page": page,
            "pageSize": pageSize,
            "stats": {"total": 0, "user_actions": 0, "system_actions": 0},
            "error": str(e),
        }


@router.get("/api/logs/distinct")
async def get_audit_distinct_values(
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
    if not hasattr(state, "audit_repo") or not state.audit_repo:
        return []
    
    try:
        all_logs = state.audit_repo.get_audit_logs(limit=10000)
        
        # Transform to rows format
        rows = []
        for log in all_logs:
            rows.append({
                "actor_username": log.get("actor_username") or "(unknown)",
                "action": log.get("action"),
                "target_username": log.get("target_username") or "-",
                "created_at": log.get("created_at").isoformat() if log.get("created_at") else None,
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
        
        # Extract filter params from request
        text_filters: dict[str, list[str]] = {}
        date_range_filter: tuple[str | None, str | None] | None = None
        
        for key, value in request.query_params.items():
            if key.startswith("filter_") and value and key != "filter_order":
                col_key = key[7:]
                if col_key not in applicable_cols:
                    continue
                    
                # Date range filter for created_at
                if col_key == "created_at":
                    parts = value.split(",")
                    from_date = parts[0] if parts[0] else None
                    to_date = parts[1] if len(parts) > 1 and parts[1] else None
                    date_range_filter = (from_date, to_date)
                else:
                    text_filters[col_key] = parse_multi_value_filter(value)
        
        # Apply date range filter
        if date_range_filter:
            from_date, to_date = date_range_filter
            filtered = []
            for row in rows:
                created_at = row.get("created_at")
                if not created_at:
                    continue
                if from_date and created_at < from_date:
                    continue
                if to_date and created_at > to_date:
                    continue
                filtered.append(row)
            rows = filtered
        
        # Apply cascading text filters (multi-select)
        if text_filters:
            filtered = []
            for row in rows:
                match = True
                for col_key, filter_vals in text_filters.items():
                    cell_val = str(row.get(col_key, "")).lower()
                    if not any(fv.lower() == cell_val for fv in filter_vals):
                        match = False
                        break
                if match:
                    filtered.append(row)
            rows = filtered
        
        values = set()
        for row in rows:
            val = row.get(column)
            if val is not None and str(val).strip() and str(val) != "-":
                values.add(str(val))
        return sorted(values)
        
    except Exception:
        # Graceful degradation: return empty list for filter options
        logger.debug("Failed to get distinct values for column %s", column, exc_info=True)
        return []
