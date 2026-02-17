"""MySQL connection pool and cursor infrastructure for pullDB.

Provides typed cursor wrappers, connection pooling, and factory functions
shared by all repository modules.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import mysql.connector
from mysql.connector.abstracts import MySQLConnectionAbstract
from mysql.connector.pooling import PooledMySQLConnection

logger = logging.getLogger(__name__)

# Type aliases for MySQL cursor results with dictionary=True
# These help Pylance understand the actual runtime types
DictRow = dict[str, Any]
TupleRow = tuple[Any, ...]


def _dict_row(row: Any) -> DictRow | None:
    """Cast fetchone() result to DictRow for cursors with dictionary=True.

    mysql-connector-python type stubs don't narrow the return type when
    dictionary=True is passed. This helper provides type safety for the
    actual runtime behavior.
    """
    return cast(DictRow | None, row)


def _dict_rows(rows: Any) -> list[DictRow]:
    """Cast fetchall() result to list[DictRow] for cursors with dictionary=True."""
    return cast(list[DictRow], rows)


class TypedDictCursor:
    """Wrapper around MySQL cursor with proper type annotations for dictionary mode.

    mysql-connector-python's type stubs use generic RowType/RowItemType that don't
    narrow when dictionary=True. This wrapper provides correctly typed fetchone()
    and fetchall() methods for dictionary cursors.

    Usage:
        with pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()  # Returns dict[str, Any] | None
            if row:
                username = row.get("username")  # Type-safe access
    """

    def __init__(self, cursor: Any) -> None:
        """Wrap a MySQL cursor created with dictionary=True."""
        self._cursor = cursor

    def execute(self, query: str, params: Any = None) -> None:
        """Execute a query with optional parameters."""
        if params is None:
            self._cursor.execute(query)
        else:
            self._cursor.execute(query, params)

    def executemany(self, query: str, params: list[Any]) -> None:
        """Execute a query with multiple parameter sets."""
        self._cursor.executemany(query, params)

    def fetchone(self) -> DictRow | None:
        """Fetch one row as a dictionary."""
        return cast(DictRow | None, self._cursor.fetchone())

    def fetchall(self) -> list[DictRow]:
        """Fetch all rows as dictionaries."""
        return cast(list[DictRow], self._cursor.fetchall())

    def fetchmany(self, size: int = 1) -> list[DictRow]:
        """Fetch many rows as dictionaries."""
        return cast(list[DictRow], self._cursor.fetchmany(size))

    @property
    def rowcount(self) -> int:
        """Number of rows affected by the last execute."""
        return cast(int, self._cursor.rowcount)

    @property
    def lastrowid(self) -> int | None:
        """Last auto-incremented ID."""
        return cast(int | None, self._cursor.lastrowid)

    def close(self) -> None:
        """Close the cursor."""
        self._cursor.close()

    def __enter__(self) -> "TypedDictCursor":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit - closes cursor."""
        self.close()


