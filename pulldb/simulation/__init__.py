from __future__ import annotations

"""Simulation domain for pullDB.

This package contains the Mock System implementation, including:
- In-memory repositories (MySQL replacement)
- Mock S3 client
- Mock Process Executor
- Event bus for observability
- Scenario engine for chaos engineering

HCA Layer: features (pulldb/simulation/)
"""

from pulldb.simulation.adapters.mock_exec import MockCommandConfig, MockProcessExecutor
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedAuditRepository,
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
from pulldb.simulation.core.seeding import (
    reset_and_seed,
    seed_dev_scenario,
)
from pulldb.simulation.core.queue_runner import (
    JobPhase,
    MockQueueRunner,
    MockRunnerConfig,
    get_mock_queue_runner,
)

__all__ = [
    # Adapters
    "MockCommandConfig",
    "MockProcessExecutor",
    "MockS3Client",
    "SimulatedAuditRepository",
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
    # Seeding
    "reset_and_seed",
    "seed_dev_scenario",
    # Queue Runner
    "JobPhase",
    "MockQueueRunner",
    "MockRunnerConfig",
    "get_mock_queue_runner",
]
