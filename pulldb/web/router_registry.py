"""Router registry for pullDB web UI.

HCA Layer: Foundation
Purpose: Central registry that imports and aggregates all feature routers.

This is the single entry point for including all web routes in the FastAPI app.
Each feature module exports its own router, which is included here.
"""

from __future__ import annotations

from fastapi import APIRouter

# Import all feature routers
from pulldb.web.features.auth.routes import router as auth_router
from pulldb.web.features.dashboard.routes import router as dashboard_router
from pulldb.web.features.job_view.routes import router as job_view_router
from pulldb.web.features.restore.routes import router as restore_router
from pulldb.web.features.search.routes import router as search_router
from pulldb.web.features.admin.routes import router as admin_router
from pulldb.web.features.admin.logo_routes import router as admin_logo_router

# Main router that aggregates all feature routers
main_router = APIRouter()

# Include all feature routers
main_router.include_router(auth_router)
main_router.include_router(dashboard_router)
main_router.include_router(job_view_router)
main_router.include_router(restore_router)
main_router.include_router(search_router)
main_router.include_router(admin_router)
main_router.include_router(admin_logo_router)

# Export for use in main application
__all__ = ["main_router"]
