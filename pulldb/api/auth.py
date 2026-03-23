"""FastAPI authentication dependencies for pullDB.

Provides secure authentication middleware using HMAC-signed requests
for CLI/API access and session cookies for web UI.

Authentication Methods:
- HMAC Signed: X-API-Key + X-Timestamp + X-Signature (CLI, programmatic)
- Session Cookie: session_token httponly cookie (Web UI)

The X-Trusted-User header is NO LONGER SUPPORTED (deprecated for security).

Unified Auth Pattern:
All authenticated endpoints should use the dependency functions:
- get_authenticated_user: Requires login (any role)
- get_admin_user: Requires admin role
- get_manager_user: Requires manager or admin role

These dependencies support BOTH HMAC signatures AND cookies for maximum
compatibility with CLI tools and web UI.

HCA Layer: pages (pulldb/api/)
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from pulldb.domain.errors import KeyPendingApprovalError, KeyRevokedError
from pulldb.domain.models import User  # Import at runtime for Pydantic OpenAPI schema generation
from fastapi.concurrency import run_in_threadpool


if TYPE_CHECKING:
    from pulldb.api.types import APIState
    from pulldb.domain.interfaces import AuthRepository


# Constants for HMAC signature verification
SIGNATURE_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SIGNATURE_MAX_AGE_SECONDS = 300  # 5 minutes - reject old requests


def get_api_secret(key_id: str, auth_repo: AuthRepository | None = None) -> str | None:
    """Get API secret for a given key ID.

    Checks database first (via auth_repo), falls back to environment variables
    for backward compatibility during migration.

    Args:
        key_id: The API key identifier
        auth_repo: Optional AuthRepository for database lookup

    Returns:
        The secret associated with the key, or None if not found

    Raises:
        KeyPendingApprovalError: If the key exists but is pending admin approval.
    """
    # Priority 1: Database lookup (if auth_repo available)
    if auth_repo and hasattr(auth_repo, "get_api_key_secret"):
        # This may raise KeyPendingApprovalError - let it propagate
        secret = auth_repo.get_api_key_secret(key_id)
        if secret:
            return str(secret)

    # Priority 2: Environment variable (backward compatibility)
    configured_key = os.getenv("PULLDB_API_KEY")
    configured_secret = os.getenv("PULLDB_API_SECRET")

    if configured_key and configured_secret and key_id == configured_key:
        return configured_secret

    return None


def get_user_for_api_key(key_id: str, auth_repo: AuthRepository | None = None) -> str | None:
    """Get username associated with an API key.

    Checks database first (via auth_repo), falls back to environment variables.

    Args:
        key_id: The API key identifier
        auth_repo: Optional AuthRepository for database lookup

    Returns:
        Username associated with the key, or None if not found

    Raises:
        KeyPendingApprovalError: If the key exists but is pending admin approval.
    """
    # Priority 1: Database lookup (if auth_repo available)
    if auth_repo and hasattr(auth_repo, "get_api_key_user"):
        # This may raise KeyPendingApprovalError - let it propagate
        user_id = auth_repo.get_api_key_user(key_id)
        if user_id:
            # Return user_id - the caller will look up username
            return str(user_id)

    # Priority 2: Environment variable (backward compatibility)
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


# =============================================================================
# FastAPI Dependencies (Use these in all endpoints)
# =============================================================================
# These dependencies support HMAC signatures (CLI) and session cookies (Web UI).


# Note: We import get_api_state lazily at runtime to avoid circular imports.
# The Depends() wrapper ensures FastAPI's dependency override system works.
def _get_api_state_dependency() -> "APIState":
    """Get API state - imported lazily to avoid circular imports.
    
    This function is used with Depends() in endpoint signatures.
    FastAPI's dependency override system will work because we use
    Depends(_get_api_state_dependency), not a direct function call.
    """
    from typing import cast
    from pulldb.api.main import get_api_state, app
    from pulldb.api.types import APIState
    
    # Check if there's a dependency override for get_api_state
    if get_api_state in app.dependency_overrides:
        result = app.dependency_overrides[get_api_state]()
        return cast(APIState, result)
    state = get_api_state()
    return cast(APIState, state)


async def get_authenticated_user(
    request: Request,
    state: "APIState" = Depends(_get_api_state_dependency),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_timestamp: str | None = Header(None, alias="X-Timestamp"),
    x_signature: str | None = Header(None, alias="X-Signature"),
) -> "User":
    """Unified auth dependency supporting HMAC signatures and session cookies.

    Use this for ALL endpoints requiring authentication.

    Supports:
    - HMAC signature (X-API-Key + X-Timestamp + X-Signature) - CLI/programmatic
    - X-Session-Token header (programmatic API)
    - session_token cookie (Web UI httponly cookie)

    NOTE: X-Trusted-User header is NO LONGER SUPPORTED (deprecated).

    Usage:
        @app.get("/api/example")
        async def example(user: AuthUser) -> Response:
            ...

    Or without the type alias:
        @app.get("/api/example")
        async def example(user: User = Depends(get_authenticated_user)) -> Response:
            ...
    """
    # Try HMAC signed authentication first (CLI/programmatic)
    if x_api_key and x_timestamp and x_signature:
        # Validate timestamp is recent (prevent replay attacks)
        if not validate_signature_timestamp(x_timestamp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp expired or invalid",
            )

        # Get secret for this API key (try database first, then env vars)
        auth_repo = state.auth_repo if hasattr(state, "auth_repo") else None
        
        try:
            secret = get_api_secret(x_api_key, auth_repo)
        except KeyPendingApprovalError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key pending approval: {e.key_id}. Contact an administrator to approve your key.",
            )
        except KeyRevokedError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key has been revoked: {e.key_id}. Contact an administrator if you believe this is an error.",
            )
        
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
        try:
            user_or_username = get_user_for_api_key(x_api_key, auth_repo)
        except KeyPendingApprovalError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key pending approval: {e.key_id}. Contact an administrator to approve your key.",
            )
        except KeyRevokedError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key has been revoked: {e.key_id}. Contact an administrator if you believe this is an error.",
            )
        if not user_or_username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has no associated user",
            )

        # If we got a user_id from database, look up by ID; otherwise by username
        # Check if it looks like a UUID (36 chars with hyphens)
        user: User | None
        if len(user_or_username) == 36 and user_or_username.count("-") == 4:
            # It's a user_id from the database
            user = await run_in_threadpool(
                state.user_repo.get_user_by_id, user_or_username
            )
        else:
            # It's a username from env var
            user = await run_in_threadpool(
                state.user_repo.get_user_by_username, user_or_username
            )

        if user and user.disabled_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        if user and user.locked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is locked",
            )
        if user:
            # Update last_used_at and last_used_ip for this API key
            if auth_repo and hasattr(auth_repo, "update_api_key_last_used"):
                client_ip = request.client.host if request.client else None
                await run_in_threadpool(
                    auth_repo.update_api_key_last_used, x_api_key, client_ip
                )
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for API key",
        )

    # Try session authentication (Web UI)
    session_token = x_session_token or request.cookies.get("session_token")
    if session_token and hasattr(state, "auth_repo") and state.auth_repo:
        user_id = await run_in_threadpool(
            state.auth_repo.validate_session, session_token
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
            if user and user.locked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is locked",
                )
            if user:
                return user

    # No valid authentication found
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Use HMAC signature (CLI) or session cookie (Web UI).",
    )


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
    so it inherits all auth methods (signed, session).

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
    state: "APIState" = Depends(_get_api_state_dependency),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_timestamp: str | None = Header(None, alias="X-Timestamp"),
    x_signature: str | None = Header(None, alias="X-Signature"),
) -> "User | None":
    """Optional auth dependency - returns user if authenticated, None otherwise.

    For endpoints that can work with or without authentication.
    If credentials are provided, they MUST be valid.

    Supports: HMAC signatures (CLI) and session cookies (Web UI).
    """
    # Get auth_repo from state for database lookups
    auth_repo = state.auth_repo if hasattr(state, "auth_repo") else None
    
    # Try HMAC signed authentication first
    if x_api_key and x_timestamp and x_signature:
        # Validate timestamp is recent (prevent replay attacks)
        if not validate_signature_timestamp(x_timestamp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp expired or invalid",
            )

        # Get secret for this API key (check database first, then env vars)
        try:
            secret = get_api_secret(x_api_key, auth_repo)
        except KeyPendingApprovalError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key pending approval: {e.key_id}. Contact an administrator to approve your key.",
            )
        except KeyRevokedError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key has been revoked: {e.key_id}. Contact an administrator if you believe this is an error.",
            )
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
        try:
            user_or_username = get_user_for_api_key(x_api_key, auth_repo)
        except KeyPendingApprovalError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key pending approval: {e.key_id}. Contact an administrator to approve your key.",
            )
        except KeyRevokedError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"API key has been revoked: {e.key_id}. Contact an administrator if you believe this is an error.",
            )
        if not user_or_username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has no associated user",
            )

        # If we got a user_id from database, look up by ID; otherwise by username
        # Check if it looks like a UUID (36 chars with hyphens)
        user: User | None
        if len(user_or_username) == 36 and user_or_username.count("-") == 4:
            # It's a user_id from the database
            user = await run_in_threadpool(
                state.user_repo.get_user_by_id, user_or_username
            )
        else:
            # It's a username from env var
            user = await run_in_threadpool(
                state.user_repo.get_user_by_username, user_or_username
            )
            
        if user and user.disabled_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        if user and user.locked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is locked",
            )
        if user:
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for API key",
        )

    # Try session authentication (Web UI)
    session_token = x_session_token or request.cookies.get("session_token")
    if session_token and hasattr(state, "auth_repo") and state.auth_repo:
        user_id = await run_in_threadpool(
            state.auth_repo.validate_session, session_token
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
            if user and user.locked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is locked",
                )
            if user:
                return user

    # No authentication provided - return None (allowed for optional endpoints)
    return None


def validate_job_submission_user(
    authenticated_user: "User",
    request_username: str,
) -> None:
    """Validate that job submission is authorized for the given user.

    Args:
        authenticated_user: The authenticated user making the request.
        request_username: The username in the job request.

    Raises:
        HTTPException 403: If authenticated but submitting for a different user
                          and not an admin.
    """
    # Admins and service accounts can submit jobs for anyone
    from pulldb.domain.models import UserRole
    if authenticated_user.role in (UserRole.ADMIN, UserRole.SERVICE):
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

AuthUser = Annotated[User, Depends(get_authenticated_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
ManagerUser = Annotated[User, Depends(get_manager_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
