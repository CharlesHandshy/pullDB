"""Tests for `scripts/benchmark_atomic_rename.py` benchmark behavior.

Focus on input validation FAIL HARD diagnostics and JSON output structure.
We avoid timing assertions (non-deterministic) by validating presence of
expected keys and reasonable positive values.

HCA Layer: tests (pulldb/tests/)
"""

from __future__ import annotations

import json
import sys
from typing import Any, TypedDict

import pytest

import scripts.benchmark_atomic_rename as bench


class _BenchmarkEntry(TypedDict):
    table_count: int
    repetitions: int
    avg_seconds: float
    min_seconds: float
    max_seconds: float
    rename_sql_length: int


def _run(argv: list[str]) -> tuple[int, str, str]:
    orig_argv = sys.argv
    orig_out = sys.stdout
    orig_err = sys.stderr
    from io import StringIO

    try:
        sys.argv = ["benchmark_atomic_rename.py", *argv]
        buf_out = StringIO()
        buf_err = StringIO()
        sys.stdout = buf_out
        sys.stderr = buf_err
        try:
            code = bench.main()
        except SystemExit as e:
            code = int(e.code) if isinstance(e.code, (int, str)) else 0
        return code, buf_out.getvalue(), buf_err.getvalue()
    finally:  # pragma: no cover - cleanup
        sys.argv = orig_argv
        sys.stdout = orig_out
        sys.stderr = orig_err


def test_json_output_structure() -> None:
    code, out, err = _run(["--tables", "5", "--repeat", "2", "--json"])
    assert code == 0
    assert err == ""
    data_raw: Any = json.loads(out)
    assert isinstance(data_raw, list)
    # data_raw is expected to be a list of dicts matching _BenchmarkEntry keys
    data: list[_BenchmarkEntry] = data_raw  # mypy infers correct structure dynamically
    assert isinstance(data, list)
    assert len(data) == 1
    entry = data[0]
    for key in [
        "table_count",
        "repetitions",
        "avg_seconds",
        "min_seconds",
        "max_seconds",
        "rename_sql_length",
    ]:
        assert key in entry
    table_count = entry["table_count"]
    repetitions = entry["repetitions"]
    avg_seconds = entry["avg_seconds"]
    rename_len = entry["rename_sql_length"]
    assert table_count == 5
    assert repetitions == 2
    assert avg_seconds >= 0.0
    assert rename_len > 0


@pytest.mark.parametrize("bad_count", [0, -1])
def test_fail_hard_non_positive_table_count(bad_count: int) -> None:
    code, out, err = _run(["--tables", str(bad_count)])
    assert code == 1
    assert out == ""
    assert "Goal:" in err and "Problem:" in err and "Root Cause:" in err
    assert "Non-positive table count" in err


def test_fail_hard_excessive_table_count() -> None:
    excessive = bench.MAX_TABLE_COUNT + 1
    code, out, err = _run(["--tables", str(excessive)])
    assert code == 1
    assert out == ""
    assert "exceeds" in err


@pytest.mark.parametrize("bad_repeat", [0, -5])
def test_fail_hard_non_positive_repeat(bad_repeat: int) -> None:
    code, out, err = _run(["--repeat", str(bad_repeat)])
    assert code == 1
    assert out == ""
    assert "Repeat must be positive" in err


@pytest.mark.parametrize("bad_width", [0, -2, bench.MAX_NAME_WIDTH + 1])
def test_fail_hard_width_outside_range(bad_width: int) -> None:
    code, out, err = _run(["--width", str(bad_width)])
    assert code == 1
    assert out == ""
    assert "Width outside" in err


def test_multiple_table_counts() -> None:
    code, out, err = _run(["--tables", "2", "4", "--repeat", "1", "--json"])
    assert code == 0
    assert err == ""
    data = json.loads(out)
    counts = [e["table_count"] for e in data]
    assert counts == [2, 4]
