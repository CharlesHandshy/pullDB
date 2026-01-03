"""FastAPI authentication dependencies for pullDB.

Phase 4: Provides authentication middleware that supports both
trusted CLI mode and session-based web authentication.

Authentication Modes (PULLDB_AUTH_MODE environment variable):
- 'trusted': Accept X-Trusted-User header only (CLI mode, default)
- 'session': Require X-Session-Token header only (web mode)
- 'both': Accept either authentication method (transition mode)
- 'signed': Require HMAC signature verification (secure CLI mode)

Unified Auth Pattern:
All authenticated endpoints should use the dependency functions:
- get_authenticated_user: Requires login (any role)
- get_admin_user: Requires admin role
- get_manager_user: Requires manager or admin role

These dependencies support BOTH headers AND cookies for maximum compatibility
with CLI tools (headers) and web UI (httponly cookies).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool


if TYPE_CHECKING:
    from pulldb.api.types import APIState
    from pulldb.domain.models import User


# Constants for HMAC signature verification
SIGNATURE_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SIGNATURE_MAX_AGE_SECONDS = 300  # 5 minutes - reject old requests


def get_auth_mode() -> str:
    """Get current authentication mode from environment.

    Returns:
        One of: 'trusted', 'session', 'both', 'signed'
    """
    mode = os.getenv("PULLDB_AUTH_MODE", "trusted").lower()
    if mode not in ("trusted", "session", "both", "signed"):
        return "trusted"
    return mode


def get_api_secret(key_id: str) -> str | None:
    """Get API secret for a given key ID.

    For now, uses a simple environment variable lookup.
    In production, this would query a database of API keys.

    Args:
        key_id: The API key identifier

    Returns:
        The secret associated with the key, or None if not found
    """
    # Simple implementation: check if key matches configured key
    configured_key = os.getenv("PULLDB_API_KEY")
    configured_secret = os.getenv("PULLDB_API_SECRET")

    if configured_key and configured_secret and key_id == configured_key:
        return configured_secret
    return None


def get_user_for_api_key(key_id: str) -> str | None:
    """Get username associated with an API key.

    For now, uses environment variable. In production, would query database.

    Args:
        key_id: The API key identifier

    Returns:
        Username associated with the key, or None if not found
    """
    configured_key = os.getenv("PULLDB_API_KEY")
    configured_user = os.getenv("PULLDB_API_KEY_USER")

    if configured_key and key_id == configured_key:
        return configured_user or "api-user"
    return None


def verify_signature(
    method: str,
    path: str,
    body: bytes | None,
    timestamp: str,
    signature: str,
    secret: str,
) -> bool:
    """Verify HMAC-SHA256 request signature.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path
        body: Request body bytes (or None for GET)
        timestamp: ISO 8601 timestamp from request
        signature: Hex-encoded signature from request
        secret: API secret key

    Returns:
        True if signature is valid, False otherwise
    """
    # Hash the body (or empty string)
    if body:
        body_hash = hashlib.sha256(body).hexdigest()
    else:
        body_hash = hashlib.sha256(b"").hexdigest()

    # Build string to sign (must match client)
    string_to_sign = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}"

    # Compute expected signature
    expected = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected, signature)


def validate_signature_timestamp(timestamp: str) -> bool:
    """Check if signature timestamp is within acceptable range.

    Prevents replay attacks by rejecting requests with old timestamps.

    Args:
        timestamp: ISO 8601 timestamp from request

    Returns:
        True if timestamp is within acceptable range
    """
    try:
        request_time = datetime.strptime(timestamp, SIGNATURE_TIMESTAMP_FORMAT)
        request_time = request_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_seconds = abs((now - request_time).total_seconds())
        return age_seconds <= SIGNATURE_MAX_AGE_SECONDS
    except ValueError:
        return False


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
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_timestamp: str | None = Header(None, alias="X-Timestamp"),
    x_signature: str | None = Header(None, alias="X-Signature"),
) -> "User":
    """Unified auth dependency supporting headers, cookies, and signatures.

    Use this for ALL endpoints requiring authentication.

    Supports:
    - HMAC signature (X-API-Key + X-Timestamp + X-Signature) - most secure
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
    auth_mode = get_auth_mode()

    # Try signed authentication first (if credentials provided)
    if x_api_key and x_timestamp and x_signature:
        # Validate timestamp is recent (prevent replay attacks)
        if not validate_signature_timestamp(x_timestamp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp expired or invalid",
            )

        # Get secret for this API key
        secret = get_api_secret(x_api_key)
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Get request details for signature verification
        method = request.method
        path = request.url.path

        # Read body for POST/PUT/PATCH requests
        body: bytes | None = None
        if method in ("POST", "PUT", "PATCH"):
            body = await request.body()

        # Verify signature
        if not verify_signature(method, path, body, x_timestamp, x_signature, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid request signature",
            )

        # Signature valid - get user for this API key
        username = get_user_for_api_key(x_api_key)
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has no associated user",
            )

        user = await run_in_threadpool(
            state.user_repo.get_user_by_username, username
        )
        if user and user.disabled_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        if user:
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for API key",
        )

    # Signed mode requires signature headers
    if auth_mode == "signed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="HMAC signature required (X-API-Key, X-Timestamp, X-Signature)",
        )

    # Cookie fallback for web UI (httponly cookies can't be sent as headers)
    session_token = x_session_token or request.cookies.get("session_token")

    return await authenticate_user(state, x_trusted_user, session_token)


