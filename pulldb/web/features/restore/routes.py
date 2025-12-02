"""Restore routes for pullDB web UI.

HCA Feature Module: restore
Handles: restore form, restore submission
Size: ~180 lines (HCA compliant)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from pulldb.web.dependencies import (
    AuthenticatedUser,
    get_api_state,
    templates,
)
from pulldb.web.exceptions import render_error_page

if TYPE_CHECKING:
    from pulldb.api.main import APIState

router = APIRouter(prefix="/web", tags=["web-restore"])


@router.get("/restore", response_class=HTMLResponse)
async def restore_page(
    request: Request,
    user: AuthenticatedUser,
    state: "APIState" = Depends(get_api_state),
    customer: str | None = None,
    date: str | None = None,
    s3env: str | None = None,
) -> Response:
    """Display restore form."""
    hosts = []
    if hasattr(state, "host_repo") and state.host_repo:
        hosts = state.host_repo.get_enabled_hosts()
    
    recent_jobs = []
    if hasattr(state, "job_repo") and state.job_repo:
        if hasattr(state.job_repo, "get_user_recent_jobs"):
            recent_jobs = state.job_repo.get_user_recent_jobs(user.user_id, limit=5)
    
    prefill = {
        "customer": customer or "",
        "date": date or "",
        "s3env": s3env or "",
    }
    
    return templates.TemplateResponse(
        request=request,
        name="restore.html",
        context={
            "user": user,
            "hosts": hosts,
            "recent_jobs": recent_jobs,
            "prefill": prefill,
        },
    )


@router.post("/restore")
async def restore_submit(
    request: Request,
    user: AuthenticatedUser,
    state: "APIState" = Depends(get_api_state),
    customer: str | None = Form(None),
    date: str | None = Form(None),
    s3env: str | None = Form(None),
    qatemplate: str = Form("false"),
    dbhost: str | None = Form(None),
    target: str | None = Form(None),
    overwrite: str | None = Form(None),
) -> Response:
    """Handle restore form submission."""
    is_qatemplate = qatemplate.lower() == "true"
    
    try:
        if not hasattr(state, "settings_repo") or state.settings_repo is None:
            # Dev server mock flow
            job_id = str(uuid.uuid4())
            
            if is_qatemplate:
                target_name = f"{user.user_code}qatemplate"
            else:
                clean_customer = "".join(c for c in (customer or "").lower() if c.isalpha())
                target_name = f"{user.user_code}{clean_customer}"
            
            from unittest.mock import MagicMock
            job = MagicMock()
            job.id = job_id
            job.job_id = job_id
            job.target = target_name
            job.staging_name = f"{target_name}_{job_id.replace('-', '')[:12]}"
            job.status = "queued"
            job.owner_user_id = user.user_id
            job.owner_username = user.username
            job.owner_user_code = user.user_code
            job.user_code = user.user_code
            job.username = user.username
            job.created_at = datetime.now(UTC)
            job.submitted_at = datetime.now(UTC)
            job.started_at = None
            job.finished_at = None
            job.completed_at = None
            job.dbhost = dbhost or "localhost"
            job.worker_id = None
            job.error_detail = None
            job.source_customer = customer if not is_qatemplate else "QA Template"
            job.backup_env = s3env if s3env and s3env != "both" else "prd"
            job.backup_file = f"{customer or 'qatemplate'}/{job.backup_env}/{date or 'latest'}/backup.tar.gz"
            job.current_operation = None
            job.options_json = {
                "is_qatemplate": str(is_qatemplate).lower(),
                "customer_id": customer,
                "env": s3env,
                "overwrite": str(overwrite == "true").lower(),
            }
            
            if hasattr(state, "job_repo") and hasattr(state.job_repo, "enqueue_job"):
                state.job_repo.enqueue_job(job)
            
            return RedirectResponse(
                url=f"/web/jobs/{job_id}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        
        # Production flow
        from pulldb.api.main import JobRequest, _enqueue_job
        from starlette.concurrency import run_in_threadpool
        
        req = JobRequest(
            user=user.username,
            customer=customer if not is_qatemplate else None,
            qatemplate=is_qatemplate,
            dbhost=dbhost if dbhost else None,
            date=date,
            env=s3env if s3env and s3env != "both" else None,
            overwrite=overwrite == "true",
        )
        
        job_response = await run_in_threadpool(_enqueue_job, state, req)
        
        return RedirectResponse(
            url=f"/web/jobs/{job_response.job_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except HTTPException as exc:
        return render_error_page(
            request=request,
            user=user,
            status_code=exc.status_code,
            title="Job Submission Failed",
            message=exc.detail,
            suggestions=[
                "Check that the customer name and backup date are valid",
                "Ensure you don't already have an active job for this target",
            ],
            back_url="/web/restore",
        )
    except Exception as exc:
        return render_error_page(
            request=request,
            user=user,
            status_code=500,
            title="Unexpected Error",
            message=str(exc),
            suggestions=["Try again in a few moments"],
            back_url="/web/restore",
        )
