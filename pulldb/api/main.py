"""FastAPI-based API service for pullDB."""

from __future__ import annotations

import json
import os
from pathlib import Path
import typing as t
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import fastapi
import pydantic
import uvicorn
from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from pulldb.api.auth import AdminUser, AuthUser, ManagerUser, OptionalUser, validate_job_submission_user
from pulldb.api.logic import enqueue_job, validate_job_request
from pulldb.api.schemas import (
    JobEventResponse,
    JobHistoryItem,
    JobMatch,
    JobRequest,
    JobResolveResponse,
    JobResponse,
    JobSummary,
    UserLastJobResponse,
)
from pulldb.api.types import APIState
from pulldb.domain.config import Config
from pulldb.domain.errors import StagingError
from pulldb.domain.models import Job, JobStatus, User
from pulldb.domain.services.discovery import DiscoveryService
from pulldb.infra.factory import is_simulation_mode
from pulldb.infra.metrics import MetricLabels, emit_counter, emit_event
from pulldb.infra.mysql import (
    HostRepository,
    JobRepository,
    SettingsRepository,
    UserRepository,
    build_default_pool,
)
from pulldb.infra.secrets import CredentialResolver
from pulldb.worker.staging import generate_staging_name

if TYPE_CHECKING:
    from pulldb.auth import AuthRepository


DEFAULT_STATUS_LIMIT = 100
MAX_STATUS_LIMIT = 1000

# Web UI enabled by default, can be disabled with PULLDB_WEB_ENABLED=false
WEB_ENABLED = os.getenv("PULLDB_WEB_ENABLED", "true").lower() in ("true", "1", "yes")

app = fastapi.FastAPI(title="pullDB API Service", version="0.0.1.dev0")

# Mount unified web UI router (if enabled)
if WEB_ENABLED:
    try:
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from pulldb.web import (
            router as web_router,
            templates as web_templates,
            SessionExpiredError,
            PasswordResetRequiredError,
            create_session_expired_handler,
            create_password_reset_required_handler,
            create_http_exception_handler,
        )
        from pulldb.web.dependencies import WEB_DIR

        # Mount static files for CSS, JS, fonts
        static_dir = WEB_DIR / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        app.include_router(web_router)
        app.add_exception_handler(SessionExpiredError, create_session_expired_handler())
        app.add_exception_handler(PasswordResetRequiredError, create_password_reset_required_handler())
        app.add_exception_handler(StarletteHTTPException, create_http_exception_handler(web_templates))
    except ImportError:
        pass  # Web UI module not installed

# Mount simulation control API if in simulation mode
if is_simulation_mode():
    from pulldb.simulation.api import router as simulation_router
    app.include_router(simulation_router)


# Forward reference for type checking
if TYPE_CHECKING:
    from pulldb.auth import AuthRepository


def _initialize_state() -> APIState:
    """Build API state by loading configuration and repositories.

    In SIMULATION mode, uses in-memory repositories.
    In REAL mode, connects to MySQL and AWS.
    """
    if is_simulation_mode():
        return _initialize_simulation_state()

    return _initialize_real_state()


def _initialize_simulation_state() -> APIState:
    """Initialize API state with simulation components."""
    from pulldb.simulation import (
        SimulatedAuditRepository,
        SimulatedAuthRepository,
        SimulatedHostRepository,
        SimulatedJobRepository,
        SimulatedSettingsRepository,
        SimulatedUserRepository,
    )

    config = Config.minimal_from_env()

    return APIState(
        config=config,
        pool=None,  # No pool in simulation mode
        user_repo=SimulatedUserRepository(),
        job_repo=SimulatedJobRepository(),
        settings_repo=SimulatedSettingsRepository(),
        host_repo=SimulatedHostRepository(),
        auth_repo=SimulatedAuthRepository(),
        audit_repo=SimulatedAuditRepository(),
    )


def _initialize_real_state() -> APIState:
    """Build API state with real MySQL/AWS connections."""
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

    # Phase 4: Create auth repository for web UI (always enabled for both API and Web services)
    auth_repo = None
    audit_repo = None
    try:
        from pulldb.auth import AuthRepository
        from pulldb.infra.mysql import AuditRepository
        auth_repo = AuthRepository(pool)
        audit_repo = AuditRepository(pool)
    except ImportError:
        pass  # Auth modules not available

    return APIState(
        config=config,
        pool=pool,
        user_repo=UserRepository(pool),
        job_repo=JobRepository(pool),
        settings_repo=SettingsRepository(pool),
        host_repo=HostRepository(pool, credential_resolver),
        auth_repo=auth_repo,
        audit_repo=audit_repo,
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


class UserInfoResponse(pydantic.BaseModel):
    """Response for user lookup."""

    username: str
    user_code: str
    is_admin: bool = False


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/users/{username}", response_model=UserInfoResponse)
async def get_user_info(
    username: str,
    state: APIState = Depends(get_api_state),
) -> UserInfoResponse:
    """Get user info by username.

    Returns user_code for the given username. Used by CLI to display
    user identity when running under sudo.
    """
    user = await run_in_threadpool(state.user_repo.get_user_by_username, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found",
        )
    return UserInfoResponse(
        username=user.username,
        user_code=user.user_code,
        is_admin=user.is_admin,
    )


class ChangePasswordRequest(pydantic.BaseModel):
    """Request body for password change."""

    username: str
    current_password: str
    new_password: str


@app.post("/api/auth/change-password")
async def change_password(
    request: ChangePasswordRequest,
    state: APIState = Depends(get_api_state),
) -> dict[str, str]:
    """Change user password.

    Used by CLI's `pulldb setpass` command.

    - If user has no password set (new account), current_password is ignored
    - If user has password_reset_at set, any current_password is accepted
    - Otherwise, current_password must match existing password
    """
    from pulldb.auth.password import hash_password, verify_password

    if not state.auth_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not available",
        )

    # Verify user exists
    user = await run_in_threadpool(
        state.user_repo.get_user_by_username, request.username
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{request.username}' not found",
        )

    if user.disabled_at:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    # Check if password reset is required
    reset_required = await run_in_threadpool(
        state.auth_repo.is_password_reset_required, user.user_id
    )

    # Check if user has existing password
    has_password = await run_in_threadpool(
        state.auth_repo.has_password, user.user_id
    )

    # Validate current password (unless reset required or no password set)
    if has_password and not reset_required:
        existing_hash = await run_in_threadpool(
            state.auth_repo.get_password_hash, user.user_id
        )
        if existing_hash and not verify_password(request.current_password, existing_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )

    # Hash and set new password
    new_hash = hash_password(request.new_password)
    await run_in_threadpool(
        state.auth_repo.set_password_hash,
        user.user_id,
        new_hash,
    )

    # Clear password reset flag if it was set
    if reset_required:
        await run_in_threadpool(
            state.auth_repo.clear_password_reset, user.user_id
        )

    # Log audit event
    if state.audit_repo:
        await run_in_threadpool(
            state.audit_repo.log_action,
            actor_user_id=user.user_id,
            action="password_change",
            target_user_id=user.user_id,
            detail=f"User {user.username} changed their password",
        )

    return {"message": "Password changed successfully"}


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
    req: JobRequest,
    state: APIState = Depends(get_api_state),
    authenticated_user: OptionalUser = None,
) -> JobResponse:
    """Submit a new restore job.

    Authentication:
    - In trusted mode: Optional (backwards compatible with CLI)
    - In session mode: Required
    - If authenticated, validates user can only submit jobs for themselves
      (admins can submit for anyone)
    """
    validate_job_submission_user(authenticated_user, req.user)
    validate_job_request(req)
    return await run_in_threadpool(enqueue_job, state, req)


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


