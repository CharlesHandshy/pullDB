"""Root conftest for the tests/ unit test tree.

HCA Layer: tests (shared test infrastructure)

This conftest is intentionally minimal — it provides only infrastructure-free
fixtures that are safe to use in all unit tests without any I/O, AWS, or MySQL.
All fixtures here must be:
  - Fast (< 1ms setup time)
  - No network, no disk, no DB calls
  - Composable with more specific fixtures in sub-conftest files

Integration / QA fixtures live in tests/qa/conftest.py.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Common mock infrastructure
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mysql_conn() -> MagicMock:
    """A MagicMock standing in for a MySQL connection/cursor pair.

    Returns a mock connection whose .cursor(dictionary=True) returns a mock
    cursor with .execute(), .fetchall(), .fetchone(), and .close() wired up.
    """
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    cursor.description = []

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.is_connected.return_value = True
    return conn


@pytest.fixture
def mock_s3_client() -> MagicMock:
    """A MagicMock standing in for a boto3 S3 client.

    Pre-configured with sensible empty defaults for common S3 operations.
    """
    client = MagicMock()
    client.list_objects_v2.return_value = {"Contents": [], "IsTruncated": False}
    client.head_object.return_value = {"ContentLength": 0}
    client.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=b"")),
        "ContentLength": 0,
    }
    return client


@pytest.fixture
def mock_secrets_client() -> MagicMock:
    """A MagicMock standing in for a boto3 SecretsManager client."""
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": (
            '{"username": "pulldb_app", "password": "testpassword",'
            ' "host": "localhost", "port": 3306}'
        )
    }
    return client


@pytest.fixture
def mock_mysql_pool() -> MagicMock:
    """A MagicMock standing in for a MySQLPool.

    The pool's context managers yield the mock_mysql_conn cursor.
    Suitable for injecting into repository constructors.
    """
    pool = MagicMock()

    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    cursor.description = []

    # Make context managers work: `with pool.dict_cursor() as c:`
    pool.dict_cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    pool.dict_cursor.return_value.__exit__ = MagicMock(return_value=False)
    pool.tuple_cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    pool.tuple_cursor.return_value.__exit__ = MagicMock(return_value=False)
    pool.connection.return_value.__enter__ = MagicMock(return_value=MagicMock())
    pool.connection.return_value.__exit__ = MagicMock(return_value=False)
    pool.transaction.return_value.__enter__ = MagicMock(return_value=MagicMock())
    pool.transaction.return_value.__exit__ = MagicMock(return_value=False)

    return pool
