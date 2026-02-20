"""Unit tests for date mode filtering in _process_backup_key.

Tests the 4 date filter modes: on_or_after, on_or_before, on_date, between.
These modes were introduced to allow flexible backup date selection on the
restore page instead of the original on_or_after-only filter.

HCA Layer: tests
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from pulldb.worker.discovery import (
    BackupInfo,
    DiscoveryService,
    SearchContext,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> DiscoveryService:
    """Create a DiscoveryService instance."""
    return DiscoveryService()


def _make_ctx(
    filter_date: datetime | None = None,
    filter_date_to: datetime | None = None,
    date_mode: str = "on_or_after",
) -> SearchContext:
    """Build a SearchContext with mock S3 and only the date fields set."""
    return SearchContext(
        s3=MagicMock(),
        bucket="test-bucket",
        prefix="daily/prod/",
        profile=None,
        env_name="prod",
        filter_date=filter_date,
        filter_date_to=filter_date_to,
        date_mode=date_mode,
    )


def _make_key(customer: str, ts: datetime) -> str:
    """Generate a valid backup S3 key for the given timestamp."""
    ts_str = ts.strftime("%Y-%m-%dT%H-%M-%SZ")
    day_abbr = ts.strftime("%a")
    return (
        f"daily/prod/{customer}/"
        f"daily_mydumper_{customer}_{ts_str}_{day_abbr}_dbimp.tar"
    )


def _process(
    service: DiscoveryService,
    ctx: SearchContext,
    ts: datetime,
    customer: str = "acme",
) -> list[BackupInfo]:
    """Run _process_backup_key and return the accumulated results list."""
    results: list[BackupInfo] = []
    key = _make_key(customer, ts)
    service._process_backup_key(ctx, key, customer, 1024 * 1024 * 500, results)
    return results


# ---------------------------------------------------------------------------
# No filter (filter_date is None)
# ---------------------------------------------------------------------------


class TestNoFilter:
    """When filter_date is None, all backups should be accepted."""

    def test_no_filter_accepts_any_date(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(filter_date=None)
        ts = datetime(2020, 1, 15, 10, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1
        assert results[0].timestamp == ts


# ---------------------------------------------------------------------------
# on_or_after mode
# ---------------------------------------------------------------------------


class TestOnOrAfter:
    """on_or_after: include backups where ts >= filter_date."""

    def test_backup_after_filter_date_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            date_mode="on_or_after",
        )
        ts = datetime(2026, 2, 5, 12, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_on_filter_date_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            date_mode="on_or_after",
        )
        ts = datetime(2026, 2, 1, 0, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_before_filter_date_excluded(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            date_mode="on_or_after",
        )
        ts = datetime(2026, 1, 31, 23, 59, 59)
        results = _process(service, ctx, ts)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# on_or_before mode
# ---------------------------------------------------------------------------


class TestOnOrBefore:
    """on_or_before: include backups where ts <= end-of-day(filter_date)."""

    def test_backup_before_filter_date_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_or_before",
        )
        ts = datetime(2026, 2, 5, 12, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_on_filter_date_end_of_day_included(self, service: DiscoveryService) -> None:
        """Backup at 23:59:59 on the filter date should be included."""
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_or_before",
        )
        ts = datetime(2026, 2, 10, 23, 59, 59)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_after_filter_date_excluded(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_or_before",
        )
        ts = datetime(2026, 2, 11, 0, 0, 1)
        results = _process(service, ctx, ts)
        assert len(results) == 0

    def test_backup_on_filter_date_morning_included(self, service: DiscoveryService) -> None:
        """Backup early on the filter date should be included."""
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_or_before",
        )
        ts = datetime(2026, 2, 10, 6, 30, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# on_date mode
# ---------------------------------------------------------------------------


class TestOnDate:
    """on_date: include only backups where ts.date() == filter_date.date()."""

    def test_backup_on_exact_date_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_date",
        )
        ts = datetime(2026, 2, 10, 14, 30, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_day_before_excluded(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_date",
        )
        ts = datetime(2026, 2, 9, 23, 59, 59)
        results = _process(service, ctx, ts)
        assert len(results) == 0

    def test_backup_day_after_excluded(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_date",
        )
        ts = datetime(2026, 2, 11, 0, 0, 1)
        results = _process(service, ctx, ts)
        assert len(results) == 0

    def test_backup_at_midnight_included(self, service: DiscoveryService) -> None:
        """Exact midnight on the date should be included."""
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_date",
        )
        ts = datetime(2026, 2, 10, 0, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_at_end_of_day_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
            date_mode="on_date",
        )
        ts = datetime(2026, 2, 10, 23, 59, 59)
        results = _process(service, ctx, ts)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# between mode
# ---------------------------------------------------------------------------


class TestBetween:
    """between: include backups where filter_date <= ts <= filter_date_to."""

    def test_backup_within_range_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            filter_date_to=datetime(2026, 2, 10, 23, 59, 59),
            date_mode="between",
        )
        ts = datetime(2026, 2, 5, 12, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_at_range_start_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            filter_date_to=datetime(2026, 2, 10, 23, 59, 59),
            date_mode="between",
        )
        ts = datetime(2026, 2, 1, 0, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_at_range_end_included(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            filter_date_to=datetime(2026, 2, 10, 23, 59, 59),
            date_mode="between",
        )
        ts = datetime(2026, 2, 10, 23, 59, 59)
        results = _process(service, ctx, ts)
        assert len(results) == 1

    def test_backup_before_range_excluded(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            filter_date_to=datetime(2026, 2, 10, 23, 59, 59),
            date_mode="between",
        )
        ts = datetime(2026, 1, 31, 23, 59, 59)
        results = _process(service, ctx, ts)
        assert len(results) == 0

    def test_backup_after_range_excluded(self, service: DiscoveryService) -> None:
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            filter_date_to=datetime(2026, 2, 10, 23, 59, 59),
            date_mode="between",
        )
        ts = datetime(2026, 2, 11, 0, 0, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 0

    def test_between_without_date_to_degrades_to_on_or_after(
        self, service: DiscoveryService
    ) -> None:
        """When between mode has no filter_date_to, upper bound is not enforced.

        This is the current behavior — a future improvement could require
        date_to for between mode, but for now we verify the degradation.
        """
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            filter_date_to=None,
            date_mode="between",
        )
        # Far future date should still be included (no upper bound)
        ts = datetime(2030, 12, 31, 23, 59, 59)
        results = _process(service, ctx, ts)
        assert len(results) == 1

        # But dates before filter_date are still excluded
        ts_old = datetime(2026, 1, 31, 0, 0, 0)
        results_old = _process(service, ctx, ts_old)
        assert len(results_old) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for date filtering."""

    def test_invalid_key_format_skipped(self, service: DiscoveryService) -> None:
        """Keys that don't match BACKUP_FILENAME_REGEX are skipped."""
        ctx = _make_ctx(filter_date=None)
        results: list[BackupInfo] = []
        service._process_backup_key(ctx, "invalid/key/name.txt", "acme", 1024, results)
        assert len(results) == 0

    def test_unknown_mode_accepts_all(self, service: DiscoveryService) -> None:
        """An unknown date_mode should not filter anything (no branch matches)."""
        ctx = _make_ctx(
            filter_date=datetime(2026, 2, 1, 0, 0, 0),
            date_mode="unknown_mode",
        )
        ts = datetime(2020, 1, 1, 0, 0, 0)
        results = _process(service, ctx, ts)
        # No branch matches the mode, so the backup is NOT filtered out
        assert len(results) == 1

    def test_result_fields_populated_correctly(self, service: DiscoveryService) -> None:
        """Verify BackupInfo fields are set correctly."""
        ctx = _make_ctx(filter_date=None)
        ts = datetime(2026, 2, 10, 14, 30, 0)
        results = _process(service, ctx, ts)
        assert len(results) == 1
        info = results[0]
        assert info.customer == "acme"
        assert info.timestamp == ts
        assert info.date == "20260210"
        assert info.environment == "prod"
        assert info.bucket == "test-bucket"
        assert info.size_mb == 500.0
        assert "MB" in info.size_display


