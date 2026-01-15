"""Dump metadata parsing for restore progress tracking.

Note: The primary implementation is now in backup_metadata.py.
This module re-exports from there for backward compatibility.

Parses mydumper backup metadata to extract table row counts for accurate
progress estimation during myloader execution.

Supports:
- mydumper 0.19+ INI format metadata with `rows=` entries
- mydumper 0.9 format via file scanning (using backup_metadata.count_rows_in_file)

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import configparser
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from pulldb.infra.logging import get_logger
from pulldb.worker.backup_metadata import count_rows_in_file, parse_filename

logger = get_logger("pulldb.worker.dump_metadata")

# Minimum parts for database.table parsing
_MIN_DB_TABLE_PARTS = 2


@dataclass(slots=True, frozen=True)
class TableRowCount:
    """Row count for a single table.

    Attributes:
        database: Database name.
        table: Table name.
        rows: Estimated row count.
    """

    database: str
    table: str
    rows: int


@dataclass(slots=True, frozen=True)
class DumpMetadata:
    """Parsed metadata from a mydumper backup directory.

    Attributes:
        tables: List of tables with row counts.
        total_rows: Sum of all table row counts.
        format_version: Detected format ('0.19+' or '0.9').
    """

    tables: list[TableRowCount]
    total_rows: int
    format_version: str


def parse_dump_metadata(backup_dir: str) -> DumpMetadata:
    """Parse dump metadata to extract table row counts.

    Tries INI format first (0.19+), falls back to file scanning (0.9).

    Args:
        backup_dir: Path to extracted mydumper backup directory.

    Returns:
        DumpMetadata with table row counts and total.
    """
    path = Path(backup_dir)
    metadata_path = path / "metadata"

    # Try INI format first (0.19+)
    if metadata_path.exists():
        tables = _parse_ini_metadata(metadata_path)
        if tables:
            total_rows = sum(t.rows for t in tables)
            logger.info(
                f"Parsed INI metadata: {len(tables)} tables, {total_rows:,} total rows"
            )
            return DumpMetadata(
                tables=tables,
                total_rows=total_rows,
                format_version="0.19+",
            )

    # Fall back to file scanning (0.9 or missing metadata)
    tables = _scan_dump_files(path)
    total_rows = sum(t.rows for t in tables)
    logger.info(
        f"Scanned dump files: {len(tables)} tables, {total_rows:,} total rows"
    )
    return DumpMetadata(
        tables=tables,
        total_rows=total_rows,
        format_version="0.9",
    )


def _parse_ini_metadata(metadata_path: Path) -> list[TableRowCount]:
    """Parse INI format metadata file for table row counts.

    INI format example:
        [mydb.users]
        rows = 12345

        [mydb.orders]
        rows = 67890
    """
    tables: list[TableRowCount] = []

    try:
        parser = configparser.ConfigParser()
        parser.read(str(metadata_path), encoding="utf-8")

        for section in parser.sections():
            # Skip non-table sections
            if section in ("myloader", "mydumper", "binlog"):
                continue

            # Section format: database.table
            if "." not in section:
                continue

            parts = section.split(".", 1)
            if len(parts) != _MIN_DB_TABLE_PARTS:
                continue

            database, table = parts

            # Get row count (0 if not present or invalid)
            rows = 0
            if parser.has_option(section, "rows"):
                with suppress(ValueError, configparser.Error):
                    rows = parser.getint(section, "rows")

            if rows > 0:
                tables.append(TableRowCount(database=database, table=table, rows=rows))

    except Exception as e:
        logger.warning(f"Failed to parse INI metadata: {e}")

    return tables


def _scan_dump_files(backup_dir: Path) -> list[TableRowCount]:
    """Scan dump files to count rows for 0.9 format backups.

    Uses metadata_synthesis.count_rows_in_file for .gz files.
    """
    tables: list[TableRowCount] = []
    row_counts: dict[tuple[str, str], int] = {}

    # Scan .sql.gz files (0.9 format)
    for filepath in backup_dir.glob("*.sql.gz"):
        parsed = parse_filename(filepath.name)
        if not parsed:
            continue

        database, table = parsed
        key = (database, table)
        rows = count_rows_in_file(str(filepath))
        row_counts[key] = row_counts.get(key, 0) + rows

    # Scan .sql.zst files (0.19 format fallback)
    for filepath in backup_dir.glob("*.sql.zst"):
        # parse_filename expects .sql.gz, adapt for .zst
        name = filepath.name
        if not name.endswith(".sql.zst"):
            continue

        # Convert to gz format for parsing, then process
        base = name[:-8]  # remove .sql.zst
        parsed = _parse_zst_filename(base)
        if not parsed:
            continue

        database, table = parsed
        key = (database, table)
        # For .zst files, we can't easily count rows without zstd
        # Return 0 rows - the INI metadata should have been parsed instead
        row_counts[key] = row_counts.get(key, 0)

    # Convert to TableRowCount list
    for (database, table), rows in row_counts.items():
        tables.append(TableRowCount(database=database, table=table, rows=rows))

    return tables


def _parse_zst_filename(base: str) -> tuple[str, str] | None:
    """Parse base filename (without .sql.zst) to extract database.table.

    Format: database.table or database.table.00001 (chunk)
    """
    parts = base.split(".")

    if len(parts) < _MIN_DB_TABLE_PARTS:
        return None

    # Check for chunk number at end
    if parts[-1].isdigit():
        parts.pop()

    if len(parts) < _MIN_DB_TABLE_PARTS:
        return None

    database = parts[0]
    table = ".".join(parts[1:])

    return database, table
