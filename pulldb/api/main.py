"""FastAPI-based API service for pullDB."""

from __future__ import annotations

import typing as t
import uuid
import os
import json
from datetime import UTC, datetime

import fastapi
import pydantic
import uvicorn
from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from pulldb.domain.config import Config
from pulldb.domain.errors import StagingError
from pulldb.domain.models import Job, JobStatus, User
from pulldb.infra.metrics import MetricLabels, emit_counter, emit_event
from pulldb.infra.mysql import (
    HostRepository,
    JobRepository,
    MySQLPool,
    SettingsRepository,
    UserRepository,
    build_default_pool,
)
from pulldb.infra.secrets import CredentialResolver
from pulldb.worker.staging import generate_staging_name


DEFAULT_STATUS_LIMIT = 100
MAX_STATUS_LIMIT = 1000


def _letters_only(value: str) -> str:
    """Return lowercase letters-only subset of *value*."""
    return "".join(ch for ch in value.lower() if ch.isalpha())


app = fastapi.FastAPI(title="pullDB API Service", version="0.0.1.dev0")


class JobRequest(pydantic.BaseModel):
    """Incoming job submission payload."""

    user: str = pydantic.Field(min_length=1)
    customer: str | None = None
    qatemplate: bool = False
    dbhost: str | None = None
    overwrite: bool = False


class JobResponse(pydantic.BaseModel):
    """Response payload for successful job submission."""

    job_id: str
    target: str
    staging_name: str
    status: str
    owner_username: str
    owner_user_code: str
    submitted_at: datetime | None = None


class JobSummary(pydantic.BaseModel):
    """Summary view of a job for status listing."""

    id: str
    target: str
    status: str
    user_code: str
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    staging_name: str | None = None
    current_operation: str | None = None
    dbhost: str | None = None
    source: str | None = None


class JobHistoryItem(pydantic.BaseModel):
    """Detailed history item for completed/failed/canceled jobs."""

    id: str
    target: str
    status: str
    user_code: str
    owner_username: str
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    staging_name: str | None = None
    dbhost: str | None = None
    source: str | None = None
    error_detail: str | None = None
    retry_count: int = 0


class JobEventResponse(pydantic.BaseModel):
    """Job event payload."""

    id: int
    job_id: str
    event_type: str
    detail: str | None
    logged_at: datetime


class APIState(t.NamedTuple):
    """Cached application state shared across requests."""

    config: Config
    pool: MySQLPool
    user_repo: UserRepository
    job_repo: JobRepository
    settings_repo: SettingsRepository
    host_repo: "HostRepository"


def _initialize_state() -> APIState:
    """Build API state by loading configuration and repositories."""
    try:
        config = Config.minimal_from_env()

        # REQUIRED: API service must have its own MySQL user
        api_mysql_user = os.getenv("PULLDB_API_MYSQL_USER")
        if not api_mysql_user:
            raise RuntimeError(
                "PULLDB_API_MYSQL_USER is required. "
                "Set it to the API service MySQL user (e.g., pulldb_api)."
            )
        config.mysql_user = api_mysql_user.strip()

        # Resolve coordination credentials if provided via secret
        # Only fetch from Secrets Manager if password is not already set
        coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
        if coordination_secret and not config.mysql_password:
            try:
                resolver = CredentialResolver(config.aws_profile)
                creds = resolver.resolve(coordination_secret)
                # Secret provides host and password; username comes from PULLDB_API_MYSQL_USER
                config.mysql_host = creds.host
                config.mysql_password = creds.password
                print(
                    f"INFO: Resolved coordination credentials from {coordination_secret} "
                    f"(host={creds.host}, user={config.mysql_user})"
                )
            except Exception as e:
                # Log warning but proceed with defaults (will likely fail connection)
                print(f"WARNING: Failed to resolve coordination secret: {e}")

    except Exception as exc:  # FAIL HARD: configuration path invalid
        raise RuntimeError(
            "Failed loading pullDB configuration from environment for API service: "
            f"{exc}. Configure PULLDB_MYSQL_* variables or consult docs/testing.md."
        ) from exc

    try:
        pool = build_default_pool(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
        )
    except Exception as exc:  # pragma: no cover - guarded by tests
        raise RuntimeError(
            "Failed connecting to coordination database for pullDB API service. "
            f"Attempted {config.mysql_host}/{config.mysql_database}: {exc}."
        ) from exc

    # Create credential resolver for host lookups
    credential_resolver = CredentialResolver(config.aws_profile)

    return APIState(
        config=config,
        pool=pool,
        user_repo=UserRepository(pool),
        job_repo=JobRepository(pool),
        settings_repo=SettingsRepository(pool),
        host_repo=HostRepository(pool, credential_resolver),
    )


