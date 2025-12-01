"""
CLI Test Fixtures for pullDB QA Testing

Provides fixtures for:
- Click CLI testing via CliRunner
- API mocking with responses library
- Environment variable management
- Test data (job IDs, user codes, etc.)

Usage:
    pytest tests/qa/cli/ -v
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from typing import Any

import pytest
import responses
from click.testing import CliRunner

from pulldb.cli.main import cli  # noqa: F401 - Used in test files


# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

MOCK_API_BASE = "http://api.test"
SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"
SAMPLE_JOB_PREFIX = "75777a4c"
SAMPLE_USER_CODE = "charle"
SAMPLE_USERNAME = "charleshandshy"
SAMPLE_TARGET = "charleqatemplate"


# ---------------------------------------------------------------------------
# CLI Runner Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def isolated_runner() -> CliRunner:
    """Click CLI test runner with isolated filesystem."""
    return CliRunner()


# ---------------------------------------------------------------------------
# Environment Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_api_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set up mock API environment and return base URL."""
    monkeypatch.setenv("PULLDB_API_URL", MOCK_API_BASE)
    monkeypatch.setenv("PULLDB_API_TIMEOUT", "5")
    return MOCK_API_BASE


@pytest.fixture
def mock_user_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set up mock user environment and return username."""
    monkeypatch.setenv("USER", SAMPLE_USERNAME)
    monkeypatch.delenv("SUDO_USER", raising=False)
    return SAMPLE_USERNAME


@pytest.fixture
def mock_s3_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up S3 environment variables."""
    monkeypatch.setenv("PULLDB_S3ENV_DEFAULT", "both")
    monkeypatch.setenv("PULLDB_S3_AWS_PROFILE", "pr-staging")
    # Set backup locations for predictable test behavior
    locations = [
        {
            "name": "staging",
            "bucket_path": "s3://test-bucket-staging/daily/stg/",
            "profile": "pr-staging"
        },
        {
            "name": "prod",
            "bucket_path": "s3://test-bucket-prod/daily/prod/",
            "profile": "pr-prod"
        }
    ]
    monkeypatch.setenv("PULLDB_S3_BACKUP_LOCATIONS", json.dumps(locations))


# ---------------------------------------------------------------------------
# Sample Data Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_job_id() -> str:
    """Sample full job UUID."""
    return SAMPLE_JOB_ID


@pytest.fixture
def sample_job_prefix() -> str:
    """Sample 8-character job ID prefix."""
    return SAMPLE_JOB_PREFIX


@pytest.fixture
def sample_user_code() -> str:
    """Sample user code."""
    return SAMPLE_USER_CODE


@pytest.fixture
def sample_username() -> str:
    """Sample username."""
    return SAMPLE_USERNAME


@pytest.fixture
def sample_target() -> str:
    """Sample target database name."""
    return SAMPLE_TARGET


# ---------------------------------------------------------------------------
# API Response Builders
# ---------------------------------------------------------------------------

@pytest.fixture
def job_response_factory() -> Callable[..., dict[str, Any]]:
    """Factory for creating job response payloads."""
    def _create(
        job_id: str = SAMPLE_JOB_ID,
        target: str = SAMPLE_TARGET,
        status: str = "queued",
        user_code: str = SAMPLE_USER_CODE,
        staging_name: str | None = None,
        current_operation: str | None = None,
        submitted_at: str = "2025-11-29T02:08:40.322709",
        started_at: str | None = None,
        completed_at: str | None = None,
        dbhost: str = "localhost",
        source: str = "qatemplate",
        error_detail: str | None = None,
    ) -> dict[str, Any]:
        if staging_name is None:
            staging_name = f"{target}_{job_id[:8]}{job_id[9:13]}"
        return {
            "id": job_id,
            "target": target,
            "status": status,
            "user_code": user_code,
            "staging_name": staging_name,
            "current_operation": current_operation,
            "submitted_at": submitted_at,
            "started_at": started_at,
            "completed_at": completed_at,
            "dbhost": dbhost,
            "source": source,
            "error_detail": error_detail,
        }
    return _create


@pytest.fixture
def job_submit_response_factory() -> Callable[..., dict[str, Any]]:
    """Factory for creating job submission response payloads."""
    def _create(
        job_id: str = SAMPLE_JOB_ID,
        target: str = SAMPLE_TARGET,
        status: str = "queued",
        owner_username: str = SAMPLE_USERNAME,
        owner_user_code: str = SAMPLE_USER_CODE,
    ) -> dict[str, Any]:
        staging_name = f"{target}_{job_id[:8]}{job_id[9:13]}"
        return {
            "job_id": job_id,
            "target": target,
            "staging_name": staging_name,
            "status": status,
            "owner_username": owner_username,
            "owner_user_code": owner_user_code,
            "submitted_at": "2025-11-29T02:08:40.322709",
        }
    return _create


@pytest.fixture
def event_response_factory() -> Callable[..., dict[str, Any]]:
    """Factory for creating event response payloads."""
    def _create(
        event_id: int = 1,
        job_id: str = SAMPLE_JOB_ID,
        event_type: str = "running",
        detail: str = "Job started",
        logged_at: str = "2025-11-29T02:09:09.169206",
    ) -> dict[str, Any]:
        return {
            "id": event_id,
            "job_id": job_id,
            "event_type": event_type,
            "detail": detail,
            "logged_at": logged_at,
        }
    return _create


