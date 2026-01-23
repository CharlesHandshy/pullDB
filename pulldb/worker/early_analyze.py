"""Early ANALYZE TABLE worker - runs analysis as tables complete during myloader.

Runs ANALYZE TABLE on tables as they finish loading/indexing, in parallel with
ongoing myloader operations. This ensures index statistics are fresh before
the atomic rename, without adding serial wait time after myloader completes.

Thread Budget Model:
- During myloader: analyzer_threads = (max_threads - active_myloader_threads) + 1
- After myloader: analyzer_threads = max_threads (full capacity)
- Always guarantees at least 1 analyzer thread even when myloader is at capacity

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import contextlib
import queue
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pulldb.infra.logging import get_logger
from pulldb.worker.table_analyzer import AnalyzeResult, AnalyzeStatus, analyze_table


if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger("pulldb.worker.early_analyze")

# Sentinel value to signal worker threads to stop
_STOP_SENTINEL = object()


@dataclass
class EarlyAnalyzeStats:
    """Statistics for early analyze worker.

    Attributes:
        tables_queued: Number of tables added to queue
        tables_analyzed: Number of tables successfully analyzed
        tables_failed: Number of tables that failed analysis
        tables_in_progress: Tables currently being analyzed
        total_duration_seconds: Total time spent analyzing
        started_at: When worker started
        completed_at: When all work finished
    """

    tables_queued: int = 0
    tables_analyzed: int = 0
    tables_failed: int = 0
    tables_in_progress: set[str] = field(default_factory=set)
    results: list[AnalyzeResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def tables_pending(self) -> int:
        """Tables waiting in queue."""
        in_progress = len(self.tables_in_progress)
        return (
            self.tables_queued - self.tables_analyzed - self.tables_failed - in_progress
        )


class EarlyAnalyzeWorker:
    """Background worker that runs ANALYZE TABLE on tables as they complete.

    Manages a pool of worker threads that process completed tables from a queue.
    Thread count is dynamically adjusted based on myloader's active thread count.

    Usage:
        worker = EarlyAnalyzeWorker(
            connection_factory=lambda: mysql.connector.connect(...),
            staging_db="staging_xyz",
            max_threads=8,
            event_callback=emit_event,
        )
        worker.start()

        # As tables complete...
        worker.queue_table("users")
        worker.update_active_threads(6)  # myloader using 6, so analyzer gets 3

        # When myloader done
        worker.notify_myloader_complete()

        # Wait for all analysis
        stats = worker.wait_for_completion()
        worker.stop()
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        staging_db: str,
        max_threads: int = 8,
        event_callback: Callable[[str, dict], None] | None = None,
    ) -> None:
        """Initialize early analyze worker.

        Args:
            connection_factory: Callable that returns a new MySQL connection.
            staging_db: Staging database name for table qualification.
            max_threads: Maximum threads (same as myloader max_threads).
            event_callback: Optional callback for events.
        """
        self._connection_factory = connection_factory
        self._staging_db = staging_db
        self._max_threads = max(1, max_threads)
        self._event_callback = event_callback

        # Thread management
        # maxsize prevents unbounded memory growth if tables complete faster than analysis
        self._queue: queue.Queue[str | object] = queue.Queue(maxsize=1000)
        self._workers: list[threading.Thread] = []
        self._active_workers = 0
        self._active_workers_lock = threading.Lock()

        # Dynamic thread budget
        # NOTE: Using RLock because _can_work() calls _get_thread_budget() which
        # acquires this lock, and _can_work() is called inside the Condition block
        # which already holds this lock. RLock allows reentrant acquisition.
        self._myloader_active_threads = 0
        self._myloader_complete = False
        self._budget_lock = threading.RLock()
        self._budget_condition = threading.Condition(self._budget_lock)

        # Stats tracking
        self._stats = EarlyAnalyzeStats()
        self._stats_lock = threading.Lock()

        # Progress tracker (set by run_myloader to update UI)
        self._progress_tracker: Any = None

        # Control
        self._started = False
        self._stopping = False
        self._all_done = threading.Event()

    def set_progress_tracker(self, tracker: Any) -> None:
        """Set the progress tracker for UI updates.

        Called by run_myloader() to connect analyze events to the progress tracker.
        This allows the UI to show tables in 'analyzing' phase.

        Args:
            tracker: RestoreProgressTracker instance (Any to avoid circular import).
        """
        self._progress_tracker = tracker

    def start(self) -> None:
        """Start the worker thread pool."""
        if self._started:
            return

        self._started = True
        self._stats.started_at = datetime.now(UTC)

        # Create worker threads (up to max_threads)
        # They will self-regulate based on budget
        for i in range(self._max_threads):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"EarlyAnalyze-{i}",
                daemon=True,
            )
            self._workers.append(thread)
            thread.start()

        logger.info(
            "early_analyze_started",
            extra={
                "max_threads": self._max_threads,
                "staging_db": self._staging_db,
            },
        )

    def queue_table(self, table_name: str) -> None:
        """Add a table to the analyze queue.

        Called when a table finishes loading+indexing (table_restore_complete).
        Uses non-blocking put to avoid deadlocking myloader if queue is full.

        Args:
            table_name: Table name (without database prefix).
        """
        if self._stopping:
            return

        try:
            # Use put_nowait to avoid blocking myloader's callback thread
            # If queue is full (1000 tables), we skip this table rather than block
            self._queue.put_nowait(table_name)
        except queue.Full:
            logger.warning(
                "early_analyze_queue_full",
                extra={
                    "table": table_name,
                    "queue_size": self._queue.qsize(),
                },
            )
            return  # Don't increment stats for tables we couldn't queue

        with self._stats_lock:
            self._stats.tables_queued += 1

        # Wake up any waiting workers
        with self._budget_condition:
            self._budget_condition.notify_all()

        logger.debug("early_analyze_queued", extra={"table": table_name})

    def update_active_threads(self, myloader_active: int) -> None:
        """Update the count of active myloader threads.

        Called periodically from processlist monitor to adjust analyzer budget.

        Args:
            myloader_active: Number of currently active myloader threads.
        """
        with self._budget_condition:
            self._myloader_active_threads = myloader_active
            self._budget_condition.notify_all()

    def notify_myloader_complete(self) -> None:
        """Signal that myloader has finished.

        Allows analyzer to use full thread capacity.
        """
        with self._budget_condition:
            self._myloader_complete = True
            self._myloader_active_threads = 0
            self._budget_condition.notify_all()

        logger.info(
            "early_analyze_myloader_complete",
            extra={
                "pending_tables": self._stats.tables_pending,
            },
        )

    def _get_thread_budget(self) -> int:
        """Calculate current thread budget.

        Returns:
            Number of threads allowed to be active for analyzing.
        """
        with self._budget_lock:
            if self._myloader_complete:
                return self._max_threads
            else:
                # (max - active) + 1, minimum of 1
                return max(1, (self._max_threads - self._myloader_active_threads) + 1)

    def _can_work(self) -> bool:
        """Check if this worker thread can proceed with work.

        Returns:
            True if within budget and work available.
        """
        budget = self._get_thread_budget()
        with self._active_workers_lock:
            return self._active_workers < budget

    def _worker_loop(self) -> None:
        """Main loop for worker threads."""
        connection = None

        try:
            while not self._stopping:
                # Wait for budget availability
                with self._budget_condition:
                    while not self._stopping and not self._can_work():
                        self._budget_condition.wait(timeout=0.5)

                if self._stopping:
                    break

                # Try to get work
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if item is _STOP_SENTINEL:
                    self._queue.task_done()
                    break

                # Type assertion: item is now str (not sentinel)
                table_name: str = item  # type: ignore[assignment]

                # Register as active
                with self._active_workers_lock:
                    self._active_workers += 1

                with self._stats_lock:
                    self._stats.tables_in_progress.add(table_name)

                # Update progress tracker for UI (errors logged, not raised)
                if self._progress_tracker:
                    try:
                        self._progress_tracker.mark_table_analyzing(table_name)
                    except Exception as tracker_err:
                        logger.warning(
                            "progress_tracker_error",
                            extra={"method": "mark_table_analyzing", "error": str(tracker_err)},
                        )

                # Emit event
                self._emit("table_analyze_started", {"table": table_name})

                try:
                    # Ensure connection
                    if connection is None:
                        connection = self._connection_factory()

                    # Run ANALYZE TABLE
                    full_name = f"{self._staging_db}.{table_name}"
                    result = analyze_table(
                        connection, full_name, no_write_to_binlog=True
                    )

                    # Record result
                    with self._stats_lock:
                        self._stats.results.append(result)
                        self._stats.tables_in_progress.discard(table_name)
                        self._stats.total_duration_seconds += result.duration_seconds

                        if result.status == AnalyzeStatus.OK:
                            self._stats.tables_analyzed += 1
                        else:
                            self._stats.tables_failed += 1

                    # Emit completion event
                    self._emit(
                        "table_analyze_complete",
                        {
                            "table": table_name,
                            "duration_seconds": round(result.duration_seconds, 3),
                            "status": result.status.name,
                        },
                    )

                    # Update progress tracker for UI (errors logged, not raised)
                    if self._progress_tracker:
                        try:
                            self._progress_tracker.mark_table_analyze_complete(table_name)
                        except Exception as tracker_err:
                            logger.warning(
                                "progress_tracker_error",
                                extra={"method": "mark_table_analyze_complete", "error": str(tracker_err)},
                            )

                except Exception as e:
                    logger.error(
                        "early_analyze_error",
                        extra={
                            "table": table_name,
                            "error": str(e),
                        },
                    )

                    with self._stats_lock:
                        self._stats.tables_in_progress.discard(table_name)
                        self._stats.tables_failed += 1

                    self._emit(
                        "table_analyze_complete",
                        {
                            "table": table_name,
                            "duration_seconds": 0,
                            "status": "ERROR",
                            "error": str(e),
                        },
                    )

                    # Update progress tracker for UI (errors logged, not raised)
                    if self._progress_tracker:
                        try:
                            self._progress_tracker.mark_table_analyze_complete(table_name)
                        except Exception as tracker_err:
                            logger.warning(
                                "progress_tracker_error",
                                extra={"method": "mark_table_analyze_complete", "error": str(tracker_err)},
                            )

                    # Reset connection on error
                    if connection:
                        with contextlib.suppress(Exception):
                            connection.close()
                        connection = None

                finally:
                    with self._active_workers_lock:
                        self._active_workers -= 1

                    self._queue.task_done()

                    # Check if all done
                    self._check_completion()

        finally:
            if connection:
                with contextlib.suppress(Exception):
                    connection.close()

    def _check_completion(self) -> None:
        """Check if all work is complete and signal if so.

        Atomically checks all completion conditions under a single lock scope
        to prevent race conditions where new work could arrive between checks.
        """
        with self._stats_lock:
            pending = self._stats.tables_pending
            in_progress = len(self._stats.tables_in_progress)
            # Check queue inside lock to ensure atomic read of all conditions
            queue_empty = self._queue.empty()

            if pending == 0 and in_progress == 0 and queue_empty:
                self._all_done.set()

    def _emit(self, event_type: str, data: dict) -> None:
        """Emit event if callback registered."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except Exception as e:
                logger.warning(
                    "event_callback_error",
                    extra={
                        "event_type": event_type,
                        "error": str(e),
                    },
                )

    def wait_for_completion(self, timeout: float | None = None) -> EarlyAnalyzeStats:
        """Wait for all queued tables to be analyzed.

        Args:
            timeout: Maximum seconds to wait (None = forever).

        Returns:
            EarlyAnalyzeStats with final statistics.
        """
        # Handle edge case: if no tables were ever queued, complete immediately
        self._check_completion()

        # Wait for queue to drain
        self._all_done.wait(timeout=timeout)

        with self._stats_lock:
            self._stats.completed_at = datetime.now(UTC)

            self._emit(
                "early_analyze_batch_complete",
                {
                    "tables_analyzed": self._stats.tables_analyzed,
                    "tables_failed": self._stats.tables_failed,
                    "total_duration_seconds": round(
                        self._stats.total_duration_seconds, 2
                    ),
                },
            )

            return EarlyAnalyzeStats(
                tables_queued=self._stats.tables_queued,
                tables_analyzed=self._stats.tables_analyzed,
                tables_failed=self._stats.tables_failed,
                tables_in_progress=set(self._stats.tables_in_progress),
                results=list(self._stats.results),
                total_duration_seconds=self._stats.total_duration_seconds,
                started_at=self._stats.started_at,
                completed_at=self._stats.completed_at,
            )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop all worker threads.

        Args:
            timeout: Seconds to wait for each thread to stop.
        """
        self._stopping = True

        # Wake up all waiting workers
        with self._budget_condition:
            self._budget_condition.notify_all()

        # Send stop sentinels - use put_nowait with suppression since
        # queue might be full, but workers will exit via _stopping flag anyway
        for _ in self._workers:
            try:
                self._queue.put_nowait(_STOP_SENTINEL)
            except queue.Full:
                pass  # Workers will exit via _stopping flag check

        # Wait for threads
        for thread in self._workers:
            thread.join(timeout=timeout)

        logger.info(
            "early_analyze_stopped",
            extra={
                "tables_analyzed": self._stats.tables_analyzed,
                "tables_failed": self._stats.tables_failed,
            },
        )

    def get_analyzing_tables(self) -> set[str]:
        """Get set of tables currently being analyzed.

        Returns:
            Set of table names currently in analysis.
        """
        with self._stats_lock:
            return set(self._stats.tables_in_progress)

    def get_stats(self) -> EarlyAnalyzeStats:
        """Get current statistics snapshot.

        Returns:
            Copy of current stats.
        """
        with self._stats_lock:
            return EarlyAnalyzeStats(
                tables_queued=self._stats.tables_queued,
                tables_analyzed=self._stats.tables_analyzed,
                tables_failed=self._stats.tables_failed,
                tables_in_progress=set(self._stats.tables_in_progress),
                results=list(self._stats.results),
                total_duration_seconds=self._stats.total_duration_seconds,
                started_at=self._stats.started_at,
                completed_at=self._stats.completed_at,
            )
