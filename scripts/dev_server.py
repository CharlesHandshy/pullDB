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
from unittest.mock import MagicMock

import uvicorn
from fastapi import FastAPI, Request

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pulldb.domain.models import UserRole


# =============================================================================
# Mock Data Factories
# =============================================================================


def create_mock_user(
    user_id: int = 1,
    username: str = "testuser",
    role: UserRole = UserRole.USER,
    disabled: bool = False,
    user_code: str | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock User object."""
    user = MagicMock()
    user.user_id = user_id
    user.username = username
    user.role = role  # Now a proper UserRole enum with .value
    user.is_admin = role == UserRole.ADMIN
    user.disabled_at = datetime(2024, 1, 1, tzinfo=UTC) if disabled else None
    user.disabled = disabled
    user.user_code = user_code or f"u{user_id:03d}"
    user.created_at = created_at or datetime(2024, 1, 1, tzinfo=UTC)
    user.last_login = datetime.now(UTC) if not disabled else None
    user.active_jobs = 0
    user.total_jobs = 0
    return user


def create_mock_job(
    job_id: str = "job-001",
    source_customer: str = "acmehvac",
    status: str = "queued",  # Valid enum: queued, running, failed, complete, canceled
    owner_user_id: int = 1,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_detail: str | None = None,
    worker_id: str | None = None,
    backup_env: str = "prd",
    is_qatemplate: bool = False,
) -> MagicMock:
    """Create a mock Job object.
    
    The naming convention follows the real pullDB flow:
    
    For customer restores:
    - source_customer: Customer whose backup we're restoring (e.g., 'acmehvac')
    - target: {user_code}{customer} - final database name (e.g., 'devusracmehvac')
    - staging_name: {target}_{job_id_hex[:12]} - temp staging db
    - backup_file: {customer}/{env}/{date}/backup.tar.gz
    
    For QA template restores:
    - source_customer: "QA Template" (display only)
    - target: {user_code}qatemplate (e.g., 'devusrqatemplate')
    - staging_name: {target}_{job_id_hex[:12]}
    - backup_file: qatemplate/{date}/backup.tar.gz
    
    Note: user_code and target must be lowercase letters only (a-z).
    """
    job = MagicMock()
    job.id = job_id
    job.job_id = job_id
    
    # User info based on owner (user_code is 6 lowercase letters only)
    job.owner_user_id = owner_user_id
    job.username = "devuser" if owner_user_id == 1 else "devadmin"
    job.owner_username = job.username
    job.user_code = "devusr" if owner_user_id == 1 else "devadm"
    job.owner_user_code = job.user_code
    
    job.created_at = created_at or datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    backup_date = job.created_at.strftime('%Y-%m-%d')
    
    if is_qatemplate:
        # QA Template job
        job.source_customer = "QA Template"
        job.target = f"{job.user_code}qatemplate"
        job.backup_file = f"qatemplate/{backup_date}/backup.tar.gz"
    else:
        # Customer restore job
        job.source_customer = source_customer
        job.target = f"{job.user_code}{source_customer}"
        job.backup_file = f"{source_customer}/{backup_env}/{backup_date}/backup.tar.gz"
    
    job.source_database = job.target  # Alias for templates
    
    # Staging name: {target}_{job_id_hex[:12]} - simulate UUID hex prefix
    # Use a deterministic "hex" based on job_id for consistency
    job_hex = job_id.replace("job-", "").replace("-", "")[:12].ljust(12, "0")
    job.staging_name = f"{job.target}_{job_hex}"
    
    job.dbhost = "mysql-staging-01.example.com"
    job.status = status
    job.started_at = started_at
    job.completed_at = finished_at
    job.submitted_at = job.created_at
    job.error_detail = error_detail
    job.worker_id = worker_id
    job.progress = 45 if status == "running" else None
    job.duration = "45m 30s" if job.completed_at else None
    job.duration_display = job.duration or "-"
    
    # Operation status based on job status
    status_operations = {
        "queued": "Waiting in queue",
        "running": "Restoring database",
        "complete": None,
        "failed": None,
        "canceled": None,
    }
    job.current_operation = status_operations.get(status)
    return job


def create_mock_event(
    event_id: int = 1,
    job_id: str = "job-001",
    event_type: str = "created",
    message: str = "Job created",
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock JobEvent object."""
    event = MagicMock()
    event.event_id = event_id
    event.job_id = job_id
    event.event_type = event_type
    event.message = message
    event.created_at = created_at or datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    return event


# =============================================================================
# Mock Repositories
# =============================================================================


class MockUserRepo:
    """Mock user repository."""

    def __init__(self) -> None:
        # user_code must be 6 lowercase letters only (a-z)
        self.users = {
            "devuser": create_mock_user(1, "devuser", UserRole.USER, user_code="devusr"),
            "devadmin": create_mock_user(2, "devadmin", UserRole.ADMIN, user_code="devadm"),
            "devmanager": create_mock_user(3, "devmanager", UserRole.MANAGER, user_code="devmgr"),
            "alice": create_mock_user(4, "alice", UserRole.USER, user_code="aliceu", created_at=datetime(2023, 6, 15, tzinfo=UTC)),
            "bob": create_mock_user(5, "bob", UserRole.USER, disabled=True, user_code="bobuse", created_at=datetime(2023, 3, 10, tzinfo=UTC)),
        }
        # Set job counts
        self.users["devuser"].active_jobs = 2
        self.users["devuser"].total_jobs = 15
        self.users["devadmin"].active_jobs = 1
        self.users["devadmin"].total_jobs = 8
        self.users["devmanager"].active_jobs = 0
        self.users["devmanager"].total_jobs = 3

    def get_user_by_username(self, username: str) -> MagicMock | None:
        # Case-insensitive lookup
        for u in self.users.values():
            if u.username.lower() == username.lower():
                return u
        return None

    def get_user_by_id(self, user_id: int) -> MagicMock | None:
        for user in self.users.values():
            if user.user_id == user_id:
                return user
        return None

    def list_users(self) -> list[MagicMock]:
        """Return all users."""
        return list(self.users.values())

    def enable_user(self, user_id: int) -> None:
        """Enable a user account."""
        for user in self.users.values():
            if user.user_id == user_id:
                user.disabled = False
                user.disabled_at = None
                break

    def disable_user(self, user_id: int) -> None:
        """Disable a user account."""
        for user in self.users.values():
            if user.user_id == user_id:
                user.disabled = True
                user.disabled_at = datetime.now(UTC)
                break


class MockAuthRepo:
    """Mock auth repository."""

    def __init__(self) -> None:
        self.sessions: dict[str, int] = {}
        # Password: "PullDB_Dev2025!" for all dev users (bcrypt hash)
        # Generated with: from pulldb.auth.password import hash_password; hash_password("PullDB_Dev2025!")
        test_hash = "$2b$12$XnisilncYSnbIvEinwVYTePMF/DMiVUwpUSv8BuOWSlPH5sRam.zG"
        self.password_hashes = {
            1: test_hash,  # devuser
            2: test_hash,  # devadmin
            3: test_hash,  # devmanager
            4: test_hash,  # alice
            5: test_hash,  # bob
        }

    def get_password_hash(self, user_id: int | str) -> str | None:
        # Handle both int and str IDs
        if isinstance(user_id, str) and user_id.isdigit():
            user_id = int(user_id)
        return self.password_hashes.get(user_id)

    def validate_session(self, token: str) -> int | None:
        return self.sessions.get(token)

    def create_session(
        self,
        user_id: int,
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
    
    def _generate_active_jobs(self, count: int) -> list[MagicMock]:
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
        owners = [1, 1, 1, 2, 3]  # Mix of users
        user_codes = ["devusr", "devusr", "devusr", "devadm", "devmgr"]
        envs = ["prd", "stg"]
        
        jobs = []
        base_time = datetime.now(UTC) - timedelta(hours=12)
        
        for i in range(count):
            job_id = f"job-{i + 1:04d}"
            # Mix of statuses: ~30% queued, ~70% running
            status = "queued" if random.random() < 0.3 else "running"
            owner_idx = random.randint(0, len(owners) - 1)
            owner_id = owners[owner_idx]
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
                created_at=created_at,
                started_at=created_at + timedelta(minutes=random.randint(1, 5)) if status == "running" else None,
                worker_id=random.choice(workers) if status == "running" else None,
                backup_env=env,
            )
            # Override dbhost for variety
            job.dbhost = db_host
            jobs.append(job)
        
        return jobs

    def _generate_history_jobs(self, count: int) -> list[MagicMock]:
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
        owners = [1, 1, 1, 2]  # 75% demo, 25% admin
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
            owner_id = random.choice(owners)
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
                    created_at=created_at,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_detail=error_detail,
                    worker_id=worker,
                    backup_env=backup_env,
                )
            jobs.append(job)
        
        return jobs

    def _generate_events(self) -> dict[str, list[MagicMock]]:
        """Generate mock events for all jobs."""
        import random
        
        events: dict[str, list[MagicMock]] = {}
        event_id = 1
        
        workers = ["worker-alpha", "worker-beta", "worker-gamma", "worker-delta"]
        
        # Events for active jobs
        for job in self.active_jobs:
            job_events = []
            base_time = job.created_at
            
            # Created event
            job_events.append(create_mock_event(
                event_id, job.job_id, "created", "Job queued",
                created_at=base_time
            ))
            event_id += 1
            
            if job.status in ("running", "complete", "failed"):
                # Claimed event
                claim_time = base_time + timedelta(seconds=random.randint(5, 30))
                worker = job.worker_id or random.choice(workers)
                job_events.append(create_mock_event(
                    event_id, job.job_id, "claimed", f"Claimed by {worker}",
                    created_at=claim_time
                ))
                event_id += 1
                
                # Downloading event
                dl_time = claim_time + timedelta(seconds=random.randint(2, 10))
                job_events.append(create_mock_event(
                    event_id, job.job_id, "downloading", "Downloading backup from S3...",
                    created_at=dl_time
                ))
                event_id += 1
                
                if job.status == "running":
                    # Restoring event for running jobs
                    restore_time = dl_time + timedelta(minutes=random.randint(5, 20))
                    job_events.append(create_mock_event(
                        event_id, job.job_id, "restoring", "Running myloader restore...",
                        created_at=restore_time
                    ))
                    event_id += 1
            
            events[job.job_id] = job_events
        
        # Events for history jobs (first 50 for performance)
        for job in self.history_jobs[:50]:
            job_events = []
            base_time = job.created_at
            
            # Created event
            job_events.append(create_mock_event(
                event_id, job.job_id, "created", "Job queued",
                created_at=base_time
            ))
            event_id += 1
            
            # Claimed event
            claim_time = base_time + timedelta(seconds=random.randint(5, 60))
            worker = job.worker_id or random.choice(workers)
            job_events.append(create_mock_event(
                event_id, job.job_id, "claimed", f"Claimed by {worker}",
                created_at=claim_time
            ))
            event_id += 1
            
            # Downloading event
            dl_time = claim_time + timedelta(seconds=random.randint(10, 60))
            sizes = ["256MB", "512MB", "1.2GB", "2.4GB", "4.8GB"]
            size = random.choice(sizes)
            job_events.append(create_mock_event(
                event_id, job.job_id, "downloading", f"Downloading backup from S3... ({size})",
                created_at=dl_time
            ))
            event_id += 1
            
            # Downloaded event
            dl_complete = dl_time + timedelta(minutes=random.randint(2, 15))
            job_events.append(create_mock_event(
                event_id, job.job_id, "downloaded", f"Download complete: {size}",
                created_at=dl_complete
            ))
            event_id += 1
            
            # Restoring event
            restore_start = dl_complete + timedelta(seconds=random.randint(5, 30))
            job_events.append(create_mock_event(
                event_id, job.job_id, "restoring", "Running myloader restore...",
                created_at=restore_start
            ))
            event_id += 1
            
            if job.status == "complete":
                # Post-restore event
                post_time = restore_start + timedelta(minutes=random.randint(10, 45))
                job_events.append(create_mock_event(
                    event_id, job.job_id, "post_sql", "Applying post-restore scripts...",
                    created_at=post_time
                ))
                event_id += 1
                
                # Rename event
                rename_time = post_time + timedelta(minutes=random.randint(1, 5))
                job_events.append(create_mock_event(
                    event_id, job.job_id, "renaming", f"Renaming database to {job.target}",
                    created_at=rename_time
                ))
                event_id += 1
                
                # Complete event
                complete_time = rename_time + timedelta(seconds=random.randint(5, 30))
                duration = random.randint(15, 90)
                job_events.append(create_mock_event(
                    event_id, job.job_id, "complete", f"Restore complete: {size} in {duration}m",
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
                    event_id, job.job_id, "failed", random.choice(errors),
                    created_at=fail_time
                ))
                event_id += 1
            
            events[job.job_id] = job_events
        
        return events

    def get_job_by_id(self, job_id: str) -> MagicMock | None:
        # Search all jobs including active and full history
        all_jobs = self.active_jobs + self.history_jobs
        for job in all_jobs:
            if job.job_id == job_id:
                return job
        return None

    def get_active_jobs(self) -> list[MagicMock]:
        return self.active_jobs

    def get_recent_jobs(
        self,
        limit: int = 50,
        offset: int = 0,
        statuses: list[str] | None = None,
    ) -> list[MagicMock]:
        # History jobs only (completed/failed)
        jobs = self.history_jobs
        if statuses:
            jobs = [j for j in jobs if j.status in statuses]
        return jobs[offset : offset + limit]

    def get_job_events(
        self,
        job_id: str,
        since_id: int | None = None,
    ) -> list[MagicMock]:
        events = self.events.get(job_id, [])
        if since_id:
            events = [e for e in events if e.event_id > since_id]
        return events

    def get_user_recent_jobs(
        self,
        user_id: int,
        limit: int = 5,
    ) -> list[MagicMock]:
        """Get recent jobs for a specific user."""
        user_jobs = [j for j in self.history_jobs if j.owner_user_id == user_id]
        return user_jobs[:limit]

    def enqueue_job(self, job: MagicMock) -> None:
        """Add a new job to the queue (mock implementation)."""
        # Simply add to active jobs list
        self.active_jobs.insert(0, job)
        self.jobs.insert(0, job)
        
        # Generate initial event for the job
        self.events[job.job_id] = [
            create_mock_event(
                event_id=len(self.events) * 10 + 1,
                job_id=job.job_id,
                event_type="created",
                message="Job queued for processing",
                created_at=job.created_at,
            )
        ]

    def get_user_last_job(self, user_code: str) -> MagicMock | None:
        """Get the most recent job for a user by user_code."""
        all_jobs = self.active_jobs + self.history_jobs
        user_jobs = [j for j in all_jobs if j.user_code == user_code]
        if user_jobs:
            return sorted(user_jobs, key=lambda j: j.created_at, reverse=True)[0]
        return None


