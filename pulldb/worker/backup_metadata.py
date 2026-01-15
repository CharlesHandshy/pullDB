"""Unified backup metadata handling for myloader compatibility and progress tracking.

This module provides a single interface for:
1. Ensuring backups are compatible with myloader 0.19+
2. Extracting row estimates for progress tracking
3. Parsing binlog positions for replication setup

HCA Layer: features (pulldb/worker/)

Replaces (and re-exports from):
- metadata_synthesis.py (row estimation, INI synthesis)
- dump_metadata.py (metadata parsing for progress)

The old modules are deprecated and will be removed in a future version.
This module consolidates their functionality with clearer responsibilities.
"""

from __future__ import annotations

import configparser
import gzip
import os
import re
import struct
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pulldb.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger("pulldb.worker.backup_metadata")


# ============================================================================
# Constants
# ============================================================================

# Default bytes per row for estimation (fallback when sampling fails)
DEFAULT_BYTES_PER_ROW = 200

# Sample size for row estimation (64KB for better accuracy)
DEFAULT_SAMPLE_BYTES = 65536

# Safety margin for row estimation (10% overestimate prevents progress > 100%)
ESTIMATION_SAFETY_MARGIN = 1.10

# Minimum parts for database.table parsing
_MIN_DB_TABLE_PARTS = 2

# Parallel row counting defaults
DEFAULT_MAX_WORKERS = 8
ROW_COUNT_CHUNK_REPORT = 100_000  # Report progress every 100K rows


# ============================================================================
# Data Classes and Enums
# ============================================================================


class MetadataFormat(Enum):
    """Detected backup metadata format."""

    INI_0_19 = "0.19+"  # Modern INI format with rows
    LEGACY_0_9 = "0.9"  # Legacy text format
    MISSING = "missing"  # No metadata file
    UNKNOWN = "unknown"  # Unrecognized format


@dataclass(slots=True, frozen=True)
class BinlogPosition:
    """MySQL binlog position from backup metadata.

    Attributes:
        file: Binlog filename (e.g., 'mysql-bin.000042').
        position: Byte position in binlog file.
        gtid_set: GTID set string if available.
    """

    file: str
    position: int
    gtid_set: str = ""


@dataclass(slots=True, frozen=True)
class TableRowEstimate:
    """Row estimate for a single table.

    Attributes:
        database: Database name.
        table: Table name.
        rows: Estimated row count.
    """

    database: str
    table: str
    rows: int


@dataclass(slots=True, frozen=True)
class BackupMetadata:
    """Complete parsed backup metadata.

    Attributes:
        format: Detected metadata format.
        tables: List of tables with row estimates.
        total_rows: Sum of all table row estimates.
        binlog: Binlog position if available.
    """

    format: MetadataFormat
    tables: list[TableRowEstimate]
    total_rows: int
    binlog: BinlogPosition | None


# ============================================================================
# Public API
# ============================================================================


