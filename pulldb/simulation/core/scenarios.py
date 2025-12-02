"""Scenario Manager for Simulation Mode.

Provides predefined scenarios and chaos injection capabilities
for testing various failure modes and edge cases.
"""

from __future__ import annotations

import logging
import random
import typing as t
from dataclasses import dataclass, field
from enum import Enum

from pulldb.simulation.adapters.mock_exec import MockCommandConfig
from pulldb.simulation.core.bus import EventType, get_event_bus
from pulldb.simulation.core.state import get_simulation_state, reset_simulation

if t.TYPE_CHECKING:
    from pulldb.simulation.adapters.mock_exec import MockProcessExecutor

logger = logging.getLogger(__name__)


class ScenarioType(str, Enum):
    """Predefined scenario types."""

    # Happy path scenarios
    HAPPY_PATH = "happy_path"
    SINGLE_JOB_SUCCESS = "single_job_success"
    MULTIPLE_JOBS_SUCCESS = "multiple_jobs_success"

    # Failure scenarios
    S3_NOT_FOUND = "s3_not_found"
    S3_PERMISSION_DENIED = "s3_permission_denied"
    MYLOADER_FAILURE = "myloader_failure"
    MYLOADER_TIMEOUT = "myloader_timeout"
    POST_SQL_FAILURE = "post_sql_failure"

    # Chaos scenarios
    RANDOM_FAILURES = "random_failures"
    SLOW_OPERATIONS = "slow_operations"
    INTERMITTENT_FAILURES = "intermittent_failures"


@dataclass
class ChaosConfig:
    """Configuration for chaos injection."""

    # Probability of failure (0.0 to 1.0)
    failure_rate: float = 0.0

    # Operations to inject chaos into
    target_operations: list[str] = field(default_factory=list)

    # Delay to add (seconds)
    delay_seconds: float = 0.0

    # Specific error message to inject
    error_message: str = ""


@dataclass
class Scenario:
    """A simulation scenario configuration."""

    name: str
    description: str
    scenario_type: ScenarioType

    # S3 fixtures: {bucket: [keys]}
    s3_fixtures: dict[str, list[str]] = field(default_factory=dict)

    # Command configurations: {command_prefix: MockCommandConfig}
    command_configs: dict[str, MockCommandConfig] = field(default_factory=dict)

    # Chaos configuration
    chaos: ChaosConfig | None = None

    # Number of jobs to pre-create
    initial_jobs: int = 0

    # Custom setup function
    setup_fn: t.Callable[[], None] | None = None


# Singleton scenario manager
_scenario_manager: ScenarioManager | None = None