class MockHostRepo:
    """Mock host repository with sample database hosts."""

    def __init__(self) -> None:
        self.hosts = [
            self._create_host("mysql-staging-01.example.com", port=3306, disabled=False),
            self._create_host("mysql-staging-02.example.com", port=3306, disabled=False),
            self._create_host("mysql-dev.example.com", port=3306, disabled=True),
        ]

    def _create_host(
        self,
        hostname: str,
        port: int = 3306,
        disabled: bool = False,
    ) -> MagicMock:
        host = MagicMock()
        host.id = hostname  # Use hostname as ID for mocks
        host.name = hostname  # Use hostname as display name
        host.hostname = hostname
        host.port = port
        host.disabled = disabled
        host.description = f"MySQL host at {hostname}"
        host.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        host.active_restores = 0
        host.total_restores = 15
        return host

    def list_hosts(self) -> list[MagicMock]:
        """Return all hosts."""
        return self.hosts

    def get_enabled_hosts(self) -> list[MagicMock]:
        """Return only enabled hosts."""
        return [h for h in self.hosts if not h.disabled]


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
        self.user_repo = MockUserRepo()
        self.auth_repo = MockAuthRepo()
        self.host_repo = MockHostRepo()
        self._load_scenario(scenario)
    
    def _load_scenario(self, scenario: str) -> None:
        """Load job data based on scenario."""
        self.current_scenario = scenario
        
        if scenario == "empty":
            self.job_repo = MockJobRepo(active_count=0, history_count=0)
        elif scenario == "busy":
            self.job_repo = MockJobRepo(active_count=15, history_count=100)
            # Override to make most jobs running
            for job in self.job_repo.active_jobs:
                job.status = "running"
                job.current_operation = "Restoring database"
        elif scenario == "all_failed":
            self.job_repo = MockJobRepo(active_count=0, history_count=20)
            # Make all history jobs failed
            for job in self.job_repo.history_jobs:
                job.status = "failed"
                job.error_detail = "Connection timeout during restore"
        elif scenario == "queue_backlog":
            self.job_repo = MockJobRepo(active_count=25, history_count=50)
            # Make most jobs queued
            for i, job in enumerate(self.job_repo.active_jobs):
                if i < 20:
                    job.status = "queued"
                    job.current_operation = "Waiting in queue"
                else:
                    job.status = "running"
                    job.current_operation = "Restoring database"
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
    widgets_dir = Path(__file__).parent.parent / "pulldb" / "web" / "widgets"
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
        filter_target: str | None = None,
    ):
        """Get paginated jobs for LazyTable widget."""
        state: MockAPIState = request.app.state.api_state
        
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
        if filter_user_code:
            user_code_values = set(filter_user_code.split(','))
            filtered = [j for j in filtered if j.owner_user_code in user_code_values]
        if filter_target:
            target_values = set(v.lower() for v in filter_target.split(','))
            filtered = [j for j in filtered if any(tv in (j.target or "").lower() for tv in target_values)]
        
        # Sort
        if sortColumn and sortDirection:
            reverse = sortDirection == "desc"
            sort_keys = {
                "id": lambda j: j.id or "",
                "submitted_at": lambda j: j.submitted_at or datetime.min.replace(tzinfo=UTC),
                "status": lambda j: _get_status_value(j),
                "target": lambda j: j.target or "",
                "user_code": lambda j: j.owner_user_code or "",
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
            rows.append({
                "id": job.id,
                "target": job.target,
                "status": status_val,
                "user_code": job.owner_user_code,
                "submitted_at": job.submitted_at.isoformat() if job.submitted_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "dbhost": job.dbhost,
                "staging_name": job.staging_name,
                "current_operation": job.current_operation,
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
            elif column == "user_code" and job.owner_user_code:
                values.add(job.owner_user_code)
            elif column == "target" and job.target:
                values.add(job.target)
        
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
        all_events.sort(key=lambda e: e.created_at, reverse=True)
        
        for event in all_events[:limit]:
            events.append({
                "timestamp": event.created_at.isoformat(),
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
