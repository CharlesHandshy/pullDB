"""Simulation domain for pullDB.

This package contains the Mock System implementation, including:
- In-memory repositories (MySQL replacement)
- Mock S3 client
- Mock Process Executor
- Event bus for observability
- Scenario engine for chaos engineering
"""

from pulldb.simulation.adapters.mock_exec import MockCommandConfig, MockProcessExecutor
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedAuthRepository,
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
from pulldb.simulation.core.scenarios import (
    ChaosConfig,
    Scenario,
    ScenarioManager,
    ScenarioType,
    get_scenario_manager,
    reset_scenario_manager,
)
from pulldb.simulation.core.state import (
    SimulationState,
    get_simulation_state,
    reset_simulation,
)

__all__ = [
    # Adapters
    "MockCommandConfig",
    "MockProcessExecutor",
    "MockS3Client",
    "SimulatedAuthRepository",
    "SimulatedHostRepository",
    "SimulatedJobRepository",
    "SimulatedSettingsRepository",
    "SimulatedUserRepository",
    # Event Bus
    "EventType",
    "SimulationEvent",
    "SimulationEventBus",
    "get_event_bus",
    # Scenarios
    "ChaosConfig",
    "Scenario",
    "ScenarioManager",
    "ScenarioType",
    "get_scenario_manager",
    "reset_scenario_manager",
    # State
    "SimulationState",
    "get_simulation_state",
    "reset_simulation",
]
