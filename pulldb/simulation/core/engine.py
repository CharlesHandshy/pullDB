"""Simulation Engine Core.

Orchestrates the simulation by managing time, state, and component interactions.
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
    """Configuration for a simulation run."""
    initial_jobs: int = 0
    worker_count: int = 1
    failure_rate: float = 0.0
    time_scale: float = 1.0  # 1.0 = real time, >1.0 = faster

class SimulationEngine:
    """Main entry point for running simulations."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        """Initialize the simulation engine."""
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
        """Reset state and prepare for simulation."""
        self.state.clear()
        logger.info("Simulation initialized")

    def tick(self) -> None:
        """Advance simulation by one step."""
        # Placeholder for tick logic
        pass

    def run(self, duration_seconds: int = 60) -> None:
        """Run the simulation for a specified duration."""
        self.is_running = True
        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        logger.info(f"Starting simulation for {duration_seconds}s")
        while datetime.now(UTC) < end_time and self.is_running:
            self.tick()
            # Simple sleep to prevent tight loop in this initial version
            time.sleep(0.1)
            
        logger.info("Simulation finished")
