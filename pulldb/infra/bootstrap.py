"""Shared configuration bootstrap for API and Worker services.

Provides unified two-phase configuration loading:
1. Bootstrap from environment (MySQL credentials, AWS profile)
2. Resolve Secrets Manager credentials
3. Connect to MySQL
4. Load full config from env + MySQL settings

Both API and Worker services use this pattern to ensure consistency.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pulldb.domain.config import Config
from pulldb.infra.logging import get_logger
from pulldb.infra.mysql import MySQLPool, build_default_pool
from pulldb.infra.secrets import CredentialResolver

if TYPE_CHECKING:
    pass

logger = get_logger("pulldb.infra.bootstrap")


def bootstrap_service_config(
    *,
    service_mysql_user_env: str,
    service_name: str,
) -> tuple[Config, MySQLPool]:
    """Bootstrap configuration for a pullDB service.

    Two-phase loading pattern:
    1. Load minimal config from environment
    2. Resolve Secrets Manager credentials
    3. Connect to MySQL
    4. Load full config from env + MySQL settings

    Args:
        service_mysql_user_env: Environment variable name for MySQL user
            (e.g., "PULLDB_API_MYSQL_USER" or "PULLDB_WORKER_MYSQL_USER").
        service_name: Service name for error messages (e.g., "API service").

    Returns:
        Tuple of (fully_loaded_config, mysql_pool)

    Raises:
        RuntimeError: If required config is missing or connection fails.
    """
    # Phase 1: Bootstrap from environment
    try:
        config = Config.minimal_from_env()
    except Exception as exc:
        raise RuntimeError(
            f"Failed loading pullDB configuration from environment for {service_name}: "
            f"{exc}. Configure PULLDB_MYSQL_* variables or consult docs/testing.md."
        ) from exc

    # Default to pr-dev profile if not specified (required for Secrets Manager access)
    if not config.aws_profile:
        config.aws_profile = "pr-dev"

    # Phase 2: Service-specific MySQL user (REQUIRED)
    mysql_user = os.getenv(service_mysql_user_env)
    if not mysql_user:
        raise RuntimeError(
            f"{service_mysql_user_env} is required. "
            f"Set it to the {service_name} MySQL user."
        )
    config.mysql_user = mysql_user.strip()

    # Phase 3: Resolve coordination credentials from Secrets Manager
    # NOTE: "coordination-db" in the secret path is just a name component.
    # The actual database name comes from PULLDB_MYSQL_DATABASE (default: pulldb_service).
    # The secret returns host and password only; username comes from service_mysql_user_env.
    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if coordination_secret and not config.mysql_password:
        try:
            resolver = CredentialResolver(config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            config.mysql_host = creds.host
            config.mysql_password = creds.password
            logger.info(
                f"Resolved coordination credentials from {coordination_secret} "
                f"(host={creds.host}, user={config.mysql_user})"
            )
        except Exception as e:
            logger.warning(f"Failed to resolve coordination secret: {e}")

    # Phase 4: Connect to MySQL
    try:
        pool = build_default_pool(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
            unix_socket=config.mysql_socket,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed connecting to coordination database for {service_name}. "
            f"Attempted {config.mysql_host}/{config.mysql_database}: {exc}."
        ) from exc

    # Phase 5: Load full config from env + MySQL settings
    full_config = Config.from_env_and_mysql(pool)

    # Preserve service-specific MySQL user (from_env_and_mysql reloads from minimal)
    full_config.mysql_user = mysql_user.strip()

    # Preserve AWS profile
    if config.aws_profile:
        full_config.aws_profile = config.aws_profile

    return full_config, pool
