"""Tests for worker service enhancements.

We avoid direct signal sending inside tests for portability; instead we
exercise the poll loop `should_stop` callback logic and validate that the
service entry point wires configuration + CLI arguments correctly.
"""

from __future__ import annotations

import time
import typing as t
from types import SimpleNamespace

import pytest

from pulldb.infra.mysql import JobRepository
from pulldb.worker import service as worker_service
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
        lambda _job: None,
        max_iterations=None,
        poll_interval=0.01,
        should_stop=should_stop,
    )
    duration = time.perf_counter() - start

    assert repo.poll_count == 3, "Loop should stop after third poll iteration"
    # Upper bound guard (< 0.5s) to ensure backoff didn't run away.
    assert duration < 0.5, f"Test took too long ({duration:.3f}s)"


def test_worker_service_main_invokes_poll_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pulldb-worker` passes parsed CLI arguments to the poll loop."""

    config = SimpleNamespace(
        mysql_host="coord-db",
        mysql_user="worker",
        mysql_password="secret",
        mysql_database="pulldb",
    )
    repo = t.cast(JobRepository, object())
    job_executor = object()
    captured: dict[str, t.Any] = {}

    monkeypatch.setattr(worker_service, "_load_config", lambda: config)
    monkeypatch.setattr(worker_service, "_build_job_repository", lambda _: repo)
    monkeypatch.setattr(worker_service, "_build_job_executor", lambda *_: job_executor)
    monkeypatch.setattr(worker_service.signal, "signal", lambda *_, **__: None)
    monkeypatch.setattr(worker_service, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(worker_service, "emit_gauge", lambda *_, **__: None)

    def _fake_loop(
        repo_arg: JobRepository,
        executor_arg: t.Any,
        *,
        max_iterations: int | None,
        poll_interval: float,
        should_stop: t.Callable[[], bool],
    ) -> None:
        captured["repo"] = repo_arg
        captured["executor"] = executor_arg
        captured["max_iterations"] = max_iterations
        captured["poll_interval"] = poll_interval
        captured["should_stop"] = should_stop()

    monkeypatch.setattr(worker_service, "run_poll_loop", _fake_loop)

    result = worker_service.main(["--max-iterations", "5", "--poll-interval", "0.5"])

    assert result == 0
    assert captured["repo"] is repo
    assert captured["executor"] is job_executor
    assert captured["max_iterations"] == 5
    assert captured["poll_interval"] == 0.5
    assert captured["should_stop"] is False


def test_worker_service_oneshot_overrides_iterations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        mysql_host="coord-db",
        mysql_user="worker",
        mysql_password="secret",
        mysql_database="pulldb",
    )
    monkeypatch.setattr(worker_service, "_load_config", lambda: config)
    repo = t.cast(JobRepository, object())
    job_executor = object()
    monkeypatch.setattr(worker_service, "_build_job_repository", lambda _: repo)
    monkeypatch.setattr(worker_service, "_build_job_executor", lambda *_: job_executor)
    monkeypatch.setattr(worker_service.signal, "signal", lambda *_, **__: None)
    monkeypatch.setattr(worker_service, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(worker_service, "emit_gauge", lambda *_, **__: None)

    captured: dict[str, t.Any] = {}

    def _fake_loop(
        *_: t.Any,
        max_iterations: int | None,
        poll_interval: float,
        should_stop: t.Callable[[], bool],
    ) -> None:
        captured["max_iterations"] = max_iterations
        captured["poll_interval"] = poll_interval
        captured["should_stop_called"] = should_stop()

    monkeypatch.setattr(worker_service, "run_poll_loop", _fake_loop)

    result = worker_service.main(["--oneshot"])

    assert result == 0
    assert captured["max_iterations"] == 1
    assert captured["poll_interval"] == worker_service.MIN_POLL_INTERVAL_SECONDS
    assert captured["should_stop_called"] is False


def test_worker_service_returns_error_on_config_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_service, "_load_config", _raise)
    monkeypatch.setattr(worker_service.signal, "signal", lambda *_, **__: None)
    monkeypatch.setattr(worker_service, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(worker_service, "emit_gauge", lambda *_, **__: None)

    result = worker_service.main([])

    assert result == 1
