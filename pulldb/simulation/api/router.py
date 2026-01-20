"""Simulation Control API Router.

Provides REST endpoints to control the simulation engine:
- Reset simulation state
- Switch scenarios
- View event history
- Inject chaos at runtime

HCA Layer: pages
"""

from __future__ import annotations

from typing import Any
from dataclasses import replace
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from pulldb.auth.password import hash_password
from pulldb.infra.logging import get_logger

logger = get_logger("pulldb.simulation.api.router")
from pulldb.simulation import SimulatedAuthRepository, SimulatedUserRepository
from pulldb.simulation.core.bus import EventType, get_event_bus
from pulldb.simulation.core.scenarios import (
    ScenarioType,
    get_scenario_manager,
)
from pulldb.simulation.core.state import SimulationState, get_simulation_state, reset_simulation


router = APIRouter(prefix="/simulation", tags=["simulation"])


# ============================================================================
# Request/Response Models
# ============================================================================


class SimulationStatusResponse(BaseModel):
    """Response for simulation status."""

    mode: str = "SIMULATION"
    current_scenario: str | None = None
    job_count: int = 0
    user_count: int = 0
    host_count: int = 0
    event_count: int = 0
    s3_bucket_count: int = 0


class ResetResponse(BaseModel):
    """Response after resetting simulation."""

    success: bool = True
    message: str = "Simulation state reset successfully"


class ScenarioInfo(BaseModel):
    """Information about a single scenario."""

    type: str
    name: str
    description: str
    has_chaos: bool = False
    initial_jobs: int = 0


class ScenarioListResponse(BaseModel):
    """Response listing all available scenarios."""

    scenarios: list[ScenarioInfo]
    current: str | None = None


class ActivateScenarioRequest(BaseModel):
    """Request to activate a scenario."""

    scenario_type: str = Field(..., description="Scenario type to activate")


class ActivateScenarioResponse(BaseModel):
    """Response after activating a scenario."""

    success: bool = True
    scenario_type: str
    scenario_name: str
    s3_fixtures_loaded: int = 0


class EventInfo(BaseModel):
    """Information about a single event."""

    event_type: str
    timestamp: datetime
    source: str
    job_id: str | None = None
    data: dict[str, Any]


class EventHistoryResponse(BaseModel):
    """Response with event history."""

    total: int
    events: list[EventInfo]


class InjectChaosRequest(BaseModel):
    """Request to inject chaos."""

    operation: str = Field(..., description="Operation to inject chaos into")
    failure_rate: float = Field(
        0.5, ge=0.0, le=1.0, description="Probability of failure (0.0-1.0)"
    )
    error_message: str = Field("Chaos-injected error", description="Error message")


class InjectChaosResponse(BaseModel):
    """Response after injecting chaos."""

    success: bool = True
    operation: str
    failure_rate: float
    message: str


class StateSnapshotResponse(BaseModel):
    """Snapshot of current simulation state."""

    jobs: list[dict[str, Any]]
    users: list[dict[str, Any]]
    hosts: list[dict[str, Any]]
    settings: dict[str, str]
    s3_buckets: dict[str, list[str]]


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/status", response_model=SimulationStatusResponse)
async def get_status() -> SimulationStatusResponse:
    """Get current simulation status.

    Returns overview of simulation state including counts of jobs, users,
    hosts, events, and the currently active scenario.
    """
    state = get_simulation_state()
    bus = get_event_bus()
    manager = get_scenario_manager()

    current = manager.get_current_scenario()

    with state.lock:
        return SimulationStatusResponse(
            mode="SIMULATION",
            current_scenario=current.scenario_type.value if current else None,
            job_count=len(state.jobs),
            user_count=len(state.users),
            host_count=len(state.hosts),
            event_count=len(bus.get_history()),
            s3_bucket_count=len(state.s3_buckets),
        )


@router.post("/reset", response_model=ResetResponse)
async def reset_state() -> ResetResponse:
    """Reset all simulation state.

    Clears all jobs, users, hosts, settings, S3 buckets, and event history.
    Use this to start fresh between test runs.
    """
    reset_simulation()
    return ResetResponse(success=True, message="Simulation state reset successfully")


@router.get("/scenarios", response_model=ScenarioListResponse)
async def list_scenarios() -> ScenarioListResponse:
    """List all available scenarios.

    Returns all built-in scenarios with their descriptions and configuration.
    """
    manager = get_scenario_manager()
    scenarios = manager.list_scenarios()
    current = manager.get_current_scenario()

    return ScenarioListResponse(
        scenarios=[
            ScenarioInfo(
                type=s.scenario_type.value,
                name=s.name,
                description=s.description,
                has_chaos=s.chaos is not None,
                initial_jobs=s.initial_jobs,
            )
            for s in scenarios
        ],
        current=current.scenario_type.value if current else None,
    )


