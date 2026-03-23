"""Conftest for tests/unit/simulation/.

SECURITY: Provides an autouse fixture that calls reset_simulation() before
every test in this directory. This ensures:
  - In-memory state (jobs, users, hosts, settings, S3 buckets) is clean
  - Event bus subscribers are cleared
  - Scenario manager is reset
  - No state leaks between tests regardless of test type

Using reset_simulation() (not state.clear()) is critical because state.clear()
only clears data dictionaries. Event bus subscribers and ScenarioManager
configuration persist until reset_simulation() is called.

HCA Layer: tests (shared test infrastructure)
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_simulation_state() -> None:
    """Reset all simulation state before every test in tests/unit/simulation/.

    Called before each test regardless of whether the test class or function
    also calls state.clear() manually. This is the safety net.
    """
    from pulldb.simulation.core.state import reset_simulation

    reset_simulation()
