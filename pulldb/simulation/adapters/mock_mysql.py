"""Mock MySQL repositories for Simulation Mode.

Implements the Repository protocols using in-memory dictionaries.
Thread-safe using the shared SimulationState lock.

HCA Layer: shared
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from pulldb.domain.errors import LockedUserError
from pulldb.domain.models import (
    DBHost,
    Job,
    JobEvent,
    JobStatus,
    MaintenanceItems,
    MySQLCredentials,
    User,
    UserDetail,
    UserRole,
    UserSummary,
)
from pulldb.simulation.core.bus import EventType, get_event_bus
from pulldb.simulation.core.state import get_simulation_state

logger = logging.getLogger(__name__)


class SimulatedJobRepository:
    """In-memory implementation of JobRepository."""

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()
        self._bus = get_event_bus()

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
            self._bus.emit(
                EventType.JOB_CREATED,
                "SimulatedJobRepository",
                {"target": job.target, "owner": job.owner_username},
                job_id=job.id,
            )
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
                self._bus.emit(
                    EventType.JOB_CLAIMED,
                    "SimulatedJobRepository",
                    {"worker_id": worker_id},
                    job_id=job.id,
                )
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
        changes: dict[str, Any] = {"status": status}
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

    def mark_job_deployed(self, job_id: str) -> bool:
        """Mark job as deployed (database is live).
        
        Clears the worker processing lock (locked_at/locked_by) since
        the database is now available for user actions.
        
        Returns:
            True if job was marked deployed, False if job not found or not running.
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job and job.status == JobStatus.RUNNING:
                updated = self._update_job_status(
                    job, 
                    JobStatus.DEPLOYED, 
                    completed_at=datetime.now(UTC)
                )
                # Clear the worker lock
                updated = replace(updated, locked_at=None, locked_by=None)
                self.state.jobs[job_id] = updated
                self.append_job_event(job_id, "deployed", "Job deployed successfully")
                self._bus.emit(
                    EventType.JOB_COMPLETED,
                    "SimulatedJobRepository",
                    {"target": job.target},
                    job_id=job_id,
                )
                return True
            return False

    def mark_job_user_completed(self, job_id: str) -> None:
        """Mark deployed job as complete (user is done with database)."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job and job.status == JobStatus.DEPLOYED:
                updated = self._update_job_status(
                    job,
                    JobStatus.COMPLETE,
                )
                self.state.jobs[job_id] = updated
                self.append_job_event(job_id, "complete", "User marked job complete")

    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail.
        
        Clears the worker processing lock (locked_at/locked_by/can_cancel)
        since failed jobs should be deletable and no longer need protection.
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                updated = self._update_job_status(
                    job, 
                    JobStatus.FAILED, 
                    completed_at=datetime.now(UTC),
                    error_detail=error
                )
                # Clear the worker lock so failed jobs can be deleted
                updated = replace(updated, locked_at=None, locked_by=None, can_cancel=True)
                self.state.jobs[job_id] = updated
                self.append_job_event(job_id, "failed", f"Job failed: {error}")
                self._bus.emit(
                    EventType.JOB_FAILED,
                    "SimulatedJobRepository",
                    {"target": job.target, "error": error},
                    job_id=job_id,
                )

    def request_cancellation(self, job_id: str) -> bool:
        """Request cancellation of a job.
        
        This sets a flag that the worker should check. It does NOT
        immediately cancel the job - the worker is responsible for
        checking is_cancellation_requested() and calling mark_job_canceled().
        
        Only jobs that are cancelable (status=queued/running AND can_cancel=True)
        can be canceled.
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return False
            if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED):
                return False
            # Check the can_cancel flag - if False, job is in loading phase
            if not job.can_cancel:
                return False
            
            # Set the cancellation flag and timestamp on the job
            now = datetime.now(UTC)
            self.state.cancellation_requested.add(job_id)
            updated = replace(job, cancel_requested_at=now)
            self.state.jobs[job_id] = updated
            self.append_job_event(job_id, "cancellation_requested", "Job cancellation requested")
            return True

    def lock_for_restore(self, job_id: str, worker_id: str) -> bool:
        """Lock job for restore phase, preventing further cancellation.

        Atomically verifies can_cancel=True AND cancel_requested_at IS NULL,
        then sets can_cancel=False, locked_at, locked_by.

        The lock prevents both service and user interruption during Loading
        through Complete. Cleared by mark_job_deployed().

        Args:
            job_id: UUID of the job to lock.
            worker_id: Identifier of the worker locking the job.

        Returns:
            True if lock was acquired (proceed with restore).
            False if job was canceled or cancel requested (abort).
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return False
            # Check gate conditions
            if not job.can_cancel:
                return False
            if job.cancel_requested_at is not None:
                return False
            if job_id in self.state.cancellation_requested:
                return False
            
            # Flip can_cancel and set worker lock
            now = datetime.now(UTC)
            updated = replace(
                job,
                can_cancel=False,
                locked_at=now,
                locked_by=f"worker:{worker_id}",
            )
            self.state.jobs[job_id] = updated
            self.append_job_event(
                job_id,
                "restore_locked",
                f"Job locked for restore by worker:{worker_id}",
            )
            return True

    def mark_job_canceled(self, job_id: str, reason: str | None = None) -> None:
        """Mark job as canceled (called by worker when it honors cancellation)."""
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
                # Clear the cancellation flag
                self.state.cancellation_requested.discard(job_id)
                self.append_job_event(job_id, "canceled", reason or "Job canceled")

    def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job."""
        with self.state.lock:
            return job_id in self.state.cancellation_requested

    def should_abort_job(self, job_id: str) -> bool:
        """Check if a job should be aborted.

        Returns True if:
        - Cancellation was requested
        - Job is no longer in 'running' status (e.g., marked failed by stale recovery)

        This prevents the scenario where stale recovery marks a job as failed
        but the download continues running, wasting resources.
        """
        with self.state.lock:
            if job_id in self.state.cancellation_requested:
                return True
            job = self.state.jobs.get(job_id)
            if not job:
                return True  # Job doesn't exist - abort
            # Abort if not in running/canceling state
            return job.status not in (JobStatus.RUNNING, JobStatus.CANCELING)

    @property
    def active_jobs(self) -> list[Job]:
        """Property alias for get_active_jobs() for dev server compatibility."""
        return self.get_active_jobs()

    @property
    def history_jobs(self) -> list[Job]:
        """Property alias for terminal jobs (complete/failed/canceled).
        
        Used by dev server for pagination. Returns jobs sorted by submitted_at desc.
        """
        with self.state.lock:
            terminal = [
                j for j in self.state.jobs.values()
                if j.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)
            ]
            return sorted(terminal, key=lambda j: j.submitted_at, reverse=True)

    @property
    def _cancel_requested(self) -> dict[str, datetime]:
        """Property for dev server compatibility - returns cancellation timestamps.
        
        Maps job_id -> cancellation request timestamp.
        Note: SimulationState only tracks a set of job_ids, not timestamps.
        """
        with self.state.lock:
            now = datetime.now(UTC)
            return {jid: now for jid in self.state.cancellation_requested}

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running)."""
        with self.state.lock:
            return [
                j for j in self.state.jobs.values() 
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            ]

    def get_recent_jobs(
        self, limit: int = 100, offset: int = 0, statuses: list[str] | None = None
    ) -> list[Job]:
        """Get recent jobs (active + completed)."""
        with self.state.lock:
            jobs = list(self.state.jobs.values())
            if statuses:
                jobs = [j for j in jobs if j.status.value in statuses]
            
            sorted_jobs = sorted(jobs, key=lambda j: j.submitted_at, reverse=True)
            return sorted_jobs[offset : offset + limit]

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
        """Mark that a job's staging database has been cleaned up.
        
        In real MySQL, this might update a 'staging_cleaned_at' column.
        For simulation, we track cleanup via job events since staging_name
        is a required field (cannot be nulled).
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                # Track cleanup via event (staging_name remains for audit)
                self.append_job_event(job_id, "staging_cleaned", f"Staging database {job.staging_name} cleaned up")

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

    def count_active_jobs_for_host(self, hostname: str) -> int:
        """Count active jobs (queued or running) for a specific host."""
        with self.state.lock:
            return sum(
                1 for j in self.state.jobs.values() 
                if j.dbhost == hostname 
                and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            )

    def count_running_jobs_for_host(self, hostname: str) -> int:
        """Count running jobs for a specific host."""
        with self.state.lock:
            return sum(
                1 for j in self.state.jobs.values() 
                if j.dbhost == hostname and j.status == JobStatus.RUNNING
            )

    def get_user_recent_jobs(self, user_id: str, limit: int = 10) -> list[Job]:
        """Get recent jobs for a specific user."""
        with self.state.lock:
            user_jobs = [
                j for j in self.state.jobs.values()
                if j.owner_user_id == user_id
            ]
            return sorted(
                user_jobs, key=lambda j: j.submitted_at, reverse=True
            )[:limit]

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job. Returns True if canceled, False if not found or invalid state."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return False
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                return False

            updated = self._update_job_status(
                job,
                JobStatus.CANCELED,
                completed_at=datetime.now(UTC),
                error_detail="Canceled by user"
            )
            self.state.jobs[job_id] = updated
            self.append_job_event(job_id, "canceled", "Job canceled by user")
            self._bus.emit(
                EventType.JOB_COMPLETED,
                "SimulatedJobRepository",
                {"target": job.target, "status": "canceled"},
                job_id=job_id,
            )
            return True

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

    def get_job_events(
        self, job_id: str, since_id: int | None = None
    ) -> list[JobEvent]:
        """Get events for a job, optionally after a certain event ID."""
        with self.state.lock:
            events = [e for e in self.state.job_events if e.job_id == job_id]
            if since_id is not None:
                events = [e for e in events if e.id > since_id]
            return sorted(events, key=lambda e: e.id)

    def prune_job_events(self, retention_days: int = 90) -> int:
        """Prune old job events. Returns count of deleted events."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        with self.state.lock:
            original_count = len(self.state.job_events)
            self.state.job_events = [
                e for e in self.state.job_events if e.logged_at >= cutoff
            ]
            return original_count - len(self.state.job_events)

    def get_prune_candidates(
        self,
        retention_days: int = 90,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Get paginated list of jobs with events that would be pruned.

        Returns dict with:
        - rows: list of job summaries with event counts
        - totalCount: total jobs affected
        - totalEvents: total events that would be deleted
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        terminal_statuses = (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)

        with self.state.lock:
            # Build lookup of terminal jobs
            terminal_jobs = {
                job_id: job
                for job_id, job in self.state.jobs.items()
                if job.status in terminal_statuses
            }

            # Find jobs with old events
            candidates: list[dict] = []
            total_events = 0

            # Group events by job_id
            events_by_job: dict[str, list[JobEvent]] = {}
            for event in self.state.job_events:
                if event.job_id not in events_by_job:
                    events_by_job[event.job_id] = []
                events_by_job[event.job_id].append(event)

            for job_id, events in events_by_job.items():
                # Only consider terminal jobs
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
                "rows": candidates[offset : offset + limit],
                "totalCount": len(candidates),
                "totalEvents": total_events,
            }

    def prune_job_events_by_ids(self, job_ids: list[str]) -> int:
        """Prune all events for specific job IDs. Returns count deleted.

        This removes ALL events for the specified jobs, regardless of age.
        Used by the prune-logs UI when user selects specific jobs to purge.
        """
        with self.state.lock:
            original_count = len(self.state.job_events)
            self.state.job_events = [
                e for e in self.state.job_events if e.job_id not in job_ids
            ]
            return original_count - len(self.state.job_events)

    def prune_job_events_excluding(
        self,
        retention_days: int = 90,
        exclude_job_ids: list[str] | None = None,
    ) -> int:
        """Prune old job events, excluding specified job IDs. Returns count deleted.

        Deletes events older than retention_days for terminal jobs,
        EXCEPT for jobs in the exclude list.
        """
        exclude_job_ids = exclude_job_ids or []
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        terminal_statuses = (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)

        with self.state.lock:
            # Build lookup of terminal jobs
            terminal_job_ids = {
                job_id
                for job_id, job in self.state.jobs.items()
                if job.status in terminal_statuses
            }

            original_count = len(self.state.job_events)
            self.state.job_events = [
                e
                for e in self.state.job_events
                if not (
                    e.job_id in terminal_job_ids
                    and e.job_id not in exclude_job_ids
                    and e.logged_at < cutoff
                )
            ]
            return original_count - len(self.state.job_events)

    # ==================== Additional Methods for Real Parity ====================

    def find_job_by_staging_prefix(
        self, target: str, dbhost: str, job_id_prefix: str
    ) -> Job | None:
        """Find a job by its staging database prefix.

        Used by scheduled cleanup to match staging databases to jobs.
        """
        with self.state.lock:
            for job in self.state.jobs.values():
                if (
                    job.target == target
                    and job.dbhost == dbhost
                    and job.id.startswith(job_id_prefix)
                ):
                    return job
            return None

    def get_job_completion_time(self, job_id: str) -> datetime | None:
        """Get the completion time of a job from events.

        Looks for the last terminal event (complete, failed, canceled).
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job and job.completed_at:
                return job.completed_at
            
            # Fall back to events
            terminal_events = [
                e for e in self.state.job_events
                if e.job_id == job_id and e.event_type in ('complete', 'failed', 'canceled')
            ]
            if terminal_events:
                return max(terminal_events, key=lambda e: e.id).logged_at
            return None

    def has_active_jobs_for_target(self, target: str, dbhost: str) -> bool:
        """Check if there are any active (queued/running) jobs for a target.

        Used as a safety check before scheduled cleanup drops staging databases.
        """
        with self.state.lock:
            return any(
                j.target == target
                and j.dbhost == dbhost
                and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
                for j in self.state.jobs.values()
            )

    def get_old_terminal_jobs(self, dbhost: str, cutoff_date: datetime) -> list[Job]:
        """Get terminal jobs older than cutoff date for a specific host.

        Used by scheduled cleanup to find jobs whose staging databases
        may need cleanup.
        """
        with self.state.lock:
            return [
                job for job in self.state.jobs.values()
                if job.dbhost == dbhost
                and job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)
                and job.staging_name
                and job.completed_at
                and job.completed_at < cutoff_date
            ]

    def get_cleanup_candidates(
        self,
        retention_days: int = 7,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Get paginated list of staging databases eligible for cleanup.

        Returns dict with:
        - rows: list of staging database candidates
        - totalCount: total databases that would be cleaned up

        A database is a candidate if:
        - Job is in terminal state (complete/failed/canceled)
        - Job has staging_name set
        - Job's staging_cleaned_at is None (not yet cleaned)
        - Job completed more than retention_days ago
        - No active jobs exist for the same target (safety check)
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        terminal_statuses = (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELED)

        with self.state.lock:
            # Find active targets to exclude (safety check)
            active_targets: set[tuple[str, str]] = set()
            for job in self.state.jobs.values():
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    active_targets.add((job.target, job.dbhost))

            candidates: list[dict] = []
            for job in self.state.jobs.values():
                # Must be terminal
                if job.status not in terminal_statuses:
                    continue
                # Must have staging_name
                if not job.staging_name:
                    continue
                # Must not be already cleaned
                staging_cleaned = getattr(job, "staging_cleaned_at", None)
                if staging_cleaned is not None:
                    continue
                # Must be old enough
                if not job.completed_at or job.completed_at >= cutoff:
                    continue
                # Safety: skip if active job for same target
                if (job.target, job.dbhost) in active_targets:
                    continue

                candidates.append({
                    "database_name": job.staging_name,
                    "target": job.target,
                    "dbhost": job.dbhost,
                    "job_id": job.id,
                    "job_status": job.status.value,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "user_code": job.owner_user_code,
                })

            # Sort by completed_at (oldest first)
            candidates.sort(key=lambda x: x["completed_at"] or "")

            return {
                "rows": candidates[offset : offset + limit],
                "totalCount": len(candidates),
            }

    def cleanup_staging_by_names(
        self,
        database_names: list[str],
    ) -> dict:
        """Clean up staging databases by name (mock simulation).

        Marks jobs as cleaned by setting staging_cleaned_at.
        Includes safety check for active jobs on same target.

        Returns dict with:
        - dropped_count: number of databases "dropped"
        - skipped_count: number skipped due to safety checks
        - errors: list of error messages
        """
        dropped_count = 0
        skipped_count = 0
        errors: list[str] = []

        if not database_names:
            return {
                "dropped_count": dropped_count,
                "skipped_count": skipped_count,
                "errors": errors,
            }

        with self.state.lock:
            # Find active targets to exclude (safety check)
            active_targets: set[tuple[str, str]] = set()
            for job in self.state.jobs.values():
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    active_targets.add((job.target, job.dbhost))

            # Find jobs matching the database names
            for job_id, job in self.state.jobs.items():
                if job.staging_name not in database_names:
                    continue

                # Safety check: skip if active job for same target
                if (job.target, job.dbhost) in active_targets:
                    skipped_count += 1
                    errors.append(
                        f"Skipped {job.staging_name}: active job for target {job.target}"
                    )
                    continue

                # Check not already cleaned
                if job.staging_cleaned_at is not None:
                    continue

                # "Drop" the database by marking job as cleaned
                # Note: Job is frozen dataclass, so we need to replace it
                updated_job = replace(job, staging_cleaned_at=datetime.now(UTC))
                self.state.jobs[job_id] = updated_job

                # Log event
                self.append_job_event(
                    job_id=job_id,
                    event_type="staging_admin_cleanup",
                    detail="Dropped by admin cleanup action (simulation)",
                )

                dropped_count += 1

        return {
            "dropped_count": dropped_count,
            "skipped_count": skipped_count,
            "errors": errors,
        }

    def mark_job_staging_cleaned(self, job_id: str) -> None:
        """Mark a job's staging database as cleaned.

        Sets staging_cleaned_at to current time.
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return

            updated_job = replace(job, staging_cleaned_at=datetime.now(UTC))
            self.state.jobs[job_id] = updated_job

    # ==================== Database Retention & Lifecycle Methods ====================

    def count_jobs_by_host(self, hostname: str) -> int:
        """Count total jobs (all statuses) for a specific host."""
        with self.state.lock:
            return sum(1 for j in self.state.jobs.values() if j.dbhost == hostname)

    def count_jobs_by_user(self, user_code: str) -> int:
        """Count total jobs (all statuses) for a specific user."""
        with self.state.lock:
            return sum(1 for j in self.state.jobs.values() if j.owner_user_code == user_code)

    def get_all_locked_databases(self) -> list[Job]:
        """Get all locked databases across all users (manager report)."""
        with self.state.lock:
            locked = [
                j for j in self.state.jobs.values()
                if j.locked_at is not None and j.db_dropped_at is None
            ]
            return sorted(locked, key=lambda j: (j.owner_username, j.locked_at or datetime.min.replace(tzinfo=UTC)))

    def get_cancel_requested_at(self, job_id: str) -> datetime | None:
        """Get the timestamp when cancellation was requested for a job."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            return job.cancel_requested_at if job else None

    def get_current_operation(self, job_id: str) -> str | None:
        """Get user-friendly current operation string for a job."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return None
            
            # Get latest event
            job_events = [e for e in self.state.job_events if e.job_id == job_id]
            if job_events:
                latest = max(job_events, key=lambda e: e.id)
                event_type = latest.event_type
                detail = latest.detail or ""
                
                # Map event types to user-friendly strings
                if event_type == "download_progress":
                    return f"Downloading({detail})"
                elif event_type == "restore_progress":
                    return f"Restoring({detail})"
                elif event_type == "restore_started":
                    return "Restoring"
                elif event_type == "download_started":
                    return "Downloading"
                elif event_type == "queued":
                    return "Queued"
                elif event_type == "running":
                    return "Starting"
                elif event_type == "deployed":
                    return "Deployed"
                elif event_type == "failed":
                    return "Failed"
                elif event_type == "canceled":
                    return "Canceled"
            
            # Fallback to status
            return job.status.value.capitalize()

    def get_deployed_job_for_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Get the deployed job for a target+host+user if one exists."""
        with self.state.lock:
            for job in self.state.jobs.values():
                if (
                    job.target == target
                    and job.dbhost == dbhost
                    and job.owner_user_id == owner_user_id
                    and job.status == JobStatus.DEPLOYED
                    and job.superseded_at is None
                    and job.db_dropped_at is None
                ):
                    return job
            return None

    def has_any_deployed_job_for_target(
        self, target: str, dbhost: str
    ) -> Job | None:
        """Check if ANY user has a deployed job for this target+host.
        
        Cross-user check - no owner_user_id filter. Used for deletion protection.
        """
        with self.state.lock:
            for job in self.state.jobs.values():
                if (
                    job.target == target
                    and job.dbhost == dbhost
                    and job.status == JobStatus.DEPLOYED
                    and job.superseded_at is None
                    and job.db_dropped_at is None
                ):
                    return job
            return None

    def has_any_locked_job_for_target(
        self, target: str, dbhost: str
    ) -> Job | None:
        """Check if ANY user has a locked job for this target+host.
        
        Cross-user check - no owner_user_id filter. Used for deletion protection.
        """
        with self.state.lock:
            for job in self.state.jobs.values():
                if (
                    job.target == target
                    and job.dbhost == dbhost
                    and job.locked_at is not None
                    and job.superseded_at is None
                    and job.db_dropped_at is None
                ):
                    return job
            return None

    def get_job_history_v2(
        self,
        limit: int = 100,
        retention_days: int | None = None,
        user_code: str | None = None,
        target: str | None = None,
        dbhost: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """Get historical jobs (History view)."""
        history_statuses = (
            JobStatus.FAILED, JobStatus.CANCELED, JobStatus.COMPLETE,
            # Also include deleted/deleting/expired/superseded if they exist
        )
        with self.state.lock:
            jobs = [
                j for j in self.state.jobs.values()
                if j.status in history_statuses or j.status.value in (
                    'deleted', 'deleting', 'expired', 'superseded'
                )
            ]
            
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
            
            return sorted(
                jobs, 
                key=lambda j: j.completed_at or datetime.min.replace(tzinfo=UTC), 
                reverse=True
            )[:limit]

    def get_latest_completed_job_for_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Get the most recent completed job for a target+host+user."""
        with self.state.lock:
            completed = [
                j for j in self.state.jobs.values()
                if (
                    j.target == target
                    and j.dbhost == dbhost
                    and j.owner_user_id == owner_user_id
                    and j.status == JobStatus.COMPLETE
                    and j.superseded_at is None
                )
            ]
            if not completed:
                return None
            return max(completed, key=lambda j: j.completed_at or datetime.min.replace(tzinfo=UTC))

    def get_locked_by_target(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Find a locked job for a specific target+host+user combination."""
        with self.state.lock:
            for job in self.state.jobs.values():
                if (
                    job.target == target
                    and job.dbhost == dbhost
                    and job.owner_user_id == owner_user_id
                    and job.locked_at is not None
                    and job.db_dropped_at is None
                    and job.superseded_at is None
                ):
                    return job
            return None

    def get_expired_cleanup_candidates(self, grace_days: int) -> list[Job]:
        """Get jobs eligible for automatic database cleanup.

        Returns deployed jobs that are:
        - Past expiration + grace period
        - Not locked
        - Database not already dropped
        - Not superseded

        Args:
            grace_days: Additional days after expiry before cleanup.

        Returns:
            List of jobs whose databases can be dropped.
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=grace_days)
        candidates: list[Job] = []

        with self.state.lock:
            for job in self.state.jobs.values():
                if (
                    job.status == JobStatus.DEPLOYED
                    and job.locked_at is None
                    and job.db_dropped_at is None
                    and job.superseded_at is None
                    and job.expires_at is not None
                    and job.expires_at < cutoff
                ):
                    candidates.append(job)

        # Sort by expires_at ascending (oldest first)
        return sorted(candidates, key=lambda j: j.expires_at or datetime.min.replace(tzinfo=UTC))

    def get_maintenance_items(
        self, user_id: str, notice_days: int, grace_days: int
    ) -> "MaintenanceItems":
        """Get maintenance items for a user's daily modal."""
        from pulldb.domain.models import MaintenanceItems

        expired: list[Job] = []
        expiring: list[Job] = []
        locked: list[Job] = []

        with self.state.lock:
            for job in self.state.jobs.values():
                if (
                    job.owner_user_id != user_id
                    or job.status != JobStatus.DEPLOYED
                    or job.db_dropped_at is not None
                    or job.superseded_at is not None
                ):
                    continue
                
                if job.is_locked and job.is_expired:
                    locked.append(job)
                elif job.is_expired:
                    expired.append(job)
                elif job.is_expiring(notice_days):
                    expiring.append(job)

        return MaintenanceItems(expired=expired, expiring=expiring, locked=locked)

    def get_owned_databases(
        self,
        limit: int = 100,
        user_code: str | None = None,
        target: str | None = None,
        dbhost: str | None = None,
    ) -> list[Job]:
        """Get databases user currently owns (Active view)."""
        active_statuses = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DEPLOYED)
        # Also include 'canceling' if it exists as a status
        
        with self.state.lock:
            jobs = [
                j for j in self.state.jobs.values()
                if j.status in active_statuses or j.status.value == 'canceling'
            ]
            
            if user_code:
                jobs = [j for j in jobs if j.owner_user_code == user_code]
            if target:
                jobs = [j for j in jobs if j.target == target]
            if dbhost:
                jobs = [j for j in jobs if j.dbhost == dbhost]
            
            return sorted(jobs, key=lambda j: j.submitted_at, reverse=True)[:limit]

    def get_user_active_databases(self, user_id: str) -> list[Job]:
        """Get all active (non-dropped, non-superseded) databases for a user."""
        with self.state.lock:
            jobs = [
                j for j in self.state.jobs.values()
                if (
                    j.owner_user_id == user_id
                    and j.status == JobStatus.COMPLETE
                    and j.db_dropped_at is None
                    and j.superseded_at is None
                )
            ]
            
            # Sort by: locked first, then expiring soon, then others
            def sort_key(j: Job) -> tuple[int, datetime]:
                if j.locked_at is not None:
                    priority = 0
                elif j.expires_at and j.expires_at < datetime.now(UTC) + timedelta(days=7):
                    priority = 1
                else:
                    priority = 2
                return (priority, j.expires_at or datetime.max.replace(tzinfo=UTC))
            
            return sorted(jobs, key=sort_key)

    def get_user_target_databases(self, user_id: str) -> list[dict[str, str]]:
        """Get unique target databases created by a user."""
        with self.state.lock:
            seen: set[tuple[str, str]] = set()
            results: list[dict[str, str]] = []
            
            for job in self.state.jobs.values():
                if job.owner_user_id == user_id:
                    key = (job.target, job.dbhost)
                    if key not in seen:
                        seen.add(key)
                        results.append({"name": job.target, "host": job.dbhost})
            
            return sorted(results, key=lambda x: (x["name"], x["host"]))

    def hard_delete_job(self, job_id: str) -> bool:
        """Hard delete a job record and its events."""
        with self.state.lock:
            if job_id not in self.state.jobs:
                return False
            
            # Delete events first
            self.state.job_events = [
                e for e in self.state.job_events if e.job_id != job_id
            ]
            # Delete the job
            del self.state.jobs[job_id]
            return True

    def has_restore_started(self, job_id: str) -> bool:
        """Check if myloader restore has started for a job."""
        with self.state.lock:
            return any(
                e.job_id == job_id and e.event_type == 'restore_started'
                for e in self.state.job_events
            )

    def lock_job(self, job_id: str, locked_by: str) -> bool:
        """Lock a job's database to protect from cleanup and overwrites."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job or job.locked_at is not None:
                return False
            
            updated = replace(job, locked_at=datetime.now(UTC), locked_by=locked_by)
            self.state.jobs[job_id] = updated
            return True

    def unlock_job(self, job_id: str) -> bool:
        """Unlock a job's database."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job or job.locked_at is None:
                return False
            
            updated = replace(job, locked_at=None, locked_by=None)
            self.state.jobs[job_id] = updated
            return True

    def mark_db_dropped(self, job_id: str) -> None:
        """Mark that the actual database was dropped from target host."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                updated = replace(job, db_dropped_at=datetime.now(UTC))
                self.state.jobs[job_id] = updated

    def mark_job_canceling(self, job_id: str) -> bool:
        """Transition a running job to canceling state."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job or job.status != JobStatus.RUNNING:
                return False
            
            # Use 'canceling' status if available, otherwise use CANCELED
            try:
                canceling_status = JobStatus('canceling')
            except ValueError:
                canceling_status = JobStatus.CANCELED
            
            updated = replace(
                job, 
                status=canceling_status,
                cancel_requested_at=datetime.now(UTC)
            )
            self.state.jobs[job_id] = updated
            return True

    def mark_job_deleted(self, job_id: str, detail: str | None = None) -> None:
        """Mark job as deleted (soft delete complete)."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                # Use 'deleted' status if available
                try:
                    deleted_status = JobStatus('deleted')
                except ValueError:
                    deleted_status = JobStatus.CANCELED  # fallback
                
                error_detail = detail or "Databases deleted by user"
                updated = replace(
                    job,
                    status=deleted_status,
                    completed_at=job.completed_at or datetime.now(UTC),
                    error_detail=error_detail,
                )
                self.state.jobs[job_id] = updated

    def mark_job_deleting(self, job_id: str) -> None:
        """Mark job as deleting (async delete in progress)."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                # Use 'deleting' status if available
                try:
                    deleting_status = JobStatus('deleting')
                except ValueError:
                    deleting_status = JobStatus.CANCELED  # fallback
                
                updated = replace(
                    job,
                    status=deleting_status,
                    started_at=datetime.now(UTC),
                    worker_id=None,
                    retry_count=job.retry_count + 1,
                )
                self.state.jobs[job_id] = updated
                
                # Log event
                self.append_job_event(
                    job_id, "delete_started", f'{{"attempt": {updated.retry_count}}}'
                )

    def claim_stale_deleting_job(
        self,
        worker_id: str | None = None,
        stale_timeout_minutes: int = 5,
        max_retry_count: int = 5,
    ) -> Job | None:
        """Atomically claim a stale job stuck in 'deleting' status.
        
        Only claims jobs that are the NEWEST for their target+owner_user_code.
        Older superseded jobs have already had their DBs cleaned up.
        """
        with self.state.lock:
            cutoff = datetime.now(UTC) - timedelta(minutes=stale_timeout_minutes)
            
            # Find stale deleting jobs
            candidates = [
                j for j in self.state.jobs.values()
                if j.status == JobStatus.DELETING
                and j.started_at
                and j.started_at < cutoff
                and j.retry_count < max_retry_count
            ]
            
            if not candidates:
                return None
            
            # Filter to only include jobs that are newest for their target+owner
            def is_newest_for_target(job: Job) -> bool:
                """Check if this job is the newest for its target+owner_user_code."""
                for other in self.state.jobs.values():
                    if (other.target == job.target 
                        and other.owner_user_code == job.owner_user_code
                        and other.submitted_at > job.submitted_at):
                        return False
                return True
            
            candidates = [j for j in candidates if is_newest_for_target(j)]
            
            if not candidates:
                return None
            
            # Take oldest
            candidates.sort(key=lambda j: j.started_at or datetime.min.replace(tzinfo=UTC))
            job = candidates[0]
            
            new_retry = job.retry_count + 1
            updated = replace(
                job,
                started_at=datetime.now(UTC),
                worker_id=worker_id,
                retry_count=new_retry,
            )
            self.state.jobs[job.id] = updated
            
            # Log event
            self.append_job_event(
                job.id,
                "delete_retry",
                f'{{"attempt": {new_retry}, "reclaimed_by": "{worker_id}"}}'
            )
            
            return updated

    def mark_job_delete_failed(
        self, job_id: str, error_detail: str | None = None
    ) -> None:
        """Mark job as failed after exhausting delete retry attempts."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                detail = error_detail or "Delete failed after 5 attempts"
                updated = replace(
                    job,
                    status=JobStatus.FAILED,
                    completed_at=job.completed_at or datetime.now(UTC),
                    error_detail=detail,
                )
                self.state.jobs[job_id] = updated
                
                # Log event
                self.append_job_event(
                    job_id, "delete_failed", f'{{"reason": "{detail}"}}'
                )

    # Constants for stale running job recovery (mirroring real JobRepository)
    STALE_RUNNING_TIMEOUT_MINUTES: ClassVar[int] = 15
    STALE_RUNNING_PROCESS_CHECK_COUNT: ClassVar[int] = 3
    STALE_RUNNING_PROCESS_CHECK_DELAY_SECONDS: ClassVar[float] = 2.0

    def get_candidate_stale_running_job(
        self,
        stale_timeout_minutes: int | None = None,
    ) -> Job | None:
        """Find a candidate stale running job without claiming it.

        Jobs in 'running' status that have had no recent activity (job_events)
        for longer than the timeout may be from crashed workers. Returns a
        candidate for verification.

        IMPORTANT: Staleness is determined by the most recent job_event, NOT
        by started_at. This prevents false positives during long downloads
        where progress events are being logged regularly.
        """
        if stale_timeout_minutes is None:
            stale_timeout_minutes = self.STALE_RUNNING_TIMEOUT_MINUTES

        with self.state.lock:
            cutoff = datetime.now(UTC) - timedelta(minutes=stale_timeout_minutes)

            def get_last_activity(job: Job) -> datetime:
                """Get the most recent activity time for a job.

                Returns the latest of:
                - Most recent job_event logged_at
                - started_at (fallback if no events)
                """
                job_events = [e for e in self.state.job_events if e.job_id == job.id]
                if job_events:
                    # Sort by logged_at descending and get the most recent
                    most_recent = max(job_events, key=lambda e: e.logged_at)
                    return most_recent.logged_at
                # Fallback to started_at
                return job.started_at or datetime.min.replace(tzinfo=UTC)

            # Find running jobs with no recent activity
            candidates = [
                j for j in self.state.jobs.values()
                if j.status == JobStatus.RUNNING
                and j.started_at
                and get_last_activity(j) < cutoff
            ]

            if not candidates:
                return None

            # Filter to only include jobs that are newest for their target+owner
            def is_newest_for_target(job: Job) -> bool:
                """Check if this job is the newest for its target+owner_user_code."""
                for other in self.state.jobs.values():
                    if (other.target == job.target
                        and other.owner_user_code == job.owner_user_code
                        and other.submitted_at > job.submitted_at):
                        return False
                return True

            candidates = [j for j in candidates if is_newest_for_target(j)]

            if not candidates:
                return None

            # Return oldest candidate by last activity (don't modify it)
            candidates.sort(key=get_last_activity)
            return candidates[0]

    def mark_stale_running_failed(
        self,
        job_id: str,
        worker_id: str | None = None,
        error_detail: str | None = None,
    ) -> bool:
        """Mark a stale running job as failed after verification.

        Only updates if job is still in 'running' status.

        Returns:
            True if job was marked failed, False if not found or already transitioned.
        """
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return False

            # Only mark if still running
            if job.status != JobStatus.RUNNING:
                return False

            detail = error_detail or "Worker died during restore (stale job recovery)"
            updated = replace(
                job,
                status=JobStatus.FAILED,
                completed_at=datetime.now(UTC),
                error_detail=detail,
                worker_id=worker_id or job.worker_id,
            )
            self.state.jobs[job_id] = updated

            # Log event
            event_detail = json.dumps({
                "reason": "stale_job_recovery",
                "recovered_by": worker_id,
                "error_detail": detail,
            })
            self.append_job_event(job_id, "stale_running_recovery", event_detail)

            return True

    def mark_job_expired(self, job_id: str) -> bool:
        """Mark deployed job as expired when retention period has passed."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if not job:
                return False
            if job.status != JobStatus.DEPLOYED:
                return False
            if not job.expires_at or job.expires_at > datetime.now(UTC):
                return False
            
            # Use 'expired' status if available
            try:
                expired_status = JobStatus('expired')
            except ValueError:
                expired_status = JobStatus.COMPLETE  # fallback
            
            updated = replace(job, status=expired_status)
            self.state.jobs[job_id] = updated
            return True

    def mark_jobs_expired_batch(self, job_ids: list[str]) -> int:
        """Mark multiple deployed jobs as expired in a single transaction."""
        count = 0
        for job_id in job_ids:
            if self.mark_job_expired(job_id):
                count += 1
        return count

    def set_job_expiration(self, job_id: str, expires_at: datetime) -> None:
        """Set expiration date for a job's database."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                updated = replace(job, expires_at=expires_at)
                self.state.jobs[job_id] = updated

    def supersede_job(self, job_id: str, superseded_by_job_id: str) -> None:
        """Mark a job as superseded by a newer restore to the same target."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job:
                # Use 'superseded' status if available
                try:
                    superseded_status = JobStatus('superseded')
                except ValueError:
                    superseded_status = JobStatus.COMPLETE  # fallback
                
                now = datetime.now(UTC)
                updated = replace(
                    job,
                    superseded_at=now,
                    superseded_by_job_id=superseded_by_job_id,
                    status=superseded_status,
                    expires_at=now + timedelta(days=7),
                    db_dropped_at=now,
                )
                self.state.jobs[job_id] = updated


class SimulatedUserRepository:
    """In-memory implementation of UserRepository.
    
    Thread-safe using RLock (reentrant lock) from SimulationState.
    All public methods acquire the lock, and since RLock allows the same
    thread to re-acquire, methods can safely call each other without deadlock.
    """

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    # ==================== Locked User Guards ====================

    def _check_user_not_locked(self, user_id: str, action: str) -> None:
        """Raise LockedUserError if user is locked.
        
        Must be called with state.lock held.
        """
        user = self.state.users.get(user_id)
        if user and user.locked_at is not None:
            raise LockedUserError(user.username, action)

    def _check_user_not_locked_by_username(self, username: str, action: str) -> None:
        """Raise LockedUserError if user is locked (by username).
        
        Must be called with state.lock held.
        """
        for user in self.state.users.values():
            if user.username == username and user.locked_at is not None:
                raise LockedUserError(user.username, action)

    # ==================== Public API ====================

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username with allowed_hosts populated."""
        from dataclasses import replace

        with self.state.lock:
            for user in self.state.users.values():
                if user.username == username:
                    # Populate allowed_hosts and default_host from user_hosts
                    user_hosts = self.state.user_hosts.get(user.user_id, [])
                    allowed_hosts: list[str] = []
                    default_host: str | None = None

                    for uh in user_hosts:
                        host_id = uh['host_id']
                        host = next(
                            (h for h in self.state.hosts.values() if str(h.id) == host_id),
                            None
                        )
                        if host:
                            # Use canonical hostname, not alias
                            allowed_hosts.append(host.hostname)
                            if uh.get('is_default'):
                                default_host = host.hostname

                    # Return user with hosts populated
                    return replace(
                        user,
                        allowed_hosts=allowed_hosts if allowed_hosts else None,
                        default_host=default_host,
                    )
            return None

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID with allowed_hosts populated."""
        from dataclasses import replace

        with self.state.lock:
            user = self.state.users.get(user_id)
            if not user:
                return None

            # Populate allowed_hosts and default_host from user_hosts
            user_hosts = self.state.user_hosts.get(user_id, [])
            allowed_hosts: list[str] = []
            default_host: str | None = None

            for uh in user_hosts:
                host_id = uh['host_id']
                host = next(
                    (h for h in self.state.hosts.values() if str(h.id) == host_id),
                    None
                )
                if host:
                    # Use canonical hostname, not alias
                    allowed_hosts.append(host.hostname)
                    if uh.get('is_default'):
                        default_host = host.hostname

            return replace(
                user,
                allowed_hosts=allowed_hosts if allowed_hosts else None,
                default_host=default_host,
            )

    def generate_user_code(self, username: str) -> str:
        """Generate a unique user code with collision handling."""
        import random
        
        with self.state.lock:
            base = "".join(c for c in username if c.isalnum()).lower()[:6]
            while len(base) < 6:
                base += "x"
            
            # Check collision with retry logic (max 100 attempts)
            candidate = base
            for _ in range(100):
                if candidate not in self.state.users_by_code:
                    return candidate
                # Generate new candidate: base[:5] + random alphanumeric
                suffix = random.choice('0123456789abcdefghijklmnopqrstuvwxyz')
                candidate = base[:5] + suffix
            
            # Final fallback: use UUID suffix
            return str(uuid.uuid4())[:6]

    def create_user(self, username: str, user_code: str, manager_id: str | None = None) -> User:
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
                disabled_at=None,
                manager_id=manager_id
            )
            self.state.users[user_id] = user
            self.state.users_by_code[user_code] = user
            return user

    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create new one.
        
        Safe to call other public methods since we use RLock (reentrant).
        """
        with self.state.lock:
            existing = self.get_user_by_username(username)
            if existing:
                return existing
            
            code = self.generate_user_code(username)
            return self.create_user(username, code)

    def create_user_with_code(self, username: str) -> User:
        """Create new user with auto-generated user_code.

        Unlike get_or_create_user, this method does NOT check for existing users.
        It always attempts to create a new user.

        Args:
            username: Username for the new user.

        Returns:
            Newly created User instance.

        Raises:
            ValueError: If user_code cannot be generated or username invalid.
        """
        with self.state.lock:
            code = self.generate_user_code(username)
            return self.create_user(username, code)

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
            self._check_user_not_locked_by_username(username, "enable")
            user = self.get_user_by_username(username)
            if not user:
                raise ValueError(f"User not found: {username}")
            
            updated = replace(user, disabled_at=None)
            self.state.users[user.user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

    def disable_user(self, username: str) -> None:
        """Disable a user."""
        with self.state.lock:
            self._check_user_not_locked_by_username(username, "disable")
            user = self.get_user_by_username(username)
            if not user:
                raise ValueError(f"User not found: {username}")
            
            updated = replace(user, disabled_at=datetime.now(UTC))
            self.state.users[user.user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

    def enable_user_by_id(self, user_id: str) -> None:
        """Enable a user by ID."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "enable")
            user = self.state.users.get(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")
            
            updated = replace(user, disabled_at=None)
            self.state.users[user.user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

    def disable_user_by_id(self, user_id: str) -> None:
        """Disable a user by ID."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "disable")
            user = self.state.users.get(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")
            
            updated = replace(user, disabled_at=datetime.now(UTC))
            self.state.users[user.user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

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

    def list_users(self) -> list[User]:
        """Get all users."""
        with self.state.lock:
            return sorted(self.state.users.values(), key=lambda u: u.username)

    def get_users_managed_by(self, manager_id: str) -> list[User]:
        """Get all users managed by a specific manager.
        
        Excludes SERVICE role accounts and locked users.
        """
        with self.state.lock:
            managed = [
                user for user in self.state.users.values()
                if user.manager_id == manager_id
                and user.role != UserRole.SERVICE
                and user.locked_at is None
            ]
            return sorted(managed, key=lambda u: u.username)

    def set_user_manager(self, user_id: str, manager_id: str | None) -> None:
        """Set or clear the manager for a user."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "set manager for")
            user = self.state.users.get(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")
            
            updated = replace(user, manager_id=manager_id)
            self.state.users[user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

    def update_user_role(self, user_id: str, role: UserRole) -> None:
        """Update a user's role."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "update role for")
            user = self.state.users.get(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")
            
            updated = replace(user, role=role)
            self.state.users[user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

    def delete_user(self, user_id: str) -> dict[str, int]:
        """Delete a user and all related records.
        
        Users with ANY jobs cannot be deleted (preserves history).
        """
        with self.state.lock:
            self._check_user_not_locked(user_id, "delete")
            user = self.state.users.get(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")
            
            # Check for any jobs
            job_count = sum(
                1 for j in self.state.jobs.values()
                if j.owner_user_id == user_id
            )
            if job_count > 0:
                raise ValueError(
                    f"Cannot delete user with {job_count} job(s) in history. "
                    "Use 'disable user' instead to preserve job history."
                )
            
            # Clear manager_id for managed users
            managed_users_updated = 0
            for uid, u in list(self.state.users.items()):
                if u.manager_id == user_id:
                    updated = replace(u, manager_id=None)
                    self.state.users[uid] = updated
                    if u.user_code in self.state.users_by_code:
                        self.state.users_by_code[u.user_code] = updated
                    managed_users_updated += 1
            
            # Delete user
            del self.state.users[user_id]
            if user.user_code in self.state.users_by_code:
                del self.state.users_by_code[user.user_code]
            
            return {
                "managed_users_updated": managed_users_updated,
                "user_deleted": 1,
            }

    # =========================================================================
    # Bulk Operations (Admin only)
    # =========================================================================

    def bulk_disable_users(self, user_ids: list[str]) -> int:
        """Disable multiple users at once."""
        if not user_ids:
            return 0
        count = 0
        with self.state.lock:
            for user_id in user_ids:
                self._check_user_not_locked(user_id, "disable")
                user = self.state.users.get(user_id)
                if user and user.disabled_at is None:
                    updated = replace(user, disabled_at=datetime.now(UTC))
                    self.state.users[user_id] = updated
                    if user.user_code in self.state.users_by_code:
                        self.state.users_by_code[user.user_code] = updated
                    count += 1
        return count

    def bulk_enable_users(self, user_ids: list[str]) -> int:
        """Enable multiple users at once."""
        if not user_ids:
            return 0
        count = 0
        with self.state.lock:
            for user_id in user_ids:
                self._check_user_not_locked(user_id, "enable")
                user = self.state.users.get(user_id)
                if user and user.disabled_at is not None:
                    updated = replace(user, disabled_at=None)
                    self.state.users[user_id] = updated
                    if user.user_code in self.state.users_by_code:
                        self.state.users_by_code[user.user_code] = updated
                    count += 1
        return count

    def bulk_reassign_users(self, user_ids: list[str], new_manager_id: str | None) -> int:
        """Reassign multiple users to a new manager."""
        if not user_ids:
            return 0
        count = 0
        with self.state.lock:
            for user_id in user_ids:
                self._check_user_not_locked(user_id, "reassign")
                user = self.state.users.get(user_id)
                if user:
                    updated = replace(user, manager_id=new_manager_id)
                    self.state.users[user_id] = updated
                    if user.user_code in self.state.users_by_code:
                        self.state.users_by_code[user.user_code] = updated
                    count += 1
        return count

    def get_all_managers(self) -> list[User]:
        """Get all users with manager or admin role.
        
        Excludes SERVICE role and locked users - they cannot be assigned
        as managers for other users.
        """
        with self.state.lock:
            managers = [
                user for user in self.state.users.values()
                if user.role in (UserRole.MANAGER, UserRole.ADMIN)
                and user.disabled_at is None
                and user.locked_at is None  # Locked users cannot be managers
            ]
            return sorted(managers, key=lambda u: u.username)

    def search_users(self, query: str, limit: int = 15) -> list[User]:
        """Search for users by username or user_code.
        
        Used by searchable dropdown components.
        """
        with self.state.lock:
            query_lower = query.lower()
            matches = [
                user for user in self.state.users.values()
                if (query_lower in user.username.lower() 
                    or query_lower in user.user_code.lower())
                and user.disabled_at is None
            ]
            # Sort: prefix matches first, then alphabetically
            matches.sort(key=lambda u: (
                not u.username.lower().startswith(query_lower),
                u.username.lower()
            ))
            return matches[:limit]

    def update_user_max_active_jobs(self, user_id: str, max_active_jobs: int | None) -> None:
        """Update a user's max active jobs limit.
        
        Args:
            user_id: The user ID to update.
            max_active_jobs: New limit (None = system default, 0 = unlimited).
        """
        with self.state.lock:
            self._check_user_not_locked(user_id, "update max active jobs for")
            user = self.state.users.get(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")
            
            updated = replace(user, max_active_jobs=max_active_jobs)
            self.state.users[user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

    def set_last_maintenance_ack(self, user_id: str, ack_date: datetime) -> None:
        """Set last maintenance acknowledgment date for a user.

        Args:
            user_id: User UUID.
            ack_date: Date to record (typically today's date).
        """
        with self.state.lock:
            user = self.state.users.get(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")
            
            updated = replace(user, last_maintenance_ack=ack_date)
            self.state.users[user_id] = updated
            if user.user_code in self.state.users_by_code:
                self.state.users_by_code[user.user_code] = updated

    def needs_maintenance_ack(self, user_id: str) -> bool:
        """Check if user needs to acknowledge maintenance modal today.

        Args:
            user_id: User UUID.

        Returns:
            True if user hasn't acknowledged today, False otherwise.
        """
        with self.state.lock:
            user = self.state.users.get(user_id)
            if not user:
                return False
            
            if user.last_maintenance_ack is None:
                return True
            
            today = datetime.now(UTC).date()
            return user.last_maintenance_ack.date() < today


class SimulatedHostRepository:
    """In-memory implementation of HostRepository."""

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        """Get host by hostname."""
        with self.state.lock:
            return self.state.hosts.get(hostname)

    def get_host_by_id(self, host_id: str) -> DBHost | None:
        """Get host by ID."""
        with self.state.lock:
            for host in self.state.hosts.values():
                if host.id == host_id:
                    return host
            return None

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

    def check_host_running_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for running jobs (worker enforcement)."""
        with self.state.lock:
            host = self.state.hosts.get(hostname)
            if not host or not host.enabled:
                return False
            
            running = sum(
                1 for j in self.state.jobs.values() 
                if j.dbhost == hostname and j.status == JobStatus.RUNNING
            )
            return running < host.max_running_jobs

    def check_host_active_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for active jobs (API enforcement)."""
        with self.state.lock:
            host = self.state.hosts.get(hostname)
            if not host or not host.enabled:
                return False
            
            active = sum(
                1 for j in self.state.jobs.values() 
                if j.dbhost == hostname and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            )
            return active < host.max_active_jobs

    def update_host_limits(
        self, hostname: str, max_active_jobs: int, max_running_jobs: int
    ) -> None:
        """Update job limits for a host."""
        if max_active_jobs < 0:
            raise ValueError("max_active_jobs cannot be negative")
        if max_running_jobs < 1:
            raise ValueError("max_running_jobs must be at least 1")
        if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
            raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        with self.state.lock:
            host = self.state.hosts.get(hostname)
            if not host:
                raise ValueError(f"Host not found: {hostname}")
            
            self.state.hosts[hostname] = replace(
                host, 
                max_active_jobs=max_active_jobs, 
                max_running_jobs=max_running_jobs
            )

    def add_host(
        self, hostname: str, max_concurrent: int, credential_ref: str | None,
        *, host_id: str | None = None, host_alias: str | None = None,
        max_running_jobs: int | None = None, max_active_jobs: int | None = None
    ) -> None:
        """Add a new host.
        
        Args:
            hostname: Hostname of the database server.
            max_concurrent: Maximum concurrent jobs allowed (legacy parameter).
            credential_ref: AWS Secrets Manager reference.
            host_id: Optional UUID for the host. If None, one is generated.
            host_alias: Optional short alias for the host.
            max_running_jobs: Optional max running jobs. Defaults to max_concurrent.
            max_active_jobs: Optional max active jobs. Defaults to max_running_jobs * 10.
        """
        with self.state.lock:
            if hostname in self.state.hosts:
                raise ValueError(f"Host already exists: {hostname}")
            
            # Use provided values or defaults
            running = max_running_jobs if max_running_jobs is not None else max_concurrent
            active = max_active_jobs if max_active_jobs is not None else running * 10
            final_id = host_id or str(uuid.uuid4())
            
            host = DBHost(
                id=final_id,
                hostname=hostname,
                host_alias=host_alias,
                credential_ref=credential_ref or "mock:creds",
                max_running_jobs=running,
                max_active_jobs=active,
                enabled=True,
                created_at=datetime.now(UTC)
            )
            self.state.hosts[hostname] = host

    def update_host_config(
        self, host_id: str, *, host_alias: str | None = None,
        credential_ref: str | None = None,
        max_running_jobs: int | None = None, max_active_jobs: int | None = None
    ) -> None:
        """Update host configuration by ID."""
        with self.state.lock:
            # Find host by ID
            target_host = None
            for host in self.state.hosts.values():
                if host.id == host_id:
                    target_host = host
                    break
            
            if not target_host:
                raise ValueError(f"Host not found: {host_id}")
            
            # Build replacement with updated fields
            updates = {}
            if host_alias is not None:
                updates["host_alias"] = host_alias
            if credential_ref is not None:
                updates["credential_ref"] = credential_ref
            if max_running_jobs is not None:
                updates["max_running_jobs"] = max_running_jobs
            if max_active_jobs is not None:
                updates["max_active_jobs"] = max_active_jobs
            
            if updates:
                updated_host = replace(target_host, **updates)
                self.state.hosts[target_host.hostname] = updated_host

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

    def delete_host(self, hostname: str) -> None:
        """Delete a database host by hostname.

        Args:
            hostname: Hostname to delete.

        Raises:
            ValueError: If host not found.
        """
        with self.state.lock:
            if hostname not in self.state.hosts:
                raise ValueError(f"Host not found: {hostname}")
            del self.state.hosts[hostname]

    def search_hosts(self, query: str, limit: int = 10) -> list[DBHost]:
        """Search for hosts by hostname or alias.
        
        Used by searchable dropdown components.
        """
        with self.state.lock:
            query_lower = query.lower()
            matches = [
                host for host in self.state.hosts.values()
                if (query_lower in host.hostname.lower() 
                    or (host.host_alias and query_lower in host.host_alias.lower()))
            ]
            # Sort: prefix matches first, then alphabetically
            matches.sort(key=lambda h: (
                not h.hostname.lower().startswith(query_lower),
                h.hostname.lower()
            ))
            return matches[:limit]

    def list_hosts(self) -> list[DBHost]:
        """Get all hosts (alias for get_all_hosts)."""
        return self.get_all_hosts()

    def hard_delete_host(self, host_id: str) -> None:
        """Permanently delete a host by ID.
        
        Used by admin Remove Host feature after secret deletion.
        
        Raises:
            ValueError: If host not found.
        """
        with self.state.lock:
            # Find host by ID
            target_hostname = None
            for hostname, host in self.state.hosts.items():
                if host.id == host_id:
                    target_hostname = hostname
                    break
            
            if target_hostname is None:
                raise ValueError(f"Host not found: {host_id}")
            
            del self.state.hosts[target_hostname]

    def get_host_credentials_for_maintenance(self, hostname: str) -> Any:
        """Get resolved MySQL credentials for maintenance operations.

        Similar to get_host_credentials but allows disabled hosts.
        In simulation mode, returns a mock credential dict.

        Args:
            hostname: Hostname to get credentials for.

        Returns:
            Mock credentials dict for simulation.

        Raises:
            ValueError: If host not found.
        """
        with self.state.lock:
            host = self.state.hosts.get(hostname)
            if not host:
                raise ValueError(f"Host not found: {hostname}")
            
            # Return mock credentials suitable for simulation
            return {
                'host': hostname,
                'port': 3306,
                'user': 'simulated_user',
                'password': 'simulated_password',
            }

    def is_staging_db_active(
        self,
        hostname: str,
        staging_name: str,
        check_count: int = 3,
        check_delay_seconds: float = 2.0,
    ) -> bool:
        """Check if a staging database has active MySQL processes.

        In simulation mode, always returns False (no active processes).

        Args:
            hostname: Database host to check.
            staging_name: Staging database name to look for.
            check_count: Number of times to check (default 3).
            check_delay_seconds: Delay between checks (default 2.0).

        Returns:
            False in simulation mode (no active processes).
        """
        # Simulation mode: always report no active processes
        return False


class SimulatedSettingsRepository:
    """In-memory implementation of SettingsRepository."""

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    def get(self, key: str) -> str | None:
        """Get a setting value (alias for get_setting)."""
        return self.get_setting(key)

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

    def get_max_active_jobs_global(self) -> int:
        """Get max active jobs global setting."""
        val = self.get_setting("max_active_jobs_global")
        return int(val) if val else 0

    def get_all_settings(self) -> dict[str, str]:
        """Get all settings."""
        with self.state.lock:
            return self.state.settings.copy()

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Set a setting value."""
        with self.state.lock:
            self.state.settings[key] = value
            # Store description in metadata if provided
            if description is not None:
                self.state.settings_metadata[key] = {
                    'description': description,
                    'updated_at': datetime.now(UTC)
                }

    def delete_setting(self, key: str) -> bool:
        """Delete a setting."""
        with self.state.lock:
            if key in self.state.settings:
                del self.state.settings[key]
                return True
            return False

    def get_staging_retention_days(self) -> int:
        """Get number of days before staging databases are eligible for cleanup.

        Returns:
            Retention days. 7 is the default. 0 means cleanup is disabled.
        """
        val = self.get_setting("staging_retention_days")
        if val is None:
            return 7  # Default: 7 days
        try:
            return max(0, int(val))  # Ensure non-negative
        except ValueError:
            return 7  # Default: 7 days if setting is invalid

    def get_job_log_retention_days(self) -> int:
        """Get number of days before job logs are eligible for pruning.

        Returns:
            Retention days. 30 is the default. 0 means pruning is disabled.
        """
        val = self.get_setting("job_log_retention_days")
        if val is None:
            return 30  # Default: 30 days
        try:
            return max(0, int(val))  # Ensure non-negative
        except ValueError:
            return 30  # Default: 30 days if setting is invalid

    def get_all_settings_with_metadata(self) -> list[dict[str, str | None]]:
        """Get all settings with their metadata (description, updated_at).

        Returns:
            List of dicts with keys: setting_key, setting_value, description, updated_at
        """
        with self.state.lock:
            results = []
            for key, value in sorted(self.state.settings.items()):
                meta = self.state.settings_metadata.get(key, {})
                results.append({
                    'setting_key': key,
                    'setting_value': value,
                    'description': meta.get('description'),
                    'updated_at': meta.get('updated_at'),
                })
            return results

    def get_cleanup_grace_days(self) -> int:
        """Get days after expiry before automatic cleanup.

        Returns:
            Number of days. Default: 7.
        """
        val = self.get_setting("cleanup_grace_days")
        if val is None:
            return 7  # Default: 7 days
        try:
            return max(0, int(val))
        except ValueError:
            return 7

    def get_max_retention_months(self) -> int:
        """Get maximum retention months for database expiration.

        Returns:
            Maximum months a database can be retained (1-12). Default: 6.
        """
        val = self.get_setting("max_retention_months")
        if val is None:
            return 6  # Default: 6 months
        try:
            return max(1, min(12, int(val)))
        except ValueError:
            return 6

    def get_expiring_notice_days(self) -> int:
        """Get days before expiry to show warning notice.

        Returns:
            Number of days. Default: 7.
        """
        val = self.get_setting("expiring_notice_days")
        if val is None:
            return 7  # Default: 7 days
        try:
            return max(0, int(val))
        except ValueError:
            return 7

    def get_retention_options(
        self, include_now: bool = False
    ) -> list[tuple[str, str]]:
        """Get retention dropdown options based on current settings.

        Args:
            include_now: Whether to include "Now" (immediate removal) option.

        Returns:
            List of (value, label) tuples for dropdown options.
        """
        max_months = self.get_max_retention_months()
        options: list[tuple[str, str]] = []
        
        if include_now:
            options.append(("now", "Now"))
        
        # Add month options up to max
        for months in range(1, max_months + 1):
            if months == 1:
                options.append(("1", "1 month"))
            else:
                options.append((str(months), f"{months} months"))
        
        return options


class SimulatedAuthRepository:
    """In-memory implementation of AuthRepository for simulation mode.

    Supports password verification and session management without a database.
    """

    # Session token length in bytes (generates 64 hex chars)
    TOKEN_BYTES = 32

    # Default session TTL
    DEFAULT_SESSION_TTL_HOURS = 24

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    # ==================== Locked User Guards ====================

    def _check_user_not_locked(self, user_id: str, action: str) -> None:
        """Raise LockedUserError if user is locked.
        
        Must be called with state.lock held.
        """
        user = self.state.users.get(user_id)
        if user and user.locked_at is not None:
            raise LockedUserError(user.username, action)

    def get_password_hash(self, user_id: str) -> str | None:
        """Get stored password hash for user."""
        with self.state.lock:
            if user_id in self.state.auth_credentials:
                pw_hash = self.state.auth_credentials[user_id].get('password_hash')
                return str(pw_hash) if pw_hash else None
            return None

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        """Set password hash for user."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "set password for")
            if user_id not in self.state.auth_credentials:
                self.state.auth_credentials[user_id] = {}
            self.state.auth_credentials[user_id]['password_hash'] = password_hash
            self.state.auth_credentials[user_id]['updated_at'] = datetime.now(UTC)

    def has_password(self, user_id: str) -> bool:
        """Check if user has a password set."""
        return self.get_password_hash(user_id) is not None

    # =========================================================================
    # Password Reset Methods
    # =========================================================================

    def mark_password_reset(self, user_id: str) -> None:
        """Mark a user's password for reset."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "mark password reset for")
            if user_id not in self.state.auth_credentials:
                self.state.auth_credentials[user_id] = {}
            self.state.auth_credentials[user_id]['password_reset_at'] = datetime.now(UTC)
            self.state.auth_credentials[user_id]['updated_at'] = datetime.now(UTC)

    def clear_password_reset(self, user_id: str) -> None:
        """Clear the password reset flag after user sets new password."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "clear password reset for")
            if user_id in self.state.auth_credentials:
                self.state.auth_credentials[user_id]['password_reset_at'] = None
                self.state.auth_credentials[user_id]['updated_at'] = datetime.now(UTC)

    def is_password_reset_required(self, user_id: str) -> bool:
        """Check if user must reset their password."""
        with self.state.lock:
            if user_id in self.state.auth_credentials:
                return self.state.auth_credentials[user_id].get('password_reset_at') is not None
            return False

    def get_password_reset_at(self, user_id: str) -> datetime | None:
        """Get timestamp when password reset was requested."""
        with self.state.lock:
            if user_id in self.state.auth_credentials:
                reset_at = self.state.auth_credentials[user_id].get('password_reset_at')
                if isinstance(reset_at, datetime):
                    return reset_at
            return None

    def create_session(
        self,
        user_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        ttl_hours: int | None = None,
    ) -> tuple[str, str]:
        """Create new session for user."""
        import hashlib
        import secrets

        if ttl_hours is None:
            ttl_hours = self.DEFAULT_SESSION_TTL_HOURS

        session_id = str(uuid.uuid4())
        token = secrets.token_hex(self.TOKEN_BYTES)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)

        with self.state.lock:
            self.state.sessions[token_hash] = {
                'session_id': session_id,
                'user_id': user_id,
                'token_hash': token_hash,
                'expires_at': expires_at,
                'last_activity': datetime.now(UTC),
                'ip_address': ip_address,
                'user_agent': user_agent,
            }

        return session_id, token

    def validate_session(self, session_token: str) -> str | None:
        """Validate session token and return user_id."""
        import hashlib

        token_hash = hashlib.sha256(session_token.encode()).hexdigest()

        with self.state.lock:
            session = self.state.sessions.get(token_hash)

            if not session:
                return None

            # Check expiration
            expires_at = session['expires_at']
            if expires_at < datetime.now(UTC):
                # Session expired, clean it up
                del self.state.sessions[token_hash]
                return None

            # Update last activity
            session['last_activity'] = datetime.now(UTC)
            return str(session['user_id'])

    def delete_session(self, session_token: str) -> bool:
        """Delete a session."""
        import hashlib

        token_hash = hashlib.sha256(session_token.encode()).hexdigest()

        with self.state.lock:
            if token_hash in self.state.sessions:
                del self.state.sessions[token_hash]
                return True
            return False

    def invalidate_session_by_token(self, session_token: str) -> bool:
        """Invalidate a session by its token.

        Alias for delete_session to match AuthRepository interface.
        """
        return self.delete_session(session_token)

    def invalidate_session(self, session_id: str) -> None:
        """Invalidate a session by session_id (logout).

        Args:
            session_id: UUID of the session to invalidate.
        """
        with self.state.lock:
            to_delete = [
                token_hash for token_hash, session in self.state.sessions.items()
                if session.get('session_id') == session_id
            ]
            for token_hash in to_delete:
                del self.state.sessions[token_hash]

    def delete_user_sessions(self, user_id: str) -> int:
        """Delete all sessions for a user."""
        with self.state.lock:
            to_delete = [
                token_hash for token_hash, session in self.state.sessions.items()
                if session['user_id'] == user_id
            ]
            for token_hash in to_delete:
                del self.state.sessions[token_hash]
            return len(to_delete)

    # ==================== TOTP Methods ====================

    def get_totp_secret(self, user_id: str) -> str | None:
        """Get TOTP secret for user if enabled."""
        with self.state.lock:
            creds = self.state.auth_credentials.get(user_id, {})
            if creds.get('totp_enabled'):
                secret = creds.get('totp_secret')
                return str(secret) if secret else None
            return None

    def set_totp_secret(self, user_id: str, totp_secret: str) -> None:
        """Set and enable TOTP for user."""
        with self.state.lock:
            if user_id not in self.state.auth_credentials:
                self.state.auth_credentials[user_id] = {}
            self.state.auth_credentials[user_id]['totp_secret'] = totp_secret
            self.state.auth_credentials[user_id]['totp_enabled'] = True
            self.state.auth_credentials[user_id]['updated_at'] = datetime.now(UTC)

    def disable_totp(self, user_id: str) -> None:
        """Disable TOTP for user."""
        with self.state.lock:
            if user_id in self.state.auth_credentials:
                self.state.auth_credentials[user_id]['totp_enabled'] = False
                self.state.auth_credentials[user_id]['totp_secret'] = None
                self.state.auth_credentials[user_id]['updated_at'] = datetime.now(UTC)

    def is_totp_enabled(self, user_id: str) -> bool:
        """Check if TOTP is enabled for user."""
        with self.state.lock:
            creds = self.state.auth_credentials.get(user_id, {})
            return bool(creds.get('totp_enabled'))

    # ==================== Session Management Methods ====================

    def get_user_session_count(self, user_id: str) -> int:
        """Get count of active (non-expired) sessions for user."""
        now = datetime.now(UTC)
        with self.state.lock:
            return sum(
                1 for session in self.state.sessions.values()
                if session['user_id'] == user_id and session['expires_at'] > now
            )

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        now = datetime.now(UTC)
        with self.state.lock:
            to_delete = [
                token_hash for token_hash, session in self.state.sessions.items()
                if session['expires_at'] < now
            ]
            for token_hash in to_delete:
                del self.state.sessions[token_hash]
            return len(to_delete)

    def get_session_by_id(self, session_id: str) -> dict[str, Any] | None:
        """Get session details by session_id."""
        with self.state.lock:
            for session in self.state.sessions.values():
                if session['session_id'] == session_id:
                    return dict(session)  # Return copy
            return None

    def invalidate_all_user_sessions(self, user_id: str) -> int:
        """Invalidate all sessions for user. Alias for delete_user_sessions."""
        return self.delete_user_sessions(user_id)

    # =========================================================================
    # User Host Assignment Methods
    # =========================================================================

    def get_user_hosts(self, user_id: str) -> list[tuple[str, str, bool]]:
        """Get database hosts assigned to a user.

        Returns:
            List of (host_id, hostname, is_default) tuples.
        """
        with self.state.lock:
            user_hosts = self.state.user_hosts.get(user_id, [])
            result: list[tuple[str, str, bool]] = []
            for uh in user_hosts:
                host_id = uh['host_id']
                # Look up host details from hosts dict (keyed by hostname)
                host = next(
                    (h for h in self.state.hosts.values() if str(h.id) == host_id),
                    None
                )
                if host:
                    # Return canonical hostname for the tuple
                    result.append((host_id, host.hostname, bool(uh.get('is_default', False))))
            return result

    def set_user_hosts(
        self,
        user_id: str,
        host_ids: list[str],
        default_host_id: str | None,
        assigned_by: str | None = None,
    ) -> None:
        """Set database hosts for a user (replaces all existing assignments)."""
        with self.state.lock:
            self._check_user_not_locked(user_id, "assign hosts for")
            # Auto-default: if only one host, it becomes the default
            if len(host_ids) == 1:
                default_host_id = host_ids[0]
            new_assignments: list[dict[str, Any]] = []
            for host_id in host_ids:
                new_assignments.append({
                    'host_id': host_id,
                    'is_default': host_id == default_host_id,
                    'assigned_at': datetime.now(UTC),
                    'assigned_by': assigned_by,
                })
            self.state.user_hosts[user_id] = new_assignments

    def get_user_default_host(self, user_id: str) -> str | None:
        """Get the default host hostname for a user."""
        with self.state.lock:
            user_hosts = self.state.user_hosts.get(user_id, [])
            for uh in user_hosts:
                if uh.get('is_default'):
                    host_id = uh['host_id']
                    host = next(
                        (h for h in self.state.hosts.values() if str(h.id) == host_id),
                        None
                    )
                    if host:
                        return host.hostname
            return None

    def get_user_allowed_hosts(self, user_id: str) -> list[str]:
        """Get list of canonical hostnames a user is allowed to access."""
        with self.state.lock:
            user_hosts = self.state.user_hosts.get(user_id, [])
            result: list[str] = []
            for uh in user_hosts:
                host_id = uh['host_id']
                host = next(
                    (h for h in self.state.hosts.values() if str(h.id) == host_id),
                    None
                )
                if host:
                    result.append(host.hostname)
            return result

    # =========================================================================
    # API Key Management Methods
    # =========================================================================

    def list_api_keys_for_user(self, user_id: str) -> list[Any]:
        """List all API keys for a user.
        
        Does NOT return the secret - that's only available at creation time.
        
        Args:
            user_id: UUID of the user.
            
        Returns:
            List of ApiKey-like objects with key_id, name, is_active, created_at, last_used_at.
        """
        from dataclasses import dataclass as dc
        
        @dc
        class ApiKeyInfo:
            """Simple container for API key information."""
            key_id: str
            name: str | None
            host_name: str | None
            is_active: bool
            approved_at: datetime | None
            created_at: datetime | None
            created_from_ip: str | None
            last_used_at: datetime | None
            last_used_ip: str | None
            expires_at: datetime | None
        
        with self.state.lock:
            result: list[ApiKeyInfo] = []
            for key_id, key_data in self.state.api_keys.items():
                if key_data.get('user_id') == user_id:
                    result.append(ApiKeyInfo(
                        key_id=key_id,
                        name=key_data.get('name'),
                        host_name=key_data.get('host_name'),
                        is_active=key_data.get('is_active', False),
                        approved_at=key_data.get('approved_at'),
                        created_at=key_data.get('created_at'),
                        created_from_ip=key_data.get('created_from_ip'),
                        last_used_at=key_data.get('last_used_at'),
                        last_used_ip=key_data.get('last_used_ip'),
                        expires_at=key_data.get('expires_at'),
                    ))
            # Sort by created_at desc
            result.sort(key=lambda k: k.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
            return result

    def get_api_keys_for_user(self, user_id: str) -> list[Any]:
        """Alias for list_api_keys_for_user."""
        return self.list_api_keys_for_user(user_id)

    def create_api_key(
        self, 
        user_id: str, 
        name: str | None = None,
        host_name: str | None = None,
    ) -> tuple[str, str]:
        """Create a new API key for a user.
        
        Args:
            user_id: UUID of the user.
            name: Optional name/description for the key.
            host_name: Optional hostname the key is for.
            
        Returns:
            Tuple of (key_id, secret). The secret is only returned once.
        """
        import secrets
        
        key_id = "key_" + secrets.token_hex(16)
        secret = "sec_" + secrets.token_hex(32)
        
        with self.state.lock:
            self.state.api_keys[key_id] = {
                "key_id": key_id,
                "user_id": user_id,
                "key_secret_hash": "$2b$12$SimulatedHash",
                "key_secret": secret,  # In real DB, only hash is stored
                "name": name,
                "host_name": host_name,
                "created_from_ip": "127.0.0.1",
                "is_active": True,
                "created_at": datetime.now(UTC),
                "last_used_at": None,
                "last_used_ip": None,
                "approved_at": datetime.now(UTC),  # Auto-approve in simulation
                "approved_by": user_id,
                "expires_at": None,
            }
        
        return key_id, secret

    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key."""
        with self.state.lock:
            if key_id in self.state.api_keys:
                self.state.api_keys[key_id]['is_active'] = False
                return True
            return False

    def get_api_key_user(self, key_id: str) -> str | None:
        """Get the user_id for an API key."""
        with self.state.lock:
            key_data = self.state.api_keys.get(key_id)
            if key_data:
                return str(key_data.get('user_id'))
            return None

    def get_api_key_info(self, key_id: str) -> dict[str, Any] | None:
        """Get detailed information about an API key.
        
        Args:
            key_id: ID of the key to look up.
            
        Returns:
            Dict with key info including user_id, approved_at, etc. or None if not found.
        """
        with self.state.lock:
            key_data = self.state.api_keys.get(key_id)
            if key_data:
                return {
                    'key_id': key_id,
                    'user_id': key_data.get('user_id'),
                    'name': key_data.get('name'),
                    'host_name': key_data.get('host_name'),
                    'is_active': key_data.get('is_active', False),
                    'approved_at': key_data.get('approved_at'),
                    'approved_by': key_data.get('approved_by'),
                    'created_at': key_data.get('created_at'),
                    'created_from_ip': key_data.get('created_from_ip'),
                    'last_used_at': key_data.get('last_used_at'),
                    'last_used_ip': key_data.get('last_used_ip'),
                    'expires_at': key_data.get('expires_at'),
                }
            return None

    def get_pending_api_keys(self) -> list[Any]:
        """Get all API keys pending approval.
        
        Returns:
            List of API key objects where approved_at is None.
        """
        from dataclasses import dataclass as dc
        
        @dc
        class PendingApiKey:
            """Container for pending API key information."""
            key_id: str
            user_id: str
            username: str | None
            name: str | None
            host_name: str | None
            created_at: datetime | None
            created_from_ip: str | None
        
        with self.state.lock:
            result: list[PendingApiKey] = []
            for key_id, key_data in self.state.api_keys.items():
                if key_data.get('approved_at') is None:
                    user_id = key_data.get('user_id', '')
                    user = self.state.users.get(user_id)
                    result.append(PendingApiKey(
                        key_id=key_id,
                        user_id=user_id,
                        username=user.username if user else None,
                        name=key_data.get('name'),
                        host_name=key_data.get('host_name'),
                        created_at=key_data.get('created_at'),
                        created_from_ip=key_data.get('created_from_ip'),
                    ))
            # Sort by created_at desc
            result.sort(key=lambda k: k.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
            return result

    def get_all_api_keys(self) -> list[Any]:
        """Get all API keys in the system.
        
        Returns:
            List of all API key objects with user information.
        """
        from dataclasses import dataclass as dc
        
        @dc
        class ApiKeyInfo:
            """Container for API key information."""
            key_id: str
            user_id: str
            username: str | None
            name: str | None
            host_name: str | None
            is_active: bool
            approved_at: datetime | None
            created_at: datetime | None
            created_from_ip: str | None
            last_used_at: datetime | None
            last_used_ip: str | None
            expires_at: datetime | None
        
        with self.state.lock:
            result: list[ApiKeyInfo] = []
            for key_id, key_data in self.state.api_keys.items():
                user_id = key_data.get('user_id', '')
                user = self.state.users.get(user_id)
                result.append(ApiKeyInfo(
                    key_id=key_id,
                    user_id=user_id,
                    username=user.username if user else None,
                    name=key_data.get('name'),
                    host_name=key_data.get('host_name'),
                    is_active=key_data.get('is_active', False),
                    approved_at=key_data.get('approved_at'),
                    created_at=key_data.get('created_at'),
                    created_from_ip=key_data.get('created_from_ip'),
                    last_used_at=key_data.get('last_used_at'),
                    last_used_ip=key_data.get('last_used_ip'),
                    expires_at=key_data.get('expires_at'),
                ))
            # Sort by created_at desc
            result.sort(key=lambda k: k.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
            return result

    def approve_api_key(self, key_id: str, approver_user_id: str) -> bool:
        """Approve an API key.
        
        Args:
            key_id: ID of the key to approve.
            approver_user_id: User ID of the admin approving.
            
        Returns:
            True if approved, False if key not found.
        """
        with self.state.lock:
            if key_id in self.state.api_keys:
                self.state.api_keys[key_id]['approved_at'] = datetime.now(UTC)
                self.state.api_keys[key_id]['approved_by'] = approver_user_id
                self.state.api_keys[key_id]['is_active'] = True
                return True
            return False


class SimulatedAuditRepository:
    """In-memory implementation of AuditRepository for simulation mode.
    
    Thread-safe using RLock from SimulationState.
    """

    def __init__(self) -> None:
        """Initialize the repository with shared simulation state."""
        self.state = get_simulation_state()

    def log_action(
        self,
        actor_user_id: str,
        action: str,
        target_user_id: str | None = None,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Record an audit log entry."""
        with self.state.lock:
            audit_id = str(uuid.uuid4())
            entry = {
                "audit_id": audit_id,
                "actor_user_id": actor_user_id,
                "target_user_id": target_user_id,
                "action": action,
                "detail": detail,
                "context_json": json.dumps(context) if context else None,
                "created_at": datetime.now(UTC),
            }
            self.state.audit_logs.append(entry)
            return audit_id

    def get_audit_logs(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve audit log entries with optional filtering."""
        with self.state.lock:
            filtered = self.state.audit_logs[:]
            
            if actor_user_id:
                filtered = [e for e in filtered if e["actor_user_id"] == actor_user_id]
            if target_user_id:
                filtered = [e for e in filtered if e["target_user_id"] == target_user_id]
            if action:
                filtered = [e for e in filtered if e["action"] == action]
            
            # Sort by created_at descending (most recent first)
            filtered.sort(key=lambda x: x["created_at"], reverse=True)
            
            # Apply pagination
            paginated = filtered[offset : offset + limit]
            
            # Build username lookup from users
            user_lookup = {uid: u.username for uid, u in self.state.users.items()}
            
            # Transform to match expected format with username enrichment
            results = []
            for entry in paginated:
                actor_uid = entry["actor_user_id"]
                target_uid = entry["target_user_id"]
                results.append({
                    "audit_id": entry["audit_id"],
                    "actor_user_id": actor_uid,
                    "actor_username": user_lookup.get(actor_uid),
                    "target_user_id": target_uid,
                    "target_username": user_lookup.get(target_uid) if target_uid else None,
                    "action": entry["action"],
                    "detail": entry["detail"],
                    "context": json.loads(entry["context_json"]) if entry["context_json"] else None,
                    "created_at": entry["created_at"],
                })
            return results

    def get_audit_logs_count(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
    ) -> int:
        """Get count of audit logs matching filters."""
        with self.state.lock:
            filtered = self.state.audit_logs[:]
            
            if actor_user_id:
                filtered = [e for e in filtered if e["actor_user_id"] == actor_user_id]
            if target_user_id:
                filtered = [e for e in filtered if e["target_user_id"] == target_user_id]
            if action:
                filtered = [e for e in filtered if e["action"] == action]
            
            return len(filtered)
