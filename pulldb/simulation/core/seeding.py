"""Data seeding for Simulation Mode.

Provides functions to populate SimulationState with realistic test data
for development, testing, and demo scenarios.

HCA Layer: shared (simulation infrastructure)
"""

from __future__ import annotations

import random
import typing as t
import uuid
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
# Constants
# =============================================================================

# Realistic test data pools
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

WORKERS = [
    "worker-alpha",
    "worker-beta",
    "worker-gamma",
    "worker-delta",
    "worker-epsilon",
]

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


# =============================================================================
# User Seeding
# =============================================================================


def seed_dev_users(state: SimulationState) -> dict[str, User]:
    """Seed development users into SimulationState.

    Creates three users with different roles for testing:
    - devuser (USER role) - standard user
    - devadmin (ADMIN role) - administrator
    - devmanager (MANAGER role) - manager

    Returns:
        Dict mapping user_id to User for reference.
    """
    # Host display names for non-admin users (admins get all hosts implicitly)
    # These must match the aliases defined in seed_dev_hosts()
    dev_hosts = [
        "staging-01",
        "staging-02",
        "staging-03",
    ]
    default_host = "staging-01"

    # (user_id, username, user_code, role, manager_id, allowed_hosts)
    users_data = [
        ("usr-001", "devuser", "devusr", UserRole.USER, None, dev_hosts),
        ("usr-002", "devadmin", "devadm", UserRole.ADMIN, None, None),  # Admin gets all implicitly
        ("usr-003", "devmanager", "devmgr", UserRole.MANAGER, "usr-002", dev_hosts),
    ]

    created_users: dict[str, User] = {}

    with state.lock:
        for user_id, username, user_code, role, manager_id, allowed_hosts in users_data:
            user = User(
                user_id=user_id,
                username=username,
                user_code=user_code,
                is_admin=(role == UserRole.ADMIN),
                role=role,
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
                manager_id=manager_id,
                disabled_at=None,
                allowed_hosts=allowed_hosts,
                default_host=default_host if allowed_hosts else None,
            )
            state.users[user_id] = user
            state.users_by_code[user_code] = user
            created_users[user_id] = user

            # Seed auth credentials for login
            # Password: PullDB_Dev2025!
            # This is a bcrypt hash - in real code we'd use bcrypt.hashpw
            state.auth_credentials[user_id] = {
                "password_hash": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.VTtYPKq3q3q3q3",
                "totp_secret": None,
                "failed_attempts": 0,
                "locked_until": None,
            }

    return created_users


# =============================================================================
# Host Seeding
# =============================================================================


def seed_dev_hosts(state: SimulationState) -> list[DBHost]:
    """Seed database hosts into SimulationState.

    Creates mock staging/prod database hosts.

    Returns:
        List of created DBHost objects.
    """
    # (id, hostname, alias, max_running, max_active, enabled)
    # Using sequential readable UUIDs for deterministic test data
    hosts_data = [
        ("00000000-0000-0000-0000-000000000001", "mysql-staging-01.example.com", "staging-01", 3, 10, True),
        ("00000000-0000-0000-0000-000000000002", "mysql-staging-02.example.com", "staging-02", 2, 10, True),
        ("00000000-0000-0000-0000-000000000003", "mysql-staging-03.example.com", "staging-03", 2, 10, True),
        ("00000000-0000-0000-0000-000000000004", "mysql-prod-01.example.com", "prod-01", 1, 5, True),
        ("00000000-0000-0000-0000-000000000005", "mysql-dev.example.com", "dev", 1, 10, False),  # Disabled
    ]

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


