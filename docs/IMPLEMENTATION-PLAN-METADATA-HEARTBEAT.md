# Implementation Plan: Metadata Synthesis & Heartbeat Fix

**Created**: January 18, 2026  
**Status**: READY FOR IMPLEMENTATION  
**Root Cause**: Worker starvation during metadata synthesis blocks heartbeat events, causing 15-minute stale detection to kill active workers

---

## Executive Summary

The foxpest restore job (b5811985) failed because:

1. `metadata_synthesis.py` decompresses and reads **ALL 86 GiB** of SQL files to count rows
2. This takes ~20 minutes, during which **no job events are emitted**
3. Stale job detection looks for jobs with no events in 15 minutes
4. Worker was declared dead and recovery aborted the (actually running) myloader process

**Fix Strategy**: Two-pronged approach:

| Fix | Problem Solved | Complexity |
|-----|---------------|------------|
| **1. Smart row estimation** | Eliminates 20-minute blocking scan | Low |
| **2. Async heartbeat thread** | Protects ALL long operations | Medium |

---

## Part 1: Smart Row Estimation (Eliminates Blocking)

### 1.1 Root Cause Analysis

Current `count_rows_in_file()` decompresses every `.sql.gz` file and counts INSERT lines:

```
86 GiB compressed → ~300+ GiB uncompressed → read line by line → 20 minutes
```

### 1.2 Key Insight: mydumper's `--rows=1000000` Default

Verified from foxpest data:
- Tables with multiple chunks (*.00001.sql.gz, *.00002.sql.gz, etc.) have **exactly 1,000,000 rows per full chunk**
- Only the LAST chunk is partial
- Single-file tables have unknown row counts (but are usually small)

**Exception**: The `contracts` table is a 26 GiB single file - likely a poorly-designed table with no chunking.

### 1.3 Estimation Strategy

```
FOR each table:
  files = list all data files for this table (exclude schema files)
  
  IF multiple chunks exist:
    # mydumper default: 1M rows per chunk
    full_chunks = len(files) - 1
    rows = full_chunks * 1,000,000
    
    # Estimate last chunk from size ratio
    avg_full_size = mean(sizes of files[:-1])
    last_size = size(files[-1])
    rows += (last_size / avg_full_size) * 1,000,000
    
  ELIF single file AND size < 100MB:
    # Small enough to count quickly (~1 second)
    rows = count_rows(file)
    
  ELSE (single large file):
    # Skip counting - use ISIZE estimate or 0
    # These are pathological cases (contracts)
    rows = estimate_from_gzip_isize(file)  # O(1) - read 4 bytes
```

### 1.4 Implementation: `pulldb/worker/metadata_synthesis.py`

**Changes Required**:

1. Add new helper functions
2. Rewrite `synthesize_metadata()` to use smart estimation
3. Keep `count_rows_in_file()` for small files only

