"""Configuration hot-reload support for pullDB services.

Provides a mechanism for services (worker, API) to detect and reload
configuration changes without requiring a full restart.

HCA Layer: shared (pulldb/infra/)

IMPORTANT DESIGN DECISION:
    Hot-reload reads settings DIRECTLY from the database via SettingsRepository,
    bypassing os.environ entirely. This is critical because Config.from_env_and_mysql()
    gives os.environ precedence over database values, which would defeat hot-reload.

Error Handling:
    - Errors are stored in DB (`_system_reload_error` key in settings table)
    - If DB is unavailable, errors are logged to syslog at LOG_ERR level
    - On successful reload, the error key is cleared

Usage:
    # In service initialization:
    from pulldb.infra.config_reload import ConfigReloader
    
    reloader = ConfigReloader(
        pool=mysql_pool,
        on_reload=lambda new_config: update_service_config(new_config),
    )
    reloader.start()  # Starts background watcher thread
    
    # Later, to stop:
    reloader.stop()
"""

from __future__ import annotations

import json
import logging
import syslog
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from pulldb.infra.mysql import MySQLPool

logger = logging.getLogger(__name__)

# Marker file locations (in priority order)
RELOAD_MARKER_PATHS = [
    Path("/var/lib/pulldb/.config-reload"),
    Path("/opt/pulldb.service/.config-reload"),
]

# How often to check for config changes (seconds)
# 5 minutes - settings don't change frequently
DEFAULT_CHECK_INTERVAL = 300

# Key used to store reload errors in settings table
SYSTEM_RELOAD_ERROR_KEY = "_system_reload_error"


def _parse_int(value: str | None, default: int) -> int:
    """Parse int from string, returning default on failure."""
    if not value:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _parse_float(value: str | None, default: float) -> float:
    """Parse float from string, returning default on failure."""
    if not value:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parse_list(value: str | None, default: list[str] | None = None) -> list[str]:
    """Parse comma-separated list from string."""
    if default is None:
        default = []
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class ReloadError:
    """Represents a configuration reload failure."""

    error_message: str
    failed_at: datetime
    source: str = "database"  # "database", "parsing", "validation"
    service: str = "unknown"  # "api", "worker"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "error_message": self.error_message,
            "failed_at": self.failed_at.isoformat(),
            "source": self.source,
            "service": self.service,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReloadError":
        """Deserialize from dictionary."""
        return cls(
            error_message=data["error_message"],
            failed_at=datetime.fromisoformat(data["failed_at"]),
            source=data.get("source", "database"),
            service=data.get("service", "unknown"),
        )


@dataclass
class ReloadableConfig:
    """Configuration values that can be reloaded without restart.

    Not all config values can be hot-reloaded. This class contains
    the subset that can be safely changed at runtime.
    """

    # Myloader settings
    myloader_timeout_seconds: float
    myloader_threads: int
    myloader_default_args: list[str] = field(default_factory=list)
    myloader_extra_args: list[str] = field(default_factory=list)

    # Job limits
    max_active_jobs_per_user: int = 3
    max_active_jobs_global: int = 10

    # Retention settings
    staging_retention_days: int = 30
    job_log_retention_days: int = 90

    # Settings that are hot-reloadable (no restart needed)
    HOT_RELOADABLE_KEYS: frozenset[str] = frozenset({
        "myloader_timeout_seconds",
        "myloader_threads",
        "myloader_default_args",
        "myloader_extra_args",
        "max_active_jobs_per_user",
        "max_active_jobs_global",
        "staging_retention_days",
        "job_log_retention_days",
    })

    @classmethod
    def is_hot_reloadable(cls, key: str) -> bool:
        """Check if a setting key is hot-reloadable (no restart needed)."""
        return key in cls.HOT_RELOADABLE_KEYS

    @classmethod
    def from_db_settings(cls, settings: dict[str, str]) -> "ReloadableConfig":
        """Build ReloadableConfig directly from database settings dict.

        This bypasses Config.from_env_and_mysql() to avoid os.environ precedence.
        Database values are used directly - this is the whole point of hot-reload.
        """
        return cls(
            myloader_timeout_seconds=_parse_float(
                settings.get("myloader_timeout_seconds"), 7200.0
            ),
            myloader_threads=_parse_int(settings.get("myloader_threads"), 8),
            myloader_default_args=_parse_list(
                settings.get("myloader_default_args"),
                ["--verbose=3", "--overwrite-tables"],
            ),
            myloader_extra_args=_parse_list(settings.get("myloader_extra_args")),
            max_active_jobs_per_user=_parse_int(
                settings.get("max_active_jobs_per_user"), 3
            ),
            max_active_jobs_global=_parse_int(
                settings.get("max_active_jobs_global"), 10
            ),
            staging_retention_days=_parse_int(
                settings.get("staging_retention_days"), 30
            ),
            job_log_retention_days=_parse_int(
                settings.get("job_log_retention_days"), 90
            ),
        )