def seed_user_host_assignments(state: SimulationState) -> None:
    """Seed user-host assignments into state.user_hosts.

    Links non-admin users to their allowed hosts via the user_hosts mapping.
    This is required because the auth repository reads from state.user_hosts,
    not from User.allowed_hosts directly.

    Must be called AFTER seed_dev_users() and seed_dev_hosts().
    """
    # Host ID mapping: alias -> UUID
    # Must match IDs from seed_dev_hosts()
    host_id_by_alias = {
        "staging-01": "00000000-0000-0000-0000-000000000001",
        "staging-02": "00000000-0000-0000-0000-000000000002",
        "staging-03": "00000000-0000-0000-0000-000000000003",
        "prod-01": "00000000-0000-0000-0000-000000000004",
        "dev": "00000000-0000-0000-0000-000000000005",
    }

    # User-host assignments: (user_id, host_aliases, default_host_alias)
    # Admins don't need explicit assignments - they get all hosts implicitly
    user_host_assignments = [
        ("usr-001", ["staging-01", "staging-02", "staging-03"], "staging-01"),  # devuser
        ("usr-003", ["staging-01", "staging-02", "staging-03"], "staging-01"),  # devmanager
        # usr-002 (devadmin) skipped - admins access all hosts implicitly
    ]

    with state.lock:
        for user_id, host_aliases, default_alias in user_host_assignments:
            assignments: list[dict[str, t.Any]] = []
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
# Orphan Database Seeding
# =============================================================================

# Fixed UUIDs for deterministic orphan generation (first 12 hex chars used)
ORPHAN_DB_SEEDS = [
    # Orphans for staging-01: 4 databases
    ("mysql-staging-01.example.com", "devusracmehvac", "aaa111bbb222"),
    ("mysql-staging-01.example.com", "devusrtechcorp", "ccc333ddd444"),
    ("mysql-staging-01.example.com", "devadmglobalretail", "eee555fff666"),
    ("mysql-staging-01.example.com", "devmgrfastlogistics", "111222333444"),
    # Orphans for staging-02: 3 databases
    ("mysql-staging-02.example.com", "devusrmedisys", "555666777888"),
    ("mysql-staging-02.example.com", "devadmedulearn", "999aaabbbccc"),
    ("mysql-staging-02.example.com", "devusrfinserve", "dddeeefff000"),
    # staging-03: will simulate connection failure, no databases seeded
]

# Orphan database sizes (MB) for realistic display
# (hostname, target, job_prefix) -> size_mb
# Keys MUST match ORPHAN_DB_SEEDS tuples
ORPHAN_DB_SIZES: dict[tuple[str, str, str], float] = {
    ("mysql-staging-01.example.com", "devusracmehvac", "aaa111bbb222"): 245.5,
    ("mysql-staging-01.example.com", "devusrtechcorp", "ccc333ddd444"): 1024.0,
    ("mysql-staging-01.example.com", "devadmglobalretail", "eee555fff666"): 512.75,
    ("mysql-staging-01.example.com", "devmgrfastlogistics", "111222333444"): 78.25,
    ("mysql-staging-02.example.com", "devusrmedisys", "555666777888"): 2048.0,
    ("mysql-staging-02.example.com", "devadmedulearn", "999aaabbbccc"): 156.0,
    ("mysql-staging-02.example.com", "devusrfinserve", "dddeeefff000"): 892.5,
}

# Orphan metadata for those with pulldb meta table (some orphans won't have it)
# (hostname, target, job_prefix) -> metadata dict
# Only some orphans have metadata - simulates DBs created before tracking was added
ORPHAN_DB_METADATA: dict[tuple[str, str, str], dict[str, t.Any]] = {
    ("mysql-staging-01.example.com", "devusracmehvac", "aaa111bbb222"): {
        "job_id": "aaa111bbb222-7890-abcd-ef12-345678901234",
        "restored_by": "devuser",
        "restored_at": "2025-01-15T10:30:00Z",
        "target_database": "acmehvac_prd",
        "backup_filename": "acmehvac_prd_2025-01-15.tar.zst",
        "restore_duration_seconds": 342,
    },
    ("mysql-staging-01.example.com", "devusrtechcorp", "ccc333ddd444"): {
        "job_id": "ccc333ddd444-abcd-ef12-3456-78901234abcd",
        "restored_by": "devadmin",
        "restored_at": "2025-01-14T14:45:00Z",
        "target_database": "techcorp_prd",
        "backup_filename": "techcorp_prd_2025-01-14.tar.zst",
        "restore_duration_seconds": 1205,
    },
    ("mysql-staging-02.example.com", "devusrmedisys", "555666777888"): {
        "job_id": "555666777888-1234-5678-90ab-cdef12345678",
        "restored_by": "devuser",
        "restored_at": "2025-01-13T09:15:00Z",
        "target_database": "medisys_prd",
        "backup_filename": "medisys_prd_2025-01-13.tar.zst",
        "restore_duration_seconds": 2156,
    },
    # Note: Other orphans intentionally don't have metadata to simulate
    # databases that were created before pulldb meta table was implemented
}


