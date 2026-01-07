"""Data seeding for Simulation Mode.

Provides functions to populate SimulationState with realistic test data
for development, testing, and demo scenarios.

HCA Layer: shared (simulation infrastructure)
"""

from __future__ import annotations

import json
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

    # (user_id, username, user_code, role, manager_id, allowed_hosts, disabled_at, locked_at)
    # Extended user data structure to support additional fixture states
    users_data: list[tuple[str, str, str, UserRole, str | None, list[str] | None, datetime | None, datetime | None]] = [
        ("usr-001", "devuser", "devusr", UserRole.USER, "usr-003", dev_hosts, None, None),  # Managed by devmanager
        ("usr-002", "devadmin", "devadm", UserRole.ADMIN, None, None, None, None),  # Admin gets all implicitly
        ("usr-003", "devmanager", "devmgr", UserRole.MANAGER, "usr-002", dev_hosts, None, None),
        # Phase 0.5: Additional users for screenshot capture
        ("usr-004", "disableduser", "disusr", UserRole.USER, "usr-003", dev_hosts, datetime(2025, 1, 15, tzinfo=UTC), None),  # Disabled user, managed by devmanager
        ("usr-005", "resetuser", "rstusr", UserRole.USER, "usr-003", dev_hosts, None, None),  # Password reset pending, managed by devmanager
        ("usr-006", "systemaccount", "sysacc", UserRole.SERVICE, None, None, None, datetime(2024, 1, 1, tzinfo=UTC)),  # Locked system user
    ]

    created_users: dict[str, User] = {}

    with state.lock:
        for user_id, username, user_code, role, manager_id, allowed_hosts, disabled_at, locked_at in users_data:
            user = User(
                user_id=user_id,
                username=username,
                user_code=user_code,
                is_admin=(role == UserRole.ADMIN),
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

            # Seed auth credentials for login
            # Password: PullDB_Dev2025!
            # This is a valid bcrypt hash generated from hash_password('PullDB_Dev2025!')
            # Note: devadmin gets totp_secret for MFA badge screenshot
            totp_secret = "JBSWY3DPEHPK3PXP" if user_id == "usr-002" else None
            # Password reset timestamp for usr-005
            password_reset_at = datetime(2025, 1, 20, 14, 30, tzinfo=UTC) if user_id == "usr-005" else None
            
            state.auth_credentials[user_id] = {
                "password_hash": "$2b$12$uJQJWPXefk/JICbVNIt23OYvf/ul545Uk5Mb50wTuxKsvDtj6Xmr2",
                "totp_secret": totp_secret,
                "failed_attempts": 0,
                "locked_until": None,
                "password_reset_at": password_reset_at,
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
        # Phase 0.5: Host with credential error state for screenshot capture
        ("00000000-0000-0000-0000-000000000006", "mysql-broken.example.com", "broken", 2, 10, True),
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
        "broken": "00000000-0000-0000-0000-000000000006",
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
# API Keys Seeding (Phase 0.5)
# =============================================================================


def seed_api_keys(state: SimulationState) -> None:
    """Seed API keys into SimulationState for screenshot capture.
    
    Creates:
    - Approved key for devuser (normal operation)
    - Pending key (approved_at=None) for screenshot of approval queue
    - Revoked key (is_active=False) for history display
    """
    # API key data: (key_id, user_id, name, host_name, is_active, approved_at, approved_by)
    api_keys_data = [
        # Active approved key for devuser
        (
            "key_dev001abc123",
            "usr-001",
            "Development Laptop",
            "dev-laptop.local",
            True,
            datetime(2025, 1, 10, 9, 0, tzinfo=UTC),
            "usr-002",  # approved by devadmin
        ),
        # Pending key (not yet approved) - for approval queue screenshot
        (
            "key_pending999xyz",
            "usr-003",
            "New Server Key",
            "new-server.internal",
            False,  # Pending keys are inactive
            None,   # Not approved yet
            None,
        ),
        # Another pending key for approval queue screenshot
        (
            "key_pending888abc",
            "usr-001",
            "CI Pipeline Key",
            "jenkins.internal",
            False,
            None,
            None,
        ),
        # Revoked key (was approved, then deactivated)
        (
            "key_revoked777def",
            "usr-001",
            "Old Laptop",
            "old-laptop.local",
            False,  # Revoked
            datetime(2024, 6, 15, 14, 30, tzinfo=UTC),
            "usr-002",
        ),
    ]

    with state.lock:
        for key_id, user_id, name, host_name, is_active, approved_at, approved_by in api_keys_data:
            state.api_keys[key_id] = {
                "key_id": key_id,
                "user_id": user_id,
                "key_secret_hash": "$2b$12$MockKeyHashForSimulationOnlyDontUseInProduction",
                "key_secret": "sim_secret_" + key_id[-8:],  # Mock secret for simulation
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


# =============================================================================
# Disallowed Usernames Seeding (Phase 0.5)
# =============================================================================


def seed_disallowed_usernames(state: SimulationState) -> None:
    """Seed disallowed usernames into SimulationState for screenshot capture.
    
    Creates a mix of:
    - Hardcoded system accounts (is_hardcoded=True, cannot be removed)
    - Admin-added blocked usernames (is_hardcoded=False, can be removed)
    """
    # (username, reason, is_hardcoded, created_by)
    disallowed_data = [
        # Hardcoded system accounts
        ("root", "System administrator account", True, None),
        ("daemon", "System daemon account", True, None),
        ("mysql", "MySQL service account", True, None),
        ("nobody", "Unprivileged user", True, None),
        ("admin", "Reserved administrative username", True, None),
        ("pulldb", "PullDB service account", True, None),
        # Admin-added entries (for UI testing of remove capability)
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


# =============================================================================
# Host Credential Error Seeding (Phase 0.5)
# =============================================================================


def seed_host_credential_errors(state: SimulationState) -> None:
    """Seed host credential error states for screenshot capture.
    
    Marks the 'broken' host as having credential verification failures.
    """
    with state.lock:
        # The 'broken' host has credential issues
        state.host_credential_errors["mysql-broken.example.com"] = (
            "Access denied for user 'pulldb_stg'@'10.40.10.50' (using password: YES)"
        )


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

    # Status distribution: 80% deployed (active DBs), 20% failed
    statuses = [JobStatus.DEPLOYED] * 4 + [JobStatus.FAILED]

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
        JobStatus.DEPLOYED,
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
            # Add download progress event (simulating partial download)
            download_progress = random.randint(30, 80)  # 30-80% complete
            total_bytes = random.randint(500_000_000, 5_000_000_000)  # 500MB - 5GB
            downloaded_bytes = int(total_bytes * download_progress / 100)
            elapsed_seconds = random.randint(60, 600)  # 1-10 minutes
            progress_detail = json.dumps({
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": total_bytes,
                "percent_complete": float(download_progress),
                "elapsed_seconds": elapsed_seconds,
            })
            progress_time = dl_time + timedelta(seconds=random.randint(30, 180))
            events.append(
                _create_event(
                    event_id,
                    job.id,
                    "download_progress",
                    progress_detail,
                    logged_at=progress_time,
                )
            )
            event_id += 1

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

            # Add restore progress event for some jobs (50% chance)
            if random.random() > 0.5:
                restore_percent = random.randint(10, 60)  # 10-60% complete
                active_threads = random.randint(2, 8)
                # Generate per-table progress simulating processlist data
                table_names = ["users", "orders", "products", "schema", "inventory", "sessions", "logs"]
                tables_progress = {}
                for table in random.sample(table_names, min(active_threads, len(table_names))):
                    tables_progress[table] = {
                        "percent_complete": random.randint(5, 95),
                    }
                
                restore_detail = json.dumps({
                    "percent": float(restore_percent),
                    "active_threads": active_threads,
                    "tables": tables_progress,
                    "detail": {
                        "file": random.choice(["users.sql", "orders.sql", "products.sql", "schema.sql"]),
                        "status": "loading",
                    }
                })
                restore_progress_time = restore_time + timedelta(seconds=random.randint(30, 300))
                events.append(
                    _create_event(
                        event_id,
                        job.id,
                        "restore_progress",
                        restore_detail,
                        logged_at=restore_progress_time,
                    )
                )
                event_id += 1

        elif job.status in (JobStatus.DEPLOYED, JobStatus.COMPLETE):
            # Full event sequence for deployed/completed jobs
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
# Screenshot-Specific Job Seeding (Phase 0.5)
# =============================================================================


def seed_screenshot_jobs(state: SimulationState, users: dict[str, User]) -> list[Job]:
    """Seed specific job states for UI screenshot capture.
    
    Creates deterministic jobs in various states needed for documentation:
    - Job at 67% progress with rich log content
    - Job in CANCELING state
    - Job in FAILED state with error message
    - Job in DELETING state
    - Job in QUEUED state with queue position
    - Job in DOWNLOADING phase with progress data
    - Job in RESTORING phase with table progress
    
    Args:
        state: SimulationState to populate.
        users: Dictionary of users for ownership.
        
    Returns:
        List of created Job objects.
    """
    from dataclasses import replace
    
    jobs: list[Job] = []
    now = datetime.now(UTC)
    
    # Helper to get a user tuple from user dict
    devuser = users.get("usr-001")
    devadmin = users.get("usr-002")
    
    if not devuser or not devadmin:
        # Fallback if users not found
        return jobs
    
    with state.lock:
        # =====================================================================
        # Job 1: 67% progress with rich log content (RUNNING, restoring phase)
        # =====================================================================
        job_67_id = "screenshot-67pct-0001"
        job_67_submitted = now - timedelta(hours=2)
        job_67_started = now - timedelta(hours=1, minutes=45)
        job_67 = Job(
            id=job_67_id,
            owner_user_id=devuser.user_id,
            owner_username=devuser.username,
            owner_user_code=devuser.user_code,
            target=f"{devuser.user_code}acmehvac",
            staging_name=f"{devuser.user_code}acmehvac_screenshot67p",
            dbhost="mysql-staging-01.example.com",
            status=JobStatus.RUNNING,
            submitted_at=job_67_submitted,
            started_at=job_67_started,
            worker_id="worker-alpha",
            current_operation="Restoring database (67% complete)",
            options_json={
                "customer": "acmehvac",
                "backup_env": "prd",
                "s3_key": "s3://pulldb-backups/prd/acmehvac/latest.xbstream.zst",
            },
        )
        state.jobs[job_67_id] = job_67
        jobs.append(job_67)
        
        # Add rich event history for this job
        event_base_id = len(state.job_events) + 1
        state.job_events.extend([
            JobEvent(id=event_base_id, job_id=job_67_id, event_type="created", 
                    detail="Job queued", logged_at=job_67_submitted),
            JobEvent(id=event_base_id + 1, job_id=job_67_id, event_type="claimed",
                    detail="Claimed by worker-alpha", logged_at=job_67_started),
            JobEvent(id=event_base_id + 2, job_id=job_67_id, event_type="downloading",
                    detail="Downloading backup from S3...", logged_at=job_67_started + timedelta(seconds=5)),
            JobEvent(id=event_base_id + 3, job_id=job_67_id, event_type="download_progress",
                    detail=json.dumps({
                        "downloaded_bytes": 2147483648,  # 2GB
                        "total_bytes": 3221225472,  # 3GB
                        "percent_complete": 66.7,
                        "elapsed_seconds": 420,
                    }), logged_at=job_67_started + timedelta(minutes=7)),
            JobEvent(id=event_base_id + 4, job_id=job_67_id, event_type="downloaded",
                    detail="Download complete (3.0 GB in 8m 32s)", 
                    logged_at=job_67_started + timedelta(minutes=8, seconds=32)),
            JobEvent(id=event_base_id + 5, job_id=job_67_id, event_type="restoring",
                    detail="Running myloader restore...", 
                    logged_at=job_67_started + timedelta(minutes=9)),
            JobEvent(id=event_base_id + 6, job_id=job_67_id, event_type="restore_progress",
                    detail=json.dumps({
                        "percent": 67.0,
                        "active_threads": 4,
                        "tables_completed": 45,
                        "tables_total": 67,
                        "tables": {
                            "customers": {"percent_complete": 100},
                            "orders": {"percent_complete": 85},
                            "products": {"percent_complete": 72},
                            "inventory": {"percent_complete": 45},
                        },
                        "detail": {"file": "orders.sql", "status": "loading"},
                    }), logged_at=now - timedelta(minutes=5)),
        ])
        
        # =====================================================================
        # Job 2: CANCELING state
        # =====================================================================
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
            current_operation="Cancellation requested - stopping at checkpoint",
            cancel_requested_at=now - timedelta(minutes=2),
            can_cancel=False,
            options_json={
                "customer": "techcorp",
                "backup_env": "prd",
                "s3_key": "s3://pulldb-backups/prd/techcorp/latest.xbstream.zst",
            },
        )
        state.jobs[job_cancel_id] = job_cancel
        jobs.append(job_cancel)
        state.cancellation_requested.add(job_cancel_id)
        
        # =====================================================================
        # Job 3: FAILED state with detailed error
        # =====================================================================
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
            error_detail="ERROR 1045 (28000): Access denied for user 'pulldb_stg'@'10.40.10.50' to database 'devusrglobalretail_screenshotfail'. Verify that the staging user has CREATE/DROP privileges on the target host.",
            options_json={
                "customer": "globalretail",
                "backup_env": "prd",
                "s3_key": "s3://pulldb-backups/prd/globalretail/latest.xbstream.zst",
            },
        )
        state.jobs[job_failed_id] = job_failed
        jobs.append(job_failed)
        
        # =====================================================================
        # Job 4: DELETING state (async bulk delete in progress)
        # =====================================================================
        job_deleting_id = "screenshot-deleting-0004"
        job_deleting = Job(
            id=job_deleting_id,
            owner_user_id=devadmin.user_id,
            owner_username=devadmin.username,
            owner_user_code=devadmin.user_code,
            target=f"{devadmin.user_code}fastlogistics",
            staging_name=f"{devadmin.user_code}fastlogistics_screenshotdel",
            dbhost="mysql-staging-01.example.com",
            status=JobStatus.DELETING,
            submitted_at=now - timedelta(days=5),
            started_at=now - timedelta(days=5) + timedelta(minutes=5),
            completed_at=now - timedelta(days=5) + timedelta(hours=1),
            worker_id="worker-delta",
            current_operation="Dropping database...",
            options_json={
                "customer": "fastlogistics",
                "backup_env": "prd",
                "s3_key": "s3://pulldb-backups/prd/fastlogistics/latest.xbstream.zst",
            },
        )
        state.jobs[job_deleting_id] = job_deleting
        jobs.append(job_deleting)
        
        # =====================================================================
        # Job 5: QUEUED state with queue position indicator
        # =====================================================================
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
            options_json={
                "customer": "medisys",
                "backup_env": "prd",
                "s3_key": "s3://pulldb-backups/prd/medisys/latest.xbstream.zst",
            },
        )
        state.jobs[job_queued_id] = job_queued
        jobs.append(job_queued)
        
        # =====================================================================
        # Job 6: DOWNLOADING phase with progress data
        # =====================================================================
        job_download_id = "screenshot-downloading-0006"
        job_download_submitted = now - timedelta(minutes=30)
        job_download_started = now - timedelta(minutes=25)
        job_download = Job(
            id=job_download_id,
            owner_user_id=devuser.user_id,
            owner_username=devuser.username,
            owner_user_code=devuser.user_code,
            target=f"{devuser.user_code}edulearn",
            staging_name=f"{devuser.user_code}edulearn_screenshotdl",
            dbhost="mysql-staging-02.example.com",
            status=JobStatus.RUNNING,
            submitted_at=job_download_submitted,
            started_at=job_download_started,
            worker_id="worker-alpha",
            current_operation="Downloading backup (42% complete)",
            options_json={
                "customer": "edulearn",
                "backup_env": "stg",
                "s3_key": "s3://pulldb-backups/stg/edulearn/latest.xbstream.zst",
            },
        )
        state.jobs[job_download_id] = job_download
        jobs.append(job_download)
        
        # Add download progress event
        dl_event_id = len(state.job_events) + 100
        state.job_events.extend([
            JobEvent(id=dl_event_id, job_id=job_download_id, event_type="created",
                    detail="Job queued", logged_at=job_download_submitted),
            JobEvent(id=dl_event_id + 1, job_id=job_download_id, event_type="claimed",
                    detail="Claimed by worker-alpha", logged_at=job_download_started),
            JobEvent(id=dl_event_id + 2, job_id=job_download_id, event_type="downloading",
                    detail="Downloading backup from S3...", logged_at=job_download_started + timedelta(seconds=5)),
            JobEvent(id=dl_event_id + 3, job_id=job_download_id, event_type="download_progress",
                    detail=json.dumps({
                        "downloaded_bytes": 1073741824,  # 1GB
                        "total_bytes": 2576980378,  # ~2.4GB
                        "percent_complete": 41.7,
                        "elapsed_seconds": 180,
                        "speed_bytes_per_sec": 5965232,  # ~6MB/s
                    }), logged_at=now - timedelta(seconds=30)),
        ])
        
        # =====================================================================
        # Job 7: RESTORING phase with table progress
        # =====================================================================
        job_restore_id = "screenshot-restoring-0007"
        job_restore_submitted = now - timedelta(hours=1, minutes=30)
        job_restore_started = now - timedelta(hours=1, minutes=20)
        job_restore = Job(
            id=job_restore_id,
            owner_user_id=devadmin.user_id,
            owner_username=devadmin.username,
            owner_user_code=devadmin.user_code,
            target=f"{devadmin.user_code}finserve",
            staging_name=f"{devadmin.user_code}finserve_screenshotrst",
            dbhost="mysql-staging-01.example.com",
            status=JobStatus.RUNNING,
            submitted_at=job_restore_submitted,
            started_at=job_restore_started,
            worker_id="worker-beta",
            current_operation="Restoring database (23% complete)",
            options_json={
                "customer": "finserve",
                "backup_env": "prd",
                "s3_key": "s3://pulldb-backups/prd/finserve/latest.xbstream.zst",
            },
        )
        state.jobs[job_restore_id] = job_restore
        jobs.append(job_restore)
        
        # Add restore progress events
        rst_event_id = len(state.job_events) + 200
        state.job_events.extend([
            JobEvent(id=rst_event_id, job_id=job_restore_id, event_type="created",
                    detail="Job queued", logged_at=job_restore_submitted),
            JobEvent(id=rst_event_id + 1, job_id=job_restore_id, event_type="claimed",
                    detail="Claimed by worker-beta", logged_at=job_restore_started),
            JobEvent(id=rst_event_id + 2, job_id=job_restore_id, event_type="downloading",
                    detail="Downloading backup from S3...", logged_at=job_restore_started + timedelta(seconds=5)),
            JobEvent(id=rst_event_id + 3, job_id=job_restore_id, event_type="downloaded",
                    detail="Download complete (4.2 GB in 12m 45s)",
                    logged_at=job_restore_started + timedelta(minutes=12, seconds=45)),
            JobEvent(id=rst_event_id + 4, job_id=job_restore_id, event_type="restoring",
                    detail="Running myloader restore...",
                    logged_at=job_restore_started + timedelta(minutes=13)),
            JobEvent(id=rst_event_id + 5, job_id=job_restore_id, event_type="restore_progress",
                    detail=json.dumps({
                        "percent": 23.0,
                        "active_threads": 8,
                        "tables_completed": 12,
                        "tables_total": 52,
                        "tables": {
                            "accounts": {"percent_complete": 100},
                            "transactions": {"percent_complete": 67},
                            "balances": {"percent_complete": 45},
                            "audit_log": {"percent_complete": 12},
                            "statements": {"percent_complete": 5},
                        },
                        "detail": {"file": "transactions.sql", "status": "loading"},
                    }), logged_at=now - timedelta(minutes=2)),
        ])
    
    return jobs


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
    - "screenshots": Specific job states for documentation screenshots (Phase 0.5)

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
    
    # Phase 0.5: Always seed API keys, disallowed usernames, and host errors
    seed_api_keys(state)
    seed_disallowed_usernames(state)
    seed_host_credential_errors(state)

    if scenario in ("minimal", "empty"):
        # Infrastructure only - no jobs, history, logs, or staged databases
        # Users, hosts, and settings are seeded above
        pass
    
    elif scenario == "screenshots":
        # Phase 0.5: Specific job states for documentation screenshots
        seed_screenshot_jobs(state, users)
        # Also seed some history for context
        seed_history_jobs(state, 20, users)

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
                if job.status in (JobStatus.DEPLOYED, JobStatus.COMPLETE, JobStatus.FAILED):
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
