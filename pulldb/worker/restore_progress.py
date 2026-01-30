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

    Supports three modes (in order of preference):
    1. Row-based: When row counts are available from backup metadata
    2. Bytes-based: When file sizes are available (most accurate for ETA)
    3. File-based: Fallback when neither rows nor bytes available

    Note: ETA only covers data loading phase. The indexing phase
    (which can be substantial for large tables) is not included.

    Attributes:
        rows_per_second: Current restore throughput (rows/s).
        elapsed_seconds: Time since restore started.
        eta_seconds: Estimated seconds remaining (None if cannot estimate).
        eta_mode: How ETA was calculated - 'rows', 'bytes', 'files', or None.
        bytes_per_second: Bandwidth in bytes/sec (compressed file size basis).
        bytes_completed: Total compressed bytes loaded.
        bytes_total: Total compressed bytes to restore.
        files_per_second: File completion rate.
        files_completed: Total files completed across all tables.
        files_total: Total files to restore.
    """

    rows_per_second: int
    elapsed_seconds: float
    eta_seconds: int | None
    eta_mode: Literal["rows", "bytes", "files"] | None = None
    bytes_per_second: float = 0.0
    bytes_completed: int = 0
    bytes_total: int = 0
    files_per_second: float = 0.0
    files_completed: int = 0
    files_total: int = 0


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
                "eta_mode": self.throughput.eta_mode,
                "bytes_per_second": round(self.throughput.bytes_per_second, 0),
                "bytes_completed": self.throughput.bytes_completed,
                "bytes_total": self.throughput.bytes_total,
                "files_per_second": round(self.throughput.files_per_second, 2),
                "files_completed": self.throughput.files_completed,
                "files_total": self.throughput.files_total,
                "tables_completed": self.tables_completed,
                "tables_total": self.tables_total,
            },
        }


# =============================================================================
# Internal Mutable State
# =============================================================================


@dataclass
class _MutableTableState:
    """Internal mutable state for a single table.
    
    Phase Lifecycle:
        pending → loading → indexing → analyzing → complete
    
    Completion Model (Conservative):
        - is_complete is ONLY set when we have POSITIVE confirmation
        - Strike-based detection is used for INDEX phase only (after data_complete)
        - A table must pass through analyze phase (if enabled) before is_complete=True
        - finalize() is the ONLY path to mark tables complete in batch
    """

    name: str
    rows_total: int
    file_count: int = 1  # Total data files for this table
    total_bytes: int = 0  # Total compressed size of data files
    percent_complete: float = 0.0
    phase: str = "loading"  # 'loading', 'indexing', 'analyzing', 'complete'
    running_seconds: float = 0.0
    is_complete: bool = False
    last_seen_in_processlist: float = 0.0
    files_completed: int = 0  # Track how many chunk files have finished
    files_started: int = 0  # Track how many chunk files have started (for file-based progress)
    data_complete: bool = False  # True when "Enqueuing index" received (definitive)
    index_complete: bool = False  # True when indexes done (strike-based after data_complete)
    analyze_complete: bool = False  # True when ANALYZE TABLE finished
    analyze_skipped: bool = False  # True if early analyze is disabled for this table
    was_ever_seen: bool = False  # Track if table was ever in processlist
    first_seen_time: float = 0.0  # When table was first seen (for duration calc)
    absent_strikes: int = 0  # Consecutive polls where table was absent from processlist


# =============================================================================
# Phase Weighting for Progress Display
# =============================================================================
# Progress is weighted by phase to prevent premature 100% display:
# - Data loading phase: contributes up to 85% of progress
# - Index rebuild phase: contributes the remaining 15%
# This ensures overall progress doesn't reach 100% while indexes are building.

DATA_PHASE_WEIGHT = 0.85  # Data loading = 85% of total progress
INDEX_PHASE_WEIGHT = 0.15  # Index rebuild = 15% of total progress


# =============================================================================
# Strike-based Completion Detection
# =============================================================================
# We use a "3 strikes" approach to detect table completion:
# - A "strike" = one poll cycle where table is absent from processlist
# - When table reappears (e.g., next FULLTEXT ALTER), strikes reset to 0
# - After N consecutive strikes, mark table complete
#
# This naturally handles:
# - FULLTEXT indexes: myloader runs separate ALTER per FULLTEXT, table briefly
#   leaves processlist between them, reappears → strikes reset
# - Normal indexes: single ALTER, table leaves once → strikes accumulate
# - Random file order: data files processed randomly, table may reappear → reset
#
# Poll interval is 2s, so 3 strikes = 6s minimum absence.

# Strikes required after data_complete ("Enqueuing index" received).
# Table is in indexing phase, just need to confirm indexes are done.
# 3 strikes = 6s at 2s poll interval - enough for gaps between FULLTEXT ALTERs.
_INDEX_COMPLETE_STRIKES = 3

# Strikes required when no data_complete signal (fallback).
# We're less certain data is done, so require more consecutive absences.
# 5 strikes = 10s at 2s poll interval.
_FALLBACK_COMPLETE_STRIKES = 5


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

    # Authoritative signal that myloader completed successfully
    # Message: "Restore completed"
    _RE_RESTORE_COMPLETED = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?Restore completed",
        re.IGNORECASE,
    )

    # Match "Thread N: Creating table db.table" - schema creation started
    # Message: "Thread 5: Creating table db.table from content in filename. On db: source_db"
    _RE_CREATING_TABLE = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?Thread\s+\d+:\s+Creating table\s+"
        r"(?:`?([^`\s.]+)`?\.`?([^`\s]+)`?|([^\s.]+)\.([^\s]+))",
        re.IGNORECASE,
    )

    # Match "Thread N: Table db.table created" - schema creation completed
    # Message: "Thread 5: Table db.table created. Tables that pass created stage: 3 of 10"
    _RE_TABLE_CREATED = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?Thread\s+\d+:\s+Table\s+"
        r"(?:`?([^`\s.]+)`?\.`?([^`\s]+)`?|([^\s.]+)\.([^\s]+))\s+created",
        re.IGNORECASE,
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

    # Match "Progress X of Y" with full file details for file-based progress
    # Message: "Thread N: restoring db.table part X of Y from filename | Progress A of B. Tables C of D completed"
    # This is printed BEFORE file processing starts, so it tracks file STARTS not completions
    _RE_PROGRESS_FILE = re.compile(
        r"(?:\*\* Message: [\d:.]+: )?Thread\s+\d+:\s+restoring\s+"
        r"(?:`?([^`\s.]+)`?\.`?([^`\s]+)`?|([^\s.]+)\.([^\s]+))\s+"
        r"part\s+(\d+)\s+of\s+(\d+)\s+from\s+[^|]+\|\s*"
        r"Progress\s+(\d+)\s+of\s+(\d+)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        table_metadata: list[TableRowEstimate],
        on_progress: Callable[[RestoreProgress], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
        throttle_interval_seconds: float = 0.5,
        early_analyze_enabled: bool = False,
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
            early_analyze_enabled: If True, tables are NOT marked complete until
                analyze phase finishes. This prevents premature 100% progress.
        """
        self._lock = threading.RLock()  # Reentrant for nested calls
        self._on_progress = on_progress
        self._on_event = on_event
        self._throttle_interval = throttle_interval_seconds
        self._last_emit_time: float = 0.0
        self._start_time = time.monotonic()
        self._early_analyze_enabled = early_analyze_enabled

        # Immutable setup
        self._total_tables = len(table_metadata)
        self._total_rows = sum(t.rows for t in table_metadata)
        self._total_files = sum(t.file_count for t in table_metadata)
        self._total_bytes = sum(t.total_bytes for t in table_metadata)
        self._table_rows: dict[str, int] = {t.table: t.rows for t in table_metadata}
        self._table_file_counts: dict[str, int] = {
            t.table: t.file_count for t in table_metadata
        }
        self._table_bytes: dict[str, int] = {
            t.table: t.total_bytes for t in table_metadata
        }

        # Mutable state
        self._tables: dict[str, _MutableTableState] = {}
        self._tables_completed: set[str] = set()
        self._tables_in_processlist: set[str] = set()  # Currently active in processlist

        # De-duplication for events (prevent identical events)
        self._emitted_file_events: set[tuple[str, int]] = set()  # (table, file_index)
        self._emitted_table_ready: set[str] = set()  # table names
        self._emitted_schema_creating: set[str] = set()  # tables with schema creating emitted
        self._emitted_schema_created: set[str] = set()  # tables with schema created emitted
        self._emitted_indexing_started: set[str] = set()  # tables with indexing_started emitted

        # Indexing progress event throttling (max every 5s to avoid spam)
        self._indexing_emit_interval = 5.0
        self._last_indexing_emit: float = 0.0

        # Track authoritative completion signal from myloader
        self._myloader_restore_completed: bool = False

        # Initialize table states
        for t in table_metadata:
            self._tables[t.table] = _MutableTableState(
                name=t.table,
                rows_total=t.rows,
                file_count=t.file_count,
                total_bytes=t.total_bytes,
            )

        logger.info(
            f"Initialized progress tracker: {self._total_tables} tables, "
            f"{self._total_rows:,} total rows, {self._total_bytes / 1024 / 1024:.1f} MB"
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

            # Check for tables that have left processlist using STRIKE-BASED detection
            # 
            # IMPORTANT: Do NOT use files_started/files_completed for completion!
            # myloader processes files in RANDOM order, so seeing some files done
            # doesn't mean the table won't appear in processlist again.
            #
            # Strike logic:
            # - Table in processlist → reset strikes to 0 (it's active)
            # - Table absent → increment strikes
            # - Strikes >= threshold → mark complete
            # This naturally handles FULLTEXT gaps (table reappears → reset)
            for state in self._tables.values():
                if state.is_complete:
                    continue

                # Skip tables never seen in processlist
                if not state.was_ever_seen:
                    continue

                # Table is currently in processlist - reset strikes
                if state.name in tables_in_processlist:
                    if state.absent_strikes > 0:
                        logger.debug(
                            f"Table {state.name} reappeared in processlist, "
                            f"resetting strikes (was {state.absent_strikes})"
                        )
                        state.absent_strikes = 0
                    continue

                # Table was seen but is no longer in processlist - increment strike
                state.absent_strikes += 1

                # Determine required strikes based on whether we have data_complete
                # NOTE: Strike detection marks INDEX phase complete.
                # Whether it also marks the TABLE complete depends on early_analyze_enabled:
                # - early_analyze_enabled=False: mark table complete (traditional behavior)
                # - early_analyze_enabled=True: emit index_complete event for analyze queueing
                if state.data_complete:
                    # CASE 1: We have the definitive "Enqueuing index" signal
                    # Data files are done, table is in indexing phase (or done)
                    required_strikes = _INDEX_COMPLETE_STRIKES
                    if state.absent_strikes >= required_strikes and not state.index_complete:
                        state.index_complete = True
                        state.percent_complete = 100.0  # Now truly complete
                        logger.info(
                            f"Table {state.name} INDEX phase complete: "
                            f"{state.absent_strikes} consecutive absent polls"
                        )
                        if self._early_analyze_enabled:
                            # Emit event to queue for early analyze
                            self._emit_index_complete(state, now)
                        else:
                            # Traditional: mark table fully complete
                            self._mark_table_complete(state, now)
                            logger.info(f"Table {state.name} complete (no early analyze)")
                else:
                    # CASE 2: No data_complete signal (stdout may have missed it)
                    # Require more strikes since we're less certain
                    # This marks both data_complete and index_complete
                    required_strikes = _FALLBACK_COMPLETE_STRIKES
                    if state.absent_strikes >= required_strikes and not state.index_complete:
                        state.data_complete = True
                        state.index_complete = True
                        logger.warning(
                            f"Table {state.name} INDEX phase complete via fallback "
                            f"({state.absent_strikes} strikes, no data_complete signal)"
                        )
                        if self._early_analyze_enabled:
                            # Emit event to queue for early analyze
                            self._emit_index_complete(state, now)
                        else:
                            # Traditional: mark table fully complete
                            self._mark_table_complete(state, now)
                            logger.info(f"Table {state.name} complete (fallback, no early analyze)")

            # Emit indexing events for tables in indexing phase
            self._emit_indexing_events(now)

            self._emit_progress("processlist")

    def _emit_indexing_events(self, now: float) -> None:
        """Emit indexing_started and indexing_progress events.

        - indexing_started: Emitted once per table when entering indexing phase
        - indexing_progress: Throttled every 5s showing all tables currently indexing

        Args:
            now: Current monotonic time.
        """
        if not self._on_event:
            return

        # Find all tables currently in indexing phase
        indexing_tables: list[_MutableTableState] = []
        for state in self._tables.values():
            if state.phase == "indexing" and not state.is_complete:
                indexing_tables.append(state)

                # Emit indexing_started once per table
                if state.name not in self._emitted_indexing_started:
                    self._emitted_indexing_started.add(state.name)
                    self._on_event(
                        "indexing_started",
                        {
                            "table": state.name,
                            "rows": state.rows_total,
                        },
                    )
                    logger.debug(f"Emitted indexing_started for {state.name}")

        # Emit throttled indexing_progress if we have indexing tables
        if indexing_tables and (now - self._last_indexing_emit) >= self._indexing_emit_interval:
            self._last_indexing_emit = now
            self._on_event(
                "indexing_progress",
                {
                    "count": len(indexing_tables),
                    "tables": [t.name for t in indexing_tables],
                },
            )
            logger.debug(f"Emitted indexing_progress for {len(indexing_tables)} tables")

    def _emit_index_complete(self, state: _MutableTableState, now: float) -> None:
        """Emit table_index_complete event when indexing finishes.

        This is emitted in early_analyze mode to trigger queueing for ANALYZE TABLE.
        Unlike table_restore_complete, this doesn't mean the table is fully done -
        it still needs to go through the analyze phase.

        Args:
            state: Table state that completed indexing.
            now: Current monotonic time.
        """
        if self._on_event:
            # Calculate duration from first seen to now
            duration_seconds = 0.0
            if state.first_seen_time > 0:
                duration_seconds = now - state.first_seen_time

            self._on_event(
                "table_index_complete",
                {
                    "table": state.name,
                    "rows": state.rows_total,
                    "duration_seconds": round(duration_seconds, 1),
                },
            )
            logger.debug(f"Emitted table_index_complete for {state.name}")

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
        - File start with Progress X of Y (for file-based progress tracking)
        - Table restore start (tracking which tables are being worked on)
        - Index enqueue (data 100% complete for table)
        - Index restore start (indexing phase began)

        Args:
            line: Single line from myloader stdout/stderr.
        """
        # Check for "Progress X of Y" with file details - PRIMARY for file-based progress
        # This message is printed BEFORE file processing, so it tracks file STARTS
        if match := self._RE_PROGRESS_FILE.search(line):
            # Groups: (bt_db, bt_table, plain_db, plain_table, part_num, part_total, progress, total)
            table_name = match.group(2) or match.group(4)
            part_num = int(match.group(5))
            part_total = int(match.group(6))
            if table_name:
                self._mark_file_started(table_name, part_num, part_total)
            return

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

        # Check for schema table creation started
        if match := self._RE_CREATING_TABLE.search(line):
            table_name = match.group(2) or match.group(4)
            if table_name:
                self._emit_schema_creating(table_name)
            return

        # Check for schema table created
        if match := self._RE_TABLE_CREATED.search(line):
            table_name = match.group(2) or match.group(4)
            if table_name:
                self._emit_schema_created(table_name)
            return

        # Check for authoritative "Restore completed" signal
        if self._RE_RESTORE_COMPLETED.search(line):
            self._myloader_restore_completed = True
            logger.info("Myloader reported: Restore completed")
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

    def _mark_file_started(
        self, table_name: str, part_num: int, part_total: int
    ) -> None:
        """Mark that a file/chunk has started restoring for file-based progress.

        Called when myloader emits "Progress X of Y" message which is printed
        BEFORE file processing begins. This tracks file STARTS for accurate
        progress calculation that cannot exceed 100%.

        Args:
            table_name: Table name from myloader output.
            part_num: Current part number (1-based from myloader).
            part_total: Total parts for this table.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                logger.debug(f"Ignoring file start for unknown table: {table_name}")
                return

            if state.is_complete or state.data_complete:
                return

            # Update file count if we learn more accurate info from myloader
            if part_total > 0 and part_total != state.file_count:
                logger.debug(
                    f"Table {bare_name}: updating file_count {state.file_count} -> {part_total}"
                )
                state.file_count = part_total

            # Track files started (part_num is 1-based, so part 1 means 1 file started)
            # Note: We use max() because messages may arrive out of order with threading
            state.files_started = max(state.files_started, part_num)

            # Mark table as active
            if not state.was_ever_seen:
                state.was_ever_seen = True
                state.first_seen_time = time.monotonic()
            state.last_seen_in_processlist = time.monotonic()

            logger.debug(
                f"Table {bare_name}: file {part_num}/{part_total} started, "
                f"files_started={state.files_started}"
            )

            # Emit progress when files start - this triggers UI to show the table
            self._emit_progress("file_complete")  # Reuse file_complete for throttling

    def _emit_schema_creating(self, table_name: str) -> None:
        """Emit event when myloader starts creating a table's schema.

        Called when myloader emits 'Thread N: Creating table db.table'.
        This provides visibility into the schema creation phase before data loading.

        Args:
            table_name: Table name being created.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            # De-duplicate events
            if bare_name in self._emitted_schema_creating:
                return
            self._emitted_schema_creating.add(bare_name)

            if self._on_event:
                self._on_event(
                    "schema_creating",
                    {
                        "table": bare_name,
                        "tables_total": self._total_tables,
                    },
                )
            logger.debug(f"Schema creating: {bare_name}")

    def _emit_schema_created(self, table_name: str) -> None:
        """Emit event when myloader finishes creating a table's schema.

        Called when myloader emits 'Thread N: Table db.table created'.
        This signals schema is ready and data loading can begin.

        Args:
            table_name: Table name that was created.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            # De-duplicate events
            if bare_name in self._emitted_schema_created:
                return
            self._emitted_schema_created.add(bare_name)

            tables_created = len(self._emitted_schema_created)
            if self._on_event:
                self._on_event(
                    "schema_created",
                    {
                        "table": bare_name,
                        "tables_created": tables_created,
                        "tables_total": self._total_tables,
                    },
                )
            logger.debug(
                f"Schema created: {bare_name} ({tables_created}/{self._total_tables})"
            )

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
            # Cap at 85% because indexing is still pending (DATA_PHASE_WEIGHT)
            state.data_complete = True  # Definitive: all files done
            state.percent_complete = DATA_PHASE_WEIGHT * 100.0  # 85% - indexing pending
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

            # Ensure we're in indexing phase with correct weighted percent
            if state.phase != "indexing":
                # Use DATA_PHASE_WEIGHT since indexing is still pending
                if not state.data_complete:
                    state.data_complete = True
                state.percent_complete = DATA_PHASE_WEIGHT * 100.0  # 85%
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
        This transitions the table to 'analyzing' phase.

        Lifecycle: loading → indexing → analyzing → complete
                                    ↑ YOU ARE HERE

        NOTE: This method intentionally re-activates tables that were marked
        complete by finalize(). The early analyze phase runs AFTER myloader
        exits, so tables need to transition: complete -> analyzing -> complete.

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
                    data_complete=True,  # Must be true to reach analyze
                    index_complete=True,  # Indexes done if we're analyzing
                    first_seen_time=time.monotonic(),
                )
                self._tables[bare_name] = state
                logger.debug(f"Created state for analyzing table: {bare_name}")
                self._emit_progress("analyzing_started")
                return

            # If we're entering analyze phase, index phase is definitively complete
            if not state.index_complete:
                state.index_complete = True
                state.data_complete = True  # Must also be true
                logger.debug(f"Table {bare_name}: index phase complete (entering analyze)")

            # Re-activate table for analyzing phase
            # This handles the case where finalize() was already called
            # (myloader exited) but early analyze is still running
            if state.is_complete:
                state.is_complete = False
                self._tables_completed.discard(bare_name)
                logger.info(f"Table {bare_name}: re-activated for analyzing phase")

            state.phase = "analyzing"
            state.percent_complete = 99.0  # Show near-complete progress
            logger.debug(f"Table {bare_name}: entering analyzing phase")
            self._emit_progress("analyzing_started")

    def mark_table_analyze_complete(self, table_name: str) -> None:
        """Mark a table's ANALYZE as complete.

        Called when EarlyAnalyzeWorker finishes analyzing a table.
        This marks the table as fully complete - the final step in the lifecycle.

        Lifecycle: loading → indexing → analyzing → complete
                                            ↑ YOU ARE HERE

        NOTE: This method does NOT call _mark_table_complete() because that would
        emit table_restore_complete, which could trigger re-queueing. The worker
        already emits table_analyze_complete which is the correct completion event.

        Args:
            table_name: Table name to mark as analyze complete.
        """
        bare_name = self._normalize_table_name(table_name)

        with self._lock:
            state = self._tables.get(bare_name)
            if state is None:
                return

            # Set analyze_complete flag and mark complete WITHOUT emitting
            # table_restore_complete (which would cause re-queueing loop)
            state.analyze_complete = True

            if not state.is_complete:
                # Mark complete directly without _mark_table_complete to avoid
                # emitting table_restore_complete event
                state.is_complete = True
                state.percent_complete = 100.0
                state.phase = "complete"
                self._tables_completed.add(bare_name)

                logger.info(
                    f"Table {bare_name} fully complete: "
                    f"data={state.data_complete}, index={state.index_complete}, "
                    f"analyze={state.analyze_complete}"
                )

                self._emit_progress("analyzing_complete")

    def finalize_analyze_phase(self) -> None:
        """Safety net: mark any tables stuck in 'analyzing' phase as complete.

        Called when early_analyze_worker times out or errors, to prevent
        tables from being stuck at 99% with is_complete=False forever.

        This is a graceful degradation - we lose the analyze tracking but
        the progress display won't show stuck tables.
        """
        now = time.monotonic()
        with self._lock:
            stuck_count = 0
            for state in self._tables.values():
                if state.phase == "analyzing" and not state.is_complete:
                    state.analyze_complete = True  # Mark as "done" even if not verified
                    self._mark_table_complete(state, now)
                    stuck_count += 1

            if stuck_count > 0:
                logger.warning(
                    f"Finalized {stuck_count} tables stuck in analyzing phase "
                    "(early analyze timeout/error)"
                )

    def get_progress(self) -> RestoreProgress:
        """Get current progress snapshot.

        Returns:
            Immutable RestoreProgress snapshot, safe to use across threads.
        """
        with self._lock:
            return self._build_progress_snapshot("processlist")

    @property
    def myloader_completed(self) -> bool:
        """Check if myloader emitted authoritative 'Restore completed' message.

        This is a definitive signal that myloader finished successfully,
        as opposed to inferring completion from processlist absence.

        Returns:
            True if 'Restore completed' was seen in myloader output.
        """
        return self._myloader_restore_completed

    def finalize(self) -> RestoreProgress:
        """Finalize progress when myloader exits.

        Called after myloader completes successfully.

        Behavior depends on early_analyze_enabled:
        - If False: Marks all tables as complete (traditional behavior)
        - If True: Marks tables as index_complete but NOT is_complete
          (tables will be marked complete by mark_table_analyze_complete)

        This ensures progress doesn't show 100% while analyze is still running.

        Returns:
            Final progress snapshot.
        """
        now = time.monotonic()
        with self._lock:
            for state in self._tables.values():
                if state.is_complete:
                    continue

                if self._early_analyze_enabled:
                    # Early analyze mode: mark index phase done, but wait for analyze
                    # Tables will be completed by mark_table_analyze_complete()
                    if not state.data_complete:
                        state.data_complete = True
                    if not state.index_complete:
                        state.index_complete = True
                        logger.debug(
                            f"Table {state.name}: index phase complete (finalized, "
                            f"awaiting analyze)"
                        )
                    # Set phase to "indexing" if not already analyzing
                    # (early_analyze may have already started on some tables)
                    if state.phase not in ("analyzing", "complete"):
                        state.phase = "indexing"
                        state.percent_complete = 99.0  # Near-complete, awaiting analyze
                else:
                    # Traditional mode: mark all tables complete
                    self._mark_table_complete(state, now)

            source = "finalized"
            progress = self._build_progress_snapshot(source)

            if self._early_analyze_enabled:
                logger.info(
                    "Finalized (early_analyze mode): %d/%d tables index-complete, "
                    "awaiting analyze phase",
                    sum(1 for s in self._tables.values() if s.index_complete),
                    self._total_tables,
                )
            else:
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
        # Check verbose output format:
        # "Thread N restoring `db`.`table` part N"
        if match := self._RE_VERBOSE_RESTORE.search(line):
            group = match.group(1)
            if group:
                return group.strip()

        return None

    def _calculate_rows_loaded(self) -> int:
        """Calculate total rows loaded across all tables.

        Uses PHASE-WEIGHTED progress to prevent premature 100% display:
        - is_complete or index_complete: 100% of rows (truly done)
        - data_complete only: 85% of rows (DATA_PHASE_WEIGHT) - indexing pending
        - In progress: proportional based on files or processlist

        This ensures overall progress doesn't reach 100% while indexes are building.
        """
        total = 0
        for state in self._tables.values():
            if state.is_complete or state.index_complete:
                # Table fully complete (data + indexes done)
                total += state.rows_total
            elif state.data_complete:
                # Data done, indexing pending - contribute 85%
                total += int(DATA_PHASE_WEIGHT * state.rows_total)
            elif state.files_started > 0 and state.file_count > 0:
                # File-based progress: use files_started / file_count
                # This cannot exceed 100% since files_started <= file_count
                file_percent = state.files_started / state.file_count
                total += int(file_percent * state.rows_total)
            else:
                # Fallback: processlist percent (already capped at 100% on input)
                total += int(state.percent_complete / 100.0 * state.rows_total)
        return total

    def _calculate_file_based_percent(self) -> float:
        """Calculate overall progress using file counts.

        Used when row counts are unavailable (legacy backups with rows=0).
        Progress = sum(files_started) / total_files across all tables.
        Tables with data_complete or is_complete count as all files done.
        """
        if self._total_files <= 0:
            return 0.0

        files_done = 0
        for state in self._tables.values():
            if state.is_complete or state.data_complete:
                # All files for this table are done
                files_done += state.file_count
            else:
                # Count files started (files_started tracks how many began processing)
                files_done += state.files_started

        return min(100.0, (files_done / self._total_files) * 100)

    def _calculate_files_completed(self) -> int:
        """Calculate total files COMPLETED across all tables.

        Different from _calculate_file_based_percent which uses files_started.
        This counts only actually completed files, used for throughput/ETA.

        Returns:
            Number of data files that have finished loading.
        """
        files_done = 0
        for state in self._tables.values():
            if state.is_complete or state.data_complete:
                # All files for this table are done
                files_done += state.file_count
            else:
                # Only count actually completed files (not in-progress)
                files_done += state.files_completed
        return files_done

    def _calculate_bytes_completed(self) -> int:
        """Calculate total bytes COMPLETED across all tables.

        Uses file completion to estimate bytes loaded. When a table has
        data_complete or is_complete, all its bytes are counted.
        Otherwise, uses (files_completed / file_count) * total_bytes.

        Returns:
            Estimated bytes loaded (compressed file size basis).
        """
        bytes_done = 0
        for state in self._tables.values():
            if state.is_complete or state.data_complete:
                # All files for this table are done
                bytes_done += state.total_bytes
            elif state.file_count > 0 and state.files_completed > 0:
                # Proportional bytes based on files completed
                # This assumes roughly equal file sizes within a table
                bytes_done += int(
                    (state.files_completed / state.file_count) * state.total_bytes
                )
        return bytes_done

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
        files_completed = self._calculate_files_completed()
        bytes_completed = self._calculate_bytes_completed()

        # Calculate throughput and ETA
        # Priority: 1) Row-based 2) Bytes-based 3) File-based
        # Bytes-based is more accurate than file-based because files vary in size
        eta: int | None = None
        eta_mode: Literal["rows", "bytes", "files"] | None = None
        rps = 0
        bps = 0.0
        fps = 0.0

        if self._total_rows > 0 and rows_loaded > 0 and elapsed > 0:
            # Row-based ETA (most accurate when row counts available)
            rps = int(rows_loaded / elapsed)
            remaining_rows = self._total_rows - rows_loaded
            if rps > 0:
                eta = int(remaining_rows / rps)
                eta_mode = "rows"
        elif self._total_bytes > 0 and bytes_completed > 0 and elapsed > 0:
            # Bytes-based ETA (bandwidth-aware, good for legacy backups)
            # More accurate than file-based because files vary in size
            bps = bytes_completed / elapsed
            remaining_bytes = self._total_bytes - bytes_completed
            if bps > 0:
                eta = int(remaining_bytes / bps)
                eta_mode = "bytes"
        elif self._total_files > 0 and files_completed > 0 and elapsed > 0:
            # File-based ETA (fallback when no size info)
            fps = files_completed / elapsed
            remaining_files = self._total_files - files_completed
            if fps > 0:
                eta = int(remaining_files / fps)
                eta_mode = "files"

        # Also calculate file rate for stats even when using bytes-based ETA
        if elapsed > 0 and files_completed > 0:
            fps = files_completed / elapsed

        # Build list of in-progress tables
        # Include tables that are actively being worked on based on LOG OUTPUT:
        #   - files_started > 0: myloader has begun processing this table
        #   - NOT data_complete: still loading data files
        #   - OR data_complete but NOT is_complete: indexing phase
        # For "finalized" source, include all tables that had progress
        in_progress: list[TableProgressInfo] = []

        for state in self._tables.values():
            include_table = False

            if source == "finalized":
                # Include all tables that had any progress (now 100%)
                include_table = state.rows_total > 0 or state.was_ever_seen
            else:
                # Table is active if:
                # 1. In analyzing phase (early analyze running), OR
                # 2. Files have started (files_started > 0) AND not complete
                if state.phase == "analyzing":
                    # Analyzing phase: always show (ANALYZE TABLE running)
                    include_table = True
                elif state.files_started > 0:
                    # Loading/indexing phase: show if not complete
                    include_table = not state.is_complete

            if include_table:
                # Calculate per-table progress
                # For tables with rows_total=0 (legacy backups), use file-based %
                if state.rows_total > 0:
                    table_rows = int(state.percent_complete / 100.0 * state.rows_total)
                    table_percent = state.percent_complete
                else:
                    # File-based: files_started / file_count
                    table_rows = 0
                    if state.file_count > 0:
                        table_percent = (state.files_started / state.file_count) * 100
                        if state.data_complete:
                            table_percent = 100.0
                    else:
                        table_percent = 100.0 if state.data_complete else 0.0

                in_progress.append(
                    TableProgressInfo(
                        name=state.name,
                        percent_complete=min(100.0, table_percent),
                        phase=state.phase,  # type: ignore[arg-type]
                        rows_loaded=table_rows,
                        rows_total=state.rows_total,
                        running_seconds=state.running_seconds,
                        is_complete=state.is_complete,
                    )
                )

        # Overall progress: use row-based if available, else file-based
        if self._total_rows > 0:
            percent = rows_loaded / self._total_rows * 100
        else:
            # Legacy backup: no row counts, use file-based progress
            percent = self._calculate_file_based_percent()

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
                eta_mode=eta_mode,
                bytes_per_second=bps,
                bytes_completed=bytes_completed,
                bytes_total=self._total_bytes,
                files_per_second=fps,
                files_completed=files_completed,
                files_total=self._total_files,
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
    early_analyze_enabled: bool = False,
) -> RestoreProgressTracker:
    """Create a RestoreProgressTracker with compatible callback.

    This is a convenience factory that wraps the new RestoreProgress format
    into the old (percent, detail_dict) callback format for backwards compatibility.

    Args:
        table_metadata: List of tables with row estimates.
        progress_callback: Old-style callback receiving (percent, detail_dict).
        event_callback: Optional callback for file/table completion events.
            Called with (event_type: str, event_data: dict).
        early_analyze_enabled: If True, tables are NOT marked complete until
            analyze phase finishes. This prevents premature 100% progress.

    Returns:
        Configured RestoreProgressTracker instance.
    """
    if progress_callback is None:
        return RestoreProgressTracker(
            table_metadata=table_metadata,
            on_event=event_callback,
            early_analyze_enabled=early_analyze_enabled,
        )

    def on_progress(p: RestoreProgress) -> None:
        event_dict = p.to_event_dict()
        progress_callback(event_dict["percent"], event_dict["detail"])

    return RestoreProgressTracker(
        table_metadata=table_metadata,
        on_progress=on_progress,
        on_event=event_callback,
        early_analyze_enabled=early_analyze_enabled,
    )
