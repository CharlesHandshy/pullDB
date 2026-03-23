"""Unit tests for pulldb/api/auth.py security logic.

HCA Layer: tests
Covers:
  - validate_job_submission_user (Phase 1 Security Fix C)
  - get_optional_user session path locked-account check (Phase 1 Security Fix B)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from pulldb.api.auth import validate_job_submission_user
from pulldb.domain.models import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    username: str = "testuser",
    role: UserRole = UserRole.USER,
    disabled_at: datetime | None = None,
    locked_at: datetime | None = None,
) -> User:
    """Build a minimal User for testing."""
    return User(
        user_id="00000000-0000-0000-0000-000000000001",
        username=username,
        user_code="testus",
        role=role,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        disabled_at=disabled_at,
        locked_at=locked_at,
    )


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# validate_job_submission_user
# ===========================================================================

class TestValidateJobSubmissionUser:
    """validate_job_submission_user — Phase 1 Security Fix C.

    The trusted-mode None bypass has been removed. The parameter type is now
    User (not User | None). These tests verify that the function enforces
    authz correctly and that the dead-code bypass no longer exists.
    """

    def test_user_submitting_for_themselves_passes(self) -> None:
        user = _make_user(username="alice")
        # Should not raise
        validate_job_submission_user(user, "alice")

    def test_user_submitting_for_another_raises_403(self) -> None:
        user = _make_user(username="alice")
        with pytest.raises(HTTPException) as exc_info:
            validate_job_submission_user(user, "bob")
        assert exc_info.value.status_code == 403
        assert "bob" in exc_info.value.detail

    def test_admin_can_submit_for_anyone(self) -> None:
        admin = _make_user(username="admin", role=UserRole.ADMIN)
        validate_job_submission_user(admin, "anyone_at_all")  # must not raise

    def test_service_account_can_submit_for_anyone(self) -> None:
        svc = _make_user(username="pulldb_service", role=UserRole.SERVICE)
        validate_job_submission_user(svc, "some_user")  # must not raise

    def test_manager_cannot_submit_for_others(self) -> None:
        """Managers have elevated read access but cannot hijack job submissions."""
        mgr = _make_user(username="manager1", role=UserRole.MANAGER)
        with pytest.raises(HTTPException) as exc_info:
            validate_job_submission_user(mgr, "managed_user")
        assert exc_info.value.status_code == 403

    def test_none_user_raises_type_error(self) -> None:
        """Passing None now causes a TypeError — the bypass is gone.

        This test explicitly documents that the trusted-mode bypass
        (if authenticated_user is None: return) no longer exists.
        If the bypass is ever accidentally re-added this test will fail.
        """
        with pytest.raises((TypeError, AttributeError)):
            validate_job_submission_user(None, "any_user")  # type: ignore[arg-type]

    def test_error_message_names_disallowed_target(self) -> None:
        user = _make_user(username="charlie")
        with pytest.raises(HTTPException) as exc_info:
            validate_job_submission_user(user, "diana")
        assert "diana" in exc_info.value.detail


# ===========================================================================
# get_optional_user — session path locked-account check
# ===========================================================================

class TestGetOptionalUserLockedCheck:
    """get_optional_user session path — Phase 1 Security Fix B.

    The session-token code path previously checked disabled_at but was missing
    the user.locked check. A locked system user (e.g. pulldb_service with
    locked_at set) could authenticate via session token through optional-auth
    endpoints. These tests verify the locked check is now enforced.
    """

    @pytest.mark.asyncio
    async def test_locked_user_via_session_raises_403(self) -> None:
        """A locked user must be rejected even when using a valid session token."""
        from pulldb.api.auth import get_optional_user

        locked_user = _make_user(
            username="pulldb_service",
            role=UserRole.SERVICE,
            locked_at=_NOW,
        )

        # Build minimal mocks
        mock_state = MagicMock()
        mock_state.auth_repo.validate_session.return_value = locked_user.user_id
        mock_state.user_repo.get_user_by_id.return_value = locked_user

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None

        with patch("pulldb.api.auth.run_in_threadpool", new=AsyncMock()) as mock_tp:
            # First call: validate_session → returns user_id
            # Second call: get_user_by_id → returns locked_user
            mock_tp.side_effect = [locked_user.user_id, locked_user]

            with pytest.raises(HTTPException) as exc_info:
                await get_optional_user(
                    request=mock_request,
                    state=mock_state,
                    x_session_token="valid-session-token",
                    x_api_key=None,
                    x_timestamp=None,
                    x_signature=None,
                )

        assert exc_info.value.status_code == 403
        assert "locked" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_disabled_user_via_session_still_raises_403(self) -> None:
        """Regression: disabled_at check continues to work after adding locked check."""
        from pulldb.api.auth import get_optional_user

        disabled_user = _make_user(
            username="former_employee",
            disabled_at=_NOW,
        )

        mock_state = MagicMock()
        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None

        with patch("pulldb.api.auth.run_in_threadpool", new=AsyncMock()) as mock_tp:
            mock_tp.side_effect = [disabled_user.user_id, disabled_user]

            with pytest.raises(HTTPException) as exc_info:
                await get_optional_user(
                    request=mock_request,
                    state=mock_state,
                    x_session_token="valid-session-token",
                    x_api_key=None,
                    x_timestamp=None,
                    x_signature=None,
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_normal_user_via_session_returns_user(self) -> None:
        """Happy path: active, unlocked user with valid session passes through."""
        from pulldb.api.auth import get_optional_user

        active_user = _make_user(username="active_user")

        mock_state = MagicMock()
        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None

        with patch("pulldb.api.auth.run_in_threadpool", new=AsyncMock()) as mock_tp:
            mock_tp.side_effect = [active_user.user_id, active_user]

            result = await get_optional_user(
                request=mock_request,
                state=mock_state,
                x_session_token="valid-session-token",
                x_api_key=None,
                x_timestamp=None,
                x_signature=None,
            )

        assert result is active_user

    @pytest.mark.asyncio
    async def test_no_credentials_returns_none(self) -> None:
        """No auth headers and no session cookie → returns None (optional endpoint)."""
        from pulldb.api.auth import get_optional_user

        mock_state = MagicMock()
        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None  # no cookie

        # No session token, no HMAC headers
        result = await get_optional_user(
            request=mock_request,
            state=mock_state,
            x_session_token=None,
            x_api_key=None,
            x_timestamp=None,
            x_signature=None,
        )

        assert result is None
