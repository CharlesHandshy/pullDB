from __future__ import annotations

"""Contract interfaces for pullDB Web UI.

HCA Layer: shared

Defines interfaces that modules depend on, not implementations.
"""

from pulldb.web.shared.contracts.page_contracts import (
    AdminContext,
    DashboardContext,
    ErrorPageContext,
    JobDetailContext,
    PageContext,
    PageRenderer,
)
from pulldb.web.shared.contracts.service_contracts import (
    AuthService,
    JobRepository,
    UserRepository,
)

__all__ = [
    # Page contexts
    "PageContext",
    "ErrorPageContext",
    "DashboardContext",
    "JobDetailContext",
    "AdminContext",
    "PageRenderer",
    # Service contracts
    "AuthService",
    "UserRepository",
    "JobRepository",
]
