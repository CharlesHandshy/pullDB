"""Tests for staging database lifecycle operations.

Tests validate:
- Staging name generation from target + job_id
- Target name length validation (51 char max)
- Job ID validation (hex format, 12+ chars)
- Orphaned staging database pattern matching
- Cleanup operation with connection simulation
- Post-cleanup uniqueness verification
"""

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from pulldb.domain.errors import StagingError

# Import private function for unit testing pattern matching logic
from pulldb.worker.staging import (
    StagingConnectionSpec,
    _find_orphaned_staging_databases,
    cleanup_orphaned_staging,
    generate_staging_name,
)


def test_generate_staging_name_success() -> None:
    """Test successful staging name generation."""
    job_id = str(uuid.uuid4())  # e.g., '550e8400-e29b-41d4-a716-446655440000'
    target_db = "jdoecustomer"

    staging_name = generate_staging_name(target_db, job_id)

    # Should be: target + underscore + first 12 hex chars of job_id
    assert staging_name.startswith(f"{target_db}_")
    assert len(staging_name) == len(target_db) + 13  # target + _ + 12 chars


def test_generate_staging_name_exact_12_char_job_id() -> None:
    """Test staging name generation with exact 12-char job ID."""
    job_id = "550e8400e29b"  # Exactly 12 hex chars (no dashes)
    target_db = "testdb"

    staging_name = generate_staging_name(target_db, job_id)

    assert staging_name == "testdb_550e8400e29b"


def test_generate_staging_name_target_too_long() -> None:
    """Test error when target database name exceeds 51 chars."""
    # Target must be <= 51 chars (64 - 13 suffix)
    target_db = "a" * 52
    job_id = str(uuid.uuid4())

    with pytest.raises(StagingError) as exc_info:
        generate_staging_name(target_db, job_id)

    assert "exceeds maximum of 51 chars" in str(exc_info.value)
    assert "MySQL's 64 char limit" in str(exc_info.value)


def test_generate_staging_name_job_id_too_short() -> None:
    """Test error when job_id is less than 12 characters."""
    target_db = "testdb"
    job_id = "550e8400e2"  # Only 10 chars

    with pytest.raises(StagingError) as exc_info:
        generate_staging_name(target_db, job_id)

    assert "too short" in str(exc_info.value)
    assert "need at least 12 characters" in str(exc_info.value)


def test_generate_staging_name_job_id_non_hex() -> None:
    """Test error when job_id contains non-hexadecimal characters."""
    target_db = "testdb"
    job_id = "550e8400g29b"  # Contains 'g' (not hex)

    with pytest.raises(StagingError) as exc_info:
        generate_staging_name(target_db, job_id)

    assert "non-hexadecimal characters" in str(exc_info.value)


def test_find_orphaned_staging_databases_none() -> None:
    """Test orphan detection when no staging databases exist."""
    target_db = "jdoecustomer"
    all_databases = [
        "information_schema",
        "mysql",
        "performance_schema",
        "jdoecustomer",  # Target exists, but not a staging DB
    ]

    orphans = _find_orphaned_staging_databases(target_db, all_databases)

    assert orphans == []


def test_find_orphaned_staging_databases_single() -> None:
    """Test orphan detection with one staging database."""
    target_db = "jdoecustomer"
    all_databases = [
        "information_schema",
        "jdoecustomer_550e8400e29b",  # Orphaned staging DB
        "jdoecustomer",  # Target
    ]

    orphans = _find_orphaned_staging_databases(target_db, all_databases)

    assert orphans == ["jdoecustomer_550e8400e29b"]


def test_find_orphaned_staging_databases_multiple() -> None:
    """Test orphan detection with multiple staging databases (sorted)."""
    target_db = "jdoecustomer"
    all_databases = [
        "jdoecustomer_9a8b7c6d5e4f",  # Orphan 2
        "information_schema",
        "jdoecustomer_550e8400e29b",  # Orphan 1
        "jdoecustomer",  # Target
        "jdoecustomer_abcdef123456",  # Orphan 3
    ]

    orphans = _find_orphaned_staging_databases(target_db, all_databases)

    # Should be sorted
    assert orphans == [
        "jdoecustomer_550e8400e29b",
        "jdoecustomer_9a8b7c6d5e4f",
        "jdoecustomer_abcdef123456",
    ]


