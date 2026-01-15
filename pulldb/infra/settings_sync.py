"""Settings synchronization utilities.

Provides functions to detect and report configuration drift between
.env file and database settings.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pulldb.domain.settings import SETTING_REGISTRY
from pulldb.infra.envfile import find_env_file, read_env_file
from pulldb.infra.factory import get_settings_repository

logger = logging.getLogger(__name__)


@dataclass
class SettingMismatch:
    """A single setting that differs between .env and database."""

    key: str
    env_var: str
    env_value: str | None
    db_value: str | None
    description: str

    @property
    def is_env_only(self) -> bool:
        """True if setting only exists in .env."""
        return self.env_value is not None and self.db_value is None

    @property
    def is_db_only(self) -> bool:
        """True if setting only exists in database."""
        return self.db_value is not None and self.env_value is None

    @property
    def is_different(self) -> bool:
        """True if setting exists in both but values differ."""
        return (
            self.env_value is not None
            and self.db_value is not None
            and self.env_value != self.db_value
        )


@dataclass
class SyncCheckResult:
    """Result of comparing .env and database settings."""

    mismatches: list[SettingMismatch]
    env_file_path: str | None
    error: str | None = None

    @property
    def is_synced(self) -> bool:
        """True if .env and database are in sync."""
        return not self.mismatches and not self.error

    @property
    def differences(self) -> list[SettingMismatch]:
        """Settings that exist in both but with different values."""
        return [m for m in self.mismatches if m.is_different]

    @property
    def env_only(self) -> list[SettingMismatch]:
        """Settings that only exist in .env."""
        return [m for m in self.mismatches if m.is_env_only]

    @property
    def db_only(self) -> list[SettingMismatch]:
        """Settings that only exist in database."""
        return [m for m in self.mismatches if m.is_db_only]

    @property
    def summary(self) -> str:
        """Human-readable summary of sync status."""
        if self.error:
            return f"Sync check failed: {self.error}"
        if self.is_synced:
            return "Settings are in sync"
        parts: list[str] = []
        if diff_count := len(self.differences):
            parts.append(f"{diff_count} different")
        if env_count := len(self.env_only):
            parts.append(f"{env_count} .env only")
        if db_count := len(self.db_only):
            parts.append(f"{db_count} database only")
        return f"Out of sync: {', '.join(parts)}"


def check_env_db_sync() -> SyncCheckResult:
    """Compare .env settings against database settings.

    Returns a SyncCheckResult with any mismatches found.
    This is the main entry point for sync checking.

    Returns:
        SyncCheckResult with mismatches list or error if check failed.
    """
    # Find .env file
    env_path = find_env_file()
    if not env_path:
        return SyncCheckResult(
            mismatches=[],
            env_file_path=None,
            error="No .env file found",
        )

    # Read .env file settings
    try:
        env_file_settings = read_env_file(env_path)
    except Exception as e:
        logger.exception("Failed to read .env file")
        return SyncCheckResult(
            mismatches=[],
            env_file_path=str(env_path),
            error=f"Failed to read .env: {e}",
        )

    # Get database settings
    try:
        repo = get_settings_repository()
        db_settings = repo.get_all_settings()
    except Exception as e:
        logger.exception("Failed to connect to database")
        return SyncCheckResult(
            mismatches=[],
            env_file_path=str(env_path),
            error=f"Database connection failed: {e}",
        )

    # Compare settings from SETTING_REGISTRY (known settings only)
    mismatches: list[SettingMismatch] = []

    for key, meta in SETTING_REGISTRY.items():
        env_value = env_file_settings.get(meta.env_var)
        db_value = db_settings.get(key)

        # Skip if neither has the setting (both using defaults)
        if env_value is None and db_value is None:
            continue

        # Skip if values match
        if env_value == db_value:
            continue

        # Found a mismatch
        mismatches.append(
            SettingMismatch(
                key=key,
                env_var=meta.env_var,
                env_value=env_value,
                db_value=db_value,
                description=meta.description,
            )
        )

    return SyncCheckResult(
        mismatches=mismatches,
        env_file_path=str(env_path),
    )


def get_critical_mismatches() -> list[SettingMismatch]:
    """Get only critical mismatches (different values, not just missing).

    This is useful for admin UI banners where we only want to show
    actionable items, not just settings that haven't been pushed yet.

    Returns:
        List of settings that exist in both .env and DB but differ.
    """
    result = check_env_db_sync()
    if result.error:
        logger.warning("Sync check failed: %s", result.error)
        return []
    return result.differences