class ScenarioManager:
    """Manages simulation scenarios and chaos injection."""

    def __init__(self) -> None:
        """Initialize with default scenarios."""
        self.state = get_simulation_state()
        self._bus = get_event_bus()
        self._current_scenario: Scenario | None = None
        self._scenarios: dict[ScenarioType, Scenario] = {}
        self._register_default_scenarios()

    def _register_default_scenarios(self) -> None:
        """Register the default built-in scenarios."""
        # Happy path - everything works
        self._scenarios[ScenarioType.HAPPY_PATH] = Scenario(
            name="Happy Path",
            description="All operations succeed with minimal delay",
            scenario_type=ScenarioType.HAPPY_PATH,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/customer1/full/20240101_000000.xbstream.zst",
                    "backups/customer1/incremental/20240102_000000.xbstream.zst",
                    "backups/customer2/full/20240101_000000.xbstream.zst",
                ]
            },
            command_configs={
                "myloader": MockCommandConfig(
                    exit_code=0,
                    stdout="Restoring database...\nDone.",
                    delay_seconds=0.1,
                ),
                "mysql": MockCommandConfig(
                    exit_code=0,
                    stdout="Query OK",
                    delay_seconds=0.05,
                ),
            },
        )

        # Single job success
        self._scenarios[ScenarioType.SINGLE_JOB_SUCCESS] = Scenario(
            name="Single Job Success",
            description="One job runs to completion successfully",
            scenario_type=ScenarioType.SINGLE_JOB_SUCCESS,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/testhost/full/20240101_000000.xbstream.zst",
                ]
            },
            command_configs={
                "myloader": MockCommandConfig(exit_code=0, delay_seconds=0.2),
                "mysql": MockCommandConfig(exit_code=0),
            },
            initial_jobs=1,
        )

        # S3 not found
        self._scenarios[ScenarioType.S3_NOT_FOUND] = Scenario(
            name="S3 Not Found",
            description="Backup files are missing from S3",
            scenario_type=ScenarioType.S3_NOT_FOUND,
            s3_fixtures={},  # No files
            command_configs={
                "myloader": MockCommandConfig(exit_code=0),
            },
        )

        # S3 permission denied
        self._scenarios[ScenarioType.S3_PERMISSION_DENIED] = Scenario(
            name="S3 Permission Denied",
            description="S3 access is denied",
            scenario_type=ScenarioType.S3_PERMISSION_DENIED,
            chaos=ChaosConfig(
                failure_rate=1.0,
                target_operations=["s3_get_object", "s3_head_object"],
                error_message="AccessDenied: Access Denied",
            ),
        )

        # myloader failure
        self._scenarios[ScenarioType.MYLOADER_FAILURE] = Scenario(
            name="Myloader Failure",
            description="myloader command fails with non-zero exit code",
            scenario_type=ScenarioType.MYLOADER_FAILURE,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/testhost/full/20240101_000000.xbstream.zst",
                ]
            },
            command_configs={
                "myloader": MockCommandConfig(
                    exit_code=1,
                    stderr="ERROR: Unable to connect to target database",
                ),
            },
        )

        # myloader timeout
        self._scenarios[ScenarioType.MYLOADER_TIMEOUT] = Scenario(
            name="Myloader Timeout",
            description="myloader takes too long and times out",
            scenario_type=ScenarioType.MYLOADER_TIMEOUT,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/testhost/full/20240101_000000.xbstream.zst",
                ]
            },
            command_configs={
                "myloader": MockCommandConfig(
                    exit_code=0,
                    delay_seconds=300,  # 5 minutes - will timeout
                ),
            },
        )

        # Post-SQL failure
        self._scenarios[ScenarioType.POST_SQL_FAILURE] = Scenario(
            name="Post-SQL Failure",
            description="Post-restore SQL script fails",
            scenario_type=ScenarioType.POST_SQL_FAILURE,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/testhost/full/20240101_000000.xbstream.zst",
                ]
            },
            command_configs={
                "myloader": MockCommandConfig(exit_code=0),
                "mysql": MockCommandConfig(
                    exit_code=1,
                    stderr="ERROR 1045 (28000): Access denied for user",
                ),
            },
        )

        # Random failures
        self._scenarios[ScenarioType.RANDOM_FAILURES] = Scenario(
            name="Random Failures",
            description="Random 20% failure rate on all operations",
            scenario_type=ScenarioType.RANDOM_FAILURES,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/testhost/full/20240101_000000.xbstream.zst",
                ]
            },
            chaos=ChaosConfig(
                failure_rate=0.2,
                target_operations=["myloader", "mysql", "s3_get_object"],
            ),
        )

        # Slow operations
        self._scenarios[ScenarioType.SLOW_OPERATIONS] = Scenario(
            name="Slow Operations",
            description="All operations have significant delays",
            scenario_type=ScenarioType.SLOW_OPERATIONS,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/testhost/full/20240101_000000.xbstream.zst",
                ]
            },
            command_configs={
                "myloader": MockCommandConfig(exit_code=0, delay_seconds=2.0),
                "mysql": MockCommandConfig(exit_code=0, delay_seconds=0.5),
            },
            chaos=ChaosConfig(delay_seconds=1.0),
        )

        # Intermittent failures
        self._scenarios[ScenarioType.INTERMITTENT_FAILURES] = Scenario(
            name="Intermittent Failures",
            description="Flaky operations that occasionally fail",
            scenario_type=ScenarioType.INTERMITTENT_FAILURES,
            s3_fixtures={
                "pulldb-backups": [
                    "backups/testhost/full/20240101_000000.xbstream.zst",
                ]
            },
            chaos=ChaosConfig(
                failure_rate=0.1,
                target_operations=["myloader"],
            ),
        )

    def register_scenario(self, scenario: Scenario) -> None:
        """Register a custom scenario."""
        self._scenarios[scenario.scenario_type] = scenario

    def list_scenarios(self) -> list[Scenario]:
        """Return all available scenarios."""
        return list(self._scenarios.values())

    def get_scenario(self, scenario_type: ScenarioType) -> Scenario | None:
        """Get a scenario by type."""
        return self._scenarios.get(scenario_type)

    def activate_scenario(
        self,
        scenario_type: ScenarioType,
        executor: MockProcessExecutor | None = None,
    ) -> Scenario:
        """Activate a scenario, resetting state and applying configuration.

        Args:
            scenario_type: The type of scenario to activate
            executor: Optional MockProcessExecutor to configure

        Returns:
            The activated Scenario

        Raises:
            ValueError: If scenario type is not found
        """
        scenario = self._scenarios.get(scenario_type)
        if scenario is None:
            raise ValueError(f"Unknown scenario type: {scenario_type}")

        # Reset simulation state
        reset_simulation()

        # Re-acquire fresh state after reset
        self.state = get_simulation_state()
        self._bus = get_event_bus()

        # Apply S3 fixtures
        for bucket, keys in scenario.s3_fixtures.items():
            with self.state.lock:
                if bucket not in self.state.s3_buckets:
                    self.state.s3_buckets[bucket] = []
                self.state.s3_buckets[bucket].extend(keys)

        # Apply command configs if executor provided
        if executor and scenario.command_configs:
            for cmd_prefix, config in scenario.command_configs.items():
                # Apply chaos modifiers if present
                if scenario.chaos and cmd_prefix in scenario.chaos.target_operations:
                    config = self._apply_chaos_to_config(config, scenario.chaos)
                executor.configure_command(cmd_prefix, config)

        # Run custom setup if present
        if scenario.setup_fn:
            scenario.setup_fn()

        self._current_scenario = scenario

        # Emit scenario change event
        self._bus.emit(
            EventType.SCENARIO_CHANGED,
            source="ScenarioManager",
            data={
                "scenario_type": scenario_type.value,
                "scenario_name": scenario.name,
            },
        )

        logger.info(f"Activated scenario: {scenario.name}")
        return scenario

    def _apply_chaos_to_config(
        self, config: MockCommandConfig, chaos: ChaosConfig
    ) -> MockCommandConfig:
        """Apply chaos configuration to a command config."""
        # Create handler that sometimes fails
        original_handler = config.handler

        def chaos_handler(
            command: list[str], env: dict[str, str] | None
        ) -> tuple[int, str, str]:
            # Random failure
            if chaos.failure_rate > 0 and random.random() < chaos.failure_rate:
                return (
                    1,
                    "",
                    chaos.error_message or "Chaos-injected failure",
                )

            # Call original handler or return default
            if original_handler:
                return original_handler(command, env)
            return config.exit_code, config.stdout, config.stderr

        return MockCommandConfig(
            exit_code=config.exit_code,
            stdout=config.stdout,
            stderr=config.stderr,
            delay_seconds=config.delay_seconds + chaos.delay_seconds,
            handler=chaos_handler,
        )

    def get_current_scenario(self) -> Scenario | None:
        """Return the currently active scenario."""
        return self._current_scenario

    def inject_chaos(
        self,
        operation: str,
        failure_rate: float = 0.5,
        error_message: str = "Chaos-injected error",
    ) -> None:
        """Inject chaos into a specific operation at runtime.

        This allows for dynamic chaos injection without changing scenarios.
        """
        if self._current_scenario is None:
            logger.warning("No active scenario - chaos injection may have no effect")

        chaos = ChaosConfig(
            failure_rate=failure_rate,
            target_operations=[operation],
            error_message=error_message,
        )

        if self._current_scenario:
            self._current_scenario.chaos = chaos

        logger.info(
            f"Injected chaos into {operation}: {failure_rate*100:.0f}% failure rate"
        )


def get_scenario_manager() -> ScenarioManager:
    """Get the singleton scenario manager instance."""
    global _scenario_manager
    if _scenario_manager is None:
        _scenario_manager = ScenarioManager()
    return _scenario_manager


def reset_scenario_manager() -> None:
    """Reset the scenario manager (for testing)."""
    global _scenario_manager
    _scenario_manager = None
