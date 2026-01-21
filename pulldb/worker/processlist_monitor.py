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
from pulldb.infra.timeouts import DEFAULT_MYSQL_CONNECT_TIMEOUT_MONITOR

logger = get_logger("pulldb.worker.processlist_monitor")

# Thread and polling configuration constants
THREAD_JOIN_TIMEOUT_SECONDS: float = 5.0
DEBUG_LOG_ROW_LIMIT: int = 2
DEBUG_INFO_PREVIEW_LENGTH: int = 60

# Regex to extract completion percentage from myloader query comments
# myloader embeds: /* Completed: 45.67% */
RE_COMPLETED = re.compile(r"/\*\s*Completed:\s*([\d.]+)%\s*\*/")

# Regex to extract table name from INSERT or LOAD DATA query
# INSERT INTO `tablename` or INSERT INTO tablename
RE_INSERT_TABLE = re.compile(r"INSERT\s+INTO\s+`?([^\s`(]+)`?", re.IGNORECASE)
# LOAD DATA LOCAL INFILE '...' INTO TABLE `tablename`
RE_LOAD_TABLE = re.compile(r"INTO\s+TABLE\s+`?([^\s`(]+)`?", re.IGNORECASE)

# Regex patterns for index rebuild detection (ALTER TABLE ... ADD KEY)
# ALTER TABLE `tablename` ADD KEY ... or ALTER TABLE tablename ADD KEY/INDEX
RE_ALTER_TABLE = re.compile(r"ALTER\s+TABLE\s+`?([^\s`(]+)`?", re.IGNORECASE)
# Matches ADD KEY or ADD INDEX (index rebuild indicator)
RE_ADD_KEY = re.compile(r"ADD\s+(?:KEY|INDEX)", re.IGNORECASE)


