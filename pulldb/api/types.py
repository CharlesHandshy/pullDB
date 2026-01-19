"""Type definitions for pullDB API.

HCA Layer: pages
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from pulldb.domain.config import Config

if TYPE_CHECKING:
    from pulldb.auth import AuthRepository


class APIState(NamedTuple):
    """Cached application state shared across requests."""

    config: Config
    pool: Any  # MySQLPool in REAL mode, None in SIMULATION mode
    user_repo: Any  # UserRepository protocol
    job_repo: Any  # JobRepository protocol
    settings_repo: Any  # SettingsRepository protocol
    host_repo: Any  # HostRepository protocol
    auth_repo: "AuthRepository | None" = None  # Phase 4: Optional auth repository
    audit_repo: Any = None  # AuditRepository for audit logging
