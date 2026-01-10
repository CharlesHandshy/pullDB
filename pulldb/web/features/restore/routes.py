"""Restore routes for Web2 interface."""

import os
import typing as t
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, Request, Query, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse

from pulldb.api.logic import enqueue_job
from pulldb.api.schemas import JobRequest
from pulldb.domain.models import User, UserRole
from pulldb.domain.naming import normalize_customer_name
from pulldb.web.dependencies import get_api_state, require_login, templates
from pulldb.infra.s3 import S3Client, BACKUP_FILENAME_REGEX
from pulldb.infra.factory import is_simulation_mode
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

router = APIRouter(prefix="/web/restore", tags=["web-restore"])

# API base URL for internal calls (UI calls API for all search operations)
_API_BASE_URL = os.getenv("PULLDB_API_URL", "http://localhost:8080")


def _get_allowed_hosts_for_user(user: User, all_hosts: list) -> list:
    """Filter hosts based on user's allowed_hosts.
    
    All users (including admins) only get their assigned hosts.
    Note: allowed_hosts stores canonical hostnames.
    """
    if not user.allowed_hosts:
        return []
    
    return [h for h in all_hosts if h.hostname in user.allowed_hosts]


def _get_default_host_for_user(user: User, customer: str | None, state: Any) -> str | None:
    """Determine the default host based on user's history with this customer.
    
    Priority:
    1. Most recently used host for this customer by this user
    2. User's configured default_host
    3. None
    """
    if customer and hasattr(state, 'job_repo') and state.job_repo:
        # Try to find user's previous job for this customer
        try:
            jobs = state.job_repo.find_recent_by_user_and_customer(
                user.username, customer, limit=1
            )
            if jobs and jobs[0].dbhost:
                return str(jobs[0].dbhost)
        except Exception:
            pass  # Fall through to default
    
    return user.default_host


