"""Database Discovery routes for admin UI.

HCA Layer: pages (pulldb/web/features/)

Provides a host-scoped database discovery view that:
- Lists all databases on a selected host
- Identifies which are managed by pullDB (deployed jobs)
- Allows claiming unmanaged databases for the current user
- Allows assigning databases to other users
- Allows removing claimed/assigned databases from tracking

This enables users who restore databases outside of pullDB
to bring them into the system via synthetic job records
(origin='claim' or origin='assign').
"""

from __future__ import annotations

import logging
import re
import uuid
from fnmatch import fnmatch as _fnmatch
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from pulldb.domain.models import User
from pulldb.web.dependencies import (
    get_api_state,
    require_admin,
    templates,
)
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin", tags=["web-admin-database-discovery"])

# Staging database pattern: {target}_{12-hex-chars}
_STAGING_PATTERN = re.compile(r"^(.+)_([0-9a-f]{12})$")


# =============================================================================
# Helpers
# =============================================================================


def _text_filter_match(cell: str, vals: list[str]) -> bool:
    """Match a cell value against text filter values with wildcard support."""
    for v in vals:
        if "*" in v or "?" in v:
            if _fnmatch(cell, v):
                return True
        else:
            if v in cell:
                return True
    return False


def _get_enriched_databases(
    state: Any,
    hostname: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Load databases from a host and enrich with job/management data.

    Returns:
        (rows, stats) where rows is a list of enriched database dicts and
        stats is {"total": N, "managed": N, "unmanaged": N}.

    Raises:
        ValueError: If hostname not found or disabled.
        Exception: On connection failure.
    """
    host = state.host_repo.get_host_by_hostname(hostname)
    if host is None:
        raise ValueError(f"Host '{hostname}' not found")
    if not host.enabled:
        raise ValueError(f"Host '{hostname}' is disabled")

    all_dbs = state.host_repo.list_databases(hostname)
    deployed_jobs = state.job_repo.get_deployed_jobs_for_host(hostname)

    # Fetch earliest table creation dates from information_schema
    # for databases that aren't managed by pullDB (best-effort).
    created_dates: dict[str, str] = {}
    try:
        created_dates = state.host_repo.get_database_created_dates(
            hostname, all_dbs,
        )
    except Exception:
        logger.debug(
            "Could not fetch information_schema created dates for %s",
            hostname,
            exc_info=True,
        )

    # Build maps: target → job, target → owner_count
    job_map: dict[str, Any] = {}
    owner_count_map: dict[str, int] = {}
    seen_owners: dict[str, set[str]] = {}
    for job in deployed_jobs:
        if job.target not in seen_owners:
            seen_owners[job.target] = set()
        owner_id = job.owner_user_id or job.owner_user_code or "unknown"
        seen_owners[job.target].add(owner_id)
        owner_count_map[job.target] = len(seen_owners[job.target])
        if job.target not in job_map:
            job_map[job.target] = job

    rows: list[dict[str, Any]] = []
    managed_count = 0

    for db_name in all_dbs:
        job = job_map.get(db_name)
        is_staging = bool(_STAGING_PATTERN.match(db_name))

        if job:
            managed_count += 1
            status = "Locked" if job.is_locked else "Managed"
            rows.append({
                "name": db_name,
                "status": status,
                "managed": True,
                "owner_user_code": job.owner_user_code or "",
                "owner_username": job.owner_username or "",
                "deployed_at": (
                    job.completed_at.isoformat() if job.completed_at else None
                ),
                "expires_at": (
                    job.expires_at.isoformat() if job.expires_at else None
                ),
                "job_id": job.id,
                "locked": job.is_locked,
                "owner_count": owner_count_map.get(db_name, 1),
                "is_staging": is_staging,
                "origin": job.origin,
            })
        else:
            rows.append({
                "name": db_name,
                "status": "Unmanaged",
                "managed": False,
                "owner_user_code": "",
                "owner_username": "",
                "deployed_at": created_dates.get(db_name),
                "expires_at": None,
                "job_id": None,
                "locked": False,
                "owner_count": 0,
                "is_staging": is_staging,
                "origin": None,
            })

    stats = {
        "total": len(rows),
        "managed": managed_count,
        "unmanaged": len(rows) - managed_count,
    }
    return rows, stats


# =============================================================================
# Page Routes
# =============================================================================


@router.get("/database-discovery", response_class=HTMLResponse)
async def database_discovery_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Render the database discovery page.

    Shows a host selector and, once a host is selected, a table of all
    databases on that host with their pullDB management status.
    """
    hosts_data: list[dict[str, str]] = []
    try:
        hosts = state.host_repo.get_enabled_hosts()
        hosts_data = [
            {
                "hostname": h.hostname,
                "alias": h.host_alias or h.hostname,
            }
            for h in hosts
        ]
    except Exception:
        logger.warning("Failed to load hosts for database discovery", exc_info=True)

    return templates.TemplateResponse(
        "features/admin/database_discovery.html",
        {
            "request": request,
            "active_nav": "admin",
            "user": user,
            "hosts": hosts_data,
            "breadcrumbs": get_breadcrumbs("admin_database_discovery"),
        },
    )


# =============================================================================
# API Routes
# =============================================================================


@router.get("/api/database-discovery/databases/paginated")
async def api_databases_paginated(
    request: Request,
    hostname: str = Query(..., description="Target host to enumerate"),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
    page: int = Query(0, ge=0),
    pageSize: int = Query(50, ge=10, le=500),
    sortColumn: str | None = None,
    sortDirection: str | None = None,
) -> dict:
    """Paginated database listing for LazyTable.

    Supports filtering via ``filter_<column>`` query params and sorting
    via ``sortColumn`` / ``sortDirection``.
    """
    try:
        rows, stats = _get_enriched_databases(state, hostname)
    except ValueError as exc:
        return {
            "rows": [],
            "totalCount": 0,
            "filteredCount": 0,
            "page": 0,
            "pageSize": pageSize,
            "error": str(exc),
            "stats": {"total": 0, "managed": 0, "unmanaged": 0},
        }
    except Exception as exc:
        logger.exception("Database discovery paginated failed for %s", hostname)
        return {
            "rows": [],
            "totalCount": 0,
            "filteredCount": 0,
            "page": 0,
            "pageSize": pageSize,
            "error": str(exc),
            "stats": {"total": 0, "managed": 0, "unmanaged": 0},
        }

    total_count = len(rows)

    # ----- Apply filters -----
    text_filters: dict[str, list[str]] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter_") and value:
            col_key = key[7:]
            text_filters[col_key] = [
                v.strip().lower() for v in value.split(",") if v.strip()
            ]

    if text_filters:
        filtered: list[dict[str, Any]] = []
        for row in rows:
            match = True
            for col, vals in text_filters.items():
                if col == "status":
                    cell = row.get("status", "").lower()
                    if cell not in vals:
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

    # ----- Apply sorting -----
    if sortColumn:
        reverse = sortDirection == "desc"
        if sortColumn == "managed":
            rows.sort(
                key=lambda r: (r.get("managed") is None, r.get("managed", False)),
                reverse=reverse,
            )
        elif sortColumn == "owner_count":
            rows.sort(key=lambda r: r.get("owner_count") or 0, reverse=reverse)
        elif sortColumn in ("deployed_at", "expires_at"):
            rows.sort(
                key=lambda r: (r.get(sortColumn) is None, r.get(sortColumn) or ""),
                reverse=reverse,
            )
        else:
            rows.sort(
                key=lambda r: (
                    r.get(sortColumn) is None,
                    str(r.get(sortColumn) or "").lower(),
                ),
                reverse=reverse,
            )

    # ----- Paginate -----
    start = page * pageSize
    page_rows = rows[start : start + pageSize]

    return {
        "rows": page_rows,
        "totalCount": total_count,
        "filteredCount": filtered_count,
        "page": page,
        "pageSize": pageSize,
        "stats": stats,
    }


@router.get("/api/database-discovery/databases/paginated/distinct")
async def api_databases_distinct(
    request: Request,
    column: str,
    hostname: str = Query(..., description="Target host"),
    filter_order: str | None = None,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> list:
    """Distinct values for a column, used by LazyTable checkbox filters."""
    # Validate column against known filterable columns
    _VALID_FILTER_COLUMNS = {"status", "name", "owner_user_code"}
    if column not in _VALID_FILTER_COLUMNS:
        return []

    try:
        rows, _ = _get_enriched_databases(state, hostname)
    except Exception:
        return []

    # Cascading filters: apply filters for columns appearing before this one
    if filter_order:
        ordered_cols = [c.strip() for c in filter_order.split(",") if c.strip()]
        if column in ordered_cols:
            ordered_cols = ordered_cols[: ordered_cols.index(column)]

        for col_key in ordered_cols:
            filter_val = request.query_params.get(f"filter_{col_key}")
            if filter_val:
                vals = [
                    v.strip().lower() for v in filter_val.split(",") if v.strip()
                ]
                filtered = []
                for row in rows:
                    if col_key == "status":
                        if row.get("status", "").lower() in vals:
                            filtered.append(row)
                    else:
                        cell = str(row.get(col_key, "") or "").lower()
                        if _text_filter_match(cell, vals):
                            filtered.append(row)
                rows = filtered

    # Collect distinct values
    values: set[str] = set()
    for row in rows:
        if column == "status":
            values.add(row.get("status", "Unmanaged"))
        else:
            val = row.get(column)
            if val is not None and val != "":
                values.add(str(val))

    return sorted(values)


@router.get("/api/database-discovery/users")
async def api_list_users_for_assignment(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """List active users for the assign-to-user dropdown.

    Returns a compact list of users suitable for a <select> dropdown.
    """
    try:
        users = state.user_repo.list_users()
        return {
            "users": [
                {
                    "user_id": u.user_id,
                    "username": u.username,
                    "user_code": u.user_code,
                }
                for u in users
                if not u.disabled
            ],
        }
    except Exception as exc:
        logger.exception("Failed to list users for assignment")
        return {"error": str(exc), "users": []}


@router.post("/api/database-discovery/claim")
async def api_claim_database(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Claim an unmanaged database for the current user.

    Creates a synthetic deployed job with origin='claim' to track the database
    in pullDB without going through the restore pipeline. The actual database
    is NOT modified — only a tracking record is created.

    Request body:
        {
            "hostname": "db-host-01.example.com",
            "database": "external_db"
        }
    """
    try:
        body = await request.json()
        hostname = body.get("hostname", "").strip()
        database = body.get("database", "").strip()

        if not hostname or not database:
            return {"success": False, "message": "hostname and database are required"}

        # Validate host
        host = state.host_repo.get_host_by_hostname(hostname)
        if host is None:
            return {"success": False, "message": f"Host '{hostname}' not found"}

        # Validate database exists on host
        if not state.host_repo.database_exists(hostname, database):
            return {
                "success": False,
                "message": f"Database '{database}' does not exist on {hostname}",
            }

        # Check if already managed
        existing = state.job_repo.has_any_deployed_job_for_target(database, hostname)
        if existing:
            return {
                "success": False,
                "message": (
                    f"Database '{database}' is already managed by "
                    f"{existing.owner_username} ({existing.owner_user_code})"
                ),
            }

        # Create synthetic deployed job to track this database
        job_id = str(uuid.uuid4())
        state.job_repo.create_claimed_job(
            job_id=job_id,
            owner_user_id=user.user_id,
            owner_username=user.username,
            owner_user_code=user.user_code,
            target=database,
            dbhost=hostname,
            origin="claim",
        )

        logger.info(
            "User %s (%s) claimed database '%s' on host '%s' (job %s)",
            user.username,
            user.user_code,
            database,
            hostname,
            job_id[:12],
        )

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="database_discovery_claim",
                detail=f"Claimed database '{database}' on host '{hostname}' (job {job_id[:12]})",
                context={"hostname": hostname, "database": database, "job_id": job_id},
            )

        return {
            "success": True,
            "message": f"Database '{database}' is now tracked under your account.",
        }

    except Exception as exc:
        logger.exception("Claim database failed")
        return {"success": False, "message": str(exc)}


@router.post("/api/database-discovery/assign")
async def api_assign_database(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Assign an unmanaged database to a specific user.

    Creates a synthetic deployed job with origin='assign' to track the database
    under the specified user. Admin-only. The actual database is NOT modified.

    Request body:
        {
            "hostname": "db-host-01.example.com",
            "database": "external_db",
            "target_user_id": "uuid-of-target-user"
        }
    """
    try:
        body = await request.json()
        hostname = body.get("hostname", "").strip()
        database = body.get("database", "").strip()
        target_user_id = body.get("target_user_id", "").strip()

        if not hostname or not database or not target_user_id:
            return {
                "success": False,
                "message": "hostname, database, and target_user_id are required",
            }

        # Validate host
        host = state.host_repo.get_host_by_hostname(hostname)
        if host is None:
            return {"success": False, "message": f"Host '{hostname}' not found"}

        # Validate target user exists
        target_user = state.user_repo.get_user_by_id(target_user_id)
        if target_user is None:
            return {"success": False, "message": "Target user not found"}

        # Validate database exists on host
        if not state.host_repo.database_exists(hostname, database):
            return {
                "success": False,
                "message": f"Database '{database}' does not exist on {hostname}",
            }

        # Check if already managed
        existing = state.job_repo.has_any_deployed_job_for_target(database, hostname)
        if existing:
            return {
                "success": False,
                "message": (
                    f"Database '{database}' is already managed by "
                    f"{existing.owner_username} ({existing.owner_user_code})"
                ),
            }

        # Create synthetic deployed job assigned to the target user
        job_id = str(uuid.uuid4())
        state.job_repo.create_claimed_job(
            job_id=job_id,
            owner_user_id=target_user.user_id,
            owner_username=target_user.username,
            owner_user_code=target_user.user_code,
            target=database,
            dbhost=hostname,
            origin="assign",
        )

        logger.info(
            "Admin %s assigned database '%s' on '%s' to user %s (%s) (job %s)",
            user.username,
            database,
            hostname,
            target_user.username,
            target_user.user_code,
            job_id[:12],
        )

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="database_discovery_assign",
                target_user_id=target_user.user_id,
                detail=(
                    f"Assigned database '{database}' on host '{hostname}' "
                    f"to {target_user.username} ({target_user.user_code}) (job {job_id[:12]})"
                ),
                context={
                    "hostname": hostname,
                    "database": database,
                    "target_user_id": target_user.user_id,
                    "job_id": job_id,
                },
            )

        return {
            "success": True,
            "message": (
                f"Database '{database}' is now tracked under "
                f"{target_user.username} ({target_user.user_code})."
            ),
        }

    except Exception as exc:
        logger.exception("Assign database failed")
        return {"success": False, "message": str(exc)}


@router.post("/api/database-discovery/remove")
async def api_remove_database(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_admin),
) -> dict:
    """Remove a claimed/assigned database from pullDB management.

    Only removes tracking for databases with origin 'claim' or 'assign'.
    Databases restored through the normal pipeline (origin='restore') cannot
    be removed via this endpoint — use the standard job delete flow instead.

    The actual database on the target host is NOT dropped; only the synthetic
    job record is hard-deleted.

    Request body:
        {
            "hostname": "db-host-01.example.com",
            "database": "external_db"
        }
    """
    try:
        body = await request.json()
        hostname = body.get("hostname", "").strip()
        database = body.get("database", "").strip()

        if not hostname or not database:
            return {"success": False, "message": "hostname and database are required"}

        # Find the deployed job for this database
        job = state.job_repo.has_any_deployed_job_for_target(database, hostname)
        if not job:
            return {
                "success": False,
                "message": f"Database '{database}' is not currently managed by pullDB",
            }

        # Only allow removal of claimed/assigned databases
        if job.origin not in ("claim", "assign"):
            return {
                "success": False,
                "message": (
                    f"Database '{database}' was restored through the normal pipeline. "
                    f"Use the job delete flow instead (job {job.id[:12]})."
                ),
            }

        # Hard-delete the synthetic job record (no database drops)
        # Note: We don't append a job_event here because hard_delete_job
        # removes all events. The audit_repo log below captures the action.
        state.job_repo.hard_delete_job(job.id)

        logger.info(
            "Admin %s removed %s database '%s' on '%s' (job %s, owner %s)",
            user.username,
            job.origin,
            database,
            hostname,
            job.id[:12],
            job.owner_username,
        )

        # Audit log
        if hasattr(state, "audit_repo") and state.audit_repo:
            state.audit_repo.log_action(
                actor_user_id=user.user_id,
                action="database_discovery_remove",
                target_user_id=job.owner_user_id,
                detail=(
                    f"Removed {job.origin} tracking of '{database}' on '{hostname}' "
                    f"(was owned by {job.owner_username}, job {job.id[:12]})"
                ),
                context={
                    "hostname": hostname,
                    "database": database,
                    "job_id": job.id,
                    "origin": job.origin,
                    "previous_owner": job.owner_username,
                },
            )

        return {
            "success": True,
            "message": f"Database '{database}' removed from pullDB tracking.",
        }

    except Exception as exc:
        logger.exception("Remove database failed")
        return {"success": False, "message": str(exc)}