# --- User's Last Job ---


class UserLastJobResponse(pydantic.BaseModel):
    """Response for user's last job lookup."""

    job_id: str | None = None
    target: str | None = None
    status: str | None = None
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_detail: str | None = None
    found: bool = False


def _get_user_last_job(state: APIState, user_code: str) -> UserLastJobResponse:
    """Get the user's most recently submitted job."""
    job = state.job_repo.get_user_last_job(user_code)
    if not job:
        return UserLastJobResponse(found=False)
    return UserLastJobResponse(
        job_id=job.id,
        target=job.target,
        status=job.status.value,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_detail=job.error_detail,
        found=True,
    )


@app.get("/api/users/{user_code}/last-job")
async def get_user_last_job(
    user_code: str,
    state: APIState = Depends(get_api_state),
) -> UserLastJobResponse:
    """Get the most recently submitted job for a user.

    Returns the user's last job regardless of status (queued, running,
    complete, failed, or canceled).

    Args:
        user_code: The 6-character user code.

    Returns:
        UserLastJobResponse with job details or found=False if no jobs.
    """
    return await run_in_threadpool(_get_user_last_job, state, user_code)


# --- Job ID Resolution ---


class JobMatch(pydantic.BaseModel):
    """A job matching a prefix search."""

    id: str
    target: str
    status: str
    user_code: str
    submitted_at: datetime | None = None


class JobResolveResponse(pydantic.BaseModel):
    """Response for job ID prefix resolution."""

    resolved_id: str | None = pydantic.Field(
        None, description="Full job ID if exactly one match"
    )
    matches: list[JobMatch] = pydantic.Field(
        default_factory=list, description="List of matching jobs if multiple"
    )
    count: int = pydantic.Field(description="Number of matches found")


def _resolve_job_id(state: APIState, prefix: str) -> JobResolveResponse:
    """Resolve a job ID prefix to full job ID(s).

    Args:
        state: API state with repositories.
        prefix: Job ID prefix (minimum 8 characters).

    Returns:
        JobResolveResponse with resolved_id if exactly one match,
        or list of matches if multiple.

    Raises:
        HTTPException: 400 if prefix too short, 404 if no matches.
    """
    if len(prefix) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job ID prefix must be at least 8 characters",
        )

    # First try exact match
    exact_job = state.job_repo.get_job_by_id(prefix)
    if exact_job:
        return JobResolveResponse(
            resolved_id=exact_job.id,
            matches=[
                JobMatch(
                    id=exact_job.id,
                    target=exact_job.target,
                    status=exact_job.status.value,
                    user_code=exact_job.owner_user_code,
                    submitted_at=exact_job.submitted_at,
                )
            ],
            count=1,
        )

    # Try prefix match
    jobs = state.job_repo.find_jobs_by_prefix(prefix, limit=10)

    if not jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No jobs found matching prefix '{prefix}'",
        )

    matches = [
        JobMatch(
            id=job.id,
            target=job.target,
            status=job.status.value,
            user_code=job.owner_user_code,
            submitted_at=job.submitted_at,
        )
        for job in jobs
    ]

    if len(jobs) == 1:
        return JobResolveResponse(
            resolved_id=jobs[0].id,
            matches=matches,
            count=1,
        )

    # Multiple matches - return list for user disambiguation
    return JobResolveResponse(
        resolved_id=None,
        matches=matches,
        count=len(matches),
    )


@app.get(
    "/api/jobs/resolve/{prefix}",
    response_model=JobResolveResponse,
)
async def resolve_job_id(
    prefix: str,
    state: APIState = Depends(get_api_state),
) -> JobResolveResponse:
    """Resolve a job ID prefix to full job ID.

    Accepts short job ID prefixes (minimum 8 characters) and returns the
    full job ID if exactly one match is found. If multiple jobs match,
    returns a list for user disambiguation.

    Args:
        prefix: Job ID prefix (e.g., '8b4c4a3a' from '8b4c4a3a-85a1-4da2-...').

    Returns:
        - resolved_id: Full job ID if exactly one match
        - matches: List of matching jobs (always populated)
        - count: Number of matches

    Use Cases:
        - Single match: Use resolved_id directly
        - Multiple matches: Present matches list for user selection
        - No matches: Returns 404
    """
    return await run_in_threadpool(_resolve_job_id, state, prefix)


class JobSearchResult(pydantic.BaseModel):
    """Result from job search."""

    id: str
    target: str
    status: str
    user_code: str | None
    owner_username: str | None
    submitted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    dbhost: str | None


class JobSearchResponse(pydantic.BaseModel):
    """Response from job search endpoint."""

    query: str
    count: int
    exact_match: bool
    jobs: list[JobSearchResult]


def _search_jobs(
    state: APIState, query: str, limit: int, exact: bool
) -> JobSearchResponse:
    """Search jobs by query string."""
    jobs = state.job_repo.search_jobs(query, limit=limit, exact=exact)

    results = [
        JobSearchResult(
            id=job.id,
            target=job.target,
            status=job.status.value,
            user_code=job.owner_user_code,
            owner_username=job.owner_username,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            dbhost=job.dbhost,
        )
        for job in jobs
    ]

    return JobSearchResponse(
        query=query, count=len(results), exact_match=exact, jobs=results
    )


# --- Paginated Jobs Endpoint for LazyTable ---


class PaginatedJobsResponse(pydantic.BaseModel):
    """Paginated response for LazyTable widget."""

    rows: list[JobSummary]
    totalCount: int
    filteredCount: int
    page: int
    pageSize: int


def _wildcard_match(pattern: str, value: str) -> bool:
    """Match value against pattern with * wildcards.
    
    Examples:
        _wildcard_match("job-01*", "job-0100") -> True
        _wildcard_match("*0100", "job-0100") -> True
        _wildcard_match("12/*/2024", "12/08/2024") -> True
    """
    import fnmatch
    return fnmatch.fnmatch(value.lower(), pattern.lower())


