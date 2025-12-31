"""Shared FastAPI dependencies for pullDB Web UI.

HCA Layer: Foundation (shared across all layers)
Purpose: Common dependencies used by all route modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from pulldb.domain.models import User
from pulldb.infra.factory import is_simulation_mode
from pulldb.simulation import get_scenario_manager

if TYPE_CHECKING:
    from pulldb.api.main import APIState

# Template configuration - HCA multi-directory support
# Search order: feature pages → shared layouts → legacy templates
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"  # Legacy templates (backward compat)
FEATURES_DIR = WEB_DIR / "features"
SHARED_DIR = WEB_DIR / "shared"
IMAGES_DIR = WEB_DIR.parent / "images"
LOGO_CONFIG_PATH = IMAGES_DIR / "logo_config.json"

# Create loader that searches multiple directories
# Order matters: templates (backward compat) first, then HCA layouts
_loader = ChoiceLoader([
    # Legacy templates first (for backward compatibility with {% extends "base.html" %})
    FileSystemLoader(str(TEMPLATES_DIR)),
    # Web root (allows shared/layouts/... paths)
    FileSystemLoader(str(WEB_DIR)),
    # Feature-specific pages
    FileSystemLoader(str(FEATURES_DIR / "auth" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "dashboard" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "job_view" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "restore" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "search" / "pages")),
    FileSystemLoader(str(FEATURES_DIR / "admin" / "pages")),
    # Widgets
    FileSystemLoader(str(WEB_DIR / "widgets")),
    # Shared layouts (direct access without shared/layouts/ prefix)
    FileSystemLoader(str(SHARED_DIR / "layouts")),
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


def _get_logo_config() -> dict:
    """Load logo configuration from JSON file for use in templates."""
    default_label_style = {
        "x": 0,
        "y": 0,
        "font": "system-ui, -apple-system, sans-serif",
        "size": 20,
        "weight": "700",
        "style": "normal",
        "color": "#1f2937",
        "rotation": 0,
        "spacing": 0,
        "transform": "none",
    }

    default_config = {
        "path": "/static/images/pullDB_logo.mp4",
        "type": "video",
        "label": "",
        "logo_scale": 100,
        "crop_top": 13,
        "crop_bottom": 17,
        "crop_left": 0,
        "crop_right": 0,
        "label_style": default_label_style,
    }

    if LOGO_CONFIG_PATH.exists():
        try:
            with open(LOGO_CONFIG_PATH) as f:
                config = json.load(f)
                label_style = config.get("labelStyle", {})
                return {
                    "path": config.get("path", default_config["path"]),
                    "type": config.get("type", default_config["type"]),
                    "label": config.get("label", default_config["label"]),
                    "logo_scale": config.get("logoScale", default_config["logo_scale"]),
                    "crop_top": config.get("crop", {}).get("top", default_config["crop_top"]),
                    "crop_bottom": config.get("crop", {}).get("bottom", default_config["crop_bottom"]),
                    "crop_left": config.get("crop", {}).get("left", default_config["crop_left"]),
                    "crop_right": config.get("crop", {}).get("right", default_config["crop_right"]),
                    "label_style": {
                        "x": label_style.get("x", default_label_style["x"]),
                        "y": label_style.get("y", default_label_style["y"]),
                        "font": label_style.get("font", default_label_style["font"]),
                        "size": label_style.get("size", default_label_style["size"]),
                        "weight": label_style.get("weight", default_label_style["weight"]),
                        "style": label_style.get("style", default_label_style["style"]),
                        "color": label_style.get("color", default_label_style["color"]),
                        "rotation": label_style.get("rotation", default_label_style["rotation"]),
                        "spacing": label_style.get("spacing", default_label_style["spacing"]),
                        "transform": label_style.get("transform", default_label_style["transform"]),
                    },
                }
        except Exception:
            pass

    return default_config


def _get_admin_dark_mode() -> bool:
    """Get the admin-configured dark mode default setting.
    
    Returns True if dark mode is enabled by admin, False otherwise.
    Called by Jinja2 templates to set data-admin-theme-default attribute.
    """
    try:
        from pulldb.api.main import get_api_state as _get_api_state
        state = _get_api_state()
        if state and hasattr(state, "settings_repo") and state.settings_repo:
            dark_mode_str = state.settings_repo.get("dark_mode_enabled") or "false"
            return dark_mode_str.lower() in ("true", "1", "yes")
    except Exception:
        pass
    return False


def _get_theme_version() -> int:
    """Get the current theme CSS version for cache-busting.
    
    Returns the timestamp when theme CSS was last generated.
    """
    try:
        version_file = WEB_DIR / "static" / "css" / "generated" / ".theme-version"
        if version_file.exists():
            return int(version_file.read_text().strip())
    except Exception:
        pass
    return int(Path(WEB_DIR / "static" / "css" / "generated" / "manifest-light.css").stat().st_mtime)


# Add simulation mode globals to Jinja2 environment
# These are evaluated at template render time via callable
templates.env.globals["simulation_mode"] = is_simulation_mode
templates.env.globals["simulation_scenario_name"] = _get_active_scenario_name
templates.env.globals["get_logo_config"] = _get_logo_config
templates.env.globals["admin_dark_mode"] = _get_admin_dark_mode
templates.env.globals["theme_version"] = _get_theme_version
# Explicitly disable dev toolbar in production (defense in depth)
templates.env.globals["dev_mode"] = False
# App version from package
from pulldb import __version__ as _app_version
templates.env.globals["app_version"] = _app_version


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
    state: "APIState" = Depends(get_api_state),
) -> User:
    """Require authenticated user, raise SessionExpiredError if not.
    
    Also checks if user must change their password before continuing.
    The change-password route is exempted from the password reset check.
    
    Handles both regular requests (via Location header) and HTMX requests
    (via HX-Redirect header) to properly redirect.
    
    Args:
        request: The FastAPI request object
        user: The current user from session (injected)
        state: API state with auth_repo (injected)
        
    Returns:
        The authenticated User
        
    Raises:
        SessionExpiredError: If no valid session exists
        PasswordResetRequiredError: If user must change password first
    """
    from pulldb.web.exceptions import SessionExpiredError, PasswordResetRequiredError
    
    if not user:
        is_htmx = request.headers.get("HX-Request") == "true"
        raise SessionExpiredError(is_htmx=is_htmx)
    
    # Check if password reset is required (exempt the change-password route itself)
    current_path = request.url.path
    if not current_path.startswith("/web/change-password"):
        if hasattr(state, "auth_repo") and state.auth_repo:
            if hasattr(state.auth_repo, "is_password_reset_required"):
                if state.auth_repo.is_password_reset_required(user.user_id):
                    is_htmx = request.headers.get("HX-Request") == "true"
                    raise PasswordResetRequiredError(is_htmx=is_htmx)
    
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


def require_manager_or_above(
    user: Annotated[User, Depends(require_login)],
) -> User:
    """Require authenticated manager or admin user.
    
    Args:
        user: The authenticated user (injected)
        
    Returns:
        The authenticated manager/admin User
        
    Raises:
        HTTPException: 403 if user is not a manager or admin
    """
    from fastapi import HTTPException, status
    from pulldb.domain.models import UserRole
    
    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or admin access required",
        )
    return user


# Type aliases for cleaner route signatures
# Note: Using Annotated with non-forward-reference types works correctly
SessionUser = Annotated[User | None, Depends(get_session_user)]
AuthenticatedUser = Annotated[User, Depends(require_login)]
AdminUser = Annotated[User, Depends(require_admin)]
ManagerUser = Annotated[User, Depends(require_manager_or_above)]
# Note: APIState as string forward-reference doesn't work with Annotated due to
# FastAPI parsing it as a query param. Use the pattern: state: "APIState" = Depends(...)
