# Research Report: Optimizing Legacy Backup Restoration & Unified Loader Strategy

**Date:** November 25, 2025
**Status:** Draft / Planning
**Target:** pullDB Architecture

## 1. Executive Summary

The current dual-loader approach (using `myloader` 0.9 for legacy backups and 0.19 for modern backups) has revealed significant performance and stability issues with the legacy path. Specifically, `myloader` 0.9 lacks granular concurrency controls (e.g., `--max-threads-per-table`), leading to excessive locking and I/O saturation when multiple threads target the same table.

**Recommendation:**
Abandon the use of the legacy `myloader` 0.9 binary. Instead, standardize on `myloader` 0.19+ for **all** backup formats. If direct compatibility is missing (due to metadata format differences), implement a **Metadata Synthesis** step to bridge the gap. This unlocks modern concurrency controls for legacy backups without the high risk/complexity of converting SQL to CSV on the fly.

## 2. Problem Analysis: The v0.9 Concurrency Bottleneck

### The Issue
`myloader` 0.9 uses a simple work-stealing queue. If a large table is split into 100 chunks and the worker pool has 16 threads, it is statistically likely that all 16 threads will eventually grab chunks for the same large table.

### The Impact
*   **InnoDB Locking**: Heavy contention on auto-increment locks (if applicable) and page locks.
*   **I/O Saturation**: Random I/O spikes as multiple threads fight for the same tablespace pages.
*   **Deadlocks**: Increased probability of gap lock contention.

### The v0.19 Solution
Modern `myloader` (0.16+) introduces `--max-threads-per-table`. By setting this to a low value (e.g., 4), we force the loader to diversify its workload across multiple tables, significantly smoothing I/O patterns and reducing lock contention.

## 3. Proposed Strategy: Unified Loader (Metadata Synthesis)

Instead of maintaining two execution paths, we should enable `myloader` 0.19 to ingest v0.9 backups.

### Feasibility
*   **SQL Compatibility**: Both versions use standard `INSERT INTO` statements. `myloader` 0.19 can execute these without issue.
*   **Compression**: `myloader` 0.19 supports GZIP (`.gz`), which is the format of v0.9 backups.
*   **The Gap**: The `metadata` file. `myloader` relies on this file to discover tables and chunks. The v0.9 metadata format (if present) may be incompatible or missing the fields 0.19 expects.

### Implementation Plan
1.  **Pre-Flight Scan**: Before invoking `myloader`, the Python worker scans the extracted backup directory.
2.  **Metadata Synthesis**: If a valid 0.19 `metadata` file is missing, the worker generates one.
    *   It lists all `.sql.gz` files.
    *   It groups them by table.
    *   It writes a `metadata` file conforming to the 0.19 spec.
3.  **Execution**: Invoke `myloader` 0.19 pointing to the directory. It "sees" a valid modern backup and applies all advanced logic (including `--max-threads-per-table`).

### Pros
*   **Solves Locking**: Immediately enables `--max-threads-per-table` for legacy backups.
*   **Code Simplicity**: Removes the "dual binary" logic from `restore.py`.
*   **Robustness**: Uses the battle-tested 0.19 binary for parsing and execution.

### Cons
*   **Development Cost**: Requires reverse-engineering the 0.19 `metadata` format (text-based INI style) and writing a generator.

## 4. Alternative Strategy: `LOAD DATA LOCAL INFILE` Conversion

The user requested an analysis of converting `INSERT` statements to `LOAD DATA` streams.

### Concept
Create a Python generator that reads `.sql.gz` streams, strips SQL syntax (`INSERT INTO...`), parses the value lists, and emits CSV-formatted rows to a MySQL connection using `LOAD DATA LOCAL INFILE`.

### Analysis
*   **Performance**: `LOAD DATA` is typically 2-3x faster than bulk `INSERT`.
*   **Complexity (High)**:
    *   **Parsing**: SQL values are complex. A simple regex fails on escaped quotes inside strings (`'It\'s a trap'`), binary data, or NULLs. A robust parser is required, which is slow in Python.
    *   **Error Handling**: A single parsing error aborts the stream.
*   **Risk**: High probability of data corruption (e.g., truncated strings, shifted columns) due to parsing mismatches.

### Verdict
**Not Recommended for Restore-Time.** The complexity and risk outweigh the performance benefits, especially since `myloader`'s bulk inserts are already quite efficient. This optimization belongs at the **Backup** stage (using `mydumper --csv`), not the Restore stage.

## 5. Validation Strategy

To ensure data integrity regardless of the method used:

1.  **Row Counts (Fast)**:
    *   Run `SELECT COUNT(*) FROM table` on Source (if available) and Target.
    *   *Note*: `COUNT(*)` on InnoDB is slow unless `ANALYZE TABLE` is fresh (approximate) or a full scan is forced.
2.  **Checksums (Robust)**:
    *   `CHECKSUM TABLE table_name`.
    *   Very slow for large tables but guarantees exact matches.
3.  **Composite Metrics (Recommended)**:
    *   Sum of a numeric ID column: `SELECT SUM(id) FROM table`.
    *   Faster than full checksum, catches missing rows better than count (if IDs are sequential).

## 6. Next Steps

1.  **Verify Compatibility**: Manually attempt to run `myloader` 0.19 against a 0.9 backup directory. Capture the error (likely "metadata file not found" or "invalid format").
2.  **Analyze Metadata**: Compare a v0.9 `metadata` file (if it exists) with a v0.19 `metadata` file.
3.  **Prototype Synthesizer**: Write a script to generate a 0.19-compatible `metadata` file from a list of `.sql.gz` files.
4.  **Test**: Perform a restore of a 0.9 backup using the Synthesizer + `myloader` 0.19 with `--max-threads-per-table=4`. Measure locking metrics.
