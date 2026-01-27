"""Data seeding for Simulation Mode.

Provides functions to populate SimulationState with realistic test data
for development, testing, and demo scenarios.

HCA Layer: shared (simulation infrastructure)

=============================================================================
SCENARIO DEFINITIONS - Edit these to configure simulation scenarios
=============================================================================
"""

from __future__ import annotations

import json
import random
from typing import Any
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pulldb.domain.models import (
    DBHost,
    Job,
    JobEvent,
    JobStatus,
    User,
    UserRole,
)

if TYPE_CHECKING:
    from pulldb.simulation.core.state import SimulationState


# =============================================================================
# SCENARIO CONFIGURATION - Easy to edit section
# =============================================================================

@dataclass
class ScenarioConfig:
    """Configuration for a simulation scenario.
    
    Edit these values to customize each scenario's behavior.
    """
    name: str
    description: str
    
    # User configuration
    users: str = "standard"  # "lean" (3 users) or "standard" (6 users)
    
    # Host configuration  
    hosts: str = "standard"  # "lean" (1 host) or "standard" (6 hosts)
    
    # Customer list
    customers: str = "standard"  # "lean" (3) or "standard" (20)
    
    # Job counts
    active_jobs: int = 0
    history_jobs: int = 0
    custom_target_jobs: int = 0
    
    # Extra features
    include_orphans: bool = False
    include_audit_logs: bool = False
    include_api_keys: bool = False
    include_disallowed_users: bool = False
    include_host_errors: bool = False
    include_screenshot_jobs: bool = False
    
    # Job distribution overrides
    force_all_queued: bool = False
    force_all_running: bool = False
    force_all_failed: bool = False
    respect_job_limits: bool = True


# =============================================================================
# SCENARIO REGISTRY - Add new scenarios here
# =============================================================================

SCENARIOS: dict[str, ScenarioConfig] = {
    # -------------------------------------------------------------------------
    # MINIMAL SCENARIOS
    # -------------------------------------------------------------------------
    "lean": ScenarioConfig(
        name="Lean",
        description="Bare minimum: 3 users, 1 host, 3 customers, NO jobs",
        users="lean",
        hosts="lean", 
        customers="lean",
        active_jobs=0,
        history_jobs=0,
    ),
    
    "minimal": ScenarioConfig(
        name="Minimal",
        description="Infrastructure only (users, hosts, settings) - no jobs",
        users="standard",
        hosts="standard",
        customers="standard",
        active_jobs=0,
        history_jobs=0,
        custom_target_jobs=2,
        include_orphans=True,
        include_audit_logs=True,
        include_api_keys=True,
        include_disallowed_users=True,
        include_host_errors=True,
    ),
    
    "empty": ScenarioConfig(
        name="Empty State",
        description="Alias for minimal - no jobs",
        users="standard",
        hosts="standard",
        customers="standard",
        active_jobs=0,
        history_jobs=0,
        custom_target_jobs=2,
        include_orphans=True,
        include_audit_logs=True,
        include_api_keys=True,
        include_disallowed_users=True,
        include_host_errors=True,
    ),
    
    # -------------------------------------------------------------------------
    # ACTIVE SCENARIOS
    # -------------------------------------------------------------------------
    "busy": ScenarioConfig(
        name="Busy System",
        description="Many concurrent running jobs",
        active_jobs=15,
        history_jobs=100,
        custom_target_jobs=5,
        force_all_running=True,
        include_orphans=True,
        include_audit_logs=True,
        include_api_keys=True,
        include_disallowed_users=True,
        include_host_errors=True,
    ),
    
    "queue_backlog": ScenarioConfig(
        name="Queue Backlog",
        description="Many jobs waiting in queue",
        active_jobs=25,
        history_jobs=50,
        force_all_queued=True,
        include_orphans=True,
        include_audit_logs=True,
        include_api_keys=True,
        include_disallowed_users=True,
        include_host_errors=True,
    ),
    
    # -------------------------------------------------------------------------
    # ERROR SCENARIOS
    # -------------------------------------------------------------------------
    "all_failed": ScenarioConfig(
        name="All Failed",
        description="Multiple failed jobs for error testing",
        active_jobs=0,
        history_jobs=20,
        force_all_failed=True,
        include_orphans=True,
        include_audit_logs=True,
        include_api_keys=True,
        include_disallowed_users=True,
        include_host_errors=True,
    ),
    
    # -------------------------------------------------------------------------
    # TESTING SCENARIOS
    # -------------------------------------------------------------------------
    "screenshots": ScenarioConfig(
        name="Screenshots",
        description="Specific job states for documentation screenshots",
        active_jobs=0,
        history_jobs=20,
        custom_target_jobs=3,
        include_screenshot_jobs=True,
        include_orphans=True,
        include_audit_logs=True,
        include_api_keys=True,
        include_disallowed_users=True,
        include_host_errors=True,
    ),
    
    "dev_mocks": ScenarioConfig(
        name="Dev Server Mocks",
        description="Large dataset for stress testing (800 jobs)",
        active_jobs=400,
        history_jobs=400,
        custom_target_jobs=10,
        respect_job_limits=False,
        include_orphans=True,
        include_audit_logs=True,
        include_api_keys=True,
        include_disallowed_users=True,
        include_host_errors=True,
    ),
}


def get_scenario_list() -> list[dict[str, str]]:
    """Get list of available scenarios for UI dropdown.
    
    Returns:
        List of dicts with 'id', 'name', and 'description' keys.
    """
    return [
        {"id": key, "name": cfg.name, "description": cfg.description}
        for key, cfg in SCENARIOS.items()
    ]


# =============================================================================
# DATA POOLS - Customer, worker, host, and error message pools
# =============================================================================

