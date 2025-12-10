#!/usr/bin/env python3
"""Development server with mocked data.

Run this to start the web UI without needing a real MySQL database.
Uses the same mock infrastructure as the Playwright e2e tests.
"""

from __future__ import annotations

import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import uvicorn
from fastapi import FastAPI, Request

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pulldb.domain.models import UserRole, JobStatus, User, Job, JobEvent


# =============================================================================
# Mock Data Factories
# =============================================================================


def create_mock_user(
    user_id: str = "usr-001",
    username: str = "testuser",
    role: UserRole = UserRole.USER,
    disabled: bool = False,
    user_code: str | None = None,
    created_at: datetime | None = None,
    manager_id: str | None = None,
    allowed_hosts: list[str] | None = None,
    default_host: str | None = None,
) -> User:
    """Create a User dataclass instance for dev/testing.
    
    Returns a real User dataclass (frozen) to match production behavior.
    Uses short string IDs (e.g., 'usr-001') for readability.
    """
    return User(
        user_id=user_id,
        username=username,
        user_code=user_code or f"u{user_id[-3:]}",
        is_admin=role == UserRole.ADMIN,
        role=role,
        created_at=created_at or datetime(2024, 1, 1, tzinfo=UTC),
        manager_id=manager_id,
        disabled_at=datetime(2024, 1, 1, tzinfo=UTC) if disabled else None,
        allowed_hosts=allowed_hosts,
        default_host=default_host,
    )


def create_mock_job(
    job_id: str = "job-001",
    source_customer: str = "acmehvac",
    status: str = "queued",
    owner_user_id: str = "usr-001",
    owner_username: str = "devuser",
    owner_user_code: str = "devusr",
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_detail: str | None = None,
    worker_id: str | None = None,
    backup_env: str = "prd",
    is_qatemplate: bool = False,
    dbhost: str = "mysql-staging-01.example.com",
    staging_name: str | None = None,
) -> Job:
    """Create a Job dataclass instance for dev/testing.
    
    Returns a real Job dataclass (frozen) to match production behavior.
    Uses short string IDs (e.g., 'job-001', 'usr-001') for readability.
    
    Args:
        staging_name: Override staging name. If None, generates from target + job_id.
                      For mock jobs with non-UUID job_ids, pass explicit staging_name
                      or use UUID job_ids to match production behavior.
    """
    
    ts = created_at or datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    
    if is_qatemplate:
        target = f"{owner_user_code}qatemplate"
    else:
        target = f"{owner_user_code}{source_customer}"
    
    # Generate staging name if not provided
    # For mock job_ids like "job-001", this produces "001000000000" which is valid hex
    # For real UUIDs, this produces proper 12-char hex prefix
    if staging_name is None:
        # Strip common mock prefixes and hyphens, take first 12 chars, pad with 0
        job_clean = job_id.replace("job-", "").replace("-", "").lower()
        job_hex = job_clean[:12].ljust(12, "0")
        staging_name = f"{target}_{job_hex}"
    
    # Convert string status to JobStatus enum
    status_enum = JobStatus(status)
    
    return Job(
        id=job_id,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        owner_user_code=owner_user_code,
        target=target,
        staging_name=staging_name,
        dbhost=dbhost,
        status=status_enum,
        submitted_at=ts,
        started_at=started_at,
        completed_at=finished_at,
        options_json={"customer": source_customer} if not is_qatemplate else {"qatemplate": "true"},
        retry_count=0,
        error_detail=error_detail,
        worker_id=worker_id,
        current_operation="Waiting in queue" if status_enum == JobStatus.QUEUED else None,
    )


def create_mock_event(
    event_id: int = 1,
    job_id: str = "job-001",
    event_type: str = "created",
    message: str = "Job created",
    created_at: datetime | None = None,
) -> JobEvent:
    """Create a JobEvent dataclass instance for dev/testing.
    
    Returns a real JobEvent dataclass (frozen) to match production behavior.
    Field names match the real model: id, job_id, event_type, detail, logged_at.
    """
    return JobEvent(
        id=event_id,
        job_id=job_id,
        event_type=event_type,
        detail=message,
        logged_at=created_at or datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )


# =============================================================================
# Mock Repositories
# =============================================================================


class MockUserRepo:
    """Mock user repository."""

    def __init__(self) -> None:
        # user_code must be 6 lowercase letters only (a-z)
        # Manager relationships: devmanager (user_id="usr-003") manages devuser and alice
        # Host assignments:
        # - ADMIN: all hosts
        # - MANAGER: subset of hosts (staging-01, staging-02)
        # - USER: random subset of manager's hosts
        all_hosts = [
            "mysql-staging-01.example.com",
            "mysql-staging-02.example.com",
            "mysql-staging-03.example.com",
            "mysql-prod-01.example.com",
        ]
        manager_hosts = ["mysql-staging-01.example.com", "mysql-staging-02.example.com"]
        
        # Create base User objects (frozen)
        self._users = {
            "devuser": create_mock_user(
                user_id="usr-001", username="devuser", role=UserRole.USER,
                user_code="devusr", manager_id="usr-003",
                allowed_hosts=["mysql-staging-01.example.com"],
                default_host="mysql-staging-01.example.com"
            ),
            "devadmin": create_mock_user(
                user_id="usr-002", username="devadmin", role=UserRole.ADMIN,
                user_code="devadm", allowed_hosts=all_hosts,
                default_host="mysql-staging-01.example.com"
            ),
            "devmanager": create_mock_user(
                user_id="usr-003", username="devmanager", role=UserRole.MANAGER,
                user_code="devmgr", allowed_hosts=manager_hosts,
                default_host="mysql-staging-01.example.com"
            ),
            "alice": create_mock_user(
                user_id="usr-004", username="alice", role=UserRole.USER,
                user_code="aliceu", created_at=datetime(2023, 6, 15, tzinfo=UTC),
                manager_id="usr-003", allowed_hosts=["mysql-staging-02.example.com"],
                default_host="mysql-staging-02.example.com"
            ),
            "bob": create_mock_user(
                user_id="usr-005", username="bob", role=UserRole.USER,
                disabled=True, user_code="bobuse",
                created_at=datetime(2023, 3, 10, tzinfo=UTC),
                allowed_hosts=[],  # Disabled user has no hosts
                default_host=None
            ),
        }
        # Job stats stored separately (User is frozen)
        self._user_stats: dict[str, dict[str, int]] = {
            "usr-001": {"active_jobs": 2, "total_jobs": 15},
            "usr-002": {"active_jobs": 1, "total_jobs": 8},
            "usr-003": {"active_jobs": 0, "total_jobs": 3},
            "usr-004": {"active_jobs": 0, "total_jobs": 0},
            "usr-005": {"active_jobs": 0, "total_jobs": 0},
        }
    
    @property
    def users(self) -> dict[str, User]:
        """Access users dict for backward compatibility."""
        return self._users

    def get_user_by_username(self, username: str) -> User | None:
        # Case-insensitive lookup
        for u in self._users.values():
            if u.username.lower() == username.lower():
                return u
        return None

    def get_user_by_id(self, user_id: str) -> User | None:
        for user in self._users.values():
            if user.user_id == user_id:
                return user
        return None

    def list_users(self) -> list[User]:
        """Return all users."""
        return list(self._users.values())

    def enable_user(self, user_id: str) -> None:
        """Enable a user account."""
        from dataclasses import replace
        for username, user in self._users.items():
            if user.user_id == user_id:
                self._users[username] = replace(user, disabled_at=None)
                break

    def disable_user(self, user_id: str) -> None:
        """Disable a user account."""
        from dataclasses import replace
        for username, user in self._users.items():
            if user.user_id == user_id:
                self._users[username] = replace(user, disabled_at=datetime.now(UTC))
                break

    def update_default_host(self, user_id: str, host: str | None) -> None:
        """Update user's default host."""
        from dataclasses import replace
        for username, user in self._users.items():
            if user.user_id == user_id:
                self._users[username] = replace(user, default_host=host)
                break

    def update_role(self, user_id: str, new_role: UserRole) -> None:
        """Update a user's role."""
        from dataclasses import replace
        for username, user in self._users.items():
            if user.user_id == user_id:
                self._users[username] = replace(
                    user, 
                    role=new_role,
                    is_admin=(new_role == UserRole.ADMIN),
                )
                break

    def get_users_managed_by(self, manager_id: str) -> list[User]:
        """Get users managed by a specific manager."""
        return [u for u in self._users.values() if getattr(u, 'manager_id', None) == manager_id]

    def get_users_with_job_counts(self) -> list[User]:
        """Get all users (for admin user selector)."""
        return list(self._users.values())

    def get_or_create_user(self, username: str) -> User:
        """Get existing user by username.
        
        For the dev server, we only return existing mock users.
        In production, this would create a new user if not found.
        """
        user = self.get_user_by_username(username)
        if user:
            return user
        raise ValueError(
            f"User '{username}' not found. Use a predefined dev account: "
            "devuser, devadmin, devmanager, alice, bob"
        )


