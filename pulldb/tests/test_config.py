"""Tests for Config dataclass and configuration loading.

Tests both minimal_from_env (environment only) and from_env_and_mysql
(environment + MySQL settings table).
"""

import json
import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pulldb.domain.config import Config, _parse_s3_backup_locations


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
        assert config.s3_aws_profile is None
        assert config.default_dbhost is None
        assert config.myloader_binary == "myloader"
        assert config.myloader_extra_args == ()
        assert config.myloader_timeout_seconds == 7200.0
        assert config.myloader_threads == 8

    def test_minimal_with_explicit_values(self) -> None:
        """Test minimal config with explicit environment variables."""
        os.environ["PULLDB_MYSQL_HOST"] = "db.example.com"
        os.environ["PULLDB_MYSQL_USER"] = "pulldb_user"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "secret123"
        os.environ["PULLDB_MYSQL_DATABASE"] = "pulldb_prod"
        os.environ["PULLDB_S3_BUCKET_PATH"] = "s3://my-bucket/backups/"
        os.environ["PULLDB_AWS_PROFILE"] = "production"
        os.environ["PULLDB_S3_AWS_PROFILE"] = "staging-reader"
        os.environ["PULLDB_DEFAULT_DBHOST"] = "db-prod-01"
        os.environ["PULLDB_MYLOADER_BINARY"] = "/opt/bin/myloader-custom"
        os.environ["PULLDB_MYLOADER_EXTRA_ARGS"] = (
            "--rows-per-insert=1000 --skip-triggers"
        )
        os.environ["PULLDB_MYLOADER_TIMEOUT_SECONDS"] = "3600.5"
        os.environ["PULLDB_MYLOADER_THREADS"] = "16"

        config = Config.minimal_from_env()

        assert config.mysql_host == "db.example.com"
        assert config.mysql_user == "pulldb_user"
        assert config.mysql_password == "secret123"
        assert config.mysql_database == "pulldb_prod"
        assert config.s3_bucket_path == "s3://my-bucket/backups/"
        assert config.aws_profile == "production"
        assert config.s3_aws_profile == "staging-reader"
        assert config.default_dbhost == "db-prod-01"
        assert config.myloader_binary == "/opt/bin/myloader-custom"
        assert config.myloader_extra_args == (
            "--rows-per-insert=1000",
            "--skip-triggers",
        )
        assert config.myloader_timeout_seconds == pytest.approx(3600.5)
        assert config.myloader_threads == 16

    def test_invalid_threads_env_raises(self) -> None:
        os.environ["PULLDB_MYLOADER_THREADS"] = "-1"
        with pytest.raises(ValueError):
            Config.minimal_from_env()

    def test_s3_profile_defaults_to_aws_profile(self) -> None:
        os.environ["PULLDB_AWS_PROFILE"] = "dev"
        config = Config.minimal_from_env()
        assert config.s3_aws_profile == "dev"


