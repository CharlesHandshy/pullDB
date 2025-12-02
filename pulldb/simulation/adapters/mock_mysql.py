"""Mock MySQL repositories for Simulation Mode.

Implements the Repository protocols using in-memory dictionaries.
Thread-safe using the shared SimulationState lock.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import typing as t

from pulldb.domain.interfaces import (
    HostRepository,
    JobRepository,
    SettingsRepository,
    UserRepository,
)
from pulldb.domain.models import (
    DBHost,
    Job,
    JobEvent,
    JobStatus,
    MySQLCredentials,
    User,
    UserDetail,
    UserRole,
    UserSummary,
)
from pulldb.simulation.core.state import get_simulation_state

logger = logging.getLogger(__name__)


class SimulatedJobRepository:
    """In-memory implementation of JobRepository."""

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    def enqueue_job(self, job: Job) -> str:
        """Insert new job into queue."""
        with self.state.lock:
            # Ensure ID is set
            if not job.id:
                # Create a new job with a generated ID if one wasn't provided
                # But Job dataclass is frozen, so we assume caller provided a valid Job object
                pass
            
            self.state.jobs[job.id] = job
            self.append_job_event(job.id, "queued", "Job submitted to queue")
            return job.id

    def claim_next_job(self, worker_id: str | None = None) -> Job | None:
        """Atomically claim next queued job for processing."""
        with self.state.lock:
            # Find oldest queued job
            queued_jobs = [
                j for j in self.state.jobs.values() 
                if j.status == JobStatus.QUEUED
            ]
            # Sort by submitted_at
            queued_jobs.sort(key=lambda j: j.submitted_at)

            for job in queued_jobs:
                # Check target exclusivity
                if self._is_target_busy(job.target, job.dbhost):
                    continue
                
                # Claim it
                updated_job = self._update_job_status(
                    job, 
                    JobStatus.RUNNING, 
                    started_at=datetime.now(UTC),
                    worker_id=worker_id
                )
                self.state.jobs[job.id] = updated_job
                self.append_job_event(job.id, "running", f"Job claimed by {worker_id}")
                return updated_job
            
            return None

    def _is_target_busy(self, target: str, dbhost: str) -> bool:
        """Check if any job is running for this target on this host."""
        for job in self.state.jobs.values():
            if (
                job.target == target
                and job.dbhost == dbhost
                and job.status == JobStatus.RUNNING
            ):
                return True
        return False

    def _update_job_status(
        self, 
        job: Job, 
        status: JobStatus, 
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_detail: str | None = None,
        worker_id: str | None = None
    ) -> Job:
        """Helper to create a new Job instance with updated fields."""
        changes: dict[str, t.Any] = {"status": status}
        if started_at:
            changes["started_at"] = started_at
        if completed_at:
            changes["completed_at"] = completed_at
        if error_detail:
            changes["error_detail"] = error_detail
        if worker_id:
            changes["worker_id"] = worker_id
            
        return replace(job, **changes)

    def get_job_by_id(self, job_id: str) -> Job | None:
        """Get job by ID."""
        with self.state.lock:
            return self.state.jobs.get(job_id)

    def find_jobs_by_prefix(self, prefix: str, limit: int = 10) -> list[Job]:
        """Find jobs by ID prefix."""
        with self.state.lock:
            matches = [
                j for j in self.state.jobs.values() 
                if j.id.startswith(prefix)
            ]
            return sorted(matches, key=lambda j: j.submitted_at, reverse=True)[:limit]

    def search_jobs(
        self, query: str, limit: int = 50, exact: bool = False
    ) -> list[Job]:
        """Search jobs by query string."""
        with self.state.lock:
            results = []
            q = query.lower()
            for job in self.state.jobs.values():
                if exact:
                    if query in {job.owner_username, job.owner_user_code, job.target}:
                        results.append(job)
                else:
                    if (
                        q in job.owner_username.lower()
                        or q in job.owner_user_code.lower()
                        or q in job.target.lower()
                    ):
                        results.append(job)
            
            return sorted(results, key=lambda j: j.submitted_at, reverse=True)[:limit]

    def get_last_job_by_user_code(self, user_code: str) -> Job | None:
        """Get the most recent job submitted by a user."""
        with self.state.lock:
            user_jobs = [
                j for j in self.state.jobs.values() 
                if j.owner_user_code == user_code
            ]
            if not user_jobs:
                return None
            return max(user_jobs, key=lambda j: j.submitted_at)

    def mark_job_complete(self, job_id: str) -> None:
        """Mark job as complete."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                updated = self._update_job_status(
                    job, 
                    JobStatus.COMPLETE, 
                    completed_at=datetime.now(UTC)
                )
                self.state.jobs[job_id] = updated
                self.append_job_event(job_id, "complete", "Job completed successfully")

    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                updated = self._update_job_status(
                    job, 
                    JobStatus.FAILED, 
                    completed_at=datetime.now(UTC),
                    error_detail=error
                )
                self.state.jobs[job_id] = updated
                self.append_job_event(job_id, "failed", f"Job failed: {error}")

    def request_cancellation(self, job_id: str) -> bool:
        """Request cancellation of a job."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return False
            if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED):
                return False
            
            # In simulation, we just mark it canceled immediately for now
            updated = self._update_job_status(
                job, 
                JobStatus.CANCELED, 
                completed_at=datetime.now(UTC)
            )
            self.state.jobs[job_id] = updated
            self.append_job_event(job_id, "canceled", "Job cancellation requested")
            return True

    def mark_job_canceled(self, job_id: str, reason: str | None = None) -> None:
        """Mark job as canceled."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                updated = self._update_job_status(
                    job, 
                    JobStatus.CANCELED, 
                    completed_at=datetime.now(UTC),
                    error_detail=reason
                )
                self.state.jobs[job_id] = updated
                self.append_job_event(job_id, "canceled", reason or "Job canceled")

    def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            return job.status == JobStatus.CANCELED if job else False

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running)."""
        with self.state.lock:
            return [
                j for j in self.state.jobs.values() 
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            ]

    def get_recent_jobs(
        self, limit: int = 100, statuses: list[str] | None = None
    ) -> list[Job]:
        """Get recent jobs (active + completed)."""
        with self.state.lock:
            jobs = list(self.state.jobs.values())
            if statuses:
                jobs = [j for j in jobs if j.status.value in statuses]
            
            return sorted(jobs, key=lambda j: j.submitted_at, reverse=True)[:limit]

    def get_user_last_job(self, user_code: str) -> Job | None:
        """Get the most recently submitted job for a user."""
        return self.get_last_job_by_user_code(user_code)

    def get_job_history(
        self,
        limit: int = 100,
        retention_days: int | None = None,
        user_code: str | None = None,
        target: str | None = None,
        dbhost: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """Get historical jobs with optional filtering."""
        with self.state.lock:
            jobs = list(self.state.jobs.values())
            
            if retention_days is not None:
                cutoff = datetime.now(UTC) - timedelta(days=retention_days)
                jobs = [j for j in jobs if j.completed_at and j.completed_at >= cutoff]
            
            if user_code:
                jobs = [j for j in jobs if j.owner_user_code == user_code]
            
            if target:
                jobs = [j for j in jobs if j.target == target]
                
            if dbhost:
                jobs = [j for j in jobs if j.dbhost == dbhost]
                
            if status:
                jobs = [j for j in jobs if j.status.value == status]
                
            return sorted(jobs, key=lambda j: j.completed_at or datetime.min.replace(tzinfo=UTC), reverse=True)[:limit]

    def list_jobs(
        self,
        limit: int = 20,
        active_only: bool = False,
        user_filter: str | None = None,
        dbhost: str | None = None,
        status_filter: str | None = None,
    ) -> list[Job]:
        with self.state.lock:
            jobs = list(self.state.jobs.values())
            
            if active_only:
                jobs = [j for j in jobs if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)]
            elif status_filter:
                jobs = [j for j in jobs if j.status.value == status_filter]
                
            if user_filter:
                q = user_filter.lower()
                jobs = [
                    j for j in jobs 
                    if q in j.owner_username.lower() or q in j.owner_user_code.lower()
                ]
                
            if dbhost:
                jobs = [j for j in jobs if j.dbhost == dbhost]
                
            return sorted(jobs, key=lambda j: j.submitted_at, reverse=True)[:limit]

    def get_jobs_by_user(self, user_id: str) -> list[Job]:
        with self.state.lock:
            return [j for j in self.state.jobs.values() if j.owner_user_id == user_id]

    def find_orphaned_staging_databases(
        self, older_than_hours: int, dbhost: str | None = None
    ) -> list[Job]:
        with self.state.lock:
            cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
            orphans = []
            for job in self.state.jobs.values():
                if (
                    job.staging_name 
                    and job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)
                    and job.completed_at
                    and job.completed_at < cutoff
                ):
                    if dbhost and job.dbhost != dbhost:
                        continue
                    orphans.append(job)
            return orphans

    def mark_staging_cleaned(self, job_id: str) -> None:
        # In simulation, we just assume it's cleaned.
        pass

    def check_target_exclusivity(self, target: str, dbhost: str) -> bool:
        return not self._is_target_busy(target, dbhost)

    def count_active_jobs_for_user(self, user_id: str) -> int:
        with self.state.lock:
            return sum(
                1 for j in self.state.jobs.values() 
                if j.owner_user_id == user_id 
                and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            )

    def count_all_active_jobs(self) -> int:
        with self.state.lock:
            return sum(
                1 for j in self.state.jobs.values() 
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            )
            
    def append_job_event(
        self, job_id: str, event_type: str, detail: str | None = None
    ) -> None:
        with self.state.lock:
            event = JobEvent(
                id=len(self.state.job_events) + 1,
                job_id=job_id,
                event_type=event_type,
                detail=detail,
                logged_at=datetime.now(UTC)
            )
            self.state.job_events.append(event)


class SimulatedUserRepository:
    """In-memory implementation of UserRepository."""

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username."""
        with self.state.lock:
            for user in self.state.users.values():
                if user.username == username:
                    return user
            return None

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        with self.state.lock:
            return self.state.users.get(user_id)

    def create_user(self, username: str, user_code: str) -> User:
        """Create a new user."""
        with self.state.lock:
            user_id = str(uuid.uuid4())
            user = User(
                user_id=user_id,
                username=username,
                user_code=user_code,
                is_admin=False,
                role=UserRole.USER,
                created_at=datetime.now(UTC),
                disabled_at=None
            )
            self.state.users[user_id] = user
            self.state.users_by_code[user_code] = user
            return user

    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create new one."""
        with self.state.lock:
            existing = self.get_user_by_username(username)
            if existing:
                return existing
            
            # Generate code
            code = self.generate_user_code(username)
            return self.create_user(username, code)

    def generate_user_code(self, username: str) -> str:
        """Generate a unique user code."""
        base = "".join(c for c in username if c.isalnum()).lower()[:6]
        while len(base) < 6:
            base += "x"
        
        # Check collision
        if self.check_user_code_exists(base):
            # Append random digit
            base = base[:5] + "1" # Simplified
        return base

    def check_user_code_exists(self, user_code: str) -> bool:
        """Check if user code already exists."""
        with self.state.lock:
            return user_code in self.state.users_by_code

    def get_users_with_job_counts(self) -> list[UserSummary]:
        """Get all users with their active job counts."""
        with self.state.lock:
            summaries = []
            for user in self.state.users.values():
                active_count = sum(
                    1 for j in self.state.jobs.values() 
                    if j.owner_user_id == user.user_id 
                    and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
                )
                summaries.append(UserSummary(user=user, active_jobs_count=active_count))
            return sorted(summaries, key=lambda s: s.user.username)

    def enable_user(self, username: str) -> None:
        """Enable a user."""
        with self.state.lock:
            user = self.get_user_by_username(username)
            if not user:
                raise ValueError(f"User not found: {username}")
            
            updated = replace(user, disabled_at=None)
            self.state.users[user.user_id] = updated

    def disable_user(self, username: str) -> None:
        """Disable a user."""
        with self.state.lock:
            user = self.get_user_by_username(username)
            if not user:
                raise ValueError(f"User not found: {username}")
            
            updated = replace(user, disabled_at=datetime.now(UTC))
            self.state.users[user.user_id] = updated

    def get_user_detail(self, username: str) -> UserDetail | None:
        """Get detailed user info including job stats."""
        with self.state.lock:
            user = self.get_user_by_username(username)
            if not user:
                return None
            
            jobs = [j for j in self.state.jobs.values() if j.owner_user_id == user.user_id]
            return UserDetail(
                user=user,
                total_jobs=len(jobs),
                complete_jobs=sum(1 for j in jobs if j.status == JobStatus.COMPLETE),
                failed_jobs=sum(1 for j in jobs if j.status == JobStatus.FAILED),
                active_jobs=sum(1 for j in jobs if j.status in (JobStatus.QUEUED, JobStatus.RUNNING))
            )


class SimulatedHostRepository:
    """In-memory implementation of HostRepository."""

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        """Get host by hostname."""
        with self.state.lock:
            return self.state.hosts.get(hostname)

    def get_host_by_alias(self, alias: str) -> DBHost | None:
        """Get host by alias."""
        with self.state.lock:
            for host in self.state.hosts.values():
                if host.host_alias == alias:
                    return host
            return None

    def resolve_hostname(self, name: str) -> str | None:
        """Resolve hostname from name or alias."""
        host = self.get_host_by_hostname(name)
        if host:
            return host.hostname
        host = self.get_host_by_alias(name)
        if host:
            return host.hostname
        return None

    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled hosts."""
        with self.state.lock:
            return [h for h in self.state.hosts.values() if h.enabled]

    def get_all_hosts(self) -> list[DBHost]:
        """Get all hosts."""
        with self.state.lock:
            return sorted(self.state.hosts.values(), key=lambda h: h.hostname)

    def get_host_credentials(self, hostname: str) -> MySQLCredentials:
        """Get credentials for a host."""
        # Return mock credentials
        return MySQLCredentials(
            username="mock_user",
            password="mock_password",
            host=hostname,
            port=3306
        )

    def check_host_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for new jobs."""
        with self.state.lock:
            host = self.state.hosts.get(hostname)
            if not host or not host.enabled:
                return False
            
            running = sum(
                1 for j in self.state.jobs.values() 
                if j.dbhost == hostname and j.status == JobStatus.RUNNING
            )
            return running < host.max_concurrent_restores

    def add_host(
        self, hostname: str, max_concurrent: int, credential_ref: str | None
    ) -> None:
        """Add a new host."""
        with self.state.lock:
            if hostname in self.state.hosts:
                raise ValueError(f"Host already exists: {hostname}")
            
            host = DBHost(
                id=len(self.state.hosts) + 1,
                hostname=hostname,
                credential_ref=credential_ref or "mock:creds",
                max_concurrent_restores=max_concurrent,
                enabled=True,
                created_at=datetime.now(UTC)
            )
            self.state.hosts[hostname] = host

    def enable_host(self, hostname: str) -> None:
        """Enable a host."""
        with self.state.lock:
            host = self.state.hosts.get(hostname)
            if not host:
                raise ValueError(f"Host not found: {hostname}")
            
            self.state.hosts[hostname] = replace(host, enabled=True)

    def disable_host(self, hostname: str) -> None:
        """Disable a host."""
        with self.state.lock:
            host = self.state.hosts.get(hostname)
            if not host:
                raise ValueError(f"Host not found: {hostname}")
            
            self.state.hosts[hostname] = replace(host, enabled=False)


class SimulatedSettingsRepository:
    """In-memory implementation of SettingsRepository."""

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    def get_setting(self, key: str) -> str | None:
        """Get a setting value."""
        with self.state.lock:
            return self.state.settings.get(key)

    def get_setting_required(self, key: str) -> str:
        """Get a required setting value."""
        val = self.get_setting(key)
        if val is None:
            raise ValueError(f"Required setting '{key}' not found")
        return val

    def get_max_active_jobs_per_user(self) -> int:
        """Get max active jobs per user setting."""
        val = self.get_setting("max_active_jobs_per_user")
        return int(val) if val else 0

    def get_all_settings(self) -> dict[str, str]:
        """Get all settings."""
        with self.state.lock:
            return self.state.settings.copy()

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Set a setting value."""
        with self.state.lock:
            self.state.settings[key] = value

    def delete_setting(self, key: str) -> bool:
        """Delete a setting."""
        with self.state.lock:
            if key in self.state.settings:
                del self.state.settings[key]
                return True
            return False