def seed_orphan_databases(state: SimulationState) -> None:
    """Seed mock orphan databases into SimulationState.

    Creates deterministic orphan databases on staging hosts that have NO
    matching job records. These simulate databases left behind by crashes
    or bugs that require admin review.

    Note: mysql-staging-03 is intentionally NOT seeded with databases
    to simulate a connection failure scenario during orphan scanning.
    """
    with state.lock:
        # Clear any existing staging databases (reset on server restart)
        state.staging_databases.clear()
        state.deleted_orphans.clear()
        state.orphan_sizes.clear()
        state.orphan_metadata.clear()

        for hostname, target, job_prefix in ORPHAN_DB_SEEDS:
            # Format: {target}_{12-hex-chars}
            db_name = f"{target}_{job_prefix}"

            # Initialize host's database set if needed
            if hostname not in state.staging_databases:
                state.staging_databases[hostname] = set()

            state.staging_databases[hostname].add(db_name)

            # Add size for this orphan
            key = (hostname, target, job_prefix)
            if key in ORPHAN_DB_SIZES:
                state.orphan_sizes[(hostname, db_name)] = ORPHAN_DB_SIZES[key]

            # Add metadata if available (simulates pulldb meta table)
            if key in ORPHAN_DB_METADATA:
                state.orphan_metadata[(hostname, db_name)] = ORPHAN_DB_METADATA[key]


# =============================================================================
# Settings Seeding
# =============================================================================


def seed_dev_settings(state: SimulationState) -> None:
    """Seed default settings into SimulationState."""
    settings = {
        "myloader_threads": "4",
        "myloader_overwrite": "true",
        "staging_retention_days": "7",
        "job_log_retention_days": "30",
        "max_active_jobs_global": "0",  # 0 = unlimited
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
# Job Seeding
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
) -> Job:
    """Create a Job instance for seeding."""
    ts = created_at or datetime.now(UTC)

    if is_qatemplate:
        target = f"{owner_user_code}qatemplate"
    else:
        target = f"{owner_user_code}{source_customer}"

    # Generate staging name from job_id
    # For UUIDs: first 12 hex chars. For mock IDs: pad to 12 chars
    clean_id = job_id.replace("-", "").replace("job", "")
    staging_prefix = clean_id[:12].ljust(12, "0")
    staging_name = f"{target}_{staging_prefix}"

    # Store source_customer and backup_env in options_json (Job model doesn't have these as direct fields)
    options = {
        "customer": source_customer if not is_qatemplate else "qatemplate",
        "backup_env": backup_env,
        "s3_key": f"s3://pulldb-backups/{backup_env}/{source_customer}/latest.xbstream.zst",
    }
    if is_qatemplate:
        options["qatemplate"] = "true"

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


