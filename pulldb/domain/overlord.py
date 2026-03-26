"""Overlord domain models and error hierarchy.

HCA Layer: entities (pulldb/domain/)

These models represent overlord.companies integration concepts:
- OverlordTracking: local tracking of pullDB ownership
- OverlordCompany: row from the external overlord.companies table
- OverlordTrackingStatus: lifecycle states for tracking records
- OverlordError hierarchy: typed errors for overlord operations

Relocated from pulldb/infra/overlord.py to establish correct semantic
ownership — these are entity-level concepts, not infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


# =============================================================================
# Domain Models
# =============================================================================


class OverlordTrackingStatus(str, Enum):
    """Status of overlord tracking record."""

    CLAIMED = "claimed"    # Record created, backup taken, not yet synced
    SYNCED = "synced"      # Changes written to overlord.companies
    RELEASED = "released"  # pullDB no longer managing this row


@dataclass
class OverlordTracking:
    """Local tracking record for overlord.companies management."""

    id: int
    database_name: str
    company_id: int | None
    job_id: str
    job_target: str
    created_by: str
    status: OverlordTrackingStatus
    row_existed_before: bool
    previous_dbhost: str | None
    previous_dbhost_read: str | None
    previous_snapshot: dict[str, Any] | None
    current_dbhost: str | None
    current_dbhost_read: str | None
    current_subdomain: str | None
    created_at: datetime | None
    updated_at: datetime | None
    released_at: datetime | None


@dataclass
class OverlordCompany:
    """Row from overlord.companies table.

    Note: This adapts to the actual schema of the external companies table.
    We read whatever columns exist and provide safe defaults for optional ones.
    The actual schema has: companyID, company, owner, brandingPrefix, brandingLogo, database
    """

    company_id: int
    database: str
    # Core fields from actual schema
    company_name: str | None = None  # 'company' column
    owner: str | None = None
    branding_prefix: str | None = None
    branding_logo: int | None = None
    # Extended fields (may not exist in all installations)
    db_host: str | None = None
    db_host_read: str | None = None
    subdomain: str | None = None
    visible: int | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> OverlordCompany:
        """Create from database row.

        Handles varying schemas by using .get() for all optional fields.
        Only companyID is required.
        """
        company_id = row.get("companyID")
        if company_id is None:
            raise ValueError(f"Missing required field 'companyID' in overlord row: {list(row.keys())}")
        return cls(
            company_id=company_id,
            database=row.get("database", ""),
            company_name=row.get("company"),
            owner=row.get("owner"),
            branding_prefix=row.get("brandingPrefix"),
            branding_logo=row.get("brandingLogo"),
            # Extended fields - may not exist
            db_host=row.get("dbHost"),
            db_host_read=row.get("dbHostRead"),
            subdomain=row.get("subdomain"),
            visible=row.get("visible"),
        )

    @property
    def name(self) -> str:
        """Backward-compatible name property."""
        return self.company_name or self.database or f"Company #{self.company_id}"


# =============================================================================
# Errors
# =============================================================================


class OverlordError(Exception):
    """Base error for overlord operations."""
    pass


class OverlordConnectionError(OverlordError):
    """Failed to connect to overlord database."""
    pass


class OverlordOwnershipError(OverlordError):
    """Operation denied - no ownership of this database."""
    pass


class OverlordAlreadyClaimedError(OverlordError):
    """Database already claimed by another job."""
    pass


class OverlordSafetyError(OverlordError):
    """Safety check failed - operation aborted."""
    pass


class OverlordExternalChangeError(OverlordError):
    """External modification detected - row changed outside pullDB."""
    pass


class OverlordRowDeletedError(OverlordError):
    """Row no longer exists - was deleted externally."""
    pass
