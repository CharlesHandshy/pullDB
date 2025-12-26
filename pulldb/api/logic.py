"""Business logic for pullDB API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status

from pulldb.api.schemas import JobRequest, JobResponse
from pulldb.api.types import APIState
from pulldb.domain.errors import StagingError
from pulldb.domain.models import Job, JobStatus, User
from pulldb.infra.metrics import MetricLabels, emit_counter, emit_event
from pulldb.worker.staging import generate_staging_name


def _letters_only(value: str) -> str:
    """Return lowercase letters-only subset of *value*."""
    return "".join(ch for ch in value.lower() if ch.isalpha())


def _select_dbhost(state: APIState, req: JobRequest, user: User) -> str:
    """Select database host for job, using user's default if not specified.

    Priority:
    1. Explicitly requested host (req.dbhost)
    2. User's configured default_host
    3. System default_dbhost from config
    4. mysql_host from config (fallback)
    """
    if req.dbhost:
        return req.dbhost
    if user.default_host:
        return user.default_host
    if state.config.default_dbhost:
        return state.config.default_dbhost
    return state.config.mysql_host


def _construct_target(user: User, req: JobRequest) -> str:
    """Construct target database name from user code and customer/qatemplate.
    
    Target names MUST be lowercase letters only (a-z). No numbers, no special
    characters, no underscores. This is a hard requirement enforced at:
    - API level (this function)
    - CLI level (parse.py validation)
    - Web UI level (JavaScript validation + input filtering)
    """
    if req.qatemplate:
        target = f"{user.user_code}qatemplate"
        if req.suffix:
            target = f"{target}{req.suffix}"
        return target

    customer_value = req.customer or ""
    sanitized = _letters_only(customer_value)
    if not sanitized:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Customer identifier must include at least one alphabetic character. "
                f"Received '{customer_value}'."
            ),
        )
    target = f"{user.user_code}{sanitized}"
    
    # Append optional suffix if provided
    if req.suffix:
        target = f"{target}{req.suffix}"
    
    # Final validation: target must be lowercase letters only
    if not target.isalpha() or not target.islower():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Target database name must contain only lowercase letters (a-z). "
                f"Generated target '{target}' contains invalid characters."
            ),
        )
    return target


def _options_snapshot(req: JobRequest) -> dict[str, str]:
    opts: dict[str, str] = {
        "customer_id": req.customer or "",
        "is_qatemplate": str(req.qatemplate).lower(),
        "overwrite": str(req.overwrite).lower(),
        "api_version": "v1",
    }
    if req.date:
        opts["date"] = req.date
    if req.env:
        opts["env"] = req.env
    return opts


def validate_job_request(req: JobRequest) -> None:
    """Validate that exactly one of customer or qatemplate is specified."""
    if bool(req.customer) == bool(req.qatemplate):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Must specify exactly one of customer or qatemplate for "
                "restore request."
            ),
        )


def check_host_active_capacity(state: APIState, hostname: str) -> None:
    """Check if host has capacity for more active jobs.

    Enforces per-host active job limit (queued + running).

    Args:
        state: API state with repositories.
        hostname: Database host to check.

    Raises:
        HTTPException: 429 Too Many Requests if host at capacity.
    """
    if not state.host_repo.check_host_active_capacity(hostname):
        host = state.host_repo.get_host_by_hostname(hostname)
        max_active = host.max_active_jobs if host else 0
        
        # Frozen host (max_active_jobs = 0) gets a specific message
        if max_active == 0:
            emit_event(
                "job_enqueue_rejected",
                f"Host frozen for {hostname}: queue disabled (max_active_jobs=0)",
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="frozen",
                ),
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Host '{hostname}' is frozen (queue disabled). No new jobs accepted.",
            )
        
        active_count = state.job_repo.count_active_jobs_for_host(hostname)
        emit_event(
            "job_enqueue_rejected",
            f"Host capacity reached for {hostname}: {active_count}/{max_active} active jobs",
            labels=MetricLabels(
                target="",
                phase="enqueue",
                status="rate_limited",
            ),
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Host '{hostname}' has {active_count} active jobs (limit: {max_active}). "
                "Please wait for a job to finish or choose another host."
            ),
        )


def check_concurrency_limits(state: APIState, user: User) -> None:
    """Check concurrency limits before enqueueing a job.

    Enforces per-user and global active job limits. A limit of 0 means unlimited.

    Args:
        state: API state with repositories.
        user: User attempting to enqueue a job.

    Raises:
        HTTPException: 429 Too Many Requests if limit exceeded.
    """
    # Check global limit first (higher priority)
    global_limit = state.settings_repo.get_max_active_jobs_global()
    if global_limit > 0:
        global_active = state.job_repo.count_all_active_jobs()
        if global_active >= global_limit:
            emit_event(
                "job_enqueue_rejected",
                f"Global limit reached: {global_active}/{global_limit} active jobs",
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="rate_limited",
                ),
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"System at capacity: {global_active} active jobs "
                    f"(limit: {global_limit}). Please try again later."
                ),
            )

    # Check per-user limit (user-specific overrides system default)
    # NULL = use system default, 0 = unlimited, N > 0 = specific limit
    if user.max_active_jobs is not None:
        per_user_limit = user.max_active_jobs
    else:
        per_user_limit = state.settings_repo.get_max_active_jobs_per_user()
    
    if per_user_limit > 0:
        user_active = state.job_repo.count_active_jobs_for_user(user.user_id)
        if user_active >= per_user_limit:
            emit_event(
                "job_enqueue_rejected",
                (
                    f"User limit reached for {user.username}: "
                    f"{user_active}/{per_user_limit}"
                ),
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="rate_limited",
                ),
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You have {user_active} active jobs (limit: {per_user_limit}). "
                    "Please wait for a job to finish."
                ),
            )


def enqueue_job(state: APIState, req: JobRequest) -> JobResponse:
    """Enqueue a new restore job."""
    validate_job_request(req)

    # Get user - do NOT auto-create, user must register first
    user = state.user_repo.get_user_by_username(username=req.user)
    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"User '{req.user}' not found. Use 'pulldb register' to create an account.",
        )

    # Check if user is disabled (pending admin approval)
    if user.disabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Your account is pending approval. Contact an administrator to enable your account.",
        )

    target = _construct_target(user, req)
    dbhost = _select_dbhost(state, req, user)  # Pass user for default_host

    # Validate user can use the selected host
    if not user.can_use_host(dbhost):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"You are not authorized to use database host '{dbhost}'. "
                   f"Contact an administrator to request access."
        )

    # Proactive duplicate check - fail fast with clear message
    if state.job_repo.has_active_jobs_for_target(target, dbhost):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A restore for '{target}' on '{dbhost}' is already queued or running. "
                   f"Please wait for it to complete or cancel it first."
        )

    # Phase 2: Concurrency controls - check limits before job creation
    check_concurrency_limits(state, user)
    
    # Phase 3: Per-host capacity check - ensure host can accept more jobs
    check_host_active_capacity(state, dbhost)

    job_id = str(uuid.uuid4())
    staging_name = generate_staging_name(target, job_id)

    job = Job(
        id=job_id,
        owner_user_id=user.user_id,
        owner_username=user.username,
        owner_user_code=user.user_code,
        target=target,
        staging_name=staging_name,
        dbhost=dbhost,
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(UTC),
        options_json=_options_snapshot(req),
        retry_count=0,
    )

    try:
        state.job_repo.enqueue_job(job)
    except ValueError as exc:
        message = str(exc)
        if "already has an active job" in message:
            emit_event(
                "job_enqueue_conflict",
                message,
                labels=MetricLabels(
                    job_id=job_id,
                    target=target,
                    phase="enqueue",
                    status="conflict",
                ),
            )
            raise HTTPException(status.HTTP_409_CONFLICT, detail=message) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=message) from exc
    except StagingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - MySQL errors surfaced as 500
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue job due to unexpected error: {exc}",
        ) from exc

    stored = state.job_repo.get_job_by_id(job_id) or job

    emit_counter(
        "jobs_enqueued_total",
        labels=MetricLabels(
            job_id=job_id,
            target=target,
            phase="enqueue",
            status="queued",
        ),
    )

    return JobResponse(
        job_id=job_id,
        target=target,
        staging_name=stored.staging_name,
        status=stored.status.value,
        owner_username=stored.owner_username,
        owner_user_code=stored.owner_user_code,
        submitted_at=stored.submitted_at,
    )
