"""Backup metadata handling for myloader compatibility and progress tracking.

This module provides a unified interface for:
1. Ensuring backups are compatible with myloader 0.19+
2. Extracting row estimates for progress tracking
3. Parsing binlog positions for replication setup

HCA Layer: features (pulldb/worker/)

Performance: Uses O(1) ISIZE estimation instead of decompressing all files.
For an 86 GiB backup, metadata handling takes ~2 seconds instead of ~20 minutes.

Replaces:
- metadata_synthesis.py (deprecated)
- dump_metadata.py (deprecated)
"""

from __future__ import annotations

import configparser
import contextlib
import gzip
import re
import struct
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pulldb.infra.logging import get_logger

if TYPE_CHECKING:
    from pulldb.domain.restore_models import ExtractionStats

logger = get_logger("pulldb.worker.backup_metadata")


# =============================================================================
# Constants
# =============================================================================

# mydumper default: 1 million rows per chunk file (fallback if detection fails)
MYDUMPER_DEFAULT_ROWS_PER_CHUNK = 1_000_000

# Size thresholds for choosing estimation strategy
SMALL_FILE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB - fast to count directly
LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB - use ISIZE estimate

# Threshold for considering a chunk "full" vs "partial" (80% of max size)
FULL_CHUNK_SIZE_RATIO = 0.80

# Estimated bytes per row in mydumper extended INSERT format (fallback)
ESTIMATED_BYTES_PER_ROW = 200

# Sampling configuration for improved row estimation accuracy
SAMPLE_BYTES = 8192  # 8KB sample size

# Minimum parts required for database.table parsing
MIN_DB_TABLE_PARTS = 2


# =============================================================================
# Enums and Data Classes
# =============================================================================


class MetadataFormat(Enum):
    """Detected backup metadata format."""

    INI_0_19 = "0.19+"  # Modern INI format with rows
    LEGACY_0_9 = "0.9"  # Legacy text format
    MISSING = "missing"  # No metadata file
    UNKNOWN = "unknown"  # Unrecognized format


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
    file_count: int = 1  # Number of data files for this table
    total_bytes: int = 0  # Total compressed size of data files (for bandwidth ETA)


@dataclass(slots=True, frozen=True)
class BackupMetadata:
    """Complete parsed backup metadata."""

    format: MetadataFormat
    tables: list[TableRowEstimate]
    total_rows: int
    binlog: BinlogPosition | None


# =============================================================================
# Event Callback Type
# =============================================================================

EventCallback = Callable[[str, dict[str, Any]], None]


# =============================================================================
# Core Public Functions
# =============================================================================


def ensure_myloader_compatibility(
    backup_dir: str,
    event_callback: EventCallback | None = None,
) -> MetadataFormat:
    """Ensure backup has valid metadata for myloader 0.19+.

    This is a FAST operation - O(1), no file scanning for compatibility check.
    If metadata needs to be created/upgraded, row estimation uses ISIZE (O(n) fast).

    Args:
        backup_dir: Path to extracted backup directory.
        event_callback: Optional callback for progress events.

    Returns:
        Detected/created metadata format.
    """
    if event_callback:
        event_callback("metadata_synthesis_started", {"backup_dir": backup_dir})

    metadata_path = Path(backup_dir) / "metadata"
    detected = _detect_metadata_format(backup_dir)

    if detected == MetadataFormat.INI_0_19:
        logger.debug(f"Backup already has 0.19+ metadata: {backup_dir}")
        if event_callback:
            event_callback(
                "metadata_synthesis_complete",
                {"backup_dir": backup_dir, "action": "none_needed", "format": "0.19+"},
            )
        return detected

    # Need to create/upgrade metadata
    binlog = parse_binlog_position(backup_dir)

    if detected == MetadataFormat.LEGACY_0_9:
        logger.info(f"Upgrading legacy 0.9 metadata to INI format: {backup_dir}")
        action = "upgraded"
    else:
        logger.info(f"Creating metadata for myloader: {backup_dir}")
        action = "created"

    # Synthesize full metadata with row estimates
    _synthesize_metadata(backup_dir, str(metadata_path), binlog, event_callback)

    if event_callback:
        event_callback(
            "metadata_synthesis_complete",
            {"backup_dir": backup_dir, "action": action, "format": "0.19+"},
        )

    return MetadataFormat.INI_0_19


