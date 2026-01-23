from __future__ import annotations

"""Integration tests for Config with real MySQL database.

    HCA Layer: tests

These tests connect to the actual pulldb database to verify
from_env_and_mysql() works with real MySQL settings table.

Uses AWS Secrets Manager to resolve MySQL credentials for network login.
"""

import os
from collections.abc import Generator
from typing import Any

import pytest

from pulldb.domain.config import Config
from pulldb.infra.mysql import build_default_pool


@pytest.fixture(autouse=True)
def clear_env() -> Generator[None, None, None]:
    """Clear PULLDB_* environment variables before each test."""
    pulldb_vars = {k: v for k, v in os.environ.items() if k.startswith("PULLDB_")}
    for key in pulldb_vars:
        del os.environ[key]
    yield
    # Restore
    for key, value in pulldb_vars.items():
        os.environ[key] = value


@pytest.mark.integration
class TestConfigIntegration:
    """Integration tests with real MySQL database."""

    def test_load_from_real_database(
        self,
        mysql_network_credentials: tuple[str, str, str],
        mysql_pool: Any,  # Ensure database exists with test data
    ) -> None:
        """Test loading config from actual pulldb database.

        Uses localhost network login with credentials from AWS Secrets Manager.
        Verifies MySQL settings table is read correctly.

        Note: PULLDB_MYSQL_USER is NOT read by Config.minimal_from_env() because
        mysql_user is service-specific. We pass credentials directly to the pool.
        """
        host, username, password = mysql_network_credentials

        # Set up minimal environment
        os.environ["PULLDB_MYSQL_HOST"] = host
        os.environ["PULLDB_MYSQL_PASSWORD"] = password
        os.environ["PULLDB_MYSQL_DATABASE"] = "pulldb_service"  # Match test fixture database

        # Bootstrap: Load minimal config (host/password only)
        bootstrap_config = Config.minimal_from_env()

        # Connect to MySQL - pass username directly since Config doesn't load it
        pool = build_default_pool(
            host=bootstrap_config.mysql_host,
            user=username,  # Pass directly, not from config
            password=bootstrap_config.mysql_password,
            database=bootstrap_config.mysql_database,
        )
        # Load full config with MySQL settings (pool passed directly)
        config = Config.from_env_and_mysql(pool)

        # Verify MySQL credentials
        assert config.mysql_host == host
        assert config.mysql_user == ""  # Config doesn't load PULLDB_MYSQL_USER
        assert config.mysql_password == password
        assert config.mysql_database == "pulldb_service"  # Test database

        # Verify operational settings came from MySQL settings table
        # (these are populated by conftest.py test data seeding)
        assert config.s3_bucket_path == "pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/"
        assert config.default_dbhost == "localhost"

    def test_environment_override_with_real_database(
        self,
        mysql_network_credentials: tuple[str, str, str],
        mysql_pool: Any,  # Ensure database exists with test data
    ) -> None:
        """Test that environment variables override MySQL settings."""
        host, username, password = mysql_network_credentials

        # Set environment variables that should override MySQL
        os.environ["PULLDB_MYSQL_HOST"] = host
        os.environ["PULLDB_MYSQL_PASSWORD"] = password
        os.environ["PULLDB_MYSQL_DATABASE"] = "pulldb_service"  # Match test fixture database
        os.environ["PULLDB_S3_BUCKET_PATH"] = "s3://override-bucket/"
        os.environ["PULLDB_DEFAULT_DBHOST"] = "override-dbhost"

        bootstrap_config = Config.minimal_from_env()
        pool = build_default_pool(
            host=bootstrap_config.mysql_host,
            user=username,  # Pass directly
            password=bootstrap_config.mysql_password,
            database=bootstrap_config.mysql_database,
        )
        # Pool passed directly to from_env_and_mysql()
        config = Config.from_env_and_mysql(pool)

        # Environment should take precedence
        assert config.s3_bucket_path == "s3://override-bucket/"
        assert config.default_dbhost == "override-dbhost"

    def test_two_phase_loading_pattern(
        self,
        mysql_network_credentials: tuple[str, str, str],
        mysql_pool: Any,  # Ensure database exists with test data
    ) -> None:
        """Test the recommended two-phase loading pattern.

        Phase 1: minimal_from_env() for bootstrap credentials (host, password only)
        Phase 2: from_env_and_mysql() for full configuration

        Note: mysql_user must be passed separately since Config.minimal_from_env()
        does not read PULLDB_MYSQL_USER - it's service-specific.
        """
        host, username, password = mysql_network_credentials

        os.environ["PULLDB_MYSQL_HOST"] = host
        os.environ["PULLDB_MYSQL_PASSWORD"] = password
        os.environ["PULLDB_MYSQL_DATABASE"] = "pulldb_service"  # Match test fixture database

        # Phase 1: Bootstrap
        bootstrap = Config.minimal_from_env()
        assert bootstrap.s3_bucket_path is None  # Not loaded yet
        assert bootstrap.default_dbhost is None  # Not loaded yet
        assert bootstrap.mysql_user == ""  # Not loaded from env

        # Phase 2: Full config - pass username directly
        pool = build_default_pool(
            host=bootstrap.mysql_host,
            user=username,  # Pass directly, not from config
            password=bootstrap.mysql_password,
            database=bootstrap.mysql_database,
        )

        # Phase 2: Load full config from MySQL (pool passed directly)
        full_config = Config.from_env_and_mysql(pool)

        # Now we have operational settings from MySQL
        assert full_config.s3_bucket_path is not None
        assert full_config.default_dbhost is not None
