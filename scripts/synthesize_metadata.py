#!/usr/bin/env python3
"""Synthesize a myloader 0.19+ compatible metadata file for a legacy 0.9.x backup.

Usage:
    python scripts/synthesize_metadata.py /path/to/backup/dir

The script scans the directory for *.sql.gz files, detects the database/table
names from their filenames, and writes a 'metadata' file in the INI format that
myloader 0.21.x expects.

If the directory already contains a valid 0.19+ metadata file the script exits
without overwriting it.  Pass --force to overwrite.
"""

from __future__ import annotations

import argparse
import configparser
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Filename parser
# ---------------------------------------------------------------------------

# mydumper 0.9.x filenames:
#   <db>.<table>.<chunk>.sql.gz          e.g. mydb.users.00001.sql.gz
#   <db>.<table>-schema.sql.gz           schema file
#   <db>-schema-create.sql.gz            db create file
_DATA_FILE_RE = re.compile(
    r"^(?P<db>[^.]+)\.(?P<table>[^.]+)\.\d+\.sql(?:\.gz|\.zst)$"
)


def _parse_filename(name: str) -> tuple[str, str] | None:
    """Return (database, table) for a mydumper data file, or None."""
    m = _DATA_FILE_RE.match(name)
    if m:
        return m.group("db"), m.group("table")
    return None


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _is_ini_metadata(path: Path) -> bool:
    """Return True if path contains a valid 0.19+ INI metadata file."""
    try:
        content = path.read_text(errors="ignore")
        parser = configparser.ConfigParser()
        parser.read_string(content)
        return "config" in parser or "myloader_session_variables" in parser
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Binlog position (optional)
# ---------------------------------------------------------------------------

_LEGACY_BINLOG_RE = re.compile(
    r"Log:\s*(?P<file>\S+)\s*Pos:\s*(?P<pos>\d+)"
)


def _parse_legacy_binlog(path: Path) -> tuple[str, str, str] | None:
    """Parse binlog position from a legacy text metadata file.

    Returns (file, position, gtid_set) or None.
    """
    try:
        content = path.read_text(errors="ignore")
        m = _LEGACY_BINLOG_RE.search(content)
        if m:
            return m.group("file"), m.group("pos"), ""
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Core synthesis
# ---------------------------------------------------------------------------

def synthesize(backup_dir: Path, force: bool = False) -> None:
    if not backup_dir.is_dir():
        print(f"ERROR: {backup_dir} is not a directory.", file=sys.stderr)
        sys.exit(1)

    metadata_path = backup_dir / "metadata"

    if metadata_path.exists() and not force:
        if _is_ini_metadata(metadata_path):
            print(
                f"✅  Backup already has a valid 0.19+ metadata file — nothing to do.\n"
                f"    (Pass --force to overwrite.)"
            )
            return
        print("ℹ️   Found legacy text metadata — will upgrade to INI format.")
        binlog = _parse_legacy_binlog(metadata_path)
    else:
        print("ℹ️   No metadata file found — will create one from scratch.")
        binlog = None

    # Discover tables
    table_files: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for f in backup_dir.glob("*.sql.gz"):
        result = _parse_filename(f.name)
        if result:
            table_files[result].append(f)
    # Also support .sql.zst (newer mydumper)
    for f in backup_dir.glob("*.sql.zst"):
        result = _parse_filename(f.name)
        if result:
            table_files[result].append(f)

    if not table_files:
        print(
            "WARNING: No *.sql.gz / *.sql.zst data files found in the directory.\n"
            "         The metadata file will still be written but may be empty.",
            file=sys.stderr,
        )

    print(f"    Found {len(table_files)} table(s) across "
          f"{sum(len(v) for v in table_files.values())} data file(s).")

    # Build INI
    config = configparser.ConfigParser()
    config.optionxform = str  # Preserve case

    config["config"] = {
        "quote-character": "BACKTICK",
        "local-infile": "1",
    }

    config["myloader_session_variables"] = {
        "SQL_MODE": "'NO_AUTO_VALUE_ON_ZERO,' /*!40101",
        "foreign_key_checks": "0",
        "time_zone": "'+00:00'",
        "sql_log_bin": "0",
    }

    binlog_file, binlog_pos, binlog_gtid = binlog if binlog else ("", "", "")
    config["source"] = {
        "File": binlog_file,
        "Position": binlog_pos,
        "Executed_Gtid_Set": binlog_gtid,
    }

    # rows=0 for all tables — myloader only needs the section to exist;
    # accurate row counts are optional and expensive to compute.
    for (db, table) in sorted(table_files):
        section = f"`{db}`.`{table}`"
        config[section] = {"real_table_name": table, "rows": "0"}

    with metadata_path.open("w") as f:
        config.write(f)

    print(f"✅  Metadata written to {metadata_path}")
    if binlog_file:
        print(f"    Binlog: {binlog_file} @ {binlog_pos}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize a myloader 0.19+ metadata file for a legacy 0.9.x backup."
    )
    parser.add_argument(
        "backup_dir",
        help="Path to the extracted backup directory (contains *.sql.gz files).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing metadata file even if it is already valid.",
    )
    args = parser.parse_args()

    synthesize(Path(args.backup_dir), force=args.force)


if __name__ == "__main__":
    main()
