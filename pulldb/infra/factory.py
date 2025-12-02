"""Infrastructure factory for dependency injection.

Handles creation of infrastructure components (repositories, clients)
based on configuration (Real vs Simulation).
"""

from __future__ import annotations

import os
import typing as t

from pulldb.domain.interfaces import (
    HostRepository,
    JobRepository,
    ProcessExecutor,
    S3Client,
    SettingsRepository,
    UserRepository,
)
from pulldb.infra.exec import SubprocessExecutor
from pulldb.infra.mysql import HostRepository as MySQLHostRepository
from pulldb.infra.mysql import JobRepository as MySQLJobRepository
from pulldb.infra.mysql import MySQLPool
from pulldb.infra.mysql import SettingsRepository as MySQLSettingsRepository
from pulldb.infra.mysql import UserRepository as MySQLUserRepository
from pulldb.infra.s3 import S3Client as BotoS3Client
from pulldb.infra.secrets import CredentialResolver


def get_mode() -> str:
    """Get current operation mode (REAL or SIMULATION)."""
    return os.getenv("PULLDB_MODE", "REAL").upper()


def get_job_repository() -> JobRepository:
    """Get JobRepository implementation."""
    mode = get_mode()
    if mode == "SIMULATION":
        # TODO: Import and return SimulatedJobRepository
        raise NotImplementedError("Simulation mode not yet implemented")

    # Real mode
    pool = _get_real_mysql_pool()
    return MySQLJobRepository(pool)


def get_s3_client(profile: str | None = None, region: str | None = None) -> S3Client:
    """Get S3Client implementation."""
    mode = get_mode()
    if mode == "SIMULATION":
        # TODO: Import and return SimulatedS3Client
        raise NotImplementedError("Simulation mode not yet implemented")

    return BotoS3Client(profile=profile, region=region)


def get_process_executor() -> ProcessExecutor:
    """Get ProcessExecutor implementation."""
    mode = get_mode()
    if mode == "SIMULATION":
        # TODO: Import and return SimulatedProcessExecutor
        raise NotImplementedError("Simulation mode not yet implemented")

    return SubprocessExecutor()


def get_user_repository() -> UserRepository:
    """Get UserRepository implementation."""
    mode = get_mode()
    if mode == "SIMULATION":
        # TODO: Import and return SimulatedUserRepository
        raise NotImplementedError("Simulation mode not yet implemented")

    pool = _get_real_mysql_pool()
    return MySQLUserRepository(pool)


def get_host_repository() -> HostRepository:
    """Get HostRepository implementation."""
    mode = get_mode()
    if mode == "SIMULATION":
        # TODO: Import and return SimulatedHostRepository
        raise NotImplementedError("Simulation mode not yet implemented")

    pool = _get_real_mysql_pool()
    aws_profile = os.getenv("PULLDB_AWS_PROFILE")
    resolver = CredentialResolver(aws_profile=aws_profile)
    return MySQLHostRepository(pool, resolver)


def get_settings_repository() -> SettingsRepository:
    """Get SettingsRepository implementation."""
    mode = get_mode()
    if mode == "SIMULATION":
        # TODO: Import and return SimulatedSettingsRepository
        raise NotImplementedError("Simulation mode not yet implemented")

    pool = _get_real_mysql_pool()
    return MySQLSettingsRepository(pool)


def _get_real_mysql_pool() -> t.Any:
    """Create real MySQL connection pool."""
    secret_ref = os.getenv(
        "PULLDB_COORDINATION_SECRET", "aws-secretsmanager:/pulldb/mysql/coordination-db"
    )

    aws_profile = os.getenv("PULLDB_AWS_PROFILE")
    resolver = CredentialResolver(aws_profile=aws_profile)
    creds = resolver.resolve(secret_ref)

    mysql_user = os.getenv("PULLDB_API_MYSQL_USER", "pulldb_api")
    mysql_database = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb_service")

    return MySQLPool(
        host=creds.host,
        user=mysql_user,
        password=creds.password,
        database=mysql_database,
        port=creds.port,
    )
