"""Tests for overlord companies routes and helpers.

Phase 7b: Tests for the extracted overlord_routes.py module covering:
- _text_filter_match with wildcards
- _enrich_companies_with_tracking enrichment logic
- API route response structure

Test Count: 12 tests
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pulldb.web.features.admin.overlord_routes import (
    _enrich_companies_with_tracking,
    _text_filter_match,
)


# ===========================================================================
# _text_filter_match tests
# ===========================================================================


class TestTextFilterMatch:
    """Tests for wildcard text filter matching."""

    def test_plain_substring_match(self) -> None:
        """Plain value matches as substring."""
        assert _text_filter_match("test_database", ["test"]) is True

    def test_plain_substring_no_match(self) -> None:
        """Plain value that is not a substring returns False."""
        assert _text_filter_match("production_db", ["test"]) is False

    def test_wildcard_prefix(self) -> None:
        """test* matches 'test_db' but not 'my_test'."""
        assert _text_filter_match("test_db", ["test*"]) is True
        assert _text_filter_match("my_test", ["test*"]) is False

    def test_wildcard_suffix(self) -> None:
        """*test matches 'my_test' but not 'test_db'."""
        assert _text_filter_match("my_test", ["*test"]) is True
        assert _text_filter_match("test_db", ["*test"]) is False

    def test_wildcard_both(self) -> None:
        """*test* matches any string containing 'test'."""
        assert _text_filter_match("my_test_db", ["*test*"]) is True
        assert _text_filter_match("production", ["*test*"]) is False

    def test_multiple_values_any_match(self) -> None:
        """Returns True if any value matches."""
        assert _text_filter_match("production_db", ["test", "prod"]) is True

    def test_empty_values_no_match(self) -> None:
        """Empty values list returns False."""
        assert _text_filter_match("anything", []) is False


# ===========================================================================
# _enrich_companies_with_tracking tests
# ===========================================================================


class TestEnrichCompaniesWithTracking:
    """Tests for company enrichment with local tracking data."""

    def _make_tracking(
        self,
        database_name: str,
        status: str = "claimed",
        job_id: str | None = "job-123",
        created_by: str | None = "admin",
        row_existed_before: bool = True,
    ) -> MagicMock:
        """Create a mock tracking record."""
        t = MagicMock()
        t.database_name = database_name
        t.status = MagicMock(value=status)
        t.job_id = job_id
        t.created_by = created_by
        t.id = 1
        t.row_existed_before = row_existed_before
        return t

    def test_unmanaged_company(self) -> None:
        """Company with no tracking record gets _managed=False."""
        tracking_repo = MagicMock()
        tracking_repo.list_active.return_value = []

        companies = [{"database": "db1"}]
        result = _enrich_companies_with_tracking(companies, tracking_repo)

        assert result[0]["_managed"] is False
        assert result[0]["_tracking_status"] is None
        assert result[0]["_job_id"] is None

    def test_managed_company(self) -> None:
        """Company with tracking record gets _managed=True and enriched fields."""
        tracking = self._make_tracking("db1", status="claimed", job_id="job-123")
        tracking_repo = MagicMock()
        tracking_repo.list_active.return_value = [tracking]

        companies = [{"database": "db1"}]
        result = _enrich_companies_with_tracking(companies, tracking_repo)

        assert result[0]["_managed"] is True
        assert result[0]["_tracking_status"] == "claimed"
        assert result[0]["_job_id"] == "job-123"
        assert result[0]["_managed_by"] == "admin"

    def test_mixed_companies(self) -> None:
        """Mixed managed/unmanaged companies enriched correctly."""
        tracking = self._make_tracking("db2")
        tracking_repo = MagicMock()
        tracking_repo.list_active.return_value = [tracking]

        companies = [{"database": "db1"}, {"database": "db2"}]
        result = _enrich_companies_with_tracking(companies, tracking_repo)

        assert result[0]["_managed"] is False
        assert result[1]["_managed"] is True

    def test_user_code_from_job(self) -> None:
        """_user_code resolved from linked job when job_repo provided."""
        tracking = self._make_tracking("db1", job_id="job-abc")
        tracking_repo = MagicMock()
        tracking_repo.list_active.return_value = [tracking]

        job = MagicMock()
        job.owner_user_code = "usrx"
        job_repo = MagicMock()
        job_repo.get_job_by_id.return_value = job

        companies = [{"database": "db1"}]
        result = _enrich_companies_with_tracking(
            companies, tracking_repo, job_repo=job_repo
        )

        assert result[0]["_user_code"] == "usrx"

    def test_none_tracking_repo(self) -> None:
        """When tracking_repo is None, all companies are unmanaged."""
        companies = [{"database": "db1"}]
        result = _enrich_companies_with_tracking(companies, None)

        assert result[0]["_managed"] is False
