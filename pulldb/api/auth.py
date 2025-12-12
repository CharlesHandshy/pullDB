"""FastAPI authentication dependencies for pullDB.

Phase 4: Provides authentication middleware that supports both
trusted CLI mode and session-based web authentication.

Authentication Modes (PULLDB_AUTH_MODE environment variable):
- 'trusted': Accept X-Trusted-User header only (CLI mode, default)
- 'session': Require X-Session-Token header only (web mode)
- 'both': Accept either authentication method (transition mode)

Unified Auth Pattern:
All authenticated endpoints should use the dependency functions:
- get_authenticated_user: Requires login (any role)
- get_admin_user: Requires admin role
- get_manager_user: Requires manager or admin role

These dependencies support BOTH headers AND cookies for maximum compatibility
with CLI tools (headers) and web UI (httponly cookies).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool


if TYPE_CHECKING:
    from pulldb.api.types import APIState
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


# =============================================================================
# Unified Auth Dependencies (Use these in all endpoints)
# =============================================================================
# These dependencies support BOTH headers AND cookies for maximum compatibility
# with CLI tools (headers) and web UI (httponly cookies).


async def authenticate_user_optional(
    state: "APIState",
    x_trusted_user: str | None,
    x_session_token: str | None,
) -> "User | None":
    """Authenticate user if credentials provided, return None otherwise.

    This is for endpoints that need to support unauthenticated access in
    trusted mode but should validate user when auth is provided.

    Returns:
        Authenticated User object, or None if no credentials provided.

    Raises:
        HTTPException 401: Invalid credentials (credentials provided but bad).
        HTTPException 403: User account is disabled.
    """
    auth_mode = get_auth_mode()

    # In pure session mode, always require auth
    if auth_mode == "session" and not x_session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid session token required",
        )

    # No credentials provided
    if not x_trusted_user and not x_session_token:
        return None

    # Credentials provided - validate them
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

    # Credentials provided but invalid
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
    )


def _get_api_state() -> "APIState":
    """Import get_api_state lazily to avoid circular imports."""
    from pulldb.api.main import get_api_state
    return get_api_state()


async def get_authenticated_user(
    request: Request,
    state: "APIState" = Depends(_get_api_state),
    x_trusted_user: str | None = Header(None, alias="X-Trusted-User"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
) -> "User":
    """Unified auth dependency supporting both headers and cookies.

    Use this for ALL endpoints requiring authentication.

    Supports:
    - X-Trusted-User header (CLI mode)
    - X-Session-Token header (programmatic API)
    - session_token cookie (Web UI httponly cookie)

    Usage:
        @app.get("/api/example")
        async def example(user: AuthUser) -> Response:
            ...

    Or without the type alias:
        @app.get("/api/example")
        async def example(user: User = Depends(get_authenticated_user)) -> Response:
            ...
    """
    # Cookie fallback for web UI (httponly cookies can't be sent as headers)
    session_token = x_session_token or request.cookies.get("session_token")

    return await authenticate_user(state, x_trusted_user, session_token)


async def get_admin_user(
    request: Request,
    state: "APIState" = Depends(_get_api_state),
    x_trusted_user: str | None = Header(None, alias="X-Trusted-User"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
) -> "User":
    """Auth dependency requiring admin role.

    Use this for admin-only endpoints.

    Usage:
        @app.post("/api/admin/dangerous-action")
        async def dangerous(user: AdminUser) -> Response:
            ...
    """
    session_token = x_session_token or request.cookies.get("session_token")
    user = await authenticate_user(state, x_trusted_user, session_token)

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    return user


async def get_manager_user(
    request: Request,
    state: "APIState" = Depends(_get_api_state),
    x_trusted_user: str | None = Header(None, alias="X-Trusted-User"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
) -> "User":
    """Auth dependency requiring manager or admin role.

    Use this for manager-level endpoints.

    Usage:
        @app.get("/api/manager/team")
        async def team(user: ManagerUser) -> Response:
            ...
    """
    session_token = x_session_token or request.cookies.get("session_token")
    user = await authenticate_user(state, x_trusted_user, session_token)

    if not user.is_manager_or_above:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or admin role required",
        )

    return user


async def get_optional_user(
    request: Request,
    state: "APIState" = Depends(_get_api_state),
    x_trusted_user: str | None = Header(None, alias="X-Trusted-User"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
) -> "User | None":
    """Optional auth dependency - returns user if authenticated, None otherwise.

    Use this for endpoints that need to support unauthenticated access in
    trusted mode but should validate and enforce user when auth is provided.

    In session-only mode (PULLDB_AUTH_MODE=session), auth is still required.
    """
    session_token = x_session_token or request.cookies.get("session_token")
    return await authenticate_user_optional(state, x_trusted_user, session_token)


def validate_job_submission_user(
    authenticated_user: "User | None",
    request_username: str,
) -> None:
    """Validate that job submission is authorized for the given user.

    Args:
        authenticated_user: The authenticated user (or None if unauthenticated).
        request_username: The username in the job request.

    Raises:
        HTTPException 403: If authenticated but submitting for a different user
                          and not an admin.
    """
    if authenticated_user is None:
        # No auth provided - allow in trusted mode (backwards compat)
        return

    # Admins can submit jobs for anyone
    if authenticated_user.is_admin:
        return

    # Non-admins can only submit jobs for themselves
    if authenticated_user.username != request_username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You can only submit jobs for yourself, not for '{request_username}'",
        )


# =============================================================================
# Type Aliases for Clean Endpoint Signatures
# =============================================================================

AuthUser = Annotated["User", Depends(get_authenticated_user)]
AdminUser = Annotated["User", Depends(get_admin_user)]
ManagerUser = Annotated["User", Depends(get_manager_user)]
OptionalUser = Annotated["User | None", Depends(get_optional_user)]