def get_api_state() -> APIState:
    """FastAPI dependency returning shared API state."""
    state = t.cast(APIState | None, getattr(app.state, "api_state", None))
    if state is not None:
        return state
    try:
        state = _initialize_state()
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    app.state.api_state = state
    return state


def _select_dbhost(state: APIState, req: JobRequest) -> str:
    if req.dbhost:
        return req.dbhost
    if state.config.default_dbhost:
        return state.config.default_dbhost
    return state.config.mysql_host


def _construct_target(user: User, req: JobRequest) -> str:
    if req.qatemplate:
        return f"{user.user_code}qatemplate"

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
    return f"{user.user_code}{sanitized}"


def _options_snapshot(req: JobRequest) -> dict[str, str]:
    return {
        "customer_id": req.customer or "",
        "is_qatemplate": str(req.qatemplate).lower(),
        "overwrite": str(req.overwrite).lower(),
        "api_version": "v1",
    }


def _validate_job_request(req: JobRequest) -> None:
    if bool(req.customer) == bool(req.qatemplate):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Must specify exactly one of customer or qatemplate for restore request.",
        )


def _check_concurrency_limits(state: APIState, user: User) -> None:
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

    # Check per-user limit
    per_user_limit = state.settings_repo.get_max_active_jobs_per_user()
    if per_user_limit > 0:
        user_active = state.job_repo.count_active_jobs_for_user(user.user_id)
        if user_active >= per_user_limit:
            emit_event(
                "job_enqueue_rejected",
                f"User limit reached for {user.username}: {user_active}/{per_user_limit}",
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="rate_limited",
                ),
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"User limit reached: you have {user_active} active jobs "
                    f"(limit: {per_user_limit}). Wait for jobs to complete or cancel one."
                ),
            )


def _enqueue_job(state: APIState, req: JobRequest) -> JobResponse:
    user = state.user_repo.get_or_create_user(username=req.user)
    target = _construct_target(user, req)
    dbhost = _select_dbhost(state, req)

    # Phase 2: Concurrency controls - check limits before job creation
    _check_concurrency_limits(state, user)

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


def _active_jobs(state: APIState, limit: int) -> list[JobSummary]:
    jobs = state.job_repo.get_recent_jobs(limit)
    result: list[JobSummary] = []
    for job in jobs:
        source = None
        if job.options_json:
            if job.options_json.get("is_qatemplate") == "true":
                source = "qatemplate"
            else:
                source = job.options_json.get("customer_id")

        result.append(
            JobSummary(
                id=job.id,
                target=job.target,
                status=job.status.value,
                user_code=job.owner_user_code,
                submitted_at=job.submitted_at,
                started_at=job.started_at,
                staging_name=job.staging_name,
                current_operation=job.current_operation,
                dbhost=job.dbhost,
                source=source,
            )
        )
    return result


