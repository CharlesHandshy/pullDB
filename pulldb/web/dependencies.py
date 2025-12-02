"""Shared FastAPI dependencies for pullDB Web UI.

HCA Layer: Foundation (shared across all layers)
Purpose: Common dependencies used by all route modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import User

if TYPE_CHECKING:
    from pulldb.api.main import APIState

# Template configuration - shared across all route modules
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_api_state(request: Request) -> "APIState":
    """Get API state from request.
    
    Returns:
        The global APIState instance containing repositories and services.
    """
    from pulldb.api.main import get_api_state as _get_api_state
    return _get_api_state()


def get_session_user(
    request: Request,
    state: Annotated["APIState", Depends(get_api_state)],
) -> User | None:
    """Get current user from session cookie if valid.
    
    Args:
        request: The FastAPI request object
        state: The API state with repositories
        
    Returns:
        The authenticated User or None if not logged in.
    """
    session_token = request.cookies.get("session_token")
    if not session_token:
        return None
    
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return None
    
    user_id = state.auth_repo.validate_session(session_token)
    if not user_id:
        return None
    
    return state.user_repo.get_user_by_id(user_id)


def require_login(
    request: Request,
    user: Annotated[User | None, Depends(get_session_user)],
) -> User:
    """Require authenticated user, raise SessionExpiredError if not.
    
    Handles both regular requests (via Location header) and HTMX requests
    (via HX-Redirect header) to properly redirect to the login page.
    
    Args:
        request: The FastAPI request object
        user: The current user from session (injected)
        
    Returns:
        The authenticated User
        
    Raises:
        SessionExpiredError: If no valid session exists
    """
    from pulldb.web.exceptions import SessionExpiredError
    
    if not user:
        is_htmx = request.headers.get("HX-Request") == "true"
        raise SessionExpiredError(is_htmx=is_htmx)
    return user


def require_admin(
    user: Annotated[User, Depends(require_login)],
) -> User:
    """Require authenticated admin user.
    
    Args:
        user: The authenticated user (injected)
        
    Returns:
        The authenticated admin User
        
    Raises:
        HTTPException: 403 if user is not an admin
    """
    from fastapi import HTTPException, status
    
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# Type aliases for cleaner route signatures
SessionUser = Annotated[User | None, Depends(get_session_user)]
AuthenticatedUser = Annotated[User, Depends(require_login)]
AdminUser = Annotated[User, Depends(require_admin)]
APIStateDep = Annotated["APIState", Depends(get_api_state)]
