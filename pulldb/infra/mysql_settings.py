"""MySQL settings repository for pullDB.

Implements the SettingsRepository class for key-value configuration
settings management.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import logging

from pulldb.infra.mysql_pool import (
    MySQLPool,
    TypedDictCursor,
    TypedTupleCursor,
)

logger = logging.getLogger(__name__)

class SettingsRepository:
    """Repository for settings operations.

    Manages configuration settings stored in the database. Settings supplement
    environment variables and provide runtime configuration that can be updated
    without redeployment.

    Example:
        >>> repo = SettingsRepository(pool)
        >>> default_host = repo.get_setting("default_dbhost")
        >>> print(default_host)  # "localhost"
        >>> all_settings = repo.get_all_settings()
        >>> print(all_settings["s3_bucket_path"])
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize SettingsRepository with connection pool.

        Args:
            pool: MySQL connection pool for coordination database access.
        """
        self.pool = pool

    def get(self, key: str) -> str | None:
        """Alias for get_setting().

        Args:
            key: Setting key to look up.

        Returns:
            Setting value if found, None otherwise.
        """
        return self.get_setting(key)

    def get_setting(self, key: str) -> str | None:
        """Get setting value by key.

        Args:
            key: Setting key to look up.

        Returns:
            Setting value if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT setting_value
                FROM settings
                WHERE setting_key = %s
                """,
                (key,),
            )
            row = cursor.fetchone()
            return row["setting_value"] if row else None

    def get_setting_required(self, key: str) -> str:
        """Get required setting value.

        Args:
            key: Setting key to look up.

        Returns:
            Setting value.

        Raises:
            ValueError: If setting not found.
        """
        value = self.get_setting(key)
        if value is None:
            raise ValueError(f"Required setting '{key}' not found")
        return value

    def get_max_active_jobs_per_user(self) -> int:
        """Get maximum active jobs allowed per user.

        Returns:
            Maximum concurrent active jobs per user. 0 means unlimited.
        """
        value = self.get_setting("max_active_jobs_per_user")
        if value is None:
            return 0  # Default: unlimited
        try:
            return int(value)
        except ValueError:
            return 0  # Default: unlimited if setting is invalid

    def is_maintenance_mode_enabled(self) -> bool:
        """Check if global maintenance mode is active.

        When True the worker will not claim new jobs. Running jobs continue
        until complete. Toggle via: pulldb-admin maintenance enable/disable

        Returns:
            True if maintenance mode is enabled, False otherwise.
        """
        value = self.get_setting("maintenance_mode")
        if value is None:
            return False
        return value.lower() in ("true", "1", "yes")

    def get_max_active_jobs_global(self) -> int:
        """Get maximum active jobs allowed system-wide.

        Returns:
            Maximum concurrent active jobs globally. 0 means unlimited.
        """
        value = self.get_setting("max_active_jobs_global")
        if value is None:
            return 0  # Default: unlimited
        try:
            return int(value)
        except ValueError:
            return 0  # Default: unlimited if setting is invalid

    def get_staging_retention_days(self) -> int:
        """Get number of days before staging databases are eligible for cleanup.

        Returns:
            Retention days. 7 is the default. 0 means cleanup is disabled.
        """
        value = self.get_setting("staging_retention_days")
        if value is None:
            return 7  # Default: 7 days
        try:
            return max(0, int(value))  # Ensure non-negative
        except ValueError:
            return 7  # Default: 7 days if setting is invalid

    def get_job_log_retention_days(self) -> int:
        """Get number of days before job logs are eligible for pruning.

        Returns:
            Retention days. 30 is the default. 0 means pruning is disabled.
        """
        value = self.get_setting("job_log_retention_days")
        if value is None:
            return 30  # Default: 30 days
        try:
            return max(0, int(value))  # Ensure non-negative
        except ValueError:
            return 30  # Default: 30 days if setting is invalid

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Set setting value (INSERT or UPDATE).

        Uses INSERT ... ON DUPLICATE KEY UPDATE to handle both new settings
        and updates to existing settings in a single operation.

        Args:
            key: Setting key.
            value: Setting value.
            description: Optional description of setting purpose.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            if description is not None:
                cursor.execute(
                    """
                    INSERT INTO settings
                        (setting_key, setting_value, description, updated_at)
                    VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        description = VALUES(description),
                        updated_at = UTC_TIMESTAMP(6)
                    """,
                    (key, value, description),
                )
            else:
                # Don't update description if not provided
                cursor.execute(
                    """
                    INSERT INTO settings
                        (setting_key, setting_value, updated_at)
                    VALUES (%s, %s, UTC_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        updated_at = UTC_TIMESTAMP(6)
                    """,
                    (key, value),
                )
            conn.commit()

    def get_all_settings(self) -> dict[str, str]:
        """Get all settings as dictionary.

        Returns:
            Dictionary mapping setting keys to values.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT setting_key, setting_value
                FROM settings
                ORDER BY setting_key ASC
                """
            )
            rows = cursor.fetchall()
            return {row["setting_key"]: row["setting_value"] for row in rows}

    def delete_setting(self, key: str) -> bool:
        """Delete a setting from the database.

        Args:
            key: Setting key to delete.

        Returns:
            True if setting was deleted, False if it didn't exist.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                DELETE FROM settings
                WHERE setting_key = %s
                """,
                (key,),
            )
            conn.commit()
            return bool(cursor.rowcount > 0)

    def get_all_settings_with_metadata(self) -> list[dict[str, str | None]]:
        """Get all settings with their metadata (description, updated_at).

        Returns:
            List of dicts with keys: setting_key, setting_value, description, updated_at
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT setting_key, setting_value, description, updated_at
                FROM settings
                ORDER BY setting_key ASC
                """
            )
            return list(cursor.fetchall())

    # -------------------------------------------------------------------------
    # Database Retention Settings
    # -------------------------------------------------------------------------

    def get_default_retention_days(self) -> int:
        """Get default retention days for new restores.

        Returns:
            Default days for new database expiration. Default: 7 (1 week).
        """
        value = self.get_setting("default_retention_days")
        if value is None:
            return 7  # Default: 1 week
        try:
            return max(1, int(value))
        except ValueError:
            return 7

    def get_max_retention_days(self) -> int:
        """Get maximum retention days for database expiration.

        Returns:
            Maximum days a database can be retained. Default: 180 (~6 months).
        """
        value = self.get_setting("max_retention_days")
        if value is None:
            return 180  # Default: ~6 months
        try:
            return max(1, int(value))
        except ValueError:
            return 180

    def get_expiring_warning_days(self) -> int:
        """Get days before expiry to show yellow 'will expire soon' warning.

        Returns:
            Number of days. Default: 7.
        """
        value = self.get_setting("expiring_warning_days")
        if value is None:
            return 7
        try:
            return max(0, int(value))
        except ValueError:
            return 7

    def get_cleanup_grace_days(self) -> int:
        """Get days after expiry before automatic cleanup.

        Returns:
            Number of days. Default: 7.
        """
        value = self.get_setting("cleanup_grace_days")
        if value is None:
            return 7
        try:
            return max(0, int(value))
        except ValueError:
            return 7

    def get_jobs_refresh_interval(self) -> int:
        """Get auto-refresh interval for jobs page in seconds.

        Returns:
            Interval in seconds. Default: 5. 0 means disabled.
        """
        value = self.get_setting("jobs_refresh_interval_seconds")
        if value is None:
            return 5  # Default: 5 seconds
        try:
            return max(0, min(60, int(value)))  # Clamp to 0-60
        except ValueError:
            return 5

    def get_retention_options(
        self, include_now: bool = False
    ) -> list[tuple[str, str]]:
        """Get retention dropdown options based on current settings.

        Generates a comprehensive set of options in days, weeks, and months,
        up to the maximum retention days setting.

        Args:
            include_now: Whether to include "Now" (immediate removal) option.

        Returns:
            List of (value, label) tuples for dropdown options.
            Value is days as string ("1", "7", "30", etc.) or "now".
            Label is human readable ("+1 day", "+1 week", "+1 month", etc.)
        """
        max_days = self.get_max_retention_days()

        options: list[tuple[str, str]] = []

        if include_now:
            options.append(("now", "Now"))

        # Days: 1, 3 (if max_days >= 3)
        if max_days >= 1:
            options.append(("1", "+1 day"))
        if max_days >= 3:
            options.append(("3", "+3 days"))

        # Weeks: 1, 2, 3, 4 weeks
        for weeks in [1, 2, 3, 4]:
            days = weeks * 7
            if days <= max_days:
                label = f"+{weeks} week" if weeks == 1 else f"+{weeks} weeks"
                options.append((str(days), label))

        # Months: 2, 3, 4, 5, 6 months (skip 1 month = 4 weeks already covered)
        for months in [2, 3, 4, 5, 6]:
            days = months * 30
            if days <= max_days:
                options.append((str(days), f"+{months} months"))

        return options


