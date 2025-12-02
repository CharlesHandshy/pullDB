"""Page interface contracts for pullDB Web UI.

HCA Layer 0: Shared contracts
Purpose: Define the contract for page context data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pulldb.domain.models import User


@dataclass
class PageContext:
    """Base context data required for all pages.
    
    All page templates expect these fields to be present.
    Features can extend this with additional fields.
    """
    
    user: User | None = None
    title: str = "pullDB"
    
    # Flash messages
    error: str | None = None
    success: str | None = None
    warning: str | None = None
    
    # Navigation state
    active_nav: str | None = None
    breadcrumbs: list[dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for template rendering."""
        return {
            "user": self.user,
            "title": self.title,
            "error": self.error,
            "success": self.success,
            "warning": self.warning,
            "active_nav": self.active_nav,
            "breadcrumbs": self.breadcrumbs,
        }


@dataclass
class ErrorPageContext(PageContext):
    """Context for error pages."""
    
    status_code: int = 500
    error_title: str = "Error"
    message: str = "An unexpected error occurred."
    detail: str | None = None
    suggestions: list[str] = field(default_factory=list)
    back_url: str | None = None


@dataclass 
class DashboardContext(PageContext):
    """Context for dashboard page."""
    
    active_jobs: list[Any] = field(default_factory=list)
    recent_jobs: list[Any] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    

@dataclass
class JobDetailContext(PageContext):
    """Context for job detail page."""
    
    job: Any = None
    events: list[Any] = field(default_factory=list)
    can_cancel: bool = False
    back_tab: str | None = None


@dataclass
class AdminContext(PageContext):
    """Base context for admin pages."""
    
    stats: dict[str, int] = field(default_factory=dict)
    

class PageRenderer(Protocol):
    """Protocol for page rendering functions.
    
    All page renderers must accept a context and return HTML.
    """
    
    def __call__(self, context: PageContext) -> str:
        """Render the page with the given context."""
        ...
