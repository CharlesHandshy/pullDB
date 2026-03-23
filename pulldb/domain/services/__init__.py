"""Deprecated — import from pulldb.worker instead.

HCA Phase 2 migration: all domain/services/* files have moved to
pulldb/worker/ (features layer).  This shim re-exports the most-used
symbols for backward compatibility and emits a DeprecationWarning.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "pulldb.domain.services is deprecated; import from pulldb.worker instead.",
    DeprecationWarning,
    stacklevel=2,
)

from pulldb.worker.enqueue import (  # noqa: E402, F401
    EnqueueDeps,
    EnqueueResult,
    TargetResult,
    check_concurrency_limits,
    check_host_active_capacity,
    enqueue_job,
    validate_job_request,
)

__all__ = [
    "EnqueueDeps",
    "EnqueueResult",
    "TargetResult",
    "check_concurrency_limits",
    "check_host_active_capacity",
    "enqueue_job",
    "validate_job_request",
]