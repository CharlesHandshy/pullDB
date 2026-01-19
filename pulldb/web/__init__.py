from __future__ import annotations

"""Web UI module for pullDB.

Phase 4: Provides browser-based interface using Jinja2 templates and HTMX.

HCA Restructure Complete: The web UI uses HCA-compliant feature-based routes.
Unified - all routes under /web prefix with modern design system.

HCA Layer: pages (pulldb/web/)
"""

from pulldb.web.router_registry import main_router as router
from pulldb.web.dependencies import TEMPLATES_DIR, templates
from pulldb.web.exceptions import (
    SessionExpiredError,
    PasswordResetRequiredError,
    MaintenanceRequiredError,
    create_session_expired_handler,
    create_password_reset_required_handler,
    create_maintenance_required_handler,
    create_http_exception_handler,
)

__all__ = [
    "router",
    "TEMPLATES_DIR",
    "templates",
    "SessionExpiredError",
    "PasswordResetRequiredError",
    "MaintenanceRequiredError",
    "create_session_expired_handler",
    "create_password_reset_required_handler",
    "create_maintenance_required_handler",
    "create_http_exception_handler",
]
