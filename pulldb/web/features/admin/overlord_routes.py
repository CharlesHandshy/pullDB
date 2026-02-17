"""Overlord Companies CRUD routes for admin UI.

HCA Layer: pages (pulldb/web/features/)

Extracted from admin/routes.py for maintainability.
Handles all Overlord Companies management operations:
- List / paginate / distinct values
- Detail view
- Create / update / delete
- Claim / release
"""

from __future__ import annotations

import fnmatch as _fnmatch
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from pulldb.domain.models import JobStatus, User
from pulldb.web.dependencies import (
    OverlordCache,
    get_api_state,
    require_admin,
    templates,
)
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin", tags=["web-admin-overlord"])


# =============================================================================
# Helpers
# =============================================================================


def _get_overlord_repos(state: Any) -> tuple:
    """Get overlord repository and tracking repository from state.

    Returns:
        (overlord_manager, overlord_repo, tracking_repo) — any may be None
    """
    overlord_manager = getattr(state, "overlord_manager", None)
    if not overlord_manager or not overlord_manager.is_enabled:
        return None, None, None
    overlord_repo = overlord_manager.overlord_repo
    tracking_repo = overlord_manager.tracking_repo
    return overlord_manager, overlord_repo, tracking_repo


def _text_filter_match(cell: str, vals: list[str]) -> bool:
    """Match a cell value against text filter values with wildcard (*) support.

    Supports:
    - Plain substring matching: "test" matches "test_db"
    - Wildcard prefix: "test*" matches "test_db" but not "my_test"
    - Wildcard suffix: "*test" matches "my_test" but not "test_db"
    - Wildcard both: "*test*" same as plain substring
    - Exact: no wildcards → substring containment
    """
    for v in vals:
        if "*" in v or "?" in v:
            if _fnmatch.fnmatch(cell, v):
                return True
        else:
            if v in cell:
                return True
    return False


def _enrich_companies_with_tracking(
    companies: list[dict],
    tracking_repo: Any,
    job_repo: Any = None,
) -> list[dict]:
    """Enrich company rows with local tracking data.

    Adds _managed, _tracking_status, _job_id, _managed_by, _user_code fields.
    When job_repo is provided, resolves owner_user_code from the linked job.
    """
    active_tracking = tracking_repo.list_active() if tracking_repo else []
    tracking_map = {t.database_name: t for t in active_tracking}

    # Build job lookup for user_code resolution
    job_map: dict[str | int, Any] = {}
    if job_repo:
        try:
            claimed_job_ids = {t.job_id for t in active_tracking if t.job_id}
            for jid in claimed_job_ids:
                job = job_repo.get_job_by_id(str(jid))
                if job:
                    job_map[jid] = job
        except Exception:
            pass

    for row in companies:
        db_name = row.get("database", "")
        tracking = tracking_map.get(db_name)
        row["_managed"] = tracking is not None
        row["_tracking_status"] = tracking.status.value if tracking else None
        row["_job_id"] = tracking.job_id if tracking else None
        row["_managed_by"] = tracking.created_by if tracking else None
        row["_tracking_id"] = tracking.id if tracking else None
        row["_row_existed_before"] = tracking.row_existed_before if tracking else None
        # Resolve user code from linked job
        job = job_map.get(tracking.job_id) if tracking and tracking.job_id else None
        row["_user_code"] = getattr(job, "owner_user_code", None) or None

    return companies


# =============================================================================
# Overlord Companies Routes
# =============================================================================


@router.get("/overlord/companies", response_class=HTMLResponse)
async def overlord_companies_list(
    request: Request,
    cache: OverlordCache,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Render overlord companies list page with LazyTable."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    overlord_enabled = overlord_manager is not None and overlord_manager.is_enabled

    # Get initial stats for server-side render
    stats = {"total": 0, "managed": 0, "unmanaged": 0}
    if overlord_enabled and cache is not None:
        try:
            all_companies = list(cache.rows)
            all_companies = _enrich_companies_with_tracking(all_companies, tracking_repo)
            stats["total"] = len(all_companies)
            stats["managed"] = len([c for c in all_companies if c["_managed"]])
            stats["unmanaged"] = stats["total"] - stats["managed"]
        except Exception:
            logger.warning("Failed to get overlord companies stats", exc_info=True)

    return templates.TemplateResponse(
        "features/admin/overlord_companies.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "stats": stats,
            "overlord_enabled": overlord_enabled,
            "breadcrumbs": get_breadcrumbs("admin_overlord_companies"),
        },
    )