def seed_active_jobs(
    state: SimulationState,
    count: int,
    users: dict[str, User] | None = None,
    respect_limits: bool = True,
) -> list[Job]:
    """Seed active jobs (queued/running) into SimulationState.

    Args:
        state: SimulationState to populate.
        count: Number of active jobs to create.
        users: Optional dict of users to use as owners. If None, uses state.users.
        respect_limits: If True, respects max_active_jobs_per_user setting.
            If False, ignores limits (for stress testing).

    Returns:
        List of created Job objects.
    """
    if users is None:
        users = dict(state.users)

    if not users:
        raise ValueError("No users available for job ownership. Seed users first.")

    # Get max jobs per user limit from settings
    max_per_user = 0  # 0 = unlimited
    if respect_limits and "max_active_jobs_per_user" in state.settings:
        try:
            max_per_user = int(state.settings["max_active_jobs_per_user"])
        except (ValueError, TypeError):
            max_per_user = 0

    # Weighted owner selection (devuser more common)
    owner_weights = [
        ("usr-001", "devuser", "devusr", 3),  # 60%
        ("usr-002", "devadmin", "devadm", 1),  # 20%
        ("usr-003", "devmanager", "devmgr", 1),  # 20%
    ]
    owners_pool = [
        (uid, uname, ucode) for uid, uname, ucode, w in owner_weights for _ in range(w)
    ]

    # Track active jobs per user
    jobs_per_user: dict[str, int] = {}

    # Count existing active jobs per user
    with state.lock:
        for job in state.jobs.values():
            if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                jobs_per_user[job.owner_user_id] = (
                    jobs_per_user.get(job.owner_user_id, 0) + 1
                )

    jobs: list[Job] = []
    base_time = datetime.now(UTC) - timedelta(hours=12)

    with state.lock:
        for i in range(count):
            job_id = str(uuid.uuid4())

            # Select owner respecting limits
            if respect_limits and max_per_user > 0:
                # Filter owners who haven't hit limit
                available_owners = [
                    o for o in owners_pool if jobs_per_user.get(o[0], 0) < max_per_user
                ]
                if not available_owners:
                    # All users at limit - stop seeding active jobs
                    break
                owner_id, owner_username, owner_user_code = random.choice(
                    available_owners
                )
            else:
                owner_id, owner_username, owner_user_code = random.choice(owners_pool)

            # Update count
            jobs_per_user[owner_id] = jobs_per_user.get(owner_id, 0) + 1

            # Mix of statuses: ~30% queued, ~70% running
            status = JobStatus.QUEUED if random.random() < 0.3 else JobStatus.RUNNING
            customer = random.choice(CUSTOMERS)
            dbhost, _ = random.choice(DB_HOSTS)
            env = random.choice(["prd", "stg"])

            # Vary creation times across the last 12 hours
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

            # Generate events for this job
            _seed_job_events(state, job, len(state.job_events))

    return jobs


def seed_history_jobs(
    state: SimulationState,
    count: int,
    users: dict[str, User] | None = None,
) -> list[Job]:
    """Seed historical jobs (complete/failed/canceled) into SimulationState.

    Args:
        state: SimulationState to populate.
        count: Number of history jobs to create.
        users: Optional dict of users to use as owners.

    Returns:
        List of created Job objects.
    """
    if users is None:
        users = dict(state.users)

    if not users:
        raise ValueError("No users available for job ownership. Seed users first.")

    # Weighted owner selection
    owners = [
        ("usr-001", "devuser", "devusr"),
        ("usr-001", "devuser", "devusr"),
        ("usr-001", "devuser", "devusr"),
        ("usr-002", "devadmin", "devadm"),
    ]

    # Status distribution: 80% complete, 20% failed
    statuses = [JobStatus.COMPLETE] * 4 + [JobStatus.FAILED]

    jobs: list[Job] = []
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    with state.lock:
        for i in range(count):
            job_id = str(uuid.uuid4())
            status = random.choice(statuses)
            owner_id, owner_username, owner_user_code = random.choice(owners)

            # 10% chance of QA template job
            is_qatemplate = random.random() < 0.10

            # Vary timestamps - go back in time
            hours_ago = i * 2 + random.randint(0, 12)
            created_at = base_time - timedelta(hours=hours_ago)
            started_at = created_at + timedelta(minutes=random.randint(1, 10))
            duration_minutes = random.randint(5, 120)
            finished_at = started_at + timedelta(minutes=duration_minutes)

            error_detail = (
                random.choice(ERROR_MESSAGES) if status == JobStatus.FAILED else None
            )

            customer = random.choice(CUSTOMERS[:12])  # Use first 12 for history
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

            # Generate events for first 50 jobs (for performance)
            if i < 50:
                _seed_job_events(state, job, len(state.job_events))

    return jobs