def _list_jobs(
    state: APIState,
    limit: int,
    active: bool,
    history: bool,
    filter_json: str | None,
) -> list[JobSummary]:
    statuses: list[str] = []
    if active:
        statuses.extend([JobStatus.QUEUED.value, JobStatus.RUNNING.value])
    if history:
        statuses.extend(
            [
                JobStatus.COMPLETE.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELED.value,
            ]
        )

    # Default to active if neither specified
    if not statuses:
        statuses.extend([JobStatus.QUEUED.value, JobStatus.RUNNING.value])

    jobs = state.job_repo.get_recent_jobs(limit, statuses=statuses)

    # Parse filter
    filters = {}
    if filter_json:
        try:
            filters = json.loads(filter_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON filter: {exc}",
            ) from exc

    result: list[JobSummary] = []
    for job in jobs:
        source = None
        if job.options_json:
            if job.options_json.get("is_qatemplate") == "true":
                source = "qatemplate"
            else:
                source = job.options_json.get("customer_id")

        summary = JobSummary(
            id=job.id,
            target=job.target,
            status=job.status.value,
            user_code=job.owner_user_code,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            staging_name=job.staging_name,
            current_operation=job.current_operation,
            dbhost=job.dbhost,
            source=source,
        )

        # Apply filters
        if filters:
            match = True
            summary_dict = summary.model_dump()
            for key, val in filters.items():
                # Simple string match
                if str(summary_dict.get(key, "")) != str(val):
                    match = False
                    break
            if not match:
                continue

        result.append(summary)
    return result


def _get_job_events(
    state: APIState, job_id: str, since_id: int | None
) -> list[JobEventResponse]:
    events = state.job_repo.get_job_events(job_id, since_id)
    return [
        JobEventResponse(
            id=event.id,
            job_id=event.job_id,
            event_type=event.event_type,
            detail=event.detail,
            logged_at=event.logged_at,
        )
        for event in events
    ]


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def status_endpoint(state: APIState = Depends(get_api_state)) -> dict[str, t.Any]:
    def _collect() -> dict[str, t.Any]:
        jobs = state.job_repo.get_active_jobs()
        active_count = len(jobs)
        return {
            "queue_depth": active_count,
            "active_restores": active_count,
            "service": "api",
        }

    return await run_in_threadpool(_collect)


@app.post("/api/jobs", status_code=status.HTTP_201_CREATED, response_model=JobResponse)
async def submit_job(
    req: JobRequest, state: APIState = Depends(get_api_state)
) -> JobResponse:
    _validate_job_request(req)
    return await run_in_threadpool(_enqueue_job, state, req)


@app.get(
    "/api/jobs",
    response_model=list[JobSummary],
)
async def list_jobs(
    limit: int = fastapi.Query(DEFAULT_STATUS_LIMIT, ge=1, le=MAX_STATUS_LIMIT),
    active: bool = False,
    history: bool = False,
    filter: str | None = None,
    state: APIState = Depends(get_api_state),
) -> list[JobSummary]:
    return await run_in_threadpool(_list_jobs, state, limit, active, history, filter)


@app.get(
    "/api/jobs/active",
    response_model=list[JobSummary],
)
async def list_active_jobs(
    limit: int = fastapi.Query(DEFAULT_STATUS_LIMIT, ge=1, le=MAX_STATUS_LIMIT),
    state: APIState = Depends(get_api_state),
) -> list[JobSummary]:
    return await run_in_threadpool(_active_jobs, state, limit)


DEFAULT_HISTORY_RETENTION_DAYS = 30
MAX_HISTORY_RETENTION_DAYS = 365


