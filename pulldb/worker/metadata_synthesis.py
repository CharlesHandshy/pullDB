"""Metadata synthesis logic for myloader compatibility.

Ensures that backups from older mydumper versions (0.9.x) which produce
text-based metadata files are compatible with myloader 0.19.x which expects
INI-style metadata files.

This module provides functionality to:
1. Parse mydumper filenames to extract DB/Table info.
2. Count rows in compressed SQL files (robustly).
3. Synthesize a myloader 0.19 compatible metadata.ini file, preserving
   binlog coordinates from legacy metadata if available.
"""

import configparser
import gzip
import os
import re
from collections import defaultdict
from pathlib import Path

from pulldb.infra.logging import get_logger

logger = get_logger("pulldb.worker.metadata_synthesis")


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
    """Count rows in a mydumper SQL file.

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
            with open(metadata_path, "r") as f:
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