@router.post("/scenarios/activate", response_model=ActivateScenarioResponse)
async def activate_scenario(
    request: ActivateScenarioRequest,
) -> ActivateScenarioResponse:
    """Activate a scenario.

    Resets simulation state and applies the specified scenario configuration,
    including S3 fixtures and command configurations.
    Also seeds the 3 dev users (devuser, devadmin, devmanager) with auth credentials.
    If scenario has initial_jobs > 0, creates queued jobs for the dev user.
    """
    from pulldb.simulation import seed_dev_scenario
    
    manager = get_scenario_manager()

    # Validate scenario type
    try:
        scenario_type = ScenarioType(request.scenario_type)
    except ValueError as e:
        valid_types = [st.value for st in ScenarioType]
        logger.debug("Invalid scenario type: %s", request.scenario_type, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scenario type: {request.scenario_type}. "
            f"Valid types: {valid_types}",
        ) from e

    # Activate scenario (this calls reset_simulation())
    scenario = manager.activate_scenario(scenario_type)

    # Seed dev users and auth credentials
    state = get_simulation_state()
    seed_dev_scenario(state, "lean")  # Use lean to get 3 basic users
    _seed_auth_credentials(state)

    # Create initial jobs if scenario requires them
    if scenario.initial_jobs > 0:
        _seed_scenario_jobs(state, scenario.initial_jobs)

    # Count S3 fixtures loaded
    with state.lock:
        s3_fixtures = sum(len(keys) for keys in state.s3_buckets.values())

    return ActivateScenarioResponse(
        success=True,
        scenario_type=scenario.scenario_type.value,
        scenario_name=scenario.name,
        s3_fixtures_loaded=s3_fixtures,
    )


def _seed_auth_credentials(state: SimulationState) -> None:
    """Seed auth credentials for dev users.
    
    Password: PullDB_Dev2025! (bcrypt hash)
    """
    # Pre-computed bcrypt hash for "PullDB_Dev2025!"
    test_hash = "$2b$12$XnisilncYSnbIvEinwVYTePMF/DMiVUwpUSv8BuOWSlPH5sRam.zG"
    
    with state.lock:
        for user_id in ["usr-001", "usr-002", "usr-003"]:
            state.auth_credentials[user_id] = {
                "password_hash": test_hash,
                "totp_secret": None,
                "failed_attempts": 0,
                "locked_until": None,
            }


def _seed_scenario_jobs(state: SimulationState, count: int) -> None:
    """Seed queued jobs for scenarios with initial_jobs > 0.
    
    Creates jobs owned by devuser (usr-001) in QUEUED status.
    """
    import uuid
    from datetime import UTC, timedelta
    
    from pulldb.domain.models import Job, JobEvent, JobStatus
    
    with state.lock:
        for i in range(count):
            job_id = str(uuid.uuid4())
            now = datetime.now(UTC)
            
            # Create job owned by devuser
            target = f"devusracme{i+1}"
            staging_name = f"{target}_{job_id.replace('-', '')[:12]}"
            
            job = Job(
                id=job_id,
                target=target,
                dbhost="db1.pulldb.test",
                status=JobStatus.QUEUED,
                owner_user_id="usr-001",
                owner_username="devuser",
                owner_user_code="devusr",
                submitted_at=now - timedelta(minutes=5 * (i + 1)),
                started_at=None,
                completed_at=None,
                worker_id=None,
                error_detail=None,
                staging_name=staging_name,
                staging_cleaned_at=None,
                current_operation=None,
                options_json={
                    "customer": f"acme{i+1}",
                    "backup_env": "prd",
                    "s3_key": f"s3://pulldb-backups/prd/acme{i+1}/latest.xbstream.zst",
                },
                custom_target=False,
                expires_at=None,
                locked_at=None,
                locked_by=None,
            )
            state.jobs[job_id] = job
            
            # Create initial "created" event
            event = JobEvent(
                id=len(state.job_events) + 1,
                job_id=job_id,
                event_type="created",
                detail="Job queued",
                logged_at=job.submitted_at,
            )
            state.job_events.append(event)