def _get_job_history(
    state: APIState,
    limit: int,
    retention_days: int | None,
    user_code: str | None,
    target: str | None,
    dbhost: str | None,
    job_status: str | None,
) -> list[JobHistoryItem]:
    """Get job history with optional filtering.

    Args:
        state: API state with repositories.
        limit: Maximum number of jobs to return.
        retention_days: Only return jobs completed within N days.
        user_code: Filter by owner user code.
        target: Filter by target database name.
        dbhost: Filter by database host.
        job_status: Filter by status (complete, failed, canceled).

    Returns:
        List of JobHistoryItem with computed duration.
    """
    jobs = state.job_repo.get_job_history(
        limit=limit,
        retention_days=retention_days,
        user_code=user_code,
        target=target,
        dbhost=dbhost,
        status=job_status,
    )

    result: list[JobHistoryItem] = []
    for job in jobs:
        # Compute duration if both started_at and completed_at exist
        duration_seconds: float | None = None
        if job.started_at and job.completed_at:
            delta = job.completed_at - job.started_at
            duration_seconds = delta.total_seconds()

        # Derive source from options_json
        source = None
        if job.options_json:
            if job.options_json.get("is_qatemplate") == "true":
                source = "qatemplate"
            else:
                source = job.options_json.get("customer_id")

        result.append(
            JobHistoryItem(
                id=job.id,
                target=job.target,
                status=job.status.value,
                user_code=job.owner_user_code,
                owner_username=job.owner_username,
                submitted_at=job.submitted_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                duration_seconds=duration_seconds,
                staging_name=job.staging_name,
                dbhost=job.dbhost,
                source=source,
                error_detail=job.error_detail,
                retry_count=job.retry_count,
            )
        )
    return result


@app.get(
    "/api/jobs/history",
    response_model=list[JobHistoryItem],
)
async def list_job_history(
    limit: int = fastapi.Query(DEFAULT_STATUS_LIMIT, ge=1, le=MAX_STATUS_LIMIT),
    days: int = fastapi.Query(
        DEFAULT_HISTORY_RETENTION_DAYS,
        ge=1,
        le=MAX_HISTORY_RETENTION_DAYS,
        description="Only return jobs completed within N days",
    ),
    user_code: str | None = fastapi.Query(None, description="Filter by user code"),
    target: str | None = fastapi.Query(None, description="Filter by target database"),
    dbhost: str | None = fastapi.Query(None, description="Filter by database host"),
    job_status: str | None = fastapi.Query(
        None,
        alias="status",
        description="Filter by status: complete, failed, or canceled",
    ),
    state: APIState = Depends(get_api_state),
) -> list[JobHistoryItem]:
    """Get job history with filtering and retention policy.

    Returns completed, failed, and canceled jobs ordered by completion time.
    Supports filtering by user, target, host, and status.
    Default retention is 30 days; maximum is 365 days.
    """
    # Validate status if provided
    if job_status and job_status not in ("complete", "failed", "canceled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{job_status}'. Must be one of: complete, failed, canceled",
        )

    return await run_in_threadpool(
        _get_job_history, state, limit, days, user_code, target, dbhost, job_status
    )


@app.get(
    "/api/jobs/{job_id}/events",
    response_model=list[JobEventResponse],
)
async def list_job_events(
    job_id: str,
    since_id: int | None = None,
    state: APIState = Depends(get_api_state),
) -> list[JobEventResponse]:
    return await run_in_threadpool(_get_job_events, state, job_id, since_id)


# --- Profile Response Models ---


class PhaseProfileResponse(pydantic.BaseModel):
    """Profile data for a single restore phase."""

    phase: str
    started_at: str
    completed_at: str | None = None
    duration_seconds: float | None = None
    bytes_processed: int | None = None
    bytes_per_second: float | None = None
    mbps: float | None = None
    metadata: dict[str, t.Any] = pydantic.Field(default_factory=dict)


class JobProfileResponse(pydantic.BaseModel):
    """Complete profile for a restore job."""

    job_id: str
    started_at: str
    completed_at: str | None = None
    total_duration_seconds: float | None = None
    total_bytes: int = 0
    phases: dict[str, PhaseProfileResponse] = pydantic.Field(default_factory=dict)
    phase_breakdown_percent: dict[str, float] = pydantic.Field(default_factory=dict)
    error: str | None = None


