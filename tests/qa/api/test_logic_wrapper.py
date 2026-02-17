"""Tests for api/logic.py wrapper — EnqueueError → HTTPException mapping.

Phase 7a: Verifies that _wrap_enqueue_error converts each domain error
subclass to the correct HTTP status code.

Test Count: 12 tests
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

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
    RateLimitError,
    UserDisabledError,
)
from pulldb.api.logic import _ERROR_STATUS_MAP, _wrap_enqueue_error


class TestErrorStatusMap:
    """Verify _ERROR_STATUS_MAP covers all subclasses with correct HTTP codes."""

    @pytest.mark.parametrize(
        "error_cls, expected_status",
        [
            (EnqueueValidationError, 400),
            (HostUnauthorizedError, 403),
            (UserDisabledError, 403),
            (JobNotFoundError, 404),
            (EnqueueBackupNotFoundError, 404),
            (DuplicateJobError, 409),
            (DatabaseProtectionError, 409),
            (JobLockedError, 409),
            (RateLimitError, 429),
            (HostUnavailableError, 503),
        ],
        ids=lambda cls: cls.__name__ if isinstance(cls, type) else str(cls),
    )
    def test_subclass_maps_to_correct_status(
        self, error_cls: type[EnqueueError], expected_status: int
    ) -> None:
        """Each error subclass maps to the expected HTTP status code."""
        assert _ERROR_STATUS_MAP[error_cls] == expected_status

    def test_unknown_enqueue_error_defaults_to_500(self) -> None:
        """Base EnqueueError (unmapped) falls back to HTTP 500."""

        def raises_base():
            raise EnqueueError("unexpected internal error")

        with pytest.raises(HTTPException) as exc_info:
            _wrap_enqueue_error(raises_base)
        assert exc_info.value.status_code == 500

    def test_all_subclasses_present_in_map(self) -> None:
        """Every concrete subclass of EnqueueError has a map entry."""
        concrete = {
            EnqueueValidationError,
            HostUnauthorizedError,
            UserDisabledError,
            JobNotFoundError,
            EnqueueBackupNotFoundError,
            DuplicateJobError,
            DatabaseProtectionError,
            JobLockedError,
            RateLimitError,
            HostUnavailableError,
        }
        assert concrete == set(_ERROR_STATUS_MAP.keys())


class TestWrapEnqueueError:
    """Verify _wrap_enqueue_error behaviour."""

    def test_success_passes_through(self) -> None:
        """Non-error return values pass through unmodified."""
        result = _wrap_enqueue_error(lambda: "ok")
        assert result == "ok"

    @pytest.mark.parametrize(
        "error_cls, expected_status",
        [
            (EnqueueValidationError, 400),
            (UserDisabledError, 403),
            (HostUnavailableError, 503),
        ],
    )
    def test_converts_to_http_exception(
        self, error_cls: type[EnqueueError], expected_status: int
    ) -> None:
        """Domain error is converted to HTTPException with correct status and detail."""
        detail_msg = f"test {error_cls.__name__}"

        def raises():
            raise error_cls(detail_msg)

        with pytest.raises(HTTPException) as exc_info:
            _wrap_enqueue_error(raises)
        assert exc_info.value.status_code == expected_status
        assert exc_info.value.detail == detail_msg

    def test_non_enqueue_error_propagates(self) -> None:
        """Non-EnqueueError exceptions are not caught."""

        def raises():
            raise ValueError("not an enqueue error")

        with pytest.raises(ValueError, match="not an enqueue error"):
            _wrap_enqueue_error(raises)
