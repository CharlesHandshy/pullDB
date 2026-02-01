"""Type definitions for pullDB API.

HCA Layer: pages
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pulldb.domain.config import Config

if TYPE_CHECKING:
    from pulldb.domain.interfaces import (
        AuditRepository,
        AuthRepository,
        HostRepository,
        JobRepository,
        SettingsRepository,
        UserRepository,
    )
    from pulldb.infra.mysql import MySQLPool
    from pulldb.worker.overlord_manager import OverlordManager


class APIState(NamedTuple):
    """Cached application state shared across requests.

    Attributes:
        config: Application configuration.
        pool: MySQLPool in REAL mode, None in SIMULATION mode.
        user_repo: Repository for user operations.
        job_repo: Repository for job queue operations.
        settings_repo: Repository for settings operations.
        host_repo: Repository for database host operations.
        auth_repo: Optional auth repository (Phase 4).
        audit_repo: Optional audit logging repository.
        overlord_manager: Optional overlord manager for overlord.companies integration.
    """

    config: Config
    pool: "MySQLPool | None"
    user_repo: "UserRepository"
    job_repo: "JobRepository"
    settings_repo: "SettingsRepository"
    host_repo: "HostRepository"
    auth_repo: "AuthRepository | None" = None
    audit_repo: "AuditRepository | None" = None
    overlord_manager: "OverlordManager | None" = None