def _seed_job_events(
    state: SimulationState,
    job: Job,
    base_event_id: int,
) -> None:
    """Seed events for a single job."""
    events: list[JobEvent] = []
    event_id = base_event_id + 1
    base_time = job.submitted_at

    # Created event
    events.append(
        _create_event(event_id, job.id, "created", "Job queued", logged_at=base_time)
    )
    event_id += 1

    if job.status in (
        JobStatus.RUNNING,
        JobStatus.COMPLETE,
        JobStatus.FAILED,
        JobStatus.CANCELED,
    ):
        # Claimed event
        claim_time = base_time + timedelta(seconds=random.randint(5, 30))
        worker = job.worker_id or random.choice(WORKERS)
        events.append(
            _create_event(
                event_id,
                job.id,
                "claimed",
                f"Claimed by {worker}",
                logged_at=claim_time,
            )
        )
        event_id += 1

        # Downloading event
        dl_time = claim_time + timedelta(seconds=random.randint(2, 10))
        events.append(
            _create_event(
                event_id,
                job.id,
                "downloading",
                "Downloading backup from S3...",
                logged_at=dl_time,
            )
        )
        event_id += 1

        if job.status == JobStatus.RUNNING:
            # Restoring event for running jobs
            restore_time = dl_time + timedelta(minutes=random.randint(5, 20))
            events.append(
                _create_event(
                    event_id,
                    job.id,
                    "restoring",
                    "Running myloader restore...",
                    logged_at=restore_time,
                )
            )
            event_id += 1

        elif job.status == JobStatus.COMPLETE:
            # Full event sequence for completed jobs
            dl_complete = dl_time + timedelta(minutes=random.randint(2, 15))
            events.append(
                _create_event(
                    event_id,
                    job.id,
                    "downloaded",
                    "Download complete",
                    logged_at=dl_complete,
                )
            )
            event_id += 1

            restore_start = dl_complete + timedelta(seconds=random.randint(5, 30))
            events.append(
                _create_event(
                    event_id,
                    job.id,
                    "restoring",
                    "Running myloader restore...",
                    logged_at=restore_start,
                )
            )
            event_id += 1

            post_time = restore_start + timedelta(minutes=random.randint(10, 45))
            events.append(
                _create_event(
                    event_id,
                    job.id,
                    "post_sql",
                    "Applying post-restore scripts...",
                    logged_at=post_time,
                )
            )
            event_id += 1

            complete_time = post_time + timedelta(minutes=random.randint(1, 5))
            events.append(
                _create_event(
                    event_id,
                    job.id,
                    "complete",
                    "Restore complete",
                    logged_at=complete_time,
                )
            )
            event_id += 1

        elif job.status == JobStatus.FAILED:
            fail_time = dl_time + timedelta(minutes=random.randint(5, 30))
            events.append(
                _create_event(
                    event_id,
                    job.id,
                    "failed",
                    job.error_detail or "Unknown error",
                    logged_at=fail_time,
                )
            )
            event_id += 1

    state.job_events.extend(events)


# =============================================================================
# Audit Log Seeding
# =============================================================================

# Audit action types matching the real system
AUDIT_ACTIONS = [
    "user_create",
    "user_update",
    "user_disable",
    "user_enable",
    "password_change",
    "role_change",
    "host_create",
    "host_update",
    "host_disable",
    "host_enable",
    "login_success",
    "login_failed",
    "job_create",
    "job_cancel",
    "settings_update",
]