class TypedTupleCursor:
    """Wrapper around MySQL cursor with proper type annotations for tuple mode.

    For cursors created without dictionary=True, rows are tuples.
    This wrapper provides correctly typed fetchone() and fetchall() methods.
    Also exposes nextset() for multi-statement query support.
    """

    def __init__(self, cursor: Any) -> None:
        """Wrap a MySQL cursor (without dictionary=True)."""
        self._cursor = cursor

    def execute(self, query: str, params: Any = None) -> None:
        """Execute a query with optional parameters."""
        if params is None:
            self._cursor.execute(query)
        else:
            self._cursor.execute(query, params)

    def executemany(self, query: str, params: list[Any]) -> None:
        """Execute a query with multiple parameter sets."""
        self._cursor.executemany(query, params)

    def fetchone(self) -> TupleRow | None:
        """Fetch one row as a tuple."""
        return cast(TupleRow | None, self._cursor.fetchone())

    def fetchall(self) -> list[TupleRow]:
        """Fetch all rows as tuples."""
        return cast(list[TupleRow], self._cursor.fetchall())

    def fetchmany(self, size: int = 1) -> list[TupleRow]:
        """Fetch many rows as tuples."""
        return cast(list[TupleRow], self._cursor.fetchmany(size))

    @property
    def rowcount(self) -> int:
        """Number of rows affected by the last execute."""
        return cast(int, self._cursor.rowcount)

    @property
    def lastrowid(self) -> int | None:
        """Last auto-incremented ID."""
        return cast(int | None, self._cursor.lastrowid)

    def nextset(self) -> bool | None:
        """Move to next result set (for multi-statement queries)."""
        return cast(bool | None, self._cursor.nextset())

    def close(self) -> None:
        """Close the cursor."""
        self._cursor.close()

    def __enter__(self) -> "TypedTupleCursor":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit - closes cursor."""
        self.close()


class MySQLPool:
    """Very small wrapper around mysql.connector.connect for early prototype.

    Will be replaced with a real pooled implementation and per-host connections.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize MySQL connection pool.

        Args:
            **kwargs: Connection parameters passed to mysql.connector.connect().
        """
        self._kwargs = kwargs

    @contextmanager
    def connection(self) -> Iterator[PooledMySQLConnection | MySQLConnectionAbstract]:
        """Get a database connection from the pool.

        Yields:
            MySQL connection object with automatic cleanup.
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[PooledMySQLConnection | MySQLConnectionAbstract]:
        """Get a database connection with explicit transaction control.

        Disables autocommit for manual transaction management. Commits on
        successful exit, rolls back on exception. Used for atomic operations
        like job claiming in multi-worker environments.

        Yields:
            MySQL connection object with autocommit disabled.

        Example:
            >>> with pool.transaction() as conn:
            ...     cursor = TypedTupleCursor(conn.cursor())
            ...     cursor.execute("SELECT ... FOR UPDATE")
            ...     cursor.execute("UPDATE ...")
            ...     # Commits automatically on exit
        """
        conn = mysql.connector.connect(**self._kwargs)
        conn.autocommit = False  # type: ignore[union-attr]
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def dict_cursor(self) -> Iterator[TypedDictCursor]:
        """Get a typed dictionary cursor with automatic cleanup.

        This is the preferred way to query when you need to access columns by name.
        The cursor's fetchone() returns dict[str, Any] | None with proper typing.

        Yields:
            TypedDictCursor with properly typed fetch methods.

        Example:
            >>> with pool.dict_cursor() as cursor:
            ...     cursor.execute("SELECT id, name FROM users")
            ...     row = cursor.fetchone()
            ...     if row:
            ...         print(row.get("name"))  # Type-safe access
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            raw_cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor = TypedDictCursor(raw_cursor)
            try:
                yield cursor
            finally:
                cursor.close()
        finally:
            conn.close()

    @contextmanager
    def tuple_cursor(self) -> Iterator[TypedTupleCursor]:
        """Get a typed tuple cursor with automatic cleanup.

        This is for queries where positional access is acceptable.
        The cursor's fetchone() returns tuple[Any, ...] | None with proper typing.

        Yields:
            TypedTupleCursor with properly typed fetch methods.
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            raw_cursor = TypedTupleCursor(conn.cursor())
            cursor = TypedTupleCursor(raw_cursor)
            try:
                yield cursor
            finally:
                cursor.close()
        finally:
            conn.close()


def build_default_pool(
    host: str,
    user: str,
    password: str,
    database: str,
    unix_socket: str | None = None,
) -> MySQLPool:
    """Build a MySQL connection pool with default configuration.

    Args:
        host: MySQL server hostname.
        user: MySQL username.
        password: MySQL password.
        database: Database name.
        unix_socket: Optional Unix socket path (overrides host/port if provided).

    Returns:
        Configured MySQLPool instance.
    """
    kwargs: dict[str, Any] = {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
    }
    if unix_socket:
        kwargs["unix_socket"] = unix_socket
    return MySQLPool(**kwargs)
