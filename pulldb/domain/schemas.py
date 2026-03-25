"""Domain-level request schemas shared across entry points (API, Web, CLI).

These Pydantic models represent core domain concepts used by multiple
pages-layer packages. They live in the entities layer so both pulldb.api
and pulldb.web can import them without lateral pages-to-pages coupling.

HCA Layer: entities (pulldb/domain/)
"""

from __future__ import annotations

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
    backup_path: str | None = pydantic.Field(
        default=None,
        description="Full S3 path to specific backup (e.g., s3://bucket/prefix/customer/daily_mydumper_*.tar)",
    )
    custom_target: str | None = pydantic.Field(
        default=None,
        pattern=r"^[a-z]{1,51}$",
        description="Custom target database name. 1-51 lowercase letters, user has FULL control.",
    )
    # Override acknowledgments — must be explicitly set to True after the user
    # reviews and accepts the corresponding warning in the UI.  Each triggers
    # an audit record when the job is created.
    ack_customer_name_override: bool = False
    """Acknowledge that the custom target matches a real customer name."""
    ack_ownership_transfer: bool = False
    """Acknowledge transferring ownership from the current DB owner to this user."""
