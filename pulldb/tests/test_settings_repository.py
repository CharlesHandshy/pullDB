"""SettingsRepository tests.

CRUD operations: get missing, insert+get, update existing, get all.
Also tests new configurable settings like cleanup retention.

MANDATE: Uses AWS Secrets Manager for DB login via conftest.py fixtures.
"""

from __future__ import annotations

"""HCA Layer: tests."""

from typing import Any

from pulldb.infra.mysql import SettingsRepository


class TestSettingsRepository:
    def _cleanup(self, pool: Any, sql: str, params: tuple[Any, ...]) -> None:
        with pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            cursor.close()

    def test_get_setting_not_found(self, mysql_pool: Any) -> None:
        repo = SettingsRepository(mysql_pool)
        assert repo.get_setting("does_not_exist") is None

    def test_set_setting_insert_and_get(self, mysql_pool: Any) -> None:
        repo = SettingsRepository(mysql_pool)
        key = "s3_bucket_path"
        val = "example-bucket/path"
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))
        repo.set_setting(key, val, description="Path")
        assert repo.get_setting(key) == val
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))

    def test_set_setting_update(self, mysql_pool: Any) -> None:
        repo = SettingsRepository(mysql_pool)
        key = "default_dbhost"
        initial = "dev-db-01"
        updated = "dev-db-02"
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))
        repo.set_setting(key, initial, description="Initial host")
        repo.set_setting(key, updated, description="Updated host")
        assert repo.get_setting(key) == updated
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))

    def test_get_all_settings(self, mysql_pool: Any) -> None:
        repo = SettingsRepository(mysql_pool)
        key1, val1 = "setting_one", "value1"
        key2, val2 = "setting_two", "value2"
        self._cleanup(
            mysql_pool,
            "DELETE FROM settings WHERE setting_key IN (%s,%s)",
            (key1, key2),
        )
        repo.set_setting(key1, val1, description="Desc1")
        repo.set_setting(key2, val2, description="Desc2")
        all_settings = repo.get_all_settings()
        assert all_settings[key1] == val1 and all_settings[key2] == val2
        self._cleanup(
            mysql_pool,
            "DELETE FROM settings WHERE setting_key IN (%s,%s)",
            (key1, key2),
        )

    def test_get_staging_retention_days_default(self, mysql_pool: Any) -> None:
        """Test cleanup retention returns default 7 when not set."""
        repo = SettingsRepository(mysql_pool)
        key = "staging_retention_days"
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))
        assert repo.get_staging_retention_days() == 7

    def test_get_staging_retention_days_custom(self, mysql_pool: Any) -> None:
        """Test cleanup retention returns configured value."""
        repo = SettingsRepository(mysql_pool)
        key = "staging_retention_days"
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))
        repo.set_setting(key, "14", description="Custom retention")
        assert repo.get_staging_retention_days() == 14
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))

    def test_get_staging_retention_days_disabled(self, mysql_pool: Any) -> None:
        """Test cleanup retention returns 0 when disabled."""
        repo = SettingsRepository(mysql_pool)
        key = "staging_retention_days"
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))
        repo.set_setting(key, "0", description="Disabled")
        assert repo.get_staging_retention_days() == 0
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))

    def test_get_staging_retention_days_invalid(self, mysql_pool: Any) -> None:
        """Test cleanup retention returns default 7 for invalid values."""
        repo = SettingsRepository(mysql_pool)
        key = "staging_retention_days"
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))
        repo.set_setting(key, "not_a_number", description="Invalid")
        assert repo.get_staging_retention_days() == 7
        self._cleanup(mysql_pool, "DELETE FROM settings WHERE setting_key = %s", (key,))
