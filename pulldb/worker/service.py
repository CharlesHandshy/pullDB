"""Worker Service prototype stub.

Phase 0: polls nothing and exits; structure in place for future implementation.
"""

from __future__ import annotations

import time
import typing as t


def run_once() -> None:
    """Emit a single heartbeat log line (placeholder)."""
    print("[pulldb-worker] heartbeat - no queue polling yet")


def main(argv: t.Sequence[str] | None = None) -> int:
    """Worker service main entry point (prototype)."""
    run_once()
    # Simulate tiny wait to show structure for future loop.
    time.sleep(0.05)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main([]))
