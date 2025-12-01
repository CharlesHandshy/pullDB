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
from fastapi import FastAPI

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pulldb.domain.models import UserRole
from pulldb.web.routes import router as web_router


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
            "alice": create_mock_user(3, "alice", UserRole.USER, user_code="aliceu", created_at=datetime(2023, 6, 15, tzinfo=UTC)),
            "bob": create_mock_user(4, "bob", UserRole.USER, disabled=True, user_code="bobuse", created_at=datetime(2023, 3, 10, tzinfo=UTC)),
        }
        # Set job counts
        self.users["devuser"].active_jobs = 2
        self.users["devuser"].total_jobs = 15
        self.users["devadmin"].active_jobs = 1
        self.users["devadmin"].total_jobs = 8

    def get_user_by_username(self, username: str) -> MagicMock | None:
        return self.users.get(username)

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
        # Password: "PullDB_Dev2025!" for all users
        self.password_hashes = {
            1: "$2b$12$yBnagsAYiWx2reL6Zu/wJezUnOhmVpOM7E6k2m6VfICYxvksQHYOK",
            2: "$2b$12$yBnagsAYiWx2reL6Zu/wJezUnOhmVpOM7E6k2m6VfICYxvksQHYOK",
        }

    def get_password_hash(self, user_id: int) -> str | None:
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

    def __init__(self) -> None:
        # Active jobs (queued/running)
        self.active_jobs = [
            create_mock_job(
                job_id="job-001",
                source_customer="acmehvac",
                status="queued",
                owner_user_id=1,
            ),
            create_mock_job(
                job_id="job-002",
                source_customer="techcorp",
                status="running",
                owner_user_id=1,
                started_at=datetime(2024, 1, 15, 10, 5, 0, tzinfo=UTC),
                worker_id="worker-alpha",
                backup_env="stg",
            ),
            # QA Template job example
            create_mock_job(
                job_id="job-003",
                status="running",
                owner_user_id=1,
                started_at=datetime(2024, 1, 15, 10, 15, 0, tzinfo=UTC),
                worker_id="worker-beta",
                is_qatemplate=True,
            ),
            create_mock_job(
                job_id="job-005",
                source_customer="globalretail",
                status="running",
                owner_user_id=2,
                started_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
                worker_id="worker-gamma",
            ),
        ]
        
        # Generate 400 fake historical jobs
        self.history_jobs = self._generate_history_jobs(400)
        
        # Combine for backward compatibility
        self.jobs = self.active_jobs + self.history_jobs[:10]
        
        # Mock events for jobs
        self.events = self._generate_events()
    
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
        statuses: list[str] | None = None,
    ) -> list[MagicMock]:
        # History jobs only (completed/failed)
        jobs = self.history_jobs
        if statuses:
            jobs = [j for j in jobs if j.status in statuses]
        return jobs[:limit]

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
    """Mock API state with all repositories."""

    def __init__(self) -> None:
        self.user_repo = MockUserRepo()
        self.auth_repo = MockAuthRepo()
        self.job_repo = MockJobRepo()
        self.host_repo = MockHostRepo()


# =============================================================================
# Application Setup
# =============================================================================


def create_dev_app() -> FastAPI:
    """Create FastAPI app with mocked repositories."""
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from pulldb.web.routes import SessionExpiredError, create_session_expired_handler

    app = FastAPI(
        title="pullDB Dev Server",
        description="Development server with mocked data",
    )

    # Store mock state
    app.state.api_state = MockAPIState()

    # Mount static files (images, etc.)
    images_dir = Path(__file__).parent.parent / "pulldb" / "images"
    if images_dir.exists():
        app.mount("/static/images", StaticFiles(directory=str(images_dir)), name="static-images")

    # Include web router
    app.include_router(web_router)
    
    # Register session expired exception handler
    app.add_exception_handler(SessionExpiredError, create_session_expired_handler())

    # Redirect root to login
    @app.get("/")
    async def root():  # noqa: RUF029
        return RedirectResponse(url="/web/login")

    return app


def _mock_get_api_state() -> MockAPIState:
    """Override for get_api_state that returns our mock."""
    import pulldb.api.main as api_main

    return api_main._test_api_state  # type: ignore[attr-defined]


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    """Run the development server."""
    import pulldb.api.main as api_main

    print("\n" + "=" * 60)
    print("  pullDB Development Server")
    print("=" * 60)
    print("\n  Login credentials:")
    print("    Username: devuser    Password: PullDB_Dev2025!")
    print("    Username: devadmin   Password: PullDB_Dev2025!")
    print("\n  Open: http://127.0.0.1:8888/web/login")
    print("=" * 60 + "\n")

    # Create app and store state for the mock
    app = create_dev_app()
    api_main._test_api_state = app.state.api_state  # type: ignore[attr-defined]

    # Patch get_api_state to use our mock
    api_main.get_api_state = _mock_get_api_state  # type: ignore[assignment]

    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="info")


if __name__ == "__main__":
    main()
