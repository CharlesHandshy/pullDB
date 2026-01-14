"""Metadata synthesis logic for myloader compatibility.

Ensures that backups from older mydumper versions (0.9.x) which produce
text-based metadata files are compatible with myloader 0.19.x which expects
INI-style metadata files.

This module provides functionality to:
1. Parse mydumper filenames to extract DB/Table info.
2. Estimate rows in compressed SQL files using gzip ISIZE (O(1) per file).
3. Synthesize a myloader 0.19 compatible metadata.ini file, preserving
   binlog coordinates from legacy metadata if available.
"""

import configparser
import os
import re
import struct
from collections import defaultdict
from pathlib import Path

from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.worker.metadata_synthesis")


# Default bytes per row for estimation (empirically derived from mydumper output)
# Mydumper extended INSERTs average ~200 bytes per row including syntax overhead
DEFAULT_BYTES_PER_ROW = 200


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
            return struct.unpack("<I", f.read(4))[0]
    except (OSError, struct.error):
        return 0


def estimate_rows_from_size(uncompressed_size: int, bytes_per_row: int = DEFAULT_BYTES_PER_ROW) -> int:
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


def parse_filename(filename: str) -> tuple[str, str] | None:
    """Parse a mydumper filename to extract database and table names.

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
    min_parts = 2
    if len(parts) < min_parts:
        return None

    # If the last part is a number, it's a chunk
    if parts[-1].isdigit():
        parts.pop()  # Remove chunk number

    if len(parts) < min_parts:
        return None

    # Reassemble table name
    # Standard mydumper: first part is DB, rest is table.
    db_name = parts[0]
    table_name = ".".join(parts[1:])

    return db_name, table_name


def count_rows_in_file(filepath: str) -> int:
    """Estimate rows in a mydumper SQL file using gzip ISIZE.

    Uses O(1) gzip trailer read instead of decompressing the entire file.
    This provides ~50% accuracy for mydumper's extended INSERT format,
    which is sufficient for myloader progress indication.

    The function name is preserved for backward compatibility, but the
    implementation now estimates rather than counts exactly.

    Args:
        filepath: Path to a .sql.gz mydumper data file.

    Returns:
        Estimated row count (minimum 1).
    """
    uncompressed_size = get_gzip_uncompressed_size(filepath)
    if uncompressed_size == 0:
        # Fallback: file couldn't be read, return minimum
        logger.warning(f"Could not read ISIZE from {filepath}, defaulting to 1 row")
        return 1
    return estimate_rows_from_size(uncompressed_size)


def synthesize_metadata(backup_dir: str, output_file: str | None = None) -> None:
    """Scan backup directory and generate myloader 0.19 compatible metadata file."""
    if not os.path.isdir(backup_dir):
        logger.error(f"Directory {backup_dir} not found.")
        return

    table_rows: dict[tuple[str, str], int] = defaultdict(int)

    logger.info(f"Scanning {backup_dir} for metadata synthesis...")

    for filename in os.listdir(backup_dir):
        result = parse_filename(filename)
        if result:
            db, table = result
            filepath = os.path.join(backup_dir, filename)
            rows = count_rows_in_file(filepath)
            table_rows[(db, table)] += rows

    logger.info(f"Found {len(table_rows)} tables for metadata synthesis.")

    # Generate INI content
    config = configparser.ConfigParser()
    config.optionxform = str  # type: ignore # Preserve case

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
    # Try to read legacy metadata for binlog info
    legacy_metadata_path = os.path.join(backup_dir, "metadata")
    binlog_file = ""
    binlog_pos = ""

    if os.path.exists(legacy_metadata_path):
        try:
            with open(legacy_metadata_path) as f_meta:
                content = f_meta.read()
                # Check if it's legacy (simple text)
                if "[config]" not in content:
                    # Parse legacy format
                    # Log: mysql-bin.000001
                    # Pos: 123
                    m_log = re.search(r"Log: (\S+)", content)
                    m_pos = re.search(r"Pos: (\d+)", content)
                    if m_log:
                        binlog_file = m_log.group(1)
                    if m_pos:
                        binlog_pos = m_pos.group(1)
        except Exception as e:
            logger.warning(f"Failed to read legacy metadata: {e}")

    config["source"] = {
        "File": binlog_file,
        "Position": binlog_pos,
        "Executed_Gtid_Set": "",
    }

    # Tables
    for (db, table), rows in sorted(table_rows.items()):
        section_name = f"`{db}`.`{table}`"
        config[section_name] = {"real_table_name": table, "rows": str(rows)}

    # Output
    target_file = output_file if output_file else os.path.join(backup_dir, "metadata")
    try:
        with open(target_file, "w") as f_out:
            config.write(f_out)
        logger.info(f"Synthesized metadata written to {target_file}")
    except Exception as e:
        logger.error(f"Failed to write synthesized metadata: {e}")


def ensure_compatible_metadata(backup_dir: str) -> None:
    """Ensure the backup directory has a myloader 0.19 compatible metadata file.

    If 'metadata' is missing or in legacy format, it synthesizes a new one.
    """
    metadata_path = Path(backup_dir) / "metadata"

    needs_synthesis = False

    if not metadata_path.exists():
        # If no metadata file, check if we have .sql.gz files (implies 0.9 backup)
        # If we have .zst files, it's likely 0.19 and maybe metadata is missing or named differently?
        # But for now, if missing, we try to synthesize if we see data.
        if any(Path(backup_dir).glob("*.sql.gz")):
            logger.info("Metadata file missing in 0.9 backup. Synthesizing...")
            needs_synthesis = True
    else:
        # Check format
        try:
            with open(metadata_path) as f:
                first_line = f.readline()
                # INI files usually start with [section] or comments
                # Legacy starts with "Started dump at:"
                if not first_line.strip().startswith("["):
                    logger.info(
                        "Legacy metadata format detected. Synthesizing upgrade..."
                    )
                    needs_synthesis = True
        except Exception as e:
            logger.warning(f"Failed to read metadata file header: {e}")
            # Assume we need to fix it if we can't read it? Or fail hard?
            # Safer to try synthesis if we can't validate it.
            needs_synthesis = True

    if needs_synthesis:
        synthesize_metadata(backup_dir, str(metadata_path))
