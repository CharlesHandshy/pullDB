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
    JobRepository,
    MySQLPool,
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


def _initialize_state() -> APIState:
    """Build API state by loading configuration and repositories."""
    try:
        config = Config.minimal_from_env()
        
        # Resolve coordination credentials if provided via secret
        coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
        if coordination_secret and config.mysql_user == "root" and not config.mysql_password:
            try:
                resolver = CredentialResolver(config.aws_profile)
                creds = resolver.resolve(coordination_secret)
                config.mysql_host = creds.host
                config.mysql_user = creds.username
                config.mysql_password = creds.password
                # Note: Config doesn't currently support port override for coordination DB
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

    return APIState(
        config=config,
        pool=pool,
        user_repo=UserRepository(pool),
        job_repo=JobRepository(pool),
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


def _enqueue_job(state: APIState, req: JobRequest) -> JobResponse:
    user = state.user_repo.get_or_create_user(username=req.user)
    target = _construct_target(user, req)
    job_id = str(uuid.uuid4())
    staging_name = generate_staging_name(target, job_id)
    dbhost = _select_dbhost(state, req)

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
    return await run_in_threadpool(
        _list_jobs, state, limit, active, history, filter
    )


@app.get(
    "/api/jobs/active",
    response_model=list[JobSummary],
)
async def list_active_jobs(
    limit: int = fastapi.Query(DEFAULT_STATUS_LIMIT, ge=1, le=MAX_STATUS_LIMIT),
    state: APIState = Depends(get_api_state),
) -> list[JobSummary]:
    return await run_in_threadpool(_active_jobs, state, limit)


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


def create_app() -> fastapi.FastAPI:
    return app


def main(argv: list[str] | None = None) -> int:
    uvicorn.run(app, host="0.0.0.0", port=8080)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