def _get_paginated_jobs(
    state: APIState,
    page: int,
    page_size: int,
    view: str,
    sort_column: str | None,
    sort_direction: str | None,
    status_filter: str | None,
    host_filter: str | None,
    user_filter: str | None,
    target_filter: str | None,
    id_filter: str | None,
    submitted_at_filter: str | None,
    days: int,
    user: User | None = None,
) -> PaginatedJobsResponse:
    """Get paginated jobs for LazyTable.
    
    Multi-value filters (comma-separated) use OR logic within each column.
    Different columns use AND logic between them.
    """
    from pulldb.domain.permissions import can_cancel_job
    from pulldb.infra.filter_utils import parse_multi_value_filter

    # Determine statuses based on view
    if view == "history":
        statuses = [JobStatus.COMPLETE.value, JobStatus.FAILED.value, JobStatus.CANCELED.value]
    else:
        statuses = [JobStatus.QUEUED.value, JobStatus.RUNNING.value]

    # Apply status filter (supports multiple comma-separated statuses with OR logic)
    status_values = parse_multi_value_filter(status_filter)
    if status_values:
        # Filter to only valid statuses that match the filter AND are valid for view
        valid_statuses = [s for s in status_values if s in statuses]
        if valid_statuses:
            statuses = valid_statuses

    # Get jobs
    all_jobs = state.job_repo.get_recent_jobs(limit=1000, statuses=statuses)

    # Parse multi-value filters (comma-separated values use OR logic within column)
    host_values = parse_multi_value_filter(host_filter)
    user_values = parse_multi_value_filter(user_filter)
    target_values = parse_multi_value_filter(target_filter)

    # Apply filters in memory (for simulation mode compatibility)
    # Multi-value filters: match if ANY value matches (OR within column)
    # Different columns: AND logic between them
    filtered_jobs = list(all_jobs)
    if host_values:
        host_set = set(v.lower() for v in host_values)
        filtered_jobs = [j for j in filtered_jobs if j.dbhost and j.dbhost.lower() in host_set]
    if user_values:
        user_set = set(v.lower() for v in user_values)
        filtered_jobs = [j for j in filtered_jobs if j.owner_user_code and j.owner_user_code.lower() in user_set]
    if target_values:
        # Target uses substring matching - match if ANY target value is found
        filtered_jobs = [
            j for j in filtered_jobs 
            if j.target and any(tv in j.target.lower() for tv in target_values)
        ]
    
    # Text-based wildcard filter for Job ID
    if id_filter:
        filtered_jobs = [j for j in filtered_jobs if j.id and _wildcard_match(id_filter, j.id)]
    
    # Text-based wildcard filter for submitted_at (matches formatted date MM/DD/YYYY)
    if submitted_at_filter:
        def match_submitted(job):
            if not job.submitted_at:
                return False
            # Format date as MM/DD/YYYY for pattern matching
            formatted = job.submitted_at.strftime("%m/%d/%Y")
            return _wildcard_match(submitted_at_filter, formatted)
        filtered_jobs = [j for j in filtered_jobs if match_submitted(j)]

    # Sort if requested
    if sort_column and sort_direction:
        reverse = sort_direction == "desc"
        if sort_column == "submitted_at":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.submitted_at or datetime.min.replace(tzinfo=UTC), reverse=reverse)
        elif sort_column == "status":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.status.value, reverse=reverse)
        elif sort_column == "target":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.target or "", reverse=reverse)
        elif sort_column == "user_code":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.owner_user_code or "", reverse=reverse)
        elif sort_column == "dbhost":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.dbhost or "", reverse=reverse)

    total_count = len(all_jobs)
    filtered_count = len(filtered_jobs)

    # Paginate
    offset = page * page_size
    page_jobs = filtered_jobs[offset:offset + page_size]

    # Build cache of job owner manager_ids for permission checks
    owner_manager_cache: dict[str, str | None] = {}

    # Convert to JobSummary
    rows = []
    for job in page_jobs:
        source = None
        if job.options_json:
            if job.options_json.get("is_qatemplate") == "true":
                source = "qatemplate"
            else:
                source = job.options_json.get("customer_id")

        # Compute can_cancel for this user
        job_can_cancel = False
        if user:
            if job.owner_user_id not in owner_manager_cache:
                job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
                owner_manager_cache[job.owner_user_id] = job_owner.manager_id if job_owner else None
            job_owner_manager_id = owner_manager_cache[job.owner_user_id]
            job_can_cancel = (
                job.status in (JobStatus.QUEUED, JobStatus.RUNNING) and
                can_cancel_job(user, job.owner_user_id, job_owner_manager_id)
            )

        rows.append(JobSummary(
            id=job.id,
            target=job.target,
            status=job.status.value,
            user_code=job.owner_user_code,
            owner_user_code=job.owner_user_code,
            owner_user_id=job.owner_user_id,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            staging_name=job.staging_name,
            current_operation=job.current_operation,
            dbhost=job.dbhost,
            source=source,
            cancel_requested_at=getattr(job, 'cancel_requested_at', None),
            can_cancel=job_can_cancel,
        ))

    return PaginatedJobsResponse(
        rows=rows,
        totalCount=total_count,
        filteredCount=filtered_count,
        page=page,
        pageSize=page_size,
    )


@app.get("/api/jobs/paginated", response_model=PaginatedJobsResponse)
async def get_paginated_jobs(
    page: int = fastapi.Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = fastapi.Query(50, ge=10, le=200, description="Page size"),
    view: str = fastapi.Query("active", description="View: 'active' or 'history'"),
    sortColumn: str | None = fastapi.Query(None, description="Column to sort by"),
    sortDirection: str | None = fastapi.Query(None, description="Sort direction: 'asc' or 'desc'"),
    filter_status: str | None = fastapi.Query(None, alias="filter_status", description="Filter by status"),
    filter_dbhost: str | None = fastapi.Query(None, alias="filter_dbhost", description="Filter by host"),
    filter_user_code: str | None = fastapi.Query(None, alias="filter_user_code", description="Filter by user"),
    filter_owner_user_code: str | None = fastapi.Query(None, alias="filter_owner_user_code", description="Filter by user (alias for owner_user_code column)"),
    filter_target: str | None = fastapi.Query(None, alias="filter_target", description="Filter by target"),
    filter_id: str | None = fastapi.Query(None, alias="filter_id", description="Filter by job ID (wildcards: *)"),
    filter_submitted_at: str | None = fastapi.Query(None, alias="filter_submitted_at", description="Filter by date (MM/DD/YYYY, wildcards: *)"),
    days: int = fastapi.Query(30, ge=1, le=365, description="History retention days"),
    state: APIState = fastapi.Depends(get_api_state),
    x_trusted_user: str | None = fastapi.Header(None, alias="X-Trusted-User"),
    x_session_token: str | None = fastapi.Header(None, alias="X-Session-Token"),
) -> PaginatedJobsResponse:
    """Get paginated jobs for LazyTable widget.

    Supports server-side pagination, sorting, and filtering.
    Used by the LazyTable widget on the jobs page.

    If authenticated, includes can_cancel permission for each job.
    """
    from pulldb.api.auth import authenticate_user

    # Try to authenticate user (optional - for can_cancel computation)
    user = None
    try:
        user = await authenticate_user(state, x_trusted_user, x_session_token)
    except Exception:
        pass  # Continue without user for unauthenticated requests

    # Merge filter_owner_user_code with filter_user_code (column key is owner_user_code)
    effective_user_filter = filter_user_code or filter_owner_user_code
    
    return await run_in_threadpool(
        _get_paginated_jobs,
        state,
        page,
        pageSize,
        view,
        sortColumn,
        sortDirection,
        filter_status,
        filter_dbhost,
        effective_user_filter,
        filter_target,
        filter_id,
        filter_submitted_at,
        days,
        user,
    )