def get_backup_metadata(
    backup_dir: str,
    event_callback: EventCallback | None = None,
    extraction_stats: ExtractionStats | None = None,
) -> BackupMetadata:
    """Get complete backup metadata including row estimates.

    Ensures myloader compatibility first, then parses metadata.

    Args:
        backup_dir: Path to extracted backup directory.
        event_callback: Optional callback for progress events.
        extraction_stats: Optional file size data from extraction phase to avoid re-scanning.

    Returns:
        BackupMetadata with tables, row estimates, and binlog position.
    """
    # Ensure compatibility (creates/upgrades metadata if needed)
    fmt = ensure_myloader_compatibility(backup_dir, event_callback)

    # Parse the metadata, passing file sizes if available
    file_sizes = extraction_stats.file_sizes if extraction_stats else None
    tables = get_table_row_estimates(backup_dir, file_sizes=file_sizes)
    total_rows = sum(t.rows for t in tables)
    binlog = parse_binlog_position(backup_dir)

    logger.info(
        f"Backup metadata: format={fmt.value}, "
        f"tables={len(tables)}, total_rows={total_rows:,}"
        + (", file_sizes=from_extraction" if file_sizes else ", file_sizes=scanned")
    )

    return BackupMetadata(
        format=fmt,
        tables=tables,
        total_rows=total_rows,
        binlog=binlog,
    )


def get_table_row_estimates(
    backup_dir: str,
    file_sizes: dict[str, int] | None = None,
) -> list[TableRowEstimate]:
    """Get row estimates for all tables in backup.

    Uses fastest available method:
    1. If 0.19+ INI exists with rows: parse it
    2. Otherwise: use gzip ISIZE estimation

    Args:
        backup_dir: Path to extracted backup directory.
        file_sizes: Optional pre-computed file sizes from extraction (filename -> bytes).

    Returns:
        List of TableRowEstimate for each table.
    """
    metadata_path = Path(backup_dir) / "metadata"

    # Try INI format first
    if metadata_path.exists():
        tables = _parse_ini_metadata(metadata_path, file_sizes=file_sizes)
        if tables:
            return tables

    # Fall back to ISIZE scanning
    return _scan_for_row_estimates(Path(backup_dir), file_sizes=file_sizes)


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
        content = metadata_path.read_text()
    except Exception as e:
        logger.warning(f"Failed to read metadata for binlog: {e}")
        return None

    # Try INI format first
    if content.strip().startswith("["):
        return _parse_ini_binlog(content)

    # Try legacy format
    return _parse_legacy_binlog(content)


# =============================================================================
# Internal Helpers - Metadata Detection
# =============================================================================


def _detect_metadata_format(backup_dir: str) -> MetadataFormat:
    """Detect the format of existing metadata file."""
    metadata_path = Path(backup_dir) / "metadata"

    if not metadata_path.exists():
        # Check if we have data files (implies it's a backup dir)
        backup_path = Path(backup_dir)
        if any(backup_path.glob("*.sql.gz")) or any(backup_path.glob("*.sql.zst")):
            return MetadataFormat.MISSING
        return MetadataFormat.UNKNOWN

    try:
        with open(metadata_path) as f:
            # Skip blank lines at the beginning
            for line in f:
                first_line = line.strip()
                if first_line:
                    break
            else:
                # File is empty or all blank
                return MetadataFormat.UNKNOWN

        if first_line.startswith("["):
            return MetadataFormat.INI_0_19
        elif first_line.startswith("Started dump") or "Log:" in first_line:
            return MetadataFormat.LEGACY_0_9
        else:
            return MetadataFormat.UNKNOWN

    except Exception as e:
        logger.warning(f"Failed to detect metadata format: {e}")
        return MetadataFormat.UNKNOWN


# =============================================================================
# Internal Helpers - ISIZE and Row Estimation
# =============================================================================