```python
# NEW CONSTANTS
MYDUMPER_DEFAULT_ROWS_PER_CHUNK = 1_000_000
SMALL_FILE_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB
LARGE_FILE_THRESHOLD_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB (skip entirely)

# NEW FUNCTION: Get gzip ISIZE (O(1) - no decompression)
def get_gzip_uncompressed_size(filepath: str) -> int:
    """Read ISIZE from gzip trailer - instant, no decompression.
    
    Per RFC 1952, ISIZE is last 4 bytes (little-endian uint32).
    Wraps at 4GB but most SQL files are smaller.
    """
    try:
        with open(filepath, 'rb') as f:
            f.seek(-4, 2)
            return struct.unpack('<I', f.read(4))[0]
    except Exception:
        return 0

# NEW FUNCTION: Estimate rows for a table (all its chunk files)
def estimate_table_rows(table_files: list[Path]) -> int:
    """Estimate rows for a table using chunk math or size heuristics.
    
    Args:
        table_files: List of data files for this table (*.00000.sql.gz, etc.)
                    Sorted by chunk number.
    
    Returns:
        Estimated row count for the entire table.
    """
    if not table_files:
        return 0
    
    # Sort by chunk number to identify full vs partial
    table_files = sorted(table_files, key=lambda p: p.name)
    
    if len(table_files) == 1:
        # Single file - check size
        file_size = table_files[0].stat().st_size
        
        if file_size > LARGE_FILE_THRESHOLD_BYTES:
            # Giant single file (pathological) - use ISIZE estimate
            logger.warning(
                f"Large unchunked table {table_files[0].name} ({file_size / 1e9:.1f} GB) - "
                "using ISIZE estimate"
            )
            uncompressed = get_gzip_uncompressed_size(str(table_files[0]))
            # Estimate ~200 bytes per row for INSERT data
            return max(1, uncompressed // 200)
        
        elif file_size < SMALL_FILE_THRESHOLD_BYTES:
            # Small file - fast to count directly
            return count_rows_in_file(str(table_files[0]))
        
        else:
            # Medium file - use ISIZE estimate to avoid delay
            uncompressed = get_gzip_uncompressed_size(str(table_files[0]))
            return max(1, uncompressed // 200)
    
    # Multiple chunks - use mydumper math
    full_chunks = len(table_files) - 1
    rows = full_chunks * MYDUMPER_DEFAULT_ROWS_PER_CHUNK
    
    # Estimate last chunk from size ratio
    full_sizes = [f.stat().st_size for f in table_files[:-1]]
    if full_sizes:
        avg_full_size = sum(full_sizes) / len(full_sizes)
        last_size = table_files[-1].stat().st_size
        if avg_full_size > 0:
            rows += int((last_size / avg_full_size) * MYDUMPER_DEFAULT_ROWS_PER_CHUNK)
    
    return rows

# MODIFIED: synthesize_metadata() - use smart estimation
def synthesize_metadata(backup_dir: str, output_file: str | None = None) -> None:
    """Scan backup directory and generate myloader 0.19 compatible metadata file.
    
    Uses smart row estimation to avoid decompressing all files:
    - Chunked tables: (chunks - 1) * 1M + size-proportional estimate for last chunk
    - Small single files: count directly (fast)
    - Large single files: ISIZE-based estimate (O(1))
    """
    if not os.path.isdir(backup_dir):
        logger.error(f"Directory {backup_dir} not found.")
        return

    backup_path = Path(backup_dir)
    
    # Group files by table
    table_files: dict[tuple[str, str], list[Path]] = defaultdict(list)
    
    logger.info(f"Scanning {backup_dir} for metadata synthesis...")
    
    for filepath in backup_path.glob("*.sql.gz"):
        result = parse_filename(filepath.name)
        if result:
            db, table = result
            table_files[(db, table)].append(filepath)
    
    # Estimate rows per table
    table_rows: dict[tuple[str, str], int] = {}
    for (db, table), files in table_files.items():
        table_rows[(db, table)] = estimate_table_rows(files)
    
    logger.info(f"Estimated row counts for {len(table_rows)} tables.")
    
    # ... rest of INI generation unchanged ...
```

### 1.5 Expected Performance

| Scenario | Before | After |
|----------|--------|-------|
| foxpest (86 GiB, 2356 files) | ~20 minutes | ~2 seconds |
| Small backup (1 GiB, 50 files) | ~30 seconds | ~0.5 seconds |
| Medium backup (10 GiB, 300 files) | ~3 minutes | ~1 second |

---

## Part 2: Async Heartbeat Thread (Defense in Depth)

### 2.1 Why This Is Still Needed

Even with fast metadata synthesis, other operations can block:
- `myloader` itself runs for hours on large restores
- Future operations we haven't anticipated
- Network timeouts, disk I/O stalls

The heartbeat thread provides **defense in depth** - the worker stays alive regardless of what the main thread is doing.

### 2.2 How Stale Detection Currently Works

From `mysql.py` line 1100-1180:

```sql
SELECT j.* FROM jobs j
LEFT JOIN (
    SELECT job_id, MAX(logged_at) AS last_logged_at
    FROM job_events
    GROUP BY job_id
) last_event ON last_event.job_id = j.id
WHERE j.status = 'running'
  AND COALESCE(last_event.last_logged_at, j.started_at)
      < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 15 MINUTE)
```

**Key insight**: Staleness is determined by the most recent `job_event` timestamp. If we emit events regularly, the job won't be considered stale.

### 2.3 Heartbeat Strategy

Add a background thread that emits `heartbeat` events every 60 seconds during job execution:

