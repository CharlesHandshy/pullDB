"""Web UI module for pullDB.

Phase 4: Provides browser-based interface using Jinja2 templates and HTMX.

HCA Restructure Complete: The web UI uses HCA-compliant feature-based routes.
Unified - all routes under /web prefix with modern design system.
"""

from pulldb.web.router_registry import main_router as router
from pulldb.web.dependencies import TEMPLATES_DIR
from pulldb.web.exceptions import SessionExpiredError, create_session_expired_handler

__all__ = ["router", "TEMPLATES_DIR", "SessionExpiredError", "create_session_expired_handler"]
