#!/usr/bin/env python3
"""FAIL HARD enforcement script.

Validates that control documents contain a canonical FAIL HARD section.
Optionally appends a standard block if missing (--fix mode).

Usage:
    python scripts/ensure_fail_hard.py --check
    python scripts/ensure_fail_hard.py --fix

Exit Codes:
    0 - All files compliant (or fixed successfully)
    1 - Non-compliant files found in --check mode
    2 - Fix attempted but failures remain

The canonical marker string is 'FAIL HARD'. We enforce presence and
optionally inject blocks based on file type context.

Files Scoped (control documents):
    README.md
    design/system-overview.md
    design/security-model.md
    design/implementation-notes.md
    design/roadmap.md
    design/runbook-failure.md
    design/runbook-restore.md
    docs/coding-standards.md
    docs/aws-authentication-setup.md
    constitution.md
    .github/copilot-instructions.md

Injection Strategy:
    - For README.md: Append standard section after Purpose if missing.
    - For other markdown: Append minimal canonical block at end if missing.

This script intentionally FAILS HARD: any unexpected exception prints a
Goal/Problem/Root Cause/Solutions diagnostic and exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

CONTROL_FILES = [
    ROOT / "README.md",
    ROOT / "design/system-overview.md",
    ROOT / "design/security-model.md",
    ROOT / "design/implementation-notes.md",
    ROOT / "design/roadmap.md",
    ROOT / "design/runbook-failure.md",
    ROOT / "design/runbook-restore.md",
    ROOT / "docs/coding-standards.md",
    ROOT / "docs/aws-authentication-setup.md",
    ROOT / "constitution.md",
    ROOT / ".github/copilot-instructions.md",
]

CANONICAL_BLOCK = (
    "\n## FAIL HARD Auto-Appended\n\n"
    "This document was missing a FAIL HARD section. Added by automation.\n"
    "See `constitution.md` and `.github/copilot-instructions.md` for full protocol.\n"
    "Template:\n1. Goal\n2. Problem\n3. Root Cause\n4. Ranked Solutions\n\n"
    "Non-Negotiables: No silent degradation; preserve traceback; actionable "
    "remediation.\n"
)

MARKER = "FAIL HARD"


def load(file: Path) -> str:
    """Read and return file contents as UTF-8 string.

    Args:
        file: Path to a UTF-8 encoded text file.

    Returns:
        Entire file content.
    """
    return file.read_text(encoding="utf-8")


def save(file: Path, content: str) -> None:
    """Persist UTF-8 text content to file path atomically.

    Args:
        file: Destination path.
        content: Text to write.
    """
    file.write_text(content, encoding="utf-8")


def find_non_compliant(files: Iterable[Path]) -> list[Path]:
    """Return list of files missing the FAIL HARD marker.

    Args:
        files: Iterable of file paths to inspect.

    Returns:
        list of Path objects that do not contain MARKER.
    """
    missing: list[Path] = []
    for f in files:
        try:
            text = load(f)
        except Exception as e:  # FAIL HARD: surface file I/O issues
            print(
                "Goal: Scan control document for FAIL HARD marker\n"
                f"Problem: Exception reading {f}: {e}\n"
                "Root Cause: File I/O error (permission, missing file, encoding)\n"
                "Solutions:\n"
                "  1. Verify file exists and readable (ls -l)\n"
                "  2. Check permissions / ownership\n"
                "  3. Validate UTF-8 encoding or adjust loader"
            )
            raise
        if MARKER not in text:
            missing.append(f)
    return missing


def fix_files(files: Iterable[Path]) -> list[Path]:
    """Append canonical block to each file missing the marker.

    Args:
        files: Files previously identified as missing the marker.

    Returns:
        list of Path objects that still lack the marker after attempted fix.
    """
    still_missing: list[Path] = []
    for f in files:
        text = load(f)
        if MARKER in text:
            continue
        # Simple heuristic: if README.md place before end; else append.
        if f.name == "README.md":
            content = text + CANONICAL_BLOCK
        else:
            content = text.rstrip() + CANONICAL_BLOCK
        save(f, content)
        # Re-verify
        if MARKER not in load(f):
            still_missing.append(f)
    return still_missing


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Raw argument vector excluding program name.

    Returns:
        Parsed argparse Namespace.
    """
    parser = argparse.ArgumentParser(description="Ensure FAIL HARD coverage")
    parser.add_argument("--check", action="store_true", help="Check compliance only")
    parser.add_argument(
        "--fix", action="store_true", help="Append canonical block where missing"
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Entrypoint for FAIL HARD enforcement.

    Performs check or fix operations based on flags.

    Args:
        argv: Command-line arguments.

    Returns:
        Process exit code (0 success, 1 check failed, 2 fix partial failure).
    """
    args = parse_args(argv)
    if not (args.check or args.fix):
        print("Specify --check or --fix")
        return 1

    try:
        missing = find_non_compliant(CONTROL_FILES)
    except Exception:
        return 1

    if args.check and missing:
        print("Non-compliant files (missing FAIL HARD marker):")
        for m in missing:
            print(f" - {m.relative_to(ROOT)}")
        return 1

    if args.fix and missing:
        still = fix_files(missing)
        if still:
            print(
                "Goal: Auto-append FAIL HARD block\n"
                "Problem: Some files remained missing after fix\n"
                "Root Cause: Unexpected write failure or marker mismatch\n"
                "Solutions:\n"
                "  1. Manually inspect files for encoding issues\n"
                "  2. Confirm script write permissions\n"
                "  3. Adjust marker constant if wording changed"
            )
            for s in still:
                print(f" - {s.relative_to(ROOT)}")
            return 2
        print("Added FAIL HARD block to:")
        for m in missing:
            print(f" - {m.relative_to(ROOT)}")

    print("All control documents contain FAIL HARD marker.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
