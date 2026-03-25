"""Business logic for pullDB API — thin wrapper over domain enqueue service.

The actual orchestration logic lives in ``pulldb.domain.services.enqueue``
(entities layer). This module provides backward-compatible API-layer
functions that convert domain ``EnqueueError`` to FastAPI ``HTTPException``.

HCA Layer: pages
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from pulldb.api.schemas import JobRequest, JobResponse
from pulldb.api.types import APIState
from pulldb.domain.errors import (
    DatabaseProtectionError,
    DuplicateJobError,
    EnqueueBackupNotFoundError,
    EnqueueError,
    EnqueueValidationError,
    HostUnavailableError,
    HostUnauthorizedError,
    JobLockedError,
    JobNotFoundError,
    OverrideAcknowledgmentRequired,
    RateLimitError,
    UserDisabledError,
)

# Re-export domain types that existing callers import from here
from pulldb.worker.enqueue import (  # noqa: F401 — re-exports
    TargetResult,
    check_concurrency_limits as _domain_check_concurrency_limits,
    check_host_active_capacity as _domain_check_host_active_capacity,
    enqueue_job as _domain_enqueue_job,
    validate_job_request as _domain_validate_job_request,
)

logger = logging.getLogger(__name__)

# Maps domain error subclasses to HTTP status codes.
_ERROR_STATUS_MAP: dict[type[EnqueueError], int] = {
    EnqueueValidationError: 400,
    HostUnauthorizedError: 403,
    UserDisabledError: 403,
    JobNotFoundError: 404,
    EnqueueBackupNotFoundError: 404,
    DuplicateJobError: 409,
    DatabaseProtectionError: 409,
    JobLockedError: 409,
    RateLimitError: 429,
    HostUnavailableError: 503,
}


def _wrap_enqueue_error(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Call *fn* and translate :class:`EnqueueError` → :class:`HTTPException`."""
    try:
        return fn(*args, **kwargs)
    except OverrideAcknowledgmentRequired as exc:
        # Return structured 409 so API callers know which acks to supply on retry.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "acknowledgment_required",
                "required": exc.required,
                "context": exc.context,
            },
        ) from exc
    except EnqueueError as exc:
        status = _ERROR_STATUS_MAP.get(type(exc), 500)
        raise HTTPException(status_code=status, detail=exc.detail) from exc


def validate_job_request(req: JobRequest) -> None:
    """Validate that exactly one of customer or qatemplate is specified."""
    _wrap_enqueue_error(_domain_validate_job_request, req)


def check_host_active_capacity(state: APIState, hostname: str) -> None:
    """Check if host has capacity for more active jobs."""
    _wrap_enqueue_error(_domain_check_host_active_capacity, state, hostname)


def check_concurrency_limits(state: APIState, user) -> None:  # type: ignore[no-untyped-def]
    """Check concurrency limits before enqueueing a job."""
    _wrap_enqueue_error(_domain_check_concurrency_limits, state, user)


def enqueue_job(state: APIState, req: JobRequest) -> JobResponse:
    """Enqueue a new restore job.

    Wraps the domain-level ``enqueue_job`` and converts its
    ``EnqueueResult`` into a ``JobResponse`` for API consumers.
    """
    result = _wrap_enqueue_error(_domain_enqueue_job, state, req)
    stored = result.job
    tr = result.target_result

    return JobResponse(
        job_id=stored.id,
        target=stored.target,
        staging_name=stored.staging_name,
        status=stored.status.value,
        owner_username=stored.owner_username,
        owner_user_code=stored.owner_user_code,
        submitted_at=stored.submitted_at,
        original_customer=tr.original_customer,
        customer_normalized=tr.was_normalized,
        normalization_message=tr.normalization_message if tr.was_normalized else None,
        custom_target_used=tr.custom_target_used,
    )
