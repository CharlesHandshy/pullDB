"""Shared FastAPI dependencies for pullDB Web UI.

HCA Layer: Foundation (shared across all layers)
Purpose: Common dependencies used by all route modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from pulldb.domain.models import User
from pulldb.infra.factory import is_simulation_mode
from pulldb.simulation import get_simulation_state, get_scenario_manager

if TYPE_CHECKING:
    from pulldb.api.main import APIState

# Template configuration - HCA multi-directory support
# Search order: feature pages → shared layouts → legacy templates
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"  # Legacy templates (backward compat)
FEATURES_DIR = WEB_DIR / "features"
SHARED_DIR = WEB_DIR / "shared"

# Create loader that searches multiple directories
_loader = ChoiceLoader([
    # Feature-specific pages
    FileSystemLoader(str(FEATURES_DIR / "auth" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "dashboard" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "job_view" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "restore" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "search" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "admin" / "pages")),
    # Shared layouts
    FileSystemLoader(str(SHARED_DIR / "layouts")),
    # Legacy templates (fallback)
    FileSystemLoader(str(TEMPLATES_DIR)),
])

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.loader = _loader


def _get_active_scenario_name() -> str | None:
    """Get the name of the currently active scenario (for template display)."""
    if not is_simulation_mode():
        return None
    try:
        manager = get_scenario_manager()
        if manager.active_scenario:
            return manager.active_scenario.name.replace("_", " ").title()
    except Exception:
        pass
    return None


# Add simulation mode globals to Jinja2 environment
# These are evaluated at template render time via callable
templates.env.globals["simulation_mode"] = is_simulation_mode
templates.env.globals["simulation_scenario_name"] = _get_active_scenario_name


def get_api_state(request: Request) -> "APIState":
    """Get API state from request.
    
    Returns:
        The global APIState instance containing repositories and services.
    """
    from pulldb.api.main import get_api_state as _get_api_state
    return _get_api_state()


def get_session_user(
    request: Request,
    state: "APIState" = Depends(get_api_state),
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
# Note: Using Annotated with non-forward-reference types works correctly
SessionUser = Annotated[User | None, Depends(get_session_user)]
AuthenticatedUser = Annotated[User, Depends(require_login)]
AdminUser = Annotated[User, Depends(require_admin)]
# Note: APIState as string forward-reference doesn't work with Annotated due to
# FastAPI parsing it as a query param. Use the pattern: state: "APIState" = Depends(...)
