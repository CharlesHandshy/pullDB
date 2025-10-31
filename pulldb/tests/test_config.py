"""Tests for Config dataclass and configuration loading.

Tests both minimal_from_env (environment only) and from_env_and_mysql
(environment + MySQL settings table).
"""

import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pulldb.domain.config import Config


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


class TestMinimalFromEnv:
    """Test Config.minimal_from_env() - environment variable loading only."""

    def test_minimal_with_defaults(self) -> None:
        """Test minimal config with default values."""
        config = Config.minimal_from_env()

        assert config.mysql_host == "localhost"
        assert config.mysql_user == "root"
        assert config.mysql_password == ""
        assert config.mysql_database == "pulldb"
        assert config.s3_bucket_path is None
        assert config.aws_profile is None
        assert config.default_dbhost is None

    def test_minimal_with_explicit_values(self) -> None:
        """Test minimal config with explicit environment variables."""
        os.environ["PULLDB_MYSQL_HOST"] = "db.example.com"
        os.environ["PULLDB_MYSQL_USER"] = "pulldb_user"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "secret123"
        os.environ["PULLDB_MYSQL_DATABASE"] = "pulldb_prod"
        os.environ["PULLDB_S3_BUCKET_PATH"] = "s3://my-bucket/backups/"
        os.environ["PULLDB_AWS_PROFILE"] = "production"
        os.environ["PULLDB_DEFAULT_DBHOST"] = "db-prod-01"

        config = Config.minimal_from_env()

        assert config.mysql_host == "db.example.com"
        assert config.mysql_user == "pulldb_user"
        assert config.mysql_password == "secret123"
        assert config.mysql_database == "pulldb_prod"
        assert config.s3_bucket_path == "s3://my-bucket/backups/"
        assert config.aws_profile == "production"
        assert config.default_dbhost == "db-prod-01"


class TestFromEnvAndMySQL:
    """Test Config.from_env_and_mysql() - environment + MySQL settings."""

    def test_load_with_mysql_overrides(self) -> None:
        """Test config loading with MySQL settings overrides."""
        # Set up environment
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        # Mock MySQL connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Simulate settings table query results
        mock_cursor.fetchall.return_value = [
            {
                "setting_key": "default_dbhost",
                "setting_value": "db-mysql-db4-dev.example.com",
            },
            {"setting_key": "s3_bucket_stg", "setting_value": "pestroutesrdsdbs"},
            {"setting_key": "s3_prefix_stg", "setting_value": "daily/stg"},
            {"setting_key": "work_directory", "setting_value": "/var/lib/pulldb"},
            {
                "setting_key": "customers_after_sql_dir",
                "setting_value": "/opt/pulldb/customers_after_sql",
            },
        ]

        # Load config
        config = Config.from_env_and_mysql(mock_conn)

        # Verify MySQL credentials came from environment
        assert config.mysql_host == "localhost"
        assert config.mysql_user == "root"
        assert config.mysql_password == "testpass"
        assert config.mysql_database == "pulldb"

        # Verify operational settings came from MySQL
        assert config.s3_bucket_path == "pestroutesrdsdbs"
        assert config.default_dbhost == "db-mysql-db4-dev.example.com"
        assert config.work_dir == Path("/var/lib/pulldb")
        assert config.customers_after_sql_dir == Path("/opt/pulldb/customers_after_sql")

        # Verify cursor was used correctly
        mock_conn.cursor.assert_called_once_with(dictionary=True)
        mock_cursor.execute.assert_called_once_with(
            "SELECT setting_key, setting_value FROM settings"
        )
        mock_cursor.close.assert_called_once()

    def test_environment_takes_precedence_over_mysql(self) -> None:
        """Test that environment variables override MySQL settings."""
        # Set up environment with explicit values
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"
        os.environ["PULLDB_S3_BUCKET_PATH"] = "s3://env-bucket/"
        os.environ["PULLDB_DEFAULT_DBHOST"] = "env-dbhost"
        os.environ["PULLDB_WORK_DIR"] = "/tmp/env-work"

        # Mock MySQL connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # MySQL settings (should be overridden by environment)
        mock_cursor.fetchall.return_value = [
            {"setting_key": "s3_bucket_stg", "setting_value": "mysql-bucket"},
            {"setting_key": "default_dbhost", "setting_value": "mysql-dbhost"},
            {"setting_key": "work_directory", "setting_value": "/var/mysql-work"},
        ]

        config = Config.from_env_and_mysql(mock_conn)

        # Environment should win
        assert config.s3_bucket_path == "s3://env-bucket/"
        assert config.default_dbhost == "env-dbhost"
        assert config.work_dir == Path("/tmp/env-work")

    def test_mysql_settings_fallback_to_defaults(self) -> None:
        """Test that defaults are used when neither env nor MySQL provide values."""
        # Minimal environment (just credentials)
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        # Mock MySQL connection with empty settings
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        config = Config.from_env_and_mysql(mock_conn)

        # Should use hardcoded defaults
        assert config.work_dir == Path("/tmp/pulldb-work")
        assert config.customers_after_sql_dir == Path("customers_after_sql")
        assert config.qa_template_after_sql_dir == Path("qa_template_after_sql")

    def test_prefers_staging_bucket_over_prod(self) -> None:
        """Test that s3_bucket_stg is preferred over s3_bucket_prod."""
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Both staging and production buckets present
        mock_cursor.fetchall.return_value = [
            {"setting_key": "s3_bucket_stg", "setting_value": "staging-bucket"},
            {"setting_key": "s3_bucket_prod", "setting_value": "prod-bucket"},
        ]

        config = Config.from_env_and_mysql(mock_conn)

        # Should prefer staging
        assert config.s3_bucket_path == "staging-bucket"

    def test_falls_back_to_prod_bucket_if_no_staging(self) -> None:
        """Test fallback to production bucket when staging not available."""
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Only production bucket present
        mock_cursor.fetchall.return_value = [
            {"setting_key": "s3_bucket_prod", "setting_value": "prod-bucket"},
        ]

        config = Config.from_env_and_mysql(mock_conn)

        # Should use production
        assert config.s3_bucket_path == "prod-bucket"
