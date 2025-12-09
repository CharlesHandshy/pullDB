"""Breadcrumb widget for navigation context.

HCA Layer: widgets
Provides reusable breadcrumb trail component for all pages.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BreadcrumbItem:
    """Single breadcrumb item."""

    label: str
    url: str | None = None  # None = current page (no link)
    icon: str | None = None  # Optional icon name


def build_breadcrumbs(*items: tuple[str, str | None]) -> list[BreadcrumbItem]:
    """Build breadcrumb list from tuples.

    Args:
        *items: Tuples of (label, url). Last item should have url=None.

    Returns:
        List of BreadcrumbItem instances.

    Example:
        >>> build_breadcrumbs(
        ...     ("Dashboard", "/web/dashboard"),
        ...     ("Team Management", "/web/manager"),
        ...     ("Create User", None),  # Current page
        ... )
    """
    return [BreadcrumbItem(label=label, url=url) for label, url in items]


# Pre-defined breadcrumb paths for common pages
# Type: dict[str, list[tuple[str, str | None]]]
BREADCRUMB_PATHS: dict[str, list[tuple[str, str | None]]] = {
    # Main section
    "dashboard": [("Dashboard", None)],
    "my_jobs": [("Dashboard", "/web/dashboard"), ("My Jobs", None)],
    "restore": [("Dashboard", "/web/dashboard"), ("New Restore", None)],
    "search": [("Dashboard", "/web/dashboard"), ("Search Backups", None)],
    "job_search": [("Dashboard", "/web/dashboard"), ("Search Jobs", None)],
    "history": [("Dashboard", "/web/dashboard"), ("Job History", None)],
    "audit": [("Dashboard", "/web/dashboard"), ("Audit Logs", None)],

    # Job detail
    "job_detail": [("Dashboard", "/web/dashboard"), ("Job", None)],

    # Team Management section
    "manager": [("Dashboard", "/web/dashboard"), ("Team Management", None)],
    "manager_team": [
        ("Dashboard", "/web/dashboard"),
        ("Team Management", "/web/manager"),
        ("My Team", None),
    ],
    "manager_create_user": [
        ("Dashboard", "/web/dashboard"),
        ("Team Management", "/web/manager"),
        ("Create User", None),
    ],
    "manager_submit_for_user": [
        ("Dashboard", "/web/dashboard"),
        ("Team Management", "/web/manager"),
        ("Submit for User", None),
    ],
    "manager_user_detail": [
        ("Dashboard", "/web/dashboard"),
        ("Team Management", "/web/manager"),
        ("My Team", "/web/manager/my-team"),
        ("User", None),  # Will be replaced with username
    ],

    # Administration section
    "admin": [("Dashboard", "/web/dashboard"), ("Administration", None)],
    "admin_jobs": [
        ("Dashboard", "/web/dashboard"),
        ("Administration", "/web/admin"),
        ("All Jobs", None),
    ],
    "admin_users": [
        ("Dashboard", "/web/dashboard"),
        ("Administration", "/web/admin"),
        ("Users", None),
    ],
    "admin_user_detail": [
        ("Dashboard", "/web/dashboard"),
        ("Administration", "/web/admin"),
        ("Users", "/web/admin/users"),
        ("User", None),  # Will be replaced with username
    ],
    "admin_hosts": [
        ("Dashboard", "/web/dashboard"),
        ("Administration", "/web/admin"),
        ("Hosts", None),
    ],
    "admin_settings": [
        ("Dashboard", "/web/dashboard"),
        ("Administration", "/web/admin"),
        ("Settings", None),
    ],
    "admin_cleanup": [
        ("Dashboard", "/web/dashboard"),
        ("Administration", "/web/admin"),
        ("Cleanup", None),
    ],
    "admin_maintenance": [
        ("Dashboard", "/web/dashboard"),
        ("Administration", "/web/admin"),
        ("Maintenance", None),
    ],
}


def get_breadcrumbs(
    page_key: str,
    **replacements: str,
) -> list[BreadcrumbItem]:
    """Get breadcrumbs for a page with optional replacements.

    Args:
        page_key: Key from BREADCRUMB_PATHS.
        **replacements: Label replacements, e.g., user="jsmith"

    Returns:
        List of BreadcrumbItem for the page.

    Example:
        >>> get_breadcrumbs("manager_user_detail", user="jsmith")
        # Returns breadcrumbs with "jsmith" instead of "User"
    """
    if page_key not in BREADCRUMB_PATHS:
        return [BreadcrumbItem(label="Home", url="/web/dashboard")]

    items: list[BreadcrumbItem] = []
    for base_label, item_url in BREADCRUMB_PATHS[page_key]:
        # Check for replacements
        replacement_key = base_label.lower()
        final_label = replacements.get(replacement_key, base_label)
        items.append(BreadcrumbItem(label=final_label, url=item_url))

    return items


__all__ = ["BREADCRUMB_PATHS", "BreadcrumbItem", "build_breadcrumbs", "get_breadcrumbs"]