# Standard customers (20)
CUSTOMERS = [
    "acmehvac",
    "techcorp",
    "globalretail",
    "fastlogistics",
    "medisys",
    "edulearn",
    "finserve",
    "autoparts",
    "foodmart",
    "energyco",
    "buildpro",
    "healthnet",
    "cloudnine",
    "skytech",
    "oceanview",
    "mountainpeak",
    "riverflow",
    "sunbeam",
    "moonlight",
    "stargazer",
]

# Lean customers (3) - subset for minimal testing
LEAN_CUSTOMERS = ["acmehvac", "techcorp", "globalretail"]

WORKERS = [
    "worker-alpha",
    "worker-beta",
    "worker-gamma",
    "worker-delta",
    "worker-epsilon",
]

# Standard hosts: (id, hostname, alias, max_running, max_active, enabled)
STANDARD_HOSTS = [
    ("00000000-0000-0000-0000-000000000001", "mysql-staging-01.example.com", "staging-01", 3, 10, True),
    ("00000000-0000-0000-0000-000000000002", "mysql-staging-02.example.com", "staging-02", 2, 10, True),
    ("00000000-0000-0000-0000-000000000003", "mysql-staging-03.example.com", "staging-03", 2, 10, True),
    ("00000000-0000-0000-0000-000000000004", "mysql-prod-01.example.com", "prod-01", 1, 5, True),
    ("00000000-0000-0000-0000-000000000005", "mysql-dev.example.com", "dev", 1, 10, False),
    ("00000000-0000-0000-0000-000000000006", "mysql-broken.example.com", "broken", 2, 10, True),
]

# Lean host: single staging host
LEAN_HOSTS = [
    ("00000000-0000-0000-0000-000000000001", "mysql-staging-01.example.com", "staging-01", 3, 10, True),
]

# DB_HOSTS for job seeding (hostname, alias pairs)
DB_HOSTS = [
    ("mysql-staging-01.example.com", "staging-01"),
    ("mysql-staging-02.example.com", "staging-02"),
    ("mysql-staging-03.example.com", "staging-03"),
    ("mysql-prod-01.example.com", "prod-01"),
]

ERROR_MESSAGES = [
    "S3 download timeout after 300s",
    "MySQL connection refused",
    "Disk space exhausted",
    "myloader process killed by OOM",
    "Invalid backup format detected",
    "Permission denied on target database",
    "Backup file corrupted or incomplete",
]

# Custom target names for custom target job seeding
CUSTOM_TARGET_NAMES = [
    "migrationtest",
    "featurebranch",
    "hotfixdata",
    "qavalidation",
    "performancebench",
    "clientdemo",
    "sandboxenv",
    "stagingcopy",
    "backuprestore",
    "dataimport",
]


# =============================================================================
# USER SEEDING
# =============================================================================

def _seed_users(state: SimulationState, mode: str = "standard") -> dict[str, User]:
    """Seed users based on mode.
    
    Args:
        state: SimulationState to populate.
        mode: "lean" for 3 users, "standard" for 6 users.
        
    Returns:
        Dict mapping user_id to User.
    """
    default_host = "staging-01"
    dev_hosts = ["staging-01", "staging-02", "staging-03"]
    
    # Password hash for: PullDB_Dev2025!
    password_hash = "$2b$12$uJQJWPXefk/JICbVNIt23OYvf/ul545Uk5Mb50wTuxKsvDtj6Xmr2"
    
    if mode == "lean":
        # Lean: 3 users only
        users_data: list[tuple] = [
            ("usr-001", "devuser", "devusr", UserRole.USER, "usr-003", dev_hosts[:1], None, None, None, None),
            ("usr-002", "devadmin", "devadm", UserRole.ADMIN, None, None, None, None, "JBSWY3DPEHPK3PXP", None),
            ("usr-003", "devmanager", "devmgr", UserRole.MANAGER, "usr-002", dev_hosts[:1], None, None, None, None),
        ]
    else:
        # Standard: 6 users with various states
        users_data = [
            ("usr-001", "devuser", "devusr", UserRole.USER, "usr-003", dev_hosts, None, None, None, None),
            ("usr-002", "devadmin", "devadm", UserRole.ADMIN, None, None, None, None, "JBSWY3DPEHPK3PXP", None),
            ("usr-003", "devmanager", "devmgr", UserRole.MANAGER, "usr-002", dev_hosts, None, None, None, None),
            ("usr-004", "disableduser", "disusr", UserRole.USER, "usr-003", dev_hosts, datetime(2025, 1, 15, tzinfo=UTC), None, None, None),
            ("usr-005", "resetuser", "rstusr", UserRole.USER, "usr-003", dev_hosts, None, None, None, datetime(2025, 1, 20, 14, 30, tzinfo=UTC)),
            ("usr-006", "systemaccount", "sysacc", UserRole.SERVICE, None, None, None, datetime(2024, 1, 1, tzinfo=UTC), None, None),
        ]
    
    created_users: dict[str, User] = {}
    
    with state.lock:
        for user_id, username, user_code, role, manager_id, allowed_hosts, disabled_at, locked_at, totp_secret, password_reset_at in users_data:
            user = User(
                user_id=user_id,
                username=username,
                user_code=user_code,
                role=role,
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
                manager_id=manager_id,
                disabled_at=disabled_at,
                allowed_hosts=allowed_hosts,
                default_host=default_host if allowed_hosts else None,
                locked_at=locked_at,
            )
            state.users[user_id] = user
            state.users_by_code[user_code] = user
            created_users[user_id] = user
            
            state.auth_credentials[user_id] = {
                "password_hash": password_hash,
                "totp_secret": totp_secret,
                "failed_attempts": 0,
                "locked_until": None,
                "password_reset_at": password_reset_at,
            }
    
    return created_users


# =============================================================================
# HOST SEEDING
# =============================================================================

