"""Tests for the `pulldb restore` command rate limiting handling."""

from __future__ import annotations

"""HCA Layer: tests."""

import pytest
import responses
from click.testing import CliRunner

from pulldb.cli.main import cli


def _base_url(monkeypatch: pytest.MonkeyPatch) -> str:
    base = "http://api.test"
    monkeypatch.setenv("PULLDB_API_URL", base)
    monkeypatch.setenv("PULLDB_API_KEY", "test-key")
    monkeypatch.setenv("PULLDB_API_SECRET", "test-secret")
    return base


@responses.activate
def test_restore_rate_limit_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """User-friendly message when user hits per-user rate limit."""
    base = _base_url(monkeypatch)
    detail = (
        "User limit reached: you have 3 active jobs (limit: 3). "
        "Wait for jobs to complete or cancel one."
    )
    responses.add(
        responses.POST,
        f"{base}/api/jobs",
        json={"detail": detail},
        status=429,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["restore", "user=Jane.Doe", "customer=acme"])
    assert result.exit_code != 0
    assert "Rate limited" in result.output
    assert "User limit" in result.output
    assert "pulldb status" in result.output


@responses.activate
def test_restore_rate_limit_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """User-friendly message when system is at capacity."""
    base = _base_url(monkeypatch)
    detail = "System at capacity: 10 active jobs (limit: 10). Please try again later."
    responses.add(
        responses.POST,
        f"{base}/api/jobs",
        json={"detail": detail},
        status=429,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["restore", "user=Jane.Doe", "customer=acme"])
    assert result.exit_code != 0
    assert "Rate limited" in result.output
    assert "System at capacity" in result.output
    assert "try again" in result.output


@responses.activate
def test_restore_rate_limit_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic rate limit message when detail is missing."""
    base = _base_url(monkeypatch)
    responses.add(
        responses.POST,
        f"{base}/api/jobs",
        json={},
        status=429,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["restore", "user=Jane.Doe", "customer=acme"])
    assert result.exit_code != 0
    assert "Rate limited" in result.output
    assert "wait" in result.output.lower()


@responses.activate
def test_restore_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful restore returns job details."""
    base = _base_url(monkeypatch)
    responses.add(
        responses.POST,
        f"{base}/api/jobs",
        json={
            "job_id": "test-job-123",
            "target": "janedoacme",
            "staging_name": "janedoacme_testjob123",
            "status": "queued",
            "owner_username": "Jane.Doe",
            "owner_user_code": "janedo",
        },
        status=201,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["restore", "user=Jane.Doe", "customer=acme"])
    assert result.exit_code == 0
    assert "Job queued successfully" in result.output
    assert "janedoacme" in result.output