def seed_audit_logs(
    state: SimulationState,
    users_dict: dict[str, User],
    count: int = 150,
) -> None:
    """Seed realistic audit log entries.

    Creates a variety of audit events spanning the past 30 days,
    including user management, host changes, logins, and job operations.

    Args:
        state: SimulationState to populate.
        users_dict: Dictionary of user_id -> User to reference as actors/targets.
        count: Number of audit entries to create (default 150).
    """
    import json

    users = list(users_dict.values())
    admin_users = [u for u in users if u.role == UserRole.ADMIN]
    manager_users = [u for u in users if u.role == UserRole.MANAGER]
    regular_users = [u for u in users if u.role == UserRole.USER]

    # Get host list for host-related actions
    hosts = list(state.hosts.values())

    entries: list[dict[str, t.Any]] = []
    now = datetime.now(UTC)

    for i in range(count):
        # Spread events across the past 30 days
        days_ago = random.randint(0, 30)
        hours_ago = random.randint(0, 23)
        minutes_ago = random.randint(0, 59)
        timestamp = now - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)

        action = random.choice(AUDIT_ACTIONS)
        audit_id = str(uuid.uuid4())

        # Select actor and target based on action type
        actor: User
        target_user_id: str | None = None
        detail: str | None = None
        context: dict[str, t.Any] | None = None

        if action in ("user_create", "user_update", "user_disable", "user_enable", "role_change"):
            # Admin/manager actions on users
            actor = random.choice(admin_users + manager_users) if (admin_users or manager_users) else random.choice(users)
            target = random.choice(users)
            target_user_id = target.user_id

            if action == "user_create":
                detail = f"Created user {target.username}"
                context = {"username": target.username, "role": target.role.value}
            elif action == "user_update":
                detail = f"Updated profile for {target.username}"
                context = {"field": random.choice(["email", "display_name", "preferences"])}
            elif action == "user_disable":
                detail = f"Disabled user {target.username}"
            elif action == "user_enable":
                detail = f"Enabled user {target.username}"
            elif action == "role_change":
                old_role = random.choice(["user", "manager", "admin"])
                new_role = random.choice(["user", "manager", "admin"])
                detail = f"Changed {target.username} role from {old_role} to {new_role}"
                context = {"old_role": old_role, "new_role": new_role}

        elif action == "password_change":
            # User changes own password or admin resets
            if random.random() < 0.7:
                actor = random.choice(users)
                target_user_id = actor.user_id
                detail = "Changed own password"
            else:
                actor = random.choice(admin_users) if admin_users else random.choice(users)
                target = random.choice(users)
                target_user_id = target.user_id
                detail = f"Reset password for {target.username}"

        elif action in ("host_create", "host_update", "host_disable", "host_enable"):
            # Host management (admin only)
            actor = random.choice(admin_users) if admin_users else random.choice(users)
            if hosts:
                host = random.choice(hosts)
                if action == "host_create":
                    detail = f"Created host {host.hostname}"
                    context = {"hostname": host.hostname, "alias": host.host_alias}
                elif action == "host_update":
                    detail = f"Updated host {host.hostname}"
                    context = {"hostname": host.hostname, "field": random.choice(["port", "max_concurrent", "alias"])}
                elif action == "host_disable":
                    detail = f"Disabled host {host.hostname}"
                    context = {"hostname": host.hostname}
                elif action == "host_enable":
                    detail = f"Enabled host {host.hostname}"
                    context = {"hostname": host.hostname}
            else:
                detail = f"{action.replace('_', ' ').title()} (no host reference)"

        elif action in ("login_success", "login_failed"):
            # Login events
            actor = random.choice(users)
            if action == "login_success":
                detail = f"Login from {random.choice(['192.168.1.', '10.0.0.', '172.16.0.'])}{random.randint(1, 254)}"
                context = {"ip": detail.split("from ")[1], "user_agent": "Mozilla/5.0"}
            else:
                detail = f"Failed login attempt for {actor.username}"
                context = {"reason": random.choice(["invalid_password", "account_disabled", "rate_limited"])}

        elif action in ("job_create", "job_cancel"):
            # Job operations
            actor = random.choice(users)
            job_id = str(uuid.uuid4())[:8]
            customer = random.choice(CUSTOMERS)
            if action == "job_create":
                detail = f"Created restore job for {customer}"
                context = {"job_id": job_id, "customer": customer}
            else:
                detail = f"Cancelled job {job_id}"
                context = {"job_id": job_id, "reason": random.choice(["user_requested", "duplicate", "invalid_backup"])}

        elif action == "settings_update":
            # System settings (admin only)
            actor = random.choice(admin_users) if admin_users else random.choice(users)
            setting = random.choice(["max_concurrent_jobs", "retention_days", "s3_bucket", "alert_threshold"])
            detail = f"Updated setting: {setting}"
            context = {"setting": setting}

        else:
            actor = random.choice(users)
            detail = f"Unknown action: {action}"

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

    # Sort by timestamp ascending so newest are last (matches real behavior)
    entries.sort(key=lambda x: x["created_at"])

    with state.lock:
        state.audit_logs.extend(entries)


