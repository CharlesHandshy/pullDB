"""Tests for pullDB API job endpoints."""

from __future__ import annotations

"""HCA Layer: tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, NamedTuple, Protocol, cast

import pytest
from fastapi.testclient import TestClient

from pulldb.api.auth import get_authenticated_user
from pulldb.api.main import APIState, app, get_api_state
from pulldb.domain.config import Config
from pulldb.domain.models import Job, JobStatus, User, UserRole
from pulldb.infra.mysql import (
    HostRepository as MySQLHostRepository,
)
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
            role=UserRole.USER,
            created_at=datetime(2025, 11, 3, 0, 0, tzinfo=UTC),
            allowed_hosts=["dev-db-01"],  # Allow default host for tests
        )

    def get_user_by_username(self, username: str) -> User | None:
        """Return user by username (used by enqueue_job)."""
        self.requested.append(username)
        return User(
            user_id="user-1",
            username=username,
            user_code="janedo",
            role=UserRole.USER,
            created_at=datetime(2025, 11, 3, 0, 0, tzinfo=UTC),
            allowed_hosts=["dev-db-01"],  # Allow default host for tests
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

    def count_active_jobs_for_user(self, user_id: str) -> int:
        """Count active jobs for a user."""
        return sum(1 for j in self.active if j.owner_user_id == user_id)

    def count_all_active_jobs(self) -> int:
        """Count all active jobs."""
        return len(self.active)

    def count_active_jobs_for_host(self, hostname: str) -> int:
        """Count active jobs for a host."""
        return sum(1 for j in self.active if j.dbhost == hostname)

    def has_active_jobs_for_target(self, target: str, dbhost: str) -> bool:
        """Check if there are active jobs for the same target on the same host."""
        return any(
            j.target == target and j.dbhost == dbhost
            for j in self.active
        )

    def get_current_operation(self, job_id: str) -> str | None:
        """Get current operation for a job (stub returns None)."""
        return None

    def get_cancel_requested_at(self, job_id: str) -> datetime | None:
        """Get cancel requested timestamp (stub returns None)."""
        return None

    def get_locked_by_target(
        self, target: str, dbhost: str, user_id: str
    ) -> Job | None:
        """Check if target is locked (stub returns None - not locked)."""
        return None

    def get_deployed_job_for_target(
        self, target: str, dbhost: str, user_id: str
    ) -> Job | None:
        """Get deployed job for target (stub returns None - no existing deploy)."""
        return None


class FakeSettingsRepository:
    """In-memory settings repository stub for API tests."""

    def __init__(self) -> None:
        self.settings: dict[str, str] = {
            "max_active_jobs_per_user": "0",  # Unlimited by default
            "max_active_jobs_global": "0",  # Unlimited by default
        }

    def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

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


class FakeHostRepository:
    """In-memory host repository stub for API tests."""

    def __init__(self) -> None:
        from pulldb.domain.models import DBHost

        self.hosts: dict[str, DBHost] = {}
        # Default: always have capacity
        self._has_active_capacity = True

    def get_host_by_hostname(self, hostname: str) -> Any:
        """Return host or a mock with default limits."""
        from pulldb.domain.models import DBHost

        if hostname in self.hosts:
            return self.hosts[hostname]
        # Return a default host with sensible limits
        return DBHost(
            id="default-host-id",
            hostname=hostname,
            credential_ref="",
            max_running_jobs=5,
            max_active_jobs=10,
            enabled=True,
        )

    def check_host_active_capacity(self, hostname: str) -> bool:
        """Return whether host has capacity for more active jobs."""
        return self._has_active_capacity

    def set_has_active_capacity(self, value: bool) -> None:
        """Test helper to control capacity check result."""
        self._has_active_capacity = value


class FakeRepos(NamedTuple):
    user_repo: FakeUserRepository
    job_repo: FakeJobRepository
    settings_repo: FakeSettingsRepository
    host_repo: FakeHostRepository


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
    settings_repo = FakeSettingsRepository()
    host_repo = FakeHostRepository()
    config = Config(
        mysql_host="coord-db",
        mysql_user="pulldb_app",
        mysql_password="secret",
        mysql_database="pulldb_service",
        default_dbhost="dev-db-01",
    )
    state = APIState(
        config=config,
        pool=cast(MySQLPool, SimpleNamespace()),
        user_repo=cast(MySQLUserRepository, user_repo),
        job_repo=cast(MySQLJobRepository, job_repo),
        settings_repo=cast(MySQLSettingsRepository, settings_repo),
        host_repo=cast(MySQLHostRepository, host_repo),
    )

    def _override() -> APIState:
        return state

    # Create a mock authenticated user for auth bypass
    # Use admin=True to bypass the "can only submit jobs for yourself" check
    # since tests may use different usernames in requests
    async def _mock_auth_user() -> User:
        return User(
            user_id="user-1",
            username="jane.doe",
            user_code="janedo",
            role=UserRole.ADMIN,
            created_at=datetime(2025, 11, 3, 0, 0, tzinfo=UTC),
            allowed_hosts=["dev-db-01"],
        )

    app.dependency_overrides[get_api_state] = _override
    app.dependency_overrides[get_authenticated_user] = _mock_auth_user
    if hasattr(app.state, "api_state"):
        delattr(app.state, "api_state")
    try:
        yield FakeRepos(
            user_repo=user_repo,
            job_repo=job_repo,
            settings_repo=settings_repo,
            host_repo=host_repo,
        )
    finally:
        app.dependency_overrides.pop(get_api_state, None)
        app.dependency_overrides.pop(get_authenticated_user, None)
        if hasattr(app.state, "api_state"):
            delattr(app.state, "api_state")


@pytest.fixture
def client(fake_state: FakeRepos) -> Iterator[TestClient]:
    """Create test client after fake_state is set up.
    
    Depends on fake_state to ensure dependency override is configured
    before the client makes any requests.
    """
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
    # Use backup_path to bypass S3 discovery
    response = _post_json(
        client, "/api/jobs", {
            "user": "Jane.Doe",
            "customer": "Acme-123",
            "backup_path": "s3://test-bucket/backups/acme/20260103.tar"
        }
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
        client, "/api/jobs", {
            "user": "Jane.Doe",
            "customer": "Acme-123",
            "backup_path": "s3://test-bucket/backups/acme/20260103.tar"
        }
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


# =============================================================================
# Phase 2: Concurrency Control Tests
# =============================================================================


def test_submit_job_unlimited_when_caps_are_zero(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """When caps are 0 (unlimited), jobs should be accepted regardless of count."""
    # Set limits to 0 (unlimited)
    fake_state.settings_repo.settings["max_active_jobs_per_user"] = "0"
    fake_state.settings_repo.settings["max_active_jobs_global"] = "0"

    # Add some existing active jobs (with different targets to avoid conflict)
    fake_state.job_repo.active = [
        _build_job(id="existing-1", target="othercust1"),
        _build_job(id="existing-2", target="othercust2"),
        _build_job(id="existing-3", target="othercust3"),
    ]

    response = _post_json(
        client, "/api/jobs", {
            "user": "Jane.Doe",
            "customer": "NewCust",
            "backup_path": "s3://test-bucket/backups/newcust/20260103.tar"
        }
    )
    assert response.status_code == 201
    data = cast(dict[str, Any], response.json())
    assert data["status"] == "queued"


def test_submit_job_respects_per_user_limit(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Per-user limit should block new jobs when user has reached limit."""
    # Set per-user limit to 2
    fake_state.settings_repo.settings["max_active_jobs_per_user"] = "2"
    fake_state.settings_repo.settings["max_active_jobs_global"] = "0"

    # Add 2 existing active jobs for user-1 (with different targets to avoid conflict)
    fake_state.job_repo.active = [
        _build_job(id="job-1", owner_user_id="user-1", target="othercust1"),
        _build_job(id="job-2", owner_user_id="user-1", target="othercust2"),
    ]

    # Submit a new job (FakeUserRepository always returns user_id="user-1")
    response = _post_json(client, "/api/jobs", {
        "user": "Jane.Doe",
        "customer": "Acme",
        "backup_path": "s3://test-bucket/backups/acme/20260103.tar"
    })

    assert response.status_code == 429
    data = cast(dict[str, Any], response.json())
    # Error message format: "You have X active jobs (limit: Y). Please wait..."
    assert "2 active jobs" in data["detail"]
    assert "limit: 2" in data["detail"]


