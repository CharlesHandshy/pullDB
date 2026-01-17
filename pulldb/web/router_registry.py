"""Router registry for pullDB web UI.

HCA Layer: Foundation
Purpose: Central registry that imports and aggregates all feature routers.

This is the single entry point for including all web routes in the FastAPI app.
Each feature module exports its own router, which is included here.
"""

from __future__ import annotations

from fastapi import APIRouter

# Import all feature routers (web2-style unified routes)
from pulldb.web.features.admin.routes import router as admin_router
from pulldb.web.features.audit.routes import router as audit_router
from pulldb.web.features.auth.routes import router as auth_router
from pulldb.web.features.dashboard.routes import router as dashboard_router
from pulldb.web.features.jobs.routes import router as jobs_router
from pulldb.web.features.manager.routes import router as manager_router
from pulldb.web.features.requests.routes import router as requests_router
from pulldb.web.features.restore.routes import router as restore_router

# Main router that aggregates all feature routers
main_router = APIRouter()

# Include all feature routers
main_router.include_router(auth_router)
main_router.include_router(dashboard_router)
main_router.include_router(jobs_router)
main_router.include_router(restore_router)
main_router.include_router(admin_router)
main_router.include_router(audit_router)
main_router.include_router(manager_router)
main_router.include_router(requests_router)

# Export for use in main application
__all__ = ["main_router"]