# =============================================================================
# Scenario Seeding (Orchestration)
# =============================================================================


def seed_dev_scenario(
    state: SimulationState,
    scenario: str = "minimal",
) -> None:
    """Seed SimulationState for a specific development scenario.

    Available scenarios:
    - "minimal": Infrastructure only (users, hosts, settings) - no jobs
    - "empty": Alias for minimal (no jobs)
    - "dev_mocks": Large dataset for stress testing (400 active, 400 history jobs)
    - "busy": Many concurrent running jobs (15 active, 100 history)
    - "all_failed": Multiple failed jobs for error testing
    - "queue_backlog": Many jobs waiting in queue

    Args:
        state: SimulationState to populate (should be cleared first).
        scenario: Scenario name to seed.
    """
    from dataclasses import replace

    # Always seed base data (users, hosts, settings)
    users = seed_dev_users(state)
    seed_dev_hosts(state)
    seed_user_host_assignments(state)  # Link users to their allowed hosts
    seed_dev_settings(state)
    
    # Always seed orphan databases for admin maintenance testing
    seed_orphan_databases(state)
    
    # Always seed audit logs for audit page testing
    seed_audit_logs(state, users)

    if scenario in ("minimal", "empty"):
        # Infrastructure only - no jobs, history, logs, or staged databases
        # Users, hosts, and settings are seeded above
        pass

    elif scenario == "busy":
        # Many concurrent running jobs
        jobs = seed_active_jobs(state, 15, users)
        # Make most jobs running
        with state.lock:
            for job_id, job in state.jobs.items():
                if job.status == JobStatus.QUEUED:
                    state.jobs[job_id] = replace(
                        job,
                        status=JobStatus.RUNNING,
                        current_operation="Restoring database",
                        worker_id=random.choice(WORKERS),
                    )
        seed_history_jobs(state, 100, users)

    elif scenario == "all_failed":
        # All history jobs failed
        seed_history_jobs(state, 20, users)
        with state.lock:
            for job_id, job in state.jobs.items():
                if job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
                    state.jobs[job_id] = replace(
                        job,
                        status=JobStatus.FAILED,
                        error_detail="Connection timeout during restore",
                    )

    elif scenario == "queue_backlog":
        # Many jobs waiting in queue
        jobs = seed_active_jobs(state, 25, users)
        with state.lock:
            queued_count = 0
            for job_id, job in state.jobs.items():
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    if queued_count < 20:
                        state.jobs[job_id] = replace(
                            job,
                            status=JobStatus.QUEUED,
                            current_operation="Waiting in queue",
                            worker_id=None,
                        )
                        queued_count += 1
                    else:
                        state.jobs[job_id] = replace(
                            job,
                            status=JobStatus.RUNNING,
                            current_operation="Restoring database",
                        )
        seed_history_jobs(state, 50, users)

    else:
        # Default: dev_mocks - large dataset for LazyTable testing
        # Use respect_limits=False for stress testing purposes
        seed_active_jobs(state, 400, users, respect_limits=False)
        seed_history_jobs(state, 400, users)


def reset_and_seed(scenario: str = "minimal") -> None:
    """Reset simulation state and seed with specified scenario.

    Convenience function that:
    1. Resets all simulation state
    2. Seeds with the specified scenario

    Args:
        scenario: Scenario name to seed after reset. Defaults to "minimal".
    """
    from pulldb.simulation.core.state import get_simulation_state, reset_simulation

    reset_simulation()
    state = get_simulation_state()
    seed_dev_scenario(state, scenario)