```python
# pulldb/worker/heartbeat.py (NEW FILE)

"""Async heartbeat mechanism for long-running worker operations.

Prevents stale job detection from killing active workers during
long-running operations like metadata synthesis, myloader, etc.
"""

import threading
import time
from typing import Callable

from pulldb.infra.logging import get_logger

logger = get_logger("pulldb.worker.heartbeat")


class HeartbeatThread(threading.Thread):
    """Background thread that emits heartbeat events at regular intervals.
    
    Usage:
        def emit_heartbeat():
            job_repo.append_job_event(job_id, "heartbeat", "Worker alive")
        
        heartbeat = HeartbeatThread(emit_heartbeat, interval=60)
        heartbeat.start()
        try:
            do_long_running_work()
        finally:
            heartbeat.stop()
            heartbeat.join(timeout=5)
    """
    
    def __init__(
        self,
        heartbeat_fn: Callable[[], None],
        interval_seconds: float = 60.0,
        name: str = "heartbeat",
    ):
        """Initialize heartbeat thread.
        
        Args:
            heartbeat_fn: Function to call on each heartbeat (e.g., emit event)
            interval_seconds: Seconds between heartbeats (default 60)
            name: Thread name for debugging
        """
        super().__init__(name=name, daemon=True)
        self.heartbeat_fn = heartbeat_fn
        self.interval = interval_seconds
        self._stop_event = threading.Event()
        self._started = False
    
    def run(self) -> None:
        """Background loop that emits heartbeats until stopped."""
        self._started = True
        logger.debug(f"Heartbeat thread started (interval={self.interval}s)")
        
        while not self._stop_event.wait(self.interval):
            try:
                self.heartbeat_fn()
                logger.debug("Heartbeat emitted")
            except Exception as e:
                # Log but don't crash - heartbeat is best-effort
                logger.warning(f"Heartbeat emission failed: {e}")
        
        logger.debug("Heartbeat thread stopped")
    
    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()
    
    @property
    def is_running(self) -> bool:
        """Check if heartbeat thread is actively running."""
        return self._started and not self._stop_event.is_set()


class HeartbeatContext:
    """Context manager for automatic heartbeat lifecycle.
    
    Usage:
        with HeartbeatContext(emit_fn, interval=60) as hb:
            do_long_running_work()
        # Heartbeat automatically stopped on exit
    """
    
    def __init__(
        self,
        heartbeat_fn: Callable[[], None],
        interval_seconds: float = 60.0,
    ):
        self.heartbeat_fn = heartbeat_fn
        self.interval = interval_seconds
        self._thread: HeartbeatThread | None = None
    
    def __enter__(self) -> "HeartbeatContext":
        self._thread = HeartbeatThread(
            self.heartbeat_fn,
            interval_seconds=self.interval,
        )
        self._thread.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._thread:
            self._thread.stop()
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("Heartbeat thread did not stop cleanly")
```

### 2.4 Integration Point: `executor.py`

The heartbeat should wrap the entire job execution, not just individual phases:

```python
# pulldb/worker/executor.py - WorkerJobExecutor.execute()

def execute(self, job: Job) -> None:
    """Execute complete restore workflow for a job."""
    
    # Create heartbeat emission function
    def emit_heartbeat():
        try:
            self.deps.job_repo.append_job_event(
                job.id,
                "heartbeat", 
                f"Worker alive - executing job"
            )
        except Exception as e:
            logger.warning(f"Failed to emit heartbeat: {e}")
    
    # Wrap entire execution in heartbeat context
    from pulldb.worker.heartbeat import HeartbeatContext
    
    with HeartbeatContext(emit_heartbeat, interval_seconds=60.0):
        # Existing execution logic...
        self._execute_workflow(job)
```

### 2.5 Heartbeat Interval Calculation

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Stale timeout | 15 minutes | Current setting in `STALE_RUNNING_TIMEOUT_MINUTES` |
| Heartbeat interval | 60 seconds | Emits 15 events before timeout |
| Safety margin | 15x | Plenty of room for missed beats |

### 2.6 Thread Safety Considerations

1. **`append_job_event()` is thread-safe**: Uses connection pooling with per-call connections
2. **Daemon thread**: Automatically killed if main process exits
3. **Graceful shutdown**: `stop()` + `join()` ensures clean exit
4. **Exception isolation**: Heartbeat failures don't crash main workflow

---

## Part 3: File Changes Summary

### 3.1 Files to Create

| File | Purpose |
|------|---------|
| `pulldb/worker/heartbeat.py` | Async heartbeat thread + context manager |

### 3.2 Files to Modify

| File | Changes |
|------|---------|
| `pulldb/worker/metadata_synthesis.py` | Smart row estimation (replace blocking scan) |
| `pulldb/worker/executor.py` | Wrap job execution in heartbeat context |

### 3.3 Files to Update (Tests)

| File | Changes |
|------|---------|
| `tests/unit/worker/test_metadata_synthesis.py` | Test smart estimation |
| `tests/unit/worker/test_heartbeat.py` | New: test heartbeat thread |
| `tests/qa/worker/test_stale_running_recovery.py` | Add heartbeat integration test |

---

## Part 4: Detailed Implementation Sequence

### Phase 1: Smart Row Estimation (Priority: HIGH)

**Goal**: Eliminate 20-minute blocking scan immediately.

1. **Add `struct` import** to `metadata_synthesis.py`
2. **Add `get_gzip_uncompressed_size()`** helper
3. **Add `estimate_table_rows()`** helper
4. **Modify `synthesize_metadata()`** to use estimation
5. **Keep `count_rows_in_file()`** for small files only
6. **Add unit tests** for new functions
7. **Manual test** with foxpest backup

