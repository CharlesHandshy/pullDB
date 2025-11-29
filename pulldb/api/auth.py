"""FastAPI authentication dependencies for pullDB.

Phase 4: Provides authentication middleware that supports both
trusted CLI mode and session-based web authentication.

Authentication Modes (PULLDB_AUTH_MODE environment variable):
- 'trusted': Accept X-Trusted-User header only (CLI mode, default)
- 'session': Require X-Session-Token header only (web mode)
- 'both': Accept either authentication method (transition mode)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool


if TYPE_CHECKING:
    from pulldb.api.main import APIState
    from pulldb.domain.models import User


def get_auth_mode() -> str:
    """Get current authentication mode from environment.

    Returns:
        One of: 'trusted', 'session', 'both'
    """
    mode = os.getenv("PULLDB_AUTH_MODE", "trusted").lower()
    if mode not in ("trusted", "session", "both"):
        return "trusted"
    return mode


async def get_current_user_optional(
    x_trusted_user: str | None = Header(None, alias="X-Trusted-User"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
) -> tuple[str | None, str | None]:
    """Extract authentication headers without validation.

    This is a low-level dependency that just extracts headers.
    Use get_current_user for full validation.

    Returns:
        Tuple of (trusted_user, session_token)
    """
    return x_trusted_user, x_session_token


async def authenticate_user(
    state: APIState,
    x_trusted_user: str | None,
    x_session_token: str | None,
) -> User:
    """Authenticate user from request headers.

    Authentication modes (PULLDB_AUTH_MODE):
    - 'trusted': Only X-Trusted-User header (CLI)
    - 'session': Only X-Session-Token header (web)
    - 'both': Accept either (transition)

    Args:
        state: API state with repositories.
        x_trusted_user: Value of X-Trusted-User header.
        x_session_token: Value of X-Session-Token header.

    Returns:
        Authenticated User object.

    Raises:
        HTTPException 401: Invalid or missing authentication.
        HTTPException 403: User account is disabled.
    """
    auth_mode = get_auth_mode()
    user = None

    # Try trusted mode first (if enabled)
    if auth_mode in ("trusted", "both") and x_trusted_user:
        user = await run_in_threadpool(
            state.user_repo.get_user_by_username, x_trusted_user
        )
        if user and user.disabled_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        if user:
            return user

    # Try session mode (if enabled and auth_repo available)
    if (
        auth_mode in ("session", "both")
        and x_session_token
        and hasattr(state, "auth_repo")
        and state.auth_repo
    ):
        user_id = await run_in_threadpool(
            state.auth_repo.validate_session, x_session_token
        )
        if user_id:
            user = await run_in_threadpool(
                state.user_repo.get_user_by_id, user_id
            )
            if user and user.disabled_at:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is disabled",
                )
            if user:
                return user

    # No valid authentication found
    if auth_mode == "trusted":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Trusted-User header required",
        )
    elif auth_mode == "session":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid session token required",
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (X-Trusted-User or session token)",
        )