def _seed_hosts(state: SimulationState, mode: str = "standard") -> list[DBHost]:
    """Seed hosts based on mode.
    
    Args:
        state: SimulationState to populate.
        mode: "lean" for 1 host, "standard" for 6 hosts.
        
    Returns:
        List of created DBHost objects.
    """
    hosts_data = LEAN_HOSTS if mode == "lean" else STANDARD_HOSTS
    created_hosts: list[DBHost] = []
    
    with state.lock:
        for host_id, hostname, alias, max_running, max_active, enabled in hosts_data:
            host = DBHost(
                id=host_id,
                hostname=hostname,
                host_alias=alias,
                credential_ref=f"mock/mysql/{alias}",
                max_running_jobs=max_running,
                max_active_jobs=max_active,
                enabled=enabled,
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
            state.hosts[hostname] = host
            created_hosts.append(host)
    
    return created_hosts


def _seed_user_host_assignments(state: SimulationState, mode: str = "standard") -> None:
    """Seed user-host assignments into state.user_hosts."""
    host_id_by_alias = {
        "staging-01": "00000000-0000-0000-0000-000000000001",
        "staging-02": "00000000-0000-0000-0000-000000000002",
        "staging-03": "00000000-0000-0000-0000-000000000003",
        "prod-01": "00000000-0000-0000-0000-000000000004",
        "dev": "00000000-0000-0000-0000-000000000005",
        "broken": "00000000-0000-0000-0000-000000000006",
    }
    
    if mode == "lean":
        user_host_assignments = [
            ("usr-001", ["staging-01"], "staging-01"),
            ("usr-003", ["staging-01"], "staging-01"),
        ]
    else:
        user_host_assignments = [
            ("usr-001", ["staging-01", "staging-02", "staging-03"], "staging-01"),
            ("usr-003", ["staging-01", "staging-02", "staging-03"], "staging-01"),
        ]
    
    with state.lock:
        for user_id, host_aliases, default_alias in user_host_assignments:
            assignments: list[dict[str, Any]] = []
            default_host_id = host_id_by_alias.get(default_alias)
            
            for alias in host_aliases:
                host_id = host_id_by_alias.get(alias)
                if host_id:
                    assignments.append({
                        'host_id': host_id,
                        'is_default': host_id == default_host_id,
                        'assigned_at': datetime(2024, 1, 1, tzinfo=UTC),
                        'assigned_by': 'system-seed',
                    })
            
            state.user_hosts[user_id] = assignments


# =============================================================================
# SETTINGS SEEDING
# =============================================================================

def _seed_settings(state: SimulationState, mode: str = "standard") -> None:
    """Seed settings based on mode."""
    if mode == "lean":
        settings = {
            "max_active_jobs_per_user": "5",
            "default_retention_days": "30",
            "maintenance_mode": "false",
        }
    else:
        settings = {
            "myloader_threads": "4",
            "myloader_overwrite": "true",
            "staging_retention_days": "7",
            "job_log_retention_days": "30",
            "max_active_jobs_global": "0",
            "max_active_jobs_per_user": "5",
            "s3_bucket_path": "s3://pulldb-backups/production",
            "work_directory": "/var/lib/pulldb/work",
        }
    
    with state.lock:
        for key, value in settings.items():
            state.settings[key] = value
            state.settings_metadata[key] = {
                "description": f"Mock setting: {key}",
                "updated_at": datetime(2024, 6, 1, tzinfo=UTC),
            }


# =============================================================================
# JOB CREATION HELPERS
# =============================================================================

def _create_job(
    job_id: str,
    source_customer: str,
    status: JobStatus,
    owner_user_id: str,
    owner_username: str,
    owner_user_code: str,
    dbhost: str,
    backup_env: str = "prd",
    is_qatemplate: bool = False,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_detail: str | None = None,
    worker_id: str | None = None,
    custom_target_name: str | None = None,
    expires_at: datetime | None = None,
    is_locked: bool = False,
    locked_by: str | None = None,
) -> Job:
    """Create a Job instance for seeding."""
    ts = created_at or datetime.now(UTC)
    
    is_custom_target = custom_target_name is not None
    if is_custom_target:
        target = custom_target_name
    elif is_qatemplate:
        target = f"{owner_user_code}qatemplate"
    else:
        target = f"{owner_user_code}{source_customer}"
    
    clean_id = job_id.replace("-", "").replace("job", "")
    staging_prefix = clean_id[:12].ljust(12, "0")
    staging_name = f"{target}_{staging_prefix}"
    
    options = {
        "customer": source_customer if not is_qatemplate else "qatemplate",
        "backup_env": backup_env,
        "s3_key": f"s3://pulldb-backups/{backup_env}/{source_customer}/latest.xbstream.zst",
    }
    if is_qatemplate:
        options["qatemplate"] = "true"
    if is_custom_target:
        options["custom_target"] = custom_target_name
    
    # Set retention fields for deployed/complete jobs
    job_expires_at = expires_at
    job_locked_at = None
    job_locked_by = None
    if status == JobStatus.DEPLOYED and finished_at:
        # Default: 30 day retention from completion
        if job_expires_at is None:
            job_expires_at = finished_at + timedelta(days=30)
        if is_locked:
            job_locked_at = finished_at
            job_locked_by = locked_by or owner_username
    
    return Job(
        id=job_id,
        target=target,
        dbhost=dbhost,
        status=status,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        owner_user_code=owner_user_code,
        submitted_at=ts,
        started_at=started_at,
        completed_at=finished_at,
        worker_id=worker_id,
        error_detail=error_detail,
        staging_name=staging_name,
        staging_cleaned_at=None,
        current_operation=None,
        options_json=options,
        custom_target=is_custom_target,
        expires_at=job_expires_at,
        locked_at=job_locked_at,
        locked_by=job_locked_by,
    )


def _create_event(
    event_id: int,
    job_id: str,
    event_type: str,
    message: str,
    logged_at: datetime | None = None,
) -> JobEvent:
    """Create a JobEvent instance for seeding."""
    return JobEvent(
        id=event_id,
        job_id=job_id,
        event_type=event_type,
        detail=message,
        logged_at=logged_at or datetime.now(UTC),
    )


def _seed_job_events(state: SimulationState, job: Job, base_event_id: int) -> None:
    """Seed events for a single job."""
    events: list[JobEvent] = []
    event_id = base_event_id + 1
    base_time = job.submitted_at
    
    events.append(_create_event(event_id, job.id, "created", "Job queued", logged_at=base_time))
    event_id += 1
    
    if job.status in (JobStatus.RUNNING, JobStatus.DEPLOYED, JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED):
        claim_time = base_time + timedelta(seconds=random.randint(5, 30))
        worker = job.worker_id or random.choice(WORKERS)
        events.append(_create_event(event_id, job.id, "claimed", f"Claimed by {worker}", logged_at=claim_time))
        event_id += 1
        
        dl_time = claim_time + timedelta(seconds=random.randint(2, 10))
        events.append(_create_event(event_id, job.id, "downloading", "Downloading backup from S3...", logged_at=dl_time))
        event_id += 1
        
        if job.status == JobStatus.RUNNING:
            download_progress = random.randint(30, 80)
            total_bytes = random.randint(500_000_000, 5_000_000_000)
            downloaded_bytes = int(total_bytes * download_progress / 100)
            progress_detail = json.dumps({
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": total_bytes,
                "percent_complete": float(download_progress),
                "elapsed_seconds": random.randint(60, 600),
            })
            progress_time = dl_time + timedelta(seconds=random.randint(30, 180))
            events.append(_create_event(event_id, job.id, "download_progress", progress_detail, logged_at=progress_time))
            event_id += 1
            
            restore_time = dl_time + timedelta(minutes=random.randint(5, 20))
            events.append(_create_event(event_id, job.id, "restoring", "Running myloader restore...", logged_at=restore_time))
            event_id += 1
            
        elif job.status in (JobStatus.DEPLOYED, JobStatus.COMPLETE):
            dl_complete = dl_time + timedelta(minutes=random.randint(2, 15))
            events.append(_create_event(event_id, job.id, "downloaded", "Download complete", logged_at=dl_complete))
            event_id += 1
            
            restore_start = dl_complete + timedelta(seconds=random.randint(5, 30))
            events.append(_create_event(event_id, job.id, "restoring", "Running myloader restore...", logged_at=restore_start))
            event_id += 1
            
            post_time = restore_start + timedelta(minutes=random.randint(10, 45))
            events.append(_create_event(event_id, job.id, "post_sql", "Applying post-restore scripts...", logged_at=post_time))
            event_id += 1
            
            complete_time = post_time + timedelta(minutes=random.randint(1, 5))
            events.append(_create_event(event_id, job.id, "complete", "Restore complete", logged_at=complete_time))
            event_id += 1
            
        elif job.status == JobStatus.FAILED:
            fail_time = dl_time + timedelta(minutes=random.randint(5, 30))
            events.append(_create_event(event_id, job.id, "failed", job.error_detail or "Unknown error", logged_at=fail_time))
            event_id += 1
    
    state.job_events.extend(events)


# =============================================================================
# JOB SEEDING FUNCTIONS
# =============================================================================

def _seed_active_jobs(
    state: SimulationState,
    count: int,
    users: dict[str, User],
    respect_limits: bool = True,
) -> list[Job]:
    """Seed active jobs (queued/running) into SimulationState."""
    if not users:
        raise ValueError("No users available for job ownership.")
    
    max_per_user = 0
    if respect_limits and "max_active_jobs_per_user" in state.settings:
        try:
            max_per_user = int(state.settings["max_active_jobs_per_user"])
        except (ValueError, TypeError):
            max_per_user = 0
    
    owners_pool = [
        ("usr-001", "devuser", "devusr"),
        ("usr-001", "devuser", "devusr"),
        ("usr-001", "devuser", "devusr"),
        ("usr-002", "devadmin", "devadm"),
        ("usr-003", "devmanager", "devmgr"),
    ]
    
    jobs_per_user: dict[str, int] = {}
    with state.lock:
        for job in state.jobs.values():
            if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                jobs_per_user[job.owner_user_id] = jobs_per_user.get(job.owner_user_id, 0) + 1
    
    jobs: list[Job] = []
    base_time = datetime.now(UTC) - timedelta(hours=12)
    
    with state.lock:
        for i in range(count):
            job_id = str(uuid.uuid4())
            
            if respect_limits and max_per_user > 0:
                available_owners = [o for o in owners_pool if jobs_per_user.get(o[0], 0) < max_per_user]
                if not available_owners:
                    break
                owner_id, owner_username, owner_user_code = random.choice(available_owners)
            else:
                owner_id, owner_username, owner_user_code = random.choice(owners_pool)
            
            jobs_per_user[owner_id] = jobs_per_user.get(owner_id, 0) + 1
            
            status = JobStatus.QUEUED if random.random() < 0.3 else JobStatus.RUNNING
            customer = random.choice(CUSTOMERS)
            dbhost, _ = random.choice(DB_HOSTS)
            env = random.choice(["prd", "stg"])
            
            minutes_ago = random.randint(0, 720)
            created_at = base_time + timedelta(minutes=720 - minutes_ago)
            
            started_at = None
            worker_id = None
            if status == JobStatus.RUNNING:
                started_at = created_at + timedelta(minutes=random.randint(1, 5))
                worker_id = random.choice(WORKERS)
            
            job = _create_job(
                job_id=job_id,
                source_customer=customer,
                status=status,
                owner_user_id=owner_id,
                owner_username=owner_username,
                owner_user_code=owner_user_code,
                dbhost=dbhost,
                backup_env=env,
                created_at=created_at,
                started_at=started_at,
                worker_id=worker_id,
            )
            
            state.jobs[job_id] = job
            jobs.append(job)
            _seed_job_events(state, job, len(state.job_events))
    
    return jobs


def _seed_history_jobs(
    state: SimulationState,
    count: int,
    users: dict[str, User],
) -> list[Job]:
    """Seed historical jobs (complete/failed/canceled) into SimulationState."""
    if not users:
        raise ValueError("No users available for job ownership.")
    
    owners = [
        ("usr-001", "devuser", "devusr"),
        ("usr-001", "devuser", "devusr"),
        ("usr-001", "devuser", "devusr"),
        ("usr-002", "devadmin", "devadm"),
    ]
    
    statuses = [JobStatus.DEPLOYED] * 4 + [JobStatus.FAILED]
    jobs: list[Job] = []
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    
    with state.lock:
        for i in range(count):
            job_id = str(uuid.uuid4())
            status = random.choice(statuses)
            owner_id, owner_username, owner_user_code = random.choice(owners)
            
            is_qatemplate = random.random() < 0.10
            
            hours_ago = i * 2 + random.randint(0, 12)
            created_at = base_time - timedelta(hours=hours_ago)
            started_at = created_at + timedelta(minutes=random.randint(1, 10))
            duration_minutes = random.randint(5, 120)
            finished_at = started_at + timedelta(minutes=duration_minutes)
            
            error_detail = random.choice(ERROR_MESSAGES) if status == JobStatus.FAILED else None
            
            customer = random.choice(CUSTOMERS[:12])
            dbhost, _ = random.choice(DB_HOSTS)
            env = random.choice(["prd", "stg"])
            worker = random.choice(WORKERS[:4])
            
            job = _create_job(
                job_id=job_id,
                source_customer=customer,
                status=status,
                owner_user_id=owner_id,
                owner_username=owner_username,
                owner_user_code=owner_user_code,
                dbhost=dbhost,
                backup_env=env,
                is_qatemplate=is_qatemplate,
                created_at=created_at,
                started_at=started_at,
                finished_at=finished_at,
                error_detail=error_detail,
                worker_id=worker,
            )
            
            state.jobs[job_id] = job
            jobs.append(job)
            
            if i < 50:
                _seed_job_events(state, job, len(state.job_events))
    
    return jobs


def _seed_custom_target_jobs(
    state: SimulationState,
    count: int,
    users: dict[str, User],
) -> list[Job]:
    """Seed jobs with custom target names."""
    if not users:
        raise ValueError("No users available for job ownership.")
    
    owners = [
        ("usr-001", "devuser", "devusr"),
        ("usr-001", "devuser", "devusr"),
        ("usr-002", "devadmin", "devadm"),
    ]
    
    jobs: list[Job] = []
    base_time = datetime.now(UTC) - timedelta(hours=6)
    
    with state.lock:
        for i in range(count):
            job_id = str(uuid.uuid4())
            owner_id, owner_username, owner_user_code = random.choice(owners)
            
            status_weights = [
                (JobStatus.DEPLOYED, 4),
                (JobStatus.RUNNING, 2),
                (JobStatus.QUEUED, 2),
                (JobStatus.FAILED, 2),
            ]
            status = random.choices(
                [s for s, _ in status_weights],
                weights=[w for _, w in status_weights],
            )[0]
            
            custom_name = CUSTOM_TARGET_NAMES[i % len(CUSTOM_TARGET_NAMES)]
            customer = random.choice(CUSTOMERS)
            dbhost, _ = random.choice(DB_HOSTS)
            env = random.choice(["prd", "stg"])
            
            minutes_ago = random.randint(0, 360)
            created_at = base_time + timedelta(minutes=360 - minutes_ago)
            
            started_at = None
            finished_at = None
            worker_id = None
            error_detail = None
            
            if status in (JobStatus.RUNNING, JobStatus.DEPLOYED, JobStatus.FAILED):
                started_at = created_at + timedelta(minutes=random.randint(1, 5))
                worker_id = random.choice(WORKERS)
            
            if status in (JobStatus.DEPLOYED, JobStatus.FAILED):
                assert started_at is not None  # Set in RUNNING/DEPLOYED/FAILED branch above
                finished_at = started_at + timedelta(minutes=random.randint(10, 60))
            
            if status == JobStatus.FAILED:
                error_detail = random.choice(ERROR_MESSAGES)
            
            job = _create_job(
                job_id=job_id,
                source_customer=customer,
                status=status,
                owner_user_id=owner_id,
                owner_username=owner_username,
                owner_user_code=owner_user_code,
                dbhost=dbhost,
                backup_env=env,
                created_at=created_at,
                started_at=started_at,
                finished_at=finished_at,
                worker_id=worker_id,
                error_detail=error_detail,
                custom_target_name=custom_name,
            )
            
            state.jobs[job_id] = job
            jobs.append(job)
            _seed_job_events(state, job, len(state.job_events))
    
    return jobs


# =============================================================================
# EXTRA FEATURE SEEDING
# =============================================================================

# Orphan database seeds
ORPHAN_DB_SEEDS = [
    ("mysql-staging-01.example.com", "devusracmehvac", "aaa111bbb222"),
    ("mysql-staging-01.example.com", "devusrtechcorp", "ccc333ddd444"),
    ("mysql-staging-01.example.com", "devadmglobalretail", "eee555fff666"),
    ("mysql-staging-01.example.com", "devmgrfastlogistics", "111222333444"),
    ("mysql-staging-02.example.com", "devusrmedisys", "555666777888"),
    ("mysql-staging-02.example.com", "devadmedulearn", "999aaabbbccc"),
    ("mysql-staging-02.example.com", "devusrfinserve", "dddeeefff000"),
]

ORPHAN_DB_SIZES: dict[tuple[str, str, str], float] = {
    ("mysql-staging-01.example.com", "devusracmehvac", "aaa111bbb222"): 245.5,
    ("mysql-staging-01.example.com", "devusrtechcorp", "ccc333ddd444"): 1024.0,
    ("mysql-staging-01.example.com", "devadmglobalretail", "eee555fff666"): 512.75,
    ("mysql-staging-01.example.com", "devmgrfastlogistics", "111222333444"): 78.25,
    ("mysql-staging-02.example.com", "devusrmedisys", "555666777888"): 2048.0,
    ("mysql-staging-02.example.com", "devadmedulearn", "999aaabbbccc"): 156.0,
    ("mysql-staging-02.example.com", "devusrfinserve", "dddeeefff000"): 892.5,
}

ORPHAN_DB_METADATA: dict[tuple[str, str, str], dict[str, Any]] = {
    ("mysql-staging-01.example.com", "devusracmehvac", "aaa111bbb222"): {
        "job_id": "aaa111bbb222-7890-abcd-ef12-345678901234",
        "restored_by": "devuser",
        "restored_at": "2025-01-15T10:30:00Z",
        "target_database": "acmehvac_prd",
    },
    ("mysql-staging-01.example.com", "devusrtechcorp", "ccc333ddd444"): {
        "job_id": "ccc333ddd444-abcd-ef12-3456-78901234abcd",
        "restored_by": "devadmin",
        "restored_at": "2025-01-14T14:45:00Z",
        "target_database": "techcorp_prd",
    },
    ("mysql-staging-02.example.com", "devusrmedisys", "555666777888"): {
        "job_id": "555666777888-1234-5678-90ab-cdef12345678",
        "restored_by": "devuser",
        "restored_at": "2025-01-13T09:15:00Z",
        "target_database": "medisys_prd",
    },
}


def _seed_orphan_databases(state: SimulationState) -> None:
    """Seed mock orphan databases into SimulationState."""
    with state.lock:
        state.staging_databases.clear()
        state.deleted_orphans.clear()
        state.orphan_sizes.clear()
        state.orphan_metadata.clear()
        
        for hostname, target, job_prefix in ORPHAN_DB_SEEDS:
            db_name = f"{target}_{job_prefix}"
            
            if hostname not in state.staging_databases:
                state.staging_databases[hostname] = set()
            
            state.staging_databases[hostname].add(db_name)
            
            key = (hostname, target, job_prefix)
            if key in ORPHAN_DB_SIZES:
                state.orphan_sizes[(hostname, db_name)] = ORPHAN_DB_SIZES[key]
            
            if key in ORPHAN_DB_METADATA:
                state.orphan_metadata[(hostname, db_name)] = ORPHAN_DB_METADATA[key]


def _seed_api_keys(state: SimulationState) -> None:
    """Seed API keys into SimulationState."""
    api_keys_data = [
        ("key_dev001abc123", "usr-001", "Development Laptop", "dev-laptop.local", True, datetime(2025, 1, 10, 9, 0, tzinfo=UTC), "usr-002"),
        ("key_pending999xyz", "usr-003", "New Server Key", "new-server.internal", False, None, None),
        ("key_pending888abc", "usr-001", "CI Pipeline Key", "jenkins.internal", False, None, None),
        ("key_revoked777def", "usr-001", "Old Laptop", "old-laptop.local", False, datetime(2024, 6, 15, 14, 30, tzinfo=UTC), "usr-002"),
    ]
    
    with state.lock:
        for key_id, user_id, name, host_name, is_active, approved_at, approved_by in api_keys_data:
            state.api_keys[key_id] = {
                "key_id": key_id,
                "user_id": user_id,
                "key_secret_hash": "$2b$12$MockKeyHashForSimulationOnlyDontUseInProduction",
                "key_secret": "sim_secret_" + key_id[-8:],
                "name": name,
                "host_name": host_name,
                "created_from_ip": "192.168.1." + str(random.randint(10, 250)),
                "is_active": is_active,
                "created_at": datetime(2025, 1, 5, 10, 0, tzinfo=UTC),
                "last_used_at": datetime(2025, 1, 20, 15, 30, tzinfo=UTC) if is_active else None,
                "last_used_ip": "10.0.0." + str(random.randint(10, 250)) if is_active else None,
                "approved_at": approved_at,
                "approved_by": approved_by,
                "expires_at": None,
            }


def _seed_disallowed_usernames(state: SimulationState) -> None:
    """Seed disallowed usernames into SimulationState."""
    disallowed_data = [
        ("root", "System administrator account", True, None),
        ("daemon", "System daemon account", True, None),
        ("mysql", "MySQL service account", True, None),
        ("nobody", "Unprivileged user", True, None),
        ("admin", "Reserved administrative username", True, None),
        ("pulldb", "PullDB service account", True, None),
        ("testbot", "Automated test account - blocked by policy", False, "usr-002"),
        ("tempuser", "Temporary account no longer needed", False, "usr-002"),
        ("former_employee", "Departed staff member", False, "usr-003"),
    ]
    
    with state.lock:
        for username, reason, is_hardcoded, created_by in disallowed_data:
            state.disallowed_usernames[username.lower()] = {
                "username": username.lower(),
                "reason": reason,
                "is_hardcoded": is_hardcoded,
                "created_at": datetime(2024, 1, 1, tzinfo=UTC) if is_hardcoded else datetime(2025, 1, 18, 11, 30, tzinfo=UTC),
                "created_by": created_by,
            }


def _seed_host_credential_errors(state: SimulationState) -> None:
    """Seed host credential error states."""
    with state.lock:
        state.host_credential_errors["mysql-broken.example.com"] = (
            "Access denied for user 'pulldb_stg'@'10.40.10.50' (using password: YES)"
        )


AUDIT_ACTIONS = [
    "user_create", "user_update", "user_disable", "user_enable", "password_change",
    "role_change", "host_create", "host_update", "host_disable", "host_enable",
    "login_success", "login_failed", "job_create", "job_cancel", "settings_update",
]


def _seed_audit_logs(state: SimulationState, users_dict: dict[str, User], count: int = 150) -> None:
    """Seed realistic audit log entries."""
    users = list(users_dict.values())
    admin_users = [u for u in users if u.role == UserRole.ADMIN]
    manager_users = [u for u in users if u.role == UserRole.MANAGER]
    hosts = list(state.hosts.values())
    
    entries: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    
    for i in range(count):
        days_ago = random.randint(0, 30)
        hours_ago = random.randint(0, 23)
        minutes_ago = random.randint(0, 59)
        timestamp = now - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
        
        action = random.choice(AUDIT_ACTIONS)
        audit_id = str(uuid.uuid4())
        
        actor = random.choice(admin_users + manager_users) if (admin_users or manager_users) else random.choice(users)
        target_user_id = None
        detail = f"Action: {action}"
        context = None
        
        if action in ("user_create", "user_update", "user_disable", "user_enable"):
            target = random.choice(users)
            target_user_id = target.user_id
            detail = f"{action.replace('_', ' ').title()} for {target.username}"
        elif action in ("login_success", "login_failed"):
            actor = random.choice(users)
            detail = f"Login {'successful' if action == 'login_success' else 'failed'}"
        elif action in ("job_create", "job_cancel"):
            actor = random.choice(users)
            detail = f"{action.replace('_', ' ').title()} for customer"
        
        entry = {
            "audit_id": audit_id,
            "actor_user_id": actor.user_id,
            "target_user_id": target_user_id,
            "action": action,
            "detail": detail,
            "context_json": json.dumps(context) if context else None,
            "created_at": timestamp,
        }
        entries.append(entry)
    
    entries.sort(key=lambda x: x["created_at"])
    
    with state.lock:
        state.audit_logs.extend(entries)


def _seed_screenshot_jobs(state: SimulationState, users: dict[str, User]) -> list[Job]:
    """Seed specific job states for UI screenshot capture."""
    jobs: list[Job] = []
    now = datetime.now(UTC)
    
    devuser = users.get("usr-001")
    devadmin = users.get("usr-002")
    
    if not devuser or not devadmin:
        return jobs
    
    with state.lock:
        # Job 1: 67% progress
        job_67_id = "screenshot-67pct-0001"
        job_67 = Job(
            id=job_67_id,
            owner_user_id=devuser.user_id,
            owner_username=devuser.username,
            owner_user_code=devuser.user_code,
            target=f"{devuser.user_code}acmehvac",
            staging_name=f"{devuser.user_code}acmehvac_screenshot67p",
            dbhost="mysql-staging-01.example.com",
            status=JobStatus.RUNNING,
            submitted_at=now - timedelta(hours=2),
            started_at=now - timedelta(hours=1, minutes=45),
            worker_id="worker-alpha",
            current_operation="Restoring database (67% complete)",
            options_json={"customer": "acmehvac", "backup_env": "prd"},
        )
        state.jobs[job_67_id] = job_67
        jobs.append(job_67)
        
        # Job 2: CANCELING
        job_cancel_id = "screenshot-canceling-0002"
        job_cancel = Job(
            id=job_cancel_id,
            owner_user_id=devuser.user_id,
            owner_username=devuser.username,
            owner_user_code=devuser.user_code,
            target=f"{devuser.user_code}techcorp",
            staging_name=f"{devuser.user_code}techcorp_screenshotcancel",
            dbhost="mysql-staging-02.example.com",
            status=JobStatus.CANCELING,
            submitted_at=now - timedelta(hours=1),
            started_at=now - timedelta(minutes=45),
            worker_id="worker-beta",
            current_operation="Cancellation requested",
            cancel_requested_at=now - timedelta(minutes=2),
            can_cancel=False,
            options_json={"customer": "techcorp", "backup_env": "prd"},
        )
        state.jobs[job_cancel_id] = job_cancel
        jobs.append(job_cancel)
        state.cancellation_requested.add(job_cancel_id)
        
        # Job 3: FAILED
        job_failed_id = "screenshot-failed-0003"
        job_failed = Job(
            id=job_failed_id,
            owner_user_id=devuser.user_id,
            owner_username=devuser.username,
            owner_user_code=devuser.user_code,
            target=f"{devuser.user_code}globalretail",
            staging_name=f"{devuser.user_code}globalretail_screenshotfail",
            dbhost="mysql-staging-01.example.com",
            status=JobStatus.FAILED,
            submitted_at=now - timedelta(hours=3),
            started_at=now - timedelta(hours=2, minutes=50),
            completed_at=now - timedelta(hours=2),
            worker_id="worker-gamma",
            error_detail="ERROR 1045 (28000): Access denied for user 'pulldb_stg'@'10.40.10.50'",
            options_json={"customer": "globalretail", "backup_env": "prd"},
        )
        state.jobs[job_failed_id] = job_failed
        jobs.append(job_failed)
        
        # Job 4: QUEUED
        job_queued_id = "screenshot-queued-0005"
        job_queued = Job(
            id=job_queued_id,
            owner_user_id=devuser.user_id,
            owner_username=devuser.username,
            owner_user_code=devuser.user_code,
            target=f"{devuser.user_code}medisys",
            staging_name=f"{devuser.user_code}medisys_screenshotqueue",
            dbhost="mysql-staging-01.example.com",
            status=JobStatus.QUEUED,
            submitted_at=now - timedelta(minutes=15),
            current_operation="Position #3 in queue",
            options_json={"customer": "medisys", "backup_env": "prd"},
        )
        state.jobs[job_queued_id] = job_queued
        jobs.append(job_queued)
    
    return jobs


# =============================================================================
# MAIN SCENARIO SEEDING FUNCTION
# =============================================================================

def seed_dev_scenario(state: SimulationState, scenario: str = "minimal") -> None:
    """Seed SimulationState for a specific development scenario.
    
    This is the main entry point for seeding. It reads the scenario configuration
    from SCENARIOS and applies the appropriate seeding functions.
    
    Args:
        state: SimulationState to populate (should be cleared first).
        scenario: Scenario name to seed.
    """
    from dataclasses import replace
    
    config = SCENARIOS.get(scenario)
    if not config:
        raise ValueError(f"Unknown scenario: {scenario}. Available: {list(SCENARIOS.keys())}")
    
    # Seed base infrastructure
    users = _seed_users(state, config.users)
    _seed_hosts(state, config.hosts)
    _seed_user_host_assignments(state, config.hosts)
    _seed_settings(state, config.users)
    
    # Seed optional features
    if config.include_orphans:
        _seed_orphan_databases(state)
    
    if config.include_audit_logs:
        _seed_audit_logs(state, users)
    
    if config.include_api_keys:
        _seed_api_keys(state)
    
    if config.include_disallowed_users:
        _seed_disallowed_usernames(state)
    
    if config.include_host_errors:
        _seed_host_credential_errors(state)
    
    # Seed jobs
    if config.active_jobs > 0:
        _seed_active_jobs(state, config.active_jobs, users, config.respect_job_limits)
    
    if config.history_jobs > 0:
        _seed_history_jobs(state, config.history_jobs, users)
    
    if config.custom_target_jobs > 0:
        _seed_custom_target_jobs(state, config.custom_target_jobs, users)
    
    if config.include_screenshot_jobs:
        _seed_screenshot_jobs(state, users)
    
    # Apply job status overrides
    if config.force_all_queued or config.force_all_running or config.force_all_failed:
        with state.lock:
            for job_id, job in list(state.jobs.items()):
                if config.force_all_queued and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    state.jobs[job_id] = replace(
                        job,
                        status=JobStatus.QUEUED,
                        current_operation="Waiting in queue",
                        worker_id=None,
                    )
                elif config.force_all_running and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    state.jobs[job_id] = replace(
                        job,
                        status=JobStatus.RUNNING,
                        current_operation="Restoring database",
                        worker_id=job.worker_id or random.choice(WORKERS),
                    )
                elif config.force_all_failed and job.status in (JobStatus.DEPLOYED, JobStatus.COMPLETE, JobStatus.FAILED):
                    state.jobs[job_id] = replace(
                        job,
                        status=JobStatus.FAILED,
                        error_detail="Connection timeout during restore",
                    )


def reset_and_seed(scenario: str = "minimal") -> None:
    """Reset simulation state and seed with specified scenario.
    
    Convenience function that:
    1. Resets all simulation state
    2. Seeds with the specified scenario
    
    Args:
        scenario: Scenario name to seed after reset.
    """
    from pulldb.simulation.core.state import get_simulation_state, reset_simulation
    
    reset_simulation()
    state = get_simulation_state()
    seed_dev_scenario(state, scenario)


# =============================================================================
# LEGACY COMPATIBILITY - Keep these for backwards compatibility
# =============================================================================

# Re-export for backward compatibility with imports
def seed_dev_users(state: SimulationState) -> dict[str, User]:
    """Legacy: Seed standard development users."""
    return _seed_users(state, "standard")


def seed_dev_hosts(state: SimulationState) -> list[DBHost]:
    """Legacy: Seed standard development hosts."""
    return _seed_hosts(state, "standard")


def seed_dev_settings(state: SimulationState) -> None:
    """Legacy: Seed standard development settings."""
    _seed_settings(state, "standard")


def seed_user_host_assignments(state: SimulationState) -> None:
    """Legacy: Seed standard user-host assignments."""
    _seed_user_host_assignments(state, "standard")


def seed_active_jobs(state: SimulationState, count: int, users: dict[str, User] | None = None, respect_limits: bool = True) -> list[Job]:
    """Legacy: Seed active jobs."""
    if users is None:
        users = dict(state.users)
    return _seed_active_jobs(state, count, users, respect_limits)


def seed_history_jobs(state: SimulationState, count: int, users: dict[str, User] | None = None) -> list[Job]:
    """Legacy: Seed history jobs."""
    if users is None:
        users = dict(state.users)
    return _seed_history_jobs(state, count, users)


def seed_custom_target_jobs(state: SimulationState, count: int = 3, users: dict[str, User] | None = None) -> list[Job]:
    """Legacy: Seed custom target jobs."""
    if users is None:
        users = dict(state.users)
    return _seed_custom_target_jobs(state, count, users)


def seed_orphan_databases(state: SimulationState) -> None:
    """Legacy: Seed orphan databases."""
    _seed_orphan_databases(state)


def seed_api_keys(state: SimulationState) -> None:
    """Legacy: Seed API keys."""
    _seed_api_keys(state)


def seed_disallowed_usernames(state: SimulationState) -> None:
    """Legacy: Seed disallowed usernames."""
    _seed_disallowed_usernames(state)


def seed_host_credential_errors(state: SimulationState) -> None:
    """Legacy: Seed host credential errors."""
    _seed_host_credential_errors(state)


def seed_audit_logs(state: SimulationState, users_dict: dict[str, User], count: int = 150) -> None:
    """Legacy: Seed audit logs."""
    _seed_audit_logs(state, users_dict, count)


def seed_screenshot_jobs(state: SimulationState, users: dict[str, User]) -> list[Job]:
    """Legacy: Seed screenshot jobs."""
    return _seed_screenshot_jobs(state, users)


# Legacy lean seeding functions
def seed_lean_users(state: SimulationState) -> dict[str, User]:
    """Legacy: Seed lean users."""
    return _seed_users(state, "lean")


def seed_lean_host(state: SimulationState) -> DBHost | None:
    """Legacy: Seed lean host."""
    hosts = _seed_hosts(state, "lean")
    return hosts[0] if hosts else None


def seed_lean_settings(state: SimulationState) -> None:
    """Legacy: Seed lean settings."""
    _seed_settings(state, "lean")