def test_find_orphaned_staging_databases_wrong_pattern() -> None:
    """Test that databases not matching pattern are excluded."""
    target_db = "jdoecustomer"
    all_databases = [
        "jdoecustomer_staging",  # Wrong suffix (not 12 hex)
        "jdoecustomer_550e",  # Too short
        "jdoecustomer_550e8400e29b123",  # Too long
        "jdoecustomer_550E8400E29B",  # Uppercase (should match after lowercase)
        "jdoecustomer_550e8400g29b",  # Non-hex char
        "othercustomer_550e8400e29b",  # Different target
    ]

    orphans = _find_orphaned_staging_databases(target_db, all_databases)

    # None should match the exact pattern
    assert orphans == []


# Fake connection/cursor for testing without real MySQL
class _FakeCursor:
    """Simulated MySQL cursor for testing."""

    def __init__(self, all_databases: list[str], orphans_to_drop: list[str]) -> None:
        """Initialize fake cursor.

        Args:
            all_databases: Initial list of databases.
            orphans_to_drop: Orphans that should be dropped during test.
        """
        self._databases = list(all_databases)
        self._orphans_to_drop = orphans_to_drop

    def execute(self, sql: str) -> None:
        """Simulate SQL execution."""
        if sql == "SHOW DATABASES":
            return  # fetchall() will return _databases
        elif sql.startswith("DROP DATABASE"):
            # Extract database name from DROP statement
            # Format: DROP DATABASE IF EXISTS `dbname`
            db_name = sql.split("`")[1]  # Extract name between backticks
            if db_name in self._databases:
                self._databases.remove(db_name)

    def fetchall(self) -> list[tuple[str]]:
        """Return current list of databases as tuples."""
        return [(db,) for db in self._databases]

    def close(self) -> None:
        """Simulate cursor close."""
        pass


class _FakeConnection:
    """Simulated MySQL connection for testing."""

    def __init__(self, all_databases: list[str], orphans_to_drop: list[str]) -> None:
        """Initialize fake connection.

        Args:
            all_databases: Initial list of databases.
            orphans_to_drop: Orphans that should be dropped during test.
        """
        self._cursor = _FakeCursor(all_databases, orphans_to_drop)
        self.closed = False

    def cursor(self) -> _FakeCursor:
        """Return fake cursor."""
        return self._cursor

    def close(self) -> None:
        """Simulate connection close."""
        self.closed = True


def _connect_factory(
    all_databases: list[str],
    orphans_to_drop: list[str],
) -> Any:
    """Create typed helper function for monkeypatching mysql.connector.connect.

    Args:
        all_databases: Initial list of databases for SHOW DATABASES.
        orphans_to_drop: Orphans expected to be dropped.

    Returns:
        Function matching mysql.connector.connect signature.
    """

    def _connect(**kwargs: Any) -> _FakeConnection:
        return _FakeConnection(all_databases, orphans_to_drop)

    return _connect


def test_cleanup_orphaned_staging_no_orphans(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test cleanup when no orphaned staging databases exist."""
    target_db = "jdoecustomer"
    job_id = "550e8400e29b41d4a716446655440000"

    all_databases = ["information_schema", "mysql", "jdoecustomer"]

    # Monkeypatch mysql.connector.connect
    import mysql.connector

    monkeypatch.setattr(
        mysql.connector,
        "connect",
        _connect_factory(all_databases, []),
    )

    conn_spec = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="pulldb_worker",
        mysql_password="test_pass",
        timeout_seconds=30,
    )

    result = cleanup_orphaned_staging(conn_spec, target_db, job_id)

    assert result.staging_db == "jdoecustomer_550e8400e29b"
    assert result.target_db == "jdoecustomer"
    assert result.orphans_dropped == []


def test_cleanup_orphaned_staging_with_orphans(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test cleanup with multiple orphaned staging databases."""
    target_db = "jdoecustomer"
    job_id = "550e8400e29b41d4a716446655440000"

    orphans = [
        "jdoecustomer_9a8b7c6d5e4f",
        "jdoecustomer_abcdef123456",
    ]

    all_databases = [
        "information_schema",
        *orphans,
        "jdoecustomer",
    ]

    # Monkeypatch mysql.connector.connect
    import mysql.connector

    monkeypatch.setattr(
        mysql.connector,
        "connect",
        _connect_factory(all_databases, orphans),
    )

    conn_spec = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="pulldb_worker",
        mysql_password="test_pass",
        timeout_seconds=30,
    )

    result = cleanup_orphaned_staging(conn_spec, target_db, job_id)

    assert result.staging_db == "jdoecustomer_550e8400e29b"
    assert result.target_db == "jdoecustomer"
    assert result.orphans_dropped == sorted(orphans)


