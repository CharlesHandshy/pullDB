"""Tests for HostRepository.database_exists and get_pulldb_metadata_owner.

Phase 7c: Verifies the infra-layer implementations (mysql.py) of the
new HostRepository protocol methods introduced in Phase 5.

Test Count: 8 tests
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestDatabaseExists:
    """Tests for HostRepository.database_exists."""

    def test_database_exists_returns_true(self) -> None:
        """Returns True when SHOW DATABASES finds a match."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "root"
        mock_creds.password = "password"

        with patch.object(repo, "get_host_credentials", return_value=mock_creds):
            with patch("mysql.connector.connect") as mock_connect:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = ("mytestdb",)
                mock_conn = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_connect.return_value = mock_conn

                result = repo.database_exists("localhost", "mytestdb")
                assert result is True
                mock_conn.close.assert_called_once()

    def test_database_exists_returns_false(self) -> None:
        """Returns False when SHOW DATABASES has no match."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "root"
        mock_creds.password = "password"

        with patch.object(repo, "get_host_credentials", return_value=mock_creds):
            with patch("mysql.connector.connect") as mock_connect:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = None
                mock_conn = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_connect.return_value = mock_conn

                result = repo.database_exists("localhost", "mytestdb")
                assert result is False

    def test_database_exists_propagates_exception(self) -> None:
        """Connection errors propagate to caller."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        with patch.object(repo, "get_host_credentials", side_effect=Exception("Connection refused")):
            with pytest.raises(Exception, match="Connection refused"):
                repo.database_exists("localhost", "mytestdb")


class TestGetPulldbMetadataOwner:
    """Tests for HostRepository.get_pulldb_metadata_owner."""

    def test_no_pulldb_table(self) -> None:
        """Returns (False, None, None) when no pullDB table exists."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "root"
        mock_creds.password = "password"

        with patch.object(repo, "get_host_credentials", return_value=mock_creds):
            with patch("mysql.connector.connect") as mock_connect:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = None  # no pullDB table
                mock_conn = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_connect.return_value = mock_conn

                result = repo.get_pulldb_metadata_owner("localhost", "mytestdb")
                assert result == (False, None, None)

    def test_pulldb_table_no_owner_columns(self) -> None:
        """Returns (True, None, None) when pullDB table has no owner columns."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "root"
        mock_creds.password = "password"

        with patch.object(repo, "get_host_credentials", return_value=mock_creds):
            with patch("mysql.connector.connect") as mock_connect:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.side_effect = [
                    ("pullDB",),  # table exists
                    None,  # no owner_user_id column
                ]
                mock_conn = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_connect.return_value = mock_conn

                result = repo.get_pulldb_metadata_owner("localhost", "mytestdb")
                assert result == (True, None, None)

    def test_pulldb_table_with_owner(self) -> None:
        """Returns owner info when pullDB table has owner columns."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "root"
        mock_creds.password = "password"

        with patch.object(repo, "get_host_credentials", return_value=mock_creds):
            with patch("mysql.connector.connect") as mock_connect:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.side_effect = [
                    ("pullDB",),  # table exists
                    ("owner_user_id",),  # has owner columns
                    ("owner-uuid", "ownrx"),  # owner data
                ]
                mock_conn = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_connect.return_value = mock_conn

                has_table, owner_id, owner_code = repo.get_pulldb_metadata_owner(
                    "localhost", "mytestdb"
                )
                assert has_table is True
                assert owner_id == "owner-uuid"
                assert owner_code == "ownrx"

    def test_pulldb_table_with_empty_owner(self) -> None:
        """Returns (True, None, None) when owner row exists but values are NULL."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        mock_creds = MagicMock()
        mock_creds.host = "localhost"
        mock_creds.port = 3306
        mock_creds.username = "root"
        mock_creds.password = "password"

        with patch.object(repo, "get_host_credentials", return_value=mock_creds):
            with patch("mysql.connector.connect") as mock_connect:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.side_effect = [
                    ("pullDB",),  # table exists
                    ("owner_user_id",),  # has owner columns
                    (None, None),  # NULL owner values
                ]
                mock_conn = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_connect.return_value = mock_conn

                has_table, owner_id, owner_code = repo.get_pulldb_metadata_owner(
                    "localhost", "mytestdb"
                )
                assert has_table is True
                assert owner_id is None
                assert owner_code is None

    def test_pulldb_connection_error_propagates(self) -> None:
        """Connection errors propagate to caller."""
        from pulldb.infra.mysql import HostRepository

        repo = HostRepository.__new__(HostRepository)

        with patch.object(repo, "get_host_credentials", side_effect=Exception("timeout")):
            with pytest.raises(Exception, match="timeout"):
                repo.get_pulldb_metadata_owner("localhost", "mytestdb")