# ---------------------------------------------------------------------------
# Simulation mode date filtering
# ---------------------------------------------------------------------------


class TestSimulationDateFiltering:
    """Simulation mode should respect date_mode and date_to params."""

    def test_simulation_on_or_after_filters_old(self, service: DiscoveryService) -> None:
        result = service._search_backups_simulation(
            customer="testcust",
            environment="both",
            limit=100,
            offset=0,
            date_mode="on_or_after",
            filter_date=datetime(2026, 2, 10, 0, 0, 0),
        )
        for b in result.backups:
            assert b.timestamp >= datetime(2026, 2, 10, 0, 0, 0)

    def test_simulation_on_or_before_filters_new(self, service: DiscoveryService) -> None:
        result = service._search_backups_simulation(
            customer="testcust",
            environment="both",
            limit=100,
            offset=0,
            date_mode="on_or_before",
            filter_date=datetime(2026, 2, 5, 0, 0, 0),
        )
        for b in result.backups:
            assert b.timestamp.date() <= datetime(2026, 2, 5).date()

    def test_simulation_on_date_filters_exact(self, service: DiscoveryService) -> None:
        target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = service._search_backups_simulation(
            customer="testcust",
            environment="both",
            limit=100,
            offset=0,
            date_mode="on_date",
            filter_date=target_date,
        )
        for b in result.backups:
            assert b.timestamp.date() == target_date.date()

    def test_simulation_between_filters_range(self, service: DiscoveryService) -> None:
        from_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        to_date = from_date  # Same day — should only get today's backup
        result = service._search_backups_simulation(
            customer="testcust",
            environment="both",
            limit=100,
            offset=0,
            date_mode="between",
            filter_date=from_date,
            filter_date_to=to_date.replace(hour=23, minute=59, second=59),
        )
        for b in result.backups:
            assert b.timestamp >= from_date
            assert b.timestamp <= to_date.replace(hour=23, minute=59, second=59)

    def test_simulation_no_filter_returns_all(self, service: DiscoveryService) -> None:
        result = service._search_backups_simulation(
            customer="testcust",
            environment="both",
            limit=100,
            offset=0,
        )
        # Without filter, should return all 20 mock backups (both envs)
        assert result.total == 20
