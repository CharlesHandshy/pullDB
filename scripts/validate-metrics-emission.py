#!/usr/bin/env python3
"""Validate metrics emission without full restore execution.

This script validates that the metrics infrastructure is correctly configured
and can emit metrics during a restore workflow. Phase A validation approach.

Exit codes:
    0: All metrics validated successfully
    1: Metrics validation failed (see output for details)
"""

from __future__ import annotations

import sys
from pathlib import Path


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pulldb.infra.metrics import (
    MetricLabels,
    emit_counter,
    emit_event,
    emit_gauge,
    emit_timer,
)


def main() -> int:
    """Validate metrics emission.

    Returns:
        Exit code (0 success, 1 failure).
    """
    print("=" * 60)
    print("Metrics Emission Validation (Phase A)")
    print("=" * 60)

    try:
        # Test counter emission
        print("\n1️⃣  Testing counter emission...")
        emit_counter("pulldb.test.counter", 1, MetricLabels(phase="test"))
        print("✓ Counter emitted successfully")

        # Test gauge emission
        print("\n2️⃣  Testing gauge emission...")
        emit_gauge("pulldb.test.gauge", 42.5, MetricLabels(phase="test"))
        print("✓ Gauge emitted successfully")

        # Test timer emission
        print("\n3️⃣  Testing timer emission...")
        emit_timer("pulldb.test.timer", 1.23, MetricLabels(phase="test"))
        print("✓ Timer emitted successfully")

        # Test event emission
        print("\n4️⃣  Testing event emission...")
        emit_event(
            "pulldb.test.event", "Test event message", MetricLabels(phase="test")
        )
        print("✓ Event emitted successfully")

        print("\n" + "=" * 60)
        print("✅ All metrics emission checks passed!")
        print("\nPhase A Complete: Metrics emission validated")
        print("Next: Phase B - Deploy and execute 10 production restores")
        return 0

    except Exception as e:
        print(f"\n❌ Metrics validation failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
