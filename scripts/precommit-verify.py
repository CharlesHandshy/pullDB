"""Redirect entrypoint for hygiene verification.

This legacy script delegates to the canonical tool in `dna_repo/tools/`
to avoid duplicate module definitions for mypy while preserving backwards
compatibility with existing CI references.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:  # pragma: no cover
    """Delegate execution to canonical dna_repo hygiene script.

    Returns:
        Exit status code (always 0; delegated script handles failures).
    """
    target = (
        Path(__file__).resolve().parent.parent
        / "dna_repo"
        / "tools"
        / "precommit-verify.py"
    )
    runpy.run_path(str(target), run_name="__main__")
    # The delegated script handles its own exit code printing. We cannot easily
    # capture it without modifying the target; assume process exit will occur.
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
