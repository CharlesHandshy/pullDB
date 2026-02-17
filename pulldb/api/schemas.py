"""Pydantic models for pullDB API.

HCA Layer: pages
"""

from __future__ import annotations

from datetime import datetime

import pydantic

# JobRequest is now defined in the domain layer (entities) so it can be
# shared across pages-layer packages (api, web) without lateral imports.
# Re-exported here for backward compatibility.
from pulldb.domain.schemas import JobRequest as JobRequest  # noqa: F401 — re-export


class JobResponse(pydantic.BaseModel):
    """Response payload for successful job submission."""

    job_id: str
    target: str
    staging_name: str
    status: str
    owner_username: str
    owner_user_code: str
    submitted_at: datetime | None = None
    # Customer name normalization info (for long names)
    original_customer: str | None = None
    customer_normalized: bool = False
    normalization_message: str | None = None
    # Indicate if custom target was used
    custom_target_used: bool = False


class JobSummary(pydantic.BaseModel):
    """Summary view of a job for status listing."""

    id: str
    target: str
    status: str
    user_code: str
    owner_user_code: str | None = None  # For templates expecting this field name
    owner_user_id: str | None = None  # For authorization checks
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    staging_name: str | None = None
    current_operation: str | None = None
    dbhost: str | None = None
    source: str | None = None
    cancel_requested_at: datetime | None = None  # For strikethrough styling
    can_cancel: bool = False  # Computed per-user permission
    custom_target: bool = False  # Indicates custom target name was used


class JobHistoryItem(pydantic.BaseModel):
    """Detailed history item for completed/failed/canceled jobs."""

    id: str
    target: str
    status: str
    user_code: str
    owner_username: str
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    staging_name: str | None = None
    dbhost: str | None = None
    source: str | None = None
    error_detail: str | None = None
    retry_count: int = 0


class JobEventResponse(pydantic.BaseModel):
    """Job event payload."""

    id: int
    job_id: str
    event_type: str
    detail: str | None
    logged_at: datetime


class UserLastJobResponse(pydantic.BaseModel):
    """Response for user's last job lookup."""

    job_id: str | None = None
    target: str | None = None
    status: str | None = None
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_detail: str | None = None
    found: bool = False


class JobMatch(pydantic.BaseModel):
    """A job matching a prefix search."""

    id: str
    target: str
    status: str
    user_code: str
    submitted_at: datetime | None = None


class JobResolveResponse(pydantic.BaseModel):
    """Response for job ID prefix resolution."""

    resolved_id: str | None = pydantic.Field(
        None, description="Full job ID if exactly one match"
    )
    matches: list[JobMatch] = pydantic.Field(
        default_factory=list, description="List of matching jobs if multiple"
    )
    count: int = pydantic.Field(description="Number of matches found")
