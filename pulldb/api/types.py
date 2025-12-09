"""Type definitions for pullDB API."""

from __future__ import annotations

import typing as t
from typing import TYPE_CHECKING

from pulldb.domain.config import Config

if TYPE_CHECKING:
    from pulldb.auth import AuthRepository


class APIState(t.NamedTuple):
    """Cached application state shared across requests."""

    config: Config
    pool: t.Any  # MySQLPool in REAL mode, None in SIMULATION mode
    user_repo: t.Any  # UserRepository protocol
    job_repo: t.Any  # JobRepository protocol
    settings_repo: t.Any  # SettingsRepository protocol
    host_repo: t.Any  # HostRepository protocol
    auth_repo: "AuthRepository | None" = None  # Phase 4: Optional auth repository
    audit_repo: t.Any = None  # AuditRepository for audit logging
