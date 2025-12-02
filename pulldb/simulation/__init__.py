"""Simulation domain for pullDB.

This package contains the Mock System implementation, including:
- In-memory repositories (MySQL replacement)
- Mock S3 client
- Mock Process Executor
- Event bus for observability
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
from pulldb.simulation.core.bus import (
    EventType,
    SimulationEvent,
    SimulationEventBus,
    get_event_bus,
)
from pulldb.simulation.core.state import (
    SimulationState,
    get_simulation_state,
    reset_simulation,
)

__all__ = [
    # Adapters
    "MockProcessExecutor",
    "MockS3Client",
    "SimulatedHostRepository",
    "SimulatedJobRepository",
    "SimulatedSettingsRepository",
    "SimulatedUserRepository",
    # Event Bus
    "EventType",
    "SimulationEvent",
    "SimulationEventBus",
    "get_event_bus",
    # State
    "SimulationState",
    "get_simulation_state",
    "reset_simulation",
]
