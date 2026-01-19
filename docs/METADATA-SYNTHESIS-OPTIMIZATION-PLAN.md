# Metadata Synthesis Optimization Plan

**Created**: January 13, 2026  
**Updated**: January 19, 2026  
**Status**: PHASE 1-3 COMPLETE ✅  
**Root Cause**: 8-minute delay between `restore_started` and `restore_progress` for job 4616272e

---

## Implementation Status

| Phase | Description | Status | Date |
|-------|-------------|--------|------|
| **Phase 1** | ISIZE Optimization | ✅ COMPLETE | Jan 16, 2026 |
| **Phase 1B** | Sampling Enhancement | ⏸️ DEFERRED | — |
| **Phase 2** | Module Unification | ✅ COMPLETE | Jan 19, 2026 |
| **Phase 3** | Event Visibility | ✅ COMPLETE | Jan 19, 2026 |
| **Issue 2** | connect_timeout config | ❌ NOT STARTED | — |

### Phase 1 Completion Notes

Implemented in [metadata_synthesis.py](../pulldb/worker/metadata_synthesis.py) (now deprecated):
- `get_gzip_uncompressed_size()` — O(1) ISIZE reading
- `estimate_table_rows()` — Smart chunked/ISIZE heuristics
- Three-tier strategy: small files (count), medium files (ISIZE), large files (ISIZE)
- **Performance**: 86 GiB backup synthesis reduced from ~20 min to ~2 sec

Tests added in [test_metadata_synthesis.py](../tests/unit/worker/test_metadata_synthesis.py)

### Phase 2 Completion Notes (Jan 19, 2026)

Unified metadata handling into [backup_metadata.py](../pulldb/worker/backup_metadata.py):
- Replaces both `metadata_synthesis.py` and `dump_metadata.py` (both deprecated)
- Public API: `ensure_myloader_compatibility()`, `get_backup_metadata()`, `get_table_row_estimates()`, `parse_binlog_position()`
- Dataclasses: `MetadataFormat`, `BackupMetadata`, `TableRowEstimate`, `BinlogPosition`
- Backwards compatibility: aliases for old function names
- Updated [restore.py](../pulldb/worker/restore.py) to use new module

### Phase 3 Completion Notes (Jan 19, 2026)

Added event callback support for visibility:
- `ensure_myloader_compatibility()` now accepts `event_callback` parameter
- Emits `metadata_synthesis_started` and `metadata_synthesis_complete` events
- `restore.py` passes `_emit_event()` callback to metadata functions
- Events include: `backup_dir`, `action` (none_needed/upgraded/created), `format`

Tests added in [test_backup_metadata.py](../tests/unit/worker/test_backup_metadata.py)

---

## Research: Architecture Analysis (January 13, 2026)

### Key Question: Can we combine/simplify metadata handling?

**Answer: YES - there is significant duplication and over-engineering.**

### Current Architecture (Two Modules, Redundant Logic)

| Module | Purpose | Calls `count_rows_in_file()`? |
|--------|---------|------------------------------|
| `metadata_synthesis.py` | Create INI metadata for myloader | YES (line 96) |
| `dump_metadata.py` | Parse metadata for progress tracking | YES via fallback (line 161) |

**Problem**: We have TWO modules doing similar things with confusing responsibilities:

1. **`metadata_synthesis.py`** - Creates an INI file that myloader can use
2. **`dump_metadata.py`** - Parses metadata to get row counts for OUR progress bar

### Critical Discovery: What Does myloader Actually NEED?

From mydumper documentation research:

1. **Metadata file is NOT required for myloader to work** - myloader can scan the directory
2. **Rows in metadata are for PROGRESS DISPLAY only** - myloader docs: "rows" field is optional
3. **The [config] and [myloader_session_variables] sections ARE useful** - sets session variables

**Key insight from docs**:
> "Without this file, myloader v0.19 may fail or fall back to single-threaded mode"

But testing shows: **myloader 0.19 WORKS without metadata** - it discovers tables from files.

### What We're Actually Using Row Counts For

The row counts in the synthesized metadata are used for TWO purposes:

1. **myloader's internal progress** - But myloader doesn't require accurate counts
2. **OUR progress bar in the web UI** - This is the main consumer (restore.py lines 274-366)

**The irony**: We decompress ALL files to count rows so we can show a progress bar, which causes the very delay that makes users think the progress is stuck!

### Proposed Simplification: Single Unified Module

**Recommendation**: Merge `metadata_synthesis.py` and `dump_metadata.py` into one module with clear responsibilities:

```
pulldb/worker/backup_metadata.py  (NEW - replaces both)
├── ensure_myloader_compatibility()  # Quick: just config sections, no rows
├── get_table_row_estimates()        # O(1) per file using gzip ISIZE
└── parse_existing_metadata()        # Read 0.19+ INI if present
```

### What myloader ACTUALLY Requires vs What We Provide

| Requirement | Required? | What We Do | Simplification |
|-------------|-----------|------------|----------------|
| `[config]` section | Optional | Synthesize | Keep (useful) |
| `[myloader_session_variables]` | Optional | Synthesize | Keep (critical for consistency) |
| `[source]` binlog info | Optional | Extract from legacy | Keep (useful for replication) |
| `[db.table]` sections | Optional | Synthesize with exact rows | **SIMPLIFY: skip or use estimate** |
| Exact row counts | NO | Count every row | **ELIMINATE: use estimates** |

### Why We Over-Engineered This

Original assumption (from plan-metadata-synthesis.md):
> "Without this file, myloader v0.19 may fail or fall back to single-threaded mode"

