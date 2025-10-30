"""Entry point for the `pulldb-daemon` executable.

Phase 0 prototype stub. The real polling/worker loop will be implemented in
Milestone 4 after repositories and configuration are ready.
"""
from __future__ import annotations

import typing as t
import sys


def run_once() -> None:
    # Placeholder heartbeat.
    print("[pulldb-daemon] Prototype daemon stub running - no job processing yet.")


def main(argv: t.Sequence[str] | None = None) -> int:
    # For now just emit a single heartbeat then exit; later will become long-running.
    run_once()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