**Estimated effort**: 2-3 hours

### Phase 2: Heartbeat Thread (Priority: MEDIUM)

**Goal**: Defense in depth for all long operations.

1. **Create `pulldb/worker/heartbeat.py`** with HeartbeatThread + HeartbeatContext
2. **Add integration in `executor.py`** - wrap execute() in heartbeat context
3. **Add unit tests** for heartbeat module
4. **Integration test** - verify events appear during long operations
5. **Manual test** - run restore and check for heartbeat events

**Estimated effort**: 2-3 hours

### Phase 3: Validation & Cleanup

1. **Re-run foxpest restore** to validate fix
2. **Monitor production** for heartbeat events
3. **Update documentation** (KNOWLEDGE-POOL.md, admin-guide.md)
4. **Archive old plan** (METADATA-SYNTHESIS-OPTIMIZATION-PLAN.md → archived/)

---

## Part 5: Risk Assessment

### 5.1 Risks of Smart Estimation

| Risk | Mitigation |
|------|------------|
| Inaccurate row counts | Acceptable - myloader doesn't need exact counts |
| Non-standard chunk sizes | Detect via file analysis; fall back to ISIZE |
| ISIZE wraparound (>4GB) | Rare; still better than blocking |

### 5.2 Risks of Heartbeat Thread

| Risk | Mitigation |
|------|------------|
| Thread doesn't stop | Daemon=True ensures cleanup on exit |
| Database connection issues | Catch exceptions, log warnings, continue |
| Too many events | 1/minute is negligible load |

### 5.3 Rollback Plan

If issues arise:
1. Heartbeat can be disabled by removing context manager
2. Estimation can revert to original `count_rows_in_file()` 
3. Both changes are isolated and independently revertible

---

## Part 6: Success Criteria

### Immediate (After Implementation)

- [ ] foxpest restore completes without stale detection killing worker
- [ ] Metadata synthesis completes in <5 seconds for 86 GiB backup
- [ ] Heartbeat events visible in job_events table during restore

### Long-term (1 Week Post-Deploy)

- [ ] No false-positive stale job recoveries
- [ ] Heartbeat events appearing for all running jobs
- [ ] No complaints about "stuck" progress display

---

## Appendix A: foxpest Investigation Findings

### Timeline of Failed Job

| Time | Event | Gap |
|------|-------|-----|
| 18:29:00 | `running` event | - |
| 18:29:01 | Download started | 1 sec |
| 18:53:26 | Download complete | 24 min |
| 18:53:26 | Extraction started | 0 sec |
| 19:05:34 | Extraction complete | 12 min |
| 19:05:35 | **Metadata synthesis started** | 1 sec |
| (silence) | No events for 15 minutes | - |
| 19:20:52 | `stale_running_recovery` | 15 min 17 sec |

### Key Data Points

- Backup: 86.2 GiB compressed, 2,356 files
- Tables with most chunks: `changeLog` (309), `salesRoutesAccess` (297)
- Largest single file: `contracts` (26 GiB)
- Rows per full chunk: 999,768-999,775 (≈1M as expected)

### Why Worker Appeared Dead

1. Worker started `synthesize_metadata()` at 19:05:35
2. Function calls `count_rows_in_file()` for ALL 2,356 files
3. For 86 GiB, this takes ~20 minutes (decompressing everything)
4. No events emitted during this time (no callback mechanism)
5. At 19:20:52 (15 min 17 sec later), another worker detected "stale" job
6. Stale recovery aborted the myloader process (which was actually running fine)

---

## Appendix B: myloader Metadata Requirements

From mydumper documentation and testing:

| Field | Required? | What We Provide |
|-------|-----------|-----------------|
| `[config]` section | No (but useful) | `quote-character`, `local-infile` |
| `[myloader_session_variables]` | No (but critical) | `SQL_MODE`, `foreign_key_checks`, etc. |
| `[source]` binlog info | No | Extracted from legacy metadata |
| `[db.table]` sections | No | Table names + row counts |
| Exact row counts | **NO** | Used only for progress display |

**Conclusion**: myloader works fine with estimated/zero row counts. The counts are purely for progress tracking (ours and myloader's internal progress bar).

---

## Appendix C: Related Documents

- [METADATA-SYNTHESIS-OPTIMIZATION-PLAN.md](METADATA-SYNTHESIS-OPTIMIZATION-PLAN.md) - Earlier analysis (to be archived)
- [KNOWLEDGE-POOL.md](KNOWLEDGE-POOL.md) - Stale Running Job Recovery section
- `.pulldb/standards/myloader.md` - myloader configuration standards
