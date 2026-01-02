"""MySQL processlist polling for myloader progress tracking.

Polls `SHOW PROCESSLIST` during myloader execution to extract per-table
progress from myloader's embedded `/* Completed: XX% */` query comments.

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

import mysql.connector

from pulldb.infra.logging import get_logger

logger = get_logger("pulldb.worker.processlist_monitor")

# Regex to extract completion percentage from myloader query comments
# myloader embeds: /* Completed: 45.67% */
RE_COMPLETED = re.compile(r"/\*\s*Completed:\s*([\d.]+)%\s*\*/")

# Regex to extract table name from INSERT query
# INSERT INTO `tablename` or INSERT INTO tablename
RE_INSERT_TABLE = re.compile(r"INSERT\s+INTO\s+`?([^\s`(]+)`?", re.IGNORECASE)


@dataclass(slots=True)
class TableProgress:
    """Progress tracking for a single table.

    Attributes:
        table: Table name.
        percent_complete: Latest completion percentage (0-100).
        last_updated: Timestamp of last update.
    """

    table: str
    percent_complete: float = 0.0
    last_updated: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class ProcesslistSnapshot:
    """Snapshot of myloader progress from processlist.

    Attributes:
        tables: Dict mapping table name to TableProgress.
        active_threads: Number of active myloader threads.
        timestamp: When snapshot was taken.
    """

    tables: dict[str, TableProgress]
    active_threads: int
    timestamp: float


@dataclass(slots=True, frozen=True)
class ProcesslistMonitorConfig:
    """Configuration for processlist monitor.

    Attributes:
        mysql_host: MySQL server hostname.
        mysql_port: MySQL server port.
        mysql_user: MySQL user (needs PROCESS privilege).
        mysql_password: MySQL password.
        poll_interval_seconds: How often to poll (default 2s).
        staging_db: Database name to filter queries for.
    """

    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    staging_db: str
    poll_interval_seconds: float = 2.0


class ProcesslistMonitor:
    """Background thread that polls MySQL processlist for myloader progress.

    Usage:
        config = ProcesslistMonitorConfig(...)
        monitor = ProcesslistMonitor(config)
        monitor.start()
        # ... myloader runs ...
        snapshot = monitor.get_snapshot()
        monitor.stop()
    """

    def __init__(
        self,
        config: ProcesslistMonitorConfig,
        progress_callback: Callable[[ProcesslistSnapshot], None] | None = None,
    ) -> None:
        """Initialize processlist monitor.

        Args:
            config: Connection and polling configuration.
            progress_callback: Optional callback invoked on each poll with snapshot.
        """
        self._config = config
        self._progress_callback = progress_callback
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._latest_snapshot: ProcesslistSnapshot | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start background polling thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Monitor already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="processlist-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"Started processlist monitor for {self._config.staging_db} "
            f"(interval={self._config.poll_interval_seconds}s)"
        )

    def stop(self) -> None:
        """Stop background polling thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Stopped processlist monitor")

    def get_snapshot(self) -> ProcesslistSnapshot | None:
        """Get latest processlist snapshot.

        Returns:
            Latest snapshot or None if no data yet.
        """
        with self._lock:
            return self._latest_snapshot

    def _poll_loop(self) -> None:
        """Main polling loop running in background thread."""
        while not self._stop_event.is_set():
            try:
                snapshot = self.poll_once()
                if snapshot:
                    with self._lock:
                        self._latest_snapshot = snapshot
                    if self._progress_callback:
                        try:
                            self._progress_callback(snapshot)
                        except Exception as e:
                            logger.warning(f"Progress callback error: {e}")
            except Exception as e:
                logger.debug(f"Processlist poll error: {e}")

            self._stop_event.wait(self._config.poll_interval_seconds)

    def poll_once(self) -> ProcesslistSnapshot | None:
        """Execute single processlist poll.

        Public method for direct polling without starting background thread.

        Returns:
            ProcesslistSnapshot or None on error.
        """
        conn = self._connect()
        if conn is None:
            return None

        try:
            return self._execute_poll(conn)
        finally:
            with suppress(Exception):
                conn.close()

    def _connect(self) -> Any:
        """Create MySQL connection for polling.

        Returns connection object or None on failure.
        """
        try:
            return mysql.connector.connect(
                host=self._config.mysql_host,
                port=self._config.mysql_port,
                user=self._config.mysql_user,
                password=self._config.mysql_password,
                connection_timeout=5,
            )
        except Exception as e:
            logger.debug(f"Connection failed: {e}")
            return None

    def _execute_poll(self, conn: Any) -> ProcesslistSnapshot | None:
        """Execute processlist query and parse results."""
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SHOW PROCESSLIST")
            rows: list[dict[str, Any]] = cursor.fetchall()
            snapshot = self._parse_processlist_rows(rows)
            cursor.close()
            return snapshot
        except Exception as e:
            logger.debug(f"Query failed: {e}")
            return None

    def _parse_processlist_rows(
        self, rows: list[dict[str, Any]]
    ) -> ProcesslistSnapshot:
        """Parse processlist rows into snapshot."""
        tables: dict[str, TableProgress] = {}
        active_threads = 0

        for row in rows:
            # Filter for myloader threads on our staging DB
            db = row.get("db") or row.get("Db")
            info = row.get("Info") or row.get("info") or ""

            if db != self._config.staging_db:
                continue

            if not info or not isinstance(info, str):
                continue

            # Look for INSERT statements with completion comments
            if not info.upper().startswith("INSERT"):
                continue

            active_threads += 1

            # Extract table name
            table_match = RE_INSERT_TABLE.search(info)
            if not table_match:
                continue
            table_name = table_match.group(1)

            # Extract completion percentage
            percent = self._extract_percent(info)

            # Update or create table progress
            self._update_table_progress(tables, table_name, percent)

        return ProcesslistSnapshot(
            tables=tables,
            active_threads=active_threads,
            timestamp=time.monotonic(),
        )

    def _extract_percent(self, info: str) -> float:
        """Extract completion percentage from query comment."""
        pct_match = RE_COMPLETED.search(info)
        if not pct_match:
            return 0.0
        try:
            return float(pct_match.group(1))
        except ValueError:
            return 0.0

    def _update_table_progress(
        self,
        tables: dict[str, TableProgress],
        table_name: str,
        percent: float,
    ) -> None:
        """Update table progress tracking."""
        if table_name in tables:
            if percent > tables[table_name].percent_complete:
                tables[table_name].percent_complete = percent
                tables[table_name].last_updated = time.monotonic()
        else:
            tables[table_name] = TableProgress(
                table=table_name,
                percent_complete=percent,
                last_updated=time.monotonic(),
            )


def poll_processlist_once(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    staging_db: str,
) -> ProcesslistSnapshot | None:
    """Execute single processlist poll without starting monitor.

    Utility function for one-off polling.
    """
    config = ProcesslistMonitorConfig(
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_user=mysql_user,
        mysql_password=mysql_password,
        staging_db=staging_db,
    )
    monitor = ProcesslistMonitor(config)
    return monitor.poll_once()