def _get_gzip_uncompressed_size(filepath: str) -> int:
    """Read ISIZE from gzip trailer - O(1), no decompression.

    Per RFC 1952, the ISIZE field is the last 4 bytes of a gzip file,
    containing the uncompressed size as a little-endian uint32.
    This wraps at 4GB but most SQL files are smaller.

    Args:
        filepath: Path to a .gz file.

    Returns:
        Uncompressed size in bytes, or 0 on error.
    """
    try:
        with open(filepath, "rb") as f:
            f.seek(-4, 2)  # Seek to last 4 bytes from end
            data = f.read(4)
            return int(struct.unpack("<I", data)[0])
    except Exception:
        # Graceful degradation: return 0 if ISIZE can't be read
        logger.debug("Failed to get ISIZE for %s", filepath, exc_info=True)
        return 0


def _estimate_rows_from_size(uncompressed_size: int) -> int:
    """Estimate row count from uncompressed SQL file size."""
    if uncompressed_size <= 0:
        return 0
    return max(1, uncompressed_size // ESTIMATED_BYTES_PER_ROW)


def _estimate_rows_by_sampling(
    filepath: str,
    sample_bytes: int = SAMPLE_BYTES,
    fallback_bytes_per_row: int = ESTIMATED_BYTES_PER_ROW,
) -> int:
    """Estimate row count by sampling first N bytes of SQL file.

    More accurate than pure ISIZE/200 because it measures actual row density
    in the specific file's format (extended inserts, column count, data types).

    Achieves ~±15% accuracy vs ~±50% for hardcoded bytes/row.

    Args:
        filepath: Path to gzip-compressed SQL file
        sample_bytes: How many uncompressed bytes to sample (default 8KB)
        fallback_bytes_per_row: Fallback if sampling fails

    Returns:
        Estimated row count
    """
    total_size = _get_gzip_uncompressed_size(filepath)
    if total_size == 0:
        return 0

    try:
        with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            sample = f.read(sample_bytes)
    except Exception as e:
        logger.warning("Sampling failed for %s: %s, using fallback", filepath, e)
        return max(1, total_size // fallback_bytes_per_row)

    if not sample:
        return max(1, total_size // fallback_bytes_per_row)

    # Count row indicators in sample
    # Mydumper extended INSERT format puts each row on its own line:
    #   INSERT INTO `t` VALUES (1,'alice'),
    #   (2,'bob'),
    #   (3,'charlie');
    #
    # Row separators: "),\n(" between rows within an INSERT statement
    # First row in each INSERT counted via "INSERT INTO"
    #
    # Note: "),(" (no newline) rarely appears in mydumper output but we count
    # both patterns for robustness
    rows_in_sample = (
        sample.count("),\n(")  # Standard mydumper row separator
        + sample.count("),(")  # Fallback: single-line format
        + sample.count("INSERT INTO")  # First row of each INSERT statement
    )

    if rows_in_sample == 0:
        # No rows found in sample (might be schema file or empty), use fallback
        return max(1, total_size // fallback_bytes_per_row)

    # Calculate bytes per row from sample
    sample_len = len(sample.encode("utf-8"))
    bytes_per_row_measured = sample_len / rows_in_sample

    # Extrapolate to full file
    estimated_rows = int(total_size / bytes_per_row_measured)

    logger.debug(
        "Sampled %s: %d rows in %d bytes (%.1f bytes/row) → %d total",
        filepath,
        rows_in_sample,
        sample_len,
        bytes_per_row_measured,
        estimated_rows,
    )

    return max(1, estimated_rows)


def _count_rows_in_file(filepath: str) -> int:
    """Count rows by decompressing and scanning - slow, for small files only."""
    count = 0
    try:
        with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.lstrip()
                if stripped.startswith("INSERT INTO") or stripped.startswith(",("):
                    count += 1
    except Exception as e:
        logger.warning(f"Failed to count rows in {filepath}: {e}")
    return count


def _detect_rows_per_chunk(
    table_files_by_table: dict[tuple[str, str], list[Path]]
) -> int:
    """Detect the actual --rows setting by counting rows in the smallest full chunk.

    Scans backup for chunked tables, finds the smallest "full" chunk file,
    and counts actual rows to determine the rows-per-chunk setting.

    This is more accurate than assuming mydumper's default 1M because:
    - Different customers may use different --rows settings
    - Backups may be created with non-default configurations

    Strategy:
    1. Find all tables with 2+ chunk files (indicates chunking was used)
    2. From those, find tables where we can identify "full" chunks
       (files with similar sizes, excluding the smaller last chunk)
    3. Pick the SMALLEST full chunk file (for counting speed)
    4. Count actual rows in that file - that's the --rows setting

    Args:
        table_files_by_table: Dict mapping (db, table) to list of data files

    Returns:
        Detected rows-per-chunk, or MYDUMPER_DEFAULT_ROWS_PER_CHUNK if detection fails
    """
    # Collect candidate full chunks: (file_path, compressed_size)
    candidate_chunks: list[tuple[Path, int]] = []

    for (db, table), files in table_files_by_table.items():
        if len(files) < 2:
            # Single file - not chunked, can't use for detection
            continue

        # Get sizes, filter out zero-size files
        file_sizes: list[tuple[Path, int]] = []
        for f in files:
            try:
                size = f.stat().st_size
                if size > 0:
                    file_sizes.append((f, size))
            except OSError:
                continue

        if len(file_sizes) < 2:
            continue

        # Find max size (likely a full chunk)
        max_size = max(s for _, s in file_sizes)

        # Identify "full" chunks (within 80% of max size)
        # The last chunk is often partial and smaller
        for filepath, size in file_sizes:
            if size >= max_size * FULL_CHUNK_SIZE_RATIO:
                candidate_chunks.append((filepath, size))

    if not candidate_chunks:
        logger.info(
            "No chunked tables found for rows-per-chunk detection, "
            "using default %d",
            MYDUMPER_DEFAULT_ROWS_PER_CHUNK,
        )
        return MYDUMPER_DEFAULT_ROWS_PER_CHUNK

    # Sort by compressed size (smallest first) for fastest counting
    candidate_chunks.sort(key=lambda x: x[1])

    # Count rows in the smallest full chunk
    smallest_chunk, smallest_size = candidate_chunks[0]
    logger.info(
        "Detecting rows-per-chunk from %s (%.2f MB compressed)",
        smallest_chunk.name,
        smallest_size / (1024 * 1024),
    )

    detected_rows = _count_rows_in_file(str(smallest_chunk))

    if detected_rows > 0:
        logger.info(
            "Detected rows-per-chunk=%d from %s",
            detected_rows,
            smallest_chunk.name,
        )
        return detected_rows

    # Fallback if counting failed
    logger.warning(
        "Failed to count rows in %s, using default %d",
        smallest_chunk.name,
        MYDUMPER_DEFAULT_ROWS_PER_CHUNK,
    )
    return MYDUMPER_DEFAULT_ROWS_PER_CHUNK


def _estimate_table_rows(
    table_files: list[Path],
    rows_per_chunk: int = MYDUMPER_DEFAULT_ROWS_PER_CHUNK,
) -> int:
    """Estimate rows for a table using chunk math or size heuristics.

    Strategy:
    1. For chunked tables (multiple files): Use detected rows-per-chunk
       - Identify full vs partial chunks by size comparison
       - Full chunks = rows_per_chunk
       - Partial chunks = size_ratio * rows_per_chunk
    2. For single small files: Count directly (fast enough)
    3. For single medium/large files: Use sampling for ~±15% accuracy

    Args:
        table_files: List of data files for this table
        rows_per_chunk: Detected rows-per-chunk from backup (not hardcoded 1M)
    """
    if not table_files:
        return 0

    # Sort by filename to identify chunks in order
    table_files = sorted(table_files, key=lambda p: p.name)

    # Get sizes, filter out zero-size files
    file_sizes: list[tuple[Path, int]] = []
    for f in table_files:
        try:
            size = f.stat().st_size
            if size > 0:
                file_sizes.append((f, size))
        except OSError:
            continue

    if not file_sizes:
        return 0

    if len(file_sizes) == 1:
        # Single file - choose strategy based on size
        file_path, file_size = file_sizes[0]

        if file_size < SMALL_FILE_THRESHOLD_BYTES:
            # Small file - fast to count directly
            return _count_rows_in_file(str(file_path))
        elif file_size > LARGE_FILE_THRESHOLD_BYTES:
            # Large unchunked file - use sampling for better accuracy
            logger.info(
                "Large unchunked table %s (%.1f GB) - using sampling estimate",
                file_path.name,
                file_size / 1e9,
            )
            return _estimate_rows_by_sampling(str(file_path))
        else:
            # Medium file - use sampling for ~±15% accuracy
            return _estimate_rows_by_sampling(str(file_path))

    # Multiple chunks - use size-based estimation with detected rows_per_chunk
    # Find max size to identify full vs partial chunks
    max_size = max(s for _, s in file_sizes)

    total_rows = 0
    for filepath, size in file_sizes:
        if size >= max_size * FULL_CHUNK_SIZE_RATIO:
            # Full chunk - use detected rows_per_chunk
            total_rows += rows_per_chunk
        else:
            # Partial chunk - estimate using size ratio
            ratio = size / max_size
            total_rows += int(ratio * rows_per_chunk)

    return total_rows


# =============================================================================
# Internal Helpers - Filename Parsing
# =============================================================================


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
    if len(parts) < MIN_DB_TABLE_PARTS:
        return None

    # If the last part is a number, it's a chunk
    if parts[-1].isdigit():
        parts.pop()

    if len(parts) < MIN_DB_TABLE_PARTS:
        return None

    # First part is DB, rest is table
    db_name = parts[0]
    table_name = ".".join(parts[1:])

    return db_name, table_name


# =============================================================================
# Internal Helpers - Metadata Writing
# =============================================================================


def _synthesize_metadata(
    backup_dir: str,
    output_file: str,
    binlog: BinlogPosition | None,
    event_callback: EventCallback | None = None,
) -> None:
    """Synthesize myloader 0.19 compatible metadata file.

    For legacy backups, we create valid metadata with rows=0 for all tables.
    This allows myloader to work while avoiding expensive row estimation.
    Progress tracking uses file-based completion instead of row counts.
    """
    backup_path = Path(backup_dir)

    # Check if directory exists - gracefully handle nonexistent paths
    if not backup_path.is_dir():
        logger.error(f"Directory {backup_dir} not found.")
        return

    # Group files by table (cheap: just list directory)
    table_files: dict[tuple[str, str], list[Path]] = defaultdict(list)

    for filepath in backup_path.glob("*.sql.gz"):
        result = _parse_mydumper_filename(filepath.name)
        if result:
            db, table = result
            table_files[(db, table)].append(filepath)

    # For legacy backups, we skip expensive row estimation
    # Set rows=0 for all tables - progress tracking uses file counts instead
    logger.info(
        "Creating metadata for %d tables (legacy backup, no row estimation)",
        len(table_files),
    )

    # Generate INI content
    config = configparser.ConfigParser()
    config.optionxform = str  # type: ignore # Preserve case

    config["config"] = {"quote-character": "BACKTICK", "local-infile": "1"}

    config["myloader_session_variables"] = {
        "SQL_MODE": "'NO_AUTO_VALUE_ON_ZERO,' /*!40101",
        "foreign_key_checks": "0",
        "time_zone": "'+00:00'",
        "sql_log_bin": "0",
    }

    config["source"] = {
        "File": binlog.file if binlog else "",
        "Position": str(binlog.position) if binlog else "",
        "Executed_Gtid_Set": binlog.gtid_set if binlog else "",
    }

    # rows=0 for all tables - progress uses file-based tracking
    for (db, table), files in sorted(table_files.items()):
        section_name = f"`{db}`.`{table}`"
        config[section_name] = {"real_table_name": table, "rows": "0"}

    with open(output_file, "w") as f:
        config.write(f)

    logger.info(f"Synthesized metadata written to {output_file}")


# =============================================================================
# Internal Helpers - Metadata Parsing
# =============================================================================


def _parse_ini_metadata(
    metadata_path: Path,
    file_sizes: dict[str, int] | None = None,
) -> list[TableRowEstimate]:
    """Parse 0.19+ INI format metadata for row counts.
    
    Also counts data files per table and their sizes. If file_sizes is provided
    from extraction stats, uses those instead of re-scanning the directory.
    
    Args:
        metadata_path: Path to the INI metadata file.
        file_sizes: Optional pre-computed file sizes from extraction (filename -> bytes).
    """
    tables: list[TableRowEstimate] = []
    
    # Count files and total bytes per table
    backup_dir = metadata_path.parent
    file_counts: dict[tuple[str, str], int] = defaultdict(int)
    file_bytes: dict[tuple[str, str], int] = defaultdict(int)
    
    if file_sizes:
        # Use pre-computed file sizes from extraction
        for filename, size in file_sizes.items():
            # Only process SQL data files
            if not (filename.endswith(".sql.gz") or filename.endswith(".sql.zst")):
                continue
            # Parse the filename to get database and table
            parsed_name = filename.replace(".sql.zst", ".sql.gz")  # Normalize
            result = _parse_mydumper_filename(parsed_name)
            if result:
                file_counts[result] += 1
                file_bytes[result] += size
    else:
        # Fall back to scanning the directory
        for filepath in backup_dir.glob("*.sql.gz"):
            result = _parse_mydumper_filename(filepath.name)
            if result:
                file_counts[result] += 1
                file_bytes[result] += filepath.stat().st_size
        # Also check for .sql.zst files
        for filepath in backup_dir.glob("*.sql.zst"):
            result = _parse_mydumper_filename(filepath.name.replace(".zst", ".gz"))
            if result:
                file_counts[result] += 1
                file_bytes[result] += filepath.stat().st_size

    try:
        parser = configparser.ConfigParser()
        parser.read(str(metadata_path), encoding="utf-8")

        for section in parser.sections():
            # Skip non-table sections
            if section in (
                "config",
                "myloader",
                "mydumper",
                "binlog",
                "source",
                "myloader_session_variables",
            ):
                continue

            # Section format: `database`.`table` or database.table
            # Remove backticks if present
            clean_section = section.replace("`", "")

            if "." not in clean_section:
                continue

            parts = clean_section.split(".", 1)
            if len(parts) != MIN_DB_TABLE_PARTS:
                continue

            database, table = parts

            # Get row count (0 is valid for empty tables)
            rows = 0
            if parser.has_option(section, "rows"):
                with contextlib.suppress(ValueError, configparser.Error):
                    rows = parser.getint(section, "rows")

            # Get file count (default to 1 if not found - schema file)
            fc = file_counts.get((database, table), 1)
            
            # Get total bytes for this table's data files
            tb = file_bytes.get((database, table), 0)

            # Include ALL tables, even empty ones (rows=0)
            # Empty tables still need to be tracked for progress reporting
            # and are restored/renamed by myloader/atomic_rename
            tables.append(
                TableRowEstimate(
                    database=database, table=table, rows=rows, file_count=fc, total_bytes=tb
                )
            )

    except Exception as e:
        logger.warning(f"Failed to parse INI metadata: {e}")

    return tables


def _scan_for_row_estimates(
    backup_dir: Path,
    file_sizes: dict[str, int] | None = None,
) -> list[TableRowEstimate]:
    """Scan backup files and count files per table.

    For legacy backups (pre-0.19), we no longer estimate row counts because:
    1. ISIZE estimation is unreliable (4GB wraparound, compression variance)
    2. Full file scanning is too slow and resource-intensive
    3. With log-based progress tracking, we only need file counts

    Row counts are set to 0 for legacy backups. Progress tracking uses
    file-based completion instead of row-based estimates.

    Args:
        backup_dir: Path to backup directory.
        file_sizes: Optional pre-computed file sizes from extraction (filename -> bytes).

    Returns:
        List of TableRowEstimate with rows=0 but accurate file_count and total_bytes.
    """
    # table_key -> list of (filename, size)
    table_files: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)

    if file_sizes:
        # Use pre-computed file sizes from extraction
        for filename, size in file_sizes.items():
            # Only process SQL data files (both .gz and .zst formats)
            if not (filename.endswith(".sql.gz") or filename.endswith(".sql.zst")):
                continue
            # Normalize .zst to .gz for filename parsing
            parsed_name = filename.replace(".sql.zst", ".sql.gz")
            result = _parse_mydumper_filename(parsed_name)
            if result:
                db, table = result
                table_files[(db, table)].append((filename, size))
    else:
        # Fall back to scanning the directory
        for filepath in backup_dir.glob("*.sql.gz"):
            result = _parse_mydumper_filename(filepath.name)
            if result:
                db, table = result
                table_files[(db, table)].append((filepath.name, filepath.stat().st_size))

    # Log that we're not doing row estimation for legacy backups
    if table_files:
        logger.info(
            f"Legacy backup detected ({len(table_files)} tables). "
            "Using file-based progress tracking (no row estimation)."
        )

    tables: list[TableRowEstimate] = []
    for (db, table), files in table_files.items():
        # rows=0 means "unknown" - progress tracker will use file-based tracking
        # Calculate total bytes from all files for this table
        # files is list of (filename, size) tuples
        total_bytes = sum(size for _, size in files)
        tables.append(
            TableRowEstimate(
                database=db, table=table, rows=0, file_count=len(files), total_bytes=total_bytes
            )
        )

    return tables


def _parse_ini_binlog(content: str) -> BinlogPosition | None:
    """Parse binlog position from INI format content."""
    try:
        parser = configparser.ConfigParser()
        parser.read_string(content)

        if not parser.has_section("source"):
            return None

        file = parser.get("source", "File", fallback="")
        pos_str = parser.get("source", "Position", fallback="0")
        gtid = parser.get("source", "Executed_Gtid_Set", fallback="")

        if not file:
            return None

        try:
            position = int(pos_str)
        except ValueError:
            position = 0

        return BinlogPosition(file=file, position=position, gtid_set=gtid)

    except Exception as e:
        logger.warning(f"Failed to parse INI binlog: {e}")
        return None


def _parse_legacy_binlog(content: str) -> BinlogPosition | None:
    """Parse binlog position from legacy text format."""
    m_log = re.search(r"Log:\s*(\S+)", content)
    m_pos = re.search(r"Pos:\s*(\d+)", content)

    if not m_log:
        return None

    file = m_log.group(1)
    position = int(m_pos.group(1)) if m_pos else 0

    return BinlogPosition(file=file, position=position, gtid_set="")


# =============================================================================
# Backwards Compatibility Aliases
# =============================================================================

# These maintain compatibility with code using the old module names.
# Import from backup_metadata instead of metadata_synthesis/dump_metadata.


def count_rows_in_file(filepath: str) -> int:
    """Alias for _count_rows_in_file - backwards compatibility."""
    return _count_rows_in_file(filepath)


def parse_filename(filename: str) -> tuple[str, str] | None:
    """Alias for _parse_mydumper_filename - backwards compatibility."""
    return _parse_mydumper_filename(filename)


def synthesize_metadata(backup_dir: str, output_file: str | None = None) -> None:
    """Alias for backwards compatibility with metadata_synthesis module."""
    output = output_file or str(Path(backup_dir) / "metadata")
    binlog = parse_binlog_position(backup_dir)
    _synthesize_metadata(backup_dir, output, binlog)


def ensure_compatible_metadata(backup_dir: str) -> None:
    """Alias for backwards compatibility with metadata_synthesis module."""
    ensure_myloader_compatibility(backup_dir)


def get_gzip_uncompressed_size(filepath: str) -> int:
    """Alias for _get_gzip_uncompressed_size - backwards compatibility."""
    return _get_gzip_uncompressed_size(filepath)


def estimate_table_rows(table_files: list[Path]) -> int:
    """Alias for _estimate_table_rows - backwards compatibility."""
    return _estimate_table_rows(table_files)
