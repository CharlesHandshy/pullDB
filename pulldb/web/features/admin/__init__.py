"""Admin feature module for pullDB web UI."""

from pulldb.web.features.admin.routes import router
from pulldb.web.features.admin.logo_routes import router as logo_router

__all__ = ["router", "logo_router"]
