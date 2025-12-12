"""Mock Queue Runner for Simulation Mode.

Processes jobs through their lifecycle stages without actually
performing any real work (no S3 downloads, no myloader execution).

HCA Layer: features (business logic)
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING

from pulldb.domain.models import JobStatus
from pulldb.simulation.core.bus import EventType, get_event_bus
from pulldb.simulation.core.state import get_simulation_state

if TYPE_CHECKING:
    from pulldb.domain.models import Job
    from pulldb.simulation.adapters.mock_mysql import SimulatedJobRepository

logger = logging.getLogger(__name__)


class JobPhase(Enum):
    """Phases a job progresses through during execution."""
    
    DISCOVERY = "discovery"
    DOWNLOAD = "download"
    EXTRACTION = "extraction"
    RESTORE = "restore"
    COMPLETE = "complete"


@dataclass
class MockRunnerConfig:
    """Configuration for the mock queue runner.
    
    Attributes:
        failure_rate: Probability (0.0-1.0) that a job fails during processing.
        phase_delay_ms: Milliseconds to sleep between phase transitions.
                        Set to 0 for instant processing (useful in tests).
        failure_phases: Which phases can fail. Empty = any phase can fail.
        cancel_check_enabled: Whether to honor cancellation requests.
        worker_id: Identifier for this mock worker instance.
    """
    
    failure_rate: float = 0.0
    phase_delay_ms: int = 0
    failure_phases: list[JobPhase] = field(default_factory=list)
    cancel_check_enabled: bool = True
    worker_id: str = "mock-worker:1"
    
    def __post_init__(self) -> None:
        """Validate configuration values."""
        if not 0.0 <= self.failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0.0 and 1.0")


class MockQueueRunner:
    """Processes simulation jobs through their lifecycle.
    
    This class simulates the worker service behavior:
    - Claims queued jobs
    - Progresses them through phases (discovery, download, extraction, restore)
    - Marks them complete or failed
    - Honors cancellation requests
    
    Usage:
        runner = MockQueueRunner(job_repo)
        
        # Process one job
        job = runner.process_next()
        
        # Process all queued jobs
        results = runner.process_all()
        
        # Process with failure injection
        runner = MockQueueRunner(job_repo, MockRunnerConfig(failure_rate=0.3))
        runner.process_all()
    """
    
    # Error messages for random failure simulation
    FAILURE_MESSAGES = [
        "S3 download timeout",
        "Archive extraction failed: corrupt file",
        "myloader execution failed: exit code 1",
        "Connection refused to target host",
        "Disk space exhausted",
        "Database already exists (conflict)",
        "Authentication failed for target host",
        "Network timeout during restore",
    ]
    
    def __init__(
        self,
        job_repo: SimulatedJobRepository,
        config: MockRunnerConfig | None = None,
    ) -> None:
        """Initialize the mock queue runner.
        
        Args:
            job_repo: The simulated job repository for job operations.
            config: Configuration options. Uses defaults if not provided.
        """
        self.job_repo = job_repo
        self.config = config or MockRunnerConfig()
        self._bus = get_event_bus()
        self._state = get_simulation_state()
    
    def process_next(self) -> Job | None:
        """Process the next queued job.
        
        Claims the oldest queued job and runs it through all phases.
        
        Returns:
            The processed job (in COMPLETE, FAILED, or CANCELED state),
            or None if no jobs are queued.
        """
        job = self.job_repo.claim_next_job(self.config.worker_id)
        if not job:
            logger.debug("No queued jobs to process")
            return None
        
        logger.info(f"Processing job {job.id[:8]} for target {job.target}")
        return self._execute_job(job)
    
    def process_all(self, max_jobs: int | None = None) -> list[Job]:
        """Process all queued jobs.
        
        Args:
            max_jobs: Maximum number of jobs to process. None = unlimited.
        
        Returns:
            List of processed jobs (each in terminal state).
        """
        results: list[Job] = []
        count = 0
        
        while True:
            if max_jobs is not None and count >= max_jobs:
                break
            
            job = self.process_next()
            if job is None:
                break
            
            results.append(job)
            count += 1
        
        logger.info(f"Processed {len(results)} jobs")
        return results
    
    def advance_job_phase(self, job_id: str) -> Job | None:
        """Advance a specific job to its next phase.
        
        This is useful for step-by-step debugging or controlled testing.
        Only works for RUNNING jobs.
        
        Args:
            job_id: The job ID to advance.
        
        Returns:
            The updated job, or None if job not found or not running.
        """
        job = self.job_repo.get_job_by_id(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found")
            return None
        
        if job.status != JobStatus.RUNNING:
            logger.warning(f"Job {job_id} is not running (status: {job.status})")
            return None
        
        current_phase = self._get_current_phase(job)
        next_phase = self._get_next_phase(current_phase)
        
        if next_phase == JobPhase.COMPLETE:
            self.job_repo.mark_job_complete(job_id)
        else:
            self._transition_to_phase(job, next_phase)
        
        return self.job_repo.get_job_by_id(job_id)
    
    def _execute_job(self, job: Job) -> Job:
        """Execute a claimed job through all phases.
        
        Args:
            job: The job to execute (must be in RUNNING state).
        
        Returns:
            The job in its terminal state.
        """
        phases = [
            JobPhase.DISCOVERY,
            JobPhase.DOWNLOAD,
            JobPhase.EXTRACTION,
            JobPhase.RESTORE,
        ]
        
        for phase in phases:
            # Check for cancellation before each phase
            cancel_check = self.config.cancel_check_enabled
            if cancel_check and self.job_repo.is_cancellation_requested(job.id):
                logger.info(f"Job {job.id[:8]} canceled at {phase.value} phase")
                reason = f"Canceled during {phase.value}"
                self.job_repo.mark_job_canceled(job.id, reason)
                return self.job_repo.get_job_by_id(job.id)  # type: ignore
            
            # Simulate phase transition
            self._transition_to_phase(job, phase)
            
            # Apply delay if configured
            if self.config.phase_delay_ms > 0:
                time.sleep(self.config.phase_delay_ms / 1000.0)
            
            # Check for simulated failure
            if self._should_fail(phase):
                error = random.choice(self.FAILURE_MESSAGES)
                logger.info(f"Job {job.id[:8]} failed at {phase.value}: {error}")
                self.job_repo.mark_job_failed(job.id, error)
                return self.job_repo.get_job_by_id(job.id)  # type: ignore
        
        # All phases complete
        logger.info(f"Job {job.id[:8]} completed successfully")
        self.job_repo.mark_job_complete(job.id)
        return self.job_repo.get_job_by_id(job.id)  # type: ignore
    
    def _transition_to_phase(self, job: Job, phase: JobPhase) -> None:
        """Update job state for a phase transition."""
        with self._state.lock:
            current_job = self._state.jobs.get(job.id)
            if current_job:
                updated = replace(current_job, current_operation=phase.value)
                self._state.jobs[job.id] = updated
        
        # Log event for this phase
        event_detail = f"Phase: {phase.value}"
        self.job_repo.append_job_event(job.id, phase.value, event_detail)

        # Emit bus event - use DB_UPDATE for phase transitions
        # (JOB_CLAIMED is emitted by claim_next_job already)
        if phase != JobPhase.DISCOVERY:
            self._bus.emit(
                EventType.DB_UPDATE,
                "MockQueueRunner",
                {"phase": phase.value, "target": job.target},
                job_id=job.id,
            )
    
    def _get_current_phase(self, job: Job) -> JobPhase:
        """Determine the current phase of a job based on current_operation."""
        if not job.current_operation:
            return JobPhase.DISCOVERY
        
        try:
            return JobPhase(job.current_operation)
        except ValueError:
            return JobPhase.DISCOVERY
    
    def _get_next_phase(self, current: JobPhase) -> JobPhase:
        """Get the next phase after the current one."""
        order = [
            JobPhase.DISCOVERY,
            JobPhase.DOWNLOAD,
            JobPhase.EXTRACTION,
            JobPhase.RESTORE,
            JobPhase.COMPLETE,
        ]
        try:
            idx = order.index(current)
            return order[idx + 1] if idx + 1 < len(order) else JobPhase.COMPLETE
        except ValueError:
            return JobPhase.DISCOVERY
    
    def _should_fail(self, phase: JobPhase) -> bool:
        """Determine if this phase should fail based on config."""
        if self.config.failure_rate <= 0:
            return False

        # If specific failure phases are configured, only fail in those
        if self.config.failure_phases and phase not in self.config.failure_phases:
            return False

        return random.random() < self.config.failure_rate


# Module-level convenience function
def get_mock_queue_runner(
    job_repo: SimulatedJobRepository | None = None,
    config: MockRunnerConfig | None = None,
) -> MockQueueRunner:
    """Get a mock queue runner instance.

    If job_repo is not provided, creates a new SimulatedJobRepository.

    Args:
        job_repo: Optional job repository to use.
        config: Optional configuration.

    Returns:
        A configured MockQueueRunner instance.
    """
    if job_repo is None:
        # Import here to avoid circular import
        from pulldb.simulation.adapters.mock_mysql import (  # noqa: PLC0415
            SimulatedJobRepository as SimJobRepo,
        )

        job_repo = SimJobRepo()

    return MockQueueRunner(job_repo, config)