@router.get("/events", response_model=EventHistoryResponse)
async def get_events(
    event_type: str | None = None,
    job_id: str | None = None,
    limit: int = 100,
) -> EventHistoryResponse:
    """Get event history.

    Returns recorded events with optional filtering by event type or job ID.
    Events are returned newest first.
    """
    bus = get_event_bus()

    # Parse event type if provided
    parsed_event_type: EventType | None = None
    if event_type:
        try:
            parsed_event_type = EventType(event_type)
        except ValueError as e:
            valid_types = [et.value for et in EventType]
            logger.debug("Invalid event type: %s", event_type, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid event type: {event_type}. "
                f"Valid types: {valid_types}",
            ) from e

    events = bus.get_history(
        event_type=parsed_event_type,
        job_id=job_id,
        limit=limit,
    )

    return EventHistoryResponse(
        total=len(events),
        events=[
            EventInfo(
                event_type=e.event_type.value,
                timestamp=e.timestamp,
                source=e.source,
                job_id=e.job_id,
                data=e.data,
            )
            for e in events
        ],
    )


@router.delete("/events", response_model=ResetResponse)
async def clear_events() -> ResetResponse:
    """Clear event history.

    Removes all recorded events without affecting other simulation state.
    """
    bus = get_event_bus()
    bus.clear_history()
    return ResetResponse(success=True, message="Event history cleared")


@router.post("/chaos", response_model=InjectChaosResponse)
async def inject_chaos(request: InjectChaosRequest) -> InjectChaosResponse:
    """Inject chaos at runtime.

    Configures a specific operation to fail with the given probability.
    This allows testing failure scenarios without switching scenarios.
    """
    manager = get_scenario_manager()
    manager.inject_chaos(
        operation=request.operation,
        failure_rate=request.failure_rate,
        error_message=request.error_message,
    )

    return InjectChaosResponse(
        success=True,
        operation=request.operation,
        failure_rate=request.failure_rate,
        message=f"Chaos injected: {request.operation} will fail "
        f"{request.failure_rate * 100:.0f}% of the time",
    )


@router.get("/state", response_model=StateSnapshotResponse)
async def get_state_snapshot() -> StateSnapshotResponse:
    """Get full state snapshot.

    Returns a complete dump of simulation state for debugging.
    Use with caution on large datasets.
    """
    state = get_simulation_state()

    with state.lock:
        # Convert jobs to dicts
        jobs: list[dict[str, Any]] = []
        for job in state.jobs.values():
            submitted_at_str = (
                job.submitted_at.isoformat() if job.submitted_at else None
            )
            jobs.append(
                {
                    "id": job.id,
                    "target": job.target,
                    "status": job.status.value,
                    "owner_username": job.owner_username,
                    "submitted_at": submitted_at_str,
                    "worker_id": job.worker_id,
                    "error_detail": job.error_detail,
                }
            )

        # Convert users to dicts
        users: list[dict[str, Any]] = []
        for user in state.users.values():
            users.append(
                {
                    "user_id": user.user_id,
                    "username": user.username,
                    "user_code": user.user_code,
                    "is_admin": user.is_admin,
                }
            )

        # Convert hosts to dicts
        hosts: list[dict[str, Any]] = []
        for host in state.hosts.values():
            hosts.append(
                {
                    "id": host.id,
                    "hostname": host.hostname,
                    "host_alias": host.host_alias,
                    "enabled": host.enabled,
                }
            )

        return StateSnapshotResponse(
            jobs=jobs,
            users=users,
            hosts=hosts,
            settings=dict(state.settings),
            s3_buckets={k: list(v) for k, v in state.s3_buckets.items()},
        )


@router.get("/event-types")
async def list_event_types() -> dict[str, list[str]]:
    """List all available event types.

    Returns event types grouped by category for documentation purposes.
    """
    return {
        "job_events": [
            EventType.JOB_CREATED.value,
            EventType.JOB_CLAIMED.value,
            EventType.JOB_COMPLETED.value,
            EventType.JOB_FAILED.value,
            EventType.JOB_CANCELED.value,
        ],
        "s3_events": [
            EventType.S3_LIST_KEYS.value,
            EventType.S3_HEAD_OBJECT.value,
            EventType.S3_GET_OBJECT.value,
            EventType.S3_ERROR.value,
        ],
        "exec_events": [
            EventType.EXEC_START.value,
            EventType.EXEC_COMPLETE.value,
            EventType.EXEC_ERROR.value,
        ],
        "system_events": [
            EventType.STATE_RESET.value,
            EventType.SCENARIO_CHANGED.value,
        ],
    }