@router.get("/api/overlord/companies/paginated")
async def api_overlord_companies_paginated(
    request: Request,
    cache: OverlordCache,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
    page: int = Query(0, ge=0),
    pageSize: int = Query(50, ge=10, le=200),
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict:
    """Get paginated overlord companies for LazyTable."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_repo or cache is None:
        return {"rows": [], "totalCount": 0, "filteredCount": 0, "page": 0, "pageSize": pageSize, "stats": {"total": 0, "managed": 0, "unmanaged": 0}}

    try:
        all_companies = list(cache.rows)
    except Exception as e:
        logger.error(f"Failed to fetch overlord companies: {e}")
        return {"rows": [], "totalCount": 0, "filteredCount": 0, "page": 0, "pageSize": pageSize, "error": str(e)}

    # Enrich with tracking
    all_companies = _enrich_companies_with_tracking(all_companies, tracking_repo, job_repo=state.job_repo if hasattr(state, "job_repo") else None)

    total_count = len(all_companies)
    stats = {
        "total": total_count,
        "managed": len([c for c in all_companies if c["_managed"]]),
        "unmanaged": len([c for c in all_companies if not c["_managed"]]),
    }

    # Serialize (convert non-JSON-safe types)
    rows = []
    for c in all_companies:
        row = {}
        for k, v in c.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
            elif isinstance(v, bytes):
                row[k] = v.decode("utf-8", errors="replace")
            else:
                row[k] = v
        rows.append(row)

    # Apply filters
    text_filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]
            text_filters[col_key] = [v.strip().lower() for v in value.split(",") if v.strip()]

    if text_filters:
        filtered = []
        for row in rows:
            match = True
            for col, vals in text_filters.items():
                if col == "_managed":
                    # Exact match — "managed" is a substring of "unmanaged"
                    managed_str = "managed" if row.get("_managed") else "unmanaged"
                    if managed_str not in vals:
                        match = False
                        break
                elif col == "_tracking_status":
                    status = (row.get("_tracking_status") or "none").lower()
                    if status not in vals:
                        match = False
                        break
                elif col == "visible":
                    # Map "yes"/"no" labels back to 0/1 values
                    vis_val = row.get("visible")
                    vis_str = "yes" if vis_val == 1 or vis_val == "1" else "no"
                    if vis_str not in vals:
                        match = False
                        break
                else:
                    cell = str(row.get(col, "") or "").lower()
                    if not _text_filter_match(cell, vals):
                        match = False
                        break
            if match:
                filtered.append(row)
        rows = filtered

    filtered_count = len(rows)

    # Apply sorting
    if sortColumn:
        reverse = sortDirection == "desc"
        if sortColumn == "_managed":
            rows.sort(key=lambda r: (r.get("_managed") is None, r.get("_managed", False)), reverse=reverse)
        elif sortColumn in ("companyID", "visible", "brandingLogo"):
            rows.sort(key=lambda r: r.get(sortColumn) or 0, reverse=reverse)
        else:
            rows.sort(
                key=lambda r: (r.get(sortColumn) is None, str(r.get(sortColumn) or "").lower()),
                reverse=reverse,
            )

    # Paginate
    start = page * pageSize
    page_rows = rows[start:start + pageSize]

    return {
        "rows": page_rows,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "page": page,
        "pageSize": pageSize,
        "stats": stats,
    }


@router.get("/api/overlord/companies/paginated/distinct")
async def api_overlord_companies_distinct(
    request: Request,
    column: str,
    cache: OverlordCache,
    filter_order: str | None = None,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> list:
    """Get distinct values for company filter dropdowns."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_repo or cache is None:
        return []

    try:
        all_companies = list(cache.rows)
    except Exception:
        return []

    all_companies = _enrich_companies_with_tracking(all_companies, tracking_repo, job_repo=state.job_repo if hasattr(state, "job_repo") else None)

    # Apply cascading filters (filters before this column)
    if filter_order:
        ordered_cols = [c.strip() for c in filter_order.split(",") if c.strip()]
        # Only apply filters for columns that appear before `column` in the order
        if column in ordered_cols:
            ordered_cols = ordered_cols[:ordered_cols.index(column)]

        for col_key in ordered_cols:
            filter_val = request.query_params.get(f"filter_{col_key}")
            if filter_val:
                vals = [v.strip().lower() for v in filter_val.split(",") if v.strip()]
                filtered = []
                for row in all_companies:
                    if col_key == "_managed":
                        # Exact match — "managed" is substring of "unmanaged"
                        managed_str = "managed" if row.get("_managed") else "unmanaged"
                        if managed_str in vals:
                            filtered.append(row)
                    elif col_key == "visible":
                        vis_val = row.get("visible")
                        vis_str = "yes" if vis_val == 1 or vis_val == "1" else "no"
                        if vis_str in vals:
                            filtered.append(row)
                    else:
                        cell = str(row.get(col_key, "") or "").lower()
                        if _text_filter_match(cell, vals):
                            filtered.append(row)
                all_companies = filtered

    # Collect distinct values
    values = set()
    for row in all_companies:
        if column == "_managed":
            values.add("Managed" if row.get("_managed") else "Unmanaged")
        elif column == "_tracking_status":
            values.add(row.get("_tracking_status") or "none")
        elif column == "visible":
            vis_val = row.get("visible")
            values.add("Yes" if vis_val == 1 or vis_val == "1" else "No")
        else:
            val = row.get(column)
            if val is not None:
                values.add(str(val))

    return sorted(values)


@router.get("/overlord/companies/{company_id}", response_class=HTMLResponse)
async def overlord_company_detail(
    company_id: int,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    updated: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Render overlord company detail/edit page."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_repo:
        return templates.TemplateResponse(
            "features/errors/404.html",
            {"request": request, "user": user, "message": "Overlord is not configured"},
            status_code=503,
        )

    try:
        company = overlord_repo.get_by_id(company_id)
    except Exception as e:
        return templates.TemplateResponse(
            "features/errors/404.html",
            {"request": request, "user": user, "message": f"Overlord connection error: {e}"},
            status_code=503,
        )

    if not company:
        return templates.TemplateResponse(
            "features/errors/404.html",
            {"request": request, "user": user, "message": f"Company #{company_id} not found"},
            status_code=404,
        )

    # Get tracking data
    db_name = company.get("database", "")
    tracking = tracking_repo.get(db_name) if tracking_repo and db_name else None
    is_managed = tracking is not None and tracking.status.value in ("claimed", "synced")

    # Get deployed jobs for claim dropdown
    deployed_jobs: list[dict[str, Any]] = []
    if hasattr(state, "job_repo") and state.job_repo:
        try:
            all_jobs = state.job_repo.list_jobs()
            for j in all_jobs:
                if getattr(j, "status", None) != JobStatus.DEPLOYED:
                    continue
                opts = j.options_json or {}
                host = j.dbhost or getattr(j, "target_host", "") or ""
                # Shorten host: take first segment before first dot
                short_host = host.split(".")[0] if "." in host else host
                deployed_jobs.append({
                    "id": j.id,
                    "short_id": j.id[:8] if j.id else "",
                    "target": j.target or "",
                    "customer": opts.get("customer_id") or opts.get("customer") or "",
                    "host": host,
                    "short_host": short_host,
                })
        except Exception:
            pass

    # Auto-match: find deployed job that correlates with this company row
    # Match: job.target == company.database AND job.dbhost == company.dbHost
    # Exclude jobs already claimed by other tracking rows
    suggested_job_id = None
    if not is_managed and deployed_jobs:
        claimed_job_ids: set[str] = set()
        if tracking_repo:
            try:
                for t in tracking_repo.list_active():
                    if t.job_id:
                        claimed_job_ids.add(str(t.job_id))
            except Exception:
                pass

        company_db = (company.get("database") or "").lower()
        company_host = (company.get("dbHost") or "").lower()

        for dj in deployed_jobs:
            if str(dj["id"]) in claimed_job_ids:
                continue
            job_target = (dj["target"] or "").lower()
            job_host = (dj["host"] or "").lower()

            # Primary: exact target == database match
            if company_db and job_target == company_db:
                # Confirming signal: host matches too (or host not set)
                if not company_host or not job_host or job_host == company_host:
                    suggested_job_id = dj["id"]
                    break

    # Build tracking dict for template
    tracking_data = None
    if tracking:
        tracking_data = {
            "id": tracking.id,
            "status": tracking.status.value,
            "job_id": tracking.job_id,
            "created_by": tracking.created_by,
            "row_existed_before": tracking.row_existed_before,
            "previous_dbhost": tracking.previous_dbhost,
            "previous_dbhost_read": tracking.previous_dbhost_read,
            "current_dbhost": tracking.current_dbhost,
            "current_dbhost_read": tracking.current_dbhost_read,
            "current_subdomain": tracking.current_subdomain,
            "created_at": tracking.created_at.isoformat() if tracking.created_at else None,
            "updated_at": tracking.updated_at.isoformat() if tracking.updated_at else None,
        }

    flash_message = None
    flash_type = None
    if updated:
        flash_message = "Company updated successfully"
        flash_type = "success"
    elif error:
        flash_message = error
        flash_type = "error"

    return templates.TemplateResponse(
        "features/admin/overlord_company_detail.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "company": company,
            "tracking": tracking_data,
            "is_managed": is_managed,
            "deployed_jobs": deployed_jobs,
            "suggested_job_id": suggested_job_id,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "breadcrumbs": get_breadcrumbs(
                "admin_overlord_company_detail",
                company=db_name or f"#{company_id}",
            ),
        },
    )


@router.post("/api/overlord/companies/create")
async def api_overlord_company_create(
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Create a new overlord company row."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_repo:
        return {"success": False, "message": "Overlord is not configured"}

    try:
        body = await request.json()
    except Exception:
        return {"success": False, "message": "Invalid request body"}

    # Extract and validate fields
    data: dict[str, Any] = {}
    allowed_fields = [
        "database", "company", "name", "owner", "subdomain",
        "dbHost", "dbHostRead", "dbServer", "visible",
        "brandingPrefix", "brandingLogo",
        "adminContact", "adminPhone", "adminEmail", "billingEmail", "billingName",
    ]
    for field in allowed_fields:
        if field in body and body[field] is not None and body[field] != "":
            data[field] = body[field]

    if not data.get("database"):
        return {"success": False, "message": "Database name is required"}

    # Check for duplicates
    existing = overlord_repo.get_by_database(data["database"])
    if existing:
        return {"success": False, "message": f"Company with database '{data['database']}' already exists"}

    try:
        company_id = overlord_repo.insert(data)

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="overlord_company_created",
                detail=f"Created overlord company: database={data['database']}",
                context={"company_id": company_id, "database": data["database"]},
            )

        return {"success": True, "message": "Company created", "company_id": company_id}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/api/overlord/companies/{company_id}/update")
async def api_overlord_company_update(
    company_id: int,
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Update an overlord company row. Only allowed for managed rows."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_repo:
        return {"success": False, "message": "Overlord is not configured"}

    # Verify row exists
    company = overlord_repo.get_by_id(company_id)
    if not company:
        return {"success": False, "message": f"Company #{company_id} not found"}

    # Verify managed status
    db_name = company.get("database", "")
    tracking = tracking_repo.get(db_name) if tracking_repo and db_name else None
    if not tracking or tracking.status.value not in ("claimed", "synced"):
        return {"success": False, "message": "Only managed companies can be edited. Claim this company first."}

    try:
        body = await request.json()
    except Exception:
        return {"success": False, "message": "Invalid request body"}

    # Build update data (exclude companyID — it's the PK)
    data: dict[str, Any] = {}
    allowed_fields = [
        "company", "name", "owner", "subdomain",
        "dbHost", "dbHostRead", "dbServer", "visible",
        "brandingPrefix", "brandingLogo",
        "adminContact", "adminPhone", "adminEmail", "billingEmail", "billingName",
    ]
    for field in allowed_fields:
        if field in body:
            val = body[field]
            data[field] = val if val != "" else None

    if not data:
        return {"success": False, "message": "No fields to update"}

    try:
        overlord_repo.update_by_id(company_id, data)

        # Update tracking if routing fields changed
        if any(k in data for k in ("dbHost", "dbHostRead", "subdomain")):
            tracking_repo.update_synced(
                database_name=db_name,
                current_dbhost=data.get("dbHost", tracking.current_dbhost or ""),
                current_dbhost_read=data.get("dbHostRead", tracking.current_dbhost_read),
                current_subdomain=data.get("subdomain", tracking.current_subdomain),
            )

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="overlord_company_updated",
                detail=f"Updated overlord company #{company_id}: database={db_name}",
                context={"company_id": company_id, "database": db_name, "fields": list(data.keys())},
            )

        return {"success": True, "message": "Company updated"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/api/overlord/companies/{company_id}/delete")
async def api_overlord_company_delete(
    company_id: int,
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Delete an overlord company row. Only allowed for managed rows."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_repo:
        return {"success": False, "message": "Overlord is not configured"}

    company = overlord_repo.get_by_id(company_id)
    if not company:
        return {"success": False, "message": f"Company #{company_id} not found"}

    db_name = company.get("database", "")
    tracking = tracking_repo.get(db_name) if tracking_repo and db_name else None
    if not tracking or tracking.status.value not in ("claimed", "synced"):
        return {"success": False, "message": "Only managed companies can be deleted. Claim this company first."}

    try:
        overlord_repo.delete_by_id(company_id)

        # Release tracking
        tracking_repo.update_released(db_name, expected_job_id=tracking.job_id)

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=admin.user_id,
                action="overlord_company_deleted",
                detail=f"Deleted overlord company #{company_id}: database={db_name}",
                context={"company_id": company_id, "database": db_name},
            )

        return {"success": True, "message": f"Company '{db_name}' deleted"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/api/overlord/companies/{company_id}/claim")
async def api_overlord_company_claim(
    company_id: int,
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Claim an overlord company row for management by a deployed job."""
    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_manager:
        return {"success": False, "message": "Overlord is not configured"}

    company = overlord_repo.get_by_id(company_id)
    if not company:
        return {"success": False, "message": f"Company #{company_id} not found"}

    db_name = company.get("database", "")

    # Check if already managed
    existing = tracking_repo.get(db_name) if tracking_repo else None
    if existing and existing.status.value in ("claimed", "synced"):
        return {"success": False, "message": f"Already managed by job {existing.job_id}"}

    try:
        body = await request.json()
    except Exception:
        return {"success": False, "message": "Invalid request body"}

    job_id = body.get("job_id")
    if not job_id:
        return {"success": False, "message": "job_id is required"}

    # Verify job exists and is deployed
    job = None
    if hasattr(state, "job_repo") and state.job_repo:
        job = state.job_repo.get_job(job_id)
    if not job:
        return {"success": False, "message": f"Job {job_id} not found"}
    if getattr(job, "status", None) != JobStatus.DEPLOYED:
        return {"success": False, "message": f"Job must be in DEPLOYED status (current: {getattr(job, 'status', 'unknown')})"}

    try:
        overlord_manager.claim(
            database_name=db_name,
            job_id=job_id,
            created_by=admin.username if hasattr(admin, "username") else str(admin.user_id),
        )

        return {"success": True, "message": f"Claimed '{db_name}' for job {job_id}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/api/overlord/companies/{company_id}/release")
async def api_overlord_company_release(
    company_id: int,
    request: Request,
    state: Any = Depends(get_api_state),
    admin: User = Depends(require_admin),
) -> dict:
    """Release overlord management of a company row."""
    from pulldb.worker.overlord_manager import ReleaseAction

    overlord_manager, overlord_repo, tracking_repo = _get_overlord_repos(state)

    if not overlord_manager:
        return {"success": False, "message": "Overlord is not configured"}

    company = overlord_repo.get_by_id(company_id)
    if not company:
        return {"success": False, "message": f"Company #{company_id} not found"}

    db_name = company.get("database", "")
    tracking = tracking_repo.get(db_name) if tracking_repo else None
    if not tracking or tracking.status.value not in ("claimed", "synced"):
        return {"success": False, "message": "Company is not currently managed"}

    try:
        body = await request.json()
    except Exception:
        body = {}

    action_str = body.get("action", "RESTORE")
    try:
        release_action = ReleaseAction(action_str.upper())
    except ValueError:
        return {"success": False, "message": f"Invalid release action: {action_str}. Use RESTORE, CLEAR, or DELETE."}

    try:
        overlord_manager.release(
            database_name=db_name,
            job_id=tracking.job_id,
            action=release_action,
        )

        return {"success": True, "message": f"Released '{db_name}' (action: {release_action.value})"}
    except Exception as e:
        return {"success": False, "message": str(e)}