def ensure_myloader_compatibility(
    backup_dir: str,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> MetadataFormat:
    """Ensure backup has valid metadata for myloader 0.19+.

    For legacy 0.9 backups, uses parallel streaming row count (exact, not sampled).
    For existing 0.19+ backups, returns immediately (metadata already has counts).

    If metadata is missing or in legacy format, creates an INI file with:
    - [config] section for myloader settings
    - [myloader_session_variables] for consistent restore
    - [source] for binlog position (if available)
    - [db.table] sections with exact row counts

    Args:
        backup_dir: Path to extracted backup directory.
        event_callback: Optional callback for progress events during row counting.
            Events emitted (for legacy backups):
            - "row_count_start": {"total_files": int, "backup_dir": str}
            - "row_count_file_done": {"file": str, "rows": int, "files_done": int, "total_files": int}
            - "row_count_complete": {"total_rows": int, "files_processed": int, "elapsed_sec": float}

    Returns:
        Detected/created metadata format.
    """
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
        logger.info(f"Creating metadata for myloader: {backup_dir}")

    _synthesize_metadata(backup_dir, str(metadata_path), binlog, event_callback)
    return MetadataFormat.INI_0_19


def get_backup_metadata(backup_dir: str) -> BackupMetadata:
    """Get complete backup metadata including row estimates.

    Tries to parse existing INI metadata first. Falls back to ISIZE estimation
    if metadata is missing or in legacy format.

    Args:
        backup_dir: Path to extracted backup directory.

    Returns:
        BackupMetadata with tables, row estimates, and binlog position.
    """
    path = Path(backup_dir)
    metadata_path = path / "metadata"
    detected = _detect_metadata_format(backup_dir)

    # Try INI format first
    if detected == MetadataFormat.INI_0_19 and metadata_path.exists():
        tables = _parse_ini_metadata(metadata_path)
        if tables:
            total_rows = sum(t.rows for t in tables)
            binlog = parse_binlog_position(backup_dir)
            logger.info(
                f"Parsed INI metadata: {len(tables)} tables, {total_rows:,} total rows"
            )
            return BackupMetadata(
                format=detected,
                tables=tables,
                total_rows=total_rows,
                binlog=binlog,
            )

    # Fall back to file scanning with ISIZE estimation
    tables = _scan_for_row_estimates(path)
    total_rows = sum(t.rows for t in tables)
    binlog = parse_binlog_position(backup_dir)
    logger.info(
        f"Scanned dump files: {len(tables)} tables, {total_rows:,} total rows"
    )
    return BackupMetadata(
        format=detected,
        tables=tables,
        total_rows=total_rows,
        binlog=binlog,
    )


def get_table_row_estimates(backup_dir: str) -> list[TableRowEstimate]:
    """Get row estimates for all tables in backup.

    Uses fastest available method:
    1. If 0.19+ INI exists with rows: parse it
    2. Otherwise: use gzip ISIZE estimation

    Args:
        backup_dir: Path to extracted backup directory.

    Returns:
        List of TableRowEstimate for each table.
    """
    return get_backup_metadata(backup_dir).tables


def parse_binlog_position(backup_dir: str) -> BinlogPosition | None:
    """Extract binlog position from backup metadata.

    Supports both legacy text format and INI format.

    Args:
        backup_dir: Path to extracted backup directory.

    Returns:
        BinlogPosition if found, None otherwise.
    """
    metadata_path = Path(backup_dir) / "metadata"

    if not metadata_path.exists():
        return None

    try:
        content = metadata_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read metadata for binlog: {e}")
        return None

    # Check if INI format
    if content.strip().startswith("["):
        return _parse_ini_binlog(content)
    else:
        return _parse_legacy_binlog(content)


# ============================================================================
# ISIZE-based Row Estimation (from metadata_synthesis.py)
# ============================================================================


def get_gzip_uncompressed_size(filepath: str) -> int:
    """Read ISIZE from gzip trailer - O(1), no decompression required.

    Per RFC 1952, the last 4 bytes of a gzip file contain the uncompressed
    size modulo 2^32 (little-endian uint32). For files under 4GB, this gives
    the exact uncompressed size.

    Args:
        filepath: Path to a gzip file.

    Returns:
        Uncompressed size in bytes, or 0 if the file cannot be read.
    """
    try:
        with open(filepath, "rb") as f:
            f.seek(-4, 2)  # Seek 4 bytes before end
            result: int = struct.unpack("<I", f.read(4))[0]
            return result
    except (OSError, struct.error):
        return 0


def estimate_rows_from_size(
    uncompressed_size: int, bytes_per_row: int = DEFAULT_BYTES_PER_ROW
) -> int:
    """Estimate row count from uncompressed file size.

    Uses a heuristic based on mydumper's extended INSERT format, where each
    row averages approximately 200 bytes including SQL syntax overhead.

    Args:
        uncompressed_size: Size in bytes of the uncompressed SQL file.
        bytes_per_row: Average bytes per row (default: 200).

    Returns:
        Estimated number of rows, minimum 1.
    """
    if uncompressed_size <= 0 or bytes_per_row <= 0:
        return 1
    return max(1, uncompressed_size // bytes_per_row)


def estimate_rows_by_sampling(
    filepath: str,
    sample_bytes: int = DEFAULT_SAMPLE_BYTES,
    fallback_bytes_per_row: int = DEFAULT_BYTES_PER_ROW,
) -> int:
    """Estimate row count by sampling first N bytes of SQL file.

    More accurate than pure ISIZE/200 because it measures actual row density
    in the specific file's format (extended inserts, column count, data types).

    Counting logic:
    - `),(` = row separators within an INSERT statement
    - `);` = INSERT statement terminators (each adds 1 row)
    - Total rows = separators + terminators

    Args:
        filepath: Path to gzip-compressed SQL file.
        sample_bytes: How many uncompressed bytes to sample (default 64KB).
        fallback_bytes_per_row: Fallback divisor if sampling fails.

    Returns:
        Estimated row count with safety margin applied (minimum 1).
    """
    total_size = get_gzip_uncompressed_size(filepath)
    if total_size == 0:
        logger.warning(f"Could not read ISIZE from {filepath}, defaulting to 1 row")
        return 1

    try:
        with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            sample = f.read(sample_bytes)
    except Exception as e:
        logger.warning(f"Sampling failed for {filepath}: {e}, using fallback")
        return _apply_safety_margin(
            estimate_rows_from_size(total_size, fallback_bytes_per_row)
        )

    if not sample:
        return _apply_safety_margin(
            estimate_rows_from_size(total_size, fallback_bytes_per_row)
        )

    # Count row indicators
    row_separators = sample.count("),(")  # Rows 2..N within each INSERT
    statement_ends = sample.count(");")  # Final row of each INSERT
    rows_in_sample = row_separators + statement_ends

    if rows_in_sample == 0:
        return _apply_safety_margin(
            estimate_rows_from_size(total_size, fallback_bytes_per_row)
        )

    # Calculate bytes per row from sample and extrapolate
    sample_len = len(sample.encode("utf-8"))
    bytes_per_row_measured = sample_len / rows_in_sample
    raw_estimated_rows = int(total_size / bytes_per_row_measured)
    estimated_rows = _apply_safety_margin(raw_estimated_rows)

    logger.debug(
        f"Sampled {filepath}: {rows_in_sample} rows in {sample_len} bytes "
        f"({bytes_per_row_measured:.1f} bytes/row) → {raw_estimated_rows} raw, "
        f"{estimated_rows} with margin"
    )

    return estimated_rows


def count_rows_in_file(filepath: str) -> int:
    """Estimate rows in a mydumper SQL file using sampling.

    Uses 64KB sample to measure actual bytes-per-row, then extrapolates
    using gzip ISIZE with 10% safety margin.

    Args:
        filepath: Path to a .sql.gz mydumper data file.

    Returns:
        Estimated row count with safety margin (minimum 1).
    """
    return estimate_rows_by_sampling(filepath)


def count_rows_streaming(filepath: str) -> int:
    """Count exact rows in a mydumper SQL file by streaming decompression.

    Uses line-by-line streaming to count INSERT statements without loading
    the full file into memory. Memory usage is ~10KB (one line buffer).

    mydumper 0.9 format:
    - INSERT INTO `t` VALUES(row1_data)
    - ,(row2_data)
    - ,(row3_data)
    - ;

    Each INSERT line = 1 row, each line starting with ,( = 1 row.

    Args:
        filepath: Path to a .sql.gz mydumper data file.

    Returns:
        Exact row count (0 if no INSERT statements found).
    """
    row_count = 0

    try:
        with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("INSERT INTO "):
                    # INSERT line contains the first row
                    row_count += 1
                elif line.startswith(",("):
                    # Continuation line = one row
                    row_count += 1
    except (OSError, gzip.BadGzipFile) as e:
        logger.warning(f"Failed to stream {filepath}: {e}")
        return 0

    return row_count


def count_rows_parallel(
    backup_dir: str,
    max_workers: int | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, int]:
    """Count exact rows in all .sql.gz files using parallel streaming.

    Processes files in parallel with streaming decompression. Each worker
    uses ~10KB memory (one line buffer). Emits progress events for UI.

    Files with 0 rows (empty tables) are excluded from results.

    Args:
        backup_dir: Directory containing .sql.gz backup files.
        max_workers: Maximum parallel workers (default: min(8, cpu_count)).
        event_callback: Optional callback for progress events.
            Events emitted:
            - "row_count_start": {"total_files": int, "backup_dir": str}
            - "row_count_file_done": {"file": str, "rows": int, "rows_so_far": int, "files_done": int, "total_files": int}
            - "row_count_complete": {"total_rows": int, "files_processed": int, "elapsed_sec": float}

    Returns:
        Dict mapping filename (without path) to row count (excludes 0-row files).
    """
    import time

    path = Path(backup_dir)
    sql_files = sorted(path.glob("*.sql.gz"))

    # Filter to data files only (exclude schema files)
    data_files = [f for f in sql_files if "-schema" not in f.name]

    if not data_files:
        logger.debug(f"No data files found in {backup_dir}")
        return {}

    workers = min(max_workers or DEFAULT_MAX_WORKERS, len(data_files), os.cpu_count() or 4)
    logger.info(f"Counting rows in {len(data_files)} files with {workers} workers")

    if event_callback:
        event_callback("row_count_start", {"total_files": len(data_files), "backup_dir": backup_dir})

    start_time = time.monotonic()
    results: dict[str, int] = {}
    files_done = 0
    rows_so_far = 0  # Cumulative row count for progress events

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_file = {
            executor.submit(count_rows_streaming, str(f)): f for f in data_files
        }

        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                row_count = future.result()
            except Exception as e:
                logger.warning(f"Failed to count {file_path.name}: {e}")
                row_count = 0

            # Only include files with actual rows
            if row_count > 0:
                results[file_path.name] = row_count
                rows_so_far += row_count

            files_done += 1

            if event_callback:
                event_callback(
                    "row_count_file_done",
                    {
                        "file": file_path.name,
                        "rows": row_count,
                        "rows_so_far": rows_so_far,
                        "files_done": files_done,
                        "total_files": len(data_files),
                    },
                )

    elapsed = time.monotonic() - start_time
    total_rows = sum(results.values())

    logger.info(
        f"Row count complete: {total_rows:,} rows in {len(results)} files ({elapsed:.1f}s)"
    )

    if event_callback:
        event_callback(
            "row_count_complete",
            {
                "total_rows": total_rows,
                "files_processed": len(results),
                "elapsed_sec": round(elapsed, 2),
            },
        )

    return results


# ============================================================================
# Internal Helpers
# ============================================================================


def _apply_safety_margin(rows: int, margin: float = ESTIMATION_SAFETY_MARGIN) -> int:
    """Apply safety margin to row estimate to prevent progress overflow."""
    return max(1, int(rows * margin))


def _detect_metadata_format(backup_dir: str) -> MetadataFormat:
    """Detect the format of existing metadata file."""
    metadata_path = Path(backup_dir) / "metadata"

    if not metadata_path.exists():
        # Check if we have data files (implies backup without metadata)
        path = Path(backup_dir)
        if any(path.glob("*.sql.gz")) or any(path.glob("*.sql.zst")):
            return MetadataFormat.MISSING
        return MetadataFormat.UNKNOWN

    try:
        with open(metadata_path, encoding="utf-8") as f:
            first_line = f.readline().strip()

        # INI files start with [section] or comments
        if first_line.startswith("["):
            return MetadataFormat.INI_0_19

        # Legacy starts with "Started dump at:" or similar
        if first_line.startswith("Started dump") or "Log:" in first_line:
            return MetadataFormat.LEGACY_0_9

        return MetadataFormat.UNKNOWN
    except Exception as e:
        logger.warning(f"Failed to read metadata file header: {e}")
        return MetadataFormat.UNKNOWN


def _parse_mydumper_filename(filename: str) -> tuple[str, str] | None:
    """Parse mydumper filename to extract database.table.

    Format: database.table.sql.gz or database.table.00001.sql.gz
    Ignores schema files (-schema.sql.gz, -schema-create.sql.gz).
    """
    if not filename.endswith(".sql.gz"):
        return None

    if "-schema.sql.gz" in filename or "-schema-create.sql.gz" in filename:
        return None

    # Remove extension
    base = filename[:-7]  # remove .sql.gz

    # Check for chunk number (e.g., .00001)
    parts = base.split(".")
    if len(parts) < _MIN_DB_TABLE_PARTS:
        return None

    # If the last part is a number, it's a chunk
    if parts[-1].isdigit():
        parts.pop()

    if len(parts) < _MIN_DB_TABLE_PARTS:
        return None

    # First part is DB, rest is table
    db_name = parts[0]
    table_name = ".".join(parts[1:])

    return db_name, table_name


def _parse_ini_metadata(metadata_path: Path) -> list[TableRowEstimate]:
    """Parse INI format metadata file for table row counts."""
    tables: list[TableRowEstimate] = []

    try:
        parser = configparser.ConfigParser()
        parser.read(str(metadata_path), encoding="utf-8")

        for section in parser.sections():
            # Skip non-table sections
            if section in ("config", "myloader", "mydumper", "binlog", "source",
                           "myloader_session_variables"):
                continue

            # Handle backtick-quoted sections: `db`.`table`
            if section.startswith("`"):
                match = re.match(r"`([^`]+)`\.`([^`]+)`", section)
                if match:
                    database, table = match.groups()
                else:
                    continue
            # Handle unquoted sections: db.table
            elif "." in section:
                parts = section.split(".", 1)
                if len(parts) != _MIN_DB_TABLE_PARTS:
                    continue
                database, table = parts
            else:
                continue

            # Get row count (0 if not present or invalid)
            rows = 0
            if parser.has_option(section, "rows"):
                with suppress(ValueError, configparser.Error):
                    rows = parser.getint(section, "rows")

            if rows > 0:
                tables.append(
                    TableRowEstimate(database=database, table=table, rows=rows)
                )

    except Exception as e:
        logger.warning(f"Failed to parse INI metadata: {e}")

    return tables


def _scan_for_row_estimates(backup_dir: Path) -> list[TableRowEstimate]:
    """Scan backup files and estimate rows using ISIZE sampling."""
    row_counts: dict[tuple[str, str], int] = {}

    # Scan .sql.gz files
    for filepath in backup_dir.glob("*.sql.gz"):
        parsed = _parse_mydumper_filename(filepath.name)
        if not parsed:
            continue

        database, table = parsed
        key = (database, table)
        rows = count_rows_in_file(str(filepath))
        row_counts[key] = row_counts.get(key, 0) + rows

    # Convert to list
    return [
        TableRowEstimate(database=db, table=tbl, rows=rows)
        for (db, tbl), rows in row_counts.items()
    ]


def _parse_ini_binlog(content: str) -> BinlogPosition | None:
    """Parse binlog position from INI format metadata."""
    try:
        parser = configparser.ConfigParser()
        parser.read_string(content)

        if parser.has_section("source"):
            file = parser.get("source", "File", fallback="")
            pos_str = parser.get("source", "Position", fallback="0")
            gtid = parser.get("source", "Executed_Gtid_Set", fallback="")

            if file:
                return BinlogPosition(
                    file=file,
                    position=int(pos_str) if pos_str.isdigit() else 0,
                    gtid_set=gtid,
                )
    except Exception as e:
        logger.warning(f"Failed to parse INI binlog: {e}")

    return None


def _parse_legacy_binlog(content: str) -> BinlogPosition | None:
    """Parse binlog position from legacy text format metadata."""
    try:
        # Legacy format:
        # Log: mysql-bin.000001
        # Pos: 123456
        m_log = re.search(r"Log:\s*(\S+)", content)
        m_pos = re.search(r"Pos:\s*(\d+)", content)

        if m_log:
            return BinlogPosition(
                file=m_log.group(1),
                position=int(m_pos.group(1)) if m_pos else 0,
                gtid_set="",
            )
    except Exception as e:
        logger.warning(f"Failed to parse legacy binlog: {e}")

    return None


def _synthesize_metadata(
    backup_dir: str,
    output_file: str,
    binlog: BinlogPosition | None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> None:
    """Synthesize myloader 0.19 compatible metadata file.

    Uses parallel streaming row counting for accurate counts (legacy 0.9 backups).

    Args:
        backup_dir: Path to backup directory.
        output_file: Path to write metadata INI file.
        binlog: Binlog position to include (or None).
        event_callback: Optional callback for progress events.
    """
    path = Path(backup_dir)
    table_rows: dict[tuple[str, str], int] = defaultdict(int)

    logger.info(f"Scanning {backup_dir} for metadata synthesis (parallel exact count)...")

    # Use parallel streaming for exact counts
    file_rows = count_rows_parallel(backup_dir, event_callback=event_callback)

    # Aggregate by table (multiple files per table possible)
    for filename, rows in file_rows.items():
        parsed = _parse_mydumper_filename(filename)
        if parsed:
            db, table = parsed
            table_rows[(db, table)] += rows

    logger.info(f"Found {len(table_rows)} tables for metadata synthesis.")

    # Generate INI content
    config = configparser.ConfigParser()
    config.optionxform = str  # type: ignore  # Preserve case

    # [config]
    config["config"] = {"quote-character": "BACKTICK", "local-infile": "1"}

    # [myloader_session_variables]
    config["myloader_session_variables"] = {
        "SQL_MODE": "'NO_AUTO_VALUE_ON_ZERO,' /*!40101",
        "foreign_key_checks": "0",
        "time_zone": "'+00:00'",
        "sql_log_bin": "0",
    }

    # [source]
    config["source"] = {
        "File": binlog.file if binlog else "",
        "Position": str(binlog.position) if binlog else "",
        "Executed_Gtid_Set": binlog.gtid_set if binlog else "",
    }

    # Table sections
    for (db, table), rows in sorted(table_rows.items()):
        section_name = f"`{db}`.`{table}`"
        config[section_name] = {"real_table_name": table, "rows": str(rows)}

    # Write output
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            config.write(f)
        logger.info(f"Synthesized metadata written to {output_file}")
    except Exception as e:
        logger.error(f"Failed to write synthesized metadata: {e}")
        raise


# ============================================================================
# Backward Compatibility Re-exports
# ============================================================================

# Re-export for backward compatibility with existing imports
# These allow gradual migration from old modules
parse_filename = _parse_mydumper_filename


# Compatibility with dump_metadata.py types
@dataclass(slots=True, frozen=True)
class DumpMetadata:
    """Compatibility wrapper for dump_metadata.parse_dump_metadata return type."""

    tables: list[TableRowEstimate]
    total_rows: int
    format_version: str


def parse_dump_metadata(backup_dir: str) -> DumpMetadata:
    """Compatibility wrapper for dump_metadata.parse_dump_metadata.

    DEPRECATED: Use get_backup_metadata() instead.
    """
    meta = get_backup_metadata(backup_dir)
    return DumpMetadata(
        tables=meta.tables,
        total_rows=meta.total_rows,
        format_version=meta.format.value,
    )


def ensure_compatible_metadata(backup_dir: str) -> None:
    """Compatibility wrapper for metadata_synthesis.ensure_compatible_metadata.

    DEPRECATED: Use ensure_myloader_compatibility() instead.
    """
    ensure_myloader_compatibility(backup_dir)