@dataclass(slots=True)
class TableProgress:
    """Progress tracking for a single table.

    Attributes:
        table: Table name.
        percent_complete: Latest completion percentage (0-100).
        last_updated: Timestamp of last update.
        phase: Current phase - 'loading' for data import, 'indexing' for ALTER TABLE.
        running_seconds: Time column from processlist (seconds running).
    """

    table: str
    percent_complete: float = 0.0
    last_updated: float = field(default_factory=time.monotonic)
    phase: str = "loading"  # 'loading' or 'indexing'
    running_seconds: int = 0


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

    def stop(self, final_poll: bool = True) -> None:
        """Stop background polling thread.

        Args:
            final_poll: If True, perform one final poll before stopping to capture
                the last state of any in-progress tables. This prevents "orphaned"
                table progress bars when myloader finishes faster than poll interval.
        """
        # Perform final poll BEFORE setting stop event to capture last state
        if final_poll:
            try:
                snapshot = self.poll_once()
                if snapshot:
                    with self._lock:
                        self._latest_snapshot = snapshot
                    if self._progress_callback:
                        try:
                            self._progress_callback(snapshot)
                        except Exception as e:
                            logger.warning(f"Final progress callback error: {e}")
            except Exception as e:
                logger.warning(f"Final processlist poll error: {e}")

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=THREAD_JOIN_TIMEOUT_SECONDS)
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
                logger.warning(f"Processlist poll error: {e}")

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
                connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_MONITOR,
            )
        except Exception as e:
            logger.warning(f"Processlist monitor connection failed: {e}")
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
            logger.warning(f"Processlist query failed: {e}")
            return None

    def _parse_processlist_rows(
        self, rows: list[dict[str, Any]]
    ) -> ProcesslistSnapshot:
        """Parse processlist rows into snapshot.
        
        Detects two types of operations:
        1. Data loading: INSERT/LOAD statements with /* Completed: XX% */ comments
        2. Index rebuild: ALTER TABLE ... ADD KEY/INDEX statements
        """
        tables: dict[str, TableProgress] = {}
        active_threads = 0
        indexing_threads = 0

        # Debug: log all databases we see in processlist
        all_dbs = set()
        for row in rows:
            db = row.get("db") or row.get("Db")
            if db:
                all_dbs.add(db)
        if all_dbs:
            logger.debug(
                "processlist_dbs_seen",
                extra={"dbs": list(all_dbs), "staging_db": self._config.staging_db},
            )

        # Process each row
        matching_rows = 0
        for row in rows:
            # Filter for threads on our staging DB
            db = row.get("db") or row.get("Db")
            info = row.get("Info") or row.get("info") or ""
            time_col = row.get("Time") or row.get("time") or 0

            if db != self._config.staging_db:
                continue
            
            matching_rows += 1
            # Log the first few matching rows to debug
            if matching_rows <= DEBUG_LOG_ROW_LIMIT:
                logger.debug(
                    "processlist_row_matched",
                    extra={
                        "db": db,
                        "info_preview": str(info)[:DEBUG_INFO_PREVIEW_LENGTH] if info else None,
                    },
                )

            if not info or not isinstance(info, str):
                continue

            info_upper = info.upper()
            
            # Check for ALTER TABLE ... ADD KEY (index rebuild)
            if "ALTER" in info_upper and RE_ADD_KEY.search(info):
                alter_match = RE_ALTER_TABLE.search(info)
                if alter_match:
                    table_name = alter_match.group(1)
                    indexing_threads += 1
                    active_threads += 1
                    
                    # Parse Time column for running seconds
                    running_seconds = 0
                    try:
                        running_seconds = int(time_col)
                    except (ValueError, TypeError):
                        pass
                    
                    # Update or create table progress with indexing phase
                    self._update_table_progress(
                        tables, table_name, percent=100.0,
                        phase="indexing", running_seconds=running_seconds,
                    )
                    continue

            # Check for INSERT/LOAD data operations with Completed comment
            has_completed = "/* COMPLETED:" in info_upper
            has_data_op = "INSERT" in info_upper or "LOAD" in info_upper
            if not (has_completed and has_data_op):
                continue

            active_threads += 1

            # Extract table name - try INSERT pattern first, then LOAD DATA pattern
            table_match = RE_INSERT_TABLE.search(info)
            if not table_match:
                table_match = RE_LOAD_TABLE.search(info)
            if not table_match:
                continue
            table_name = table_match.group(1)

            # Extract completion percentage
            percent = self._extract_percent(info)

            # Update or create table progress (data loading phase)
            self._update_table_progress(tables, table_name, percent, phase="loading")

        snapshot = ProcesslistSnapshot(
            tables=tables,
            active_threads=active_threads,
            timestamp=time.monotonic(),
        )
        if active_threads > 0 or tables:
            logger.debug(
                "processlist_snapshot",
                extra={
                    "active_threads": active_threads,
                    "indexing_threads": indexing_threads,
                    "table_count": len(tables),
                    "tables": list(tables.keys())[:5],
                },
            )
        return snapshot

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
        phase: str = "loading",
        running_seconds: int = 0,
    ) -> None:
        """Update table progress tracking.
        
        Args:
            tables: Dict to update
            table_name: Name of table
            percent: Completion percentage (0-100)
            phase: 'loading' for data import, 'indexing' for ALTER TABLE
            running_seconds: Time from processlist Time column
        """
        if table_name in tables:
            existing = tables[table_name]
            # Only update percent if higher (loading phase)
            # Always update to indexing phase if detected
            if phase == "indexing" or percent > existing.percent_complete:
                existing.percent_complete = percent
                existing.last_updated = time.monotonic()
            # Always update phase if moving to indexing
            if phase == "indexing":
                existing.phase = "indexing"
                existing.running_seconds = running_seconds
        else:
            tables[table_name] = TableProgress(
                table=table_name,
                percent_complete=percent,
                last_updated=time.monotonic(),
                phase=phase,
                running_seconds=running_seconds,
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