class MockAuthRepo:
    """Mock auth repository."""

    def __init__(self) -> None:
        self.sessions: dict[str, str] = {}  # token -> user_id (str)
        self.password_reset_at: dict[str, datetime | None] = {}  # user_id -> reset timestamp
        # Password: "PullDB_Dev2025!" for all dev users (bcrypt hash)
        # Generated with: from pulldb.auth.password import hash_password; hash_password("PullDB_Dev2025!")
        test_hash = "$2b$12$XnisilncYSnbIvEinwVYTePMF/DMiVUwpUSv8BuOWSlPH5sRam.zG"
        self.password_hashes = {
            "usr-001": test_hash,  # devuser
            "usr-002": test_hash,  # devadmin
            "usr-003": test_hash,  # devmanager
            "usr-004": test_hash,  # alice
            "usr-005": test_hash,  # bob
        }

    def get_password_hash(self, user_id: str) -> str | None:
        return self.password_hashes.get(user_id)

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        self.password_hashes[user_id] = password_hash

    def has_password(self, user_id: str) -> bool:
        return user_id in self.password_hashes

    def mark_password_reset(self, user_id: str) -> None:
        self.password_reset_at[user_id] = datetime.now(UTC)

    def clear_password_reset(self, user_id: str) -> None:
        self.password_reset_at[user_id] = None

    def is_password_reset_required(self, user_id: str) -> bool:
        return self.password_reset_at.get(user_id) is not None

    def get_password_reset_at(self, user_id: str) -> datetime | None:
        return self.password_reset_at.get(user_id)

    def validate_session(self, token: str) -> str | None:
        return self.sessions.get(token)

    def create_session(
        self,
        user_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[int, str]:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = user_id
        return (1, token)

    def invalidate_session_by_token(self, token: str) -> bool:
        if token in self.sessions:
            del self.sessions[token]
            return True
        return False


class MockJobRepo:
    """Mock job repository with sample data."""

    def __init__(self, active_count: int | None = None, history_count: int | None = None) -> None:
        # Track cancellation requests separately (Job is frozen, can't add field)
        self._cancel_requested: dict[str, datetime] = {}
        
        # If counts specified, generate that many jobs
        if active_count is not None or history_count is not None:
            self.active_jobs = self._generate_active_jobs(active_count or 0)
            self.history_jobs = self._generate_history_jobs(history_count or 0)
        else:
            # Default: generate 400 active jobs for LazyTable testing
            self.active_jobs = self._generate_active_jobs(400)
        
            # Generate 400 fake historical jobs
            self.history_jobs = self._generate_history_jobs(400)
        
        # Combine for backward compatibility
        self.jobs = self.active_jobs + self.history_jobs[:10]
        
        # Mock events for jobs
        self.events = self._generate_events()
    
    def _generate_active_jobs(self, count: int) -> list[Job]:
        """Generate active jobs (queued/running)."""
        import random
        
        # More variety in customers for testing
        customers = [
            "acmehvac", "techcorp", "globalretail", "fastlogistics",
            "medisys", "edulearn", "finserve", "autoparts",
            "foodmart", "energyco", "buildpro", "healthnet",
            "cloudnine", "skytech", "oceanview", "mountainpeak",
            "riverflow", "sunbeam", "moonlight", "stargazer",
        ]
        workers = ["worker-alpha", "worker-beta", "worker-gamma", "worker-delta", "worker-epsilon"]
        db_hosts = [
            "mysql-staging-01.example.com",
            "mysql-staging-02.example.com", 
            "mysql-staging-03.example.com",
            "mysql-prod-01.example.com",
        ]
        # Use string IDs to match User dataclass
        owners = [
            ("usr-001", "devuser", "devusr"),
            ("usr-001", "devuser", "devusr"),
            ("usr-001", "devuser", "devusr"),
            ("usr-002", "devadmin", "devadm"),
            ("usr-003", "devmanager", "devmgr"),
        ]
        envs = ["prd", "stg"]
        
        jobs = []
        base_time = datetime.now(UTC) - timedelta(hours=12)
        
        for i in range(count):
            job_id = f"job-{i + 1:04d}"
            # Mix of statuses: ~30% queued, ~70% running
            status = "queued" if random.random() < 0.3 else "running"
            owner_id, owner_username, owner_user_code = random.choice(owners)
            customer = random.choice(customers)
            db_host = random.choice(db_hosts)
            env = random.choice(envs)
            
            # Vary creation times across the last 12 hours
            minutes_ago = random.randint(0, 720)
            created_at = base_time + timedelta(minutes=720 - minutes_ago)
            
            job = create_mock_job(
                job_id=job_id,
                source_customer=customer,
                status=status,
                owner_user_id=owner_id,
                owner_username=owner_username,
                owner_user_code=owner_user_code,
                created_at=created_at,
                started_at=created_at + timedelta(minutes=random.randint(1, 5)) if status == "running" else None,
                worker_id=random.choice(workers) if status == "running" else None,
                backup_env=env,
                dbhost=db_host,
            )
            jobs.append(job)
        
        return jobs

    def _generate_history_jobs(self, count: int) -> list[Job]:
        """Generate fake historical job entries."""
        import random
        
        # Source customers (the actual customer names from S3 backups)
        customers = [
            "acmehvac", "techcorp", "globalretail", "fastlogistics",
            "medisys", "edulearn", "finserve", "autoparts",
            "foodmart", "energyco", "buildpro", "healthnet",
        ]
        statuses = ["complete", "complete", "complete", "complete", "failed"]  # 80% complete, 20% failed
        workers = ["worker-alpha", "worker-beta", "worker-gamma", "worker-delta"]
        # Use string IDs with (user_id, username, user_code) tuples
        owners = [
            ("usr-001", "devuser", "devusr"),
            ("usr-001", "devuser", "devusr"),
            ("usr-001", "devuser", "devusr"),
            ("usr-002", "devadmin", "devadm"),
        ]
        error_messages = [
            "S3 download timeout after 300s",
            "MySQL connection refused",
            "Disk space exhausted",
            "myloader process killed by OOM",
            "Invalid backup format detected",
        ]
        envs = ["prd", "stg"]
        
        jobs = []
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        
        for i in range(count):
            job_id = f"job-{i + 100:04d}"
            status = random.choice(statuses)
            owner_id, owner_username, owner_user_code = random.choice(owners)
            worker = random.choice(workers)
            
            # 10% chance of being a QA template job
            is_qatemplate = random.random() < 0.10
            
            # Vary the timestamps - go back in time
            hours_ago = i * 2 + random.randint(0, 12)
            created_at = datetime(
                2024, 1, 15, 10, 0, 0, tzinfo=UTC
            ) - __import__('datetime').timedelta(hours=hours_ago)
            started_at = created_at + __import__('datetime').timedelta(minutes=random.randint(1, 10))
            duration_minutes = random.randint(5, 120)
            finished_at = started_at + __import__('datetime').timedelta(minutes=duration_minutes)
            
            error_detail = random.choice(error_messages) if status == "failed" else None
            
            if is_qatemplate:
                job = create_mock_job(
                    job_id=job_id,
                    status=status,
                    owner_user_id=owner_id,
                    owner_username=owner_username,
                    owner_user_code=owner_user_code,
                    created_at=created_at,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_detail=error_detail,
                    worker_id=worker,
                    is_qatemplate=True,
                )
            else:
                source_customer = random.choice(customers)
                backup_env = random.choice(envs)
                job = create_mock_job(
                    job_id=job_id,
                    source_customer=source_customer,
                    status=status,
                    owner_user_id=owner_id,
                    owner_username=owner_username,
                    owner_user_code=owner_user_code,
                    created_at=created_at,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_detail=error_detail,
                    worker_id=worker,
                    backup_env=backup_env,
                )
            jobs.append(job)
        
        return jobs

    def _generate_events(self) -> dict[str, list[JobEvent]]:
        """Generate mock events for all jobs."""
        import random
        
        events: dict[str, list[JobEvent]] = {}
        event_id = 1
        
        workers = ["worker-alpha", "worker-beta", "worker-gamma", "worker-delta"]
        
        # Events for active jobs
        for job in self.active_jobs:
            job_events = []
            base_time = job.submitted_at
            
            # Created event
            job_events.append(create_mock_event(
                event_id, job.id, "created", "Job queued",
                created_at=base_time
            ))
            event_id += 1
            
            if job.status in (JobStatus.RUNNING, JobStatus.COMPLETE, JobStatus.FAILED):
                # Claimed event
                claim_time = base_time + timedelta(seconds=random.randint(5, 30))
                worker = job.worker_id or random.choice(workers)
                job_events.append(create_mock_event(
                    event_id, job.id, "claimed", f"Claimed by {worker}",
                    created_at=claim_time
                ))
                event_id += 1
                
                # Downloading event
                dl_time = claim_time + timedelta(seconds=random.randint(2, 10))
                job_events.append(create_mock_event(
                    event_id, job.id, "downloading", "Downloading backup from S3...",
                    created_at=dl_time
                ))
                event_id += 1
                
                if job.status == JobStatus.RUNNING:
                    # Restoring event for running jobs
                    restore_time = dl_time + timedelta(minutes=random.randint(5, 20))
                    job_events.append(create_mock_event(
                        event_id, job.id, "restoring", "Running myloader restore...",
                        created_at=restore_time
                    ))
                    event_id += 1
            
            events[job.id] = job_events
        
        # Events for history jobs (first 50 for performance)
        for job in self.history_jobs[:50]:
            job_events = []
            base_time = job.submitted_at
            
            # Created event
            job_events.append(create_mock_event(
                event_id, job.id, "created", "Job queued",
                created_at=base_time
            ))
            event_id += 1
            
            # Claimed event
            claim_time = base_time + timedelta(seconds=random.randint(5, 60))
            worker = job.worker_id or random.choice(workers)
            job_events.append(create_mock_event(
                event_id, job.id, "claimed", f"Claimed by {worker}",
                created_at=claim_time
            ))
            event_id += 1
            
            # Downloading event
            dl_time = claim_time + timedelta(seconds=random.randint(10, 60))
            sizes = ["256MB", "512MB", "1.2GB", "2.4GB", "4.8GB"]
            size = random.choice(sizes)
            job_events.append(create_mock_event(
                event_id, job.id, "downloading", f"Downloading backup from S3... ({size})",
                created_at=dl_time
            ))
            event_id += 1
            
            # Downloaded event
            dl_complete = dl_time + timedelta(minutes=random.randint(2, 15))
            job_events.append(create_mock_event(
                event_id, job.id, "downloaded", f"Download complete: {size}",
                created_at=dl_complete
            ))
            event_id += 1
            
            # Restoring event
            restore_start = dl_complete + timedelta(seconds=random.randint(5, 30))
            job_events.append(create_mock_event(
                event_id, job.id, "restoring", "Running myloader restore...",
                created_at=restore_start
            ))
            event_id += 1
            
            if job.status == JobStatus.COMPLETE:
                # Post-restore event
                post_time = restore_start + timedelta(minutes=random.randint(10, 45))
                job_events.append(create_mock_event(
                    event_id, job.id, "post_sql", "Applying post-restore scripts...",
                    created_at=post_time
                ))
                event_id += 1
                
                # Rename event
                rename_time = post_time + timedelta(minutes=random.randint(1, 5))
                job_events.append(create_mock_event(
                    event_id, job.id, "renaming", f"Renaming database to {job.target}",
                    created_at=rename_time
                ))
                event_id += 1
                
                # Complete event
                complete_time = rename_time + timedelta(seconds=random.randint(5, 30))
                duration = random.randint(15, 90)
                job_events.append(create_mock_event(
                    event_id, job.id, "complete", f"Restore complete: {size} in {duration}m",
                    created_at=complete_time
                ))
                event_id += 1
            else:
                # Failed event
                fail_time = restore_start + timedelta(minutes=random.randint(5, 30))
                errors = [
                    "S3 download timeout after 300s",
                    "MySQL connection refused",
                    "Disk space exhausted",
                    "myloader process killed by OOM",
                    "Invalid backup format detected",
                    "Permission denied on target database",
                    "Backup file corrupted or incomplete",
                ]
                job_events.append(create_mock_event(
                    event_id, job.id, "failed", random.choice(errors),
                    created_at=fail_time
                ))
                event_id += 1
            
            events[job.id] = job_events
        
        return events

    def get_job_by_id(self, job_id: str) -> Job | None:
        # Search all jobs including active and full history
        all_jobs = self.active_jobs + self.history_jobs
        for job in all_jobs:
            if job.id == job_id:
                return job
        return None

    def get_active_jobs(self) -> list[Job]:
        return self.active_jobs

    def get_recent_jobs(
        self,
        limit: int = 50,
        offset: int = 0,
        statuses: list[str] | None = None,
    ) -> list[Job]:
        """Get recent jobs, optionally filtered by status."""
        jobs = self.history_jobs
        if statuses:
            # Compare enum value (string) against status list
            jobs = [j for j in jobs if j.status.value in statuses]
        return jobs[offset : offset + limit]

    def get_job_events(
        self,
        job_id: str,
        since_id: int | None = None,
    ) -> list[JobEvent]:
        events = self.events.get(job_id, [])
        if since_id:
            events = [e for e in events if e.id > since_id]  # Use .id not .event_id
        return events

    def get_user_recent_jobs(
        self,
        user_id: str,
        limit: int = 5,
    ) -> list[Job]:
        """Get recent jobs for a specific user."""
        user_jobs = [j for j in self.history_jobs if j.owner_user_id == user_id]
        return user_jobs[:limit]

    def enqueue_job(self, job: Job) -> None:
        """Add a new job to the queue (mock implementation)."""
        # Use job.id (standard attribute for Job dataclass)
        job_id = job.id
        created_at = getattr(job, 'submitted_at', None)
        
        # Simply add to active jobs list
        self.active_jobs.insert(0, job)
        self.jobs.insert(0, job)
        
        # Generate initial event for the job
        if job_id:
            self.events[job_id] = [
                create_mock_event(
                    event_id=len(self.events) * 10 + 1,
                    job_id=job_id,
                    event_type="created",
                    message="Job queued for processing",
                    created_at=created_at or datetime.now(UTC),
                )
            ]

    def get_user_last_job(self, user_code: str) -> Job | None:
        """Get the most recent job for a user by user_code."""
        all_jobs = self.active_jobs + self.history_jobs
        user_jobs = [j for j in all_jobs if j.owner_user_code == user_code]
        if user_jobs:
            return sorted(user_jobs, key=lambda j: j.submitted_at, reverse=True)[0]
        return None

    def has_active_jobs_for_target(self, target: str, dbhost: str) -> bool:
        """Check if there are any active (queued/running) jobs for a target."""
        for job in self.active_jobs:
            status_val = job.status.value if hasattr(job.status, 'value') else job.status
            if job.target == target and job.dbhost == dbhost and status_val in ('queued', 'running'):
                return True
        return False

    def request_cancellation(self, job_id: str) -> bool:
        """Request cancellation of a job. Returns True if cancellation was requested.
        
        Note: Job is a frozen dataclass, so we use dataclasses.replace() to create
        a new Job with updated fields and replace it in the list.
        """
        from dataclasses import replace
        
        job = self.get_job_by_id(job_id)
        if not job:
            return False
        
        # Can only cancel queued or running jobs
        if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            return False
        
        # Check if already requested (Job doesn't have cancel_requested_at - track separately)
        if job_id in self._cancel_requested:
            return False
        
        # Track cancellation request separately (Job frozen, can't add field)
        self._cancel_requested[job_id] = datetime.now(UTC)
        return True

    def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job."""
        return job_id in self._cancel_requested

    def mark_job_canceled(self, job_id: str, reason: str | None = None) -> None:
        """Mark a job as canceled.
        
        Since Job is a frozen dataclass, we create a new Job with updated fields
        and replace it in the appropriate list.
        """
        from dataclasses import replace
        
        job = self.get_job_by_id(job_id)
        if not job:
            return
        
        # Create new job with updated status
        canceled_job = replace(
            job,
            status=JobStatus.CANCELED,
            completed_at=datetime.now(UTC),
            error_detail=reason or "Canceled by user",
        )
        
        # Replace in active_jobs and move to history
        if job in self.active_jobs:
            idx = self.active_jobs.index(job)
            self.active_jobs.pop(idx)
            self.history_jobs.insert(0, canceled_job)
        elif job in self.history_jobs:
            # Already in history, just update
            idx = self.history_jobs.index(job)
            self.history_jobs[idx] = canceled_job
        
        # Update jobs list for backward compatibility
        if job in self.jobs:
            idx = self.jobs.index(job)
            self.jobs[idx] = canceled_job
        
        # Add canceled event
        event_id = len(self.events.get(job_id, [])) + 1
        cancel_event = create_mock_event(
            event_id=event_id,
            job_id=job_id,
            event_type="canceled",
            message=reason or "Job canceled by user",
            created_at=datetime.now(UTC),
        )
        if job_id not in self.events:
            self.events[job_id] = []
        self.events[job_id].append(cancel_event)

    def append_job_event(
        self,
        job_id: str,
        event_type: str,
        detail: str | None = None,
    ) -> None:
        """Append an event to a job's event log."""
        event_id = len(self.events.get(job_id, [])) + 1
        event = create_mock_event(
            event_id=event_id,
            job_id=job_id,
            event_type=event_type,
            message=detail or event_type,
            created_at=datetime.now(UTC),
        )
        if job_id not in self.events:
            self.events[job_id] = []
        self.events[job_id].append(event)

    def prune_job_events(self, retention_days: int = 90) -> int:
        """Prune old job events. Returns count of deleted events."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        
        deleted = 0
        for job_id, events in list(self.events.items()):
            original_count = len(events)
            self.events[job_id] = [e for e in events if e.logged_at >= cutoff]
            deleted += original_count - len(self.events[job_id])
        
        return deleted

    def get_prune_candidates(
        self, 
        retention_days: int = 90, 
        offset: int = 0, 
        limit: int = 50
    ) -> dict:
        """Get paginated list of jobs with events that would be pruned.
        
        Returns dict with:
        - rows: list of job summaries with event counts
        - totalCount: total jobs affected
        - totalEvents: total events that would be deleted
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        
        # Build a lookup of terminal jobs from history_jobs
        # (In real system, a job moves from active to history when terminal)
        terminal_jobs = {j.id: j for j in self.history_jobs 
                        if j.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)}
        
        # Find all jobs with events older than cutoff (only terminal jobs)
        candidates = []
        total_events = 0
        
        for job_id, events in self.events.items():
            # Only consider terminal jobs (from history)
            job = terminal_jobs.get(job_id)
            if not job:
                continue
                
            old_events = [e for e in events if e.logged_at < cutoff]
            if old_events:
                oldest = min(e.logged_at for e in old_events)
                newest = max(e.logged_at for e in old_events)
                candidates.append({
                    "job_id": job_id,
                    "target": job.target,
                    "user_code": job.owner_user_code,
                    "status": job.status.value,
                    "event_count": len(old_events),
                    "oldest_event": oldest.isoformat(),
                    "newest_event": newest.isoformat(),
                })
                total_events += len(old_events)
        
        # Sort by oldest event (oldest first)
        candidates.sort(key=lambda x: x["oldest_event"])
        
        return {
            "rows": candidates[offset:offset + limit],
            "totalCount": len(candidates),
            "totalEvents": total_events,
        }

    def prune_job_events_excluding(
        self, 
        retention_days: int = 90, 
        exclude_job_ids: list[str] | None = None
    ) -> int:
        """Prune old job events, excluding specified job IDs. Returns count deleted."""
        exclude_job_ids = exclude_job_ids or []
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        
        # Build a lookup of terminal jobs from history_jobs
        terminal_jobs = {j.id: j for j in self.history_jobs 
                        if j.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)}
        
        deleted = 0
        for job_id, events in list(self.events.items()):
            if job_id in exclude_job_ids:
                continue
            # Only prune events for terminal jobs (from history)
            if job_id not in terminal_jobs:
                continue
                
            original_count = len(events)
            self.events[job_id] = [e for e in events if e.logged_at >= cutoff]
            deleted += original_count - len(self.events[job_id])
        
        return deleted

    def prune_job_events_by_ids(self, job_ids: list[str]) -> int:
        """Prune all events for specific job IDs. Returns count deleted."""
        deleted = 0
        for job_id in job_ids:
            if job_id in self.events:
                deleted += len(self.events[job_id])
                self.events[job_id] = []  # Clear all events for this job
        return deleted

    def get_cleanup_candidates(
        self,
        retention_days: int = 7,
        offset: int = 0,
        limit: int = 50
    ) -> dict:
        """Get paginated list of staging databases that would be cleaned up.
        
        Returns dict with:
        - rows: list of staging database candidates
        - totalCount: total databases that would be deleted
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        
        candidates = []
        # Only terminal jobs with staging_name that completed before cutoff
        all_jobs = self.history_jobs + self.active_jobs
        for job in all_jobs:
            # Must be terminal status
            if job.status not in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED):
                continue
            # Must have a staging name
            staging_name = getattr(job, "staging_name", None)
            if not staging_name:
                continue
            # Must have completed before cutoff
            completed_at = getattr(job, "completed_at", None)
            if not completed_at or completed_at >= cutoff:
                continue
            # Check if already cleaned (mock: assume not cleaned)
            staging_cleaned_at = getattr(job, "staging_cleaned_at", None)
            if staging_cleaned_at:
                continue
                
            candidates.append({
                "database_name": staging_name,
                "target": job.target,
                "dbhost": job.dbhost,
                "job_id": job.id,
                "job_status": job.status.value,
                "completed_at": completed_at.isoformat() if completed_at else None,
                "user_code": job.owner_user_code,
            })
        
        # Sort by completed_at (oldest first)
        candidates.sort(key=lambda x: x["completed_at"] or "")
        
        return {
            "rows": candidates[offset:offset + limit],
            "totalCount": len(candidates),
        }

    def drop_staging_databases_by_names(self, database_names: list[str]) -> dict:
        """Drop staging databases by name. Returns cleanup result dict.
        
        Includes safety check for active jobs on the same target.
        """
        from dataclasses import replace
        
        dropped_count = 0
        skipped_count = 0
        errors: list[str] = []
        
        # Build set of active targets for safety check
        active_targets: set[tuple[str, str]] = set()
        for job in self.active_jobs:
            if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                active_targets.add((job.target, job.dbhost))
        
        for i, job in enumerate(self.history_jobs):
            if job.staging_name not in database_names:
                continue
            
            # Safety check: skip if active job for same target
            if (job.target, job.dbhost) in active_targets:
                skipped_count += 1
                errors.append(f"Skipped {job.staging_name}: active job for target {job.target}")
                continue
            
            # Skip if already cleaned
            if job.staging_cleaned_at is not None:
                continue
            
            # Mark as cleaned using replace (Job is frozen)
            updated_job = replace(job, staging_cleaned_at=datetime.now(UTC))
            self.history_jobs[i] = updated_job
            dropped_count += 1
        
        return {
            "dropped_count": dropped_count,
            "skipped_count": skipped_count,
            "errors": errors,
        }


class MockHostRepo:
    """Mock host repository with sample database hosts.
    
    Mock hosts match exact DBHost model structure:
    - id: int (auto-increment PK)
    - hostname: str (FQDN)
    - host_alias: str | None (short name)
    - credential_ref: str (AWS Secrets Manager path)
    - max_concurrent_restores: int
    - enabled: bool
    - created_at: datetime
    """

    def __init__(self) -> None:
        self.hosts = [
            self._create_host(
                id=1,
                hostname="mysql-staging-01.example.com",
                host_alias="staging-01",
                max_concurrent_restores=3,
                enabled=True,
            ),
            self._create_host(
                id=2,
                hostname="mysql-staging-02.example.com",
                host_alias="staging-02",
                max_concurrent_restores=2,
                enabled=True,
            ),
            self._create_host(
                id=3,
                hostname="mysql-dev.example.com",
                host_alias="dev",
                max_concurrent_restores=1,
                enabled=False,  # Disabled host
            ),
        ]

    def _create_host(
        self,
        id: int,
        hostname: str,
        host_alias: str | None = None,
        max_concurrent_restores: int = 2,
        enabled: bool = True,
    ) -> MagicMock:
        """Create mock host matching exact DBHost model structure."""
        host = MagicMock()
        # Exact DBHost model attributes
        host.id = id
        host.hostname = hostname
        host.host_alias = host_alias
        host.credential_ref = f"mock/mysql/{host_alias or hostname}"
        host.max_concurrent_restores = max_concurrent_restores
        host.enabled = enabled
        host.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        return host

    def list_hosts(self) -> list[MagicMock]:
        """Return all hosts."""
        return self.hosts

    def get_enabled_hosts(self) -> list[MagicMock]:
        """Return only enabled hosts."""
        return [h for h in self.hosts if h.enabled]

    def enable_host(self, hostname: str) -> None:
        """Enable a host by hostname."""
        for h in self.hosts:
            if h.hostname == hostname:
                h.enabled = True
                break

    def disable_host(self, hostname: str) -> None:
        """Disable a host by hostname."""
        for h in self.hosts:
            if h.hostname == hostname:
                h.enabled = False
                break

    def get_host_credentials(self, hostname: str) -> Any:
        """Return mock credentials for host.
        
        In production, this resolves credential_ref via AWS Secrets Manager.
        For dev server, returns mock credentials.
        """
        # Return a mock credentials object
        creds = MagicMock()
        creds.username = "mock_mysql_user"
        creds.password = "mock_mysql_password"
        creds.host = hostname
        creds.port = 3306
        return creds


class MockSettingsRepo:
    """Mock settings repository for dev server.
    
    Mock settings match exact Setting model structure:
    - setting_key: str
    - setting_value: str
    - description: str | None
    - updated_at: datetime
    """

    def __init__(self) -> None:
        self.settings = [
            self._create_setting("myloader_threads", "4", "Number of parallel threads for myloader"),
            self._create_setting("myloader_overwrite", "true", "Whether to overwrite existing databases"),
            self._create_setting("retention_days", "90", "Days to retain job event logs"),
            self._create_setting("staging_retention_days", "7", "Days to retain staging databases"),
            self._create_setting("max_active_jobs_global", "0", "Global limit on active jobs (0=unlimited)"),
            self._create_setting("max_active_jobs_per_user", "5", "Per-user limit on active jobs"),
            self._create_setting("s3_bucket_path", "s3://pulldb-backups/production", "S3 bucket path for backups"),
            self._create_setting("work_dir", "/var/lib/pulldb/work", "Working directory for downloads"),
        ]

    def _create_setting(self, key: str, value: str, description: str) -> MagicMock:
        """Create mock setting matching exact Setting model structure."""
        setting = MagicMock()
        setting.setting_key = key
        setting.setting_value = value
        setting.description = description
        setting.updated_at = datetime(2024, 6, 1, tzinfo=UTC)
        return setting

    def list_settings(self) -> list[MagicMock]:
        """Return all settings."""
        return self.settings

    def get_max_active_jobs_global(self) -> int:
        """Return global active job limit (0 = unlimited)."""
        return 0  # No limit in dev mode

    def get_max_active_jobs_per_user(self) -> int:
        """Return per-user active job limit (0 = unlimited)."""
        return 0  # No limit in dev mode


class MockConfig:
    """Mock configuration for dev server."""

    def __init__(self) -> None:
        self.default_dbhost: str | None = None
        self.mysql_host: str = "mysql-staging-01.example.com"


class MockAPIState:
    """Mock API state with all repositories and scenario support."""

    # Available scenarios
    SCENARIOS = {
        "dev_mocks": {
            "name": "Dev Server Mocks",
            "description": "Default mock data for development",
        },
        "empty": {
            "name": "Empty State",
            "description": "No jobs - fresh system",
        },
        "busy": {
            "name": "Busy System",
            "description": "Many concurrent running jobs",
        },
        "all_failed": {
            "name": "All Failed",
            "description": "Multiple failed jobs for error testing",
        },
        "queue_backlog": {
            "name": "Queue Backlog",
            "description": "Many jobs waiting in queue",
        },
    }

    def __init__(self, scenario: str = "dev_mocks") -> None:
        self.current_scenario = scenario
        self.config = MockConfig()
        self.user_repo = MockUserRepo()
        self.auth_repo = MockAuthRepo()
        self.host_repo = MockHostRepo()
        self.settings_repo = MockSettingsRepo()
        self._load_scenario(scenario)
    
    def _load_scenario(self, scenario: str) -> None:
        """Load job data based on scenario."""
        from dataclasses import replace
        
        self.current_scenario = scenario
        
        if scenario == "empty":
            self.job_repo = MockJobRepo(active_count=0, history_count=0)
        elif scenario == "busy":
            self.job_repo = MockJobRepo(active_count=15, history_count=100)
            # Override to make most jobs running (Job is frozen, use replace)
            self.job_repo.active_jobs = [
                replace(job, status=JobStatus.RUNNING, current_operation="Restoring database")
                for job in self.job_repo.active_jobs
            ]
        elif scenario == "all_failed":
            self.job_repo = MockJobRepo(active_count=0, history_count=20)
            # Make all history jobs failed (Job is frozen, use replace)
            self.job_repo.history_jobs = [
                replace(job, status=JobStatus.FAILED, error_detail="Connection timeout during restore")
                for job in self.job_repo.history_jobs
            ]
        elif scenario == "queue_backlog":
            self.job_repo = MockJobRepo(active_count=25, history_count=50)
            # Make most jobs queued (Job is frozen, use replace)
            updated_jobs = []
            for i, job in enumerate(self.job_repo.active_jobs):
                if i < 20:
                    updated_jobs.append(replace(job, status=JobStatus.QUEUED, current_operation="Waiting in queue"))
                else:
                    updated_jobs.append(replace(job, status=JobStatus.RUNNING, current_operation="Restoring database"))
            self.job_repo.active_jobs = updated_jobs
        else:
            # Default: dev_mocks
            self.job_repo = MockJobRepo()
    
    def switch_scenario(self, scenario: str) -> dict:
        """Switch to a different scenario."""
        if scenario not in self.SCENARIOS:
            return {"error": f"Unknown scenario: {scenario}"}
        
        self._load_scenario(scenario)
        return {
            "status": "success",
            "scenario": scenario,
            "scenario_name": self.SCENARIOS[scenario]["name"],
        }


# =============================================================================
# Application Setup
# =============================================================================


def create_dev_app() -> FastAPI:
    """Create FastAPI app with mocked repositories."""
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from pulldb.web import SessionExpiredError, create_session_expired_handler

    app = FastAPI(
        title="pullDB Dev Server",
        description="Development server with mocked data",
    )

    # Store mock state
    app.state.api_state = MockAPIState()

    # Mount widgets directory for JS/CSS FIRST (single source of truth)
    # Must be before /static mount so /static/widgets/ resolves to widgets dir
    widgets_dir = Path(__file__).parent.parent / "pulldb" / "web" / "static" / "widgets"
    if widgets_dir.exists():
        app.mount("/static/widgets", StaticFiles(directory=str(widgets_dir)), name="widgets")
    
    # Mount images from pulldb/images
    images_dir = Path(__file__).parent.parent / "pulldb" / "images"
    if images_dir.exists():
        app.mount("/static/images", StaticFiles(directory=str(images_dir)), name="static-images")

    # Mount static files (CSS, JS, etc.) - unified location
    static_dir = Path(__file__).parent.parent / "pulldb" / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # === DEV MOCK ENDPOINTS ===
    # These override real endpoints for dev server mock data
    
    @app.get("/web/restore/search-customers")
    async def mock_search_customers(q: str = "", limit: int = 100):
        """Mock customer search for dev server.
        
        Returns mock customers matching the query.
        Supports prefix-based caching: fetch once per 3-char prefix.
        """
        if len(q) < 3:
            return {"results": [], "total": 0, "prefix": q}
        
        # Mock customers - match the simulation list
        mock_customers = [
            "actionpest",
            "actionplumbing", 
            "acmehvac",
            "bigcorp",
            "cleanpro",
            "deltaplumbing",
            "eliteelectric",
            "fastfix",
            "greenscapes",
            "homeservices",
            "techcorp",
            "globalretail",
            "healthnet",
            "autoparts",
            "buildpro",
            "foodmart",
            "energyco",
            "finserve",
            "edulearn",
            "medisys",
        ]
        
        q_lower = q.lower()
        matches = [c for c in mock_customers if q_lower in c.lower()]
        matches = sorted(matches)[:limit]
        
        return {
            "results": [{"value": c, "label": c} for c in matches],
            "total": len(matches),
            "prefix": q[:3] if len(q) >= 3 else q,
        }
    
    @app.get("/web/restore/search-backups")
    async def mock_search_backups(request: Request, customer: str = "", env: str = "both"):
        """Mock backup search for dev server."""
        from datetime import datetime, timedelta
        from fastapi.responses import HTMLResponse as HTMLResp
        import random
        
        if not customer:
            return HTMLResp(
                '<div class="alert alert-warning">Please select a customer first.</div>'
            )
        
        # Generate mock backups for the customer
        backups = []
        now = datetime.now()
        
        for i in range(random.randint(3, 8)):
            days_ago = random.randint(1, 90)
            timestamp = now - timedelta(days=days_ago, hours=random.randint(0, 23))
            backup_env = random.choice(["staging", "prod"]) if env == "both" else env
            
            # Skip if env filter doesn't match
            if env != "both" and backup_env != env:
                continue
                
            backups.append({
                "customer": customer,
                "timestamp": timestamp,
                "date": timestamp.strftime("%Y%m%d"),
                "size_mb": round(random.uniform(50, 2000), 1),
                "environment": backup_env,
                "key": f"s3://backups/{backup_env}/{customer}/{timestamp.strftime('%Y%m%d_%H%M%S')}.sql.gz",
                "bucket": f"pulldb-backups-{backup_env}",
            })
        
        # Sort by timestamp (most recent first)
        backups.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Generate HTML directly
        if not backups:
            return HTMLResp('''
                <div class="alert alert-warning" style="margin-top: 1rem; padding: 1rem; background: var(--warning-50); border: 1px solid var(--warning-200); border-radius: var(--radius-md); color: var(--warning-700);">
                    <strong>No backups found.</strong>
                    <p style="margin: 0.5rem 0 0 0;">No backups are available for this customer in the selected environment.</p>
                </div>
            ''')
        
        rows_html = ""
        for i, backup in enumerate(backups):
            badge_class = "badge-primary" if backup["environment"] == "prod" else "badge-neutral"
            timestamp_str = backup["timestamp"].strftime('%Y-%m-%d %H:%M')
            size_str = f"{backup['size_mb']:.1f} MB"
            
            rows_html += f'''
            <tr data-backup-key="{backup["key"]}" 
                onclick="selectBackup('{backup["key"]}', '{backup["environment"]}', '{timestamp_str}', '{size_str}')">
                <td>{timestamp_str}</td>
                <td>
                    <span class="badge {badge_class}">
                        {backup["environment"]}
                    </span>
                </td>
                <td>{size_str}</td>
            </tr>
            '''
        
        html = f'''
        <table class="backup-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Environment</th>
                    <th>Size</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        '''
        
        return HTMLResp(html)

    # Include unified web router
    try:
        from pulldb.web import router as web_router
        app.include_router(web_router)
    except ImportError:
        print("WARNING: Web module not found, skipping mount.")
    
    # Register session expired exception handler
    app.add_exception_handler(SessionExpiredError, create_session_expired_handler())

    # Dropdown search API endpoints for searchable dropdowns
    @app.get("/api/dropdown/customers")
    async def dropdown_search_customers(q: str = "", limit: int = 20):
        """Search customers for dropdown."""
        if len(q) < 5:
            return {"results": [], "total": 0}
        
        # Mock customers
        mock_customers = [
            {"id": "acmehvac", "name": "ACME HVAC Services"},
            {"id": "techcorp", "name": "TechCorp Industries"},
            {"id": "fastlogistics", "name": "Fast Logistics LLC"},
            {"id": "globalretail", "name": "Global Retail Inc"},
            {"id": "healthnet", "name": "HealthNet Medical"},
            {"id": "autoparts", "name": "AutoParts Express"},
            {"id": "buildpro", "name": "BuildPro Construction"},
            {"id": "foodmart", "name": "FoodMart Groceries"},
            {"id": "energyco", "name": "EnergyCo Power"},
            {"id": "finserve", "name": "FinServe Banking"},
            {"id": "edulearn", "name": "EduLearn Academy"},
            {"id": "medisys", "name": "MediSys Healthcare"},
        ]
        
        q_lower = q.lower()
        matches = [c for c in mock_customers if q_lower in c["id"].lower() or q_lower in c["name"].lower()]
        return {
            "results": [{"value": c["id"], "label": c["id"], "sublabel": c["name"]} for c in matches[:limit]],
            "total": len(matches)
        }

    @app.get("/api/dropdown/users")
    async def dropdown_search_users(q: str = "", limit: int = 15):
        """Search users for dropdown."""
        if len(q) < 2:
            return {"results": [], "total": 0}
        
        # Mock users
        mock_users = [
            {"username": "devuser", "user_code": "devusr", "role": "user"},
            {"username": "devadmin", "user_code": "devadm", "role": "admin"},
            {"username": "testuser", "user_code": "tstusr", "role": "user"},
            {"username": "qamanager", "user_code": "qamgr", "role": "manager"},
        ]
        
        q_lower = q.lower()
        matches = [u for u in mock_users if q_lower in u["username"].lower() or q_lower in u["user_code"].lower()]
        return {
            "results": [{"value": u["username"], "label": u["username"], "sublabel": f"{u['user_code']} ({u['role']})"} for u in matches[:limit]],
            "total": len(matches)
        }

    @app.get("/api/dropdown/hosts")
    async def dropdown_search_hosts(q: str = "", limit: int = 10):
        """Search hosts for dropdown."""
        if len(q) < 2:
            return {"results": [], "total": 0}
        
        # Mock hosts
        mock_hosts = [
            {"hostname": "mysql-staging-01.example.com", "status": "enabled"},
            {"hostname": "mysql-staging-02.example.com", "status": "enabled"},
            {"hostname": "mysql-staging-03.example.com", "status": "disabled"},
            {"hostname": "mysql-prod-01.example.com", "status": "enabled"},
        ]
        
        q_lower = q.lower()
        matches = [h for h in mock_hosts if q_lower in h["hostname"].lower()]
        return {
            "results": [{"value": h["hostname"], "label": h["hostname"], "sublabel": h["status"]} for h in matches[:limit]],
            "total": len(matches)
        }

    # Helper for enum-safe status access (mock jobs use strings, real jobs use enums)
    def _get_status_value(job):
        return job.status.value if hasattr(job.status, 'value') else job.status

    def _wildcard_match(pattern: str, value: str) -> bool:
        """Match value against pattern with * wildcards.
        
        Examples:
            _wildcard_match("job-01*", "job-0100") -> True
            _wildcard_match("*0100", "job-0100") -> True
            _wildcard_match("12/*/2024", "12/08/2024") -> True
        """
        import fnmatch
        return fnmatch.fnmatch(value.lower(), pattern.lower())

    # Paginated jobs endpoint for LazyTable widget
    @app.get("/api/jobs/paginated")
    async def paginated_jobs(
        request: Request,
        page: int = 0,
        pageSize: int = 50,
        view: str = "active",
        sortColumn: str | None = None,
        sortDirection: str | None = None,
        filter_status: str | None = None,
        filter_dbhost: str | None = None,
        filter_user_code: str | None = None,
        filter_owner_user_code: str | None = None,
        filter_target: str | None = None,
        filter_id: str | None = None,
        filter_submitted_at: str | None = None,
        filter_submitted_after: str | None = None,
        filter_submitted_before: str | None = None,
    ):
        """Get paginated jobs for LazyTable widget."""
        state: MockAPIState = request.app.state.api_state
        
        # Get current user from session cookie for can_cancel permission check
        current_user = None
        session_token = request.cookies.get("session_token")
        if session_token and hasattr(state, "auth_repo") and state.auth_repo:
            user_id = state.auth_repo.validate_session(session_token)
            if user_id and hasattr(state, "user_repo") and state.user_repo:
                current_user = state.user_repo.get_user_by_id(user_id)
        
        # Get jobs based on view
        if view == "history":
            all_jobs = list(state.job_repo.history_jobs)
        else:
            all_jobs = list(state.job_repo.active_jobs)
        
        # Apply filters (comma-separated values = OR logic for multi-select)
        filtered = all_jobs
        if filter_status:
            status_values = set(filter_status.split(','))
            filtered = [j for j in filtered if _get_status_value(j) in status_values]
        if filter_dbhost:
            dbhost_values = set(filter_dbhost.split(','))
            filtered = [j for j in filtered if j.dbhost in dbhost_values]
        # Support both filter_user_code and filter_owner_user_code for compatibility
        user_code_filter = filter_owner_user_code or filter_user_code
        if user_code_filter:
            user_code_values = set(user_code_filter.split(','))
            filtered = [j for j in filtered if j.owner_user_code in user_code_values]
        if filter_target:
            target_values = set(v.lower() for v in filter_target.split(','))
            filtered = [j for j in filtered if any(tv in (j.target or "").lower() for tv in target_values)]
        
        # Text-based wildcard filters for Job ID
        if filter_id:
            filtered = [j for j in filtered if j.id and _wildcard_match(filter_id, j.id)]
        
        # Text-based wildcard filters for submitted_at (matches formatted date MM/DD/YYYY)
        if filter_submitted_at:
            def match_submitted(job):
                if not job.submitted_at:
                    return False
                # Format date as MM/DD/YYYY for pattern matching
                formatted = job.submitted_at.strftime("%m/%d/%Y")
                return _wildcard_match(filter_submitted_at, formatted)
            filtered = [j for j in filtered if match_submitted(j)]
        
        # Date range filter for submitted_after (ISO datetime string)
        if filter_submitted_after:
            try:
                cutoff = datetime.fromisoformat(filter_submitted_after.replace('Z', '+00:00'))
                filtered = [j for j in filtered if j.submitted_at and j.submitted_at >= cutoff]
            except ValueError:
                pass  # Invalid date format, skip filter
        
        # Date range filter for submitted_before (ISO datetime string)
        if filter_submitted_before:
            try:
                cutoff = datetime.fromisoformat(filter_submitted_before.replace('Z', '+00:00'))
                filtered = [j for j in filtered if j.submitted_at and j.submitted_at <= cutoff]
            except ValueError:
                pass  # Invalid date format, skip filter
        
        # Sort
        if sortColumn and sortDirection:
            reverse = sortDirection == "desc"
            sort_keys = {
                "id": lambda j: j.id or "",
                "submitted_at": lambda j: j.submitted_at or datetime.min.replace(tzinfo=UTC),
                "status": lambda j: _get_status_value(j),
                "target": lambda j: j.target or "",
                "owner_user_code": lambda j: j.owner_user_code or "",
                "user_code": lambda j: j.owner_user_code or "",  # Backward compatibility
                "dbhost": lambda j: j.dbhost or "",
            }
            if sortColumn in sort_keys:
                filtered = sorted(filtered, key=sort_keys[sortColumn], reverse=reverse)
        
        total = len(all_jobs)
        filtered_count = len(filtered)
        
        # Paginate
        offset = page * pageSize
        page_jobs = filtered[offset:offset + pageSize]
        
        # Convert to dicts
        rows = []
        for job in page_jobs:
            status_val = _get_status_value(job)
            
            # Compute duration_seconds for completed jobs
            duration_seconds = None
            if job.started_at and job.completed_at:
                delta = job.completed_at - job.started_at
                duration_seconds = delta.total_seconds()
            
            # Determine can_cancel permission
            can_cancel = False
            if status_val in ("queued", "running") and current_user is not None:
                if current_user.role.value == "admin":
                    can_cancel = True
                elif current_user.user_id == job.owner_user_id:
                    can_cancel = True
                elif current_user.role.value == "manager":
                    # Managers can cancel jobs of users they manage
                    job_owner = state.user_repo.get_user_by_id(job.owner_user_id) if state.user_repo else None
                    if job_owner and job_owner.manager_id == current_user.user_id:
                        can_cancel = True
            
            rows.append({
                "id": job.id,
                "target": job.target,
                "status": status_val,
                "owner_user_code": job.owner_user_code,
                "submitted_at": job.submitted_at.isoformat() if job.submitted_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "dbhost": job.dbhost,
                "staging_name": job.staging_name,
                "current_operation": job.current_operation,
                "duration_seconds": duration_seconds,
                "error_detail": job.error_detail,
                "can_cancel": can_cancel,
                "cancel_requested_at": state.job_repo._cancel_requested.get(job.id),
            })
        
        return {
            "rows": rows,
            "totalCount": total,
            "filteredCount": filtered_count,
            "page": page,
            "pageSize": pageSize,
        }
    
    @app.get("/api/jobs/paginated/distinct")
    async def paginated_jobs_distinct(
        request: Request,
        column: str,
        view: str = "active",
    ):
        """Get distinct values for a column."""
        state: MockAPIState = request.app.state.api_state
        
        if view == "history":
            jobs = state.job_repo.history_jobs
        else:
            jobs = state.job_repo.active_jobs
        
        values = set()
        for job in jobs:
            if column == "status":
                # Mock jobs use string status, real jobs use enum
                status_val = job.status.value if hasattr(job.status, 'value') else job.status
                values.add(status_val)
            elif column == "dbhost" and job.dbhost:
                values.add(job.dbhost)
            elif column in ("user_code", "owner_user_code") and job.owner_user_code:
                values.add(job.owner_user_code)
            elif column == "target" and job.target:
                values.add(job.target)
        
        return sorted(values)

    # Paginated team endpoint for manager LazyTable widget
    @app.get("/api/manager/team")
    async def paginated_team(
        request: Request,
        page: int = 0,
        pageSize: int = 50,
        sortColumn: str | None = None,
        sortDirection: str | None = None,
        filter_username: str | None = None,
        filter_user_code: str | None = None,
        filter_status: str | None = None,
    ):
        """Get paginated team members for manager LazyTable widget."""
        state: MockAPIState = request.app.state.api_state
        
        # Get current user from session cookie
        current_user = None
        session_token = request.cookies.get("session_token")
        if session_token and hasattr(state, "auth_repo") and state.auth_repo:
            user_id = state.auth_repo.validate_session(session_token)
            if user_id and hasattr(state, "user_repo") and state.user_repo:
                current_user = state.user_repo.get_user_by_id(user_id)
        
        if not current_user:
            return {"rows": [], "totalCount": 0, "filteredCount": 0, "page": page, "pageSize": pageSize}
        
        # Get managed users
        managed_users = []
        if hasattr(state.user_repo, "get_users_managed_by"):
            managed_users = state.user_repo.get_users_managed_by(current_user.user_id)
        
        # Get active jobs for counting
        all_jobs = []
        if hasattr(state.job_repo, "active_jobs"):
            all_jobs = list(state.job_repo.active_jobs)
        
        # Compute per-user active job counts
        user_active_jobs = {}
        for mu in managed_users:
            user_active_jobs[mu.user_id] = len([
                j for j in all_jobs
                if j.owner_user_id == mu.user_id
                and (j.status.value if hasattr(j.status, 'value') else j.status) in ('queued', 'running')
            ])
        
        # Compute per-user password reset status
        user_password_reset = {}
        for mu in managed_users:
            if hasattr(state.auth_repo, "is_password_reset_required"):
                user_password_reset[mu.user_id] = state.auth_repo.is_password_reset_required(mu.user_id)
            else:
                user_password_reset[mu.user_id] = False
        
        # Apply filters
        filtered = managed_users
        if filter_username:
            filter_username_lower = filter_username.lower()
            filtered = [u for u in filtered if filter_username_lower in (u.username or "").lower()]
        if filter_user_code:
            filter_user_code_lower = filter_user_code.lower()
            filtered = [u for u in filtered if filter_user_code_lower in (u.user_code or "").lower()]
        if filter_status:
            status_values = set(filter_status.split(','))
            def matches_status(u):
                user_status = "disabled" if u.disabled_at else "active"
                return user_status in status_values
            filtered = [u for u in filtered if matches_status(u)]
        
        # Sort
        if sortColumn and sortDirection:
            reverse = sortDirection == "desc"
            sort_keys = {
                "username": lambda u: (u.username or "").lower(),
                "user_code": lambda u: (u.user_code or "").lower(),
                "active_jobs": lambda u: user_active_jobs.get(u.user_id, 0),
                "status": lambda u: 0 if u.disabled_at else 1,  # Active first
            }
            if sortColumn in sort_keys:
                filtered = sorted(filtered, key=sort_keys[sortColumn], reverse=reverse)
        
        total = len(managed_users)
        filtered_count = len(filtered)
        
        # Paginate
        offset = page * pageSize
        page_users = filtered[offset:offset + pageSize]
        
        # Convert to dicts
        rows = []
        for u in page_users:
            rows.append({
                "user_id": u.user_id,
                "username": u.username,
                "user_code": u.user_code,
                "active_jobs": user_active_jobs.get(u.user_id, 0),
                "disabled_at": u.disabled_at.isoformat() if u.disabled_at else None,
                "password_reset_pending": user_password_reset.get(u.user_id, False),
            })
        
        return {
            "rows": rows,
            "totalCount": total,
            "filteredCount": filtered_count,
            "page": page,
            "pageSize": pageSize,
        }

    @app.get("/api/manager/team/distinct")
    async def team_distinct_values(
        request: Request,
        column: str,
    ):
        """Get distinct values for a column in the team table."""
        state: MockAPIState = request.app.state.api_state
        
        # Get current user from session cookie
        current_user = None
        session_token = request.cookies.get("session_token")
        if session_token and hasattr(state, "auth_repo") and state.auth_repo:
            user_id = state.auth_repo.validate_session(session_token)
            if user_id and hasattr(state, "user_repo") and state.user_repo:
                current_user = state.user_repo.get_user_by_id(user_id)
        
        if not current_user:
            return []
        
        # Get managed users
        managed_users = []
        if hasattr(state.user_repo, "get_users_managed_by"):
            managed_users = state.user_repo.get_users_managed_by(current_user.user_id)
        
        values = set()
        for u in managed_users:
            if column == "username" and u.username:
                values.add(u.username)
            elif column == "user_code" and u.user_code:
                values.add(u.user_code)
            elif column == "status":
                values.add("disabled" if u.disabled_at else "active")
        
        return sorted(values)

    # Redirect root to login
    @app.get("/")
    async def root():  # noqa: RUF029
        return RedirectResponse(url="/web/login")

    # =============================================================================
    # Simulation Mode Endpoints
    # =============================================================================
    # These provide mock data for the dev toolbar's simulation debug panel.
    
    @app.get("/simulation/status")
    async def simulation_status(request: Request):
        """Get current simulation state for debug panel."""
        state: MockAPIState = request.app.state.api_state
        scenario_info = MockAPIState.SCENARIOS.get(state.current_scenario, {})
        return {
            "current_scenario": scenario_info.get("name", state.current_scenario),
            "job_count": len(state.job_repo.active_jobs) + len(state.job_repo.history_jobs),
            "user_count": len(state.user_repo.users),
            "host_count": len(state.host_repo.hosts),
            "s3_bucket_count": 1,
            "event_count": len(state.job_repo.events),
        }
    
    @app.get("/simulation/scenarios")
    async def simulation_scenarios(request: Request):
        """Get available simulation scenarios."""
        state: MockAPIState = request.app.state.api_state
        return {
            "current": state.current_scenario,
            "scenarios": [
                {"type": key, "name": val["name"], "description": val["description"]}
                for key, val in MockAPIState.SCENARIOS.items()
            ]
        }
    
    @app.post("/simulation/scenarios/activate")
    async def simulation_scenarios_activate(request: Request):
        """Activate a simulation scenario - actually switches the mock data!"""
        body = await request.json()
        scenario_type = body.get("scenario_type", "dev_mocks")
        
        state: MockAPIState = request.app.state.api_state
        result = state.switch_scenario(scenario_type)
        
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        
        return {
            "status": "success", 
            "scenario_name": result["scenario_name"],
            "message": f"Switched to {result['scenario_name']} scenario. Refresh the page to see changes."
        }
    
    @app.get("/simulation/events")
    async def simulation_events(request: Request, limit: int = 20):
        """Get recent simulation events."""
        state: MockAPIState = request.app.state.api_state
        events = []
        
        # Flatten all events from the job_repo
        all_events = []
        for job_id, job_events in state.job_repo.events.items():
            all_events.extend(job_events)
        
        # Sort by timestamp descending and take limit
        all_events.sort(key=lambda e: e.logged_at, reverse=True)
        
        for event in all_events[:limit]:
            events.append({
                "timestamp": event.logged_at.isoformat(),
                "event_type": event.event_type,
                "source": "dev_server",
                "job_id": event.job_id,
            })
        
        return {"events": events}
    
    @app.get("/simulation/activate")
    async def simulation_activate(redirect: str = "/web/dashboard"):
        """Activate simulation mode (no-op in dev server - already using mocks)."""
        return RedirectResponse(url=redirect, status_code=302)
    
    @app.get("/simulation/deactivate")
    async def simulation_deactivate(redirect: str = "/web/dashboard"):
        """Deactivate simulation mode (no-op in dev server)."""
        return RedirectResponse(url=redirect, status_code=302)
    
    @app.post("/simulation/reset")
    async def simulation_reset(request: Request):
        """Reset simulation state to default scenario."""
        state: MockAPIState = request.app.state.api_state
        state.switch_scenario("dev_mocks")
        return {"status": "success", "message": "Simulation reset to default. Page will reload."}

    return app


def _mock_get_api_state() -> MockAPIState:
    """Override for get_api_state that returns our mock."""
    import pulldb.api.main as api_main

    return api_main._test_api_state  # type: ignore[attr-defined]


def _load_dev_extensions() -> str:
    """Load the dev extensions HTML from the dev_templates directory.
    
    This contains all dev-only UI components:
    - Dev toolbar (viewport testing, grid overlay, color palette)
    - Simulation debug panel (scenarios, event history, state)
    
    Returns the raw HTML/CSS/JS to be injected into templates.
    """
    dev_templates_dir = Path(__file__).parent / "dev_templates"
    dev_extensions_file = dev_templates_dir / "dev_extensions.html"
    
    if not dev_extensions_file.exists():
        print(f"WARNING: Dev extensions file not found: {dev_extensions_file}")
        return "<!-- Dev extensions not found -->"
    
    return dev_extensions_file.read_text()


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    """Run the development server."""
    import os
    
    import pulldb.api.main as api_main
    from pulldb.web.dependencies import templates

    # Security: Refuse to enable dev mode in production environment
    if os.environ.get("PULLDB_ENV", "").lower() == "production":
        print("ERROR: Cannot run dev_server.py in production environment!")
        print("       PULLDB_ENV is set to 'production'")
        sys.exit(1)
    
    # Load dev extensions (toolbar, simulation panel, etc.)
    dev_extensions_html = _load_dev_extensions()
    
    # Inject dev extensions into all templates
    # This is the ONLY place dev-specific UI is added
    templates.env.globals["dev_extensions"] = dev_extensions_html
    
    # Keep these for any template logic that checks dev mode
    templates.env.globals["dev_mode"] = True
    templates.env.globals["simulation_mode"] = lambda: True
    templates.env.globals["simulation_scenario_name"] = lambda: "Dev Server Mocks"

    print("\n" + "=" * 60)
    print("  pullDB Development Server")
    print("=" * 60)
    print("\n  Login credentials (password: PullDB_Dev2025!):")
    print("    devuser    - USER role")
    print("    devmanager - MANAGER role")
    print("    devadmin   - ADMIN role")
    print("\n  Open: http://127.0.0.1:8000/web/login")
    print("  Dev toolbar: Press Ctrl+` to toggle")
    print("=" * 60 + "\n")

    # Create app and store state for the mock
    app = create_dev_app()
    api_main._test_api_state = app.state.api_state  # type: ignore[attr-defined]

    # Patch get_api_state to use our mock
    api_main.get_api_state = _mock_get_api_state  # type: ignore[assignment]

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
