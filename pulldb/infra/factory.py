"""Infrastructure factory for dependency injection.

Handles creation of infrastructure components (repositories, clients)
based on configuration (Real vs Simulation).

HCA Layer: shared
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pulldb.domain.interfaces import (
    AuditRepository,
    AuthRepository,
    DisallowedUserRepository,
    HostRepository,
    JobRepository,
    ProcessExecutor,
    S3Client,
    SettingsRepository,
    UserRepository,
)


if TYPE_CHECKING:
    from pulldb.infra.mysql import (
        AdminTaskRepository,
        JobHistorySummaryRepository,
        MySQLPool,
    )
    from pulldb.worker.provisioning import HostProvisioningService


def get_mode() -> str:
    """Get current operation mode (REAL or SIMULATION)."""
    return os.getenv("PULLDB_MODE", "REAL").upper()


def is_simulation_mode() -> bool:
    """Check if running in simulation mode."""
    return get_mode() == "SIMULATION"


def get_job_repository() -> JobRepository:
    """Get JobRepository implementation."""
    if is_simulation_mode():
        from pulldb.simulation import SimulatedJobRepository

        return SimulatedJobRepository()

    # Real mode - lazy import to avoid circular deps
    from pulldb.infra.mysql import JobRepository as MySQLJobRepository

    pool = _get_real_mysql_pool()
    return MySQLJobRepository(pool)


def get_s3_client(profile: str | None = None, region: str | None = None) -> S3Client:
    """Get S3Client implementation."""
    if is_simulation_mode():
        from pulldb.simulation import MockS3Client

        return MockS3Client()

    from pulldb.infra.s3 import S3Client as BotoS3Client

    return BotoS3Client(profile=profile, region=region)


def get_process_executor() -> ProcessExecutor:
    """Get ProcessExecutor implementation."""
    if is_simulation_mode():
        from pulldb.simulation import MockProcessExecutor

        return MockProcessExecutor()

    from pulldb.infra.exec import SubprocessExecutor

    return SubprocessExecutor()


def get_auth_repository() -> AuthRepository:
    """Get AuthRepository implementation.

    Returns:
        AuthRepository for password and session management.
    """
    if is_simulation_mode():
        from pulldb.simulation import SimulatedAuthRepository

        return SimulatedAuthRepository()

    from pulldb.auth.repository import AuthRepository as AuthRepositoryImpl

    pool = _get_real_mysql_pool()
    return AuthRepositoryImpl(pool)


def get_user_repository() -> UserRepository:
    """Get UserRepository implementation."""
    if is_simulation_mode():
        from pulldb.simulation import SimulatedUserRepository

        return SimulatedUserRepository()

    from pulldb.infra.mysql import UserRepository as MySQLUserRepository

    pool = _get_real_mysql_pool()
    return MySQLUserRepository(pool)


def get_host_repository() -> HostRepository:
    """Get HostRepository implementation."""
    if is_simulation_mode():
        from pulldb.simulation import SimulatedHostRepository

        return SimulatedHostRepository()

    from pulldb.infra.mysql import HostRepository as MySQLHostRepository
    from pulldb.infra.secrets import CredentialResolver

    pool = _get_real_mysql_pool()
    aws_profile = os.getenv("PULLDB_AWS_PROFILE")
    resolver = CredentialResolver(aws_profile=aws_profile)
    return MySQLHostRepository(pool, resolver)


def get_settings_repository() -> SettingsRepository:
    """Get SettingsRepository implementation."""
    if is_simulation_mode():
        from pulldb.simulation import SimulatedSettingsRepository

        return SimulatedSettingsRepository()

    from pulldb.infra.mysql import SettingsRepository as MySQLSettingsRepository

    pool = _get_real_mysql_pool()
    return MySQLSettingsRepository(pool)


def get_disallowed_user_repository(
    pool: MySQLPool | None = None,
) -> DisallowedUserRepository:
    """Get DisallowedUserRepository implementation."""
    if is_simulation_mode():
        from pulldb.simulation import SimulatedDisallowedUserRepository

        return SimulatedDisallowedUserRepository()

    from pulldb.infra.mysql import DisallowedUserRepository as DisallowedUserRepoImpl

    _pool = pool or _get_real_mysql_pool()
    return DisallowedUserRepoImpl(_pool)


def get_admin_task_repository(pool: MySQLPool | None = None) -> AdminTaskRepository:
    """Get AdminTaskRepository implementation."""
    if is_simulation_mode():
        from pulldb.simulation import SimulatedAdminTaskRepository

        return SimulatedAdminTaskRepository()  # type: ignore[return-value]

    from pulldb.infra.mysql import AdminTaskRepository as AdminTaskRepoImpl

    _pool = pool or _get_real_mysql_pool()
    return AdminTaskRepoImpl(_pool)


def get_job_history_summary_repository() -> JobHistorySummaryRepository | None:
    """Get JobHistorySummaryRepository implementation.

    Returns:
        Repository for job history summary operations.
    """
    if is_simulation_mode():
        from pulldb.simulation import SimulatedJobHistorySummaryRepository

        return SimulatedJobHistorySummaryRepository()  # type: ignore[return-value]

    from pulldb.infra.mysql import JobHistorySummaryRepository

    pool = _get_real_mysql_pool()
    return JobHistorySummaryRepository(pool)


def get_audit_repository() -> AuditRepository | None:
    """Get AuditRepository implementation.

    Returns:
        AuditRepository for logging administrative actions.
    """
    if is_simulation_mode():
        from pulldb.simulation import SimulatedAuditRepository

        return SimulatedAuditRepository()

    from pulldb.infra.mysql import AuditRepository as AuditRepositoryImpl

    pool = _get_real_mysql_pool()
    return AuditRepositoryImpl(pool)


def get_provisioning_service(actor_user_id: str) -> HostProvisioningService:
    """Get HostProvisioningService instance.

    Creates a configured provisioning service with all dependencies injected.
    Used by both CLI (pulldb-admin hosts provision) and Web UI.

    Simulation-safe: get_host_repository() and get_audit_repository() both
    return simulated implementations when is_simulation_mode() is True.
    Callers in the web layer should guard with is_simulation_mode() before
    invoking service methods that would perform real I/O.

    Args:
        actor_user_id: UUID of the user performing operations.
            Used for audit logging.

    Returns:
        HostProvisioningService instance ready for use.

    Example:
        >>> from pulldb.infra.factory import get_provisioning_service
        >>>
        >>> # For CLI, look up user_id from username
        >>> user = get_user_repository().get_user_by_username("admin")
        >>> service = get_provisioning_service(user.user_id)
        >>>
        >>> # For Web UI, use session user_id
        >>> service = get_provisioning_service(current_user.user_id)
    """
    from pulldb.worker.provisioning import HostProvisioningService

    host_repo = get_host_repository()
    audit_repo = get_audit_repository()

    return HostProvisioningService(
        host_repo=host_repo,
        audit_repo=audit_repo,
        actor_user_id=actor_user_id,
    )


def _get_real_mysql_pool() -> MySQLPool:
    """Create real MySQL connection pool."""
    from pulldb.infra.mysql import MySQLPool
    from pulldb.infra.secrets import CredentialResolver

    secret_ref = os.getenv(
        "PULLDB_COORDINATION_SECRET", "aws-secretsmanager:/pulldb/mysql/coordination-db"
    )

    aws_profile = os.getenv("PULLDB_AWS_PROFILE")
    resolver = CredentialResolver(aws_profile=aws_profile)
    creds = resolver.resolve(secret_ref)

    mysql_user = os.getenv("PULLDB_API_MYSQL_USER", "pulldb_api")
    mysql_database = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb_service")
    pool_size = int(os.getenv("PULLDB_MYSQL_POOL_SIZE", "5"))

    kwargs: dict = {
        "host": creds.host,
        "user": mysql_user,
        "password": creds.password,
        "database": mysql_database,
        "port": creds.port,
    }
    unix_socket = os.getenv("PULLDB_MYSQL_SOCKET")
    if unix_socket:
        kwargs["unix_socket"] = unix_socket

    return MySQLPool(
        pool_name="pulldb_api",
        pool_size=pool_size,
        **kwargs,
    )