def test_submit_job_allows_under_per_user_limit(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Per-user limit should allow jobs when under limit."""
    # Set per-user limit to 3
    fake_state.settings_repo.settings["max_active_jobs_per_user"] = "3"
    fake_state.settings_repo.settings["max_active_jobs_global"] = "0"

    # Add 2 existing active jobs for user-1 (under limit of 3, with different targets)
    fake_state.job_repo.active = [
        _build_job(id="job-1", owner_user_id="user-1", target="othercust1"),
        _build_job(id="job-2", owner_user_id="user-1", target="othercust2"),
    ]

    response = _post_json(client, "/api/jobs", {
        "user": "Jane.Doe",
        "customer": "Acme",
        "backup_path": "s3://test-bucket/backups/acme/20260103.tar"
    })

    assert response.status_code == 201


def test_submit_job_respects_global_limit(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Global limit should block new jobs when system is at capacity."""
    # Set global limit to 5
    fake_state.settings_repo.settings["max_active_jobs_per_user"] = "0"
    fake_state.settings_repo.settings["max_active_jobs_global"] = "5"

    # Add 5 existing active jobs (across different users, with different targets)
    fake_state.job_repo.active = [
        _build_job(id="job-1", owner_user_id="user-1", target="othercust1"),
        _build_job(id="job-2", owner_user_id="user-2", target="othercust2"),
        _build_job(id="job-3", owner_user_id="user-3", target="othercust3"),
        _build_job(id="job-4", owner_user_id="user-4", target="othercust4"),
        _build_job(id="job-5", owner_user_id="user-5", target="othercust5"),
    ]

    response = _post_json(client, "/api/jobs", {
        "user": "Jane.Doe",
        "customer": "Acme",
        "backup_path": "s3://test-bucket/backups/acme/20260103.tar"
    })

    assert response.status_code == 429
    data = cast(dict[str, Any], response.json())
    assert "System at capacity" in data["detail"]
    assert "5 active jobs" in data["detail"]


def test_submit_job_global_limit_takes_precedence(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Global limit should be checked before per-user limit."""
    # Set both limits
    fake_state.settings_repo.settings["max_active_jobs_per_user"] = "10"
    fake_state.settings_repo.settings["max_active_jobs_global"] = "3"

    # Add 3 active jobs (user has 0, so under per-user limit, but at global limit)
    fake_state.job_repo.active = [
        _build_job(id="job-1", owner_user_id="other-user-1", target="othercust1"),
        _build_job(id="job-2", owner_user_id="other-user-2", target="othercust2"),
        _build_job(id="job-3", owner_user_id="other-user-3", target="othercust3"),
    ]

    response = _post_json(client, "/api/jobs", {
        "user": "Jane.Doe",
        "customer": "Acme",
        "backup_path": "s3://test-bucket/backups/acme/20260103.tar"
    })

    assert response.status_code == 429
    data = cast(dict[str, Any], response.json())
    assert "System at capacity" in data["detail"]


def test_submit_job_both_limits_satisfied(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Job should be accepted when both limits have headroom."""
    # Set both limits
    fake_state.settings_repo.settings["max_active_jobs_per_user"] = "3"
    fake_state.settings_repo.settings["max_active_jobs_global"] = "10"

    # Add 4 active jobs (1 for current user, 3 for others, with different targets)
    fake_state.job_repo.active = [
        _build_job(id="job-1", owner_user_id="user-1", target="othercust1"),  # Current user's job
        _build_job(id="job-2", owner_user_id="other-user", target="othercust2"),
        _build_job(id="job-3", owner_user_id="other-user", target="othercust3"),
        _build_job(id="job-4", owner_user_id="other-user", target="othercust4"),
    ]

    response = _post_json(client, "/api/jobs", {
        "user": "Jane.Doe",
        "customer": "Acme",
        "backup_path": "s3://test-bucket/backups/acme/20260103.tar"
    })

    # Under both limits (user: 1 < 3, global: 4 < 10)
    assert response.status_code == 201


# --- Route Ordering Tests ---
# These tests verify that specific routes like /api/jobs/my-last are not
# captured by the generic /api/jobs/{job_id} route due to incorrect ordering.


def test_my_last_route_not_captured_by_job_id(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Verify /api/jobs/my-last is not captured by /api/jobs/{job_id}.

    If route ordering is wrong, the generic {job_id} route will match first
    and return 404 'Job my-last not found' instead of proper my-last response.
    """
    # Add a job for the user so my-last has something to return
    job = _build_job(id="job-1", owner_user_code="janedo")
    fake_state.job_repo.enqueued.append(job)

    # Mock get_last_job_by_user_code method that the endpoint uses
    def get_last_job_by_user_code(user_code: str) -> Job | None:
        for j in fake_state.job_repo.enqueued:
            if j.owner_user_code == user_code:
                return j
        return None

    fake_state.job_repo.get_last_job_by_user_code = get_last_job_by_user_code  # type: ignore[attr-defined]

    # /api/jobs/my-last requires user_code query param
    response = client.get("/api/jobs/my-last", params={"user_code": "janedo"})

    # Should NOT be 404 with "Job my-last not found"
    if response.status_code == 404:
        data = response.json()
        assert "Job my-last not found" not in data.get("detail", ""), (
            "Route ordering bug: /api/jobs/{job_id} is capturing /api/jobs/my-last. "
            "The generic {job_id} route must be defined AFTER all specific routes."
        )
    # 200 is expected (returns job), 404 is acceptable if no job found
    assert response.status_code in (200, 404)


def test_history_route_not_captured_by_job_id(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Verify /api/jobs/history is not captured by /api/jobs/{job_id}.

    If route ordering is wrong, the generic {job_id} route will match first
    and return 404 'Job history not found' instead of proper history response.
    """
    # Mock get_job_history method
    fake_state.job_repo.get_job_history = lambda **kwargs: []  # type: ignore[attr-defined]

    response = client.get("/api/jobs/history")

    # Should NOT be 404 with "Job history not found"
    if response.status_code == 404:
        data = response.json()
        assert "Job history not found" not in data.get("detail", ""), (
            "Route ordering bug: /api/jobs/{job_id} is capturing /api/jobs/history. "
            "The generic {job_id} route must be defined AFTER all specific routes."
        )
    # 200 is expected (returns empty list)
    assert response.status_code == 200


def test_get_single_job_still_works(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Verify /api/jobs/{job_id} works correctly for actual job IDs."""
    # Add a job
    job = _build_job(id="job-abc123")
    fake_state.job_repo.enqueued.append(job)

    response = client.get("/api/jobs/job-abc123")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "job-abc123"
    assert data["target"] == "janedoacme"


def test_get_single_job_returns_404_for_unknown(
    client: TestClient, fake_state: FakeRepos
) -> None:
    """Verify /api/jobs/{job_id} returns 404 for non-existent jobs."""
    response = client.get("/api/jobs/nonexistent-job-id")

    assert response.status_code == 404
    data = response.json()
    assert "Job nonexistent-job-id not found" in data["detail"]