def _get_job_profile(state: APIState, job_id: str) -> JobProfileResponse:
    """Retrieve profile data for a completed job.

    Args:
        state: API state with repositories.
        job_id: UUID of job to get profile for.

    Returns:
        JobProfileResponse with phase timing data.

    Raises:
        HTTPException: If job not found or profile not available.
    """
    from pulldb.worker.profiling import parse_profile_from_event

    # Verify job exists
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Find restore_profile event (emitted by executor on job complete)
    events = state.job_repo.get_job_events(job_id)
    profile_event = None
    for event in events:
        if event.event_type == "restore_profile":
            profile_event = event
            break

    if not profile_event or not profile_event.detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile not available for job {job_id}",
        )

    # Parse profile from event
    profile = parse_profile_from_event(profile_event.detail)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse profile for job {job_id}",
        )

    # Convert to response model
    phases = {}
    for phase, phase_profile in profile.phases.items():
        phase_dict = phase_profile.to_dict()
        phases[phase.value] = PhaseProfileResponse(
            phase=phase_dict["phase"],
            started_at=phase_dict["started_at"],
            completed_at=phase_dict.get("completed_at"),
            duration_seconds=phase_dict.get("duration_seconds"),
            bytes_processed=phase_dict.get("bytes_processed"),
            bytes_per_second=phase_dict.get("bytes_per_second"),
            mbps=phase_dict.get("mbps"),
            metadata=phase_dict.get("metadata", {}),
        )

    return JobProfileResponse(
        job_id=profile.job_id,
        started_at=profile.started_at.isoformat(),
        completed_at=profile.completed_at.isoformat() if profile.completed_at else None,
        total_duration_seconds=profile.total_duration_seconds,
        total_bytes=profile.total_bytes,
        phases=phases,
        phase_breakdown_percent=profile.phase_breakdown,
        error=profile.error,
    )


@app.get(
    "/api/jobs/{job_id}/profile",
    response_model=JobProfileResponse,
)
async def get_job_profile(
    job_id: str,
    state: APIState = Depends(get_api_state),
) -> JobProfileResponse:
    """Get performance profile for a job.

    Returns timing breakdown by phase (discovery, download, extraction,
    myloader, post_sql, metadata, atomic_rename) with throughput metrics.

    Available after job completes (success or failure).
    """
    return await run_in_threadpool(_get_job_profile, state, job_id)


class CancelResponse(pydantic.BaseModel):
    """Response payload for job cancellation request."""

    job_id: str
    status: str
    message: str


def _cancel_job(state: APIState, job_id: str) -> CancelResponse:
    """Request cancellation of a job.

    Args:
        state: API state with repositories.
        job_id: UUID of job to cancel.

    Returns:
        CancelResponse with result.

    Raises:
        HTTPException: If job not found or not cancelable.
    """
    # Verify job exists
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Check if job is in cancelable state
    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} cannot be canceled (status: {job.status.value})",
        )

    # Request cancellation
    was_requested = state.job_repo.request_cancellation(job_id)
    if not was_requested:
        # Race condition: job may have completed or already been canceled
        refreshed = state.job_repo.get_job_by_id(job_id)
        if refreshed and refreshed.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Job {job_id} cannot be canceled (status: {refreshed.status.value})",
            )
        # Cancellation was already requested
        return CancelResponse(
            job_id=job_id,
            status="pending",
            message="Cancellation already requested",
        )

    # Log cancellation event
    state.job_repo.append_job_event(
        job_id=job_id,
        event_type="cancel_requested",
        detail="User requested job cancellation",
    )

    emit_event(
        "job_cancel_requested",
        f"job_id={job_id}",
        MetricLabels(phase="api", status="cancel_requested"),
    )

    # For queued jobs, we can cancel immediately
    if job.status == JobStatus.QUEUED:
        state.job_repo.mark_job_canceled(job_id, "Canceled before execution started")
        state.job_repo.append_job_event(
            job_id=job_id,
            event_type="canceled",
            detail="Job canceled before worker started processing",
        )
        emit_counter(
            "job_canceled_total",
            labels=MetricLabels(phase="api", status="queued"),
        )
        return CancelResponse(
            job_id=job_id,
            status="canceled",
            message="Job canceled successfully (was queued)",
        )

    # For running jobs, worker will check cancel flag and stop
    return CancelResponse(
        job_id=job_id,
        status="pending",
        message="Cancellation requested; worker will stop at next checkpoint",
    )


