"""Tests for the `pulldb status` command.

Covers:
- No active jobs (empty state message)
- Active jobs table output (queued + running)
- Limit option truncation
- JSON output structure
- Wide output includes staging_name

We avoid real MySQL by monkeypatching JobRepository usage in CLI entrypoint.
"""

from __future__ import annotations

import json
import typing as t
from dataclasses import dataclass
from datetime import datetime

from click.testing import CliRunner

from pulldb.cli.main import cli
from pulldb.domain.models import Job, JobStatus


@dataclass
class _FakeJob:
    id: str
    target: str
    status: JobStatus
    owner_user_code: str
    submitted_at: datetime
    started_at: datetime | None = None
    staging_name: str | None = None


class _FakeRepo:
    def __init__(self, jobs: list[_FakeJob]):
        self._jobs = jobs

    def get_active_jobs(self) -> list[Job]:
        # Cast fake jobs to Job interface expected by CLI
        return t.cast(list[Job], self._jobs)


def _patch_repos(monkeypatch: t.Any, jobs: list[_FakeJob]) -> None:
    """Patch CLI dependencies to use in-memory fakes.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        jobs: Fake job list to be returned by repository.
    """
    # Patch build_default_pool to avoid real connection attempts
    monkeypatch.setattr("pulldb.cli.main.build_default_pool", lambda **_: None)
    # Patch JobRepository to our fake
    monkeypatch.setattr("pulldb.cli.main.JobRepository", lambda _: _FakeRepo(jobs))

    # Patch Config.minimal_from_env to avoid env dependency
    def _fake_config(_cls: t.Any) -> t.Any:
        return type(
            "_C",
            (),
            {
                "mysql_host": "h",
                "mysql_user": "u",
                "mysql_password": "p",
                "mysql_database": "d",
            },
        )()

    monkeypatch.setattr(
        "pulldb.cli.main.Config.minimal_from_env", classmethod(_fake_config)
    )


def test_status_no_active_jobs(monkeypatch: t.Any) -> None:
    """Empty state message when no active jobs present."""
    _patch_repos(monkeypatch, [])
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "No active jobs" in result.output


def test_status_active_jobs_table(monkeypatch: t.Any) -> None:
    """Table output with two jobs (queued + running)."""
    jobs = [
        _FakeJob(
            id="11111111-aaaa-bbbb-cccc-000000000001",
            target="abcdeftenant",
            status=JobStatus.QUEUED,
            owner_user_code="abcdef",
            submitted_at=datetime(2025, 11, 3, 12, 0, 0),
            staging_name="abcdeftenant_11111111aaaa",
        ),
        _FakeJob(
            id="22222222-bbbb-cccc-dddd-000000000002",
            target="xyzcorp",
            status=JobStatus.RUNNING,
            owner_user_code="xyzabc",
            submitted_at=datetime(2025, 11, 3, 12, 5, 0),
            started_at=datetime(2025, 11, 3, 12, 5, 5),
            staging_name="xyzcorp_22222222bbbb",
        ),
    ]
    _patch_repos(monkeypatch, jobs)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--limit", "10"])
    assert result.exit_code == 0
    # Header
    assert "STATUS" in result.output
    # Job IDs truncated
    assert "11111111" in result.output
    assert "22222222" in result.output
    # Status values
    assert "queued" in result.output
    assert "running" in result.output
    # Staging omitted (not wide)
    assert "abcdeftenant_11111111aaaa" not in result.output


def test_status_wide(monkeypatch: t.Any) -> None:
    """Wide output includes staging column."""
    jobs = [
        _FakeJob(
            id="33333333-aaaa-bbbb-cccc-000000000003",
            target="longtargettenant",
            status=JobStatus.QUEUED,
            owner_user_code="aaaaaa",
            submitted_at=datetime(2025, 11, 3, 13, 0, 0),
            staging_name="longtargettenant_33333333aaaa",
        ),
    ]
    _patch_repos(monkeypatch, jobs)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--wide"])
    assert result.exit_code == 0
    assert "STAGING" in result.output
    assert "longtargettenant_33333333aaaa" in result.output


def test_status_json(monkeypatch: t.Any) -> None:
    """JSON output mode returns structured list."""
    jobs = [
        _FakeJob(
            id="44444444-aaaa-bbbb-cccc-000000000004",
            target="demo",
            status=JobStatus.QUEUED,
            owner_user_code="demouc",
            submitted_at=datetime(2025, 11, 3, 14, 0, 0),
            staging_name="demo_44444444aaaa",
        )
    ]
    _patch_repos(monkeypatch, jobs)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--json", "--wide"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert isinstance(parsed, list)
    assert parsed[0]["id"].startswith("44444444")
    assert parsed[0]["status"] == "queued"
    assert parsed[0]["staging_name"] == "demo_44444444aaaa"


def test_status_limit(monkeypatch: t.Any) -> None:
    """Limit parameter truncates results."""
    jobs = []
    for i in range(5):
        jobs.append(
            _FakeJob(
                id=f"55555555-aaaa-bbbb-cccc-00000000000{i}",
                target=f"t{i}",
                status=JobStatus.QUEUED,
                owner_user_code="limituc",
                submitted_at=datetime(2025, 11, 3, 15, 0, i),
                staging_name=f"t{i}_55555555aaaa",
            )
        )
    _patch_repos(monkeypatch, jobs)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--limit", "3", "--json"])
    parsed = json.loads(result.output)
    assert len(parsed) == 3
    assert parsed[0]["id"].startswith("55555555")
