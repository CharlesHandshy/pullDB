"""Tests for the `pulldb status` command routed through the API service."""

from __future__ import annotations

"""HCA Layer: tests."""

import json

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
def test_status_no_active_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty state message when no active jobs present."""
    base = _base_url(monkeypatch)
    responses.add(
        responses.GET,
        f"{base}/api/jobs",
        match=[responses.matchers.query_param_matcher({"limit": "100"})],
        json=[],
        status=200,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "No matching jobs found" in result.output


@responses.activate
def test_status_active_jobs_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """Table output displays active jobs with truncated identifiers."""
    base = _base_url(monkeypatch)
    payload = [
        {
            "id": "11111111-aaaa-bbbb-cccc-000000000001",
            "target": "abcdeftenant",
            "status": "queued",
            "user_code": "abcdef",
            "submitted_at": "2025-11-03T12:00:00+00:00",
            "staging_name": "abcdeftenant_11111111aaaa",
        },
        {
            "id": "22222222-bbbb-cccc-dddd-000000000002",
            "target": "xyzcorp",
            "status": "running",
            "user_code": "xyzabc",
            "submitted_at": "2025-11-03T12:05:00+00:00",
            "started_at": "2025-11-03T12:05:05+00:00",
            "staging_name": "xyzcorp_22222222bbbb",
        },
    ]
    responses.add(
        responses.GET,
        f"{base}/api/jobs",
        match=[responses.matchers.query_param_matcher({"limit": "10"})],
        json=payload,
        status=200,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--limit", "10"])
    assert result.exit_code == 0
    assert "STATUS" in result.output
    assert "11111111" in result.output
    assert "22222222" in result.output
    assert "queued" in result.output
    assert "running" in result.output
    assert "abcdeftenant_11111111aaaa" not in result.output


@responses.activate
def test_status_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wide output includes staging column from API payload."""
    base = _base_url(monkeypatch)
    payload = [
        {
            "id": "33333333-aaaa-bbbb-cccc-000000000003",
            "target": "longtargettenant",
            "status": "queued",
            "user_code": "aaaaaa",
            "submitted_at": "2025-11-03T13:00:00+00:00",
            "staging_name": "longtargettenant_33333333aaaa",
        }
    ]
    responses.add(
        responses.GET,
        f"{base}/api/jobs",
        match=[responses.matchers.query_param_matcher({"limit": "100"})],
        json=payload,
        status=200,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--wide"])
    assert result.exit_code == 0
    assert "STAGING" in result.output
    assert "longtargettenant_33333333aaaa" in result.output


@responses.activate
def test_status_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON output mirrors API payload (wide ignored)."""
    base = _base_url(monkeypatch)
    payload = [
        {
            "id": "44444444-aaaa-bbbb-cccc-000000000004",
            "target": "demo",
            "status": "queued",
            "user_code": "demouc",
            "submitted_at": "2025-11-03T14:00:00+00:00",
            "staging_name": "demo_44444444aaaa",
        }
    ]
    responses.add(
        responses.GET,
        f"{base}/api/jobs",
        match=[responses.matchers.query_param_matcher({"limit": "100"})],
        json=payload,
        status=200,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--json", "--wide"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert isinstance(parsed, list)
    assert parsed[0]["id"].startswith("44444444")
    assert parsed[0]["staging_name"] == "demo_44444444aaaa"


@responses.activate
def test_status_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Limit parameter truncates results before display."""
    base = _base_url(monkeypatch)
    payload = [
        {
            "id": f"55555555-aaaa-bbbb-cccc-00000000000{i}",
            "target": f"t{i}",
            "status": "queued",
            "user_code": "limituc",
            "submitted_at": f"2025-11-03T15:00:0{i}+00:00",
            "staging_name": f"t{i}_55555555aaaa",
        }
        for i in range(5)
    ]
    responses.add(
        responses.GET,
        f"{base}/api/jobs",
        match=[responses.matchers.query_param_matcher({"limit": "3"})],
        json=payload,
        status=200,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--limit", "3", "--json"])
    parsed = json.loads(result.output)
    assert len(parsed) == 3
    assert parsed[0]["id"].startswith("55555555")
