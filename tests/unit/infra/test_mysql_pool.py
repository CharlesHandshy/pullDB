"""Unit tests for pulldb.infra.mysql_pool.MySQLPool.

Verifies:
- Pool is initialised via MySQLConnectionPool, not mysql.connector.connect
- double-wrap bug is absent: dict_cursor/tuple_cursor wrap once only
- connection/transaction/dict_cursor/tuple_cursor return correct types
- transaction commits on success, rolls back on exception
- PULLDB_MYSQL_POOL_SIZE env var is respected
- pool_size constructor arg overrides env var

HCA Layer: features (tests)
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from pulldb.infra.mysql_pool import MySQLPool, TypedDictCursor, TypedTupleCursor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool(pool_size: int = 5, **extra: Any) -> tuple[MySQLPool, MagicMock]:
    """Return (pool, mock_connector_pool) with MySQLConnectionPool patched."""
    mock_connector_pool = MagicMock()
    with patch(
        "pulldb.infra.mysql_pool.MySQLConnectionPool",
        return_value=mock_connector_pool,
    ) as mock_cls:
        pool = MySQLPool(pool_name="test_pool", pool_size=pool_size, **extra)
    return pool, mock_connector_pool


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestMySQLPoolInit:
    def test_creates_connector_pool_not_direct_connect(self) -> None:
        """MySQLPool must use MySQLConnectionPool, not mysql.connector.connect."""
        with patch("pulldb.infra.mysql_pool.MySQLConnectionPool") as mock_cls:
            mock_cls.return_value = MagicMock()
            MySQLPool(pool_name="p", pool_size=3, host="h", user="u", password="pw", database="db")
        mock_cls.assert_called_once_with(
            pool_name="p", pool_size=3, host="h", user="u", password="pw", database="db"
        )

    def test_default_pool_size_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_MYSQL_POOL_SIZE", "7")
        with patch("pulldb.infra.mysql_pool.MySQLConnectionPool") as mock_cls:
            mock_cls.return_value = MagicMock()
            MySQLPool(pool_name="p", host="h", user="u", password="pw", database="db")
        _, kwargs = mock_cls.call_args
        assert mock_cls.call_args[1]["pool_size"] == 7 or mock_cls.call_args[0][1] == 7 or \
               mock_cls.call_args.kwargs.get("pool_size") == 7

    def test_explicit_pool_size_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PULLDB_MYSQL_POOL_SIZE", "99")
        with patch("pulldb.infra.mysql_pool.MySQLConnectionPool") as mock_cls:
            mock_cls.return_value = MagicMock()
            MySQLPool(pool_name="p", pool_size=2, host="h", user="u", password="pw", database="db")
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["pool_size"] == 2

    def test_fallback_pool_size_is_5(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PULLDB_MYSQL_POOL_SIZE", raising=False)
        with patch("pulldb.infra.mysql_pool.MySQLConnectionPool") as mock_cls:
            mock_cls.return_value = MagicMock()
            MySQLPool(pool_name="p", host="h", user="u", password="pw", database="db")
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["pool_size"] == 5


# ---------------------------------------------------------------------------
# connection() context manager
# ---------------------------------------------------------------------------

class TestConnectionContextManager:
    def test_yields_connection_from_pool(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pool.connection() as conn:
            assert conn is mock_conn
        mock_connector_pool.get_connection.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_connection_closed_on_exception(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pytest.raises(RuntimeError):
            with pool.connection():
                raise RuntimeError("boom")
        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# transaction() context manager
# ---------------------------------------------------------------------------

class TestTransactionContextManager:
    def test_commits_on_success(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pool.transaction():
            pass
        mock_conn.commit.assert_called_once()
        mock_conn.rollback.assert_not_called()
        mock_conn.close.assert_called_once()

    def test_rolls_back_on_exception(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pytest.raises(ValueError):
            with pool.transaction():
                raise ValueError("fail")
        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()
        mock_conn.close.assert_called_once()

    def test_autocommit_disabled(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pool.transaction():
            assert mock_conn.autocommit is False


# ---------------------------------------------------------------------------
# dict_cursor() — no double-wrap
# ---------------------------------------------------------------------------

class TestDictCursor:
    def test_yields_typed_dict_cursor(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        with pool.dict_cursor() as cursor:
            assert isinstance(cursor, TypedDictCursor)

    def test_no_double_wrap(self) -> None:
        """Inner cursor must be the raw mysql cursor, NOT a TypedDictCursor."""
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_raw = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_raw

        with pool.dict_cursor() as cursor:
            # cursor._cursor should be the raw mysql cursor, not another TypedDictCursor
            assert not isinstance(cursor._cursor, TypedDictCursor), (
                "double-wrap bug: TypedDictCursor wraps TypedDictCursor"
            )
            assert cursor._cursor is mock_raw

    def test_connection_closed_after_use(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pool.dict_cursor():
            pass
        mock_conn.close.assert_called_once()

    def test_cursor_created_with_dictionary_true(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pool.dict_cursor():
            pass
        mock_conn.cursor.assert_called_once_with(dictionary=True)


# ---------------------------------------------------------------------------
# tuple_cursor() — no double-wrap
# ---------------------------------------------------------------------------

class TestTupleCursor:
    def test_yields_typed_tuple_cursor(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        with pool.tuple_cursor() as cursor:
            assert isinstance(cursor, TypedTupleCursor)

    def test_no_double_wrap(self) -> None:
        """Inner cursor must be the raw mysql cursor, NOT a TypedTupleCursor."""
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_raw = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_raw

        with pool.tuple_cursor() as cursor:
            assert not isinstance(cursor._cursor, TypedTupleCursor), (
                "double-wrap bug: TypedTupleCursor wraps TypedTupleCursor"
            )
            assert cursor._cursor is mock_raw

    def test_connection_closed_after_use(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pool.tuple_cursor():
            pass
        mock_conn.close.assert_called_once()

    def test_cursor_created_without_dictionary(self) -> None:
        pool, mock_connector_pool = _make_pool()
        mock_conn = MagicMock()
        mock_connector_pool.get_connection.return_value = mock_conn

        with pool.tuple_cursor():
            pass
        mock_conn.cursor.assert_called_once_with()
