"""Restore routes for Web2 interface."""

import os
import typing as t
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, Query, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates

from pulldb.api.logic import enqueue_job
from pulldb.api.schemas import JobRequest
from pulldb.domain.models import User, UserRole
from pulldb.domain.services.discovery import DiscoveryService
from pulldb.web.dependencies import get_api_state, require_login
from pulldb.infra.s3 import S3Client, BACKUP_FILENAME_REGEX
from pulldb.infra.factory import is_simulation_mode

router = APIRouter(prefix="/web/restore", tags=["web-restore"])
templates = Jinja2Templates(directory="pulldb/web/templates")


def _get_allowed_hosts_for_user(user: User, all_hosts: list) -> list:
    """Filter hosts based on user's allowed_hosts.
    
    Admins get all hosts. Other users only get their allowed hosts.
    """
    if user.role == UserRole.ADMIN:
        return all_hosts
    
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
            "breadcrumbs": [
                {"label": "Dashboard", "url": "/web/dashboard"},
                {"label": "New Restore Job", "url": None},
            ],
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
    q: str = Query(..., min_length=3),
    limit: int = Query(100, ge=1, le=500),
    state: Any = Depends(get_api_state),
) -> JSONResponse:
    """JSON endpoint to search customers with caching support.
    
    Returns a list of customers matching the query prefix.
    The frontend caches results by 3-character prefix and filters client-side.
    """
    service = DiscoveryService()
    matches = await run_in_threadpool(service.search_customers, q, limit)

    results = [{"value": c, "label": c} for c in matches]

    return JSONResponse({
        "results": results,
        "total": len(results),
        "prefix": q[:3] if len(q) >= 3 else q,
    })


@router.get("/search-backups", response_class=HTMLResponse)
async def search_backups(
    request: Request,
    customer: str = Query(...),
    env: str = Query("both"),
) -> HTMLResponse:
    """HTMX endpoint to search backups for a customer."""
    service = DiscoveryService()
    domain_backups = await run_in_threadpool(
        service.search_backups, customer, env, None, 50
    )

    # Convert to dicts for template, sorted by timestamp (most recent first)
    backup_list = [
        {
            "customer": b.customer,
            "timestamp": b.timestamp,
            "date": b.date,
            "size_mb": b.size_mb,
            "environment": b.environment,
            "key": b.key,
            "bucket": b.bucket,
        }
        for b in domain_backups
    ]
    backup_list.sort(key=lambda x: x["timestamp"], reverse=True)  # type: ignore[arg-type, return-value]

    return templates.TemplateResponse(
        "features/restore/partials/backup_results.html",
        {"request": request, "backups": backup_list}
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
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> Any:
    """Handle restore form submission with server-side host enforcement.
    
    Args:
        submit_as_user: Username to submit job on behalf of (managers/admins only).
    """
    
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
    if not user.has_any_hosts and user.role != UserRole.ADMIN:
        return templates.TemplateResponse(
            "features/restore/restore.html",
            {
                "request": request,
                "allowed_hosts": [],
                "default_host": None,
                "user": user,
                "error": "You don't have any database hosts assigned. Contact your manager.",
                "active_nav": "restore",
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
    if dbhost and dbhost not in allowed_hostnames and user.role != UserRole.ADMIN:
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
    
    env_val = s3env if s3env in ("staging", "prod") else None
    overwrite_val = overwrite == "true"

    req = JobRequest(
        user=effective_username,
        customer=customer,
        env=env_val,
        dbhost=dbhost if dbhost else None,
        suffix=suffix if suffix else None,
        overwrite=overwrite_val,
    )

    try:
        await run_in_threadpool(enqueue_job, state, req)
        return RedirectResponse(url="/web/jobs", status_code=303)
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