async def get_admin_user(
    user: "User" = Depends(get_authenticated_user),
) -> "User":
    """Auth dependency requiring admin role.

    Use this for admin-only endpoints. Builds on get_authenticated_user
    so it inherits all auth methods (signed, trusted, session).

    Usage:
        @app.post("/api/admin/dangerous-action")
        async def dangerous(user: AdminUser) -> Response:
            ...
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    return user


async def get_manager_user(
    user: "User" = Depends(get_authenticated_user),
) -> "User":
    """Auth dependency requiring manager or admin role.

    Use this for manager-level endpoints. Builds on get_authenticated_user
    so it inherits all auth methods (signed, trusted, session).

    Usage:
        @app.get("/api/manager/team")
        async def team(user: ManagerUser) -> Response:
            ...
    """
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
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_timestamp: str | None = Header(None, alias="X-Timestamp"),
    x_signature: str | None = Header(None, alias="X-Signature"),
) -> "User | None":
    """Optional auth dependency - returns user if authenticated, None otherwise.

    Use this for endpoints that need to support unauthenticated access in
    trusted mode but should validate and enforce user when auth is provided.

    Supports all auth methods: signed, trusted, session.
    In session-only or signed-only mode, auth is still required.
    """
    auth_mode = get_auth_mode()

    # Try signed authentication first (if credentials provided)
    if x_api_key and x_timestamp and x_signature:
        # Validate timestamp is recent (prevent replay attacks)
        if not validate_signature_timestamp(x_timestamp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp expired or invalid",
            )

        # Get secret for this API key
        secret = get_api_secret(x_api_key)
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Get request details for signature verification
        method = request.method
        path = request.url.path

        # Read body for POST/PUT/PATCH requests
        body: bytes | None = None
        if method in ("POST", "PUT", "PATCH"):
            body = await request.body()

        # Verify signature
        if not verify_signature(method, path, body, x_timestamp, x_signature, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid request signature",
            )

        # Signature valid - get user for this API key
        username = get_user_for_api_key(x_api_key)
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has no associated user",
            )

        user = await run_in_threadpool(
            state.user_repo.get_user_by_username, username
        )
        if user and user.disabled_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        if user:
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for API key",
        )

    # Signed mode requires signature headers
    if auth_mode == "signed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="HMAC signature required (X-API-Key, X-Timestamp, X-Signature)",
        )

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