class ConfigReloader:
    """Watches for configuration changes and triggers reload callbacks.

    Uses a marker file approach: when settings are synced via the web UI,
    a marker file's mtime is updated. This class watches that file and
    triggers a reload when it changes.

    IMPORTANT: This reads settings directly from database via SettingsRepository,
    NOT via Config.from_env_and_mysql(), because that method gives os.environ
    precedence which would defeat hot-reload.

    Error Handling:
        - On failure: stores error in DB with key `_system_reload_error`
        - If DB is unavailable: logs to syslog at LOG_ERR level
        - On success: clears any existing error from DB
        - Old config continues working during failures (graceful degradation)

    Args:
        pool: MySQL pool for loading settings from database.
        on_reload: Callback function that receives the new ReloadableConfig.
        check_interval: How often to check for changes (seconds).
        service_name: Name of service for error tracking ("api" or "worker").
    """

    def __init__(
        self,
        pool: "MySQLPool",
        on_reload: Callable[["ReloadableConfig"], None],
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        service_name: str = "unknown",
    ):
        self._pool = pool
        self._on_reload = on_reload
        self._check_interval = check_interval
        self._service_name = service_name
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_marker_mtime: float = 0.0
        self._current_config: ReloadableConfig | None = None

    def start(self) -> None:
        """Start the config watcher thread."""
        if self._running:
            return

        self._running = True
        self._last_marker_mtime = self._get_marker_mtime()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="ConfigReloader",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Config reloader started (checking every %ds)", int(self._check_interval)
        )

    def stop(self) -> None:
        """Stop the config watcher thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Config reloader stopped")

    def _get_marker_mtime(self) -> float:
        """Get the mtime of the reload marker file."""
        for path in RELOAD_MARKER_PATHS:
            if path.exists():
                try:
                    return path.stat().st_mtime
                except OSError:
                    continue
        return 0.0

    def _watch_loop(self) -> None:
        """Main watch loop running in background thread."""
        while self._running:
            try:
                time.sleep(self._check_interval)

                if not self._running:
                    break

                current_mtime = self._get_marker_mtime()
                if current_mtime > self._last_marker_mtime:
                    logger.info(
                        "Config reload marker changed, reloading settings from database..."
                    )
                    self._last_marker_mtime = current_mtime
                    self._do_reload()

            except Exception:
                # Log at info level - this is a background maintenance task
                logger.info("Config reload check skipped due to transient error")

    def _do_reload(self) -> None:
        """Reload configuration directly from database and notify callback.

        CRITICAL: Reads from database directly via SettingsRepository,
        NOT via Config.from_env_and_mysql(), because that method gives
        os.environ precedence over database values.
        """
        try:
            from pulldb.infra.mysql import SettingsRepository

            # Load settings directly from database (bypasses os.environ)
            settings_repo = SettingsRepository(self._pool)
            db_settings = settings_repo.get_all_settings()

            # Build reloadable config from raw DB values
            new_reloadable = ReloadableConfig.from_db_settings(db_settings)

            # Check if anything actually changed
            old_config = self._current_config
            if old_config and self._configs_equal(old_config, new_reloadable):
                logger.debug("Config reload: no changes detected in database")
                return

            self._current_config = new_reloadable

            # Log what changed
            if old_config:
                changes = self._describe_changes(old_config, new_reloadable)
                logger.info("Config reloaded from database: %s", changes)
            else:
                logger.info(
                    "Config loaded from database: timeout=%ds, threads=%d",
                    int(new_reloadable.myloader_timeout_seconds),
                    new_reloadable.myloader_threads,
                )

            # Clear any previous error on success
            self._clear_reload_error()

            # Notify callback
            self._on_reload(new_reloadable)

        except Exception as e:
            # Store error to DB, fallback to syslog if DB unavailable
            self._store_reload_error(str(e), source="database")
            logger.warning("Failed to reload config from database: %s", e)

    def _store_reload_error(self, error_message: str, source: str = "database") -> None:
        """Store reload error to database, fallback to syslog if DB unavailable."""
        error = ReloadError(
            error_message=error_message,
            failed_at=datetime.now(UTC),
            source=source,
            service=self._service_name,
        )

        try:
            from pulldb.infra.mysql import SettingsRepository

            settings_repo = SettingsRepository(self._pool)
            settings_repo.set_setting(
                SYSTEM_RELOAD_ERROR_KEY,
                json.dumps(error.to_dict()),
                description="System: last config reload error",
            )
        except Exception as db_error:
            # DB is unavailable - log to syslog as fallback
            syslog_msg = (
                f'pulldb.config_reload error="{error_message}" '
                f'source="{source}" service="{self._service_name}"'
            )
            try:
                syslog.syslog(syslog.LOG_ERR, syslog_msg)
            except Exception:
                pass  # Syslog also failed, nothing more we can do
            logger.error(
                "Could not store reload error to DB (DB error: %s), logged to syslog",
                db_error,
            )

    def _clear_reload_error(self) -> None:
        """Clear reload error from database after successful reload."""
        try:
            from pulldb.infra.mysql import SettingsRepository

            settings_repo = SettingsRepository(self._pool)
            settings_repo.delete_setting(SYSTEM_RELOAD_ERROR_KEY)
        except Exception:
            pass  # Best effort - error will be overwritten on next failure anyway

    def _describe_changes(
        self, old: ReloadableConfig, new: ReloadableConfig
    ) -> str:
        """Describe what changed between old and new config."""
        changes = []
        if old.myloader_timeout_seconds != new.myloader_timeout_seconds:
            changes.append(
                f"timeout {int(old.myloader_timeout_seconds)}→{int(new.myloader_timeout_seconds)}s"
            )
        if old.myloader_threads != new.myloader_threads:
            changes.append(f"threads {old.myloader_threads}→{new.myloader_threads}")
        if old.max_active_jobs_per_user != new.max_active_jobs_per_user:
            changes.append(
                f"jobs_per_user {old.max_active_jobs_per_user}→{new.max_active_jobs_per_user}"
            )
        if old.max_active_jobs_global != new.max_active_jobs_global:
            changes.append(
                f"jobs_global {old.max_active_jobs_global}→{new.max_active_jobs_global}"
            )
        return ", ".join(changes) if changes else "minor changes"

    def _configs_equal(self, a: ReloadableConfig, b: ReloadableConfig) -> bool:
        """Compare two configs for equality."""
        return (
            a.myloader_timeout_seconds == b.myloader_timeout_seconds
            and a.myloader_threads == b.myloader_threads
            and a.myloader_default_args == b.myloader_default_args
            and a.myloader_extra_args == b.myloader_extra_args
            and a.max_active_jobs_per_user == b.max_active_jobs_per_user
            and a.max_active_jobs_global == b.max_active_jobs_global
            and a.staging_retention_days == b.staging_retention_days
            and a.job_log_retention_days == b.job_log_retention_days
        )

    def force_reload(self) -> None:
        """Force an immediate config reload (for testing/manual trigger)."""
        self._do_reload()

    def get_health_status(self) -> dict[str, Any]:
        """Get health status for health check endpoint.

        Reads the last reload error from the database (not memory).
        """
        try:
            from pulldb.infra.mysql import SettingsRepository

            settings_repo = SettingsRepository(self._pool)
            error_json = settings_repo.get_setting(SYSTEM_RELOAD_ERROR_KEY)
            if error_json:
                error_data = json.loads(error_json)
                return {
                    "config_reloader": "degraded",
                    "last_reload_error": error_data,
                    "using_stale_config": True,
                }
        except Exception:
            pass  # Can't check DB, assume healthy

        return {
            "config_reloader": "healthy",
            "last_reload_error": None,
            "using_stale_config": False,
        }


def get_reloadable_settings_from_db(pool: "MySQLPool") -> ReloadableConfig:
    """Load reloadable settings directly from database.

    Useful for one-off checks without setting up the full reloader.
    Bypasses os.environ - reads database values directly.
    """
    from pulldb.infra.mysql import SettingsRepository

    settings_repo = SettingsRepository(pool)
    db_settings = settings_repo.get_all_settings()
    return ReloadableConfig.from_db_settings(db_settings)


def get_last_reload_error(pool: "MySQLPool") -> ReloadError | None:
    """Get the last reload error from the database, if any.

    Useful for health endpoints to check reload status.
    """
    try:
        from pulldb.infra.mysql import SettingsRepository

        settings_repo = SettingsRepository(pool)
        error_json = settings_repo.get_setting(SYSTEM_RELOAD_ERROR_KEY)
        if error_json:
            return ReloadError.from_dict(json.loads(error_json))
    except Exception:
        pass
    return None