@router.get("/scenario-types")
async def list_scenario_types() -> dict[str, list[str]]:
    """List all available scenario types.

    Returns scenario types grouped by category for documentation purposes.
    """
    return {
        "success_scenarios": [
            ScenarioType.HAPPY_PATH.value,
            ScenarioType.SINGLE_JOB_SUCCESS.value,
            ScenarioType.MULTIPLE_JOBS_SUCCESS.value,
        ],
        "s3_failure_scenarios": [
            ScenarioType.S3_NOT_FOUND.value,
            ScenarioType.S3_PERMISSION_DENIED.value,
        ],
        "execution_failure_scenarios": [
            ScenarioType.MYLOADER_FAILURE.value,
            ScenarioType.MYLOADER_TIMEOUT.value,
            ScenarioType.POST_SQL_FAILURE.value,
        ],
        "chaos_scenarios": [
            ScenarioType.RANDOM_FAILURES.value,
            ScenarioType.SLOW_OPERATIONS.value,
            ScenarioType.INTERMITTENT_FAILURES.value,
        ],
    }


class SeedUserRequest(BaseModel):
    """Request to seed a test user."""

    username: str = Field(..., description="Username for the test user")
    password: str = Field(..., description="Password for the test user")
    user_code: str = Field(default="test", description="User code")
    is_admin: bool = Field(default=False, description="Whether user is admin")
    role: str = Field(default="user", description="User role: user, manager, or admin")
    manager_id: str | None = Field(default=None, description="ID of the user's manager")


class SeedUserResponse(BaseModel):
    """Response after seeding a test user."""

    success: bool = True
    user_id: str
    username: str
    message: str


@router.post("/seed-user", response_model=SeedUserResponse)
async def seed_user(request: SeedUserRequest) -> SeedUserResponse:
    """Seed a test user for simulation mode.

    Creates a user with the given credentials for testing authentication flows.
    """
    user_repo = SimulatedUserRepository()
    auth_repo = SimulatedAuthRepository()

    # Check if user already exists
    existing = user_repo.get_user_by_username(request.username)
    if existing:
        return SeedUserResponse(
            success=True,
            user_id=existing.user_id,
            username=existing.username,
            message=f"User '{request.username}' already exists",
        )

    # Create the user
    user = user_repo.create_user(
        username=request.username, 
        user_code=request.user_code,
        manager_id=request.manager_id,
    )

    # Set password
    password_hash = hash_password(request.password)
    auth_repo.set_password_hash(user.user_id, password_hash)

    # Make admin if requested
    if request.is_admin:
        state = get_simulation_state()
        with state.lock:
            from pulldb.domain.models import UserRole
            # Determine role - admin flag or explicit role
            if request.role == "admin" or request.is_admin:
                role = UserRole.ADMIN
            elif request.role == "manager":
                role = UserRole.MANAGER
            else:
                role = UserRole.USER
            state.users[user.user_id] = replace(user, is_admin=True, role=role)
            # Also update users_by_code index
            if user.user_code in state.users_by_code:
                state.users_by_code[user.user_code] = replace(user, is_admin=True, role=role)
    elif request.role and request.role != "user":
        # Set role even if not admin
        state = get_simulation_state()
        with state.lock:
            from pulldb.domain.models import UserRole
            if request.role == "manager":
                role = UserRole.MANAGER
            elif request.role == "admin":
                role = UserRole.ADMIN
            else:
                role = UserRole.USER
            state.users[user.user_id] = replace(user, role=role)
            if user.user_code in state.users_by_code:
                state.users_by_code[user.user_code] = replace(user, role=role)

    return SeedUserResponse(
        success=True,
        user_id=user.user_id,
        username=user.username,
        message=f"Created user '{request.username}' with password",
    )


# ============================================================================
# Queue Runner Endpoints
# ============================================================================


class QueueProcessRequest(BaseModel):
    """Request to process queued jobs."""

    max_jobs: int | None = Field(None, description="Maximum jobs to process (None=all)")
    failure_rate: float = Field(
        0.0, ge=0.0, le=1.0, description="Probability of job failure"
    )
    phase_delay_ms: int = Field(0, ge=0, description="Delay between phases in ms")


class ProcessedJobInfo(BaseModel):
    """Information about a processed job."""

    job_id: str
    target: str
    status: str
    error_detail: str | None = None


class QueueProcessResponse(BaseModel):
    """Response from queue processing."""

    success: bool = True
    jobs_processed: int
    jobs: list[ProcessedJobInfo]
    message: str


class AdvanceJobRequest(BaseModel):
    """Request to advance a specific job."""

    job_id: str = Field(..., description="Job ID to advance")


class AdvanceJobResponse(BaseModel):
    """Response from advancing a job."""

    success: bool
    job_id: str
    current_phase: str | None = None
    status: str
    message: str