@app.get("/api/jobs/paginated/distinct")
async def get_distinct_values(
    column: str = fastapi.Query(..., description="Column to get distinct values for"),
    view: str = fastapi.Query("active", description="View: 'active' or 'history'"),
    filter_status: str | None = fastapi.Query(None, description="Filter by status (comma-separated)"),
    filter_dbhost: str | None = fastapi.Query(None, description="Filter by host (comma-separated)"),
    filter_user_code: str | None = fastapi.Query(None, description="Filter by user (comma-separated)"),
    filter_owner_user_code: str | None = fastapi.Query(None, description="Filter by user (alias)"),
    filter_target: str | None = fastapi.Query(None, description="Filter by target (comma-separated)"),
    filter_order: str | None = fastapi.Query(None, description="Comma-separated filter order for cascading"),
    state: APIState = fastapi.Depends(get_api_state),
) -> list[str]:
    """Get distinct values for a column (for cascading filter dropdowns).

    Supports order-aware cascading filters:
    - If column is NOT in filter_order: apply ALL filters (narrowed options)
    - If column IS in filter_order: only apply filters that precede it
    
    Filters support comma-separated multi-values (OR within column).
    """
    from pulldb.infra.filter_utils import parse_multi_value_filter
    
    # Parse filter order and determine which filters should apply
    order_list = [c.strip() for c in filter_order.split(",") if c.strip()] if filter_order else []
    column_in_order = column in order_list
    column_idx = order_list.index(column) if column_in_order else -1
    
    # If column is in order, only apply prior filters; otherwise apply ALL filters
    if column_in_order:
        applicable_cols = set(order_list[:column_idx]) if column_idx > 0 else set()
    else:
        applicable_cols = set(order_list)  # All active filters apply
    
    if view == "history":
        statuses = [JobStatus.COMPLETE.value, JobStatus.FAILED.value, JobStatus.CANCELED.value]
    else:
        statuses = [JobStatus.QUEUED.value, JobStatus.RUNNING.value]

    # Parse multi-value filters
    status_values = parse_multi_value_filter(filter_status)
    dbhost_values = parse_multi_value_filter(filter_dbhost)
    user_values = parse_multi_value_filter(filter_user_code or filter_owner_user_code)
    target_values = parse_multi_value_filter(filter_target)
    
    # Apply status filter if applicable
    if status_values and "status" in applicable_cols:
        # Filter to only statuses that match the filter AND are valid for view
        valid_statuses = [s for s in status_values if s in statuses]
        if valid_statuses:
            statuses = valid_statuses

    jobs = state.job_repo.get_recent_jobs(limit=1000, statuses=statuses)

    # Apply filters only for applicable columns
    filtered_jobs = list(jobs)
    
    if dbhost_values and "dbhost" in applicable_cols:
        dbhost_set = set(v.lower() for v in dbhost_values)
        filtered_jobs = [j for j in filtered_jobs if j.dbhost and j.dbhost.lower() in dbhost_set]
    
    if user_values and ("user_code" in applicable_cols or "owner_user_code" in applicable_cols):
        user_set = set(v.lower() for v in user_values)
        filtered_jobs = [j for j in filtered_jobs if j.owner_user_code and j.owner_user_code.lower() in user_set]
    
    if target_values and "target" in applicable_cols:
        filtered_jobs = [
            j for j in filtered_jobs 
            if j.target and any(tv in j.target.lower() for tv in target_values)
        ]

    values: set[str] = set()
    for job in filtered_jobs:
        if column == "status":
            values.add(job.status.value)
        elif column == "dbhost":
            if job.dbhost:
                values.add(job.dbhost)
        elif column in ("user_code", "owner_user_code"):
            if job.owner_user_code:
                values.add(job.owner_user_code)
        elif column == "target":
            if job.target:
                values.add(job.target)

    return sorted(values)


@app.get("/api/jobs/search")
async def search_jobs(
    q: str = fastapi.Query(..., min_length=4, description="Search query (min 4 chars)"),
    limit: int = fastapi.Query(50, ge=1, le=200, description="Max results"),
    exact: bool = fastapi.Query(
        False, description="Require exact match (default: prefix match for 4 chars)"
    ),
    state: APIState = fastapi.Depends(get_api_state),
) -> JobSearchResponse:
    """Search for jobs by ID, target, username, or user code.

    Searches across multiple fields to find matching jobs:
    - Job ID (full or prefix)
    - Target database name
    - Owner username
    - Owner user code

    Query behavior:
    - 4 characters: Uses prefix matching (e.g., "char" matches "charle")
    - 5+ characters: Uses exact matching by default
    - Use exact=true to force exact matching

    Args:
        q: Search query string (minimum 4 characters).
        limit: Maximum number of results to return (default 50, max 200).
        exact: If true, require exact field match instead of prefix.

    Returns:
        JobSearchResponse with matching jobs.
    """
    # 4 chars = prefix match, 5+ chars = exact match (unless exact=false)
    if len(q) == 4:
        use_exact = False  # 4 chars always uses prefix
    else:
        use_exact = True  # 5+ chars defaults to exact match

    return await run_in_threadpool(_search_jobs, state, q, limit, use_exact)


class LastJobResponse(pydantic.BaseModel):
    """Response for user's last submitted job."""

    job: JobSummary | None
    user_code: str


def _get_last_job_by_user(state: APIState, user_code: str) -> LastJobResponse:
    """Get the most recent job submitted by a user."""
    job = state.job_repo.get_last_job_by_user_code(user_code)
    if job is None:
        return LastJobResponse(job=None, user_code=user_code)

    summary = JobSummary(
        id=job.id,
        status=job.status,
        target=job.target,
        user_code=job.owner_user_code or user_code,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        staging_name=job.staging_name,
        dbhost=job.dbhost,
    )
    return LastJobResponse(job=summary, user_code=user_code)


@app.get("/api/jobs/my-last")
async def get_my_last_job(
    user_code: str = fastapi.Query(..., description="User code to look up"),
    state: APIState = fastapi.Depends(get_api_state),
) -> LastJobResponse:
    """Get the most recent job submitted by a user.

    Returns the user's last submitted job regardless of status.
    Useful for the CLI to show a quick status of the user's latest work.

    Args:
        user_code: The user code to look up jobs for.

    Returns:
        LastJobResponse with the job (or None if no jobs found).
    """
    return await run_in_threadpool(_get_last_job_by_user, state, user_code)


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


def _cancel_job(state: APIState, job_id: str, user: User) -> CancelResponse:
    """Request cancellation of a job.

    Args:
        state: API state with repositories.
        job_id: UUID of job to cancel.
        user: The user requesting cancellation.

    Returns:
        CancelResponse with result.

    Raises:
        HTTPException: If job not found, not cancelable, or unauthorized.
    """
    from pulldb.domain.permissions import can_cancel_job

    # Verify job exists
    job = state.job_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Authorization check: lookup job owner to get their manager_id
    job_owner = state.user_repo.get_user_by_id(job.owner_user_id)
    job_owner_manager_id = job_owner.manager_id if job_owner else None

    if not can_cancel_job(user, job.owner_user_id, job_owner_manager_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to cancel this job",
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
    user: AuthUser,
    state: APIState = Depends(get_api_state),
) -> CancelResponse:
    """Request cancellation of a job.

    For queued jobs, cancellation is immediate.
    For running jobs, the worker will stop at the next checkpoint.

    Requires authentication. Users can only cancel their own jobs.
    Managers can cancel jobs for users they manage. Admins can cancel any job.
    """
    return await run_in_threadpool(_cancel_job, state, job_id, user)


class BulkCancelRequest(pydantic.BaseModel):
    """Request to bulk cancel jobs matching filters."""

    view: str = pydantic.Field(
        default="active",
        description="View: 'active' or 'history'",
    )
    filter_status: str | None = pydantic.Field(
        default=None,
        description="Filter by status",
    )
    filter_dbhost: str | None = pydantic.Field(
        default=None,
        description="Filter by host",
    )
    filter_user_code: str | None = pydantic.Field(
        default=None,
        description="Filter by user code",
    )
    filter_target: str | None = pydantic.Field(
        default=None,
        description="Filter by target",
    )
    confirmation: str = pydantic.Field(
        ...,
        description="Must be 'CANCEL ALL' to confirm",
    )


