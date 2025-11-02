"""Pre-Commit Hygiene Verification for pullDB.

Runs ordered quality gates (format, lint, types, tests) and performs an
engineering-dna submodule freshness check. Follows FAIL HARD philosophy:
fail immediately with actionable diagnostics.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


GATES = [
    ("format", "ruff format ."),
    ("lint", "ruff check ."),
    ("types", "mypy pulldb"),
    ("tests", "pytest -q --timeout=60 --timeout-method=thread"),
]


def run_gate(command: str) -> None:
    """Execute a hygiene gate command and fail fast on non-zero exit.

    Args:
        command: Shell command to execute for the gate.
    """
    result = subprocess.run(command, shell=True, check=False)
    if result.returncode != 0:
        print("\nFAIL HARD DIAGNOSTIC")
        print("GOAL: Run hygiene gate")
        print(f"PROBLEM: Gate command failed: {command}")
        print("ROOT CAUSE: See command output above; non-zero exit indicates failure")
        print("SOLUTIONS:")
        print("1. Fix reported issues and re-run scripts/precommit-verify.py")
        print("2. For type errors, add/adjust annotations or refactor code")
        print("3. For lint issues, run 'ruff check . --fix' where safe")
        sys.exit(1)


def check_submodule_freshness() -> None:
    """Warn if engineering-dna submodule is behind remote main.

    Performs lightweight commit comparison; does not modify working tree.
    Silent if submodule absent (e.g., shallow clone or uninitialized).
    """
    sub_path = Path("engineering-dna")
    if not sub_path.exists():  # Submodule may not be initialized yet
        print("[info] engineering-dna submodule not present (skipping freshness check)")
        return
    try:
        # Capture current submodule commit
        current = subprocess.run(
            ["git", "-C", str(sub_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        remote_ref = subprocess.run(
            ["git", "-C", str(sub_path), "ls-remote", "origin", "main"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[0]
        if current != remote_ref:
            print(
                "[warning] engineering-dna submodule behind remote main. "
                f"Current {current[:7]} != remote {remote_ref[:7]}"
            )
            print(
                "         Run: scripts/update-engineering-dna.sh --push to advance "
                "and commit pointer"
            )
    except Exception as e:
        print(f"[warning] engineering-dna freshness check skipped: {e}")


def main() -> int:  # pragma: no cover
    """Run all hygiene gates and perform submodule freshness check.

    Returns:
        Exit code: 0 on success; process exits early on failure.
    """
    for name, cmd in GATES:
        print(f"[gate] {name}: {cmd}")
        run_gate(cmd)
    check_submodule_freshness()
    print("All gates passed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
