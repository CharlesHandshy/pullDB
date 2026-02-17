"""MySQL infrastructure facade for pullDB.

Re-exports all repository classes and pool utilities from decomposed modules.
Consumers should import from ``pulldb.infra.mysql`` — this facade ensures
backward compatibility while the implementation is split across focused modules:

- mysql_pool: Connection pool, typed cursors, helper functions
- mysql_jobs: JobRepository (job queue CRUD, status, events, locking, cleanup)
- mysql_users: UserRepository (user CRUD, code generation, bulk ops)
- mysql_audit: AuditRepository (audit log recording/querying)
- mysql_hosts: HostRepository (host config, credentials, capacity)
- mysql_settings: SettingsRepository (key-value settings)
- mysql_admin: AdminTaskRepository, DisallowedUserRepository
- mysql_history: JobHistorySummaryRepository (analytics, error categorization)

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

# Pool infrastructure (mysql_pool.py)
from pulldb.infra.mysql_pool import (
    DictRow,
    MySQLPool,
    TupleRow,
    TypedDictCursor,
    TypedTupleCursor,
    _dict_row,
    _dict_rows,
    build_default_pool,
)

# Job repository (mysql_jobs.py)
from pulldb.infra.mysql_jobs import JobRepository

# User repository (mysql_users.py)
from pulldb.infra.mysql_users import UserRepository

# Audit repository (mysql_audit.py)
from pulldb.infra.mysql_audit import AuditRepository

# Host repository (mysql_hosts.py)
from pulldb.infra.mysql_hosts import HostRepository

# Settings repository (mysql_settings.py)
from pulldb.infra.mysql_settings import SettingsRepository

# Admin repositories (mysql_admin.py)
from pulldb.infra.mysql_admin import AdminTaskRepository, DisallowedUserRepository

# History repository (mysql_history.py)
from pulldb.infra.mysql_history import JobHistorySummaryRepository

__all__ = [
    # Pool infrastructure
    "DictRow",
    "MySQLPool",
    "TupleRow",
    "TypedDictCursor",
    "TypedTupleCursor",
    "_dict_row",
    "_dict_rows",
    "build_default_pool",
    # Repositories
    "AdminTaskRepository",
    "AuditRepository",
    "DisallowedUserRepository",
    "HostRepository",
    "JobHistorySummaryRepository",
    "JobRepository",
    "SettingsRepository",
    "UserRepository",
]
