"""API routers for pullDB.

Each sub-module provides a create_*_router() factory that accepts shared
dependencies (get_api_state, require_auth, etc.) via closure and returns
a FastAPI APIRouter ready to include in the main app.

HCA Layer: pages (API routes)
"""
