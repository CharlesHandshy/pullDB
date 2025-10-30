"""MySQL infrastructure placeholder.

Implements connection acquisition. Repository layer will be added in Milestone 2.
"""

from __future__ import annotations

import typing as t
from contextlib import contextmanager

import mysql.connector


class MySQLPool:
    """Very small wrapper around mysql.connector.connect for early prototype.

    Will be replaced with a real pooled implementation and per-host connections.
    """

    def __init__(self, **kwargs: t.Any) -> None:
        """Initialize MySQL connection pool.

        Args:
            **kwargs: Connection parameters passed to mysql.connector.connect().
        """
        self._kwargs = kwargs

    @contextmanager
    def connection(self) -> t.Iterator[t.Any]:
        """Get a database connection from the pool.

        Yields:
            MySQL connection object.
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            yield conn
        finally:
            conn.close()


def build_default_pool(host: str, user: str, password: str, database: str) -> MySQLPool:
    """Build a MySQL connection pool with default configuration.

    Args:
        host: MySQL server hostname.
        user: MySQL username.
        password: MySQL password.
        database: Database name.

    Returns:
        Configured MySQLPool instance.
    """
    return MySQLPool(host=host, user=user, password=password, database=database)
