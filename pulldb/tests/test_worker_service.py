"""Tests for worker service enhancements (graceful stop via callback).

We avoid direct signal sending inside tests for portability; instead we
exercise the new `should_stop` callback logic added to `run_poll_loop`.
"""

from __future__ import annotations

import time
import typing as t

from pulldb.infra.mysql import JobRepository
from pulldb.worker.loop import run_poll_loop


class _FakeJobRepo:
    """Minimal fake job repository for poll loop tests.

    Counts how many times `get_next_queued_job` is invoked and always returns
    no job (None) to trigger backoff path.
    """

    def __init__(self) -> None:
        self.poll_count = 0

    def get_next_queued_job(self) -> t.Any:  # intentionally Any for simplicity
        self.poll_count += 1
        return None


def test_poll_loop_graceful_stop_callback() -> None:
    """Poll loop stops when `should_stop` returns True.

    Uses very small poll_interval so test completes quickly while still
    exercising backoff increments.
    """

    repo = _FakeJobRepo()

    def should_stop() -> bool:
        return repo.poll_count >= 3

    start = time.perf_counter()
    # Cast to JobRepository for type checker; loop never calls other methods
    # when queue empty.
    run_poll_loop(
        t.cast(JobRepository, repo),
        max_iterations=None,
        poll_interval=0.01,
        should_stop=should_stop,
    )
    duration = time.perf_counter() - start

    assert repo.poll_count == 3, "Loop should stop after third poll iteration"
    # Upper bound guard (< 0.5s) to ensure backoff didn't run away.
    assert duration < 0.5, f"Test took too long ({duration:.3f}s)"