class BulkCancelResponse(pydantic.BaseModel):
    """Response from bulk cancel operation."""

    canceled_count: int
    skipped_count: int
    message: str
    canceled_job_ids: list[str]


def _bulk_cancel_jobs(
    state: APIState,
    request: BulkCancelRequest,
    user: User,
) -> BulkCancelResponse:
    """Bulk cancel jobs matching filters (admin only).

    Only cancels jobs in QUEUED or RUNNING state.
    """
    # Verify confirmation phrase
    if request.confirmation != "CANCEL ALL":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation must be 'CANCEL ALL'",
        )

    # Build status filter - only cancelable jobs
    if request.view == "history":
        # History view shouldn't have cancelable jobs, return early
        return BulkCancelResponse(
            canceled_count=0,
            skipped_count=0,
            message="No cancelable jobs in history view",
            canceled_job_ids=[],
        )

    statuses = [JobStatus.QUEUED.value, JobStatus.RUNNING.value]
    if request.filter_status and request.filter_status in statuses:
        statuses = [request.filter_status]

    # Get jobs matching filters
    all_jobs = state.job_repo.get_recent_jobs(limit=1000, statuses=statuses)
    filtered_jobs = list(all_jobs)

    if request.filter_dbhost:
        filtered_jobs = [j for j in filtered_jobs if j.dbhost == request.filter_dbhost]
    if request.filter_user_code:
        filtered_jobs = [
            j for j in filtered_jobs if j.owner_user_code == request.filter_user_code
        ]
    if request.filter_target:
        filtered_jobs = [
            j
            for j in filtered_jobs
            if request.filter_target.lower() in (j.target or "").lower()
        ]

    # Cancel each job
    canceled_ids = []
    skipped = 0

    for job in filtered_jobs:
        if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            skipped += 1
            continue

        was_requested = state.job_repo.request_cancellation(job.id)
        if not was_requested:
            skipped += 1
            continue

        # Log cancellation event
        state.job_repo.append_job_event(
            job_id=job.id,
            event_type="cancel_requested",
            detail=f"Bulk cancel by admin {user.username}",
        )

        # For queued jobs, cancel immediately
        if job.status == JobStatus.QUEUED:
            state.job_repo.mark_job_canceled(
                job.id, f"Bulk canceled by admin {user.username}"
            )

        canceled_ids.append(job.id)

    return BulkCancelResponse(
        canceled_count=len(canceled_ids),
        skipped_count=skipped,
        message=f"Canceled {len(canceled_ids)} job(s), skipped {skipped}",
        canceled_job_ids=canceled_ids,
    )


@app.post(
    "/api/admin/jobs/bulk-cancel",
    response_model=BulkCancelResponse,
)
async def bulk_cancel_jobs(
    request: BulkCancelRequest,
    user: AdminUser,
    state: APIState = Depends(get_api_state),
) -> BulkCancelResponse:
    """Bulk cancel jobs matching filters (admin only).

    Requires admin role and typing 'CANCEL ALL' as confirmation.
    Only affects jobs in QUEUED or RUNNING state.
    """
    return await run_in_threadpool(_bulk_cancel_jobs, state, request, user)


# --- Manager Endpoints ---


class TeamMemberSummary(pydantic.BaseModel):
    """Summary of a team member for the manager view."""

    user_id: str
    username: str
    user_code: str
    active_jobs: int
    disabled_at: datetime | None
    password_reset_pending: bool


class PaginatedTeamResponse(pydantic.BaseModel):
    """Paginated response for manager team list."""

    rows: list[TeamMemberSummary]
    totalCount: int
    filteredCount: int
    page: int
    pageSize: int


def _get_paginated_team(
    state: APIState,
    user: User,
    page: int,
    page_size: int,
    sort_column: str | None,
    sort_direction: str | None,
    filter_username: str | None,
    filter_user_code: str | None,
    filter_status: str | None,
) -> PaginatedTeamResponse:
    """Get paginated team members for a manager (sync, runs in threadpool)."""
    # Get users managed by this user
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)

    # Count active jobs per user
    user_active_jobs: dict[str, int] = {}
    for mu in managed_users:
        jobs = state.job_repo.get_jobs_by_user(mu.user_id)
        user_active_jobs[mu.user_id] = len([
            j for j in jobs
            if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        ])

    # Check password reset status per user
    user_password_reset: dict[str, bool] = {}
    for mu in managed_users:
        if state.auth_repo and hasattr(state.auth_repo, "is_password_reset_required"):
            user_password_reset[mu.user_id] = state.auth_repo.is_password_reset_required(mu.user_id)
        else:
            user_password_reset[mu.user_id] = False

    # Apply filters
    filtered = list(managed_users)
    if filter_username:
        filter_lower = filter_username.lower()
        filtered = [u for u in filtered if filter_lower in (u.username or "").lower()]
    if filter_user_code:
        filter_lower = filter_user_code.lower()
        filtered = [u for u in filtered if filter_lower in (u.user_code or "").lower()]
    if filter_status:
        status_values = set(filter_status.split(","))

        def matches_status(u: User) -> bool:
            user_status = "disabled" if u.disabled_at else "active"
            return user_status in status_values

        filtered = [u for u in filtered if matches_status(u)]

    # Sort
    if sort_column and sort_direction:
        reverse = sort_direction == "desc"
        sort_keys: dict[str, t.Callable[[User], t.Any]] = {
            "username": lambda u: (u.username or "").lower(),
            "user_code": lambda u: (u.user_code or "").lower(),
            "active_jobs": lambda u: user_active_jobs.get(u.user_id, 0),
            "status": lambda u: 0 if u.disabled_at else 1,
        }
        if sort_column in sort_keys:
            filtered = sorted(filtered, key=sort_keys[sort_column], reverse=reverse)

    total = len(managed_users)
    filtered_count = len(filtered)

    # Paginate
    offset = page * page_size
    page_users = filtered[offset : offset + page_size]

    # Build response
    rows = [
        TeamMemberSummary(
            user_id=u.user_id,
            username=u.username,
            user_code=u.user_code,
            active_jobs=user_active_jobs.get(u.user_id, 0),
            disabled_at=u.disabled_at,
            password_reset_pending=user_password_reset.get(u.user_id, False),
        )
        for u in page_users
    ]

    return PaginatedTeamResponse(
        rows=rows,
        totalCount=total,
        filteredCount=filtered_count,
        page=page,
        pageSize=page_size,
    )


@app.get("/api/manager/team", response_model=PaginatedTeamResponse)
async def get_paginated_team(
    user: ManagerUser,
    page: int = fastapi.Query(0, ge=0, description="Page number (0-indexed)"),
    pageSize: int = fastapi.Query(50, ge=10, le=200, description="Page size"),
    sortColumn: str | None = fastapi.Query(None, description="Column to sort by"),
    sortDirection: str | None = fastapi.Query(None, description="Sort direction: 'asc' or 'desc'"),
    filter_username: str | None = fastapi.Query(None, description="Filter by username"),
    filter_user_code: str | None = fastapi.Query(None, description="Filter by user code"),
    filter_status: str | None = fastapi.Query(None, description="Filter by status (active/disabled)"),
    state: APIState = fastapi.Depends(get_api_state),
) -> PaginatedTeamResponse:
    """Get paginated team members for manager LazyTable widget.

    Returns users that are managed by the authenticated user.
    Requires manager or admin role.
    """
    return await run_in_threadpool(
        _get_paginated_team,
        state,
        user,
        page,
        pageSize,
        sortColumn,
        sortDirection,
        filter_username,
        filter_user_code,
        filter_status,
    )


