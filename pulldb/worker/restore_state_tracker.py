"""Coordinated state tracker merging myloader log parsing with processlist monitoring.

.. deprecated:: 1.0.8
    This module is NOT used in production restore flow. The production code uses
    :class:`~pulldb.worker.restore_progress.RestoreProgressTracker` instead, which
    implements strike-based completion detection. This module is retained for
    potential future use but should NOT be relied upon for accurate progress tracking.
    
    Key difference: This module uses time-based stale detection (10s default) which
    can cause premature completion detection. RestoreProgressTracker uses strike-based
    detection that properly handles FULLTEXT index gaps.

Ensures table is only marked complete when BOTH:
1. Data load finished (from log: "Enqueuing index")
2. Index rebuild finished (from processlist: no ALTER TABLE, or from log: thread ending)

The RestoreStateTracker acts as a coordinator between two signal sources:
- MyloaderLogParser: Parses stdout for explicit phase transitions
- ProcesslistMonitor: Polls MySQL processlist for running operations

Log parser is authoritative for phase transitions, processlist provides:
- Running time for index operations
- Fallback detection if log parsing misses events
- Confirmation that operations are still in progress

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING

from pulldb.infra.logging import get_logger
from pulldb.worker.myloader_log_parser import (
    MyloaderLogParser,
    TablePhase,
    TableState as LogTableState,
)
from pulldb.worker.processlist_monitor import (
    ProcesslistSnapshot,
    TableProgress,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger("pulldb.worker.restore_state_tracker")


class CombinedPhase(Enum):
    """Combined phase from both signal sources."""
    UNKNOWN = auto()
    LOADING_DATA = auto()
    DATA_COMPLETE = auto()      # Log says done, waiting for index confirmation
    REBUILDING_INDEXES = auto()  # Either source detects index rebuild
    ANALYZING = auto()           # ANALYZE TABLE running (future)
    COMPLETE = auto()


@dataclass
class CombinedTableState:
    """Combined state from log parser and processlist monitor.
    
    Attributes:
        table_name: Full qualified name (db.table)
        phase: Combined phase from both sources
        log_phase: Phase from log parser (authoritative for transitions)
        processlist_phase: Phase from processlist ('loading', 'indexing', or None)
        data_parts_completed: Data file parts completed (from log)
        data_parts_total: Total data file parts (from log)
        percent_complete: Best available progress percentage
        index_running_seconds: Time spent in index rebuild (from processlist)
        last_seen_in_processlist: When table was last seen in processlist
        last_updated: Last time this state was updated
    """
    table_name: str
    phase: CombinedPhase = CombinedPhase.UNKNOWN
    log_phase: TablePhase | None = None
    processlist_phase: str | None = None  # 'loading', 'indexing', or None
    data_parts_completed: int = 0
    data_parts_total: int = 0
    percent_complete: float = 0.0
    index_running_seconds: int = 0
    last_seen_in_processlist: datetime | None = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    @property
    def is_complete(self) -> bool:
        """Check if table is fully restored."""
        return self.phase == CombinedPhase.COMPLETE
    
    @property
    def is_indexing(self) -> bool:
        """Check if table is in index rebuild phase."""
        return self.phase == CombinedPhase.REBUILDING_INDEXES


class RestoreStateTracker:
    """Coordinate signals from log parser and processlist monitor.
    
    Usage:
        parser = MyloaderLogParser()
        tracker = RestoreStateTracker(
            log_parser=parser,
            event_callback=emit_event,
        )
        
        # Feed log lines
        for line in myloader_output:
            parser.parse_line(line)
        
        # Periodically update from processlist
        snapshot = processlist_monitor.get_snapshot()
        tracker.update_from_processlist(snapshot)
        
        # Check table states
        for table, state in tracker.get_all_states().items():
            if state.is_indexing:
                print(f"{table}: indexing for {state.index_running_seconds}s")
    """
    
    def __init__(
        self,
        log_parser: MyloaderLogParser,
        event_callback: Callable[[str, dict], None] | None = None,
        stale_threshold_seconds: float = 10.0,
    ) -> None:
        """Initialize tracker.
        
        Args:
            log_parser: MyloaderLogParser instance to read state from.
            event_callback: Optional callback for emitting events.
            stale_threshold_seconds: Time without processlist activity before
                considering a table as no longer in that phase.
        """
        self._log_parser = log_parser
        self._event_callback = event_callback
        self._stale_threshold = stale_threshold_seconds
        self._combined_states: dict[str, CombinedTableState] = {}
        self._lock = threading.Lock()
        self._last_processlist_update: datetime | None = None
    
    def update_from_processlist(self, snapshot: ProcesslistSnapshot | None) -> None:
        """Update combined states from processlist snapshot.
        
        Args:
            snapshot: Latest processlist snapshot, or None if unavailable.
        """
        if snapshot is None:
            return
        
        now = datetime.now(UTC)
        self._last_processlist_update = now
        
        with self._lock:
            # Mark tables seen in processlist
            for table_name, progress in snapshot.tables.items():
                state = self._get_or_create_state(table_name)
                state.processlist_phase = progress.phase
                state.last_seen_in_processlist = now
                
                if progress.phase == "indexing":
                    state.index_running_seconds = progress.running_seconds
                    # Processlist confirms indexing - update combined phase
                    if state.phase not in (CombinedPhase.COMPLETE, CombinedPhase.ANALYZING):
                        old_phase = state.phase
                        state.phase = CombinedPhase.REBUILDING_INDEXES
                        if old_phase != CombinedPhase.REBUILDING_INDEXES:
                            self._emit("table_index_rebuild_confirmed", {
                                "table": table_name,
                                "running_seconds": progress.running_seconds,
                            })
                
                elif progress.phase == "loading":
                    state.percent_complete = progress.percent_complete
                    if state.phase == CombinedPhase.UNKNOWN:
                        state.phase = CombinedPhase.LOADING_DATA
                
                state.last_updated = now
            
            # Merge with log parser states
            self._merge_log_parser_states()
            
            # Check for tables that completed (no longer in processlist)
            self._check_for_completions(snapshot, now)
    
    def _get_or_create_state(self, table_name: str) -> CombinedTableState:
        """Get existing state or create new one."""
        if table_name not in self._combined_states:
            self._combined_states[table_name] = CombinedTableState(
                table_name=table_name
            )
        return self._combined_states[table_name]
    
    def _merge_log_parser_states(self) -> None:
        """Merge states from log parser into combined states."""
        log_states = self._log_parser.get_all_states()
        
        for table_name, log_state in log_states.items():
            state = self._get_or_create_state(table_name)
            state.log_phase = log_state.phase
            state.data_parts_completed = log_state.data_parts_completed
            state.data_parts_total = log_state.data_parts_total
            
            # Log parser is authoritative for phase transitions
            if log_state.phase == TablePhase.LOADING_DATA:
                if state.phase == CombinedPhase.UNKNOWN:
                    state.phase = CombinedPhase.LOADING_DATA
                # Calculate percent from parts if available
                if log_state.data_parts_total > 0:
                    state.percent_complete = (
                        log_state.data_parts_completed / log_state.data_parts_total * 100
                    )
            
            elif log_state.phase == TablePhase.DATA_COMPLETE:
                if state.phase in (CombinedPhase.UNKNOWN, CombinedPhase.LOADING_DATA):
                    state.phase = CombinedPhase.DATA_COMPLETE
                    state.percent_complete = 100.0  # Data is 100%, but not indexes
            
            elif log_state.phase == TablePhase.REBUILDING_INDEXES:
                if state.phase not in (CombinedPhase.COMPLETE, CombinedPhase.ANALYZING):
                    state.phase = CombinedPhase.REBUILDING_INDEXES
            
            elif log_state.phase == TablePhase.COMPLETE:
                state.phase = CombinedPhase.COMPLETE
            
            state.last_updated = datetime.now(UTC)
    
    def _check_for_completions(
        self, snapshot: ProcesslistSnapshot, now: datetime
    ) -> None:
        """Check if any tables have completed (no longer in processlist).
        
        A table is considered complete if:
        1. It was in DATA_COMPLETE or REBUILDING_INDEXES phase
        2. It's no longer in the processlist
        3. The stale threshold has passed
        """
        for table_name, state in self._combined_states.items():
            # Skip already complete tables
            if state.phase == CombinedPhase.COMPLETE:
                continue
            
            # Skip tables still in processlist
            if table_name in snapshot.tables:
                continue
            
            # Check if table should be marked complete
            if state.phase in (CombinedPhase.DATA_COMPLETE, CombinedPhase.REBUILDING_INDEXES):
                if state.last_seen_in_processlist is not None:
                    elapsed = (now - state.last_seen_in_processlist).total_seconds()
                    if elapsed > self._stale_threshold:
                        # Table is no longer in processlist and was in index phase
                        state.phase = CombinedPhase.COMPLETE
                        state.percent_complete = 100.0
                        state.last_updated = now
                        
                        self._emit("table_restore_complete", {
                            "table": table_name,
                            "index_duration_seconds": state.index_running_seconds,
                        })
                        
                        # Also mark complete in log parser
                        self._log_parser.mark_table_complete(table_name)
    
    def _emit(self, event_type: str, data: dict) -> None:
        """Emit event if callback registered."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except Exception as e:
                logger.warning(
                    "event_callback_error",
                    extra={"event_type": event_type, "error": str(e)},
                )
    
    def get_table_state(self, table_name: str) -> CombinedTableState | None:
        """Get combined state for a table.
        
        Args:
            table_name: Full qualified name or just table name
            
        Returns:
            CombinedTableState or None if not found.
        """
        with self._lock:
            # Try exact match first
            if table_name in self._combined_states:
                return self._combined_states[table_name]
            
            # Try partial match (just table name without db prefix)
            for key, state in self._combined_states.items():
                if key.endswith(f".{table_name}"):
                    return state
            
            return None
    
    def get_all_states(self) -> dict[str, CombinedTableState]:
        """Get copy of all combined states."""
        with self._lock:
            return self._combined_states.copy()
    
    def get_tables_in_phase(self, phase: CombinedPhase) -> list[str]:
        """Get all tables currently in a specific phase.
        
        Args:
            phase: Phase to filter by
            
        Returns:
            List of table names in that phase.
        """
        with self._lock:
            return [
                name for name, state in self._combined_states.items()
                if state.phase == phase
            ]
    
    def get_summary(self) -> dict:
        """Get summary of current restore state.
        
        Returns:
            Dictionary with counts per phase and overall stats.
        """
        with self._lock:
            phases = {phase: 0 for phase in CombinedPhase}
            total_index_time = 0
            
            for state in self._combined_states.values():
                phases[state.phase] += 1
                total_index_time += state.index_running_seconds
            
            log_summary = self._log_parser.get_summary()
            
            return {
                "tables_by_phase": {p.name: c for p, c in phases.items()},
                "total_tables": len(self._combined_states),
                "total_index_time_seconds": total_index_time,
                "log_parser": log_summary,
                "last_processlist_update": (
                    self._last_processlist_update.isoformat()
                    if self._last_processlist_update else None
                ),
            }
    
    def mark_all_complete(self) -> None:
        """Mark all tables as complete.
        
        Called when myloader process exits successfully.
        """
        with self._lock:
            for table_name, state in self._combined_states.items():
                if state.phase != CombinedPhase.COMPLETE:
                    state.phase = CombinedPhase.COMPLETE
                    state.percent_complete = 100.0
                    state.last_updated = datetime.now(UTC)
                    
                    self._emit("table_restore_complete", {
                        "table": table_name,
                        "index_duration_seconds": state.index_running_seconds,
                        "reason": "myloader_exit",
                    })
