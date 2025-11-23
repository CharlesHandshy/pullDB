"""Tests for pullDB API job endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, NamedTuple, Protocol, cast

import pytest
from fastapi.testclient import TestClient

from pulldb.api.main import APIState, app, get_api_state
from pulldb.domain.config import Config
from pulldb.domain.models import Job, JobStatus, User
from pulldb.infra.mysql import (
    JobRepository as MySQLJobRepository,
)
from pulldb.infra.mysql import (
    MySQLPool,
)
from pulldb.infra.mysql import (
    UserRepository as MySQLUserRepository,
)


class FakeUserRepository:
    """Minimal user repository stub for API tests."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_or_create_user(self, username: str) -> User:
        self.requested.append(username)
        return User(
            user_id="user-1",
            username=username,
            user_code="janedo",
            is_admin=False,
            created_at=datetime(2025, 11, 3, 0, 0, tzinfo=UTC),
        )


class FakeJobRepository:
    """In-memory job repository stub for API tests."""

    def __init__(self) -> None:
        self.enqueued: list[Job] = []
        self.active: list[Job] = []
        self.raise_on_enqueue: Exception | None = None

    def enqueue_job(self, job: Job) -> str:
        if self.raise_on_enqueue is not None:
            raise self.raise_on_enqueue
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

    def get_recent_jobs(self, limit: int = 100) -> list[Job]:
        """Return recent jobs (active + recently completed), limited."""
        return list(self.active[:limit])


class FakeRepos(NamedTuple):
    user_repo: FakeUserRepository
    job_repo: FakeJobRepository


class ResponseProtocol(Protocol):
    """Subset of methods returned by TestClient requests."""

    status_code: int

    def json(self) -> Any: ...


def _post_json(client: Any, url: str, payload: dict[str, Any]) -> ResponseProtocol:
    return cast(ResponseProtocol, client.post(url, json=payload))


def _get(client: Any, url: str, *, params: dict[str, Any]) -> ResponseProtocol:
    return cast(ResponseProtocol, client.get(url, params=params))


@pytest.fixture
def fake_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRepos]:
    user_repo = FakeUserRepository()
    job_repo = FakeJobRepository()
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
    )

    def _override() -> APIState:
        return state

    app.dependency_overrides[get_api_state] = _override
    if hasattr(app.state, "api_state"):
        delattr(app.state, "api_state")
    try:
        yield FakeRepos(user_repo=user_repo, job_repo=job_repo)
    finally:
        app.dependency_overrides.pop(get_api_state, None)
        if hasattr(app.state, "api_state"):
            delattr(app.state, "api_state")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _build_job(**overrides: Any) -> Job:
    return Job(
        id=overrides.get("id", "job-1"),
        owner_user_id=overrides.get("owner_user_id", "user-1"),
        owner_username=overrides.get("owner_username", "jane"),
        owner_user_code=overrides.get("owner_user_code", "janedo"),
        target=overrides.get("target", "janedoacme"),
        staging_name=overrides.get("staging_name", "janedoacme_aaaaaaaaaaaa"),
        dbhost=overrides.get("dbhost", "dev-db-01"),
        status=overrides.get("status", JobStatus.QUEUED),
        submitted_at=overrides.get(
            "submitted_at",
            datetime(2025, 11, 3, 12, 0, tzinfo=UTC),
        ),
        started_at=overrides.get("started_at"),
        completed_at=overrides.get("completed_at"),
        options_json=overrides.get("options_json", {"customer_id": "acme"}),
        retry_count=overrides.get("retry_count", 0),
        error_detail=overrides.get("error_detail"),
    )


def test_submit_job_customer_success(client: TestClient, fake_state: FakeRepos) -> None:
    response = _post_json(
        client, "/api/jobs", {"user": "Jane.Doe", "customer": "Acme-123"}
    )
    assert response.status_code == 201
    data = cast(dict[str, Any], response.json())
    assert data["target"] == "janedoacme"
    assert fake_state.job_repo.enqueued
    assert fake_state.job_repo.enqueued[0].dbhost == "dev-db-01"


def test_submit_job_conflict_returns_409(
    client: TestClient, fake_state: FakeRepos
) -> None:
    fake_state.job_repo.raise_on_enqueue = ValueError(
        "Target 'janedoacme' already has an active job"
    )
    response = _post_json(
        client, "/api/jobs", {"user": "Jane.Doe", "customer": "Acme-123"}
    )
    assert response.status_code == 409
    detail = cast(dict[str, Any], response.json())["detail"]
    assert "already has an active job" in detail


def test_submit_job_requires_mutual_exclusive(
    client: TestClient, fake_state: FakeRepos
) -> None:
    response = _post_json(
        client,
        "/api/jobs",
        {"user": "Jane", "customer": "acme", "qatemplate": True},
    )
    assert response.status_code == 400
    detail = cast(dict[str, Any], response.json())["detail"]
    assert "exactly one" in detail


def test_active_jobs_endpoint(client: TestClient, fake_state: FakeRepos) -> None:
    fake_state.job_repo.active = [
        _build_job(id="job-1"),
        _build_job(
            id="job-2",
            target="janedoqatemplate",
            staging_name="janedoqatemplate_bbbbbbbbbbbb",
            status=JobStatus.RUNNING,
            started_at=datetime(2025, 11, 3, 12, 5, tzinfo=UTC),
        ),
    ]
    response = _get(client, "/api/jobs/active", params={"limit": 5})
    assert response.status_code == 200
    payload = cast(list[dict[str, Any]], response.json())
    assert len(payload) == 2
    assert payload[0]["id"] == "job-1"
    assert payload[1]["status"] == "running"
    assert payload[1]["staging_name"] == "janedoqatemplate_bbbbbbbbbbbb"
