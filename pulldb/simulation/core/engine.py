"""Simulation Engine Core.

Orchestrates the simulation by managing time, state, and component interactions.

HCA Layer: features
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pulldb.simulation.adapters.mock_exec import MockProcessExecutor
from pulldb.simulation.adapters.mock_mysql import SimulatedHostRepository, SimulatedJobRepository
from pulldb.simulation.adapters.mock_s3 import MockS3Client
from pulldb.simulation.core.state import SimulationState, get_simulation_state

logger = logging.getLogger(__name__)


@dataclass
class SimulationConfig:
    """Configuration for a simulation run.

    Attributes:
        initial_jobs: Number of jobs to seed at simulation start.
        worker_count: Number of simulated workers.
        failure_rate: Probability of job failure (0.0-1.0).
        time_scale: Time multiplier (1.0 = real time, >1.0 = faster).
    """

    initial_jobs: int = 0
    worker_count: int = 1
    failure_rate: float = 0.0
    time_scale: float = 1.0  # 1.0 = real time, >1.0 = faster


class SimulationEngine:
    """Main entry point for running simulations.

    Coordinates simulation components including job repository,
    host repository, S3 client, and process executor mocks.
    """

    def __init__(self, config: SimulationConfig | None = None) -> None:
        """Initialize the simulation engine.

        Args:
            config: Optional simulation configuration. Uses defaults if not provided.
        """
        self.config = config or SimulationConfig()
        self.state: SimulationState = get_simulation_state()
        self.job_repo = SimulatedJobRepository()
        self.host_repo = SimulatedHostRepository()
        self.s3 = MockS3Client()
        self.executor = MockProcessExecutor()

        # Simulation control
        self.current_time = datetime.now(UTC)
        self.is_running = False

    def initialize(self) -> None:
        """Reset state and prepare for simulation.

        Clears all simulation state and prepares for a fresh run.
        """
        self.state.clear()
        logger.info("Simulation initialized")

    def tick(self) -> None:
        """Advance simulation by one discrete time step.

        Processes all pending simulation events and updates state.
        Override in subclasses to implement custom tick behavior.
        """
        # Placeholder for tick logic
        pass

    def run(self, duration_seconds: int = 60) -> None:
        """Run the simulation for a specified duration.

        Args:
            duration_seconds: How long to run the simulation.
        """
        self.is_running = True
        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(seconds=duration_seconds)

        logger.info(f"Starting simulation for {duration_seconds}s")
        while datetime.now(UTC) < end_time and self.is_running:
            self.tick()
            # Simple sleep to prevent tight loop in this initial version
            time.sleep(0.1)

        logger.info("Simulation finished")