@app.get("/api/manager/team/distinct")
async def get_team_distinct_values(
    user: ManagerUser,
    column: str = fastapi.Query(..., description="Column to get distinct values for"),
    filter_username: str | None = fastapi.Query(None, description="Filter by username (comma-separated)"),
    filter_user_code: str | None = fastapi.Query(None, description="Filter by user code (comma-separated)"),
    filter_status: str | None = fastapi.Query(None, description="Filter by status (comma-separated)"),
    filter_order: str | None = fastapi.Query(None, description="Comma-separated filter order for cascading"),
    state: APIState = fastapi.Depends(get_api_state),
) -> list[str]:
    """Get distinct values for a column in the team table.

    Supports cascading filters:
    - If column is NOT in filter_order: apply ALL filters (narrowed options)
    - If column IS in filter_order: only apply filters preceding it
    Requires manager or admin role.
    """
    from pulldb.infra.filter_utils import parse_multi_value_filter
    
    # Parse filter order and determine which filters should apply
    order_list = [c.strip() for c in filter_order.split(",") if c.strip()] if filter_order else []
    column_in_order = column in order_list
    column_idx = order_list.index(column) if column_in_order else -1
    
    # If column is in order, only apply prior filters; otherwise apply ALL filters
    if column_in_order:
        applicable_cols = set(order_list[:column_idx]) if column_idx > 0 else set()
    else:
        applicable_cols = set(order_list)

    # Get users managed by this user
    managed_users = []
    if hasattr(state.user_repo, "get_users_managed_by"):
        managed_users = state.user_repo.get_users_managed_by(user.user_id)
    
    # Parse multi-value filters
    username_values = parse_multi_value_filter(filter_username) if "username" in applicable_cols else []
    user_code_values = parse_multi_value_filter(filter_user_code) if "user_code" in applicable_cols else []
    status_values = parse_multi_value_filter(filter_status) if "status" in applicable_cols else []
    
    # Apply cascading filters
    filtered_users = list(managed_users)
    
    if username_values:
        username_set = set(username_values)
        filtered_users = [u for u in filtered_users if u.username and u.username.lower() in username_set]
    
    if user_code_values:
        user_code_set = set(user_code_values)
        filtered_users = [u for u in filtered_users if u.user_code and u.user_code.lower() in user_code_set]
    
    if status_values:
        filtered_users = [
            u for u in filtered_users
            if ("disabled" if u.disabled_at else "active").lower() in status_values
        ]

    values: set[str] = set()
    for u in filtered_users:
        if column == "username" and u.username:
            values.add(u.username)
        elif column == "user_code" and u.user_code:
            values.add(u.user_code)
        elif column == "status":
            values.add("disabled" if u.disabled_at else "active")

    return sorted(values)


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
                  AND j.status IN ('complete', 'failed', 'canceled')
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
    user: AdminUser,
    state: APIState = Depends(get_api_state),
) -> PruneLogsResponse:
    """Prune job events older than retention period.

    Admin maintenance operation. Only deletes events for terminal jobs
    (completed/failed/canceled). Events for active jobs are never pruned.

    Use dry_run=true to preview what would be deleted.
    Requires admin authentication.
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
    user: AdminUser,
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
    Requires admin authentication.
    """
    return await run_in_threadpool(_cleanup_staging, state, request)


# --- Orphan Database Report (Admin) ---


class OrphanDatabaseItem(pydantic.BaseModel):
    """An orphan database detected on a host."""

    database_name: str = pydantic.Field(description="Name of the database")
    target_name: str = pydantic.Field(description="Parsed target name")
    job_id_prefix: str = pydantic.Field(description="Parsed job ID prefix")
    dbhost: str = pydantic.Field(description="Host where database exists")
    size_mb: float | None = pydantic.Field(default=None, description="Database size in MB")


class OrphanReportResponse(pydantic.BaseModel):
    """Response containing orphan databases for admin review."""

    dbhost: str = pydantic.Field(description="Host that was scanned")
    scanned_at: str = pydantic.Field(description="When scan was performed")
    orphans: list[OrphanDatabaseItem] = pydantic.Field(
        description="List of orphan databases"
    )
    count: int = pydantic.Field(description="Number of orphans found")


class HostScanError(pydantic.BaseModel):
    """Error that occurred while scanning a host."""

    hostname: str = pydantic.Field(description="Host that failed to scan")
    message: str = pydantic.Field(description="Error message")


class AllOrphansResponse(pydantic.BaseModel):
    """Response containing orphan databases across all hosts."""

    hosts_scanned: int = pydantic.Field(description="Number of hosts scanned")
    total_orphans: int = pydantic.Field(description="Total orphans found")
    reports: list[OrphanReportResponse] = pydantic.Field(
        description="Per-host orphan reports"
    )
    errors: list[HostScanError] = pydantic.Field(
        default_factory=list,
        description="Hosts that failed to scan with error messages"
    )


