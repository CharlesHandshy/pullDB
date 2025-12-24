#!/usr/bin/env python3
"""
Normalize CSS variable names to follow --color-* convention.

This migration script finds and replaces ~136 variable references across
CSS files, Python files, and documentation.

Renames:
- --surface-* → --color-surface-*
- --scrollbar-* → --color-scrollbar-*
- --text-{primary,secondary,muted} → --color-text-*
- --border-{primary,secondary} → --color-border-*
- --bg-* → --color-bg-*

Usage:
    python scripts/normalize_css_variables.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


class Replacement(NamedTuple):
    """A single variable replacement."""

    pattern: str
    replacement: str


# Define all replacements - order matters for some overlapping patterns
REPLACEMENTS: list[Replacement] = [
    # Surface variables (must come before generic patterns)
    Replacement(r"--surface-primary", "--color-surface-primary"),
    Replacement(r"--surface-secondary", "--color-surface-secondary"),
    Replacement(r"--surface-hover", "--color-surface-hover"),
    # Scrollbar variables
    Replacement(r"--scrollbar-track", "--color-scrollbar-track"),
    Replacement(r"--scrollbar-thumb-hover", "--color-scrollbar-thumb-hover"),
    Replacement(r"--scrollbar-thumb", "--color-scrollbar-thumb"),
    # Text color variables (not typography like --text-sm)
    # Only match when followed by ) or ; or : or space (not -sm, -lg, etc.)
    Replacement(r"--text-primary(?=[);:\s,])", "--color-text-primary"),
    Replacement(r"--text-secondary(?=[);:\s,])", "--color-text-secondary"),
    Replacement(r"--text-muted(?=[);:\s,])", "--color-text-muted"),
    Replacement(r"--text-base(?=[);:\s,])", "--color-text-base"),
    # Border color variables
    Replacement(r"--border-primary(?=[);:\s,])", "--color-border-primary"),
    Replacement(r"--border-secondary(?=[);:\s,])", "--color-border-secondary"),
    # Background variables (Python-generated)
    Replacement(r"--bg-base(?=[);:\s,])", "--color-bg-base"),
    Replacement(r"--bg-surface(?=[);:\s,])", "--color-bg-surface"),
]

# Files to process
TARGET_FILES: list[Path] = [
    # CSS design tokens (main definition file)
    PROJECT_ROOT / "pulldb/web/shared/css/design-tokens.css",
    PROJECT_ROOT / "pulldb/web/static/css/shared/design-tokens.css",
    # Feature CSS files
    PROJECT_ROOT / "pulldb/web/static/css/features/dashboard.css",
    PROJECT_ROOT / "pulldb/web/features/css/dashboard.css",
    # Widget CSS files
    PROJECT_ROOT / "pulldb/web/static/widgets/lazy_table/lazy_table.css",
    # Routes with theme.css generation
    PROJECT_ROOT / "pulldb/web/features/admin/routes.py",
    # Documentation
    PROJECT_ROOT / "docs/STYLE-GUIDE.md",
    PROJECT_ROOT / "pulldb/web/widgets/virtual_table/README.md",
    # Archived CSS
    PROJECT_ROOT / "pulldb/web/_archived/css/legacy/dark-mode.css",
]


def process_file(file_path: Path, dry_run: bool = False) -> dict[str, int]:
    """
    Process a single file, applying all replacements.

    Returns dict of {pattern: count} for replacements made.
    """
    if not file_path.exists():
        print(f"  SKIP (not found): {file_path}")
        return {}

    content = file_path.read_text(encoding="utf-8")
    original_content = content
    counts: dict[str, int] = {}

    for repl in REPLACEMENTS:
        # Count matches before replacement
        matches = len(re.findall(repl.pattern, content))
        if matches > 0:
            counts[repl.pattern] = matches
            content = re.sub(repl.pattern, repl.replacement, content)

    if content != original_content:
        if dry_run:
            print(f"  DRY RUN: Would modify {file_path}")
        else:
            file_path.write_text(content, encoding="utf-8")
            print(f"  MODIFIED: {file_path}")
        for pattern, count in counts.items():
            print(f"    {pattern} → {count} replacements")
    else:
        print(f"  NO CHANGES: {file_path}")

    return counts


def main() -> int:
    """Run the migration."""
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("CSS Variable Normalization Migration")
    print("=" * 60)
    if dry_run:
        print("MODE: Dry run (no files will be modified)")
    else:
        print("MODE: Live (files will be modified)")
    print()

    total_replacements = 0

    for file_path in TARGET_FILES:
        print(f"\nProcessing: {file_path.relative_to(PROJECT_ROOT)}")
        counts = process_file(file_path, dry_run)
        total_replacements += sum(counts.values())

    print()
    print("=" * 60)
    print(f"Total replacements: {total_replacements}")
    print("=" * 60)

    if dry_run and total_replacements > 0:
        print("\nRun without --dry-run to apply changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
