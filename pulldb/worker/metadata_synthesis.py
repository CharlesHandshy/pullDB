"""Metadata synthesis logic for myloader compatibility.

Ensures that backups from older mydumper versions (0.9.x) which produce
text-based metadata files are compatible with myloader 0.19.x which expects
INI-style metadata files.

This module provides functionality to:
1. Parse mydumper filenames to extract DB/Table info.
2. Estimate rows using smart heuristics (chunk math + ISIZE).
3. Synthesize a myloader 0.19 compatible metadata.ini file, preserving
   binlog coordinates from legacy metadata if available.

Performance: Uses O(1) estimation instead of decompressing all files.
For an 86 GiB backup, this reduces synthesis time from ~20 minutes to ~2 seconds.
"""

import configparser
import gzip
import os
import re
import struct
from collections import defaultdict
from pathlib import Path

from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.worker.metadata_synthesis")

# mydumper default: 1 million rows per chunk file
# This is the --rows parameter default in mydumper 0.9.x
MYDUMPER_DEFAULT_ROWS_PER_CHUNK = 1_000_000

# Size thresholds for choosing estimation strategy
SMALL_FILE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB - fast to count directly
LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB - use ISIZE estimate

# Estimated bytes per row in mydumper extended INSERT format
# Based on typical row: INSERT prefix (amortized) + values tuple + delimiters
ESTIMATED_BYTES_PER_ROW = 200


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


def get_gzip_uncompressed_size(filepath: str) -> int:
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


def count_rows_in_file(filepath: str) -> int:
    """Count rows in a mydumper SQL file by decompressing and scanning.

    WARNING: This is slow for large files! Use estimate_table_rows() instead
    for the main synthesis workflow. This function is kept for small files
    where accuracy is preferred over speed.

    Assumes mydumper format:
    INSERT INTO ... VALUES (...)
    ,(...)
    ,(...)

    Counts lines starting with 'INSERT INTO' or ',('.
    """
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


def estimate_table_rows(table_files: list[Path]) -> int:
    """Estimate rows for a table using chunk math or size heuristics.

    Strategy:
    1. For chunked tables (multiple files): Use mydumper's 1M rows/chunk default
       - Full chunks: (num_chunks - 1) * 1,000,000
       - Last chunk: Estimated from size ratio
    2. For single small files: Count directly (fast enough)
    3. For single large files: Use gzip ISIZE estimate (O(1))

    Args:
        table_files: List of data files for this table (*.00000.sql.gz, etc.)
                    Should NOT include schema files.

    Returns:
        Estimated row count for the entire table.
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
            # Small file - fast to count directly (~1 second for 50MB)
            return count_rows_in_file(str(file_path))

        elif file_size > LARGE_FILE_THRESHOLD_BYTES:
            # Large unchunked file (pathological case like 26GB contracts table)
            logger.info(
                f"Large unchunked table {file_path.name} "
                f"({file_size / 1e9:.1f} GB) - using ISIZE estimate"
            )
            uncompressed = get_gzip_uncompressed_size(str(file_path))
            return max(1, uncompressed // ESTIMATED_BYTES_PER_ROW)

        else:
            # Medium file - use ISIZE estimate to avoid delay
            uncompressed = get_gzip_uncompressed_size(str(file_path))
            return max(1, uncompressed // ESTIMATED_BYTES_PER_ROW)

    # Multiple chunks - use mydumper math
    # mydumper default: --rows=1000000 means each full chunk has 1M rows
    full_chunks = len(table_files) - 1
    rows = full_chunks * MYDUMPER_DEFAULT_ROWS_PER_CHUNK

    # Estimate last chunk from size ratio
    try:
        full_sizes = [f.stat().st_size for f in table_files[:-1]]
        last_size = table_files[-1].stat().st_size
    except OSError:
        # Can't stat files - return estimate based on full chunks only
        return rows

    if full_sizes:
        avg_full_size = sum(full_sizes) / len(full_sizes)
        if avg_full_size > 0:
            last_chunk_rows = int(
                (last_size / avg_full_size) * MYDUMPER_DEFAULT_ROWS_PER_CHUNK
            )
            rows += last_chunk_rows

    return rows


def synthesize_metadata(backup_dir: str, output_file: str | None = None) -> None:
    """Scan backup directory and generate myloader 0.19 compatible metadata file.

    Uses smart row estimation to avoid decompressing all files:
    - Chunked tables: (num_chunks - 1) * 1M + size-proportional estimate for last chunk
    - Small single files: count directly (fast enough)
    - Large single files: ISIZE-based estimate (O(1))

    Performance: For an 86 GiB backup with 2,356 files, this takes ~2 seconds
    instead of ~20 minutes with the old approach.
    """
    if not os.path.isdir(backup_dir):
        logger.error(f"Directory {backup_dir} not found.")
        return

    backup_path = Path(backup_dir)

    # Group files by table (db, table) -> list of data files
    table_files: dict[tuple[str, str], list[Path]] = defaultdict(list)

    logger.info(f"Scanning {backup_dir} for metadata synthesis...")

    for filepath in backup_path.glob("*.sql.gz"):
        result = parse_filename(filepath.name)
        if result:
            db, table = result
            table_files[(db, table)].append(filepath)

    # Estimate rows per table using smart heuristics
    table_rows: dict[tuple[str, str], int] = {}
    for (db, table), files in table_files.items():
        table_rows[(db, table)] = estimate_table_rows(files)

    logger.info(f"Estimated row counts for {len(table_rows)} tables.")

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