@pytest.fixture
def profile_response_factory() -> Callable[..., dict[str, Any]]:
    """Factory for creating profile response payloads."""
    def _create(
        job_id: str = SAMPLE_JOB_ID,
        total_duration: float = 52.99,
        total_bytes: int = 5468160,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "started_at": "2025-11-29T02:09:09.177102+00:00",
            "completed_at": "2025-11-29T02:10:02.168929+00:00",
            "total_duration_seconds": total_duration,
            "total_bytes": total_bytes,
            "phases": {
                "discovery": {
                    "phase": "discovery",
                    "duration_seconds": 0.164,
                    "bytes_processed": None,
                    "mbps": None,
                },
                "download": {
                    "phase": "download",
                    "duration_seconds": 0.355,
                    "bytes_processed": 2734080,
                    "mbps": 7.35,
                },
                "extraction": {
                    "phase": "extraction",
                    "duration_seconds": 0.238,
                    "bytes_processed": 2734080,
                    "mbps": 10.98,
                },
            },
            "phase_breakdown_percent": {
                "discovery": 0.3,
                "download": 0.7,
                "extraction": 0.4,
            },
            "error": error,
        }
    return _create


@pytest.fixture
def history_item_factory() -> Callable[..., dict[str, Any]]:
    """Factory for creating history item payloads."""
    def _create(
        job_id: str = SAMPLE_JOB_ID,
        target: str = SAMPLE_TARGET,
        status: str = "complete",
        user_code: str = SAMPLE_USER_CODE,
        duration_seconds: float = 53.17,
        error_detail: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": job_id,
            "target": target,
            "status": status,
            "user_code": user_code,
            "owner_username": SAMPLE_USERNAME,
            "submitted_at": "2025-11-29T02:08:40.322709",
            "started_at": "2025-11-29T02:09:09.105710",
            "completed_at": "2025-11-29T02:10:02.277049",
            "duration_seconds": duration_seconds,
            "staging_name": f"{target}_{job_id[:12]}",
            "dbhost": "localhost",
            "source": "qatemplate",
            "error_detail": error_detail,
            "retry_count": 0,
        }
    return _create


# ---------------------------------------------------------------------------
# Mocked API Setup Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_api_responses() -> Generator[responses.RequestsMock, None, None]:
    """Context manager for mocking API responses."""
    with responses.RequestsMock() as rsps:
        yield rsps


def add_user_lookup(rsps: responses.RequestsMock, base_url: str, 
                    username: str = SAMPLE_USERNAME,
                    user_code: str = SAMPLE_USER_CODE) -> None:
    """Add user lookup endpoint mock."""
    rsps.add(
        responses.GET,
        f"{base_url}/api/users/{username}",
        json={"username": username, "user_code": user_code, "is_admin": False},
        status=200,
    )


def add_job_resolve(rsps: responses.RequestsMock, base_url: str,
                    prefix: str = SAMPLE_JOB_PREFIX,
                    job_id: str = SAMPLE_JOB_ID,
                    count: int = 1) -> None:
    """Add job ID resolution endpoint mock."""
    rsps.add(
        responses.GET,
        f"{base_url}/api/jobs/resolve/{prefix}",
        json={
            "resolved_id": job_id if count == 1 else None,
            "matches": [{"id": job_id, "target": SAMPLE_TARGET, 
                        "status": "complete", "user_code": SAMPLE_USER_CODE,
                        "submitted_at": "2025-11-29T02:08:40"}],
            "count": count,
        },
        status=200,
    )


def add_job_resolve_not_found(rsps: responses.RequestsMock, base_url: str,
                               prefix: str) -> None:
    """Add job ID resolution 404 mock."""
    rsps.add(
        responses.GET,
        f"{base_url}/api/jobs/resolve/{prefix}",
        json={"detail": "No job found matching prefix"},
        status=404,
    )


# ---------------------------------------------------------------------------
# Assertion Helpers
# ---------------------------------------------------------------------------

def assert_success(result) -> None:
    """Assert CLI command succeeded."""
    assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}\nOutput: {result.output}\nException: {result.exception}"


def assert_error(result, exit_code: int = 1) -> None:
    """Assert CLI command failed with expected exit code."""
    assert result.exit_code == exit_code, f"Expected exit code {exit_code}, got {result.exit_code}\nOutput: {result.output}"


def assert_contains(result, *texts: str) -> None:
    """Assert output contains all specified texts."""
    for text in texts:
        assert text in result.output, f"Expected '{text}' in output:\n{result.output}"


def assert_not_contains(result, *texts: str) -> None:
    """Assert output does not contain any specified texts."""
    for text in texts:
        assert text not in result.output, f"Did not expect '{text}' in output:\n{result.output}"


def assert_valid_json(result) -> Any:
    """Assert output is valid JSON and return parsed data."""
    try:
        return json.loads(result.output.strip())
    except json.JSONDecodeError as e:
        pytest.fail(f"Invalid JSON output: {e}\nOutput: {result.output}")