@router.get("/", response_class=HTMLResponse)
async def restore_page(
    request: Request,
    for_user: bool = Query(False),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the restore page.
    
    Args:
        for_user: If True and user is manager/admin, show user selector dropdown.
    """
    all_hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        all_hosts = state.host_repo.get_enabled_hosts()

    allowed_hosts = _get_allowed_hosts_for_user(user, all_hosts)
    default_host = user.default_host
    
    # Get managed users for "Submit for User" feature (managers/admins only)
    managed_users = []
    show_user_selector = False
    if for_user and user.role in (UserRole.MANAGER, UserRole.ADMIN):
        show_user_selector = True
        if hasattr(state, "user_repo") and state.user_repo:
            if user.role == UserRole.ADMIN:
                # Admins can submit for any user
                if hasattr(state.user_repo, "get_users_with_job_counts"):
                    all_users = state.user_repo.get_users_with_job_counts()
                    managed_users = [u for u in all_users if not getattr(u, "disabled_at", None)]
            else:
                # Managers can only submit for their managed users
                if hasattr(state.user_repo, "get_users_managed_by"):
                    managed_users = state.user_repo.get_users_managed_by(user.user_id)
                    managed_users = [u for u in managed_users if not u.disabled_at]

    return templates.TemplateResponse(
        "features/restore/restore.html",
        {
            "request": request,
            "breadcrumbs": get_breadcrumbs("restore"),
            "allowed_hosts": allowed_hosts,
            "default_host": default_host,
            "user": user,
            "active_nav": "restore",
            "show_user_selector": show_user_selector,
            "managed_users": managed_users,
        },
    )


@router.get("/search-customers", response_class=JSONResponse)
async def search_customers(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    state: Any = Depends(get_api_state),
) -> JSONResponse:
    """JSON endpoint to search customers via API.

    Proxies to /api/customers/search for unified search behavior.
    Returns a list of customers matching the query prefix or pattern.
    Supports wildcard patterns (* and ?) when detected in query.
    """
    # Forward session cookie for API authentication
    cookies = {}
    if session_token := request.cookies.get("session_token"):
        cookies["session_token"] = session_token
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_API_BASE_URL}/api/customers/search",
                params={"q": q, "limit": limit},
                cookies=cookies,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            {"results": [], "total": 0, "prefix": q, "error": f"API error: {e.response.status_code}"},
            status_code=200,  # Return 200 to frontend, error in payload
        )
    except httpx.RequestError as e:
        return JSONResponse(
            {"results": [], "total": 0, "prefix": q, "error": f"Connection error: {e}"},
            status_code=200,
        )

    # Transform API response for frontend compatibility
    customers = data.get("customers", [])
    results = [{"value": c, "label": c} for c in customers]

    return JSONResponse({
        "results": results,
        "total": data.get("total", 0),
        "prefix": q[:3] if len(q) >= 3 else q,
        "is_pattern": data.get("is_pattern", False),
    })


@router.get("/search-backups", response_class=HTMLResponse)
async def search_backups(
    request: Request,
    customer: str = Query(...),
    env: str = Query("both"),
    date_from: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> HTMLResponse:
    """HTMX endpoint to search backups via API.

    Proxies to /api/backups/search for unified search behavior.
    The API handles the 7-day date default.

    Args:
        customer: Customer name or pattern.
        env: Environment filter ('both', 'staging', 'prod').
        date_from: Start date filter in YYYYMMDD format. API defaults to 7 days ago.
        limit: Max results per page.
        offset: Pagination offset.
    """
    # Forward session cookie for API authentication
    cookies = {}
    if session_token := request.cookies.get("session_token"):
        cookies["session_token"] = session_token
    
    try:
        params: dict[str, t.Any] = {
            "customer": customer,
            "environment": env,
            "limit": limit,
            "offset": offset,
        }
        if date_from:
            params["date_from"] = date_from

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_API_BASE_URL}/api/backups/search",
                params=params,
                cookies=cookies,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        # Return empty results with error message
        return templates.TemplateResponse(
            "features/restore/partials/backup_results.html",
            {
                "request": request,
                "backups": [],
                "has_more": False,
                "total_count": 0,
                "offset": 0,
                "limit": limit,
                "customer": customer,
                "env": env,
                "date_from": date_from,
                "error": f"API error: {e.response.status_code}",
            }
        )
    except httpx.RequestError as e:
        return templates.TemplateResponse(
            "features/restore/partials/backup_results.html",
            {
                "request": request,
                "backups": [],
                "has_more": False,
                "total_count": 0,
                "offset": 0,
                "limit": limit,
                "customer": customer,
                "env": env,
                "date_from": date_from,
                "error": f"Connection error: {e}",
            }
        )

    # Transform API response for template
    backup_list = []
    for b in data.get("backups", []):
        # Parse ISO timestamp back to datetime for template
        ts = b.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = None

        backup_list.append({
            "customer": b.get("customer", ""),
            "timestamp": ts,
            "date": b.get("date", ""),
            "size_mb": b.get("size_mb", 0),
            "size_display": b.get("size_display", f"{b.get('size_mb', 0):.1f} MB"),
            "environment": b.get("environment", ""),
            "key": b.get("key", ""),
            "bucket": b.get("bucket", ""),
        })

    return templates.TemplateResponse(
        "features/restore/partials/backup_results.html",
        {
            "request": request,
            "backups": backup_list,
            "has_more": data.get("has_more", False),
            "total_count": data.get("total", 0),
            "offset": data.get("offset", 0),
            "limit": data.get("limit", limit),
            "customer": customer,
            "env": env,
            "date_from": date_from or data.get("date_from"),
        }
    )


@router.post("/")
async def restore_submit(
    request: Request,
    customer: str = Form(...),
    s3env: str = Form(...),
    dbhost: str = Form(...),
    suffix: str | None = Form(None),
    backup_key: str | None = Form(None),
    overwrite: str | None = Form(None),
    submit_as_user: str | None = Form(None),
    qatemplate: str | None = Form(None),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> Any:
    """Handle restore form submission with server-side host enforcement.
    
    Args:
        submit_as_user: Username to submit job on behalf of (managers/admins only).
        qatemplate: If 'true', this is a QA Template restore.
    """
    
    # Handle QA Template mode - override customer to 'qatemplate'
    if qatemplate == 'true':
        customer = 'qatemplate'
    
    # Determine the effective user for this job
    effective_username = user.username
    if submit_as_user and user.role in (UserRole.MANAGER, UserRole.ADMIN):
        # Validate the target user exists and caller can submit for them
        target_user = None
        if hasattr(state, "user_repo") and state.user_repo:
            if hasattr(state.user_repo, "get_user_by_username"):
                target_user = state.user_repo.get_user_by_username(submit_as_user)
        
        if target_user:
            # Managers can only submit for their managed users
            if user.role == UserRole.MANAGER:
                managed_users = []
                if hasattr(state.user_repo, "get_users_managed_by"):
                    managed_users = state.user_repo.get_users_managed_by(user.user_id)
                if target_user.user_id not in {u.user_id for u in managed_users}:
                    target_user = None  # Reset - not authorized
            
            if target_user:
                effective_username = target_user.username
    
    # === SERVER-SIDE HOST ENFORCEMENT ===
    # Block if user has no hosts at all
    if not user.has_any_hosts:
        return templates.TemplateResponse(
            "features/restore/restore.html",
            {
                "request": request,
                "allowed_hosts": [],
                "default_host": None,
                "user": user,
                "error": "You don't have any database hosts assigned. Contact an administrator to request access.",
                "active_nav": "restore",
                "show_user_selector": False,
                "managed_users": [],
            },
            status_code=403
        )
    
    # Get all hosts and filter to allowed
    all_hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        all_hosts = state.host_repo.get_enabled_hosts()
    
    allowed_hosts = _get_allowed_hosts_for_user(user, all_hosts)
    allowed_hostnames = {h.hostname for h in allowed_hosts}
    
    # Block if selected host is not in allowed list
    if dbhost and dbhost not in allowed_hostnames:
        return templates.TemplateResponse(
            "features/restore/restore.html",
            {
                "request": request,
                "allowed_hosts": allowed_hosts,
                "default_host": user.default_host,
                "user": user,
                "error": f"You are not authorized to use the selected database host.",
                "active_nav": "restore",
                "form": {
                    "customer": customer,
                    "s3env": s3env,
                    "dbhost": dbhost,
                    "suffix": suffix,
                    "overwrite": overwrite == "true",
                }
            },
            status_code=403
        )
    
    # === Validate suffix ===
    if suffix:
        suffix = suffix.lower()
        if not suffix.isalpha() or len(suffix) > 3:
            return templates.TemplateResponse(
                "features/restore/restore.html",
                {
                    "request": request,
                    "allowed_hosts": allowed_hosts,
                    "default_host": user.default_host,
                    "user": user,
                    "error": "Suffix must be up to 3 lowercase letters only.",
                    "active_nav": "restore",
                    "form": {
                        "customer": customer,
                        "s3env": s3env,
                        "dbhost": dbhost,
                        "suffix": suffix,
                        "overwrite": overwrite == "true",
                    }
                },
                status_code=400
            )
    
    # === Validate backup_key matches customer ===
    # If backup_key is provided, validate it contains the expected customer pattern
    # Pattern: {customer}/daily_mydumper_{customer}_
    validated_backup_path: str | None = None
    if backup_key:
        # Determine expected customer name for validation
        expected_customer = 'qatemplate' if qatemplate == 'true' else customer
        if expected_customer:
            # Extract customer-only part (letters only, lowercase)
            customer_letters = ''.join(ch for ch in expected_customer.lower() if ch.isalpha())
            if customer_letters:
                # Validate backup_key contains the expected pattern
                expected_pattern = f"{customer_letters}/daily_mydumper_{customer_letters}_"
                if expected_pattern not in backup_key.lower():
                    return templates.TemplateResponse(
                        "features/restore/restore.html",
                        {
                            "request": request,
                            "allowed_hosts": allowed_hosts,
                            "default_host": user.default_host,
                            "user": user,
                            "error": f"Selected backup does not match customer '{expected_customer}'. "
                                     f"Expected path to contain '{expected_pattern}'.",
                            "active_nav": "restore",
                            "form": {
                                "customer": customer,
                                "s3env": s3env,
                                "dbhost": dbhost,
                                "suffix": suffix,
                                "overwrite": overwrite == "true",
                            }
                        },
                        status_code=400
                    )
                # Validate path format - must be full S3 URI from template
                if backup_key.startswith("s3://"):
                    validated_backup_path = backup_key
                else:
                    # Legacy format without bucket - fail hard
                    return templates.TemplateResponse(
                        "features/restore/restore.html",
                        {
                            "request": request,
                            "allowed_hosts": allowed_hosts,
                            "default_host": user.default_host,
                            "user": user,
                            "error": "Invalid backup path format. Expected s3://bucket/key.",
                            "active_nav": "restore",
                            "form": {
                                "customer": customer,
                                "s3env": s3env,
                                "dbhost": dbhost,
                                "suffix": suffix,
                                "overwrite": overwrite == "true",
                            }
                        },
                        status_code=400
                    )

    env_val = s3env if s3env in ("staging", "prod") else None
    overwrite_val = overwrite == "true"
    is_qatemplate = qatemplate == 'true'
    
    # Normalize long customer names (> 42 chars get truncated + hash suffix)
    normalization_warning: str | None = None
    customer_for_api = customer
    if not is_qatemplate and customer:
        norm_result = normalize_customer_name(customer)
        customer_for_api = norm_result.normalized
        if norm_result.was_normalized:
            normalization_warning = norm_result.display_message

    req = JobRequest(
        user=effective_username,
        customer=customer_for_api if not is_qatemplate else None,
        qatemplate=is_qatemplate,
        env=env_val,
        dbhost=dbhost if dbhost else None,
        suffix=suffix if suffix else None,
        overwrite=overwrite_val,
        backup_path=validated_backup_path,
    )

    try:
        await run_in_threadpool(enqueue_job, state, req)
        # Build redirect URL with optional normalization warning
        redirect_url = "/web/jobs"
        if normalization_warning:
            redirect_url = f"/web/jobs?{urlencode({'restore_warning': normalization_warning})}"
        return RedirectResponse(url=redirect_url, status_code=303)
    except HTTPException as exc:
        # Handle specific HTTP errors (e.g., 409 Conflict for duplicate jobs)
        error_status = exc.status_code if hasattr(exc, 'status_code') else 400
        error_message = exc.detail if hasattr(exc, 'detail') else str(exc)
        return templates.TemplateResponse(
            "features/restore/restore.html",
            {
                "request": request,
                "allowed_hosts": allowed_hosts,
                "default_host": user.default_host,
                "user": user,
                "error": error_message,
                "active_nav": "restore",
                # Preserve form values
                "form": {
                    "customer": customer,
                    "s3env": s3env,
                    "dbhost": dbhost,
                    "suffix": suffix,
                    "overwrite": overwrite_val,
                }
            },
            status_code=error_status
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "features/restore/restore.html",
            {
                "request": request,
                "allowed_hosts": allowed_hosts,
                "default_host": user.default_host,
                "user": user,
                "error": str(exc),
                "active_nav": "restore",
                # Preserve form values
                "form": {
                    "customer": customer,
                    "s3env": s3env,
                    "dbhost": dbhost,
                    "suffix": suffix,
                    "overwrite": overwrite_val,
                }
            },
            status_code=400
        )
