"""Standalone development smoke test for the pullDB CLI ↔ API contract."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Protocol, cast

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from pulldb.api.main import APIState, app, get_api_state
from pulldb.cli.main import cli
from pulldb.domain.config import Config
from pulldb.domain.models import Job, User
from pulldb.infra.mysql import (
    JobRepository as MySQLJobRepository,
)
from pulldb.infra.mysql import (
    MySQLPool,
)
from pulldb.infra.mysql import (
    SettingsRepository as MySQLSettingsRepository,
)
from pulldb.infra.mysql import (
    UserRepository as MySQLUserRepository,
)


class _FakeUserRepository:
    """Minimal user repository stub for the smoke test."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_or_create_user(self, username: str) -> User:
        self.requested.append(username)
        return User(
            user_id="user-123",
            username=username,
            user_code="janedo",
            is_admin=False,
            created_at=datetime(2025, 11, 3, 0, 0, tzinfo=UTC),
        )


class _FakeJobRepository:
    """In-memory job repository stub with queue tracking."""

    def __init__(self) -> None:
        self.enqueued: list[Job] = []
        self.active: list[Job] = []

    def enqueue_job(self, job: Job) -> str:
        self.enqueued.append(job)
        self.active.append(job)
        return job.id

    def get_job_by_id(self, job_id: str) -> Job | None:
        for job in self.enqueued:
            if job.id == job_id:
                return job
        return None

    def get_active_jobs(self) -> list[Job]:
        return list(self.active)

    def get_recent_jobs(
        self, limit: int, statuses: list[str] | None = None
    ) -> list[Job]:
        # Filter by status if provided
        candidates = self.enqueued
        if statuses:
            candidates = [j for j in candidates if j.status.value in statuses]
        # Sort by submitted_at desc (mock implementation assumes append order
        # is time order)
        # For simplicity, just reverse the list
        return list(reversed(candidates))[:limit]

    def count_active_jobs_for_user(self, user_id: str) -> int:
        """Count active jobs for a user."""
        return sum(1 for j in self.active if j.owner_user_id == user_id)

    def count_all_active_jobs(self) -> int:
        """Count all active jobs."""
        return len(self.active)


class _FakeSettingsRepository:
    """In-memory settings repository stub for smoke tests."""

    def __init__(self) -> None:
        self.settings: dict[str, str] = {
            "max_active_jobs_per_user": "0",  # Unlimited
            "max_active_jobs_global": "0",  # Unlimited
        }

    def get_max_active_jobs_per_user(self) -> int:
        value = self.settings.get("max_active_jobs_per_user", "0")
        try:
            return int(value)
        except ValueError:
            return 0

    def get_max_active_jobs_global(self) -> int:
        value = self.settings.get("max_active_jobs_global", "0")
        try:
            return int(value)
        except ValueError:
            return 0


class _ResponseProtocol(Protocol):
    """Subset of methods returned by the patched requests module."""

    status_code: int

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...

    @property
    def reason(self) -> str: ...


def test_dev_smoke_restore_then_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy-path smoke test covering CLI restore submission and status listing."""

    user_repo = _FakeUserRepository()
    job_repo = _FakeJobRepository()
    settings_repo = _FakeSettingsRepository()
    config = Config(
        mysql_host="coord-db",
        mysql_user="pulldb",
        mysql_password="secret",
        mysql_database="pulldb",
        default_dbhost="dev-db-01",
    )
    state = APIState(
        config=config,
        pool=cast(MySQLPool, SimpleNamespace()),
        user_repo=cast(MySQLUserRepository, user_repo),
        job_repo=cast(MySQLJobRepository, job_repo),
        settings_repo=cast(MySQLSettingsRepository, settings_repo),
    )

    def _override_state() -> APIState:
        return state

    app.dependency_overrides[get_api_state] = _override_state
    if hasattr(app.state, "api_state"):
        delattr(app.state, "api_state")

    runner = CliRunner()

    with TestClient(app) as api_client:

        def _client_post(
            url: str,
            *,
            json: dict[str, Any],
            timeout: float,
        ) -> _ResponseProtocol:
            assert url.startswith("http://testserver"), (
                "CLI should target local TestClient"
            )
            return cast(_ResponseProtocol, api_client.post(url, json=json))

        def _client_get(
            url: str,
            *,
            params: dict[str, Any],
            timeout: float,
        ) -> _ResponseProtocol:
            assert url.startswith("http://testserver"), (
                "CLI should target local TestClient"
            )
            return cast(_ResponseProtocol, api_client.get(url, params=params))

        monkeypatch.setenv("PULLDB_API_URL", "http://testserver")
        monkeypatch.setattr("pulldb.cli.main.requests_module.post", _client_post)
        monkeypatch.setattr("pulldb.cli.main.requests_module.get", _client_get)

        restore_result = runner.invoke(
            cli,
            ["restore", "user=Jane.Doe", "customer=Acme-123"],
            catch_exceptions=False,
        )
        assert restore_result.exit_code == 0
        assert "Job submitted successfully!" in restore_result.output
        assert "target: janedoacme" in restore_result.output
        assert user_repo.requested == ["Jane.Doe"]
        assert job_repo.enqueued, "Job repository should receive enqueued job"

        status_result = runner.invoke(
            cli,
            ["status", "--limit", "5"],
            catch_exceptions=False,
        )
        assert status_result.exit_code == 0
        assert "janedoacme" in status_result.output
        assert "STATUS" in status_result.output

    app.dependency_overrides.pop(get_api_state, None)
    if hasattr(app.state, "api_state"):
        delattr(app.state, "api_state")
