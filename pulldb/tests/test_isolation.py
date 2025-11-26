"""Smoke test for Native Ephemeral Isolation strategy.

Verifies that the isolated_mysql fixture correctly sets up a private,
socket-based MySQL instance and that the application can connect to it.
"""

import os
import subprocess
import time

import pytest

from pulldb.infra.mysql import MySQLPool


@pytest.mark.integration
def test_isolation_environment(isolated_mysql: str) -> None:
    """Verify environment variables are set correctly."""
    assert os.getenv("PULLDB_TEST_MYSQL_SOCKET") == isolated_mysql
    assert os.getenv("PULLDB_TEST_MYSQL_HOST") == "localhost"
    assert os.getenv("PULLDB_TEST_MYSQL_USER") == "root"
    assert os.getenv("PULLDB_TEST_MYSQL_DATABASE") == "pulldb"


@pytest.mark.integration
def test_database_connection(isolated_mysql: str, isolated_mysql_pool: MySQLPool) -> None:
    """Verify we can connect to the isolated database."""
    with isolated_mysql_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        assert result[0] == 1


@pytest.mark.integration
def test_schema_deployed(isolated_mysql: str, isolated_mysql_pool: MySQLPool) -> None:
    """Verify schema was deployed to the isolated database."""
    with isolated_mysql_pool.connection() as conn:
        cursor = conn.cursor()
        # Check for jobs table
        cursor.execute("SHOW TABLES LIKE 'jobs'")
        assert cursor.fetchone() is not None

        # Check for settings table
        cursor.execute("SHOW TABLES LIKE 'settings'")
        assert cursor.fetchone() is not None


@pytest.mark.integration
def test_data_persistence(isolated_mysql: str, isolated_mysql_pool: MySQLPool) -> None:
    """Verify we can write and read data."""
    with isolated_mysql_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "REPLACE INTO settings (setting_key, setting_value) VALUES (%s, %s)",
            ("test_key", "test_value"),
        )
        conn.commit()

        cursor.execute(
            "SELECT setting_value FROM settings WHERE setting_key = %s", ("test_key",)
        )
        result = cursor.fetchone()
        assert result is not None
        assert result[0] == "test_value"


@pytest.mark.integration
def test_worker_startup(isolated_worker: subprocess.Popen[bytes]) -> None:
    """Verify the worker process starts and stays running."""
    # It should be running
    assert isolated_worker.poll() is None

    # Let it run for a bit
    time.sleep(2)
    assert isolated_worker.poll() is None