@app.post(
    "/api/jobs/{job_id}/cancel",
    response_model=CancelResponse,
)
async def cancel_job(
    job_id: str,
    state: APIState = Depends(get_api_state),
) -> CancelResponse:
    """Request cancellation of a job.

    For queued jobs, cancellation is immediate.
    For running jobs, the worker will stop at the next checkpoint.
    """
    return await run_in_threadpool(_cancel_job, state, job_id)


# --- Admin Endpoints ---


class PruneLogsRequest(pydantic.BaseModel):
    """Request to prune old job events."""

    days: int = pydantic.Field(
        default=90,
        ge=1,
        le=365,
        description="Retention period in days",
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="If true, return count without deleting",
    )


class PruneLogsResponse(pydantic.BaseModel):
    """Response from prune-logs operation."""

    deleted: int = pydantic.Field(
        default=0,
        description="Number of events deleted (0 if dry_run)",
    )
    would_delete: int = pydantic.Field(
        default=0,
        description="Number of events that would be deleted (dry_run only)",
    )
    retention_days: int = pydantic.Field(description="Retention period used")
    dry_run: bool = pydantic.Field(description="Whether this was a dry run")


def _prune_logs(state: APIState, request: PruneLogsRequest) -> PruneLogsResponse:
    """Prune old job events.

    Only events for terminal jobs (completed/failed/canceled) are deleted.
    Events for running or queued jobs are never pruned.
    """
    if request.dry_run:
        # For dry run, we need to count without deleting
        # This uses a similar query to the actual prune
        with state.job_repo.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM job_events je
                INNER JOIN jobs j ON je.job_id = j.id
                WHERE je.logged_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)
                  AND j.status IN ('completed', 'failed', 'canceled')
                """,
                (request.days,),
            )
            row = cursor.fetchone()
            count = row[0] if row else 0

        return PruneLogsResponse(
            deleted=0,
            would_delete=count,
            retention_days=request.days,
            dry_run=True,
        )

    # Actually prune
    deleted_count = state.job_repo.prune_job_events(retention_days=request.days)

    return PruneLogsResponse(
        deleted=deleted_count,
        would_delete=0,
        retention_days=request.days,
        dry_run=False,
    )


@app.post(
    "/api/admin/prune-logs",
    response_model=PruneLogsResponse,
)
async def prune_logs(
    request: PruneLogsRequest,
    state: APIState = Depends(get_api_state),
) -> PruneLogsResponse:
    """Prune job events older than retention period.

    Admin maintenance operation. Only deletes events for terminal jobs
    (completed/failed/canceled). Events for active jobs are never pruned.

    Use dry_run=true to preview what would be deleted.
    """
    return await run_in_threadpool(_prune_logs, state, request)


# --- Scheduled Staging Cleanup ---


class CleanupStagingRequest(pydantic.BaseModel):
    """Request to clean up orphaned staging databases."""

    days: int = pydantic.Field(
        default=7,
        ge=1,
        le=365,
        description="Age threshold in days",
    )
    dbhost: str | None = pydantic.Field(
        default=None,
        description="Specific host to clean. If omitted, all enabled hosts are scanned.",
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="If true, return count without deleting",
    )


class CleanupStagingResponse(pydantic.BaseModel):
    """Response from cleanup-staging operation."""

    hosts_scanned: int = pydantic.Field(description="Number of hosts scanned")
    total_candidates: int = pydantic.Field(
        description="Number of orphaned staging DBs found"
    )
    total_dropped: int = pydantic.Field(description="Number of DBs dropped")
    total_skipped: int = pydantic.Field(description="Number of DBs skipped")
    total_errors: int = pydantic.Field(description="Number of errors encountered")
    retention_days: int = pydantic.Field(description="Age threshold used")
    dry_run: bool = pydantic.Field(description="Whether this was a dry run")


def _cleanup_staging(
    state: APIState, request: CleanupStagingRequest
) -> CleanupStagingResponse:
    """Clean up orphaned staging databases."""
    from pulldb.worker.cleanup import cleanup_host_staging, run_scheduled_cleanup

    if request.dbhost:
        # Single host cleanup
        result = cleanup_host_staging(
            dbhost=request.dbhost,
            job_repo=state.job_repo,
            host_repo=state.host_repo,
            retention_days=request.days,
            dry_run=request.dry_run,
        )
        return CleanupStagingResponse(
            hosts_scanned=1,
            total_candidates=result.candidates_found,
            total_dropped=result.databases_dropped,
            total_skipped=result.databases_skipped,
            total_errors=len(result.errors),
            retention_days=request.days,
            dry_run=request.dry_run,
        )

    # All hosts cleanup
    summary = run_scheduled_cleanup(
        job_repo=state.job_repo,
        host_repo=state.host_repo,
        retention_days=request.days,
        dry_run=request.dry_run,
    )

    return CleanupStagingResponse(
        hosts_scanned=summary.hosts_scanned,
        total_candidates=summary.total_candidates,
        total_dropped=summary.total_dropped,
        total_skipped=summary.total_skipped,
        total_errors=summary.total_errors,
        retention_days=request.days,
        dry_run=request.dry_run,
    )


@app.post(
    "/api/admin/cleanup-staging",
    response_model=CleanupStagingResponse,
)
async def cleanup_staging(
    request: CleanupStagingRequest,
    state: APIState = Depends(get_api_state),
) -> CleanupStagingResponse:
    """Clean up orphaned staging databases.

    Admin maintenance operation. Scans database hosts for staging databases
    from jobs that completed/failed more than N days ago.

    Safety checks:
    - Only removes staging DBs for terminal jobs (completed/failed/canceled)
    - Skips if any active job exists for the target
    - Logs all deletions to job_events

    Use dry_run=true to preview what would be deleted.
    """
    return await run_in_threadpool(_cleanup_staging, state, request)


# --- Orphan Database Report (Admin) ---


class OrphanDatabaseItem(pydantic.BaseModel):
    """An orphan database detected on a host."""

    database_name: str = pydantic.Field(description="Name of the database")
    target_name: str = pydantic.Field(description="Parsed target name")
    job_id_prefix: str = pydantic.Field(description="Parsed job ID prefix")
    dbhost: str = pydantic.Field(description="Host where database exists")


class OrphanReportResponse(pydantic.BaseModel):
    """Response containing orphan databases for admin review."""

    dbhost: str = pydantic.Field(description="Host that was scanned")
    scanned_at: str = pydantic.Field(description="When scan was performed")
    orphans: list[OrphanDatabaseItem] = pydantic.Field(
        description="List of orphan databases"
    )
    count: int = pydantic.Field(description="Number of orphans found")


class AllOrphansResponse(pydantic.BaseModel):
    """Response containing orphan databases across all hosts."""

    hosts_scanned: int = pydantic.Field(description="Number of hosts scanned")
    total_orphans: int = pydantic.Field(description="Total orphans found")
    reports: list[OrphanReportResponse] = pydantic.Field(
        description="Per-host orphan reports"
    )


def _get_orphan_report(state: APIState, dbhost: str | None) -> AllOrphansResponse:
    """Get orphan database report for admin review."""
    from pulldb.worker.cleanup import detect_orphaned_databases

    reports: list[OrphanReportResponse] = []
    total_orphans = 0

    if dbhost:
        hosts = [type("H", (), {"hostname": dbhost})()]
    else:
        hosts = state.host_repo.get_enabled_hosts()

    for host in hosts:
        orphan_report = detect_orphaned_databases(
            dbhost=host.hostname,
            job_repo=state.job_repo,
            host_repo=state.host_repo,
        )

        orphan_items = [
            OrphanDatabaseItem(
                database_name=o.database_name,
                target_name=o.target_name,
                job_id_prefix=o.job_id_prefix,
                dbhost=o.dbhost,
            )
            for o in orphan_report.orphans
        ]

        reports.append(
            OrphanReportResponse(
                dbhost=host.hostname,
                scanned_at=orphan_report.scanned_at.isoformat(),
                orphans=orphan_items,
                count=len(orphan_items),
            )
        )
        total_orphans += len(orphan_items)

    return AllOrphansResponse(
        hosts_scanned=len(hosts),
        total_orphans=total_orphans,
        reports=reports,
    )


@app.get(
    "/api/admin/orphan-databases",
    response_model=AllOrphansResponse,
)
async def get_orphan_databases(
    dbhost: str | None = None,
    state: APIState = Depends(get_api_state),
) -> AllOrphansResponse:
    """Get report of orphan databases for admin review.

    Orphan databases match the staging pattern but have NO corresponding
    job record. These are NEVER auto-deleted and require manual admin
    review before deletion.

    Use the delete-orphans endpoint to remove selected orphans after review.
    """
    return await run_in_threadpool(_get_orphan_report, state, dbhost)


class DeleteOrphansRequest(pydantic.BaseModel):
    """Request to delete specific orphan databases."""

    dbhost: str = pydantic.Field(description="Host where databases exist")
    database_names: list[str] = pydantic.Field(
        description="List of database names to delete"
    )
    admin_user: str = pydantic.Field(description="Username of admin approving deletion")


class DeleteOrphansResponse(pydantic.BaseModel):
    """Response from delete-orphans operation."""

    requested: int = pydantic.Field(description="Number of deletions requested")
    succeeded: int = pydantic.Field(description="Number of successful deletions")
    failed: int = pydantic.Field(description="Number of failed deletions")
    results: dict[str, bool] = pydantic.Field(
        description="Per-database success/failure"
    )


def _delete_orphans(
    state: APIState, request: DeleteOrphansRequest
) -> DeleteOrphansResponse:
    """Delete admin-approved orphan databases."""
    from pulldb.worker.cleanup import admin_delete_orphan_databases

    results = admin_delete_orphan_databases(
        dbhost=request.dbhost,
        database_names=request.database_names,
        host_repo=state.host_repo,
        admin_user=request.admin_user,
    )

    succeeded = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)

    return DeleteOrphansResponse(
        requested=len(request.database_names),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@app.post(
    "/api/admin/delete-orphans",
    response_model=DeleteOrphansResponse,
)
async def delete_orphan_databases(
    request: DeleteOrphansRequest,
    state: APIState = Depends(get_api_state),
) -> DeleteOrphansResponse:
    """Delete admin-approved orphan databases.

    This endpoint is for databases that have been reviewed via the
    orphan-databases report and confirmed safe to delete.

    The admin_user field is logged for audit purposes.
    """
    return await run_in_threadpool(_delete_orphans, state, request)


def create_app() -> fastapi.FastAPI:
    return app


def main(argv: list[str] | None = None) -> int:
    host = os.getenv("PULLDB_API_HOST", "0.0.0.0")
    port_str = os.getenv("PULLDB_API_PORT", "8080")
    try:
        port = int(port_str)
    except ValueError:
        port = 8080
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
