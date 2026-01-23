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
        phase: Current phase - 'loading', 'indexing', or 'analyzing'.
        rows_loaded: Estimated rows loaded so far.
        rows_total: Total rows expected for this table.
        running_seconds: Time this table has been in current phase.
        is_complete: Whether this table is fully restored.
    """

    name: str
    percent_complete: float
    phase: Literal["loading", "indexing", "analyzing", "complete"]
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
            'finalized', 'analyzing_started', 'analyzing_complete').
    """

    percent_complete: float
    tables_total: int
    tables_completed: int
    tables_in_progress: tuple[TableProgressInfo, ...]
    rows_loaded: int
    rows_total: int
    throughput: ThroughputStats
    timestamp: datetime
    source: Literal[
        "processlist",
        "file_complete",
        "finalized",
        "analyzing_started",
        "analyzing_complete",
    ]

    def to_event_dict(self) -> dict:
        """Convert to dict format for event emission.

        Returns:
            Dict compatible with existing restore_progress event format.
        """
        status = "processlist_update" if self.source == "processlist" else "finished"
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
    file_count: int = 1  # Total data files for this table
    percent_complete: float = 0.0
    phase: str = "loading"  # 'loading', 'indexing', 'analyzing', 'complete'
    running_seconds: float = 0.0
    is_complete: bool = False
    last_seen_in_processlist: float = 0.0
    files_completed: int = 0  # Track how many chunk files have finished
    was_ever_seen: bool = False  # Track if table was ever in processlist
    first_seen_time: float = 0.0  # When table was first seen (for duration calc)


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
    # Myloader output format varies by version:
    #   0.9: "** Message: 15:50:48.537: Thread 7 restoring `db`.`table` part 0"
    #   0.19: "Thread 5: Enqueuing index for table: db.table"
    #
    # All patterns allow optional "** Message: HH:MM:SS.mmm: " prefix

    # Match "Thread N finished restoring" for file completion
    _RE_FINISHED = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?(?:Thread \d+|Message: Thread \d+) finished restoring (\S+)"
    )

    # Match "Thread N restoring `db`.`table` part N" - table data started loading
    # Captures table name from backtick-quoted format
    _RE_VERBOSE_RESTORE = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?Thread \d+(?: restoring| shutting down)"
        r"(?:\s+`[^`]+`\.`([^`]+)`(?:\s+part \d+)?)?",
        re.IGNORECASE,
    )

    # Definitive signal that data loading is complete for a table
    # Message: "Thread N: Enqueuing index for table: staging_db.tablename"
    # Also matches: "** Message: 06:02:20.155: Thread 0: Enqueuing index for table: db.table"
    _RE_ENQUEUE_INDEX = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?Thread\s+\d+:\s+Enqueuing index for table:\s+"
        r"(?:`?([^`.\s]+)`?\.`?([^`\s]+)`?|([^\s.]+)\.([^\s]+))",
        re.IGNORECASE,
    )

    # Signal that index rebuild has started
    # Message: "restoring index: staging_db.tablename"
    _RE_RESTORING_INDEX = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?restoring index:\s+"
        r"(?:`?([^`.\s]+)`?\.`?([^`\s]+)`?|([^\s.]+)\.([^\s]+))",
        re.IGNORECASE,
    )

    # Match table file completion from verbose output
    # "** Message: 15:54:59.179: Thread 5 restoring `db`.`table` part 0" followed by next table
    # indicates previous table file is done
    _RE_TABLE_PART_RESTORE = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?Thread \d+ restoring `[^`]+`\.`([^`]+)`(?:\s+part (\d+))?",
        re.IGNORECASE,
    )

    def __init__(
        self,
        table_metadata: list[TableRowEstimate],
        on_progress: Callable[[RestoreProgress], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
        throttle_interval_seconds: float = 0.5,
    ) -> None:
        """Initialize tracker.

        Args:
            table_metadata: List of tables with row estimates from backup metadata.
            on_progress: Optional callback invoked on each progress update.
                Receives immutable RestoreProgress snapshot.
            on_event: Optional callback for file/table completion events.
                Called with (event_type: str, event_data: dict).
            throttle_interval_seconds: Minimum interval between progress emissions.
                Prevents flooding with too many events. Set to 0 to disable.
        """
        self._lock = threading.RLock()  # Reentrant for nested calls
        self._on_progress = on_progress
        self._on_event = on_event
        self._throttle_interval = throttle_interval_seconds
        self._last_emit_time: float = 0.0
        self._start_time = time.monotonic()

        # Immutable setup
        self._total_tables = len(table_metadata)
        self._total_rows = sum(t.rows for t in table_metadata)
        self._table_rows: dict[str, int] = {t.table: t.rows for t in table_metadata}
        self._table_file_counts: dict[str, int] = {
            t.table: t.file_count for t in table_metadata
        }

        # Mutable state
        self._tables: dict[str, _MutableTableState] = {}
        self._tables_completed: set[str] = set()
        self._tables_in_processlist: set[str] = set()  # Currently active in processlist

        # De-duplication for events (prevent identical events)
        self._emitted_file_events: set[tuple[str, int]] = set()  # (table, file_index)
        self._emitted_table_ready: set[str] = set()  # table names

        # Initialize table states
        for t in table_metadata:
            self._tables[t.table] = _MutableTableState(
                name=t.table,
                rows_total=t.rows,
                file_count=t.file_count,
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
                # Track first time table is seen for duration calculation
                if not state.was_ever_seen:
                    state.first_seen_time = now
                state.was_ever_seen = True

            # Store current processlist tables for UI display
            self._tables_in_processlist = tables_in_processlist

            # Check for tables that have left processlist
            # Mark complete if: was seen before, not in processlist now, and either:
            #   - has file completions (myloader confirmed), OR
            #   - has been gone for > stale timeout (likely complete)
            # BUT: don't mark complete if table is in indexing phase - it may be
            #      between data thread ending and ALTER TABLE starting
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

                # Handle indexing tables specially - they may briefly leave
                # processlist between data thread ending and ALTER starting.
                # Only mark complete if gone for > 3 seconds.
                if state.phase == "indexing":
                    if time_since_seen > 3.0:
                        # Indexing finished - table is complete
                        self._mark_table_complete(state, now)
                        logger.info(
                            f"Table {state.name} complete: indexing finished "
                            f"(left processlist {time_since_seen:.1f}s ago)"
                        )
                    continue

                # Mark complete if has file completions OR stale timeout exceeded
                if (
                    state.files_completed > 0
                    or time_since_seen > _STALE_TABLE_TIMEOUT_SECONDS
                ):
                    self._mark_table_complete(state, now)
                    logger.info(
                        f"Table {state.name} complete: left processlist "
                        f"({state.files_completed} files, {time_since_seen:.1f}s ago)"
                    )

            self._emit_progress("processlist")

    def _mark_table_complete(self, state: _MutableTableState, now: float) -> None:
        """Mark a table as complete and emit table_restore_complete event.

        Args:
            state: Table state to mark complete.
            now: Current monotonic time.
        """
        state.is_complete = True
        state.percent_complete = 100.0
        state.phase = "complete"
        self._tables_completed.add(state.name)

        # Emit table_restore_complete event with full stats
        if self._on_event:
            # Calculate duration from first seen to now
            duration_seconds = 0.0
            if state.first_seen_time > 0:
                duration_seconds = now - state.first_seen_time

            # Calculate rows per second
            rows_per_second = 0
            if duration_seconds > 0:
                rows_per_second = int(state.rows_total / duration_seconds)

            self._on_event(
                "table_restore_complete",
                {
                    "table": state.name,
                    "rows": state.rows_total,
                    "duration_seconds": round(duration_seconds, 1),
                    "rows_per_second": rows_per_second,
                },
            )

    def update_from_myloader_line(self, line: str) -> None:
        """Update progress from myloader stdout line.

        Called for each line of myloader output. Detects:
        - Table restore start (tracking which tables are being worked on)
        - Index enqueue (data 100% complete for table)
        - Index restore start (indexing phase began)

        Args:
            line: Single line from myloader stdout/stderr.
        """
        # Check for "Enqueuing index" = data load complete, entering indexing
        if match := self._RE_ENQUEUE_INDEX.search(line):
            # Pattern has 4 groups: (backtick_db, backtick_table, plain_db, plain_table)
            # Either groups 1,2 or groups 3,4 will have values
            table_name = match.group(2) or match.group(4)
            if table_name:
                self._mark_data_complete(table_name)
            return

        # Check for "restoring index" = index rebuild actively running
        if match := self._RE_RESTORING_INDEX.search(line):
            # Same pattern structure as ENQUEUE_INDEX
            table_name = match.group(2) or match.group(4)
            if table_name:
                self._mark_indexing_started(table_name)
            return

        # Check for table data file restore started
        # This helps track which tables are being worked on even before processlist updates
        if match := self._RE_TABLE_PART_RESTORE.search(line):
            table_name = match.group(1)
            if table_name:
                # Mark that we've seen this table being restored
                self._mark_table_restore_started(table_name)
            return

        # Check for file completion (less reliable but useful for progress)
        table_name = self._extract_completed_table(line)
        if table_name:
            self.mark_table_file_complete(table_name)

    def _mark_table_restore_started(self, table_name: str) -> None:
        """Mark that a table restore has started from myloader verbose output.

        This is called when myloader emits "Thread N restoring `db`.`table` part N".
        It helps track table activity even before processlist updates.

        Args:
            table_name: Table name being restored.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                return

            if state.is_complete:
                return

            # Mark table as active if not already
            if not state.was_ever_seen:
                state.was_ever_seen = True
                state.last_seen_in_processlist = time.monotonic()
                logger.debug(f"Table {bare_name}: restore started from myloader output")

    def _mark_data_complete(self, table_name: str) -> None:
        """Mark table's data load as 100% complete, entering indexing phase.

        Called when myloader emits 'Enqueuing index for table'.
        This is the definitive signal that all data chunks are loaded.

        Args:
            table_name: Table name from myloader output.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                logger.debug(f"Ignoring enqueue for unknown table: {table_name}")
                return

            if state.is_complete:
                return

            # Data is 100% complete, now entering indexing phase
            state.percent_complete = 100.0
            state.phase = "indexing"
            files_loaded = state.files_completed
            file_count = state.file_count
            logger.info(
                f"Table {bare_name}: data complete "
                f"({files_loaded}/{file_count} files), indexes queued"
            )

            # Emit table ready event (de-duplicated)
            if self._on_event and bare_name not in self._emitted_table_ready:
                self._emitted_table_ready.add(bare_name)
                self._on_event(
                    "restore_table_ready",
                    {
                        "table": bare_name,
                        "files_loaded": files_loaded,
                        "file_count": file_count,
                    },
                )

            self._emit_progress("file_complete")

    def _mark_indexing_started(self, table_name: str) -> None:
        """Mark table as actively rebuilding indexes.

        Called when myloader emits 'restoring index: db.table'.
        This message indicates data load is complete and indexing is underway.

        NOTE: myloader 0.19 does NOT emit "Enqueuing index" messages, so this
        is often the first signal that data loading finished. We emit
        restore_table_ready here if not already emitted.

        Args:
            table_name: Table name from myloader output.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                # Table not in tracker - this is normal for empty/schema-only tables
                # which have no data rows but still have indexes to restore.
                # We can still emit the event with file counts of 0.
                if self._on_event and bare_name not in self._emitted_table_ready:
                    self._emitted_table_ready.add(bare_name)
                    self._on_event(
                        "restore_table_ready",
                        {
                            "table": bare_name,
                            "files_loaded": 0,
                            "file_count": 0,
                        },
                    )
                return

            if state.is_complete:
                return

            # Ensure we're in indexing phase
            if state.phase != "indexing":
                state.percent_complete = 100.0
                state.phase = "indexing"
                logger.info(f"Table {bare_name}: indexing started (data complete)")

            # Emit restore_table_ready if not already emitted
            # This handles myloader 0.19 which skips "Enqueuing index" messages
            if self._on_event and bare_name not in self._emitted_table_ready:
                self._emitted_table_ready.add(bare_name)
                files_loaded = state.files_completed
                file_count = state.file_count
                self._on_event(
                    "restore_table_ready",
                    {
                        "table": bare_name,
                        "files_loaded": files_loaded,
                        "file_count": file_count,
                    },
                )

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
            file_index = state.files_completed  # 1-based
            file_count = state.file_count

            logger.debug(
                f"File completed for table {bare_name}: "
                f"{file_index} of {file_count} files done"
            )

            # Emit file completion event (de-duplicated)
            event_key = (bare_name, file_index)
            if self._on_event and event_key not in self._emitted_file_events:
                self._emitted_file_events.add(event_key)
                self._on_event(
                    "restore_file_loaded",
                    {
                        "table": bare_name,
                        "file_index": file_index,
                        "file_count": file_count,
                    },
                )

            # Emit progress event for this file completion
            self._emit_progress("file_complete")

    def mark_table_complete(self, table_name: str) -> None:
        """Explicitly mark a table as fully complete.

        Args:
            table_name: Table name to mark complete.
        """
        bare_name = self._normalize_table_name(table_name)
        now = time.monotonic()

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                return

            if not state.is_complete:
                self._mark_table_complete(state, now)
                logger.debug(f"Table marked complete: {bare_name}")

                self._emit_progress("file_complete")

    def mark_table_analyzing(self, table_name: str) -> None:
        """Mark a table as being analyzed (ANALYZE TABLE).

        Called when EarlyAnalyzeWorker starts analyzing a table.
        This transitions the table from 'indexing' phase to 'analyzing' phase.

        Args:
            table_name: Table name to mark as analyzing.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                # Table not tracked (e.g., schema-only or already removed)
                # Create a minimal state to track analyzing phase
                state = _MutableTableState(
                    name=bare_name,
                    rows_total=0,
                    percent_complete=99.0,
                    phase="analyzing",
                    is_complete=False,
                    first_seen_time=time.monotonic(),
                )
                self._tables[bare_name] = state
                logger.debug(f"Created state for analyzing table: {bare_name}")
                self._emit_progress("analyzing_started")
                return

            if state.is_complete:
                # Already complete - don't revert
                return

            state.phase = "analyzing"
            state.percent_complete = 99.0  # Show indeterminate progress
            logger.debug(f"Table {bare_name}: entering analyzing phase")
            self._emit_progress("analyzing_started")

    def mark_table_analyze_complete(self, table_name: str) -> None:
        """Mark a table's ANALYZE as complete.

        Called when EarlyAnalyzeWorker finishes analyzing a table.
        This marks the table as fully complete.

        Args:
            table_name: Table name to mark as analyze complete.
        """
        bare_name = self._normalize_table_name(table_name)
        now = time.monotonic()

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                return

            if not state.is_complete:
                self._mark_table_complete(state, now)
                logger.debug(f"Table analyze complete: {bare_name}")

                self._emit_progress("analyzing_complete")

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
        now = time.monotonic()
        with self._lock:
            # Any table still "in progress" is actually done
            for state in self._tables.values():
                if not state.is_complete:
                    self._mark_table_complete(state, now)

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
        self,
        source: Literal[
            "processlist",
            "file_complete",
            "finalized",
            "analyzing_started",
            "analyzing_complete",
        ],
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
        # For normal updates, ONLY include tables currently in processlist
        in_progress: list[TableProgressInfo] = []

        for state in self._tables.values():
            include_table = False

            if source == "finalized":
                # Include all tables that had any progress (now 100%)
                include_table = state.rows_total > 0
            else:
                # Normal: ONLY include tables with active threads in processlist
                include_table = state.name in self._tables_in_processlist

            if include_table:
                table_rows = int(state.percent_complete / 100.0 * state.rows_total)
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
        self,
        source: Literal[
            "processlist",
            "file_complete",
            "finalized",
            "analyzing_started",
            "analyzing_complete",
        ],
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
    event_callback: Callable[[str, dict], None] | None = None,
) -> RestoreProgressTracker:
    """Create a RestoreProgressTracker with compatible callback.

    This is a convenience factory that wraps the new RestoreProgress format
    into the old (percent, detail_dict) callback format for backwards compatibility.

    Args:
        table_metadata: List of tables with row estimates.
        progress_callback: Old-style callback receiving (percent, detail_dict).
        event_callback: Optional callback for file/table completion events.
            Called with (event_type: str, event_data: dict).

    Returns:
        Configured RestoreProgressTracker instance.
    """
    if progress_callback is None:
        return RestoreProgressTracker(
            table_metadata=table_metadata,
            on_event=event_callback,
        )

    def on_progress(p: RestoreProgress) -> None:
        event_dict = p.to_event_dict()
        progress_callback(event_dict["percent"], event_dict["detail"])

    return RestoreProgressTracker(
        table_metadata=table_metadata,
        on_progress=on_progress,
        on_event=event_callback,
    )
