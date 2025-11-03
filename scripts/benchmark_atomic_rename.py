"""Benchmark script for atomic rename RENAME TABLE SQL build performance.

Generates synthetic staging tables metadata in-memory to measure time to build
single atomic RENAME statement (mirroring stored procedure logic) for various
scale factors. This does NOT require MySQL; focuses solely on string assembly
cost which is dominant for very large schemas (hundreds/thousands of tables).

Usage:
    python3 scripts/benchmark_atomic_rename.py --tables 50 200 1000 5000

Options:
    --tables   One or more integer table counts to benchmark (default: 50 200 1000)
    --repeat   Repetitions per table count (default: 5)
    --width    Table name width (characters) base (default: 24)
    --staging-prefix  Prefix for staging db name (default: stagingdb)
    --target-prefix   Prefix for target db name (default: targetdb)
    --json     Emit JSON summary only (machine-readable)

Output:
    Human readable table of counts, average build time, min/max, bytes length.

FAIL HARD Philosophy:
    Any invalid input (non-positive counts, excessive width) aborts with clear
    diagnostics. Benchmark aims to stay deterministic: uses predictable table
    name generation.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


DEFAULT_TABLE_COUNTS = [50, 200, 1000]
MAX_TABLE_COUNT = 20000  # guard unrealistic explosion
MAX_NAME_WIDTH = 48  # keep individual names moderate


@dataclass(slots=True)
class BenchmarkResult:
    """Result of a single table count benchmark.

    Attributes:
        table_count: Number of tables used for the rename SQL build.
        repetitions: Number of repetitions performed for timing.
        avg_seconds: Mean duration across repetitions.
        min_seconds: Fastest observed duration.
        max_seconds: Slowest observed duration.
        rename_sql_length: Byte length of generated RENAME statement.
    """

    table_count: int
    repetitions: int
    avg_seconds: float
    min_seconds: float
    max_seconds: float
    rename_sql_length: int

    def as_dict(self) -> dict[str, float | int]:
        """Return JSON-serializable dictionary representation."""
        return {
            "table_count": self.table_count,
            "repetitions": self.repetitions,
            "avg_seconds": self.avg_seconds,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "rename_sql_length": self.rename_sql_length,
        }


def _fail(goal: str, problem: str, root_cause: str, solutions: Sequence[str]) -> None:
    lines = [
        f"Goal: {goal}",
        f"Problem: {problem}",
        f"Root Cause: {root_cause}",
        "Solutions:",
    ]
    for i, s in enumerate(solutions, 1):
        lines.append(f"  {i}. {s}")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for benchmark script."""
    parser = argparse.ArgumentParser(description="Benchmark atomic rename SQL build")
    parser.add_argument(
        "--tables",
        nargs="*",
        type=int,
        default=DEFAULT_TABLE_COUNTS,
        help="List of table counts to benchmark",
    )
    parser.add_argument(
        "--repeat", type=int, default=5, help="Repetitions per table count"
    )
    parser.add_argument("--width", type=int, default=24, help="Base table name width")
    parser.add_argument(
        "--staging-prefix", default="stagingdb", help="Staging db name prefix"
    )
    parser.add_argument(
        "--target-prefix", default="targetdb", help="Target db name prefix"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON summary only")
    return parser.parse_args()


def _generate_table_names(count: int, width: int) -> list[str]:
    base = "t" * width
    names = []
    for i in range(count):
        # Ensure varying final segment for uniqueness
        names.append(f"{base}_{i}")
    return names


def _build_rename_sql(staging: str, target: str, tables: Sequence[str]) -> str:
    parts = [f"`{staging}`.`{t}` TO `{target}`.`{t}`" for t in tables]
    return "RENAME TABLE " + ", ".join(parts)


def benchmark_table_count(
    count: int, repeat: int, width: int, staging: str, target: str
) -> BenchmarkResult:
    """Benchmark building rename SQL for provided table count.

    Args:
        count: Number of tables to simulate.
        repeat: Number of repetitions for timing stability.
        width: Base width of table name prefix.
        staging: Staging database name.
        target: Target database name.

    Returns:
        BenchmarkResult containing timing statistics and statement size.
    """
    tables = _generate_table_names(count, width)
    durations: list[float] = []
    rename_sql = ""
    for _ in range(repeat):
        start = time.perf_counter()
        rename_sql = _build_rename_sql(staging, target, tables)
        end = time.perf_counter()
        durations.append(end - start)
    return BenchmarkResult(
        table_count=count,
        repetitions=repeat,
        avg_seconds=statistics.mean(durations),
        min_seconds=min(durations),
        max_seconds=max(durations),
        rename_sql_length=len(rename_sql),
    )


def _validate_inputs(table_counts: Iterable[int], repeat: int, width: int) -> None:
    for c in table_counts:
        if c <= 0:
            _fail(
                goal="Validate table counts",
                problem="Non-positive table count provided",
                root_cause=str(c),
                solutions=["Use positive integers", "Remove zero/negative counts"],
            )
        if c > MAX_TABLE_COUNT:
            _fail(
                goal="Validate table counts",
                problem="Table count exceeds maximum",
                root_cause=str(c),
                solutions=["Reduce count", "Split into multiple benchmarks"],
            )
    if repeat <= 0:
        _fail(
            goal="Validate repetitions",
            problem="Repeat must be positive",
            root_cause=str(repeat),
            solutions=["Use value >= 1"],
        )
    if not (1 <= width <= MAX_NAME_WIDTH):
        _fail(
            goal="Validate table name width",
            problem="Width outside allowed range",
            root_cause=str(width),
            solutions=[
                "Use width between 1 and 48",
                "Adjust --width parameter to acceptable range",
            ],
        )


def main() -> int:
    """Entrypoint for benchmark execution."""
    args = parse_args()
    _validate_inputs(args.tables, args.repeat, args.width)

    staging = f"{args.staging_prefix}_bench"
    target = f"{args.target_prefix}_bench"

    results: list[BenchmarkResult] = []
    for c in args.tables:
        results.append(
            benchmark_table_count(c, args.repeat, args.width, staging, target)
        )

    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
        return 0

    # Human readable
    print("Atomic Rename SQL Build Benchmark")
    print(f"Staging: {staging}  Target: {target}")
    print(f"Repetitions per count: {args.repeat}\n")
    header = (
        f"{'Tables':>8}  {'Avg ms':>10}  {'Min ms':>10}  {'Max ms':>10}  "
        f"{'SQL bytes':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.table_count:8d}  {r.avg_seconds * 1000:10.3f}  "
            f"{r.min_seconds * 1000:10.3f}  {r.max_seconds * 1000:10.3f}  "
            f"{r.rename_sql_length:10d}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