def _get_orphan_report(state: APIState, dbhost: str | None) -> AllOrphansResponse:
    """Get orphan database report for admin review."""
    from pulldb.worker.cleanup import detect_orphaned_databases, OrphanReport

    reports: list[OrphanReportResponse] = []
    errors: list[HostScanError] = []
    total_orphans = 0

    if dbhost:
        hosts = [type("H", (), {"hostname": dbhost})()]
    else:
        hosts = state.host_repo.get_enabled_hosts()

    for host in hosts:
        result = detect_orphaned_databases(
            dbhost=host.hostname,
            job_repo=state.job_repo,
            host_repo=state.host_repo,
        )

        # Handle error string return (connection failure)
        if isinstance(result, str):
            errors.append(HostScanError(
                hostname=host.hostname,
                message=result,
            ))
            continue

        # Handle successful OrphanReport
        orphan_report: OrphanReport = result
        orphan_items = [
            OrphanDatabaseItem(
                database_name=o.database_name,
                target_name=o.target_name,
                job_id_prefix=o.job_id_prefix,
                dbhost=o.dbhost,
                size_mb=o.size_mb,
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
        errors=errors,
    )


@app.get(
    "/api/admin/orphan-databases",
    response_model=AllOrphansResponse,
)
async def get_orphan_databases(
    user: AdminUser,
    dbhost: str | None = None,
    state: APIState = Depends(get_api_state),
) -> AllOrphansResponse:
    """Get report of orphan databases for admin review.

    Orphan databases match the staging pattern but have NO corresponding
    job record. These are NEVER auto-deleted and require manual admin
    review before deletion.

    Use the delete-orphans endpoint to remove selected orphans after review.
    Requires admin authentication.
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
    user: AdminUser,
    state: APIState = Depends(get_api_state),
) -> DeleteOrphansResponse:
    """Delete admin-approved orphan databases.

    This endpoint is for databases that have been reviewed via the
    orphan-databases report and confirmed safe to delete.

    The admin_user field is logged for audit purposes.
    Requires admin authentication.
    """
    return await run_in_threadpool(_delete_orphans, state, request)


# ---------------------------------------------------------------------------
# Paginated Orphan Database API (LazyTable compatible)
# ---------------------------------------------------------------------------


class PaginatedOrphansResponse(pydantic.BaseModel):
    """Paginated response for orphan databases LazyTable."""

    rows: list[OrphanDatabaseItem] = pydantic.Field(description="Orphan database items")
    totalCount: int = pydantic.Field(description="Total count before filtering")
    filteredCount: int = pydantic.Field(description="Count after filtering")
    page: int = pydantic.Field(description="Current page (0-indexed)")
    pageSize: int = pydantic.Field(description="Items per page")
    errors: list[HostScanError] = pydantic.Field(
        default_factory=list,
        description="Hosts that failed to scan"
    )


def _get_paginated_orphans(
    state: APIState,
    page: int,
    page_size: int,
    sort_column: str,
    sort_direction: str,
    filter_host: str | None,
    filter_target: str | None,
) -> PaginatedOrphansResponse:
    """Get paginated orphan databases for LazyTable."""
    from pulldb.worker.cleanup import detect_orphaned_databases, OrphanReport

    all_orphans: list[OrphanDatabaseItem] = []
    errors: list[HostScanError] = []

    # Get all enabled hosts (or filter to specific host)
    if filter_host:
        hosts = [type("H", (), {"hostname": filter_host})()]
    else:
        hosts = state.host_repo.get_enabled_hosts()

    for host in hosts:
        result = detect_orphaned_databases(
            dbhost=host.hostname,
            job_repo=state.job_repo,
            host_repo=state.host_repo,
        )

        if isinstance(result, str):
            errors.append(HostScanError(hostname=host.hostname, message=result))
            continue

        orphan_report: OrphanReport = result
        for o in orphan_report.orphans:
            all_orphans.append(OrphanDatabaseItem(
                database_name=o.database_name,
                target_name=o.target_name,
                job_id_prefix=o.job_id_prefix,
                dbhost=o.dbhost,
                size_mb=o.size_mb,
            ))

    total_count = len(all_orphans)

    # Apply target filter if provided
    if filter_target:
        filter_target_lower = filter_target.lower()
        all_orphans = [
            o for o in all_orphans
            if filter_target_lower in o.target_name.lower()
            or filter_target_lower in o.database_name.lower()
        ]

    filtered_count = len(all_orphans)

    # Sort
    reverse = sort_direction.lower() == "desc"
    if sort_column == "size_mb":
        all_orphans.sort(key=lambda o: o.size_mb or 0, reverse=reverse)
    elif sort_column == "database_name":
        all_orphans.sort(key=lambda o: o.database_name, reverse=reverse)
    elif sort_column == "target_name":
        all_orphans.sort(key=lambda o: o.target_name, reverse=reverse)
    elif sort_column == "dbhost":
        all_orphans.sort(key=lambda o: o.dbhost, reverse=reverse)

    # Paginate
    start = page * page_size
    end = start + page_size
    page_rows = all_orphans[start:end]

    return PaginatedOrphansResponse(
        rows=page_rows,
        totalCount=total_count,
        filteredCount=filtered_count,
        page=page,
        pageSize=page_size,
        errors=errors,
    )


@app.get(
    "/api/admin/orphan-databases/paginated",
    response_model=PaginatedOrphansResponse,
)
async def get_paginated_orphan_databases(
    user: AdminUser,
    page: int = 0,
    pageSize: int = 50,
    sortColumn: str = "database_name",
    sortDirection: str = "asc",
    filter_host: str | None = None,
    filter_target: str | None = None,
    state: APIState = Depends(get_api_state),
) -> PaginatedOrphansResponse:
    """Get paginated orphan databases for LazyTable display.

    Supports sorting by database_name, target_name, dbhost, size_mb.
    Supports filtering by host and target name.
    """
    return await run_in_threadpool(
        _get_paginated_orphans,
        state,
        page,
        pageSize,
        sortColumn,
        sortDirection,
        filter_host,
        filter_target,
    )


class OrphanMetadataResponse(pydantic.BaseModel):
    """Metadata from pullDB table inside an orphan database."""

    found: bool = pydantic.Field(description="Whether metadata was found")
    job_id: str | None = pydantic.Field(default=None, description="Original restore job ID")
    restored_by: str | None = pydantic.Field(default=None, description="User who restored")
    restored_at: str | None = pydantic.Field(default=None, description="When restored (ISO format)")
    target_database: str | None = pydantic.Field(default=None, description="Target database name")
    backup_filename: str | None = pydantic.Field(default=None, description="S3 backup path used")
    restore_duration_seconds: float | None = pydantic.Field(default=None, description="Restore duration")


def _get_orphan_metadata(
    state: APIState,
    dbhost: str,
    db_name: str,
) -> OrphanMetadataResponse:
    """Get metadata for a specific orphan database."""
    from pulldb.worker.cleanup import fetch_orphan_metadata

    meta = fetch_orphan_metadata(
        dbhost=dbhost,
        db_name=db_name,
        host_repo=state.host_repo,
    )

    if meta is None:
        return OrphanMetadataResponse(found=False)

    return OrphanMetadataResponse(
        found=True,
        job_id=meta.job_id,
        restored_by=meta.restored_by,
        restored_at=meta.restored_at.isoformat() if meta.restored_at else None,
        target_database=meta.target_database,
        backup_filename=meta.backup_filename,
        restore_duration_seconds=meta.restore_duration_seconds,
    )


@app.get(
    "/api/admin/orphan-databases/{dbhost}/{db_name}/meta",
    response_model=OrphanMetadataResponse,
)
async def get_orphan_database_metadata(
    dbhost: str,
    db_name: str,
    user: AdminUser,
    state: APIState = Depends(get_api_state),
) -> OrphanMetadataResponse:
    """Get metadata from pullDB table inside an orphan database.

    This fetches restore information (who, when, what backup) from the
    pullDB table that is created during restore. If the table doesn't
    exist (old restore or crash before completion), returns found=false.
    """
    return await run_in_threadpool(_get_orphan_metadata, state, dbhost, db_name)


@app.delete(
    "/api/admin/orphan-databases/{dbhost}/{db_name}",
    response_model=DeleteOrphansResponse,
)
async def delete_single_orphan_database(
    dbhost: str,
    db_name: str,
    user: AdminUser,
    state: APIState = Depends(get_api_state),
) -> DeleteOrphansResponse:
    """Delete a single orphan database.

    REST-style endpoint for deleting individual orphans via trash icon.
    """
    request = DeleteOrphansRequest(
        dbhost=dbhost,
        database_names=[db_name],
        admin_user=user.username,
    )
    return await run_in_threadpool(_delete_orphans, state, request)


def create_app() -> fastapi.FastAPI:
    return app


# ---------------------------------------------------------------------------
# Searchable Dropdown API - Standard type-ahead search endpoints
# ---------------------------------------------------------------------------


class DropdownOption(pydantic.BaseModel):
    """Single option for searchable dropdown."""

    value: str
    label: str
    sublabel: str | None = None


class DropdownSearchResponse(pydantic.BaseModel):
    """Response format for searchable dropdown endpoints."""

    results: list[DropdownOption]
    total: int


def _search_customers_dropdown(
    state: APIState, query: str, limit: int
) -> DropdownSearchResponse:
    """Search for customers for dropdown selection.

    In REAL mode, this queries S3 for unique customer directories.
    In SIMULATION mode, returns mock data.
    """
    service = DiscoveryService()
    matches = service.search_customers(query, limit)

    results = [DropdownOption(value=c, label=c, sublabel=None) for c in matches]

    return DropdownSearchResponse(results=results, total=len(matches))


@app.get("/api/dropdown/customers", response_model=DropdownSearchResponse)
async def search_customers_dropdown(
    q: str = fastapi.Query(
        ..., min_length=5, description="Search query (min 5 chars)"
    ),
    limit: int = fastapi.Query(10, ge=1, le=50, description="Max results"),
    state: APIState = fastapi.Depends(get_api_state),
) -> DropdownSearchResponse:
    """Search for customers for dropdown selection.

    Returns customer names matching the query for use in searchable dropdowns.
    Requires minimum 5 characters to avoid too many results.

    Response format:
        {
            "results": [
                {"value": "acmecorp", "label": "acmecorp", "sublabel": "12 backups"}
            ],
            "total": 1
        }
    """
    return await run_in_threadpool(_search_customers_dropdown, state, q, limit)


def _search_users_dropdown(
    state: APIState, query: str, limit: int
) -> DropdownSearchResponse:
    """Search for users for dropdown selection."""
    # Search users by username, user_code, or name
    users = state.user_repo.search_users(query, limit=limit)

    results = [
        DropdownOption(
            value=user.username,
            label=user.username,
            sublabel=f"{user.role.value} · {user.user_code}",
        )
        for user in users
    ]

    return DropdownSearchResponse(results=results, total=len(results))


@app.get("/api/dropdown/users", response_model=DropdownSearchResponse)
async def search_users_dropdown(
    q: str = fastapi.Query(
        ..., min_length=3, description="Search query (min 3 chars)"
    ),
    limit: int = fastapi.Query(15, ge=1, le=50, description="Max results"),
    state: APIState = fastapi.Depends(get_api_state),
) -> DropdownSearchResponse:
    """Search for users for dropdown selection.

    Returns usernames matching the query for use in searchable dropdowns.

    Response format:
        {
            "results": [
                {"value": "jdoe", "label": "jdoe", "sublabel": "admin · jdoejd"}
            ],
            "total": 1
        }
    """
    return await run_in_threadpool(_search_users_dropdown, state, q, limit)


def _search_hosts_dropdown(
    state: APIState, query: str, limit: int
) -> DropdownSearchResponse:
    """Search for database hosts for dropdown selection."""
    hosts = state.host_repo.search_hosts(query, limit=limit)

    results = [
        DropdownOption(
            value=host.hostname,
            label=host.hostname,
            sublabel="active" if host.is_active else "inactive",
        )
        for host in hosts
    ]

    return DropdownSearchResponse(results=results, total=len(results))


@app.get("/api/dropdown/hosts", response_model=DropdownSearchResponse)
async def search_hosts_dropdown(
    q: str = fastapi.Query(
        ..., min_length=3, description="Search query (min 3 chars)"
    ),
    limit: int = fastapi.Query(10, ge=1, le=50, description="Max results"),
    state: APIState = fastapi.Depends(get_api_state),
) -> DropdownSearchResponse:
    """Search for database hosts for dropdown selection.

    Returns hostnames matching the query for use in searchable dropdowns.

    Response format:
        {
            "results": [
                {"value": "db-prod-01", "label": "db-prod-01", "sublabel": "active"}
            ],
            "total": 1
        }
    """
    return await run_in_threadpool(_search_hosts_dropdown, state, q, limit)


# ---------------------------------------------------------------------------
# Backup Search API - S3 backup discovery for CLI
# ---------------------------------------------------------------------------


class BackupInfo(pydantic.BaseModel):
    """Information about a discovered backup."""

    customer: str
    timestamp: datetime
    date: str  # YYYYMMDD format for display
    size_mb: float
    environment: str
    key: str
    bucket: str


class BackupSearchResponse(pydantic.BaseModel):
    """Response from backup search endpoint."""

    backups: list[BackupInfo]
    total: int
    query: str
    environment: str


def _search_backups(
    customer: str,
    environment: str,
    date_from: str | None,
    limit: int,
) -> BackupSearchResponse:
    """Search S3 for backups matching customer pattern.

    This runs on the API server which has AWS credentials.
    """
    service = DiscoveryService()
    domain_backups = service.search_backups(customer, environment, date_from, limit)

    # Convert domain dataclasses to Pydantic models
    backups = [
        BackupInfo(
            customer=b.customer,
            timestamp=b.timestamp,
            date=b.date,
            size_mb=b.size_mb,
            environment=b.environment,
            key=b.key,
            bucket=b.bucket,
        )
        for b in domain_backups
    ]

    return BackupSearchResponse(
        backups=backups,
        total=len(backups),
        query=customer,
        environment=environment,
    )





@app.get("/api/backups/search", response_model=BackupSearchResponse)
async def search_backups(
    customer: str = fastapi.Query(..., min_length=1, description="Customer name or pattern (supports * and ? wildcards)"),
    environment: str = fastapi.Query("both", description="S3 environment: staging, prod, or both"),
    date_from: str | None = fastapi.Query(None, description="Filter backups from date (YYYYMMDD)"),
    limit: int = fastapi.Query(5, ge=1, le=100, description="Max results"),
) -> BackupSearchResponse:
    """Search for available backups in S3.
    
    This endpoint searches the configured S3 backup locations for
    backups matching the customer pattern.
    
    Args:
        customer: Customer name or wildcard pattern (e.g., "actionpest" or "action*")
        environment: S3 environment to search (staging, prod, or both)
        date_from: Optional start date filter in YYYYMMDD format
        limit: Maximum number of results (default 5, max 100)
    
    Returns:
        BackupSearchResponse with matching backups sorted by date (newest first)
    """
    if environment not in ("staging", "prod", "both"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"environment must be staging, prod, or both. Got: {environment}",
        )
    
    return await run_in_threadpool(_search_backups, customer, environment, date_from, limit)


def main(argv: list[str] | None = None) -> int:
    """Run the API server (REST API + optional Web UI on same port)."""
    host = os.getenv("PULLDB_API_HOST", "0.0.0.0")
    port_str = os.getenv("PULLDB_API_PORT", "8080")
    try:
        port = int(port_str)
    except ValueError:
        port = 8080
    uvicorn.run(app, host=host, port=port)
    return 0


def main_web(argv: list[str] | None = None) -> int:
    """Run the Web UI server (Web UI only, no REST API, on separate port).
    
    This entry point creates a minimal FastAPI app with only the web routes,
    allowing the Web UI to run on a different port than the API.
    """
    # Create a separate app for web-only mode
    web_app = fastapi.FastAPI(title="pullDB Web UI", version="0.0.1.dev0")
    
    try:
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from pulldb.web import (
            router as web_router,
            templates as web_templates,
            SessionExpiredError,
            PasswordResetRequiredError,
            create_session_expired_handler,
            create_password_reset_required_handler,
            create_http_exception_handler,
        )
        from pulldb.web.dependencies import WEB_DIR

        # Mount static files for CSS, JS, fonts
        static_dir = WEB_DIR / "static"
        if static_dir.exists():
            web_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        web_app.include_router(web_router)
        web_app.add_exception_handler(SessionExpiredError, create_session_expired_handler())
        web_app.add_exception_handler(PasswordResetRequiredError, create_password_reset_required_handler())
        web_app.add_exception_handler(StarletteHTTPException, create_http_exception_handler(web_templates))
    except ImportError as e:
        print(f"Error: Web UI module not available: {e}")
        return 1
    
    # Copy state initialization from main app if available
    @web_app.on_event("startup")
    async def startup_event() -> None:
        web_app.state.api = _initialize_state()
    
    host = os.getenv("PULLDB_WEB_HOST", "0.0.0.0")
    port_str = os.getenv("PULLDB_WEB_PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000
    uvicorn.run(web_app, host=host, port=port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
