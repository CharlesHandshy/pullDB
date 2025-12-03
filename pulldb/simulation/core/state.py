"""In-memory state for the Simulation Engine.

Holds the "database" state (jobs, users, hosts, settings) in thread-safe
structures. Acts as the single source of truth for all Mock Repositories.
"""

from __future__ import annotations

import threading
import typing as t
from dataclasses import dataclass, field

from pulldb.domain.models import DBHost, Job, JobEvent, User


@dataclass
class SimulationState:
    """Thread-safe in-memory database state."""

    # Data stores (Table replacements)
    jobs: dict[str, Job] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)
    hosts: dict[str, DBHost] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)
    job_events: list[JobEvent] = field(default_factory=list)
    
    # S3 State
    # bucket_name -> list of keys
    s3_buckets: dict[str, list[str]] = field(default_factory=dict)

    # Indexes (for performance/lookups)
    # user_code -> User
    users_by_code: dict[str, User] = field(default_factory=dict)
    
    # Auth state (Phase 4)
    # user_id -> {password_hash, totp_secret, etc.}
    auth_credentials: dict[str, dict[str, t.Any]] = field(default_factory=dict)
    # token_hash -> session data
    sessions: dict[str, dict[str, t.Any]] = field(default_factory=dict)
    
    # Job cancellation tracking (set of job_ids with pending cancellation requests)
    cancellation_requested: set[str] = field(default_factory=set)
    
    # Concurrency control
    lock: threading.RLock = field(default_factory=threading.RLock)

    def clear(self) -> None:
        """Reset state to empty (for testing)."""
        with self.lock:
            self.jobs.clear()
            self.users.clear()
            self.hosts.clear()
            self.settings.clear()
            self.job_events.clear()
            self.s3_buckets.clear()
            self.users_by_code.clear()
            self.auth_credentials.clear()
            self.sessions.clear()
            self.cancellation_requested.clear()


# Global singleton instance
_state = SimulationState()


def get_simulation_state() -> SimulationState:
    """Get the global simulation state instance."""
    return _state


def reset_simulation() -> None:
    """Reset simulation state (for testing).

    This also resets the event bus and scenario manager to ensure clean test isolation.
    """
    # Import here to avoid circular import
    from pulldb.simulation.core.bus import reset_event_bus
    from pulldb.simulation.core.scenarios import reset_scenario_manager

    _state.clear()
    reset_event_bus()
    reset_scenario_manager()
