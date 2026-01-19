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
from typing import Any

from pulldb.infra.logging import get_logger

logger = get_logger("pulldb.worker.backup_metadata")


# =============================================================================
# Constants
# =============================================================================

# mydumper default: 1 million rows per chunk file
MYDUMPER_DEFAULT_ROWS_PER_CHUNK = 1_000_000

# Size thresholds for choosing estimation strategy
SMALL_FILE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB - fast to count directly
LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB - use ISIZE estimate

# Estimated bytes per row in mydumper extended INSERT format
ESTIMATED_BYTES_PER_ROW = 200

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
) -> BackupMetadata:
    """Get complete backup metadata including row estimates.

    Ensures myloader compatibility first, then parses metadata.

    Args:
        backup_dir: Path to extracted backup directory.
        event_callback: Optional callback for progress events.

    Returns:
        BackupMetadata with tables, row estimates, and binlog position.
    """
    # Ensure compatibility (creates/upgrades metadata if needed)
    fmt = ensure_myloader_compatibility(backup_dir, event_callback)

    # Parse the metadata
    tables = get_table_row_estimates(backup_dir)
    total_rows = sum(t.rows for t in tables)
    binlog = parse_binlog_position(backup_dir)

    logger.info(
        f"Backup metadata: format={fmt.value}, "
        f"tables={len(tables)}, total_rows={total_rows:,}"
    )

    return BackupMetadata(
        format=fmt,
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
    metadata_path = Path(backup_dir) / "metadata"

    # Try INI format first
    if metadata_path.exists():
        tables = _parse_ini_metadata(metadata_path)
        if tables:
            return tables

    # Fall back to ISIZE scanning
    return _scan_for_row_estimates(Path(backup_dir))


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
        return 0


def _estimate_rows_from_size(uncompressed_size: int) -> int:
    """Estimate row count from uncompressed SQL file size."""
    if uncompressed_size <= 0:
        return 0
    return max(1, uncompressed_size // ESTIMATED_BYTES_PER_ROW)


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


def _estimate_table_rows(table_files: list[Path]) -> int:
    """Estimate rows for a table using chunk math or size heuristics.

    Strategy:
    1. For chunked tables (multiple files): Use mydumper's 1M rows/chunk default
    2. For single small files: Count directly (fast enough)
    3. For single large files: Use gzip ISIZE estimate (O(1))
    """
    if not table_files:
        return 0

    # Sort by filename to identify full vs partial chunks
    table_files = sorted(table_files, key=lambda p: p.name)

    if len(table_files) == 1:
        # Single file - choose strategy based on size
        file_path = table_files[0]
        try:
            file_size = file_path.stat().st_size
        except OSError:
            return 0

        if file_size < SMALL_FILE_THRESHOLD_BYTES:
            return _count_rows_in_file(str(file_path))
        else:
            uncompressed = _get_gzip_uncompressed_size(str(file_path))
            return _estimate_rows_from_size(uncompressed)

    # Multiple chunks - use mydumper math
    full_chunks = len(table_files) - 1
    rows = full_chunks * MYDUMPER_DEFAULT_ROWS_PER_CHUNK

    # Estimate last chunk from size ratio
    try:
        full_sizes = [f.stat().st_size for f in table_files[:-1]]
        last_size = table_files[-1].stat().st_size
    except OSError:
        return rows

    if full_sizes:
        avg_full_size = sum(full_sizes) / len(full_sizes)
        if avg_full_size > 0:
            last_chunk_rows = int(
                (last_size / avg_full_size) * MYDUMPER_DEFAULT_ROWS_PER_CHUNK
            )
            rows += last_chunk_rows

    return rows


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
    """Synthesize complete myloader 0.19 compatible metadata file."""
    backup_path = Path(backup_dir)

    # Group files by table
    table_files: dict[tuple[str, str], list[Path]] = defaultdict(list)

    for filepath in backup_path.glob("*.sql.gz"):
        result = _parse_mydumper_filename(filepath.name)
        if result:
            db, table = result
            table_files[(db, table)].append(filepath)

    # Estimate rows per table
    table_rows: dict[tuple[str, str], int] = {}
    for (db, table), files in table_files.items():
        table_rows[(db, table)] = _estimate_table_rows(files)

    logger.info(f"Estimated row counts for {len(table_rows)} tables")

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

    for (db, table), rows in sorted(table_rows.items()):
        section_name = f"`{db}`.`{table}`"
        config[section_name] = {"real_table_name": table, "rows": str(rows)}

    with open(output_file, "w") as f:
        config.write(f)

    logger.info(f"Synthesized metadata written to {output_file}")


# =============================================================================
# Internal Helpers - Metadata Parsing
# =============================================================================


def _parse_ini_metadata(metadata_path: Path) -> list[TableRowEstimate]:
    """Parse 0.19+ INI format metadata for row counts."""
    tables: list[TableRowEstimate] = []

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

            # Get row count
            rows = 0
            if parser.has_option(section, "rows"):
                with contextlib.suppress(ValueError, configparser.Error):
                    rows = parser.getint(section, "rows")

            if rows > 0:
                tables.append(
                    TableRowEstimate(database=database, table=table, rows=rows)
                )

    except Exception as e:
        logger.warning(f"Failed to parse INI metadata: {e}")

    return tables


def _scan_for_row_estimates(backup_dir: Path) -> list[TableRowEstimate]:
    """Scan backup files and estimate rows using ISIZE."""
    table_files: dict[tuple[str, str], list[Path]] = defaultdict(list)

    for filepath in backup_dir.glob("*.sql.gz"):
        result = _parse_mydumper_filename(filepath.name)
        if result:
            db, table = result
            table_files[(db, table)].append(filepath)

    tables: list[TableRowEstimate] = []
    for (db, table), files in table_files.items():
        rows = _estimate_table_rows(files)
        tables.append(TableRowEstimate(database=db, table=table, rows=rows))

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
