from __future__ import annotations

"""Audit feature module for pullDB Web UI.

HCA Layer: features
Purpose: Audit log browsing for administrators.
"""

from pulldb.web.features.audit.routes import router

__all__ = ["router"]
