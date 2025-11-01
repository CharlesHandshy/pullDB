"""SettingsRepository tests.

CRUD operations: get missing, insert+get, update existing, get all.

MANDATE: Uses AWS Secrets Manager for DB login via conftest.py fixtures.
"""

from __future__ import annotations

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
        initial = "db-mysql-db4-dev"
        updated = "db-mysql-db5-dev"
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
