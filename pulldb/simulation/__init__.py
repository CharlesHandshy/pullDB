"""Simulation domain for pullDB.

This package contains the Mock System implementation, including:
- In-memory repositories (MySQL replacement)
- Mock S3 client
- Mock Process Executor
- Scenario engine for chaos engineering
"""

from pulldb.simulation.adapters.mock_exec import MockProcessExecutor
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedHostRepository,
    SimulatedJobRepository,
    SimulatedSettingsRepository,
    SimulatedUserRepository,
)
from pulldb.simulation.adapters.mock_s3 import MockS3Client
from pulldb.simulation.core.state import (
    SimulationState,
    get_simulation_state,
    reset_simulation,
)

__all__ = [
    "MockProcessExecutor",
    "MockS3Client",
    "SimulatedHostRepository",
    "SimulatedJobRepository",
    "SimulatedSettingsRepository",
    "SimulatedUserRepository",
    "SimulationState",
    "get_simulation_state",
    "reset_simulation",
]
