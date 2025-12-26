"""Pydantic models for pullDB API."""

from __future__ import annotations

from datetime import datetime

import pydantic


class JobRequest(pydantic.BaseModel):
    """Incoming job submission payload."""

    user: str = pydantic.Field(min_length=1)
    customer: str | None = None
    qatemplate: bool = False
    dbhost: str | None = None
    date: str | None = None  # Specific backup date in YYYY-MM-DD format
    env: str | None = None  # S3 environment: "staging" or "prod"
    overwrite: bool = False
    suffix: str | None = pydantic.Field(
        default=None,
        pattern=r"^[a-z]{1,3}$",
        description="Optional suffix for target database (1-3 lowercase letters)",
    )


class JobResponse(pydantic.BaseModel):
    """Response payload for successful job submission."""

    job_id: str
    target: str
    staging_name: str
    status: str
    owner_username: str
    owner_user_code: str
    submitted_at: datetime | None = None


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
