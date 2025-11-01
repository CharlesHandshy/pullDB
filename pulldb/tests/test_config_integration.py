"""Integration tests for Config with real MySQL database.

These tests connect to the actual pulldb database to verify
from_env_and_mysql() works with real MySQL settings table.

Uses AWS Secrets Manager to resolve MySQL credentials for network login.
"""

import os
from collections.abc import Generator

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
        self, mysql_network_credentials: tuple[str, str, str]
    ) -> None:
        """Test loading config from actual pulldb database.

        Uses localhost network login with credentials from AWS Secrets Manager.
        Verifies MySQL settings table is read correctly.
        """
        host, username, password = mysql_network_credentials

        # Set up minimal environment (credentials from AWS Secrets Manager)
        os.environ["PULLDB_MYSQL_HOST"] = host
        os.environ["PULLDB_MYSQL_USER"] = username
        os.environ["PULLDB_MYSQL_PASSWORD"] = password

        # Bootstrap: Load minimal config
        bootstrap_config = Config.minimal_from_env()

        # Connect to MySQL
        pool = build_default_pool(
            host=bootstrap_config.mysql_host,
            user=bootstrap_config.mysql_user,
            password=bootstrap_config.mysql_password,
            database=bootstrap_config.mysql_database,
        )
        # Load full config with MySQL settings (pool passed directly)
        config = Config.from_env_and_mysql(pool)

        # Verify MySQL credentials came from environment
        assert config.mysql_host == host
        assert config.mysql_user == username
        assert config.mysql_password == password

        # Verify operational settings came from MySQL settings table
        # (these were populated by scripts/setup-pulldb-schema.sh)
        assert config.s3_bucket_path == "pestroutesrdsdbs"  # s3_bucket_stg
        assert config.default_dbhost is not None
        assert "db-mysql-db4-dev" in config.default_dbhost

    def test_environment_override_with_real_database(
        self, mysql_network_credentials: tuple[str, str, str]
    ) -> None:
        """Test that environment variables override MySQL settings."""
        host, username, password = mysql_network_credentials

        # Set environment variables that should override MySQL
        os.environ["PULLDB_MYSQL_HOST"] = host
        os.environ["PULLDB_MYSQL_USER"] = username
        os.environ["PULLDB_MYSQL_PASSWORD"] = password
        os.environ["PULLDB_S3_BUCKET_PATH"] = "s3://override-bucket/"
        os.environ["PULLDB_DEFAULT_DBHOST"] = "override-dbhost"

        bootstrap_config = Config.minimal_from_env()
        pool = build_default_pool(
            host=bootstrap_config.mysql_host,
            user=bootstrap_config.mysql_user,
            password=bootstrap_config.mysql_password,
            database=bootstrap_config.mysql_database,
        )
        # Pool passed directly to from_env_and_mysql()
        config = Config.from_env_and_mysql(pool)

        # Environment should take precedence
        assert config.s3_bucket_path == "s3://override-bucket/"
        assert config.default_dbhost == "override-dbhost"

    def test_two_phase_loading_pattern(
        self, mysql_network_credentials: tuple[str, str, str]
    ) -> None:
        """Test the recommended two-phase loading pattern.

        Phase 1: minimal_from_env() for bootstrap credentials
        Phase 2: from_env_and_mysql() for full configuration
        """
        host, username, password = mysql_network_credentials

        os.environ["PULLDB_MYSQL_HOST"] = host
        os.environ["PULLDB_MYSQL_USER"] = username
        os.environ["PULLDB_MYSQL_PASSWORD"] = password

        # Phase 1: Bootstrap
        bootstrap = Config.minimal_from_env()
        assert bootstrap.s3_bucket_path is None  # Not loaded yet
        assert bootstrap.default_dbhost is None  # Not loaded yet

        # Phase 2: Full config
        pool = build_default_pool(
            host=bootstrap.mysql_host,
            user=bootstrap.mysql_user,
            password=bootstrap.mysql_password,
            database=bootstrap.mysql_database,
        )

        # Phase 2: Load full config from MySQL (pool passed directly)
        full_config = Config.from_env_and_mysql(pool)

        # Now we have operational settings from MySQL
        assert full_config.s3_bucket_path is not None
        assert full_config.default_dbhost is not None
