"""Mock Process Executor for Simulation Mode.

Implements the ProcessExecutor protocol.
Simulates command execution with configurable delays and outcomes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pulldb.domain.models import CommandResult
from pulldb.simulation.core.bus import EventType, get_event_bus
from pulldb.simulation.core.state import get_simulation_state

logger = logging.getLogger(__name__)


@dataclass
class MockCommandConfig:
    """Configuration for a specific command simulation."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    delay_seconds: float = 0.0
    # If set, this function is called instead of default behavior
    # signature: (command, env) -> (exit_code, stdout, stderr)
    handler: Callable[..., tuple[int, str, str]] | None = None


class MockProcessExecutor:
    """In-memory implementation of ProcessExecutor."""

    def __init__(self, fast_mode: bool = True) -> None:
        """Initialize with shared simulation state.
        
        Args:
            fast_mode: If True (default), skip sleep delays for faster tests.
                      Set False only for real-time simulation scenarios.
        """
        self.state = get_simulation_state()
        self._bus = get_event_bus()
        # Map command prefix (first arg) to config
        self.configs: dict[str, MockCommandConfig] = {}
        # Default config if no match found
        self.default_config = MockCommandConfig()
        # Fast mode skips real sleeps (useful for tests)
        self.fast_mode = fast_mode

    def configure_command(self, command_prefix: str, config: MockCommandConfig) -> None:
        """Configure behavior for a specific command."""
        self.configs[command_prefix] = config

    def _get_config(self, command: Sequence[str]) -> MockCommandConfig:
        if not command:
            return self.default_config

        cmd_name = command[0]
        return self.configs.get(cmd_name, self.default_config)

    def _maybe_sleep(self, seconds: float) -> None:
        """Sleep only if not in fast_mode."""
        if not self.fast_mode and seconds > 0:
            time.sleep(seconds)

    def run_command(self, command: list[str], env: dict[str, str] | None = None) -> int:
        """Run command and return exit code."""
        config = self._get_config(command)
        cmd_str = " ".join(command)

        logger.info(f"Mock executing: {cmd_str}")
        self._bus.emit(
            EventType.EXEC_START,
            source="MockProcessExecutor",
            data={"command": cmd_str, "method": "run_command"},
        )

        self._maybe_sleep(config.delay_seconds)

        if config.handler:
            exit_code, _, _ = config.handler(command, env)
        else:
            exit_code = config.exit_code

        if exit_code == 0:
            self._bus.emit(
                EventType.EXEC_COMPLETE,
                source="MockProcessExecutor",
                data={"command": cmd_str, "exit_code": exit_code},
            )
        else:
            self._bus.emit(
                EventType.EXEC_ERROR,
                source="MockProcessExecutor",
                data={"command": cmd_str, "exit_code": exit_code},
            )

        return exit_code

    def run_command_streaming(
        self,
        command: Sequence[str],
        line_callback: Callable[[str], None],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        """Execute command, streaming merged stdout/stderr to callback."""
        started_at = datetime.now(UTC)
        config = self._get_config(command)
        cmd_str = " ".join(command)

        logger.info(f"Mock streaming: {cmd_str}")
        self._bus.emit(
            EventType.EXEC_START,
            source="MockProcessExecutor",
            data={"command": cmd_str, "method": "run_command_streaming"},
        )

        self._maybe_sleep(config.delay_seconds)

        stdout = config.stdout
        stderr = config.stderr
        exit_code = config.exit_code

        if config.handler:
            exit_code, stdout, stderr = config.handler(command, env)

        # Stream output line by line
        if stdout:
            for line in stdout.splitlines():
                line_callback(line)
        if stderr:
            for line in stderr.splitlines():
                line_callback(line)

        completed_at = datetime.now(UTC)
        duration = (completed_at - started_at).total_seconds()

        if exit_code == 0:
            self._bus.emit(
                EventType.EXEC_COMPLETE,
                source="MockProcessExecutor",
                data={"command": cmd_str, "exit_code": exit_code, "duration": duration},
            )
        else:
            self._bus.emit(
                EventType.EXEC_ERROR,
                source="MockProcessExecutor",
                data={"command": cmd_str, "exit_code": exit_code, "stderr": stderr},
            )

        return CommandResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            command=list(command),
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
        )
