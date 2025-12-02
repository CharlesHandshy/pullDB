"""Web UI module for pullDB.

Phase 4: Provides browser-based interface using Jinja2 templates and HTMX.

HCA Restructure: The web UI has been restructured following HCA principles.
- Old routes: pulldb.web.routes.router (monolithic, deprecated)
- New routes: pulldb.web.router_registry.main_router (HCA-compliant)

Currently using old routes for backward compatibility. To switch to HCA routes,
import main_router from router_registry instead.
"""

from pulldb.web.routes import router

# HCA-compliant router (feature-based)
from pulldb.web.router_registry import main_router as hca_router

__all__ = ["router", "hca_router"]