**Reality**: myloader 0.19 discovers tables from filenames. The metadata file primarily:
1. Provides session variable defaults
2. Gives progress information (optional)
3. Enables table renaming (we don't use this)

---

## Audit Reflection (January 13, 2026)

### Verified Findings

1. **Call Chain Confirmed**:
   - `orchestrate_restore_workflow()` calls `run_myloader()` at line 594
   - `run_myloader()` calls `ensure_compatible_metadata()` at line 270
   - `ensure_compatible_metadata()` calls `synthesize_metadata()` at line 200
   - `synthesize_metadata()` calls `count_rows_in_file()` for EVERY `.sql.gz` file at line 96

2. **Gzip ISIZE Approach Validated**:
   - RFC 1952 confirms: ISIZE is last 4 bytes, little-endian uint32
   - Contains uncompressed size **modulo 2^32**
   - For files < 4GB, this is exact (most SQL files are under 4GB)
   - Python: `struct.unpack('<I', last_4_bytes)[0]`

3. **Event Flow Gap Confirmed**:
   - `_emit_event` helper defined at line 475 in `orchestrate_restore_workflow()`
   - `myloader_started` event emitted at line 585, but AFTER `run_myloader()` returns from `ensure_compatible_metadata()`
   - **GAP**: No event capability inside `run_myloader()` - no `event_callback` parameter

4. **connect_timeout_seconds NOT in Config**:
   - Searched `config.py` - no `connect_timeout` setting exists
   - Each module defines its own `DEFAULT_CONNECT_TIMEOUT_SECONDS = 30`
   - `StagingConnectionSpec` creation at executor.py ~907 does NOT pass any timeout

### What I Got Right
- Root cause identification (count_rows_in_file decompressing all files)
- ISIZE approach is correct per RFC 1952
- Event visibility gap is real
- File locations are correct

### What Needs Refinement
- **Row estimation heuristic needs validation**: The "150 bytes per row" estimate is arbitrary. Should analyze actual mydumper output patterns.
- **4GB wraparound handling**: Need fallback for files > 4GB where ISIZE wraps
- **connect_timeout_seconds**: Need to decide if this should be a global config or per-connection-type setting
- **CRITICAL: TWO callsites!**: `count_rows_in_file()` is called from TWO different modules:
  1. `metadata_synthesis.py:synthesize_metadata()` line 96 - Creating the metadata file
  2. `dump_metadata.py:_scan_dump_files()` line 161 - Reading for progress tracking

### Double-Counting Risk
The current flow for legacy 0.9 backups:
1. `ensure_compatible_metadata()` → `synthesize_metadata()` → calls `count_rows_in_file()` for ALL files
2. Then `parse_dump_metadata()` reads the newly-created INI file (fast)

So for 0.9 backups, row counting happens ONCE (in synthesis), then the INI is parsed.
The optimization should target `count_rows_in_file()` which is the shared bottleneck.

---

## Executive Summary

The restore workflow has a severe performance bottleneck in `metadata_synthesis.py`. The `count_rows_in_file()` function decompresses and reads **every line** of **every .sql.gz file** to count INSERT statements. For large backups with hundreds of gzipped SQL files, this takes **minutes** with zero user visibility.

---

## Problem Statement

### Symptom
- Job 4616272e showed 8-minute gap between `restore_started` and `restore_progress` events
- No events emitted during this period - appears "stuck" to users
- First-time restore (no orphan cleanup), so staging cleanup was not the cause

### Root Cause Discovery Path
1. Initially suspected staging cleanup → Added events → Not the cause (first-time restore)
2. Suspected myloader startup → Added `myloader_started` event → Still gap before this event
3. **Found actual cause**: `synthesize_metadata()` in `run_myloader()` calls `count_rows_in_file()` for every SQL file

### The Bug (metadata_synthesis.py:63-78)
```python
def count_rows_in_file(filepath: str) -> int:
    """Count INSERT statements in a SQL file to estimate row count."""
    count = 0
    try:
        with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:  # ← READS ENTIRE DECOMPRESSED FILE
                stripped = line.strip()
                if stripped.startswith("INSERT INTO") or stripped.startswith(",("):
                    count += 1
    except Exception:
        pass
    return count
```

**Impact**: O(total_uncompressed_size) - For a backup with 10GB of compressed SQL files that decompress to 50GB, this reads 50GB of data line-by-line before myloader even starts.

---

## Proposed Solutions

### Solution 1: Gzip ISIZE Optimization (PRIMARY - MINIMAL CHANGE)

Use the gzip file format's ISIZE field (last 4 bytes) to instantly get uncompressed size without decompression.

**Change `count_rows_in_file()` in place** - fixes both modules with one change.

**Implementation**:
```python
import struct

def get_gzip_uncompressed_size(filepath: str) -> int:
    """Read ISIZE from gzip trailer - O(1), no decompression.
    
    The ISIZE field contains the uncompressed size modulo 2^32.
    For files < 4GB, this is exact. For larger files, it wraps.
    
    RFC 1952: ISIZE is last 4 bytes, little-endian unsigned 32-bit integer.
    """
    try:
        with open(filepath, 'rb') as f:
            f.seek(-4, 2)  # Seek to last 4 bytes from end
            return struct.unpack('<I', f.read(4))[0]  # Little-endian uint32
    except Exception:
        return 0

def estimate_rows_from_size(uncompressed_size: int, bytes_per_row: int = 200) -> int:
    """Estimate row count from uncompressed SQL size.
    
    Heuristic: mydumper INSERT statements average ~200 bytes per row including:
    - INSERT INTO prefix (~30 bytes) amortized across extended inserts
    - Values tuple with typical data (~150-200 bytes)
    - Newline/continuation markers (~2-10 bytes)
    
    This is approximate but O(1) vs O(file_size) for counting.
    Accuracy: ±30-50% which is sufficient for progress bar estimation.
    """
    if uncompressed_size <= 0:
        return 0
    return max(1, uncompressed_size // bytes_per_row)
```

**Complexity**: O(1) per file - just read 4 bytes + 1 seek
**Accuracy**: Approximate (±30-50%) but sufficient for progress estimation
**Edge Cases**:
- Files > 4GB: ISIZE wraps (mod 2^32) - underestimates but still O(1)
- Corrupt gzip: Returns 0, falls back gracefully
- Empty file: Returns 0

### Solution 2: Skip Row Counting in Metadata Synthesis (ALTERNATIVE - MORE AGGRESSIVE)

**Key insight**: myloader doesn't NEED row counts. We only need them for OUR progress bar.

**Change**: Have `synthesize_metadata()` write `rows = 0` for all tables (or skip rows entirely). Then `parse_dump_metadata()` estimates rows separately using ISIZE.

**Pros**: 
- Zero additional I/O during synthesis
- Synthesis becomes instant (just write config sections)
- Progress estimation happens lazily only if needed

**Cons**: 
- Requires changes to two places
- Slightly different row estimates between metadata file and progress bar

### Solution 3: Unified Backup Metadata Module (BEST - ARCHITECTURAL FIX)

Merge both modules into a single coherent module with clear separation:

```python
# pulldb/worker/backup_metadata.py (NEW)

def ensure_myloader_compatibility(backup_dir: str) -> MetadataFormat:
    """Ensure backup has valid metadata for myloader. O(1) - no file scanning.
    
    - If 0.19+ INI exists: return as-is
    - If 0.9 legacy: create MINIMAL INI with just [config] and [myloader_session_variables]
    - Does NOT scan files or count rows
    
    Returns detected format for caller to know if row estimation is needed.
    """

def get_table_row_estimates(backup_dir: str) -> dict[str, int]:
    """Get row estimates for progress tracking. O(n) where n = file count.
    
    - If 0.19+ INI with rows: parse it (fast)
    - Otherwise: use gzip ISIZE estimation (fast)
    
    Called ONLY when progress tracking is needed, not for myloader itself.
    """

def parse_binlog_position(backup_dir: str) -> BinlogPosition | None:
    """Extract binlog position from metadata (any format)."""
```

**Benefits**:
1. **Clear separation**: myloader compatibility vs progress tracking
2. **Lazy evaluation**: Row estimation only when needed
3. **Single source of truth**: No duplicate logic
4. **Testable**: Each function has one job

**Migration Path**:
1. Create new `backup_metadata.py`
2. Update `restore.py` to use new module
3. Deprecate `metadata_synthesis.py` and `dump_metadata.py`
4. Remove old modules after validation

### Solution 4: Remove Row Counting Entirely (RADICAL)

**Observation**: myloader already provides file-based progress via stdout parsing. We already track `completed_tasks` (files) and `total_tasks` (files).

**Question**: Do we NEED row-based progress at all?

**Current flow**:
1. Count all rows (SLOW)
2. Track rows_restored during restore
3. Calculate rows/sec and ETA

**Simplified flow**:
1. Count files (instant: `len(list(path.glob('*.sql.gz')))`)
2. Track files restored
3. Calculate files/sec and ETA

**Pros**: Zero additional I/O, instant startup
**Cons**: Less granular ETA (but is row-based ETA even accurate with parallel threads?)

---

## Recommendation: Solution 1 + 3 Combined

**Phase 1 (Quick Win)**: Replace `count_rows_in_file()` with ISIZE-based estimation
- Fixes the immediate 8-minute delay
- Minimal code change, maximum impact

**Phase 2 (Architectural)**: Unify modules into `backup_metadata.py`
- Clean up the codebase
- Make responsibilities clear
- Enable future optimizations

---

## Additional Issues Found

### Issue 2: connect_timeout_seconds Not Configurable

**Location**: `pulldb/worker/executor.py` line ~907

**Problem**: `StagingConnectionSpec` is created without passing `connect_timeout_seconds`:
```python
staging_spec = StagingConnectionSpec(
    host=staging_endpoint.host,
    port=staging_endpoint.port,
    user=staging_user,
    password=staging_password,
    # MISSING: connect_timeout_seconds
)
```

**Result**: Always uses default 30 seconds, ignoring any config

**Fix Required**:
1. Add `connect_timeout_seconds` to `WorkerExecutorTimeouts` dataclass
2. Add config/env var support (e.g., `PULLDB_MYSQL_CONNECT_TIMEOUT`)
3. Pass through to `StagingConnectionSpec`

### Issue 3: No Events During Metadata Synthesis

**Location**: `pulldb/worker/restore.py` → `run_myloader()` → `synthesize_metadata()`

**Problem**: `run_myloader()` has no `event_callback` parameter, so cannot emit events

**Events Needed**:
- `metadata_synthesis_started` - Before synthesis begins
- `metadata_synthesis_file_progress` - Optional, during synthesis
- `metadata_synthesis_complete` - After synthesis finishes

---

## Phase 1: Detailed Implementation Plan

### Goal
Replace slow row-by-row counting with instant gzip ISIZE-based estimation. **Expected improvement: 8 minutes → <1 second.**

### Step 1.1: Add ISIZE Helper Functions

**File**: `pulldb/worker/metadata_synthesis.py`

Add these two new functions BEFORE `count_rows_in_file()`:

```python
import struct  # Add to imports at top

def get_gzip_uncompressed_size(filepath: str) -> int:
    """Read ISIZE from gzip trailer - O(1), no decompression.
    
    The gzip format (RFC 1952) stores the uncompressed size in the last 4 bytes
    as a little-endian unsigned 32-bit integer. This wraps at 4GB but most SQL
    files are smaller.
    
    Args:
        filepath: Path to a .gz file
        
    Returns:
        Uncompressed size in bytes, or 0 on error
    """
    try:
        with open(filepath, 'rb') as f:
            f.seek(-4, 2)  # Seek to last 4 bytes from end
            return struct.unpack('<I', f.read(4))[0]
    except Exception:
        return 0


def estimate_rows_from_size(uncompressed_size: int, bytes_per_row: int = 200) -> int:
    """Estimate row count from uncompressed SQL file size.
    
    Heuristic based on mydumper's extended INSERT format:
    - INSERT INTO `table` VALUES (data) → ~30 bytes header (amortized)
    - ,(data) continuation rows → ~150-200 bytes typical row data
    - Newlines and delimiters → ~5-10 bytes
    
    Args:
        uncompressed_size: Size of uncompressed SQL file in bytes
        bytes_per_row: Estimated bytes per INSERT row (default 200)
        
    Returns:
        Estimated row count, minimum 1 for non-empty files
    """
    if uncompressed_size <= 0:
        return 0
    return max(1, uncompressed_size // bytes_per_row)
```

### Step 1.2: Replace count_rows_in_file() Internals

**File**: `pulldb/worker/metadata_synthesis.py`

Replace the BODY of `count_rows_in_file()` while keeping the signature:

```python
def count_rows_in_file(filepath: str) -> int:
    """Count rows in a mydumper SQL file.
    
    Uses gzip ISIZE field for O(1) estimation instead of decompressing.
    The estimate is approximate but sufficient for progress tracking.
    
    Args:
        filepath: Path to a .sql.gz file
        
    Returns:
        Estimated row count based on uncompressed file size
    """
    uncompressed_size = get_gzip_uncompressed_size(filepath)
    return estimate_rows_from_size(uncompressed_size)
```

**Why keep the function name**: `dump_metadata.py` imports and uses `count_rows_in_file()`. By keeping the signature, we fix BOTH modules with one change.

### Step 1.3: Add Unit Tests

**File**: `tests/test_worker_metadata_synthesis.py`

Add new test functions:

```python
import struct
import tempfile
import os

def test_get_gzip_uncompressed_size() -> None:
    """Test ISIZE extraction from gzip files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test gzip file with known content
        filepath = os.path.join(tmpdir, "test.sql.gz")
        content = "INSERT INTO `t` VALUES (1);\n" * 100  # 2800 bytes uncompressed
        
        import gzip
        with gzip.open(filepath, 'wt') as f:
            f.write(content)
        
        # Read ISIZE
        from pulldb.worker.metadata_synthesis import get_gzip_uncompressed_size
        size = get_gzip_uncompressed_size(filepath)
        
        # Should be approximately the content length
        assert size == len(content.encode('utf-8'))


def test_get_gzip_uncompressed_size_missing_file() -> None:
    """Test ISIZE returns 0 for missing files."""
    from pulldb.worker.metadata_synthesis import get_gzip_uncompressed_size
    assert get_gzip_uncompressed_size("/nonexistent/file.gz") == 0


def test_estimate_rows_from_size() -> None:
    """Test row estimation from file size."""
    from pulldb.worker.metadata_synthesis import estimate_rows_from_size
    
    # 200 bytes per row default
    assert estimate_rows_from_size(200) == 1
    assert estimate_rows_from_size(400) == 2
    assert estimate_rows_from_size(2000) == 10
    assert estimate_rows_from_size(0) == 0
    assert estimate_rows_from_size(-100) == 0


def test_count_rows_in_file_uses_estimation() -> None:
    """Test that count_rows_in_file now uses fast estimation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.sql.gz")
        # Create file with ~10 rows worth of data (2000 bytes)
        content = "x" * 2000
        
        import gzip
        with gzip.open(filepath, 'wt') as f:
            f.write(content)
        
        from pulldb.worker.metadata_synthesis import count_rows_in_file
        rows = count_rows_in_file(filepath)
        
        # Should be approximately 10 (2000 / 200)
        assert rows == 10
```

### Step 1.4: Update Existing Tests

**File**: `tests/test_worker_metadata_synthesis.py`

The existing `test_count_rows_in_file()` tests expect EXACT row counts. Update expectations to accept estimates:

```python
def test_count_rows_in_file() -> None:
    """Test row counting returns reasonable estimates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Case 1: Simple inserts - estimation based on file size
        f1 = os.path.join(tmpdir, "simple.sql.gz")
        content1 = "INSERT INTO `t` VALUES (1);\nINSERT INTO `t` VALUES (2);\n"
        create_dummy_sql_gz(f1, content1)
        rows1 = count_rows_in_file(f1)
        # Estimate: ~60 bytes / 200 = 0, but min is 1 for non-empty
        # Accept any positive value since this is now estimation
        assert rows1 >= 1

        # Case 2: Extended inserts - larger file
        f2 = os.path.join(tmpdir, "extended.sql.gz")
        content2 = "INSERT INTO `t` VALUES (1)\n,(2)\n,(3);\n"
        create_dummy_sql_gz(f2, content2)
        rows2 = count_rows_in_file(f2)
        assert rows2 >= 1
```

### Step 1.5: Benchmark Verification

**Manual test script** (not committed, run locally):

```python
#!/usr/bin/env python3
"""Benchmark metadata synthesis before/after optimization."""
import time
import tempfile
import gzip
import os

# Create test directory with realistic file sizes
def create_test_backup(num_files: int, bytes_per_file: int) -> str:
    tmpdir = tempfile.mkdtemp()
    for i in range(num_files):
        filepath = os.path.join(tmpdir, f"db.table{i}.sql.gz")
        content = "INSERT INTO `t` VALUES (1)\n" + ",(x)\n" * (bytes_per_file // 5)
        with gzip.open(filepath, 'wt') as f:
            f.write(content)
    return tmpdir

# Test with 100 files, 1MB each = 100MB total
backup_dir = create_test_backup(100, 1_000_000)

start = time.monotonic()
from pulldb.worker.metadata_synthesis import synthesize_metadata
synthesize_metadata(backup_dir, os.path.join(backup_dir, "metadata"))
elapsed = time.monotonic() - start

print(f"Synthesis time: {elapsed:.2f}s")
# Before: ~60-120 seconds
# After:  <0.5 seconds
```

### Phase 1 Checklist

- [ ] Add `import struct` to metadata_synthesis.py imports
- [ ] Add `get_gzip_uncompressed_size()` function
- [ ] Add `estimate_rows_from_size()` function  
- [ ] Replace `count_rows_in_file()` body with ISIZE estimation
- [ ] Add new unit tests for helper functions
- [ ] Update existing tests to accept estimates instead of exact counts
- [ ] Run full test suite: `pytest tests/qa/worker tests/qa/web`
- [ ] Manual benchmark with realistic backup sizes
- [ ] Deploy and verify job 4616272e-style delays are resolved

---

## Phase 1B: Sampling Enhancement (OPTIONAL - Improved Accuracy)

### Goal
Improve row estimation accuracy from ±50% to ±15% by sampling actual file content instead of using hardcoded 200 bytes/row.

### Why Sampling Beats Schema Parsing

**User question**: Could we read the schema file's CREATE TABLE and calculate row width from column types?

**Analysis with maximum effort**: This is intellectually elegant but fundamentally flawed:

#### The Core Problem: We're Estimating SQL Text Size, Not Storage Size

The ISIZE gives us **uncompressed SQL dump size**, which looks like:
```sql
INSERT INTO `users` VALUES (1,'alice','alice@example.com','2025-01-01'),
(2,'bob','bob@example.com','2025-01-02');
```

Schema parsing would give us **InnoDB storage size**, which is completely different:

| Data Type | InnoDB Storage | SQL Dump Text |
|-----------|----------------|---------------|
| `INT` value `12345` | 4 bytes | 5 bytes (`12345`) |
| `BIGINT` value `1` | 8 bytes | 1 byte (`1`) |
| `VARCHAR(255)` with `'hello'` | 6 bytes | 7 bytes (`'hello'`) |
| `DATETIME` | 5 bytes | 21 bytes (`'2025-01-13 10:30:00'`) |
| `DECIMAL(10,2)` `123.45` | 5 bytes | 6 bytes (`123.45`) |
| `NULL` | 1 bit | 4 bytes (`NULL`) |

**The relationship is inverted** - storage-small types (DATETIME: 5 bytes) become text-large (21 bytes), and vice versa.

#### Variable-Length Data Dominates

Schema tells you `notes VARCHAR(4000)`, but actual data might be:
- 90% of rows: 20 characters
- 9% of rows: 200 characters  
- 1% of rows: 3000 characters

Schema gives MAX (4000), **average is ~50**. Schema parsing cannot help.

#### SQL Dump Overhead Varies

Mydumper settings affect bytes-per-row overhead (extended inserts vs. single-row INSERTs), which schema cannot predict.

### The Right Solution: Sample the Data Itself

Read first ~8KB of decompressed data, count actual rows, extrapolate using ISIZE.

**Cost**: ~8KB decompression per file (~5ms)
**Accuracy**: ±15% (vs. ±50% for hardcoded 200 bytes/row)

### Step 1B.1: Add Sampling Function

**File**: `pulldb/worker/metadata_synthesis.py`

```python
def estimate_rows_by_sampling(
    filepath: str,
    sample_bytes: int = 8192,
    fallback_bytes_per_row: int = 200,
) -> int:
    """Estimate row count by sampling first N bytes of SQL file.
    
    More accurate than pure ISIZE/200 because it measures actual row density
    in the specific file's format (extended inserts, column count, data types).
    
    Args:
        filepath: Path to gzip-compressed SQL file
        sample_bytes: How many uncompressed bytes to sample (default 8KB)
        fallback_bytes_per_row: Fallback if sampling fails
        
    Returns:
        Estimated row count
    """
    import gzip
    
    total_size = get_gzip_uncompressed_size(filepath)
    if total_size == 0:
        return 0
    
    try:
        with gzip.open(filepath, 'rt', encoding='utf-8', errors='replace') as f:
            sample = f.read(sample_bytes)
    except Exception as e:
        logger.warning(f"Sampling failed for {filepath}: {e}, using fallback")
        return estimate_rows_from_size(total_size, fallback_bytes_per_row)
    
    if not sample:
        return estimate_rows_from_size(total_size, fallback_bytes_per_row)
    
    # Count row indicators in sample
    # Mydumper format: "INSERT INTO ... VALUES (...)" or ",(...)"
    rows_in_sample = sample.count("),(") + sample.count("INSERT INTO")
    
    if rows_in_sample == 0:
        # No rows found in sample, use fallback
        return estimate_rows_from_size(total_size, fallback_bytes_per_row)
    
    # Calculate bytes per row from sample
    sample_len = len(sample.encode('utf-8'))
    bytes_per_row_measured = sample_len / rows_in_sample
    
    # Extrapolate to full file
    estimated_rows = int(total_size / bytes_per_row_measured)
    
    logger.debug(
        f"Sampled {filepath}: {rows_in_sample} rows in {sample_len} bytes "
        f"({bytes_per_row_measured:.1f} bytes/row) → {estimated_rows} total"
    )
    
    return max(1, estimated_rows)
```

### Step 1B.2: Update count_rows_in_file to Use Sampling

```python
def count_rows_in_file(filepath: str) -> int:
    """Count rows in a mydumper SQL file using sampling.
    
    Uses fast sampling method: reads first 8KB, counts rows, extrapolates.
    Much faster than iterating full file while maintaining good accuracy.
    
    Args:
        filepath: Path to gzip-compressed SQL file
        
    Returns:
        Estimated row count
    """
    return estimate_rows_by_sampling(filepath)
```

### Step 1B.3: Add Tests for Sampling

```python
def test_estimate_rows_by_sampling_accuracy() -> None:
    """Test that sampling gives reasonable accuracy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.sql.gz")
        
        # Create file with known row count: 1000 rows
        rows = [f"({i},'value{i}')" for i in range(1000)]
        content = "INSERT INTO `t` VALUES " + ",".join(rows) + ";\n"
        
        import gzip
        with gzip.open(filepath, 'wt') as f:
            f.write(content)
        
        from pulldb.worker.metadata_synthesis import estimate_rows_by_sampling
        estimated = estimate_rows_by_sampling(filepath)
        
        # Should be within 20% of actual
        assert 800 <= estimated <= 1200, f"Expected ~1000, got {estimated}"


def test_estimate_rows_by_sampling_extended_inserts() -> None:
    """Test sampling with extended INSERT format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "extended.sql.gz")
        
        # Extended insert format: INSERT ... VALUES (...),(...),(...)
        rows = 500
        content = "INSERT INTO `users` VALUES " + ",".join(
            f"({i},'user{i}','user{i}@example.com')" for i in range(rows)
        ) + ";\n"
        
        import gzip
        with gzip.open(filepath, 'wt') as f:
            f.write(content)
        
        from pulldb.worker.metadata_synthesis import estimate_rows_by_sampling
        estimated = estimate_rows_by_sampling(filepath)
        
        # Should be within 20% of actual 500
        assert 400 <= estimated <= 600


def test_estimate_rows_by_sampling_fallback() -> None:
    """Test fallback when sampling finds no rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "norows.sql.gz")
        
        # File with no INSERT statements
        content = "-- This is a comment\n" * 100
        
        import gzip
        with gzip.open(filepath, 'wt') as f:
            f.write(content)
        
        from pulldb.worker.metadata_synthesis import estimate_rows_by_sampling
        estimated = estimate_rows_by_sampling(filepath)
        
        # Should fall back to size-based estimate
        assert estimated >= 1
```

### Accuracy Comparison

| Approach | Accuracy | Runtime | Complexity |
|----------|----------|---------|------------|
| **Full decompression** (current) | 100% exact | O(n) - minutes | Low |
| **ISIZE / 200** (Phase 1) | ±50% | O(1) - instant | Low |
| **Schema parsing** (rejected) | ±40%* | O(1) + parse | High |
| **8KB sampling** (Phase 1B) | ±15% | O(1) + 5ms | Low |

*Schema parsing gives MAX row size, not average - fundamentally wrong approach.

### When to Use Phase 1B

**Phase 1 (ISIZE/200)** is sufficient if:
- Progress bars just need rough estimates
- User tolerance for ±50% accuracy is acceptable
- Minimal code change is preferred

**Phase 1B (Sampling)** is worth it if:
- Users report progress bars jumping erratically
- More accurate ETAs are desired
- The extra ~5ms/file is acceptable

### Phase 1B Checklist

- [ ] Add `estimate_rows_by_sampling()` function
- [ ] Update `count_rows_in_file()` to use sampling instead of pure ISIZE
- [ ] Add accuracy tests with known row counts
- [ ] Add fallback tests for edge cases
- [ ] Benchmark sampling overhead (~5ms/file expected)
- [ ] Consider making sample_bytes configurable via config

---

## Phase 2: Detailed Implementation Plan

### Goal
Unify `metadata_synthesis.py` and `dump_metadata.py` into a single coherent module with clear responsibilities.

### Why This Matters
- Current: Two modules with overlapping logic, confusing names
- After: One module, clear functions, easier maintenance

### Step 2.1: Create New Module Structure

**New File**: `pulldb/worker/backup_metadata.py`

```python
"""Backup metadata handling for myloader compatibility and progress tracking.

This module provides a unified interface for:
1. Ensuring backups are compatible with myloader 0.19+
2. Extracting row estimates for progress tracking
3. Parsing binlog positions for replication setup

HCA Layer: features (pulldb/worker/)

Replaces:
- metadata_synthesis.py (deprecated)
- dump_metadata.py (deprecated)
"""

from __future__ import annotations

import configparser
import os
import re
import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pulldb.infra.logging import get_logger

logger = get_logger("pulldb.worker.backup_metadata")


class MetadataFormat(Enum):
    """Detected backup metadata format."""
    INI_0_19 = "0.19+"      # Modern INI format with rows
    LEGACY_0_9 = "0.9"      # Legacy text format
    MISSING = "missing"      # No metadata file
    UNKNOWN = "unknown"      # Unrecognized format


@dataclass(slots=True, frozen=True)
class BinlogPosition:
    """MySQL binlog position from backup metadata."""
    file: str
    position: int
    gtid_set: str = ""


@dataclass(slots=True, frozen=True)
class TableRowEstimate:
    """Row estimate for a single table."""
    database: str
    table: str
    rows: int


@dataclass(slots=True, frozen=True)
class BackupMetadata:
    """Complete parsed backup metadata."""
    format: MetadataFormat
    tables: list[TableRowEstimate]
    total_rows: int
    binlog: BinlogPosition | None


# ============================================================================
# Core Functions
# ============================================================================

def ensure_myloader_compatibility(backup_dir: str) -> MetadataFormat:
    """Ensure backup has valid metadata for myloader 0.19+.
    
    This is a FAST operation - O(1), no file scanning.
    
    If metadata is missing or in legacy format, creates a minimal INI file
    with just [config] and [myloader_session_variables] sections.
    Table sections are NOT required for myloader to function.
    
    Args:
        backup_dir: Path to extracted backup directory
        
    Returns:
        Detected/created metadata format
    """
    ...


def get_backup_metadata(backup_dir: str) -> BackupMetadata:
    """Get complete backup metadata including row estimates.
    
    Tries to parse existing metadata first. Falls back to ISIZE estimation.
    
    Args:
        backup_dir: Path to extracted backup directory
        
    Returns:
        BackupMetadata with tables, row estimates, and binlog position
    """
    ...


def get_table_row_estimates(backup_dir: str) -> list[TableRowEstimate]:
    """Get row estimates for all tables in backup.
    
    Uses fastest available method:
    1. If 0.19+ INI exists with rows: parse it
    2. Otherwise: use gzip ISIZE estimation
    
    Args:
        backup_dir: Path to extracted backup directory
        
    Returns:
        List of TableRowEstimate for each table
    """
    ...


def parse_binlog_position(backup_dir: str) -> BinlogPosition | None:
    """Extract binlog position from backup metadata.
    
    Supports both legacy text format and INI format.
    
    Args:
        backup_dir: Path to extracted backup directory
        
    Returns:
        BinlogPosition if found, None otherwise
    """
    ...


# ============================================================================
# Internal Helpers
# ============================================================================

def _detect_metadata_format(backup_dir: str) -> MetadataFormat:
    """Detect the format of existing metadata file."""
    ...


def _get_gzip_uncompressed_size(filepath: str) -> int:
    """Read ISIZE from gzip trailer - O(1), no decompression."""
    try:
        with open(filepath, 'rb') as f:
            f.seek(-4, 2)
            return struct.unpack('<I', f.read(4))[0]
    except Exception:
        return 0


def _estimate_rows_from_size(uncompressed_size: int) -> int:
    """Estimate row count from uncompressed SQL file size."""
    if uncompressed_size <= 0:
        return 0
    return max(1, uncompressed_size // 200)


def _parse_mydumper_filename(filename: str) -> tuple[str, str] | None:
    """Parse mydumper filename to extract database.table."""
    ...


def _write_minimal_metadata(backup_dir: str, binlog: BinlogPosition | None) -> None:
    """Write minimal INI metadata for myloader compatibility."""
    ...


def _parse_ini_metadata(metadata_path: Path) -> list[TableRowEstimate]:
    """Parse 0.19+ INI format metadata for row counts."""
    ...


def _scan_for_row_estimates(backup_dir: Path) -> list[TableRowEstimate]:
    """Scan backup files and estimate rows using ISIZE."""
    ...
```

### Step 2.2: Implement Core Functions

**Function: `ensure_myloader_compatibility()`**

```python
def ensure_myloader_compatibility(backup_dir: str) -> MetadataFormat:
    """Ensure backup has valid metadata for myloader 0.19+."""
    metadata_path = Path(backup_dir) / "metadata"
    detected = _detect_metadata_format(backup_dir)
    
    if detected == MetadataFormat.INI_0_19:
        logger.debug(f"Backup already has 0.19+ metadata: {backup_dir}")
        return detected
    
    # Need to create/upgrade metadata
    binlog = parse_binlog_position(backup_dir)
    
    if detected == MetadataFormat.LEGACY_0_9:
        logger.info(f"Upgrading legacy 0.9 metadata to INI format: {backup_dir}")
    else:
        logger.info(f"Creating minimal metadata for myloader: {backup_dir}")
    
    _write_minimal_metadata(backup_dir, binlog)
    return MetadataFormat.INI_0_19
```

**Function: `_write_minimal_metadata()`**

```python
def _write_minimal_metadata(backup_dir: str, binlog: BinlogPosition | None) -> None:
    """Write minimal INI metadata - NO row counting, instant."""
    config = configparser.ConfigParser()
    config.optionxform = str  # Preserve case
    
    # Essential config for myloader
    config["config"] = {
        "quote-character": "BACKTICK",
        "local-infile": "1",
    }
    
    # Session variables for consistent restore
    config["myloader_session_variables"] = {
        "SQL_MODE": "'NO_AUTO_VALUE_ON_ZERO,' /*!40101",
        "foreign_key_checks": "0",
        "time_zone": "'+00:00'",
        "sql_log_bin": "0",
    }
    
    # Binlog position if available
    config["source"] = {
        "File": binlog.file if binlog else "",
        "Position": str(binlog.position) if binlog else "",
        "Executed_Gtid_Set": binlog.gtid_set if binlog else "",
    }
    
    # NOTE: We intentionally skip table sections here.
    # myloader discovers tables from filenames.
    # Row counts are only needed for progress tracking.
    
    metadata_path = Path(backup_dir) / "metadata"
    with open(metadata_path, "w") as f:
        config.write(f)
    
    logger.info(f"Wrote minimal metadata to {metadata_path}")
```

### Step 2.3: Update restore.py to Use New Module

**File**: `pulldb/worker/restore.py`

Change imports:

```python
# OLD
from pulldb.worker.metadata_synthesis import ensure_compatible_metadata
from pulldb.worker.dump_metadata import parse_dump_metadata

# NEW
from pulldb.worker.backup_metadata import (
    ensure_myloader_compatibility,
    get_backup_metadata,
)
```

Change usage in `run_myloader()`:

```python
# OLD (lines 267-275)
version_info = _detect_backup_version(spec.backup_dir)
logger.info(f"Detected backup version info: {version_info}")
ensure_compatible_metadata(spec.backup_dir)
dump_meta = parse_dump_metadata(spec.backup_dir)
total_rows = dump_meta.total_rows

# NEW
metadata = get_backup_metadata(spec.backup_dir)
logger.info(f"Backup format: {metadata.format.value}, {len(metadata.tables)} tables")
total_rows = metadata.total_rows
```

### Step 2.4: Deprecate Old Modules

**File**: `pulldb/worker/metadata_synthesis.py`

Add deprecation warning at top:

```python
"""DEPRECATED: Use pulldb.worker.backup_metadata instead.

This module will be removed in a future version.
"""
import warnings
warnings.warn(
    "metadata_synthesis is deprecated, use backup_metadata instead",
    DeprecationWarning,
    stacklevel=2,
)

# Keep existing code for backward compatibility during transition
```

**File**: `pulldb/worker/dump_metadata.py`

Same deprecation pattern.

### Step 2.5: Migration Tests

**New File**: `tests/test_backup_metadata.py`

```python
"""Tests for unified backup_metadata module."""
import tempfile
import gzip
import os
from pathlib import Path

import pytest

from pulldb.worker.backup_metadata import (
    MetadataFormat,
    ensure_myloader_compatibility,
    get_backup_metadata,
    get_table_row_estimates,
    parse_binlog_position,
)


class TestMetadataFormatDetection:
    """Test format detection for various backup types."""
    
    def test_detect_ini_format(self, tmp_path: Path) -> None:
        """Detect 0.19+ INI format metadata."""
        metadata = tmp_path / "metadata"
        metadata.write_text("[config]\nquote-character = BACKTICK\n")
        
        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19
    
    def test_detect_legacy_format(self, tmp_path: Path) -> None:
        """Detect and upgrade 0.9 legacy format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("Started dump at: 2025-01-01\nLog: bin.000001\nPos: 123\n")
        
        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19
        
        # Verify upgrade happened
        content = metadata.read_text()
        assert "[config]" in content
    
    def test_create_metadata_when_missing(self, tmp_path: Path) -> None:
        """Create minimal metadata when missing."""
        # Create a data file so it looks like a backup
        data_file = tmp_path / "db.table.sql.gz"
        with gzip.open(data_file, 'wt') as f:
            f.write("INSERT INTO t VALUES (1);")
        
        result = ensure_myloader_compatibility(str(tmp_path))
        assert result == MetadataFormat.INI_0_19
        
        metadata = tmp_path / "metadata"
        assert metadata.exists()


class TestRowEstimation:
    """Test ISIZE-based row estimation."""
    
    def test_estimate_from_ini(self, tmp_path: Path) -> None:
        """Use row counts from INI metadata when available."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""
[config]
quote-character = BACKTICK

[`mydb`.`users`]
rows = 1000

[`mydb`.`orders`]
rows = 5000
""")
        
        estimates = get_table_row_estimates(str(tmp_path))
        total = sum(e.rows for e in estimates)
        assert total == 6000
    
    def test_estimate_from_isize(self, tmp_path: Path) -> None:
        """Fall back to ISIZE estimation when no INI rows."""
        # Create gzip file with known size
        data_file = tmp_path / "db.table.sql.gz"
        content = "x" * 2000  # 2000 bytes = ~10 rows at 200 bytes/row
        with gzip.open(data_file, 'wt') as f:
            f.write(content)
        
        estimates = get_table_row_estimates(str(tmp_path))
        assert len(estimates) == 1
        assert estimates[0].rows == 10


class TestBinlogParsing:
    """Test binlog position extraction."""
    
    def test_parse_legacy_binlog(self, tmp_path: Path) -> None:
        """Parse binlog from legacy format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("Started dump at: 2025-01-01\nLog: bin.000001\nPos: 123456\n")
        
        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is not None
        assert binlog.file == "bin.000001"
        assert binlog.position == 123456
    
    def test_parse_ini_binlog(self, tmp_path: Path) -> None:
        """Parse binlog from INI format."""
        metadata = tmp_path / "metadata"
        metadata.write_text("""
[source]
File = mysql-bin.000042
Position = 987654
Executed_Gtid_Set = abc-123:1-100
""")
        
        binlog = parse_binlog_position(str(tmp_path))
        assert binlog is not None
        assert binlog.file == "mysql-bin.000042"
        assert binlog.position == 987654
        assert binlog.gtid_set == "abc-123:1-100"
```

### Phase 2 Checklist

- [ ] Create `pulldb/worker/backup_metadata.py` with module docstring
- [ ] Implement `MetadataFormat` enum and dataclasses
- [ ] Implement `_get_gzip_uncompressed_size()` (copy from Phase 1)
- [ ] Implement `_estimate_rows_from_size()` (copy from Phase 1)
- [ ] Implement `_detect_metadata_format()`
- [ ] Implement `_parse_mydumper_filename()`
- [ ] Implement `_write_minimal_metadata()` - NO row counting
- [ ] Implement `_parse_ini_metadata()`
- [ ] Implement `_scan_for_row_estimates()` - uses ISIZE
- [ ] Implement `ensure_myloader_compatibility()`
- [ ] Implement `get_backup_metadata()`
- [ ] Implement `get_table_row_estimates()`
- [ ] Implement `parse_binlog_position()`
- [ ] Create `tests/test_backup_metadata.py`
- [ ] Update `restore.py` imports and usage
- [ ] Add deprecation warnings to `metadata_synthesis.py`
- [ ] Add deprecation warnings to `dump_metadata.py`
- [ ] Run full test suite
- [ ] Update WORKSPACE-INDEX.md with new module
- [ ] Monitor for any import errors in production
- [ ] Schedule removal of deprecated modules (2 weeks after deploy)

---

### Phase 5: Index Rebuild Tracking & ANALYZE TABLE - Detailed Implementation

#### Problem Statement

Currently, `ProcesslistMonitor` tracks `INSERT` and `LOAD DATA` statements to determine table completion. However, myloader uses `--optimize-keys=AFTER_IMPORT_PER_TABLE` (configured in `config.py:145,445`), which means:

1. **Table created WITHOUT indexes** (fast bulk load)
2. **Data loaded via INSERT/LOAD** (what we currently track)
3. **Indexes added via ALTER TABLE ... ADD KEY** (NOT tracked - table shows "finished" prematurely)
4. **Statistics are stale** after bulk import (no ANALYZE TABLE)

**Example processlist during index rebuild:**
```
| Query | 445 | altering table | ALTER TABLE changeLog ADD KEY class (class), ADD KEY category (category), ... |
```

This phase of table restoration can take significant time for large tables with many indexes, but the UI shows the table as "finished" when data load completes.

#### myloader Verbose Output Signals (Primary Detection Method)

myloader's verbose output provides **explicit signals** for index rebuild phase transitions. This is more reliable than processlist monitoring because it announces phase changes directly.

**Source Code Reference (mydumper/mydumper repository):**

The relevant logging functions are located in these source files:

| File | Function | Message |
|------|----------|---------|
| `myloader_worker_index.c` | `create_index_job()` | `"Thread %d: Enqueuing index for table: %s.%s"` |
| `myloader_worker_index.c` | `process_index()` | `"restoring index: %s.%s"` |
| `myloader_restore_job.c` | `process_restore_job()` | `"Thread %d: restoring %s %s.%s from %s. Tables %d of %d completed"` (for INDEXES type) |
| `myloader_restore_job.c` | `process_restore_job()` | `"Thread %d: restoring %s.%s part %d of %d from %s \| Progress %llu of %llu. Tables %d of %d completed"` |
| `myloader_worker_loader.c` | `loader_thread()` | `"L-Thread %u: ending"` |

**Key Source Code Snippets:**

From `myloader_worker_index.c:create_index_job()`:
```c
message("Thread %d: Enqueuing index for table: %s.%s", tdid,
  dbt->database->target_database, dbt->table_filename);
```

From `myloader_worker_index.c:process_index()`:
```c
g_message("restoring index: %s.%s",
  dbt->database->source_database, dbt->table_filename);
```

From `myloader_restore_job.c:process_restore_job()` (JOB_RESTORE_STRING for INDEXES):
```c
message("Thread %d: restoring %s %s.%s from %s. Tables %d of %d completed", td->thread_id,
  rjstmtype2str(rj->data.srj->object), dbt->database->target_database,
  dbt->source_table_name, rj->filename, total, g_hash_table_size(td->conf->table_hash));
```

From `myloader_restore_job.c:process_restore_job()` (JOB_RESTORE_FILENAME - data loading):
```c
message("Thread %d: restoring %s.%s part %d of %d from %s | Progress %llu of %llu. Tables %d of %d completed",
  td->thread_id,
  dbt->database->target_database, dbt->source_table_name, rj->data.drj->index, dbt->count, rj->filename,
  progress, total_data_sql_files, total, g_hash_table_size(td->conf->table_hash));
```

From `myloader_worker_loader.c:loader_thread()`:
```c
g_message("L-Thread %u: Starting import", td->thread_id);
// ... at end:
g_message("L-Thread %u: ending", td->thread_id);
```

**Note on "Data import ended":** This message appears to come from the loader thread ending, which is printed as `"L-Thread %u: ending"`. The exact "Data import ended" text may be from an older version or interpreted log output. The key signals to detect are:

1. `"Enqueuing index for table:"` - Table data loading complete, index rebuild queued
2. `"restoring index:"` - Index rebuild starting
3. `"restoring indexes"` - Index rebuild in progress (when verbose level shows this)
4. `"L-Thread %u: ending"` - Loader thread completed all work

**Example myloader verbose output during index rebuild:**
```
** Message: 06:02:13.767: Thread 2: restoring brunodfoxpest_655929085e57.salesRoutesAccess part 56 of 297 from foxpest.salesRoutesAccess.00159.sql.gz | Progress 600 of 606. Tables 507 of 509 completed
** Message: 06:02:20.155: Thread 0: Enqueuing index for table: brunodfoxpest_655929085e57.changeLog
** Message: 06:02:20.155: restoring index: foxpest.changeLog
** Message: 06:02:20.155: Thread 9: restoring indexes brunodfoxpest_655929085e57.changeLog from index. Tables 507 of 509 completed
...
** Message: 06:04:21.888: L-Thread 1: ending
** Message: 06:04:21.888: L-Thread 2: ending
** Message: 06:04:30.889: Thread 0: Enqueuing index for table: brunodfoxpest_655929085e57.salesRoutesAccess
** Message: 06:04:30.889: restoring index: foxpest.salesRoutesAccess
** Message: 06:04:30.889: Thread 10: restoring indexes brunodfoxpest_655929085e57.salesRoutesAccess from index. Tables 507 of 509 completed
```

**Key log patterns to parse:**

| Pattern | Signal | Source Function | Information |
|---------|--------|-----------------|-------------|
| `Thread %d: Enqueuing index for table: %s.%s` | Index rebuild queued | `create_index_job()` | Table data complete, entering index phase |
| `restoring index: %s.%s` | Index rebuild starting | `process_index()` | Source database.table being indexed |
| `restoring indexes %s.%s from index` | Index rebuild active | `process_restore_job()` | Target table being indexed |
| `restoring %s.%s part %d of %d` | Data loading progress | `process_restore_job()` | Part X of Y for multi-file tables |
| `Progress %llu of %llu` | Overall progress | `process_restore_job()` | Files processed of total |
| `Tables %d of %d completed` | Table completion count | `process_restore_job()` | Tables fully restored |
| `L-Thread %u: ending` | Thread finished | `loader_thread()` | Loader thread completed |

**Regex patterns for log parsing:**

```python
# In processlist_monitor.py or new myloader_log_parser.py

import re

# Pattern: "Thread 0: Enqueuing index for table: brunodfoxpest_655929085e57.changeLog"
RE_ENQUEUE_INDEX = re.compile(
    r"Thread\s+\d+:\s+Enqueuing index for table:\s+([^\s.]+)\.([^\s]+)",
    re.IGNORECASE
)

# Pattern: "restoring index: foxpest.changeLog"
RE_RESTORING_INDEX = re.compile(
    r"restoring index:\s+([^\s.]+)\.([^\s]+)",
    re.IGNORECASE
)

# Pattern: "restoring indexes brunodfoxpest_655929085e57.changeLog from index"  
RE_RESTORING_INDEXES = re.compile(
    r"restoring indexes\s+([^\s.]+)\.([^\s]+)\s+from index",
    re.IGNORECASE
)

# Pattern: "restoring db.table part X of Y from file | Progress A of B. Tables C of D completed"
RE_DATA_PROGRESS = re.compile(
    r"restoring\s+([^\s.]+)\.([^\s]+)\s+part\s+(\d+)\s+of\s+(\d+)\s+from\s+([^\s|]+)\s*\|\s*Progress\s+(\d+)\s+of\s+(\d+)\.\s*Tables\s+(\d+)\s+of\s+(\d+)",
    re.IGNORECASE
)

# Pattern: "L-Thread N: ending" (loader thread finished)
RE_LOADER_THREAD_ENDING = re.compile(
    r"L-Thread\s+(\d+):\s+ending",
    re.IGNORECASE
)

# Pattern: "I-Thread N: ending" (index thread finished, from worker_index_thread)
RE_INDEX_THREAD_ENDING = re.compile(
    r"I-Thread\s+(\d+):\s+ending",
    re.IGNORECASE  
)
```

**Detection strategy (dual-source):**

1. **Primary: myloader log parsing** - Most reliable, explicit phase signals
   - Parse stdout stream as myloader runs
   - Detect "Enqueuing index" → emit `table_index_rebuild_started`
   - Track which tables are in index phase
   
2. **Secondary: processlist monitoring** - Provides running time, handles edge cases
   - Continue polling processlist for ALTER TABLE
   - Use `Time` column to show elapsed seconds
   - Catches cases where log parsing misses events

**Implementation note:** Since we already capture myloader stdout for logging, we can parse these patterns in the existing output handler without additional I/O.

#### Solution Architecture

```
                          ProcesslistMonitor State Machine
                          ═══════════════════════════════
                          
    ┌─────────────────┐        ┌──────────────────────┐        ┌─────────────┐
    │  loading_data   │───────▶│  rebuilding_indexes  │───────▶│  complete   │
    │ (INSERT/LOAD)   │        │ (ALTER TABLE ADD KEY)│        │             │
    └─────────────────┘        └──────────────────────┘        └─────────────┘
           │                            │                              │
           │ emit: table_load_          │ emit: table_index_           │ (internal state)
           │   progress_XX%             │   rebuild_started            │
           │ emit: table_load_          │ emit: table_index_           │
           │   complete                 │   rebuild_complete           │
           ▼                            ▼                              ▼
    
    Post-Restore:
    ═══════════════
    After ALL tables complete → Execute ANALYZE TABLE per table → emit: table_analyze_*
```

#### MySQL ANALYZE TABLE Reference

**Syntax:**
```sql
ANALYZE [NO_WRITE_TO_BINLOG | LOCAL] TABLE tbl_name [, tbl_name] ...
```

**Key behaviors (InnoDB):**
- Updates index cardinality statistics via random dives
- Can batch multiple tables in one statement
- Fast operation (samples ~20 pages per index by default)
- `NO_WRITE_TO_BINLOG` prevents replication overhead (recommended for staging)
- Returns result set: `Table | Op | Msg_type | Msg_text`

**Example result:**
```
+------------------+---------+----------+----------+
| Table            | Op      | Msg_type | Msg_text |
+------------------+---------+----------+----------+
| staging.users    | analyze | status   | OK       |
| staging.orders   | analyze | status   | OK       |
+------------------+---------+----------+----------+
```

#### Implementation Details

##### 1. Add ALTER TABLE Regex to ProcesslistMonitor

```python
# In processlist_monitor.py - add alongside existing regexes

RE_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+`?([^\s`(]+)`?",
    re.IGNORECASE
)

RE_ADD_KEY = re.compile(
    r"ADD\s+(PRIMARY\s+)?KEY",
    re.IGNORECASE
)
```

##### 2. Add Table State Tracking

```python
# In processlist_monitor.py

from enum import Enum, auto
from dataclasses import dataclass, field

class TableRestorePhase(Enum):
    """Track what phase a table is in during restore."""
    LOADING_DATA = auto()       # INSERT/LOAD DATA happening
    REBUILDING_INDEXES = auto() # ALTER TABLE ADD KEY happening
    COMPLETE = auto()           # All done (internal state)

@dataclass
class TableRestoreState:
    """Track restore state for a single table."""
    name: str
    phase: TableRestorePhase = TableRestorePhase.LOADING_DATA
    load_progress_pct: int = 0
    index_started: bool = False
    index_complete: bool = False
    
    @property
    def is_fully_complete(self) -> bool:
        """Table is complete when data loaded AND indexes rebuilt."""
        return self.phase == TableRestorePhase.COMPLETE
```

##### 3. Update _parse_processlist_rows()

```python
def _parse_processlist_rows(self, rows: list[tuple]) -> dict[str, Any]:
    """Parse processlist for both INSERT/LOAD and ALTER TABLE operations.
    
    Captures the processlist Time column to show how long each query has been
    running - critical for ALTER TABLE operations which don't report percentage.
    """
    result = {
        "active_tables": {},      # Table -> progress info
        "loading_tables": [],     # Tables with active INSERT/LOAD
        "indexing_tables": [],    # Tables with active ALTER TABLE ADD KEY
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    for row in rows:
        info = str(row[INFO_INDEX]) if row[INFO_INDEX] else ""
        state = str(row[STATE_INDEX]) if row[STATE_INDEX] else ""
        query_time = int(row[TIME_INDEX]) if row[TIME_INDEX] else 0  # Seconds running
        
        # Check for data loading (existing logic)
        insert_match = RE_INSERT_TABLE.search(info)
        load_match = RE_LOAD_TABLE.search(info)
        
        if insert_match or load_match:
            table_name = (insert_match or load_match).group(1)
            pct = self._extract_completion_pct(info)
            result["loading_tables"].append(table_name)
            result["active_tables"][table_name] = {
                "phase": "loading_data",
                "progress_pct": pct,
                "running_seconds": query_time,
            }
        
        # NEW: Check for index rebuilding
        elif state == "altering table" or RE_ALTER_TABLE.search(info):
            alter_match = RE_ALTER_TABLE.search(info)
            if alter_match and RE_ADD_KEY.search(info):
                table_name = alter_match.group(1)
                result["indexing_tables"].append(table_name)
                result["active_tables"][table_name] = {
                    "phase": "rebuilding_indexes",
                    "progress_pct": None,  # ALTER TABLE doesn't report %
                    "running_seconds": query_time,  # Show elapsed time instead
                }
    
    return result
```

**Note**: The processlist `Time` column shows seconds since query started. For ALTER TABLE
operations that can run for hours, this provides the only indication of activity.

##### 4. Add ANALYZE TABLE Execution

```python
# In pulldb/worker/table_analyzer.py (NEW FILE - HCA layer: features)

"""
Table analyzer for post-restore statistics updates.

HCA Layer: features (pulldb/worker/)
Depends on: shared (infra/mysql)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from pulldb.infra.mysql import execute_query, MysqlConnection

logger = logging.getLogger(__name__)


@dataclass
class AnalyzeResult:
    """Result of ANALYZE TABLE for one table."""
    table: str
    msg_type: str  # "status", "error", "info", "warning"
    msg_text: str  # "OK", "Table is already up to date", error message


def analyze_tables(
    conn: MysqlConnection,
    database: str,
    tables: list[str],
    *,
    use_local: bool = True,  # NO_WRITE_TO_BINLOG for staging
    batch_size: int = 10,
    event_callback: Optional[Callable[[str, dict], None]] = None,
) -> list[AnalyzeResult]:
    """
    Execute ANALYZE TABLE on restored tables for accurate statistics.
    
    Args:
        conn: MySQL connection to staging database
        database: Database name (e.g., "staging_abc123")
        tables: List of table names to analyze
        use_local: If True, use NO_WRITE_TO_BINLOG (recommended for staging)
        batch_size: Number of tables per ANALYZE statement
        event_callback: Optional callback for progress events
    
    Returns:
        List of AnalyzeResult for each table
    """
    results = []
    local_clause = "NO_WRITE_TO_BINLOG " if use_local else ""
    
    # Process in batches
    for i in range(0, len(tables), batch_size):
        batch = tables[i:i + batch_size]
        table_list = ", ".join(f"`{database}`.`{t}`" for t in batch)
        sql = f"ANALYZE {local_clause}TABLE {table_list}"
        
        logger.debug(f"Analyzing tables: {batch}")
        
        # Emit start events
        for table in batch:
            if event_callback:
                event_callback("table_analyze_started", {"table": table})
        
        try:
            rows = execute_query(conn, sql)
            
            # Parse result set
            for row in rows:
                # Row format: (Table, Op, Msg_type, Msg_text)
                full_table = row[0]  # "staging_abc.users"
                table_name = full_table.split(".")[-1] if "." in full_table else full_table
                result = AnalyzeResult(
                    table=table_name,
                    msg_type=row[2],  # "status", "error", etc.
                    msg_text=row[3],  # "OK", "Table is already up to date"
                )
                results.append(result)
                
                if event_callback:
                    event_callback("table_analyze_complete", {
                        "table": table_name,
                        "status": result.msg_type,
                        "message": result.msg_text,
                    })
                    
        except Exception as e:
            logger.error(f"Failed to analyze tables {batch}: {e}")
            for table in batch:
                results.append(AnalyzeResult(
                    table=table,
                    msg_type="error",
                    msg_text=str(e),
                ))
                if event_callback:
                    event_callback("table_analyze_failed", {
                        "table": table,
                        "error": str(e),
                    })
    
    return results
```

##### 5. Integration Point in Restore Workflow

```python
# In restore.py - orchestrate_restore_workflow()
# After myloader completes and all tables are restored:

# Existing code ends myloader here...
_emit_event("myloader_complete", {"exit_code": 0})

# NEW: Analyze all tables for accurate statistics
if analyze_after_restore:
    _emit_event("analyze_tables_started", {"table_count": len(restored_tables)})
    
    results = analyze_tables(
        conn=staging_conn,
        database=staging_db_name,
        tables=restored_tables,
        use_local=True,  # Don't replicate ANALYZE statements
        event_callback=_emit_event,
    )
    
    success_count = sum(1 for r in results if r.msg_type == "status")
    _emit_event("analyze_tables_complete", {
        "success_count": success_count,
        "total_count": len(results),
    })
```

##### 6. New Events for UI

| Event | Data | When Emitted |
|-------|------|--------------|
| `table_index_rebuild_started` | `{table: str, running_seconds: int}` | ALTER TABLE ... ADD KEY detected |
| `table_index_rebuild_progress` | `{table: str, running_seconds: int}` | Periodic update during ALTER TABLE |
| `table_index_rebuild_complete` | `{table: str, total_seconds: int}` | ALTER TABLE finishes |
| `table_analyze_started` | `{table: str}` | ANALYZE TABLE begins |
| `table_analyze_complete` | `{table, status, message}` | ANALYZE TABLE returns |
| `analyze_tables_started` | `{table_count: int}` | Batch analysis begins |
| `analyze_tables_complete` | `{success_count, total_count}` | All tables analyzed |

##### 6b. UI Display for Index Rebuild Phase

For tables in `rebuilding_indexes` phase, the UI should display:

1. **Spinner icon** instead of progress bar (no percentage available)
2. **Running time** from `running_seconds` formatted as "Xh Ym Zs"
3. **Phase label** showing "Rebuilding indexes..." 

**Template snippet for job details page:**

```html
{% for table_name, table_info in tables.items() %}
<div class="log-progress-table-row">
    <span class="table-name">{{ table_name }}</span>
    
    {% if table_info.phase == "loading_data" %}
        {# Normal progress bar with percentage #}
        <div class="log-progress-bar-container">
            <div class="log-progress-bar" style="width: {{ table_info.progress_pct }}%"></div>
        </div>
        <span class="progress-percent">{{ table_info.progress_pct }}%</span>
    
    {% elif table_info.phase == "rebuilding_indexes" %}
        {# Spinner with elapsed time - no percentage available #}
        <div class="log-progress-spinner-container">
            <span class="spinner spinner--small"></span>
            <span class="progress-phase">Rebuilding indexes...</span>
            <span class="progress-time">{{ table_info.running_seconds | format_duration }}</span>
        </div>
    
    {% elif table_info.phase == "analyzing" %}
        {# Spinner for ANALYZE TABLE phase #}
        <div class="log-progress-spinner-container">
            <span class="spinner spinner--small"></span>
            <span class="progress-phase">Analyzing statistics...</span>
        </div>
    {% endif %}
</div>
{% endfor %}
```

**CSS additions:**

```css
.log-progress-spinner-container {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.spinner--small {
    width: 16px;
    height: 16px;
    border-width: 2px;
}

.progress-phase {
    color: var(--warning-text);
    font-style: italic;
}

.progress-time {
    color: var(--text-muted);
    font-family: var(--font-mono);
}
```

**Jinja2 filter for duration formatting:**

```python
def _format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration (e.g., '1h 23m 45s')."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    else:
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h {m}m {s}s"
```

##### 7. Test Cases

```python
# tests/test_table_analyzer.py

class TestAnalyzeTables:
    """Test ANALYZE TABLE execution."""
    
    def test_analyze_single_table(self, mock_mysql_conn):
        """Analyze one table returns result."""
        mock_mysql_conn.execute.return_value = [
            ("staging.users", "analyze", "status", "OK")
        ]
        
        results = analyze_tables(
            conn=mock_mysql_conn,
            database="staging",
            tables=["users"],
        )
        
        assert len(results) == 1
        assert results[0].table == "users"
        assert results[0].msg_type == "status"
        assert results[0].msg_text == "OK"
    
    def test_analyze_batches_tables(self, mock_mysql_conn):
        """Large table lists are batched."""
        tables = [f"table_{i}" for i in range(25)]
        mock_mysql_conn.execute.return_value = [
            (f"staging.table_{i}", "analyze", "status", "OK")
            for i in range(10)
        ]
        
        results = analyze_tables(
            conn=mock_mysql_conn,
            database="staging",
            tables=tables,
            batch_size=10,
        )
        
        # Should be 3 calls: 10 + 10 + 5
        assert mock_mysql_conn.execute.call_count == 3
    
    def test_no_write_to_binlog(self, mock_mysql_conn):
        """use_local adds NO_WRITE_TO_BINLOG clause."""
        analyze_tables(
            conn=mock_mysql_conn,
            database="staging",
            tables=["users"],
            use_local=True,
        )
        
        call_sql = mock_mysql_conn.execute.call_args[0][0]
        assert "NO_WRITE_TO_BINLOG" in call_sql


class TestProcesslistAlterTableDetection:
    """Test ALTER TABLE tracking in ProcesslistMonitor."""
    
    def test_detect_add_key(self):
        """Detects ALTER TABLE ... ADD KEY as index rebuild."""
        info = "ALTER TABLE `changeLog` ADD KEY `class` (`class`), ADD KEY `category` (`category`)"
        
        alter_match = RE_ALTER_TABLE.search(info)
        assert alter_match is not None
        assert alter_match.group(1) == "changeLog"
        assert RE_ADD_KEY.search(info) is not None
    
    def test_ignore_add_column(self):
        """Does not flag ALTER TABLE ADD COLUMN as index rebuild."""
        info = "ALTER TABLE `users` ADD COLUMN `email` VARCHAR(255)"
        
        alter_match = RE_ALTER_TABLE.search(info)
        assert alter_match is not None  # Still matches ALTER TABLE
        assert RE_ADD_KEY.search(info) is None  # But not ADD KEY
    
    def test_table_state_transitions(self):
        """Table state correctly tracks phases."""
        state = TableRestoreState(name="users")
        
        assert state.phase == TableRestorePhase.LOADING_DATA
        assert not state.is_fully_complete
        
        state.phase = TableRestorePhase.REBUILDING_INDEXES
        assert not state.is_fully_complete
        
        state.phase = TableRestorePhase.COMPLETE
        assert state.is_fully_complete
```

### Phase 5 Checklist

**myloader Log Parsing (Primary Detection):**
- [ ] Create `pulldb/worker/myloader_log_parser.py` (NEW FILE - HCA layer: features)
- [ ] Add `RE_ENQUEUE_INDEX` regex for "Thread %d: Enqueuing index for table: %s.%s" pattern
- [ ] Add `RE_RESTORING_INDEX` regex for "restoring index: %s.%s" pattern
- [ ] Add `RE_RESTORING_INDEXES` regex for "restoring indexes %s.%s from index" pattern
- [ ] Add `RE_DATA_PROGRESS` regex for "restoring %s.%s part %d of %d" pattern
- [ ] Add `RE_LOADER_THREAD_ENDING` regex for "L-Thread %u: ending" pattern
- [ ] Add `RE_INDEX_THREAD_ENDING` regex for "I-Thread %u: ending" pattern
- [ ] Implement `MyloaderLogParser` class with `parse_line()` method
- [ ] Implement `TablePhaseTracker` to track per-table state transitions
- [ ] Update `_progress_callback()` in `restore.py` to use log parser
- [ ] Emit `table_index_rebuild_started` when "Enqueuing index" detected
- [ ] Emit `table_index_rebuild_complete` when table exits index thread queue
- [ ] Add tests in `tests/test_myloader_log_parser.py`

**Processlist Monitoring (Secondary/Fallback):**
- [ ] Add `RE_ALTER_TABLE` regex to `processlist_monitor.py`
- [ ] Add `RE_ADD_KEY` regex to `processlist_monitor.py`
- [ ] Add processlist column index constants: `TIME_INDEX = 5` (for Time column)
- [ ] Add `TableRestorePhase` enum: `LOADING_DATA`, `REBUILDING_INDEXES`, `COMPLETE`
- [ ] Add `TableRestoreState` dataclass to track per-table state
- [ ] Update `_parse_processlist_rows()` to detect ALTER TABLE ADD KEY statements
- [ ] Capture processlist `Time` column as `running_seconds` for all active queries
- [ ] Track table state transitions: loading → indexing → complete
- [ ] Add tests for ALTER TABLE detection in `tests/test_worker_processlist_monitor.py`

**ANALYZE TABLE (Post-Restore):**
- [ ] Create `pulldb/worker/table_analyzer.py` (NEW FILE - HCA layer: features)
- [ ] Implement `AnalyzeResult` dataclass for per-table results
- [ ] Implement `analyze_tables()` function with batch support
- [ ] Use `NO_WRITE_TO_BINLOG` to avoid replication overhead
- [ ] Add `analyze_after_restore` config option (default: True)
- [ ] Integrate ANALYZE TABLE into `orchestrate_restore_workflow()` after myloader completes
- [ ] Add tests in `tests/test_table_analyzer.py`

**State Coordination:**
- [ ] Create `pulldb/worker/restore_state_tracker.py` (NEW FILE - HCA layer: features)
- [ ] Implement `RestoreStateTracker` class to merge log parser + processlist signals
- [ ] Handle race conditions between log events and processlist polling
- [ ] Track completion: table is done only when BOTH data load AND index rebuild complete
- [ ] Add tests in `tests/test_restore_state_tracker.py`

**UI Updates:**
- [ ] Add new events to `EVENT_TO_PHASE` mapping in `routes.py`
- [ ] Add `_format_duration()` Jinja2 filter to `dependencies.py`
- [ ] Update job details template with spinner + elapsed time for index rebuild phase
- [ ] Add CSS for `.log-progress-spinner-container` and `.spinner--small`
- [ ] Update table progress display to show phase (loading/indexing/analyzing/complete)

**Configuration:**
- [ ] Add `PULLDB_ANALYZE_AFTER_RESTORE` env var (default: "true")
- [ ] Add `PULLDB_INDEX_TRACKING_ENABLED` env var (default: "true")
- [ ] Add settings to admin page for enabling/disabling features

**Testing:**
- [ ] Create `tests/test_myloader_log_parser.py` with regex and parser tests
- [ ] Create `tests/test_table_analyzer.py` with ANALYZE TABLE tests
- [ ] Create `tests/test_restore_state_tracker.py` with state coordination tests
- [ ] Add ALTER TABLE detection tests to `tests/test_worker_processlist_monitor.py`
- [ ] Add Time column capture tests
- [ ] Add integration test for full restore with index tracking
- [ ] Run full test suite
- [ ] Manual verification with real myloader restore (foxpest backup)

---

### Phase 5: Test Specifications

#### File: `tests/test_myloader_log_parser.py` (NEW)

```python
"""
Tests for myloader log parser module.

Tests cover:
1. Individual regex pattern matching
2. MyloaderLogParser state machine
3. Event emission
4. Edge cases and malformed input
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from pulldb.worker.myloader_log_parser import (
    MyloaderLogParser,
    TablePhase,
    TableState,
    LogParseResult,
    RE_ENQUEUE_INDEX,
    RE_RESTORING_INDEX,
    RE_RESTORING_INDEXES,
    RE_DATA_PROGRESS,
    RE_OVERALL_PROGRESS,
    RE_LOADER_THREAD_ENDING,
    RE_INDEX_THREAD_ENDING,
)


class TestRegexPatterns:
    """Test individual regex pattern matching against myloader output."""
    
    def test_enqueue_index_pattern(self):
        """Matches 'Thread X: Enqueuing index for table: db.table' from myloader_worker_index.c."""
        line = "Thread 5: Enqueuing index for table: staging_abc123.users"
        match = RE_ENQUEUE_INDEX.search(line)
        assert match is not None
        assert match.group(1) == "5"
        assert match.group(2) == "staging_abc123"
        assert match.group(3) == "users"
    
    def test_enqueue_index_negative_thread(self):
        """Thread ID can be -1 per source code."""
        line = "Thread -1: Enqueuing index for table: staging.changeLog"
        match = RE_ENQUEUE_INDEX.search(line)
        assert match is not None
        assert match.group(1) == "-1"
    
    def test_restoring_index_pattern(self):
        """Matches 'restoring index: db.table' from myloader_worker_index.c:process_index()."""
        line = "restoring index: foxpest.changeLog"
        match = RE_RESTORING_INDEX.search(line)
        assert match is not None
        assert match.group(1) == "foxpest"
        assert match.group(2) == "changeLog"
    
    def test_restoring_indexes_pattern(self):
        """Matches 'Thread X: restoring indexes db.table from index' from myloader_restore_job.c."""
        line = "Thread 3: restoring indexes staging_abc.orders from index file"
        match = RE_RESTORING_INDEXES.search(line)
        assert match is not None
        assert match.group(1) == "3"
        assert match.group(2) == "staging_abc"
        assert match.group(3) == "orders"
    
    def test_data_progress_pattern(self):
        """Matches 'Thread X: restoring db.table part N of M from file'."""
        line = "Thread 2: restoring staging_abc.users part 3 of 10 from users.00002.sql.gz | Progress 45 of 120. Tables 5 of 15 completed"
        match = RE_DATA_PROGRESS.search(line)
        assert match is not None
        assert match.group(1) == "2"          # thread_id
        assert match.group(2) == "staging_abc" # target_db
        assert match.group(3) == "users"       # table_name
        assert match.group(4) == "3"           # part
        assert match.group(5) == "10"          # total
        assert "users.00002.sql.gz" in match.group(6)  # filename
    
    def test_overall_progress_pattern(self):
        """Matches 'Progress X of Y. Tables A of B completed'."""
        line = "Progress 45 of 120. Tables 5 of 15 completed"
        match = RE_OVERALL_PROGRESS.search(line)
        assert match is not None
        assert match.group(1) == "45"   # progress
        assert match.group(2) == "120"  # total
        assert match.group(3) == "5"    # tables done
        assert match.group(4) == "15"   # tables total
    
    def test_loader_thread_ending_pattern(self):
        """Matches 'L-Thread X: ending' from myloader_worker_loader.c."""
        line = "L-Thread 3: ending"
        match = RE_LOADER_THREAD_ENDING.search(line)
        assert match is not None
        assert match.group(1) == "3"
    
    def test_index_thread_ending_pattern(self):
        """Matches 'I-Thread X: ending' (if used by myloader)."""
        line = "I-Thread 1: ending"
        match = RE_INDEX_THREAD_ENDING.search(line)
        assert match is not None
        assert match.group(1) == "1"
    
    def test_no_match_for_unrelated_lines(self):
        """Unrelated log lines don't match."""
        lines = [
            "Starting myloader...",
            "Connected to MySQL server",
            "Some random debug output",
            "",
        ]
        for line in lines:
            assert RE_ENQUEUE_INDEX.search(line) is None
            assert RE_RESTORING_INDEX.search(line) is None
            assert RE_DATA_PROGRESS.search(line) is None


class TestMyloaderLogParser:
    """Test MyloaderLogParser state machine."""
    
    def test_parser_initial_state(self):
        """Parser starts with no tracked tables."""
        parser = MyloaderLogParser()
        assert parser.get_all_states() == {}
        summary = parser.get_summary()
        assert summary["tables_completed"] == 0
        assert summary["tables_total"] == 0
    
    def test_data_progress_creates_table_state(self):
        """First data progress message creates table state."""
        parser = MyloaderLogParser()
        
        result = parser.parse_line(
            "Thread 1: restoring staging.users part 1 of 5 from users.00000.sql.gz"
        )
        
        state = parser.get_table_state("staging.users")
        assert state is not None
        assert state.phase == TablePhase.LOADING_DATA
        assert state.data_parts_completed == 1
        assert state.data_parts_total == 5
    
    def test_data_progress_updates_existing_state(self):
        """Subsequent data progress updates existing state."""
        parser = MyloaderLogParser()
        
        parser.parse_line("Thread 1: restoring staging.users part 1 of 5 from users.00000.sql.gz")
        parser.parse_line("Thread 2: restoring staging.users part 2 of 5 from users.00001.sql.gz")
        
        state = parser.get_table_state("staging.users")
        assert state.data_parts_completed == 2
    
    def test_enqueue_index_transitions_to_data_complete(self):
        """'Enqueuing index' marks data complete."""
        parser = MyloaderLogParser()
        
        parser.parse_line("Thread 1: restoring staging.users part 5 of 5 from users.00004.sql.gz")
        parser.parse_line("Thread 5: Enqueuing index for table: staging.users")
        
        state = parser.get_table_state("staging.users")
        assert state.phase == TablePhase.DATA_COMPLETE
        assert state.index_started_at is not None
    
    def test_restoring_index_transitions_to_rebuilding(self):
        """'restoring index' marks index rebuild active."""
        parser = MyloaderLogParser()
        
        parser.parse_line("Thread 5: Enqueuing index for table: staging.users")
        parser.parse_line("restoring index: foxpest.users")
        
        # Should find by source table name
        states = parser.get_all_states()
        indexing_tables = [s for s in states.values() if s.phase == TablePhase.REBUILDING_INDEXES]
        assert len(indexing_tables) >= 1
    
    def test_event_callback_invoked(self):
        """Event callback receives correct events."""
        events = []
        def callback(event_type, event_data):
            events.append((event_type, event_data))
        
        parser = MyloaderLogParser(event_callback=callback)
        
        parser.parse_line("Thread 5: Enqueuing index for table: staging.users")
        
        assert len(events) == 1
        assert events[0][0] == "table_index_rebuild_queued"
        assert events[0][1]["table"] == "users"
    
    def test_overall_progress_tracked(self):
        """Overall progress is tracked from progress lines."""
        parser = MyloaderLogParser()
        
        parser.parse_line("Progress 45 of 120. Tables 5 of 15 completed")
        
        summary = parser.get_summary()
        assert summary["overall_progress"] == 45
        assert summary["overall_total"] == 120
        assert summary["tables_completed"] == 5
        assert summary["tables_total"] == 15
    
    def test_summary_counts_phases(self):
        """Summary reports tables by phase."""
        parser = MyloaderLogParser()
        
        parser.parse_line("Thread 1: restoring staging.users part 1 of 5 from users.sql.gz")
        parser.parse_line("Thread 5: Enqueuing index for table: staging.orders")
        
        summary = parser.get_summary()
        phases = summary["tables_by_phase"]
        assert phases["LOADING_DATA"] >= 1 or phases["DATA_COMPLETE"] >= 1


class TestMyloaderLogParserEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_line(self):
        """Empty lines are handled gracefully."""
        parser = MyloaderLogParser()
        result = parser.parse_line("")
        assert result.event_type is None
    
    def test_malformed_line(self):
        """Malformed lines don't crash parser."""
        parser = MyloaderLogParser()
        result = parser.parse_line("Thread : Enqueuing index for table: .")
        # Should not match or should handle gracefully
        assert True  # No exception raised
    
    def test_callback_exception_handled(self):
        """Exception in callback doesn't crash parser."""
        def bad_callback(event_type, event_data):
            raise ValueError("Callback error")
        
        parser = MyloaderLogParser(event_callback=bad_callback)
        # Should log warning but not raise
        result = parser.parse_line("Thread 5: Enqueuing index for table: staging.users")
        assert result.event_type == "table_index_rebuild_queued"
```

#### File: `tests/test_restore_state_tracker.py` (NEW)

```python
"""
Tests for restore state tracker that coordinates log parsing and processlist monitoring.

Tests cover:
1. State coordination between log and processlist signals
2. Race condition handling
3. Completion detection
4. Event emission
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

from pulldb.worker.restore_state_tracker import (
    RestoreStateTracker,
    CombinedTableState,
)
from pulldb.worker.myloader_log_parser import (
    MyloaderLogParser,
    TablePhase,
)


class TestCombinedTableState:
    """Test combined state dataclass."""
    
    def test_is_fully_complete_requires_both(self):
        """Table is complete only when data AND index are done."""
        state = CombinedTableState(table_name="users")
        
        assert not state.is_fully_complete
        
        state.is_data_complete = True
        assert not state.is_fully_complete
        
        state.is_index_complete = True
        assert state.is_fully_complete
    
    def test_effective_phase_complete(self):
        """Effective phase is 'complete' when both flags set."""
        state = CombinedTableState(
            table_name="users",
            is_data_complete=True,
            is_index_complete=True,
        )
        assert state.effective_phase == "complete"
    
    def test_effective_phase_rebuilding_from_log(self):
        """Log phase determines rebuilding state."""
        state = CombinedTableState(
            table_name="users",
            log_phase=TablePhase.REBUILDING_INDEXES,
        )
        assert state.effective_phase == "rebuilding_indexes"
    
    def test_effective_phase_rebuilding_from_processlist(self):
        """Processlist phase as fallback."""
        state = CombinedTableState(
            table_name="users",
            processlist_phase="rebuilding_indexes",
        )
        assert state.effective_phase == "rebuilding_indexes"
    
    def test_effective_phase_loading(self):
        """Loading phase detected."""
        state = CombinedTableState(
            table_name="users",
            log_phase=TablePhase.LOADING_DATA,
        )
        assert state.effective_phase == "loading_data"


class TestRestoreStateTracker:
    """Test RestoreStateTracker coordination."""
    
    def test_log_line_updates_state(self):
        """Log lines update combined state."""
        parser = MyloaderLogParser()
        tracker = RestoreStateTracker(log_parser=parser)
        
        tracker.process_log_line(
            "Thread 1: restoring staging.users part 1 of 5 from users.sql.gz"
        )
        
        state = tracker.get_table_state("staging.users")
        assert state is not None
        assert state.log_phase == TablePhase.LOADING_DATA
    
    def test_enqueue_marks_data_complete(self):
        """Enqueue index marks data as complete."""
        parser = MyloaderLogParser()
        tracker = RestoreStateTracker(log_parser=parser)
        
        tracker.process_log_line(
            "Thread 5: Enqueuing index for table: staging.users"
        )
        
        state = tracker.get_table_state("staging.users")
        assert state is not None
        assert state.is_data_complete
        assert not state.is_index_complete  # Not yet
    
    def test_processlist_update_captures_time(self):
        """Processlist snapshot captures running time."""
        parser = MyloaderLogParser()
        tracker = RestoreStateTracker(log_parser=parser)
        
        # First mark data complete
        tracker.process_log_line(
            "Thread 5: Enqueuing index for table: staging.users"
        )
        
        # Mock processlist snapshot
        snapshot = Mock()
        snapshot.tables = {
            "staging.users": {
                "phase": "rebuilding_indexes",
                "progress_pct": None,
                "running_seconds": 120,
            }
        }
        
        tracker.update_from_processlist(snapshot)
        
        state = tracker.get_table_state("staging.users")
        assert state.processlist_running_seconds == 120
    
    def test_table_disappearing_from_processlist_marks_complete(self):
        """Table no longer in processlist after indexing = complete."""
        events = []
        def callback(event_type, event_data):
            events.append((event_type, event_data))
        
        parser = MyloaderLogParser()
        tracker = RestoreStateTracker(
            log_parser=parser,
            event_callback=callback,
        )
        
        # Mark data complete and start indexing
        tracker.process_log_line(
            "Thread 5: Enqueuing index for table: staging.users"
        )
        
        # First snapshot shows indexing
        snapshot1 = Mock()
        snapshot1.tables = {
            "staging.users": {
                "phase": "rebuilding_indexes",
                "running_seconds": 60,
            }
        }
        tracker.update_from_processlist(snapshot1)
        
        # Second snapshot - table gone (index complete)
        snapshot2 = Mock()
        snapshot2.tables = {}  # No longer in processlist
        tracker.update_from_processlist(snapshot2)
        
        state = tracker.get_table_state("staging.users")
        assert state.is_data_complete
        assert state.is_index_complete
        
        # Should have emitted completion event
        complete_events = [e for e in events if e[0] == "table_index_rebuild_complete"]
        assert len(complete_events) == 1
    
    def test_get_tables_for_ui_format(self):
        """UI format includes expected fields."""
        parser = MyloaderLogParser()
        tracker = RestoreStateTracker(log_parser=parser)
        
        tracker.process_log_line(
            "Thread 1: restoring staging.users part 3 of 10 from users.sql.gz"
        )
        
        ui_data = tracker.get_tables_for_ui()
        
        assert "staging.users" in ui_data
        table_info = ui_data["staging.users"]
        assert "phase" in table_info
        assert "is_complete" in table_info
    
    def test_thread_safety(self):
        """Concurrent access doesn't cause errors."""
        import threading
        
        parser = MyloaderLogParser()
        tracker = RestoreStateTracker(log_parser=parser)
        
        errors = []
        
        def worker(table_num):
            try:
                for i in range(100):
                    tracker.process_log_line(
                        f"Thread 1: restoring staging.table{table_num} part {i} of 100 from file.sql.gz"
                    )
                    tracker.get_all_states()
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
```

#### Additional Tests for `tests/test_worker_processlist_monitor.py`

Add these tests to the existing file:

```python
# Add to existing test file

class TestAlterTableDetection:
    """Test ALTER TABLE detection for index rebuild tracking."""
    
    def test_re_alter_table_matches_simple(self):
        """Matches basic ALTER TABLE statement."""
        from pulldb.worker.processlist_monitor import RE_ALTER_TABLE
        
        info = "ALTER TABLE `changeLog` ADD KEY `class` (`class`)"
        match = RE_ALTER_TABLE.search(info)
        assert match is not None
        assert match.group(1) == "changeLog"
    
    def test_re_alter_table_matches_no_backticks(self):
        """Matches ALTER TABLE without backticks."""
        from pulldb.worker.processlist_monitor import RE_ALTER_TABLE
        
        info = "ALTER TABLE users ADD KEY idx_email (email)"
        match = RE_ALTER_TABLE.search(info)
        assert match is not None
        assert match.group(1) == "users"
    
    def test_re_add_key_matches_simple(self):
        """Matches ADD KEY clause."""
        from pulldb.worker.processlist_monitor import RE_ADD_KEY
        
        info = "ADD KEY `class` (`class`)"
        match = RE_ADD_KEY.search(info)
        assert match is not None
    
    def test_re_add_key_matches_primary(self):
        """Matches ADD PRIMARY KEY."""
        from pulldb.worker.processlist_monitor import RE_ADD_KEY
        
        info = "ADD PRIMARY KEY (`id`)"
        match = RE_ADD_KEY.search(info)
        assert match is not None
    
    def test_re_add_key_no_match_add_column(self):
        """Does not match ADD COLUMN."""
        from pulldb.worker.processlist_monitor import RE_ADD_KEY
        
        info = "ADD COLUMN email VARCHAR(255)"
        match = RE_ADD_KEY.search(info)
        assert match is None
    
    def test_parse_processlist_detects_alter_table(self, processlist_monitor):
        """ProcesslistMonitor detects ALTER TABLE ADD KEY as index rebuild."""
        rows = [
            {
                "db": "staging_abc123",
                "Info": "ALTER TABLE `changeLog` ADD KEY `class` (`class`), ADD KEY `category` (`category`)",
                "State": "altering table",
                "Time": 45,
            }
        ]
        
        snapshot = processlist_monitor._parse_processlist_rows(rows)
        
        assert "changeLog" in snapshot.tables
        assert snapshot.tables["changeLog"]["phase"] == "rebuilding_indexes"
        assert snapshot.tables["changeLog"]["running_seconds"] == 45
    
    def test_parse_processlist_ignores_non_index_alter(self, processlist_monitor):
        """ALTER TABLE ADD COLUMN not flagged as index rebuild."""
        rows = [
            {
                "db": "staging_abc123",
                "Info": "ALTER TABLE `users` ADD COLUMN `email` VARCHAR(255)",
                "State": "altering table",
                "Time": 10,
            }
        ]
        
        snapshot = processlist_monitor._parse_processlist_rows(rows)
        
        # Should not be tracked as index rebuild
        if "users" in snapshot.tables:
            assert snapshot.tables["users"].get("phase") != "rebuilding_indexes"


class TestTimeColumnCapture:
    """Test Time column capture for running duration."""
    
    def test_time_captured_for_insert(self, processlist_monitor):
        """INSERT statement captures Time as running_seconds."""
        rows = [
            {
                "db": "staging_abc123",
                "Info": "INSERT INTO `users` /* COMPLETED: 50% */ ...",
                "State": "executing",
                "Time": 120,
            }
        ]
        
        snapshot = processlist_monitor._parse_processlist_rows(rows)
        
        assert "users" in snapshot.tables
        assert snapshot.tables["users"]["running_seconds"] == 120
    
    def test_time_captured_for_load_data(self, processlist_monitor):
        """LOAD DATA captures Time as running_seconds."""
        rows = [
            {
                "db": "staging_abc123",
                "Info": "LOAD DATA LOCAL INFILE '/tmp/data.csv' INTO TABLE `orders` /* COMPLETED: 75% */",
                "State": "executing",
                "Time": 300,
            }
        ]
        
        snapshot = processlist_monitor._parse_processlist_rows(rows)
        
        assert "orders" in snapshot.tables
        assert snapshot.tables["orders"]["running_seconds"] == 300
```

---

### Phase 5: Implementation Order

Implementation should proceed in dependency order:

```
Phase 5A: Foundation (no dependencies)
├── 1. Create pulldb/worker/myloader_log_parser.py
├── 2. Create tests/test_myloader_log_parser.py
└── 3. Run tests (pytest tests/test_myloader_log_parser.py)

Phase 5B: Processlist Updates (no dependencies)
├── 4. Update pulldb/worker/processlist_monitor.py
│     ├── Add RE_ALTER_TABLE, RE_ADD_KEY regexes
│     ├── Add Time column capture
│     └── Update _parse_processlist_rows()
├── 5. Add tests to tests/test_worker_processlist_monitor.py
└── 6. Run tests (pytest tests/test_worker_processlist_monitor.py)

Phase 5C: State Coordination (depends on 5A, 5B)
├── 7. Create pulldb/worker/restore_state_tracker.py
├── 8. Create tests/test_restore_state_tracker.py
└── 9. Run tests (pytest tests/test_restore_state_tracker.py)

Phase 5D: ANALYZE TABLE (no dependencies)
├── 10. Create pulldb/worker/table_analyzer.py
├── 11. Create tests/test_table_analyzer.py
└── 12. Run tests (pytest tests/test_table_analyzer.py)

Phase 5E: Integration (depends on 5A-5D)
├── 13. Update pulldb/worker/restore.py
│      ├── Import new modules
│      ├── Update _progress_callback() to use log parser
│      └── Add ANALYZE TABLE call after myloader
├── 14. Update pulldb/web/features/jobs/routes.py
│      └── Add new events to EVENT_TO_PHASE
└── 15. Run full test suite

Phase 5F: UI (depends on 5E)
├── 16. Add _format_duration() filter to dependencies.py
├── 17. Update job details template
├── 18. Add CSS for spinner and phase display
└── 19. Manual testing with real restore

Phase 5G: Configuration (optional, can be done anytime)
├── 20. Add PULLDB_ANALYZE_AFTER_RESTORE env var
└── 21. Add PULLDB_INDEX_TRACKING_ENABLED env var
```

---

### Phase 5: Detailed File Specifications

#### File 1: `pulldb/worker/myloader_log_parser.py` (NEW)

```python
"""
myloader stdout log parser for restore phase detection.

Parses myloader verbose output to detect:
- Data loading progress (part X of Y)
- Index rebuild start (Enqueuing index for table)
- Index rebuild active (restoring index/indexes)
- Thread completion (L-Thread/I-Thread ending)

HCA Layer: features (pulldb/worker/)
Depends on: shared (infra/logging)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable, Optional

from pulldb.infra.logging import get_logger

logger = get_logger("pulldb.worker.myloader_log_parser")


class TablePhase(Enum):
    """Phase of table restore process."""
    UNKNOWN = auto()
    LOADING_DATA = auto()      # INSERT/LOAD DATA in progress
    DATA_COMPLETE = auto()     # Data load finished, waiting for index
    REBUILDING_INDEXES = auto() # ALTER TABLE ADD KEY in progress
    COMPLETE = auto()          # All done


@dataclass
class TableState:
    """Track state for a single table during restore."""
    table_name: str
    source_table: str  # Original table name (from source db)
    target_table: str  # Target table name (in staging db)
    phase: TablePhase = TablePhase.UNKNOWN
    data_parts_total: int = 0
    data_parts_completed: int = 0
    index_started_at: Optional[datetime] = None
    index_running_seconds: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LogParseResult:
    """Result of parsing a single log line."""
    event_type: Optional[str] = None  # Event to emit, if any
    event_data: dict = field(default_factory=dict)
    table_name: Optional[str] = None
    phase_change: Optional[TablePhase] = None


# Compiled regex patterns based on myloader source code
# From myloader_worker_index.c:create_index_job()
RE_ENQUEUE_INDEX = re.compile(
    r"Thread\s+(-?\d+):\s+Enqueuing index for table:\s+([^\s.]+)\.([^\s]+)",
    re.IGNORECASE
)

# From myloader_worker_index.c:process_index()
RE_RESTORING_INDEX = re.compile(
    r"restoring index:\s+([^\s.]+)\.([^\s]+)",
    re.IGNORECASE
)

# From myloader_restore_job.c - index restore message
RE_RESTORING_INDEXES = re.compile(
    r"Thread\s+(\d+):\s+restoring indexes\s+([^\s.]+)\.([^\s]+)\s+from index",
    re.IGNORECASE
)

# From myloader_restore_job.c:process_restore_job() - data loading progress
RE_DATA_PROGRESS = re.compile(
    r"Thread\s+(\d+):\s+restoring\s+([^\s.]+)\.([^\s]+)\s+part\s+(\d+)\s+of\s+(\d+)\s+from\s+([^\s|]+)",
    re.IGNORECASE
)

# Overall progress: "Progress X of Y. Tables A of B completed"
RE_OVERALL_PROGRESS = re.compile(
    r"Progress\s+(\d+)\s+of\s+(\d+)\.\s*Tables\s+(\d+)\s+of\s+(\d+)",
    re.IGNORECASE
)

# From myloader_worker_loader.c:loader_thread()
RE_LOADER_THREAD_ENDING = re.compile(
    r"L-Thread\s+(\d+):\s+ending",
    re.IGNORECASE
)

# Index thread ending (from worker_index_thread)
RE_INDEX_THREAD_ENDING = re.compile(
    r"I-Thread\s+(\d+):\s+ending",
    re.IGNORECASE
)

# Index restore complete for specific table
RE_INDEX_RESTORE_COMPLETE = re.compile(
    r"Thread\s+(\d+):\s+restoring\s+INDEXES\s+([^\s.]+)\.([^\s]+)\s+from",
    re.IGNORECASE
)


class MyloaderLogParser:
    """
    Stateful parser for myloader verbose output.
    
    Tracks per-table state and emits events when phase transitions occur.
    """
    
    def __init__(
        self,
        event_callback: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        """
        Initialize parser.
        
        Args:
            event_callback: Optional callback invoked when events should be emitted.
        """
        self._event_callback = event_callback
        self._tables: dict[str, TableState] = {}
        self._overall_progress: int = 0
        self._overall_total: int = 0
        self._tables_completed: int = 0
        self._tables_total: int = 0
        self._loader_threads_active: int = 0
        self._index_threads_active: int = 0
    
    def parse_line(self, line: str) -> LogParseResult:
        """
        Parse a single line of myloader output.
        
        Args:
            line: Raw log line from myloader stdout/stderr.
            
        Returns:
            LogParseResult with any event to emit and state changes.
        """
        result = LogParseResult()
        
        # Try each pattern in order of specificity
        
        # 1. Index enqueue (data load complete, index starting)
        if match := RE_ENQUEUE_INDEX.search(line):
            thread_id, target_db, table_name = match.groups()
            result = self._handle_enqueue_index(target_db, table_name)
            
        # 2. Index restore starting
        elif match := RE_RESTORING_INDEX.search(line):
            source_db, table_name = match.groups()
            result = self._handle_restoring_index(source_db, table_name)
            
        # 3. Index restore in progress
        elif match := RE_RESTORING_INDEXES.search(line):
            thread_id, target_db, table_name = match.groups()
            result = self._handle_restoring_indexes(target_db, table_name)
            
        # 4. Data loading progress
        elif match := RE_DATA_PROGRESS.search(line):
            thread_id, target_db, table_name, part, total, filename = match.groups()
            result = self._handle_data_progress(
                target_db, table_name, int(part), int(total), filename
            )
            
        # 5. Overall progress
        if match := RE_OVERALL_PROGRESS.search(line):
            progress, total, tables_done, tables_total = match.groups()
            self._overall_progress = int(progress)
            self._overall_total = int(total)
            self._tables_completed = int(tables_done)
            self._tables_total = int(tables_total)
            
        # 6. Loader thread ending
        elif match := RE_LOADER_THREAD_ENDING.search(line):
            thread_id = match.group(1)
            self._loader_threads_active = max(0, self._loader_threads_active - 1)
            
        # 7. Index thread ending
        elif match := RE_INDEX_THREAD_ENDING.search(line):
            thread_id = match.group(1)
            self._index_threads_active = max(0, self._index_threads_active - 1)
        
        # Emit event if callback registered
        if result.event_type and self._event_callback:
            self._event_callback(result.event_type, result.event_data)
        
        return result
    
    def _handle_enqueue_index(self, target_db: str, table_name: str) -> LogParseResult:
        """Handle 'Enqueuing index for table' message."""
        key = f"{target_db}.{table_name}"
        
        state = self._tables.get(key)
        if state is None:
            state = TableState(
                table_name=key,
                source_table=table_name,
                target_table=table_name,
            )
            self._tables[key] = state
        
        # Transition: data complete, entering index phase
        old_phase = state.phase
        state.phase = TablePhase.DATA_COMPLETE
        state.index_started_at = datetime.utcnow()
        state.last_updated = datetime.utcnow()
        
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
    
    def _handle_restoring_index(self, source_db: str, table_name: str) -> LogParseResult:
        """Handle 'restoring index:' message."""
        # Find matching table state (may be under target db name)
        state = None
        for key, s in self._tables.items():
            if s.source_table == table_name or key.endswith(f".{table_name}"):
                state = s
                break
        
        if state is None:
            # Table not seen before, create state
            key = f"{source_db}.{table_name}"
            state = TableState(
                table_name=key,
                source_table=table_name,
                target_table=table_name,
            )
            self._tables[key] = state
        
        state.phase = TablePhase.REBUILDING_INDEXES
        state.index_started_at = state.index_started_at or datetime.utcnow()
        state.last_updated = datetime.utcnow()
        
        return LogParseResult(
            event_type="table_index_rebuild_started",
            event_data={
                "table": table_name,
                "source_db": source_db,
            },
            table_name=state.table_name,
            phase_change=TablePhase.REBUILDING_INDEXES,
        )
    
    def _handle_restoring_indexes(self, target_db: str, table_name: str) -> LogParseResult:
        """Handle 'restoring indexes ... from index' message."""
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
        state.last_updated = datetime.utcnow()
        
        # Calculate running time if we have start time
        running_seconds = 0
        if state.index_started_at:
            running_seconds = int(
                (datetime.utcnow() - state.index_started_at).total_seconds()
            )
        state.index_running_seconds = running_seconds
        
        return LogParseResult(
            event_type="table_index_rebuild_progress",
            event_data={
                "table": table_name,
                "target_db": target_db,
                "running_seconds": running_seconds,
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
        """Handle data loading progress message."""
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
        state.last_updated = datetime.utcnow()
        
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
            },
            table_name=key,
        )
    
    def get_table_state(self, table_name: str) -> Optional[TableState]:
        """Get current state for a table."""
        return self._tables.get(table_name)
    
    def get_all_states(self) -> dict[str, TableState]:
        """Get all table states."""
        return self._tables.copy()
    
    def get_summary(self) -> dict:
        """Get summary of current restore state."""
        phases = {phase: 0 for phase in TablePhase}
        for state in self._tables.values():
            phases[state.phase] += 1
        
        return {
            "overall_progress": self._overall_progress,
            "overall_total": self._overall_total,
            "tables_completed": self._tables_completed,
            "tables_total": self._tables_total,
            "tables_by_phase": {p.name: c for p, c in phases.items()},
            "loader_threads_active": self._loader_threads_active,
            "index_threads_active": self._index_threads_active,
        }
```

#### File 2: `pulldb/worker/table_analyzer.py` (NEW)

**Full specification at [Section 4: Add ANALYZE TABLE Execution](#4-add-analyze-table-execution) above.**

Summary: Implements `analyze_tables()` function with:
- `AnalyzeResult` dataclass for per-table results
- `NO_WRITE_TO_BINLOG` for staging databases
- Batch processing (default 10 tables per statement)
- Event callbacks for UI progress

#### File 3: `pulldb/worker/restore_state_tracker.py` (NEW)

```python
"""
Coordinated state tracker merging myloader log parsing with processlist monitoring.

Ensures table is only marked complete when BOTH:
1. Data load finished (from log: "Enqueuing index")
2. Index rebuild finished (from processlist: no ALTER TABLE, or from log: I-Thread ending)

HCA Layer: features (pulldb/worker/)
Depends on: myloader_log_parser, processlist_monitor
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from pulldb.infra.logging import get_logger
from pulldb.worker.myloader_log_parser import (
    MyloaderLogParser,
    TablePhase,
    TableState,
)
from pulldb.worker.processlist_monitor import (
    ProcesslistMonitor,
    ProcesslistSnapshot,
)

logger = get_logger("pulldb.worker.restore_state_tracker")


@dataclass
class CombinedTableState:
    """Combined state from log parser and processlist monitor."""
    table_name: str
    
    # From log parser
    log_phase: TablePhase = TablePhase.UNKNOWN
    data_parts_completed: int = 0
    data_parts_total: int = 0
    
    # From processlist
    processlist_phase: Optional[str] = None  # "loading_data", "rebuilding_indexes", None
    processlist_percent: Optional[float] = None
    processlist_running_seconds: int = 0
    
    # Combined determination
    is_data_complete: bool = False
    is_index_complete: bool = False
    
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def is_fully_complete(self) -> bool:
        """Table is complete when both data and indexes are done."""
        return self.is_data_complete and self.is_index_complete
    
    @property
    def effective_phase(self) -> str:
        """Determine effective phase from combined signals."""
        if self.is_fully_complete:
            return "complete"
        if self.log_phase == TablePhase.REBUILDING_INDEXES:
            return "rebuilding_indexes"
        if self.processlist_phase == "rebuilding_indexes":
            return "rebuilding_indexes"
        if self.log_phase in (TablePhase.DATA_COMPLETE, TablePhase.REBUILDING_INDEXES):
            return "rebuilding_indexes"
        if self.log_phase == TablePhase.LOADING_DATA:
            return "loading_data"
        if self.processlist_phase == "loading_data":
            return "loading_data"
        return "unknown"


class RestoreStateTracker:
    """
    Coordinates state tracking from multiple sources.
    
    Uses:
    - MyloaderLogParser for explicit phase signals from myloader stdout
    - ProcesslistMonitor for running time and fallback detection
    
    Emits unified events when table state changes.
    """
    
    def __init__(
        self,
        log_parser: MyloaderLogParser,
        processlist_monitor: Optional[ProcesslistMonitor] = None,
        event_callback: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        self._log_parser = log_parser
        self._processlist_monitor = processlist_monitor
        self._event_callback = event_callback
        self._tables: dict[str, CombinedTableState] = {}
        self._lock = threading.Lock()
        
        # Track tables that entered index phase but haven't completed
        self._tables_in_index_phase: set[str] = set()
    
    def process_log_line(self, line: str) -> None:
        """Process a log line and update combined state."""
        result = self._log_parser.parse_line(line)
        
        if result.table_name:
            with self._lock:
                self._update_from_log(result.table_name, result)
    
    def update_from_processlist(self, snapshot: ProcesslistSnapshot) -> None:
        """Update combined state from processlist snapshot."""
        with self._lock:
            # Update states for tables in snapshot
            for table_name, table_info in snapshot.tables.items():
                if table_name not in self._tables:
                    self._tables[table_name] = CombinedTableState(table_name=table_name)
                
                state = self._tables[table_name]
                state.processlist_phase = table_info.get("phase")
                state.processlist_percent = table_info.get("progress_pct")
                state.processlist_running_seconds = table_info.get("running_seconds", 0)
                state.last_updated = datetime.utcnow()
            
            # Check for tables that were indexing but no longer appear in processlist
            # This could indicate index completion
            for table_name in list(self._tables_in_index_phase):
                if table_name not in snapshot.tables:
                    state = self._tables.get(table_name)
                    if state and state.is_data_complete and not state.is_index_complete:
                        # Index likely completed
                        state.is_index_complete = True
                        self._tables_in_index_phase.discard(table_name)
                        self._emit_event("table_index_rebuild_complete", {
                            "table": table_name,
                            "total_seconds": state.processlist_running_seconds,
                        })
    
    def _update_from_log(self, table_name: str, result) -> None:
        """Update state from log parse result."""
        if table_name not in self._tables:
            self._tables[table_name] = CombinedTableState(table_name=table_name)
        
        state = self._tables[table_name]
        log_state = self._log_parser.get_table_state(table_name)
        
        if log_state:
            state.log_phase = log_state.phase
            state.data_parts_completed = log_state.data_parts_completed
            state.data_parts_total = log_state.data_parts_total
            
            # Detect data completion
            if log_state.phase in (TablePhase.DATA_COMPLETE, TablePhase.REBUILDING_INDEXES):
                if not state.is_data_complete:
                    state.is_data_complete = True
                    self._tables_in_index_phase.add(table_name)
            
            # Detect index completion
            if log_state.phase == TablePhase.COMPLETE:
                state.is_index_complete = True
                self._tables_in_index_phase.discard(table_name)
        
        state.last_updated = datetime.utcnow()
    
    def _emit_event(self, event_type: str, data: dict) -> None:
        """Emit event if callback registered."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except Exception as e:
                logger.warning(f"Event callback error: {e}")
    
    def get_table_state(self, table_name: str) -> Optional[CombinedTableState]:
        """Get combined state for a table."""
        with self._lock:
            return self._tables.get(table_name)
    
    def get_all_states(self) -> dict[str, CombinedTableState]:
        """Get all table states."""
        with self._lock:
            return self._tables.copy()
    
    def get_tables_for_ui(self) -> dict[str, dict]:
        """Get table states formatted for UI consumption."""
        with self._lock:
            result = {}
            for name, state in self._tables.items():
                result[name] = {
                    "phase": state.effective_phase,
                    "progress_pct": state.processlist_percent,
                    "running_seconds": state.processlist_running_seconds,
                    "is_complete": state.is_fully_complete,
                }
            return result
```

#### File 4: Updates to `pulldb/worker/restore.py`

**Changes needed:**

```python
# Add imports
from pulldb.worker.myloader_log_parser import MyloaderLogParser
from pulldb.worker.restore_state_tracker import RestoreStateTracker
from pulldb.worker.table_analyzer import analyze_tables

# In run_myloader() - update _progress_callback to use log parser:

def run_myloader(...):
    # ... existing setup ...
    
    # NEW: Create log parser
    log_parser = MyloaderLogParser(event_callback=progress_callback)
    
    def _progress_callback(line: str) -> None:
        nonlocal completed_tasks, rows_restored
        
        # NEW: Parse line for index tracking
        log_parser.parse_line(line)
        
        # ... existing progress handling ...

# In orchestrate_restore_workflow() - add ANALYZE TABLE:

def orchestrate_restore_workflow(spec: RestoreWorkflowSpec) -> dict[str, object]:
    # ... existing workflow ...
    
    # After myloader completes successfully:
    if result.exit_code == 0 and spec.analyze_after_restore:
        _emit_event("analyze_tables_started", {
            "table_count": len(restored_tables)
        })
        
        analyze_results = analyze_tables(
            conn=staging_conn,
            database=staging_db_name,
            tables=restored_tables,
            use_local=True,
            event_callback=_emit_event,
        )
        
        success_count = sum(1 for r in analyze_results if r.msg_type == "status")
        _emit_event("analyze_tables_complete", {
            "success_count": success_count,
            "total_count": len(analyze_results),
        })
```

#### File 5: Updates to `pulldb/worker/processlist_monitor.py`

**Add after existing regex definitions (~line 30):**

```python
# NEW: Regex for ALTER TABLE detection
RE_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+`?([^\s`(]+)`?",
    re.IGNORECASE
)

# NEW: Regex to confirm it's an ADD KEY operation (index rebuild)
RE_ADD_KEY = re.compile(
    r"ADD\s+(PRIMARY\s+)?KEY",
    re.IGNORECASE
)

# Processlist column indices (when using cursor without dictionary)
# Id, User, Host, db, Command, Time, State, Info
COLUMN_ID = 0
COLUMN_USER = 1
COLUMN_HOST = 2
COLUMN_DB = 3
COLUMN_COMMAND = 4
COLUMN_TIME = 5  # Seconds the query has been running
COLUMN_STATE = 6
COLUMN_INFO = 7
```

**Update `_parse_processlist_rows()` method:**

```python
def _parse_processlist_rows(
    self, rows: list[dict[str, Any]]
) -> ProcesslistSnapshot:
    """Parse processlist rows into snapshot."""
    tables: dict[str, TableProgress] = {}
    active_threads = 0

    for row in rows:
        db = row.get("db") or row.get("Db")
        info = row.get("Info") or row.get("info") or ""
        state = row.get("State") or row.get("state") or ""
        query_time = row.get("Time") or row.get("time") or 0  # NEW: capture Time
        
        if db != self._config.staging_db:
            continue
        
        if not info or not isinstance(info, str):
            continue

        # Existing: Check for INSERT/LOAD with completion comment
        info_upper = info.upper()
        has_completed = "/* COMPLETED:" in info_upper
        has_data_op = "INSERT" in info_upper or "LOAD" in info_upper
        
        if has_completed and has_data_op:
            active_threads += 1
            table_match = RE_INSERT_TABLE.search(info) or RE_LOAD_TABLE.search(info)
            if table_match:
                table_name = table_match.group(1)
                percent = self._extract_percent(info)
                self._update_table_progress(
                    tables, table_name, percent, 
                    phase="loading_data",
                    running_seconds=int(query_time),
                )
            continue
        
        # NEW: Check for ALTER TABLE ADD KEY (index rebuild)
        if state == "altering table" or RE_ALTER_TABLE.search(info):
            alter_match = RE_ALTER_TABLE.search(info)
            if alter_match and RE_ADD_KEY.search(info):
                table_name = alter_match.group(1)
                active_threads += 1
                self._update_table_progress(
                    tables, table_name, None,
                    phase="rebuilding_indexes",
                    running_seconds=int(query_time),
                )

    return ProcesslistSnapshot(
        tables=tables,
        active_threads=active_threads,
        timestamp=time.monotonic(),
    )
```

#### File 6: Updates to `pulldb/web/features/jobs/routes.py`

**Add to EVENT_TO_PHASE mapping:**

```python
EVENT_TO_PHASE = {
    # ... existing mappings ...
    
    # NEW: Index rebuild tracking events
    "table_index_rebuild_queued": "restoring",
    "table_index_rebuild_started": "restoring",
    "table_index_rebuild_progress": "restoring",
    "table_index_rebuild_complete": "restoring",
    
    # NEW: ANALYZE TABLE events
    "analyze_tables_started": "restoring",
    "table_analyze_started": "restoring",
    "table_analyze_complete": "restoring",
    "table_analyze_failed": "restoring",
    "analyze_tables_complete": "restoring",
}
```

#### File 7: UI Template Updates

**Add to job details template (table progress section):**

```html
{% for table_name, table_info in tables.items() %}
<div class="log-progress-table-row">
    <span class="table-name">{{ table_name }}</span>
    
    {% if table_info.phase == "loading_data" %}
        <div class="log-progress-bar-container">
            <div class="log-progress-bar" style="width: {{ table_info.progress_pct or 0 }}%"></div>
        </div>
        <span class="progress-percent">{{ table_info.progress_pct or 0 | round(1) }}%</span>
    
    {% elif table_info.phase == "rebuilding_indexes" %}
        <div class="log-progress-spinner-container">
            <span class="spinner spinner--small"></span>
            <span class="progress-phase">Rebuilding indexes...</span>
            <span class="progress-time">{{ table_info.running_seconds | format_duration }}</span>
        </div>
    
    {% elif table_info.phase == "analyzing" %}
        <div class="log-progress-spinner-container">
            <span class="spinner spinner--small"></span>
            <span class="progress-phase">Analyzing statistics...</span>
        </div>
    
    {% elif table_info.phase == "complete" or table_info.is_complete %}
        <div class="log-progress-complete">
            <span class="icon-check">✓</span>
            <span class="progress-phase">Complete</span>
        </div>
    {% endif %}
</div>
{% endfor %}
```

#### File 8: CSS Additions

**Add to main CSS file:**

```css
/* Phase 5: Index rebuild spinner display */
.log-progress-spinner-container {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.spinner--small {
    width: 16px;
    height: 16px;
    border-width: 2px;
}

.progress-phase {
    color: var(--warning-text);
    font-style: italic;
}

.progress-time {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 0.875rem;
}

.log-progress-complete {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--success-text);
}

.icon-check {
    color: var(--success-text);
    font-weight: bold;
}
```

#### File 9: Jinja2 Filter Addition

**Add to `pulldb/web/dependencies.py`:**

```python
def _format_duration(seconds: int | None) -> str:
    """Format seconds as human-readable duration (e.g., '1h 23m 45s')."""
    if seconds is None or seconds < 0:
        return "0s"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    else:
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h {m}m {s}s"

# Register filter with Jinja2 environment
app.jinja_env.filters["format_duration"] = _format_duration
```

---

## Implementation Summary Checklists

### Phase 1: Quick Fix - ISIZE Optimization (HIGH PRIORITY)
**Goal**: Fix 8-minute delay with minimal code change.  
**Effort**: ~2 hours | **Risk**: Low | **Impact**: High

- [ ] Add `import struct` to metadata_synthesis.py
- [ ] Add `get_gzip_uncompressed_size()` function
- [ ] Add `estimate_rows_from_size()` function  
- [ ] Replace `count_rows_in_file()` body (keep signature)
- [ ] Add unit tests for new functions
- [ ] Update existing tests to accept estimates
- [ ] Run full test suite
- [ ] Manual benchmark verification

### Phase 1B: Sampling Enhancement (OPTIONAL - Improved Accuracy)
**Goal**: Improve estimation accuracy from ±50% to ±15%.  
**Effort**: ~1 hour | **Risk**: Low | **Impact**: Medium (UX - smoother progress bars)

- [ ] Add `estimate_rows_by_sampling()` function (8KB sample)
- [ ] Update `count_rows_in_file()` to use sampling
- [ ] Add accuracy tests with known row counts
- [ ] Benchmark sampling overhead (~5ms/file expected)

**Note**: Only implement if Phase 1's ±50% accuracy causes UX issues (erratic progress bars).

### Phase 2: Module Unification (MEDIUM PRIORITY - FUTURE)
**Goal**: Clean architecture with clear responsibilities.  
**Effort**: ~4 hours | **Risk**: Medium | **Impact**: Medium (maintainability)

- [ ] Create `pulldb/worker/backup_metadata.py`
- [ ] Implement all core functions (see detailed plan)
- [ ] Create `tests/test_backup_metadata.py`
- [ ] Update `restore.py` imports and usage
- [ ] Add deprecation warnings to old modules
- [ ] Run full test suite
- [ ] Update documentation
- [ ] Schedule old module removal

### Phase 3: Event Visibility (MEDIUM PRIORITY)
- [ ] Add `event_callback` parameter to `run_myloader()`
- [ ] Emit `metadata_compatibility_check` event (instant now)
- [ ] Emit `row_estimation_started/complete` events (if needed)
- [ ] Wire callback through `orchestrate_restore_workflow()`
- [ ] Add new events to `EVENT_TO_PHASE` mapping in routes.py

### Phase 4: connect_timeout_seconds (MEDIUM PRIORITY)
- [ ] Add to `WorkerExecutorTimeouts` dataclass
- [ ] Add to Config class with env var support
- [ ] Pass to `StagingConnectionSpec` in `_build_connection_specs()`
- [ ] Add to admin settings page if not present
- [ ] Update documentation

### Phase 5: Index Rebuild Tracking & ANALYZE TABLE (MEDIUM PRIORITY)
- [ ] Create `pulldb/worker/myloader_log_parser.py` with log parsing and state tracking
- [ ] Update ProcesslistMonitor with ALTER TABLE detection and Time column capture
- [ ] Create `pulldb/worker/restore_state_tracker.py` to coordinate log + processlist signals
- [ ] Create `pulldb/worker/table_analyzer.py` with `analyze_tables()` function
- [ ] Update `restore.py` to use log parser and call ANALYZE TABLE post-restore
- [ ] Add new events to `EVENT_TO_PHASE` in routes.py
- [ ] Add UI updates: `_format_duration()` filter, spinner, phase display
- [ ] Create comprehensive tests for all new modules
- [ ] Manual verification with real myloader restore (foxpest backup)

---

## Files to Modify

### Phase 1 (Quick Fix)
| File | Change |
|------|--------|
| `pulldb/worker/metadata_synthesis.py` | Replace `count_rows_in_file()` internals with ISIZE estimation |
| `tests/test_worker_metadata_synthesis.py` | Add tests for ISIZE functions, update row count expectations |

### Phase 1B (Sampling - Optional)
| File | Change |
|------|--------|
| `pulldb/worker/metadata_synthesis.py` | Add `estimate_rows_by_sampling()`, update `count_rows_in_file()` |
| `tests/test_worker_metadata_synthesis.py` | Add accuracy tests with known row counts |

### Phase 2 (Module Unification - Future)
| File | Change |
|------|--------|
| `pulldb/worker/backup_metadata.py` | NEW - unified module |
| `pulldb/worker/restore.py` | Update imports to use new module |
| `pulldb/worker/metadata_synthesis.py` | DEPRECATE |
| `pulldb/worker/dump_metadata.py` | DEPRECATE |

### Phase 3-4 (Events & Config)
| File | Change |
|------|--------|
| `pulldb/worker/restore.py` | Add event_callback to run_myloader() |
| `pulldb/worker/executor.py` | Add connect_timeout_seconds to timeouts |
| `pulldb/domain/config.py` | Add connect_timeout_seconds config |
| `pulldb/web/features/jobs/routes.py` | Add new events to phase mapping |

### Phase 5 (Index Tracking & ANALYZE TABLE)
| File | Change |
|------|--------|
| `pulldb/worker/myloader_log_parser.py` | NEW - `MyloaderLogParser` class, `TablePhase` enum, regex patterns for myloader stdout |
| `pulldb/worker/table_analyzer.py` | NEW - `analyze_tables()` function with batch support |
| `pulldb/worker/restore_state_tracker.py` | NEW - `RestoreStateTracker` coordinates log parser + processlist |
| `pulldb/worker/processlist_monitor.py` | Add `RE_ALTER_TABLE`, `RE_ADD_KEY` regexes; add `Time` column capture; update `_parse_processlist_rows()` |
| `pulldb/worker/restore.py` | Import new modules; update `_progress_callback()` to use log parser; add ANALYZE TABLE call |
| `pulldb/web/features/jobs/routes.py` | Add new events: `table_index_rebuild_*`, `table_analyze_*` to `EVENT_TO_PHASE` |
| `pulldb/web/dependencies.py` | Add `_format_duration()` Jinja2 filter |
| `pulldb/web/templates/jobs/details.html` | Add phase display with spinner for index rebuild |
| `pulldb/web/static/css/main.css` | Add `.log-progress-spinner-container`, `.spinner--small`, `.progress-phase` styles |
| `pulldb/domain/config.py` | Add `analyze_after_restore` and `index_tracking_enabled` config options |
| `tests/test_myloader_log_parser.py` | NEW - tests for regex patterns and parser state machine |
| `tests/test_table_analyzer.py` | NEW - tests for `analyze_tables()` |
| `tests/test_restore_state_tracker.py` | NEW - tests for state coordination |
| `tests/test_worker_processlist_monitor.py` | Add ALTER TABLE detection and Time column tests |

---

## Validation Criteria

1. **Performance**: Time from `restore_started` to `myloader_started` should drop from minutes to seconds
2. **Accuracy**: Row estimates should be within 50% of actual (sufficient for progress bars)
3. **Tests**: All existing tests pass + new tests for gzip size reading
4. **Events**: Metadata synthesis progress visible in job details UI
5. **Index Tracking**: Table not marked "finished" until ALTER TABLE ADD KEY completes
6. **Statistics**: All restored tables have ANALYZE TABLE run with `NO_WRITE_TO_BINLOG`

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| ISIZE wrong for files > 4GB | Low | Low | ISIZE wraps at 4GB but SQL files rarely exceed this |
| Row estimate inaccurate | Medium | Low | Progress bars tolerate ±50% error |
| Breaking metadata synthesis | Medium | High | Comprehensive test coverage |
| myloader compatibility | Low | High | No changes to actual myloader invocation |
| ALTER TABLE detection false positives | Low | Low | Require both ALTER TABLE match AND ADD KEY match |
| ANALYZE TABLE adds restore time | Low | Low | Fast for InnoDB (sampling), configurable |

---

## References

- Gzip file format: RFC 1952 (ISIZE is last 4 bytes, little-endian uint32)
- Python struct module: https://docs.python.org/3/library/struct.html
- MySQL ANALYZE TABLE: https://dev.mysql.com/doc/refman/8.0/en/analyze-table.html
- MySQL --optimize-keys: https://docs.percona.com/mydumper/myloader_usage.html
- Current implementation: `pulldb/worker/metadata_synthesis.py`
- ProcesslistMonitor: `pulldb/worker/processlist_monitor.py`
- HCA layer: features (pulldb/worker/)

---

## Appendix: Actual Code Locations (Audited)

### Call Chain (verified via grep/read_file)
```
orchestrate_restore_workflow() [restore.py:447]
  └── run_myloader() [restore.py:241, called at 594]
        ├── _detect_backup_version() [restore.py:267]
        ├── ensure_compatible_metadata() [metadata_synthesis.py:165, called at 270]
        │     └── synthesize_metadata() [metadata_synthesis.py:85, called at 200]
        │           └── count_rows_in_file() [metadata_synthesis.py:63, called at 96] ← BOTTLENECK
        └── parse_dump_metadata() [dump_metadata.py:60, called at 273]
              └── _parse_ini_metadata() [dump_metadata.py:100] ← Reads synthesized INI (fast)
                  OR _scan_dump_files() [dump_metadata.py:146] ← Also calls count_rows_in_file!
```

**Note**: For 0.9 backups, `ensure_compatible_metadata()` creates the INI first, so `parse_dump_metadata()` finds and reads it (fast path). The bottleneck is the SYNTHESIS step.

### Key Line Numbers
| File | Function/Line | Purpose |
|------|---------------|---------|
| `restore.py:241` | `run_myloader()` signature | Missing `event_callback` param |
| `restore.py:270` | `ensure_compatible_metadata()` call | Where synthesis happens |
| `restore.py:475` | `_emit_event()` helper | Local to orchestrate, can't pass down |
| `restore.py:585` | `myloader_started` event | Emitted AFTER synthesis completes |
| `metadata_synthesis.py:63` | `count_rows_in_file()` | THE BOTTLENECK |
| `metadata_synthesis.py:72` | `for line in f:` | Iterates entire file |
| `metadata_synthesis.py:96` | `rows = count_rows_in_file(...)` | Called per file in loop |

### Test Coverage
- `tests/test_worker_metadata_synthesis.py` - Has tests for `count_rows_in_file`, `parse_filename`, `synthesize_metadata`
- Need to add tests for new `get_gzip_uncompressed_size()` function
