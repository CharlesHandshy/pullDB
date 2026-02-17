"""Tests for overlord domain model relocation (Phase 4).

Phase 7d: Verify that domain models are importable from their new location
and that backward-compatible re-exports from infra/overlord.py still work.

Test Count: 6 tests
"""

from __future__ import annotations

import pytest


class TestDomainOverlordImports:
    """Verify domain/overlord.py exports work correctly."""

    def test_import_overlord_company(self) -> None:
        """OverlordCompany importable from domain.overlord."""
        from pulldb.domain.overlord import OverlordCompany
        assert OverlordCompany is not None

    def test_import_overlord_tracking(self) -> None:
        """OverlordTracking importable from domain.overlord."""
        from pulldb.domain.overlord import OverlordTracking
        assert OverlordTracking is not None

    def test_import_overlord_tracking_status(self) -> None:
        """OverlordTrackingStatus importable from domain.overlord."""
        from pulldb.domain.overlord import OverlordTrackingStatus
        assert OverlordTrackingStatus is not None

    def test_import_error_classes(self) -> None:
        """All error subclasses importable from domain.overlord."""
        from pulldb.domain.overlord import (
            OverlordError,
            OverlordConnectionError,
            OverlordOwnershipError,
            OverlordAlreadyClaimedError,
            OverlordSafetyError,
            OverlordExternalChangeError,
            OverlordRowDeletedError,
        )
        assert all(issubclass(cls, OverlordError) for cls in [
            OverlordConnectionError,
            OverlordOwnershipError,
            OverlordAlreadyClaimedError,
            OverlordSafetyError,
            OverlordExternalChangeError,
            OverlordRowDeletedError,
        ])

    def test_overlord_company_from_row(self) -> None:
        """OverlordCompany.from_row creates instance from dict."""
        from pulldb.domain.overlord import OverlordCompany

        row = {
            "companyID": 42,
            "database": "test_db",
            "subdomain": "test",
            "company": "Test Corp",
        }
        company = OverlordCompany.from_row(row)
        assert company.company_id == 42
        assert company.database == "test_db"
        assert company.subdomain == "test"
        assert company.company_name == "Test Corp"


class TestBackwardCompatReExports:
    """Verify infra/overlord.py re-exports still work."""

    def test_infra_overlord_exports_repository(self) -> None:
        """OverlordRepository importable from infra.overlord."""
        from pulldb.infra.overlord import OverlordRepository
        assert OverlordRepository is not None

    def test_infra_overlord_reexports_models(self) -> None:
        """Domain models re-exported from infra.overlord for backward compat."""
        from pulldb.infra.overlord import (
            OverlordCompany,
            OverlordTracking,
            OverlordTrackingStatus,
            OverlordError,
            OverlordConnectionError,
        )
        # Verify they're the same classes as domain
        from pulldb.domain.overlord import (
            OverlordCompany as DomainCompany,
            OverlordTracking as DomainTracking,
        )
        assert OverlordCompany is DomainCompany
        assert OverlordTracking is DomainTracking


class TestDomainPackageExports:
    """Verify domain/__init__.py re-exports."""

    def test_domain_init_exports_overlord(self) -> None:
        """Overlord models importable from pulldb.domain."""
        from pulldb.domain import (
            OverlordCompany,
            OverlordTracking,
            OverlordTrackingStatus,
            OverlordError,
            OverlordConnectionError,
        )
        assert OverlordCompany is not None
        assert OverlordTracking is not None
