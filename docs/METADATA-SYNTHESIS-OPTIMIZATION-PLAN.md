# Metadata Synthesis Optimization Plan

**Created**: January 13, 2026  
**Status**: AUDIT COMPLETE - AWAITING IMPLEMENTATION  
**Root Cause**: 8-minute delay between `restore_started` and `restore_progress` for job 4616272e

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
    """Parse processlist for both INSERT/LOAD and ALTER TABLE operations."""
    result = {
        "active_tables": {},      # Table -> progress info
        "loading_tables": [],     # Tables with active INSERT/LOAD
        "indexing_tables": [],    # Tables with active ALTER TABLE ADD KEY
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    for row in rows:
        info = str(row[INFO_INDEX]) if row[INFO_INDEX] else ""
        state = str(row[STATE_INDEX]) if row[STATE_INDEX] else ""
        
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
                }
    
    return result
```

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
| `table_index_rebuild_started` | `{table: str}` | ALTER TABLE ... ADD KEY detected |
| `table_index_rebuild_complete` | `{table: str}` | ALTER TABLE finishes |
| `table_analyze_started` | `{table: str}` | ANALYZE TABLE begins |
| `table_analyze_complete` | `{table, status, message}` | ANALYZE TABLE returns |
| `analyze_tables_started` | `{table_count: int}` | Batch analysis begins |
| `analyze_tables_complete` | `{success_count, total_count}` | All tables analyzed |

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

- [ ] Add `RE_ALTER_TABLE` and `RE_ADD_KEY` regexes to processlist_monitor.py
- [ ] Add `TableRestorePhase` enum and `TableRestoreState` dataclass
- [ ] Update `_parse_processlist_rows()` to detect ALTER TABLE ADD KEY
- [ ] Track table state transitions: loading → indexing → complete
- [ ] Create `pulldb/worker/table_analyzer.py` with `analyze_tables()` function
- [ ] Use `NO_WRITE_TO_BINLOG` to avoid replication overhead
- [ ] Integrate ANALYZE TABLE into `orchestrate_restore_workflow()`
- [ ] Add new events to `EVENT_TO_PHASE` mapping in routes.py
- [ ] Create `tests/test_table_analyzer.py`
- [ ] Add ALTER TABLE detection tests to processlist_monitor tests
- [ ] Update UI to show index rebuild phase (optional enhancement)
- [ ] Run full test suite
- [ ] Manual verification with real myloader restore

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
- [ ] Extend ProcesslistMonitor to track ALTER TABLE statements (index rebuilds)
- [ ] Add table state machine: `loading_data` → `rebuilding_indexes` → `complete`
- [ ] Don't mark table "finished" until ALTER TABLE completes
- [ ] Execute `ANALYZE TABLE` on each restored table for accurate statistics
- [ ] Emit granular events: `table_index_rebuild_*`, `table_analyze_*`

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
| `pulldb/worker/processlist_monitor.py` | Add `RE_ALTER_TABLE`, `RE_ADD_KEY` regexes; `TableRestorePhase` enum; update `_parse_processlist_rows()` |
| `pulldb/worker/table_analyzer.py` | NEW - `analyze_tables()` function with batch support |
| `pulldb/worker/restore.py` | Integrate ANALYZE TABLE after myloader completes |
| `pulldb/web/features/jobs/routes.py` | Add new events: `table_index_rebuild_*`, `table_analyze_*` |
| `tests/test_table_analyzer.py` | NEW - tests for analyze_tables() |
| `tests/test_worker_processlist_monitor.py` | Add ALTER TABLE detection tests |

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
