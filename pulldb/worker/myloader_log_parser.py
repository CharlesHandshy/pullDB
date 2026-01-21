"""Parse myloader verbose output for table phase transitions.

Tracks per-table state and emits events when phase transitions occur.
Primary detection method for index rebuild phase - more reliable than
processlist polling since myloader explicitly logs phase transitions.

Key log patterns detected (from mydumper source code):
- "Thread N: Enqueuing index for table: db.table" - Data load complete
- "restoring index: db.table" - Index rebuild starting
- "restoring indexes db.table from index" - Index rebuild in progress
- "L-Thread N: ending" - Loader thread finished
- "I-Thread N: ending" - Index thread finished

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING

from pulldb.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger("pulldb.worker.myloader_log_parser")


class TablePhase(Enum):
    """Phase of table restore process.
    
    State transitions:
        UNKNOWN -> LOADING_DATA (first data progress seen)
        LOADING_DATA -> DATA_COMPLETE (index enqueued)
        DATA_COMPLETE -> REBUILDING_INDEXES (index restore starts)
        REBUILDING_INDEXES -> COMPLETE (index thread ends or no more ALTER)
    """
    UNKNOWN = auto()
    LOADING_DATA = auto()       # INSERT/LOAD DATA in progress
    DATA_COMPLETE = auto()      # Data load finished, waiting for index queue
    REBUILDING_INDEXES = auto() # ALTER TABLE ADD KEY in progress
    COMPLETE = auto()           # Table fully restored


@dataclass
class TableState:
    """Track state for a single table during restore.
    
    Attributes:
        table_name: Full qualified name (target_db.table)
        source_table: Original table name from source backup
        target_table: Table name in staging database
        phase: Current phase of restore
        data_parts_total: Total parts for multi-file tables
        data_parts_completed: Parts completed so far
        index_started_at: When index rebuild phase started
        index_running_seconds: Elapsed time in index phase
        last_updated: Last time this state was updated
    """
    table_name: str
    source_table: str
    target_table: str
    phase: TablePhase = TablePhase.UNKNOWN
    data_parts_total: int = 0
    data_parts_completed: int = 0
    index_started_at: datetime | None = None
    index_running_seconds: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class LogParseResult:
    """Result of parsing a single log line.
    
    Attributes:
        event_type: Event to emit, if any (e.g., "table_index_rebuild_started")
        event_data: Data payload for the event
        table_name: Full qualified table name affected
        phase_change: New phase if a transition occurred
    """
    event_type: str | None = None
    event_data: dict = field(default_factory=dict)
    table_name: str | None = None
    phase_change: TablePhase | None = None


# ============================================================================
# Compiled regex patterns based on myloader source code
# ============================================================================

# From myloader_worker_index.c:create_index_job()
# Message: "Thread %d: Enqueuing index for table: %s.%s"
RE_ENQUEUE_INDEX = re.compile(
    r"Thread\s+(-?\d+):\s+Enqueuing index for table:\s+([^\s.]+)\.([^\s]+)",
    re.IGNORECASE,
)

# From myloader_worker_index.c:process_index()
# Message: "restoring index: %s.%s" (source_db.table)
RE_RESTORING_INDEX = re.compile(
    r"restoring index:\s+([^\s.]+)\.([^\s]+)",
    re.IGNORECASE,
)

# From myloader_restore_job.c - index restore message
# Message: "Thread %d: restoring indexes %s.%s from index"
RE_RESTORING_INDEXES = re.compile(
    r"Thread\s+(\d+):\s+restoring indexes\s+([^\s.]+)\.([^\s]+)\s+from index",
    re.IGNORECASE,
)

# From myloader_restore_job.c:process_restore_job() - data loading progress
# Message: "Thread %d: restoring %s.%s part %d of %d from %s | Progress..."
RE_DATA_PROGRESS = re.compile(
    r"Thread\s+(\d+):\s+restoring\s+([^\s.]+)\.([^\s]+)\s+part\s+(\d+)\s+of\s+(\d+)\s+from\s+([^\s|]+)",
    re.IGNORECASE,
)

# Overall progress: "Progress X of Y. Tables A of B completed"
RE_OVERALL_PROGRESS = re.compile(
    r"Progress\s+(\d+)\s+of\s+(\d+)\.\s*Tables\s+(\d+)\s+of\s+(\d+)",
    re.IGNORECASE,
)

# From myloader_worker_loader.c:loader_thread()
# Message: "L-Thread %u: ending"
RE_LOADER_THREAD_ENDING = re.compile(
    r"L-Thread\s+(\d+):\s+ending",
    re.IGNORECASE,
)

# Index thread ending (from worker_index_thread)
# Message: "I-Thread %u: ending"
RE_INDEX_THREAD_ENDING = re.compile(
    r"I-Thread\s+(\d+):\s+ending",
    re.IGNORECASE,
)


class MyloaderLogParser:
    """Stateful parser for myloader verbose output.
    
    Tracks per-table state and emits events when phase transitions occur.
    Thread-safe for concurrent access to state.
    
    Usage:
        parser = MyloaderLogParser(event_callback=emit_event)
        for line in myloader_output:
            result = parser.parse_line(line)
            if result.event_type:
                # Event was emitted via callback
                pass
        
        # Get final summary
        summary = parser.get_summary()
    """
    
    def __init__(
        self,
        event_callback: Callable[[str, dict], None] | None = None,
    ) -> None:
        """Initialize parser.
        
        Args:
            event_callback: Optional callback invoked when events should be emitted.
                Called with (event_type: str, event_data: dict).
        """
        self._event_callback = event_callback
        self._tables: dict[str, TableState] = {}
        self._overall_progress: int = 0
        self._overall_total: int = 0
        self._tables_completed: int = 0
        self._tables_total: int = 0
        self._loader_threads_ended: int = 0
        self._index_threads_ended: int = 0
        # Track source->target table name mapping
        self._source_to_target: dict[str, str] = {}
    
    def parse_line(self, line: str) -> LogParseResult:
        """Parse a single line of myloader output.
        
        Args:
            line: Raw log line from myloader stdout/stderr.
            
        Returns:
            LogParseResult with any event to emit and state changes.
        """
        result = LogParseResult()
        
        # Try each pattern in order of specificity
        
        # 1. Index enqueue (data load complete, index starting)
        if match := RE_ENQUEUE_INDEX.search(line):
            _thread_id, target_db, table_name = match.groups()
            result = self._handle_enqueue_index(target_db, table_name)
            
        # 2. Index restore starting
        elif match := RE_RESTORING_INDEX.search(line):
            source_db, table_name = match.groups()
            result = self._handle_restoring_index(source_db, table_name)
            
        # 3. Index restore in progress (more specific - from index file)
        elif match := RE_RESTORING_INDEXES.search(line):
            _thread_id, target_db, table_name = match.groups()
            result = self._handle_restoring_indexes(target_db, table_name)
            
        # 4. Data loading progress
        elif match := RE_DATA_PROGRESS.search(line):
            _thread_id, target_db, table_name, part, total, filename = match.groups()
            result = self._handle_data_progress(
                target_db, table_name, int(part), int(total), filename
            )
            
        # 5. Loader thread ending
        elif match := RE_LOADER_THREAD_ENDING.search(line):
            _thread_id = match.group(1)
            self._loader_threads_ended += 1
            logger.debug("loader_thread_ended", extra={"thread_id": _thread_id})
            
        # 6. Index thread ending
        elif match := RE_INDEX_THREAD_ENDING.search(line):
            _thread_id = match.group(1)
            self._index_threads_ended += 1
            logger.debug("index_thread_ended", extra={"thread_id": _thread_id})
        
        # Also check for overall progress (can appear with other patterns)
        if match := RE_OVERALL_PROGRESS.search(line):
            progress, total, tables_done, tables_total = match.groups()
            self._overall_progress = int(progress)
            self._overall_total = int(total)
            self._tables_completed = int(tables_done)
            self._tables_total = int(tables_total)
        
        # Emit event if callback registered
        if result.event_type and self._event_callback:
            self._event_callback(result.event_type, result.event_data)
        
        return result
    
    def _handle_enqueue_index(
        self, target_db: str, table_name: str
    ) -> LogParseResult:
        """Handle 'Enqueuing index for table' message.
        
        This signal indicates data loading is complete and the table
        is queued for index rebuild.
        """
        key = f"{target_db}.{table_name}"
        
        state = self._tables.get(key)
        if state is None:
            state = TableState(
                table_name=key,
                source_table=table_name,
                target_table=table_name,
            )
            self._tables[key] = state
        
        # Transition: data complete, entering index queue
        state.phase = TablePhase.DATA_COMPLETE
        state.index_started_at = datetime.now(UTC)
        state.last_updated = datetime.now(UTC)
        
        logger.info(
            "table_data_complete",
            extra={"table": table_name, "target_db": target_db},
        )
        
        return LogParseResult(
            event_type="table_index_rebuild_queued",
            event_data={
                "table": table_name,
                "target_db": target_db,
                "full_name": key,
            },
            table_name=key,
            phase_change=TablePhase.DATA_COMPLETE,
        )
    
    def _handle_restoring_index(
        self, source_db: str, table_name: str
    ) -> LogParseResult:
        """Handle 'restoring index:' message.
        
        This signal indicates index rebuild has started for the table.
        The source_db here is the original database name from the backup.
        """
        # Find matching table state (may be under target db name)
        state = None
        matching_key = None
        
        for key, s in self._tables.items():
            if s.source_table == table_name or key.endswith(f".{table_name}"):
                state = s
                matching_key = key
                break
        
        if state is None:
            # Table not seen before (unusual - should have seen data progress)
            key = f"{source_db}.{table_name}"
            state = TableState(
                table_name=key,
                source_table=table_name,
                target_table=table_name,
            )
            self._tables[key] = state
            matching_key = key
        
        state.phase = TablePhase.REBUILDING_INDEXES
        state.index_started_at = state.index_started_at or datetime.now(UTC)
        state.last_updated = datetime.now(UTC)
        
        # Track mapping from source to target
        self._source_to_target[f"{source_db}.{table_name}"] = matching_key
        
        logger.info(
            "table_index_rebuild_started",
            extra={"table": table_name, "source_db": source_db},
        )
        
        return LogParseResult(
            event_type="table_index_rebuild_started",
            event_data={
                "table": table_name,
                "source_db": source_db,
                "full_name": matching_key,
            },
            table_name=matching_key,
            phase_change=TablePhase.REBUILDING_INDEXES,
        )
    
    def _handle_restoring_indexes(
        self, target_db: str, table_name: str
    ) -> LogParseResult:
        """Handle 'restoring indexes ... from index' message.
        
        This indicates active index rebuild - provides target db name.
        """
        key = f"{target_db}.{table_name}"
        
        state = self._tables.get(key)
        if state is None:
            state = TableState(
                table_name=key,
                source_table=table_name,
                target_table=table_name,
            )
            self._tables[key] = state
        
        state.phase = TablePhase.REBUILDING_INDEXES
        state.last_updated = datetime.now(UTC)
        
        # Calculate running time if we have start time
        running_seconds = 0
        if state.index_started_at:
            running_seconds = int(
                (datetime.now(UTC) - state.index_started_at).total_seconds()
            )
        state.index_running_seconds = running_seconds
        
        return LogParseResult(
            event_type="table_index_rebuild_progress",
            event_data={
                "table": table_name,
                "target_db": target_db,
                "running_seconds": running_seconds,
                "full_name": key,
            },
            table_name=key,
        )
    
    def _handle_data_progress(
        self,
        target_db: str,
        table_name: str,
        part: int,
        total: int,
        filename: str,
    ) -> LogParseResult:
        """Handle data loading progress message.
        
        Tracks part X of Y progress for multi-file tables.
        """
        key = f"{target_db}.{table_name}"
        
        state = self._tables.get(key)
        if state is None:
            state = TableState(
                table_name=key,
                source_table=table_name,
                target_table=table_name,
                phase=TablePhase.LOADING_DATA,
            )
            self._tables[key] = state
        
        state.phase = TablePhase.LOADING_DATA
        state.data_parts_total = total
        state.data_parts_completed = part
        state.last_updated = datetime.now(UTC)
        
        percent = (part / total * 100) if total > 0 else 0
        
        return LogParseResult(
            event_type="table_data_progress",
            event_data={
                "table": table_name,
                "target_db": target_db,
                "part": part,
                "total": total,
                "percent": percent,
                "filename": filename,
                "full_name": key,
            },
            table_name=key,
        )
    
    def mark_table_complete(self, table_name: str) -> None:
        """Explicitly mark a table as complete.
        
        Called by RestoreStateTracker when external signals indicate
        the table is fully restored.
        
        Args:
            table_name: Full qualified table name (db.table)
        """
        state = self._tables.get(table_name)
        if state:
            state.phase = TablePhase.COMPLETE
            state.last_updated = datetime.now(UTC)
            
            if self._event_callback:
                self._event_callback(
                    "table_restore_complete",
                    {"table": state.source_table, "full_name": table_name},
                )
    
    def get_table_state(self, table_name: str) -> TableState | None:
        """Get current state for a table.
        
        Args:
            table_name: Full qualified name (db.table)
            
        Returns:
            TableState if found, None otherwise.
        """
        return self._tables.get(table_name)
    
    def get_all_states(self) -> dict[str, TableState]:
        """Get copy of all table states."""
        return self._tables.copy()
    
    def get_tables_in_phase(self, phase: TablePhase) -> list[str]:
        """Get all tables currently in a specific phase.
        
        Args:
            phase: Phase to filter by
            
        Returns:
            List of full qualified table names in that phase.
        """
        return [
            name for name, state in self._tables.items()
            if state.phase == phase
        ]
    
    def get_summary(self) -> dict:
        """Get summary of current restore state.
        
        Returns:
            Dictionary with:
            - overall_progress: Files processed
            - overall_total: Total files
            - tables_completed: Tables fully restored (per myloader)
            - tables_total: Total tables
            - tables_by_phase: Count per TablePhase
            - loader_threads_ended: Count of L-Thread endings
            - index_threads_ended: Count of I-Thread endings
        """
        phases = {phase: 0 for phase in TablePhase}
        for state in self._tables.values():
            phases[state.phase] += 1
        
        return {
            "overall_progress": self._overall_progress,
            "overall_total": self._overall_total,
            "tables_completed": self._tables_completed,
            "tables_total": self._tables_total,
            "tables_by_phase": {p.name: c for p, c in phases.items()},
            "loader_threads_ended": self._loader_threads_ended,
            "index_threads_ended": self._index_threads_ended,
            "tables_tracked": len(self._tables),
        }
