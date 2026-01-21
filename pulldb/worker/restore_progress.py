"""Unified restore progress tracking with row-based accuracy.

Single source of truth for all restore progress, replacing the fragmented
approach of separate file-based and processlist-based tracking.

Key Design Principles:
1. ROW-BASED progress (not file-based) for accuracy
2. Thread-safe with immutable snapshots for consumers
3. Processlist is PRIMARY source (real-time from MySQL)
4. Myloader stdout CONFIRMS completions (authoritative for done)
5. Single consistent event format for all consumers

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal


if TYPE_CHECKING:
    from collections.abc import Callable

from pulldb.infra.logging import get_logger
from pulldb.worker.backup_metadata import TableRowEstimate
from pulldb.worker.processlist_monitor import ProcesslistSnapshot


logger = get_logger("pulldb.worker.restore_progress")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(slots=True, frozen=True)
class TableProgressInfo:
    """Immutable progress info for a single table.

    Attributes:
        name: Table name (without database prefix).
        percent_complete: Progress percentage (0-100).
        phase: Current phase - 'loading' or 'indexing'.
        rows_loaded: Estimated rows loaded so far.
        rows_total: Total rows expected for this table.
        running_seconds: Time this table has been in current phase.
        is_complete: Whether this table is fully restored.
    """

    name: str
    percent_complete: float
    phase: Literal["loading", "indexing", "complete"]
    rows_loaded: int
    rows_total: int
    running_seconds: float = 0.0
    is_complete: bool = False


@dataclass(slots=True, frozen=True)
class ThroughputStats:
    """Throughput and ETA calculations.

    Attributes:
        rows_per_second: Current restore throughput.
        elapsed_seconds: Time since restore started.
        eta_seconds: Estimated seconds remaining (None if cannot estimate).
    """

    rows_per_second: int
    elapsed_seconds: float
    eta_seconds: int | None


@dataclass(slots=True, frozen=True)
class RestoreProgress:
    """Immutable snapshot of restore progress for UI/events.

    This is the SINGLE consistent format for all progress reporting.
    Thread-safe to share across threads.

    Attributes:
        percent_complete: Overall progress (0-100), row-based.
        tables_total: Total number of tables being restored.
        tables_completed: Number of fully restored tables.
        tables_in_progress: Currently active tables with per-table progress.
        rows_loaded: Total rows loaded across all tables.
        rows_total: Total rows expected across all tables.
        throughput: Throughput and ETA stats.
        timestamp: When this snapshot was created.
        source: What triggered this update ('processlist', 'file_complete',
            'finalized').
    """

    percent_complete: float
    tables_total: int
    tables_completed: int
    tables_in_progress: tuple[TableProgressInfo, ...]
    rows_loaded: int
    rows_total: int
    throughput: ThroughputStats
    timestamp: datetime
    source: Literal["processlist", "file_complete", "finalized"]

    def to_event_dict(self) -> dict:
        """Convert to dict format for event emission.

        Returns:
            Dict compatible with existing restore_progress event format.
        """
        status = (
            "processlist_update" if self.source == "processlist" else "finished"
        )
        # Include BOTH in-progress and recently-completed tables
        # This ensures the UI sees tables transition to 100% rather than
        # suddenly disappearing when finalized
        tables_dict = {
            t.name: {
                "percent_complete": t.percent_complete,
                "phase": t.phase,
                "running_seconds": t.running_seconds,
                "is_complete": t.is_complete,
            }
            for t in self.tables_in_progress
        }
        return {
            "percent": self.percent_complete,
            "detail": {
                "status": status,
                "active_threads": len(
                    [t for t in self.tables_in_progress if not t.is_complete]
                ),
                "tables": tables_dict,
                "rows_restored": self.rows_loaded,
                "total_rows": self.rows_total,
                "rows_per_second": self.throughput.rows_per_second,
                "eta_seconds": self.throughput.eta_seconds,
                "tables_completed": self.tables_completed,
                "tables_total": self.tables_total,
            },
        }


# =============================================================================
# Internal Mutable State
# =============================================================================


@dataclass
class _MutableTableState:
    """Internal mutable state for a single table."""

    name: str
    rows_total: int
    percent_complete: float = 0.0
    phase: str = "loading"  # 'loading', 'indexing', 'complete'
    running_seconds: float = 0.0
    is_complete: bool = False
    last_seen_in_processlist: float = 0.0
    files_completed: int = 0  # Track how many chunk files have finished
    was_ever_seen: bool = False  # Track if table was ever in processlist


# Timeout after which a table not in processlist is considered complete
# If a table had progress and disappears for this long, it's done
_STALE_TABLE_TIMEOUT_SECONDS = 10.0


# =============================================================================
# Main Tracker Class
# =============================================================================


class RestoreProgressTracker:
    """Thread-safe restore progress tracking with row-based accuracy.

    Single source of truth for restore progress. Integrates:
    - Table metadata (expected row counts)
    - Processlist polling (real-time per-table progress)
    - Myloader stdout (completion confirmations)

    Usage:
        tracker = RestoreProgressTracker(
            table_metadata=backup_meta.tables,
            on_progress=lambda p: emit_event("restore_progress", p.to_event_dict()),
        )

        # Feed from processlist monitor (every 2s)
        monitor = ProcesslistMonitor(
            config, progress_callback=tracker.update_from_processlist
        )

        # Feed from myloader stdout
        for line in myloader_output:
            tracker.update_from_myloader_line(line)

        # Get final state when myloader exits
        final = tracker.finalize()
    """

    # Regex patterns for parsing myloader output
    _RE_FINISHED = re.compile(
        r"(?:Thread \d+|Message: Thread \d+) finished restoring (\S+)"
    )
    _RE_VERBOSE_RESTORE = re.compile(
        r"Thread \d+: restoring .+ from (.+?)(?: \||\. Tables|$)"
    )

    def __init__(
        self,
        table_metadata: list[TableRowEstimate],
        on_progress: Callable[[RestoreProgress], None] | None = None,
        throttle_interval_seconds: float = 0.5,
    ) -> None:
        """Initialize tracker.

        Args:
            table_metadata: List of tables with row estimates from backup metadata.
            on_progress: Optional callback invoked on each progress update.
                Receives immutable RestoreProgress snapshot.
            throttle_interval_seconds: Minimum interval between progress emissions.
                Prevents flooding with too many events. Set to 0 to disable.
        """
        self._lock = threading.RLock()  # Reentrant for nested calls
        self._on_progress = on_progress
        self._throttle_interval = throttle_interval_seconds
        self._last_emit_time: float = 0.0
        self._start_time = time.monotonic()

        # Immutable setup
        self._total_tables = len(table_metadata)
        self._total_rows = sum(t.rows for t in table_metadata)
        self._table_rows: dict[str, int] = {t.table: t.rows for t in table_metadata}

        # Mutable state
        self._tables: dict[str, _MutableTableState] = {}
        self._tables_completed: set[str] = set()

        # Initialize table states
        for t in table_metadata:
            self._tables[t.table] = _MutableTableState(
                name=t.table,
                rows_total=t.rows,
            )

        logger.info(
            f"Initialized progress tracker: {self._total_tables} tables, "
            f"{self._total_rows:,} total rows"
        )

    def update_from_processlist(self, snapshot: ProcesslistSnapshot) -> None:
        """Update progress from processlist poll.

        Called by ProcesslistMonitor background thread every ~2 seconds.
        This is the PRIMARY source for real-time progress.

        Args:
            snapshot: Latest processlist snapshot from MySQL.
        """
        now = time.monotonic()
        # Track which tables are currently in processlist
        tables_in_processlist: set[str] = set()

        with self._lock:
            # Update tables seen in processlist
            for table_name, progress in snapshot.tables.items():
                # Handle table names with/without database prefix
                bare_name = self._normalize_table_name(table_name)
                tables_in_processlist.add(bare_name)
                state = self._tables.get(bare_name)

                if state is None:
                    # Unknown table - might be in processlist but not in our metadata
                    logger.debug(f"Ignoring unknown table in processlist: {table_name}")
                    continue

                if state.is_complete:
                    # Already marked complete
                    continue

                state.percent_complete = min(100.0, progress.percent_complete)
                state.phase = progress.phase
                state.running_seconds = progress.running_seconds
                state.last_seen_in_processlist = now
                state.was_ever_seen = True

            # Check for tables that have left processlist
            # Mark complete if: was seen before, not in processlist now, and either:
            #   - has file completions (myloader confirmed), OR
            #   - has been gone for > stale timeout (likely complete)
            for state in self._tables.values():
                if state.is_complete:
                    continue

                # Skip tables never seen in processlist
                if not state.was_ever_seen:
                    continue

                # Table is currently in processlist - not stale
                if state.name in tables_in_processlist:
                    continue

                # Table was seen but is no longer in processlist
                time_since_seen = now - state.last_seen_in_processlist

                # Mark complete if has file completions OR stale timeout exceeded
                if state.files_completed > 0 or time_since_seen > _STALE_TABLE_TIMEOUT_SECONDS:
                    state.is_complete = True
                    state.percent_complete = 100.0
                    state.phase = "complete"
                    self._tables_completed.add(state.name)
                    logger.info(
                        f"Table {state.name} complete: left processlist "
                        f"({state.files_completed} files, {time_since_seen:.1f}s ago)"
                    )

            self._emit_progress("processlist")

    def update_from_myloader_line(self, line: str) -> None:
        """Update progress from myloader stdout line.

        Called for each line of myloader output. Detects completion events
        and marks tables as done.

        Args:
            line: Single line from myloader stdout/stderr.
        """
        # Check for file completion
        table_name = self._extract_completed_table(line)
        if table_name:
            self.mark_table_file_complete(table_name)

    def mark_table_file_complete(self, table_name: str) -> None:
        """Mark a table's data file as complete.

        Called when myloader finishes restoring a file. For chunked tables,
        this may be called multiple times (once per chunk). We track file
        completions and use processlist disappearance to confirm full completion.

        Args:
            table_name: Table name from myloader output.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                logger.debug(f"Ignoring completion for unknown table: {table_name}")
                return

            if state.is_complete:
                return

            # Track file completions
            state.files_completed += 1
            logger.debug(
                f"File completed for table {bare_name}: "
                f"{state.files_completed} files done"
            )

            # Emit progress event for this file completion
            self._emit_progress("file_complete")

    def mark_table_complete(self, table_name: str) -> None:
        """Explicitly mark a table as fully complete.

        Args:
            table_name: Table name to mark complete.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                return

            if not state.is_complete:
                state.is_complete = True
                state.percent_complete = 100.0
                state.phase = "complete"
                self._tables_completed.add(bare_name)
                logger.debug(f"Table marked complete: {bare_name}")

                self._emit_progress("file_complete")

    def get_progress(self) -> RestoreProgress:
        """Get current progress snapshot.

        Returns:
            Immutable RestoreProgress snapshot, safe to use across threads.
        """
        with self._lock:
            return self._build_progress_snapshot("processlist")

    def finalize(self) -> RestoreProgress:
        """Finalize progress when myloader exits.

        Called after myloader completes successfully. Marks all tables as
        complete (myloader wouldn't exit if tables were incomplete).

        Returns:
            Final progress snapshot with all tables complete.
        """
        with self._lock:
            # Any table still "in progress" is actually done
            for state in self._tables.values():
                if not state.is_complete:
                    state.is_complete = True
                    state.percent_complete = 100.0
                    state.phase = "complete"
                    self._tables_completed.add(state.name)

            progress = self._build_progress_snapshot("finalized")

            logger.info(
                "Finalized progress: %d/%d tables, %s/%s rows",
                progress.tables_completed,
                progress.tables_total,
                f"{progress.rows_loaded:,}",
                f"{progress.rows_total:,}",
            )

            # Always emit final progress
            if self._on_progress:
                self._on_progress(progress)

            return progress

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _normalize_table_name(self, name: str) -> str:
        """Normalize table name by removing database prefix and file extensions.

        Args:
            name: Table name possibly with db prefix or file suffix.

        Returns:
            Bare table name.
        """
        # Remove file path/extension if present
        if "/" in name:
            name = Path(name).name
        if ".sql" in name:
            # Handle "database.table.00000.sql.gz" format
            # Min parts for db.table format
            min_db_table_parts = 2
            stripped = name.replace(".sql.gz", "")
            stripped = stripped.replace(".sql.zst", "")
            stripped = stripped.replace(".sql", "")
            parts = stripped.split(".")
            if len(parts) >= min_db_table_parts:
                # Usually "db.table" or "db.table.chunk"
                return parts[1] if parts[0] != parts[1] else parts[0]
            return parts[0]

        # Handle "db.table" format
        if "." in name:
            parts = name.split(".")
            # Return the table part (second element)
            return parts[-1] if len(parts) > 1 else name

        return name

    def _extract_completed_table(self, line: str) -> str | None:
        """Extract table name from myloader completion line.

        Args:
            line: Myloader stdout line.

        Returns:
            Table name if line indicates completion, None otherwise.
        """
        # Check verbose output first
        if match := self._RE_VERBOSE_RESTORE.search(line):
            return match.group(1).strip()

        # Check standard format
        if match := self._RE_FINISHED.search(line):
            return match.group(1).strip()

        return None

    def _calculate_rows_loaded(self) -> int:
        """Calculate total rows loaded across all tables."""
        total = 0
        for state in self._tables.values():
            if state.is_complete:
                total += state.rows_total
            else:
                # Use percent_complete from processlist
                total += int(state.percent_complete / 100.0 * state.rows_total)
        return total

    def _build_progress_snapshot(
        self, source: Literal["processlist", "file_complete", "finalized"]
    ) -> RestoreProgress:
        """Build immutable progress snapshot from current state.

        Must be called while holding _lock.
        """
        rows_loaded = self._calculate_rows_loaded()
        elapsed = time.monotonic() - self._start_time
        rps = int(rows_loaded / elapsed) if elapsed > 0 else 0
        remaining = self._total_rows - rows_loaded
        eta = int(remaining / rps) if rps > 0 else None

        # Build list of in-progress tables
        # For "finalized" source, include all tables that had progress
        # For normal updates, only include tables currently active (in processlist recently)
        in_progress: list[TableProgressInfo] = []
        now = time.monotonic()
        
        for state in self._tables.values():
            include_table = False
            
            if source == "finalized":
                # Include all tables that had any progress (now 100%)
                include_table = state.rows_total > 0
            else:
                # Normal: only include tables that are:
                # 1. Not complete AND
                # 2. Currently in processlist (seen within last poll interval) OR
                # 3. Were recently active (for brief gaps between processlist polls)
                if not state.is_complete and state.was_ever_seen:
                    time_since_seen = now - state.last_seen_in_processlist
                    # Show if seen within last 5 seconds (allows for poll interval gaps)
                    include_table = time_since_seen < 5.0

            if include_table:
                table_rows = int(
                    state.percent_complete / 100.0 * state.rows_total
                )
                in_progress.append(
                    TableProgressInfo(
                        name=state.name,
                        percent_complete=state.percent_complete,
                        phase=state.phase,  # type: ignore[arg-type]
                        rows_loaded=table_rows,
                        rows_total=state.rows_total,
                        running_seconds=state.running_seconds,
                        is_complete=state.is_complete,
                    )
                )

        percent = rows_loaded / self._total_rows * 100 if self._total_rows > 0 else 0.0

        return RestoreProgress(
            percent_complete=min(100.0, percent),
            tables_total=self._total_tables,
            tables_completed=len(self._tables_completed),
            tables_in_progress=tuple(in_progress),
            rows_loaded=rows_loaded,
            rows_total=self._total_rows,
            throughput=ThroughputStats(
                rows_per_second=rps,
                elapsed_seconds=elapsed,
                eta_seconds=eta,
            ),
            timestamp=datetime.now(UTC),
            source=source,
        )

    def _emit_progress(
        self, source: Literal["processlist", "file_complete", "finalized"]
    ) -> None:
        """Emit progress if throttle allows.

        Must be called while holding _lock.
        """
        if not self._on_progress:
            return

        now = time.monotonic()
        time_since_emit = now - self._last_emit_time
        if self._throttle_interval > 0 and time_since_emit < self._throttle_interval:
            return

        self._last_emit_time = now
        progress = self._build_progress_snapshot(source)
        self._on_progress(progress)


# =============================================================================
# Factory Function
# =============================================================================


def create_progress_tracker(
    table_metadata: list[TableRowEstimate],
    progress_callback: Callable[[float, dict], None] | None = None,
) -> RestoreProgressTracker:
    """Create a RestoreProgressTracker with compatible callback.

    This is a convenience factory that wraps the new RestoreProgress format
    into the old (percent, detail_dict) callback format for backwards compatibility.

    Args:
        table_metadata: List of tables with row estimates.
        progress_callback: Old-style callback receiving (percent, detail_dict).

    Returns:
        Configured RestoreProgressTracker instance.
    """
    if progress_callback is None:
        return RestoreProgressTracker(table_metadata=table_metadata)

    def on_progress(p: RestoreProgress) -> None:
        event_dict = p.to_event_dict()
        progress_callback(event_dict["percent"], event_dict["detail"])

    return RestoreProgressTracker(
        table_metadata=table_metadata,
        on_progress=on_progress,
    )