@router.post("/queue/process-next", response_model=QueueProcessResponse)
async def process_next_job(
    request: QueueProcessRequest | None = None,
) -> QueueProcessResponse:
    """Process the next queued job.

    Claims and processes one queued job through all phases.
    Useful for step-by-step testing.
    """
    from pulldb.simulation import SimulatedJobRepository
    from pulldb.simulation.core.queue_runner import MockQueueRunner, MockRunnerConfig

    job_repo = SimulatedJobRepository()

    config = MockRunnerConfig(
        failure_rate=request.failure_rate if request else 0.0,
        phase_delay_ms=request.phase_delay_ms if request else 0,
    )
    runner = MockQueueRunner(job_repo, config)

    job = runner.process_next()

    if job is None:
        return QueueProcessResponse(
            success=True,
            jobs_processed=0,
            jobs=[],
            message="No queued jobs to process",
        )

    return QueueProcessResponse(
        success=True,
        jobs_processed=1,
        jobs=[
            ProcessedJobInfo(
                job_id=job.id,
                target=job.target,
                status=job.status.value,
                error_detail=job.error_detail,
            )
        ],
        message=f"Processed job {job.id[:8]} -> {job.status.value}",
    )


@router.post("/queue/process-all", response_model=QueueProcessResponse)
async def process_all_jobs(
    request: QueueProcessRequest | None = None,
) -> QueueProcessResponse:
    """Process all queued jobs.

    Claims and processes all queued jobs through their phases.
    Optionally limit the number of jobs processed.
    """
    from pulldb.simulation import SimulatedJobRepository
    from pulldb.simulation.core.queue_runner import MockQueueRunner, MockRunnerConfig

    job_repo = SimulatedJobRepository()

    config = MockRunnerConfig(
        failure_rate=request.failure_rate if request else 0.0,
        phase_delay_ms=request.phase_delay_ms if request else 0,
    )
    runner = MockQueueRunner(job_repo, config)

    max_jobs = request.max_jobs if request else None
    jobs = runner.process_all(max_jobs=max_jobs)

    job_infos = [
        ProcessedJobInfo(
            job_id=job.id,
            target=job.target,
            status=job.status.value,
            error_detail=job.error_detail,
        )
        for job in jobs
    ]

    completed = sum(1 for j in jobs if j.status.value == "complete")
    failed = sum(1 for j in jobs if j.status.value == "failed")
    canceled = sum(1 for j in jobs if j.status.value == "canceled")

    return QueueProcessResponse(
        success=True,
        jobs_processed=len(jobs),
        jobs=job_infos,
        message=f"Processed {len(jobs)} jobs: {completed} complete, {failed} failed, {canceled} canceled",
    )


@router.post("/queue/advance-job", response_model=AdvanceJobResponse)
async def advance_job_phase(request: AdvanceJobRequest) -> AdvanceJobResponse:
    """Advance a specific running job to its next phase.

    Useful for step-by-step debugging. Only works for RUNNING jobs.
    """
    from pulldb.simulation import SimulatedJobRepository
    from pulldb.simulation.core.queue_runner import MockQueueRunner

    job_repo = SimulatedJobRepository()
    runner = MockQueueRunner(job_repo)

    job = runner.advance_job_phase(request.job_id)

    if job is None:
        # Check if job exists
        existing = job_repo.get_job_by_id(request.job_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {request.job_id} not found",
            )
        return AdvanceJobResponse(
            success=False,
            job_id=request.job_id,
            current_phase=existing.current_operation,
            status=existing.status.value,
            message=f"Cannot advance job in {existing.status.value} state",
        )

    return AdvanceJobResponse(
        success=True,
        job_id=job.id,
        current_phase=job.current_operation,
        status=job.status.value,
        message=f"Advanced job to {job.current_operation or job.status.value}",
    )


class QueueStatusResponse(BaseModel):
    """Response with queue status."""

    queued_count: int
    running_count: int
    complete_count: int
    failed_count: int
    canceled_count: int
    total_count: int


@router.get("/queue/status", response_model=QueueStatusResponse)
async def get_queue_status() -> QueueStatusResponse:
    """Get current queue status with job counts by status."""
    state = get_simulation_state()

    with state.lock:
        statuses = {"queued": 0, "running": 0, "complete": 0, "failed": 0, "canceled": 0}
        for job in state.jobs.values():
            status_val = job.status.value
            if status_val in statuses:
                statuses[status_val] += 1

        return QueueStatusResponse(
            queued_count=statuses["queued"],
            running_count=statuses["running"],
            complete_count=statuses["complete"],
            failed_count=statuses["failed"],
            canceled_count=statuses["canceled"],
            total_count=len(state.jobs),
        )
