"""Metadata synthesis logic for myloader compatibility.

Note: The primary implementation is now in backup_metadata.py.
This module re-exports from there for backward compatibility.

Ensures that backups from older mydumper versions (0.9.x) which produce
text-based metadata files are compatible with myloader 0.19.x which expects
INI-style metadata files.

This module provides functionality to:
1. Parse mydumper filenames to extract DB/Table info.
2. Estimate rows in compressed SQL files using sampling + gzip ISIZE.
3. Synthesize a myloader 0.19 compatible metadata.ini file, preserving
   binlog coordinates from legacy metadata if available.
"""

from __future__ import annotations

import os

# Re-export everything from backup_metadata for backward compatibility
from pulldb.worker.backup_metadata import (
    DEFAULT_BYTES_PER_ROW,
    DEFAULT_SAMPLE_BYTES,
    ESTIMATION_SAFETY_MARGIN,
    _synthesize_metadata,
    count_rows_in_file,
    ensure_myloader_compatibility as ensure_compatible_metadata,
    estimate_rows_by_sampling,
    estimate_rows_from_size,
    get_gzip_uncompressed_size,
    parse_binlog_position,
    parse_filename,
)


def synthesize_metadata(backup_dir: str, output_file: str | None = None) -> None:
    """Synthesize myloader 0.19 compatible metadata file.

    Backward-compatible wrapper for _synthesize_metadata.

    Args:
        backup_dir: Path to backup directory containing .sql.gz files.
        output_file: Optional output path. Defaults to backup_dir/metadata.
    """
    binlog = parse_binlog_position(backup_dir)
    target = output_file if output_file else os.path.join(backup_dir, "metadata")
    _synthesize_metadata(backup_dir, target, binlog)


__all__ = [
    "DEFAULT_BYTES_PER_ROW",
    "DEFAULT_SAMPLE_BYTES",
    "ESTIMATION_SAFETY_MARGIN",
    "count_rows_in_file",
    "ensure_compatible_metadata",
    "estimate_rows_by_sampling",
    "estimate_rows_from_size",
    "get_gzip_uncompressed_size",
    "parse_filename",
    "synthesize_metadata",
]
