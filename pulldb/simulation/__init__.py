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
    SimulatedAdminTaskRepository,
    SimulatedAuditRepository,
    SimulatedAuthRepository,
    SimulatedDisallowedUserRepository,
    SimulatedHostRepository,
    SimulatedJobHistorySummaryRepository,
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
from pulldb.simulation.core.queue_runner import (
    JobPhase,
    MockQueueRunner,
    MockRunnerConfig,
    get_mock_queue_runner,
)
from pulldb.simulation.core.scenarios import (
    ChaosConfig,
    Scenario,
    ScenarioManager,
    ScenarioType,
    get_scenario_manager,
    reset_scenario_manager,
)
from pulldb.simulation.core.seeding import (
    reset_and_seed,
    seed_dev_scenario,
)
from pulldb.simulation.core.state import (
    SimulationState,
    get_simulation_state,
    reset_simulation,
)


__all__ = [
    # Scenarios
    "ChaosConfig",
    # Event Bus
    "EventType",
    # Queue Runner
    "JobPhase",
    # Adapters
    "MockCommandConfig",
    "MockProcessExecutor",
    "MockQueueRunner",
    "MockRunnerConfig",
    "MockS3Client",
    "Scenario",
    "ScenarioManager",
    "ScenarioType",
    "SimulatedAdminTaskRepository",
    "SimulatedAuditRepository",
    "SimulatedAuthRepository",
    "SimulatedDisallowedUserRepository",
    "SimulatedHostRepository",
    "SimulatedJobHistorySummaryRepository",
    "SimulatedJobRepository",
    "SimulatedSettingsRepository",
    "SimulatedUserRepository",
    "SimulationEvent",
    "SimulationEventBus",
    # State
    "SimulationState",
    "get_event_bus",
    "get_mock_queue_runner",
    "get_scenario_manager",
    "get_simulation_state",
    # Seeding
    "reset_and_seed",
    "reset_scenario_manager",
    "reset_simulation",
    "seed_dev_scenario",
]
