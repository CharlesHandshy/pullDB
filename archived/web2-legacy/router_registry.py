from fastapi import APIRouter
from pulldb.web2.features.dashboard.routes import router as dashboard_router
from pulldb.web2.features.restore.routes import router as restore_router
from pulldb.web2.features.jobs.routes import router as jobs_router
from pulldb.web2.features.admin.routes import router as admin_router
from pulldb.web2.features.manager.routes import router as manager_router
from pulldb.web2.features.auth.routes import router as auth_router

main_router = APIRouter()
main_router.include_router(dashboard_router)
main_router.include_router(restore_router)
main_router.include_router(jobs_router)
main_router.include_router(admin_router)
main_router.include_router(manager_router)
main_router.include_router(auth_router)

__all__ = ["main_router"]