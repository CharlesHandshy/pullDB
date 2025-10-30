"""MySQL infrastructure placeholder.

Implements connection acquisition. Repository layer will be added in Milestone 2.
"""
from __future__ import annotations

from contextlib import contextmanager
import typing as t
import mysql.connector


class MySQLPool:
    """Very small wrapper around mysql.connector.connect for early prototype.

    Will be replaced with a real pooled implementation and per-host connections.
    """

    def __init__(self, **kwargs: t.Any) -> None:
        self._kwargs = kwargs

    @contextmanager
    def connection(self) -> t.Iterator[mysql.connector.MySQLConnection]:
        conn = mysql.connector.connect(**self._kwargs)
        try:
            yield conn
        finally:
            conn.close()


def build_default_pool(host: str, user: str, password: str, database: str) -> MySQLPool:
    return MySQLPool(host=host, user=user, password=password, database=database)