def test_cleanup_orphaned_staging_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup when MySQL connection fails."""
    import mysql.connector

    def _connect_fail(**kwargs: Any) -> MagicMock:
        raise mysql.connector.Error("Connection refused")

    monkeypatch.setattr(mysql.connector, "connect", _connect_fail)

    conn_spec = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="pulldb_worker",
        mysql_password="test_pass",
        timeout_seconds=30,
    )

    with pytest.raises(StagingError) as exc_info:
        cleanup_orphaned_staging(conn_spec, "testdb", str(uuid.uuid4()))

    assert "Failed to connect to MySQL server" in str(exc_info.value)
    assert "Verify credentials and network connectivity" in str(exc_info.value)


def test_cleanup_orphaned_staging_show_databases_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup when SHOW DATABASES query fails."""

    class _FailingCursor:
        """Cursor that fails on SHOW DATABASES."""

        def execute(self, sql: str) -> None:
            if sql == "SHOW DATABASES":
                import mysql.connector

                raise mysql.connector.Error("Access denied for user")

        def close(self) -> None:
            pass

    class _FailingConnection:
        """Connection that returns failing cursor."""

        def cursor(self) -> _FailingCursor:
            return _FailingCursor()

        def close(self) -> None:
            pass

    def _connect_failing(**kwargs: Any) -> _FailingConnection:
        return _FailingConnection()

    import mysql.connector

    monkeypatch.setattr(mysql.connector, "connect", _connect_failing)

    conn_spec = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="pulldb_worker",
        mysql_password="test_pass",
        timeout_seconds=30,
    )

    with pytest.raises(StagingError) as exc_info:
        cleanup_orphaned_staging(conn_spec, "testdb", str(uuid.uuid4()))

    assert "Failed to list databases" in str(exc_info.value)
    assert "SHOW DATABASES privilege" in str(exc_info.value)


def test_cleanup_orphaned_staging_staging_exists_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test error when staging database exists but DROP silently failed."""
    target_db = "jdoecustomer"
    job_id = "550e8400e29b41d4a716446655440000"

    # Staging DB name that will be generated
    staging_db_name = "jdoecustomer_550e8400e29b"

    # Initial state: staging database exists as orphan
    all_databases_initial = [
        "information_schema",
        staging_db_name,  # This IS an orphan and should be dropped
    ]

    class _FailingDropCursor:
        """Cursor that doesn't actually drop the database (simulates DROP failure)."""

        def __init__(self) -> None:
            self._databases = list(all_databases_initial)

        def execute(self, sql: str) -> None:
            """Simulate SQL but don't actually drop database."""
            if sql == "SHOW DATABASES":
                return  # fetchall() will return current databases
            elif sql.startswith("DROP DATABASE"):
                # Silently ignore drop (simulates MySQL bug or permission issue)
                pass

        def fetchall(self) -> list[tuple[str]]:
            """Return current list of databases."""
            return [(db,) for db in self._databases]

        def close(self) -> None:
            pass

    class _FailingConnection:
        """Connection with cursor that doesn't drop databases."""

        def __init__(self) -> None:
            self._cursor = _FailingDropCursor()

        def cursor(self) -> _FailingDropCursor:
            return self._cursor

        def close(self) -> None:
            pass

    def _connect_failing(**kwargs: Any) -> _FailingConnection:
        return _FailingConnection()

    import mysql.connector

    monkeypatch.setattr(mysql.connector, "connect", _connect_failing)

    conn_spec = StagingConnectionSpec(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="pulldb_worker",
        mysql_password="test_pass",
        timeout_seconds=30,
    )

    with pytest.raises(StagingError) as exc_info:
        cleanup_orphaned_staging(conn_spec, target_db, job_id)

    assert "still exists after cleanup" in str(exc_info.value)
    assert "concurrency issue" in str(exc_info.value)
