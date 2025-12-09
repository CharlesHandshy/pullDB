"""Restore routes for Web2 interface."""

import os
import typing as t
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from pulldb.api.logic import enqueue_job
from pulldb.api.schemas import JobRequest
from pulldb.domain.models import User
from pulldb.domain.services.discovery import DiscoveryService
from pulldb.web.dependencies import get_api_state, require_login
from pulldb.infra.s3 import S3Client, BACKUP_FILENAME_REGEX
from pulldb.infra.factory import is_simulation_mode

router = APIRouter(prefix="/web/restore", tags=["web-restore"])
templates = Jinja2Templates(directory="pulldb/web/templates")


@router.get("/", response_class=HTMLResponse)
async def restore_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the restore page."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()

    return templates.TemplateResponse(
        "features/restore/restore.html",
        {
            "request": request,
            "hosts": hosts,
            "user": user,
            "active_nav": "restore",
        },
    )


@router.get("/search-customers", response_class=HTMLResponse)
async def search_customers(
    request: Request,
    q: str = Query(..., min_length=3),
    state: Any = Depends(get_api_state),
) -> HTMLResponse:
    """HTMX endpoint to search customers."""
    service = DiscoveryService()
    matches = await run_in_threadpool(service.search_customers, q, 10)

    results = [{"value": c, "label": c, "sublabel": None} for c in matches]

    return templates.TemplateResponse(
        "features/restore/partials/customer_results.html",
        {"request": request, "results": results}
    )


@router.get("/search-backups", response_class=HTMLResponse)
async def search_backups(
    request: Request,
    customer: str = Query(...),
    env: str = Query("both"),
) -> HTMLResponse:
    """HTMX endpoint to search backups for a customer."""
    service = DiscoveryService()
    domain_backups = await run_in_threadpool(
        service.search_backups, customer, env, None, 10
    )

    # Convert to dicts for template
    backups = [
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

    return templates.TemplateResponse(
        "features/restore/partials/backup_results.html",
        {"request": request, "backups": backups}
    )


@router.post("/")
async def restore_submit(
    request: Request,
    customer: str = Form(...),
    s3env: str = Form(...),
    dbhost: str | None = Form(None),
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> Any:
    """Handle restore form submission."""
    env_val = s3env if s3env in ("staging", "prod") else None

    req = JobRequest(
        user=user.username,
        customer=customer,
        env=env_val,
        dbhost=dbhost if dbhost else None,
    )

    try:
        await run_in_threadpool(enqueue_job, state, req)
        return RedirectResponse(url="/web/jobs", status_code=303)
    except Exception as exc:
        # Re-render form with error
        hosts = []
        if hasattr(state, "host_repo") and state.host_repo:
            hosts = state.host_repo.get_enabled_hosts()
            
        return templates.TemplateResponse(
            "features/restore/restore.html",
            {
                "request": request,
                "hosts": hosts,
                "user": user,
                "error": str(exc),
                "active_nav": "restore",
                # Preserve form values
                "form": {
                    "customer": customer,
                    "s3env": s3env,
                    "dbhost": dbhost,
                }
            },
            status_code=400
        )
