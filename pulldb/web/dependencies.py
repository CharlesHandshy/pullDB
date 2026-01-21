"""Shared FastAPI dependencies for pullDB Web UI.

HCA Layer: Foundation (shared across all layers)
Purpose: Common dependencies used by all route modules.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)

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
        current = manager.get_current_scenario()
        if current:
            return current.name.replace("_", " ").title()
    except Exception:  # Graceful degradation - scenario name is informational only
        logger.debug("Failed to get active scenario name", exc_info=True)
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
        except Exception:  # Graceful degradation - use default logo config
            logger.debug("Failed to load logo config, using defaults", exc_info=True)

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
    except Exception:  # Graceful degradation - default to light mode
        logger.debug("Failed to get admin dark mode setting", exc_info=True)
    return False


def _get_theme_version() -> int:
    """Get the current theme CSS version for cache-busting.
    
    Returns the timestamp when theme CSS was last generated.
    """
    try:
        version_file = WEB_DIR / "static" / "css" / "generated" / ".theme-version"
        if version_file.exists():
            return int(version_file.read_text().strip())
    except Exception:  # Graceful degradation - use manifest file mtime
        logger.debug("Failed to read theme version file", exc_info=True)
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


# =============================================================================
# Custom Jinja2 Filters for Log Formatting
# =============================================================================

def _parse_log_json(detail: str | None) -> dict | str | None:
    """Parse log detail as JSON if possible, otherwise return as-is."""
    if not detail:
        return None
    try:
        result = json.loads(detail)
        return result if isinstance(result, dict) else detail
    except (json.JSONDecodeError, TypeError):
        return detail


def _format_percent(value: float | int | str | None) -> str:
    """Format a float/int as a percentage (0-100%)."""
    if value is None:
        return "—"
    try:
        num = float(value)
        return f"{num:.0f}%"
    except (ValueError, TypeError):
        return str(value)


def _format_duration(value: float | int | str | None) -> str:
    """Format duration as H:MM:SS for >=60s, else Xs."""
    if value is None:
        return "—"
    try:
        secs = int(float(value))
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}:{secs % 60:02d}"
        hours = secs // 3600
        mins = (secs % 3600) // 60
        sec = secs % 60
        return f"{hours}:{mins:02d}:{sec:02d}"
    except (ValueError, TypeError):
        return str(value)


def _format_filesize(value: int | float | None) -> str:
    """Format bytes as human-readable size."""
    if value is None:
        return "—"
    try:
        num = float(value)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num) < 1024.0:
                return f"{num:.1f} {unit}"
            num /= 1024.0
        return f"{num:.1f} PB"
    except (ValueError, TypeError):
        return str(value)


def _format_speed(bytes_per_sec: float | None) -> str:
    """Format bytes/second as MB/s."""
    if bytes_per_sec is None or bytes_per_sec <= 0:
        return "—"
    mb_per_sec = bytes_per_sec / (1024 * 1024)
    return f"{mb_per_sec:.1f} MB/s"


def _format_eta(seconds: float | None) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    if seconds is None or seconds <= 0:
        return "—"
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60}:{seconds % 60:02d}"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _format_number(value: int | float | None) -> str:
    """Format number with K/M suffix."""
    if value is None:
        return "—"
    try:
        num = float(value)
        if num >= 1_000_000:
            return f"{num / 1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num / 1_000:.1f}K"
        return f"{int(num)}"
    except (ValueError, TypeError):
        return str(value)


templates.env.filters["parse_json"] = _parse_log_json
templates.env.filters["format_percent"] = _format_percent
templates.env.filters["format_duration"] = _format_duration
templates.env.filters["format_filesize"] = _format_filesize
templates.env.filters["format_speed"] = _format_speed
templates.env.filters["format_eta"] = _format_eta
templates.env.filters["format_number"] = _format_number


# Event type to human-readable label mapping
_EVENT_LABELS: dict[str, str] = {
    # File and table completion events
    "restore_file_loaded": "file loaded",
    "restore_table_ready": "table ready",
    # Other common events keep snake_case with spaces
}


def _format_event_label(event_type: str) -> str:
    """Convert event type to human-readable label.
    
    Returns human-readable label if defined in mapping, otherwise
    converts snake_case to space-separated words.
    
    Args:
        event_type: The raw event type string (e.g., 'restore_file_loaded').
        
    Returns:
        Human-readable label (e.g., 'file loaded').
    """
    if event_type in _EVENT_LABELS:
        return _EVENT_LABELS[event_type]
    # Default: replace underscores with spaces
    return event_type.replace("_", " ")


templates.env.filters["format_event_label"] = _format_event_label


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
    
    user: User | None = state.user_repo.get_user_by_id(user_id)
    return user


def require_login(
    request: Request,
    user: Annotated[User | None, Depends(get_session_user)],
    state: "APIState" = Depends(get_api_state),
) -> User:
    """Require authenticated user, raise SessionExpiredError if not.
    
    Also checks if user must change their password before continuing.
    The change-password route is exempted from the password reset check.
    
    Additionally checks if user needs to acknowledge maintenance items (expiring
    or locked databases). The maintenance route is exempted from this check.
    
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
    from pulldb.web.exceptions import (
        PasswordResetRequiredError,
        SessionExpiredError,
    )
    
    if not user:
        is_htmx = request.headers.get("HX-Request") == "true"
        raise SessionExpiredError(is_htmx=is_htmx)
    
    current_path = request.url.path
    
    # Check if password reset is required (exempt the change-password route itself)
    if not current_path.startswith("/web/change-password"):
        if hasattr(state, "auth_repo") and state.auth_repo:
            if hasattr(state.auth_repo, "is_password_reset_required"):
                if state.auth_repo.is_password_reset_required(user.user_id):
                    is_htmx = request.headers.get("HX-Request") == "true"
                    raise PasswordResetRequiredError(is_htmx=is_htmx)
    
    # NOTE: Maintenance check is done only at login time (not on every request)
    # This provides once-per-day enforcement without blocking normal navigation
    
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
