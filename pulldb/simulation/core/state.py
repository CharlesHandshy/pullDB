"""In-memory state for the Simulation Engine.

Holds the "database" state (jobs, users, hosts, settings) in thread-safe
structures. Acts as the single source of truth for all Mock Repositories.

HCA Layer: features
"""

from __future__ import annotations

import threading
from typing import Any
from dataclasses import dataclass, field

from pulldb.domain.models import DBHost, Job, JobEvent, User


@dataclass
class SimulationState:
    """Thread-safe in-memory database state for simulation engine.

    Acts as the single source of truth for all Mock Repositories,
    replacing MySQL tables with Python dictionaries.

    Attributes:
        jobs: Job ID -> Job mapping (replaces jobs table).
        users: User ID -> User mapping (replaces users table).
        hosts: Hostname -> DBHost mapping (replaces db_hosts table).
        settings: Key -> value mapping (replaces settings table).
        settings_metadata: Key -> {description, etc.} metadata.
        job_events: Chronological list of job events.
        audit_logs: Chronological list of audit entries.
        s3_buckets: Bucket name -> list of object keys.
        users_by_code: User code -> User index for quick lookup.
        auth_credentials: User ID -> auth data (password hash, TOTP, etc.).
        sessions: Token hash -> session data for auth.
        user_hosts: User ID -> list of host assignments.
        cancellation_requested: Set of job IDs with pending cancellation.
        staging_databases: Hostname -> set of database names on staging.
        deleted_orphans: Set of (hostname, db_name) tuples deleted this session.
        orphan_sizes: (hostname, db_name) -> size in MB for orphan databases.
        orphan_metadata: (hostname, db_name) -> OrphanMetadata for mock data.
        api_keys: Key ID -> API key configuration dict.
        disallowed_usernames: Username -> {reason, is_hardcoded, etc.}.
        host_credential_errors: Hostname -> error message if credentials failed.
        lock: Reentrant lock for thread-safe operations.
    """

    # Data stores (Table replacements)
    jobs: dict[str, Job] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)
    hosts: dict[str, DBHost] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)
    settings_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    job_events: list[JobEvent] = field(default_factory=list)
    audit_logs: list[dict[str, Any]] = field(default_factory=list)
    
    # S3 State
    # bucket_name -> list of keys
    s3_buckets: dict[str, list[str]] = field(default_factory=dict)

    # Indexes (for performance/lookups)
    # user_code -> User
    users_by_code: dict[str, User] = field(default_factory=dict)
    
    # Auth state (Phase 4)
    # user_id -> {password_hash, totp_secret, etc.}
    auth_credentials: dict[str, dict[str, Any]] = field(default_factory=dict)
    # token_hash -> session data
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    # user_id -> list of {host_id, is_default, assigned_at, assigned_by}
    user_hosts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    
    # Job cancellation tracking (set of job_ids with pending cancellation requests)
    cancellation_requested: set[str] = field(default_factory=set)
    
    # Orphan database simulation
    # hostname -> set of database names that exist on that staging host
    staging_databases: dict[str, set[str]] = field(default_factory=dict)
    # (hostname, db_name) tuples of orphans deleted this session
    deleted_orphans: set[tuple[str, str]] = field(default_factory=set)
    # (hostname, db_name) -> size in MB for mock orphan databases
    orphan_sizes: dict[tuple[str, str], float] = field(default_factory=dict)
    # (hostname, db_name) -> OrphanMetadata for mock metadata (lazy import to avoid circular)
    orphan_metadata: dict[tuple[str, str], Any] = field(default_factory=dict)
    
    # Phase 0.5: API keys for approval workflow screenshots
    # key_id -> {user_id, name, host_name, created_at, approved_at, approved_by, is_active, ...}
    api_keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    
    # Phase 0.5: Disallowed usernames for admin page screenshots
    # username -> {reason, is_hardcoded, created_at, created_by}
    disallowed_usernames: dict[str, dict[str, Any]] = field(default_factory=dict)
    
    # Phase 0.5: Host credential error state tracking
    # hostname -> error message (if credentials failed)
    host_credential_errors: dict[str, str] = field(default_factory=dict)
    
    # Concurrency control
    lock: threading.RLock = field(default_factory=threading.RLock)

    def clear(self) -> None:
        """Reset state to empty (for testing)."""
        with self.lock:
            self.jobs.clear()
            self.users.clear()
            self.hosts.clear()
            self.settings.clear()
            self.settings_metadata.clear()
            self.job_events.clear()
            self.audit_logs.clear()
            self.s3_buckets.clear()
            self.users_by_code.clear()
            self.auth_credentials.clear()
            self.sessions.clear()
            self.user_hosts.clear()
            self.cancellation_requested.clear()
            self.staging_databases.clear()
            self.deleted_orphans.clear()
            self.orphan_sizes.clear()
            self.orphan_metadata.clear()
            self.api_keys.clear()
            self.disallowed_usernames.clear()
            self.host_credential_errors.clear()


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
