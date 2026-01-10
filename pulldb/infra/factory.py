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


def get_auth_repository():
    """Get AuthRepository implementation.
    
    Returns:
        AuthRepository for password and session management.
    """
    from pulldb.auth.repository import AuthRepository

    pool = _get_real_mysql_pool()
    return AuthRepository(pool)


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


def get_disallowed_user_repository() -> t.Any:
    """Get DisallowedUserRepository implementation."""
    # No simulation mode for this repository (simple lookup)
    from pulldb.infra.mysql import DisallowedUserRepository

    pool = _get_real_mysql_pool()
    return DisallowedUserRepository(pool)


def get_audit_repository() -> t.Any:
    """Get AuditRepository implementation.
    
    Returns:
        AuditRepository for logging administrative actions.
    """
    if is_simulation_mode():
        # Return None in simulation mode - audit logging is optional
        return None

    from pulldb.infra.mysql import AuditRepository

    pool = _get_real_mysql_pool()
    return AuditRepository(pool)


def get_provisioning_service(actor_user_id: str) -> t.Any:
    """Get HostProvisioningService instance.
    
    Creates a configured provisioning service with all dependencies injected.
    Used by both CLI (pulldb-admin hosts provision) and Web UI.
    
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
    from pulldb.domain.services.provisioning import HostProvisioningService

    host_repo = get_host_repository()
    audit_repo = get_audit_repository()

    return HostProvisioningService(
        host_repo=host_repo,
        audit_repo=audit_repo,
        actor_user_id=actor_user_id,
    )


def _get_real_mysql_pool() -> t.Any:
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

    return MySQLPool(
        host=creds.host,
        user=mysql_user,
        password=creds.password,
        database=mysql_database,
        port=creds.port,
    )