class TestFromEnvAndMySQL:
    """Test Config.from_env_and_mysql() using mocked MySQLPool abstraction."""

    def _build_pool_with_settings(self, settings: list[dict[str, str]]) -> MagicMock:
        """Helper to build a mock MySQLPool returning provided settings rows."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_pool.connection.return_value.__exit__.return_value = False
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = settings
        return mock_pool

    def test_load_with_mysql_overrides(self) -> None:
        """MySQL settings populate missing operational configuration fields."""
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        settings_rows = [
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
            {
                "setting_key": "myloader_binary",
                "setting_value": "/usr/local/bin/myloader",
            },
            {
                "setting_key": "myloader_extra_args",
                "setting_value": "--skip-triggers --rows-per-insert=500",
            },
            {
                "setting_key": "myloader_timeout_seconds",
                "setting_value": "1800",
            },
            {
                "setting_key": "myloader_threads",
                "setting_value": "12",
            },
        ]
        mock_pool = self._build_pool_with_settings(settings_rows)

        config = Config.from_env_and_mysql(mock_pool)

        assert config.mysql_host == "localhost"
        assert config.mysql_user == "root"
        assert config.mysql_password == "testpass"
        assert config.mysql_database == "pulldb"
        assert config.s3_bucket_path == "pestroutesrdsdbs"
        assert config.default_dbhost == "db-mysql-db4-dev.example.com"
        assert config.work_dir == Path("/var/lib/pulldb")
        assert config.customers_after_sql_dir == Path("/opt/pulldb/customers_after_sql")
        assert config.myloader_binary == "/usr/local/bin/myloader"
        assert config.myloader_extra_args == (
            "--skip-triggers",
            "--rows-per-insert=500",
        )
        assert config.myloader_timeout_seconds == 1800.0
        assert config.myloader_threads == 12

    def test_environment_takes_precedence_over_mysql(self) -> None:
        """Environment variables override MySQL settings rows."""
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"
        os.environ["PULLDB_S3_BUCKET_PATH"] = "s3://env-bucket/"
        os.environ["PULLDB_DEFAULT_DBHOST"] = "env-dbhost"
        os.environ["PULLDB_WORK_DIR"] = "/tmp/env-work"
        os.environ["PULLDB_MYLOADER_BINARY"] = "env-loader"
        os.environ["PULLDB_MYLOADER_EXTRA_ARGS"] = "--foo"
        os.environ["PULLDB_MYLOADER_TIMEOUT_SECONDS"] = "99"
        os.environ["PULLDB_MYLOADER_THREADS"] = "2"

        settings_rows = [
            {"setting_key": "s3_bucket_stg", "setting_value": "mysql-bucket"},
            {"setting_key": "default_dbhost", "setting_value": "mysql-dbhost"},
            {"setting_key": "work_directory", "setting_value": "/var/mysql-work"},
            {
                "setting_key": "myloader_binary",
                "setting_value": "/usr/bin/mysql-myloader",
            },
            {
                "setting_key": "myloader_extra_args",
                "setting_value": "--bar",
            },
        ]
        mock_pool = self._build_pool_with_settings(settings_rows)

        config = Config.from_env_and_mysql(mock_pool)

        assert config.s3_bucket_path == "s3://env-bucket/"
        assert config.default_dbhost == "env-dbhost"
        assert config.work_dir == Path("/tmp/env-work")
        assert config.myloader_binary == "env-loader"
        assert config.myloader_extra_args == ("--foo",)
        assert config.myloader_timeout_seconds == 99.0
        assert config.myloader_threads == 2

    def test_mysql_settings_fallback_to_defaults(self) -> None:
        """Defaults used when neither environment nor MySQL provide values."""
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        mock_pool = self._build_pool_with_settings([])
        config = Config.from_env_and_mysql(mock_pool)

        assert config.work_dir == Path("/tmp/pulldb-work")
        assert config.customers_after_sql_dir == Path("customers_after_sql")
        assert config.qa_template_after_sql_dir == Path("qa_template_after_sql")

    def test_prefers_staging_bucket_over_prod(self) -> None:
        """Staging bucket preferred when both staging and prod provided."""
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        settings_rows = [
            {"setting_key": "s3_bucket_stg", "setting_value": "staging-bucket"},
            {"setting_key": "s3_bucket_prod", "setting_value": "prod-bucket"},
        ]
        mock_pool = self._build_pool_with_settings(settings_rows)
        config = Config.from_env_and_mysql(mock_pool)
        assert config.s3_bucket_path == "staging-bucket"

    def test_falls_back_to_prod_bucket_if_no_staging(self) -> None:
        """Production bucket used when staging bucket absent."""
        os.environ["PULLDB_MYSQL_HOST"] = "localhost"
        os.environ["PULLDB_MYSQL_USER"] = "root"
        os.environ["PULLDB_MYSQL_PASSWORD"] = "testpass"

        settings_rows = [
            {"setting_key": "s3_bucket_prod", "setting_value": "prod-bucket"},
        ]
        mock_pool = self._build_pool_with_settings(settings_rows)
        config = Config.from_env_and_mysql(mock_pool)
        assert config.s3_bucket_path == "prod-bucket"


class TestS3BackupLocationParsing:
    def test_parse_locations_with_aliases(self) -> None:
        payload = json.dumps(
            [
                {
                    "name": "prod",
                    "bucket_path": "s3://backups/daily/prod",
                    "format": "prod-legacy",
                    "target_aliases": {
                        "qatemplate": [
                            "qatemplate",
                            "qatemplate_legacy",
                        ]
                    },
                }
            ]
        )

        locations = _parse_s3_backup_locations(payload)

        assert len(locations) == 1
        loc = locations[0]
        assert loc.name == "prod"
        assert loc.bucket == "backups"
        assert loc.prefix == "daily/prod/"
        assert loc.format_tag == "prod-legacy"
        assert loc.aliases_for_target("qatemplate") == (
            "qatemplate",
            "qatemplate_legacy",
        )
        assert loc.aliases_for_target("unknown") == ()
