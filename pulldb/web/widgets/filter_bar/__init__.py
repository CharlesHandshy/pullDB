from __future__ import annotations

"""Universal filter bar widget for list pages.

HCA Layer: widgets
Provides reusable filter/sort controls based on user security clearance.
Designed to live in the title bar of list pages.
"""

from dataclasses import dataclass, field
from enum import Enum

from pulldb.domain.models import JobStatus, UserRole


class SortOrder(Enum):
    """Sort direction."""

    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class FilterOption:
    """Single filter option for a dropdown."""

    value: str
    label: str
    selected: bool = False


@dataclass(frozen=True)
class FilterField:
    """Filter field definition."""

    name: str
    label: str
    field_type: str  # "text", "select", "date", "daterange"
    options: tuple[FilterOption, ...] = ()
    placeholder: str = ""
    value: str = ""
    min_role: UserRole = UserRole.USER  # Minimum role to see this filter


@dataclass(frozen=True)
class SortField:
    """Sort field definition."""

    name: str
    label: str
    current_order: SortOrder | None = None  # None = not sorted by this


@dataclass
class FilterBarConfig:
    """Configuration for a filter bar on a specific page."""

    page_key: str
    filters: list[FilterField] = field(default_factory=lambda: [])
    sort_fields: list[SortField] = field(default_factory=lambda: [])
    show_search: bool = True
    search_placeholder: str = "Search..."


def get_job_status_options(selected: str | None = None) -> tuple[FilterOption, ...]:
    """Get job status filter options."""
    return tuple(
        FilterOption(
            value=status.value,
            label=status.value.replace("_", " ").title(),
            selected=(status.value == selected),
        )
        for status in JobStatus
    )


def get_user_role_options(
    selected: str | None = None,
    include_all: bool = True,
) -> tuple[FilterOption, ...]:
    """Get user role filter options."""
    options: list[FilterOption] = []
    if include_all:
        options.append(
            FilterOption(value="", label="All Roles", selected=(selected is None))
        )
    options.extend(
        FilterOption(
            value=role.value,
            label=role.value.title(),
            selected=(role.value == selected),
        )
        for role in UserRole
    )
    return tuple(options)


# Pre-defined filter configurations for common list pages
JOB_LIST_FILTERS = FilterBarConfig(
    page_key="jobs",
    filters=[
        FilterField(
            name="status",
            label="Status",
            field_type="select",
            options=get_job_status_options(),
        ),
        FilterField(
            name="database",
            label="Database",
            field_type="text",
            placeholder="Filter by database...",
        ),
        FilterField(
            name="host",
            label="Host",
            field_type="text",
            placeholder="Filter by host...",
        ),
        FilterField(
            name="submitted_by",
            label="Submitted By",
            field_type="text",
            placeholder="Username...",
            min_role=UserRole.MANAGER,  # Only managers+ see this
        ),
        FilterField(
            name="date_range",
            label="Date Range",
            field_type="daterange",
        ),
    ],
    sort_fields=[
        SortField(name="created_at", label="Date"),
        SortField(name="status", label="Status"),
        SortField(name="database", label="Database"),
        SortField(name="submitted_by", label="User"),
    ],
    search_placeholder="Search jobs...",
)

USER_LIST_FILTERS = FilterBarConfig(
    page_key="users",
    filters=[
        FilterField(
            name="role",
            label="Role",
            field_type="select",
            options=get_user_role_options(),
        ),
        FilterField(
            name="is_active",
            label="Status",
            field_type="select",
            options=(
                FilterOption(value="", label="All"),
                FilterOption(value="1", label="Active"),
                FilterOption(value="0", label="Disabled"),
            ),
        ),
        FilterField(
            name="manager_id",
            label="Manager",
            field_type="select",
            options=(),  # Populated dynamically
            min_role=UserRole.ADMIN,  # Only admins see this
        ),
    ],
    sort_fields=[
        SortField(name="username", label="Username"),
        SortField(name="role", label="Role"),
        SortField(name="created_at", label="Created"),
        SortField(name="last_login", label="Last Login"),
    ],
    search_placeholder="Search users...",
)

AUDIT_LOG_FILTERS = FilterBarConfig(
    page_key="audit",
    filters=[
        FilterField(
            name="action",
            label="Action",
            field_type="select",
            options=(
                FilterOption(value="", label="All Actions"),
                FilterOption(value="LOGIN", label="Login"),
                FilterOption(value="LOGOUT", label="Logout"),
                FilterOption(value="JOB_SUBMIT", label="Job Submit"),
                FilterOption(value="JOB_CANCEL", label="Job Cancel"),
                FilterOption(value="USER_CREATE", label="User Create"),
                FilterOption(value="USER_UPDATE", label="User Update"),
                FilterOption(value="PASSWORD_RESET", label="Password Reset"),
            ),
        ),
        FilterField(
            name="username",
            label="User",
            field_type="text",
            placeholder="Filter by user...",
        ),
        FilterField(
            name="date_range",
            label="Date Range",
            field_type="daterange",
        ),
    ],
    sort_fields=[
        SortField(name="timestamp", label="Time"),
        SortField(name="action", label="Action"),
        SortField(name="username", label="User"),
    ],
    search_placeholder="Search audit logs...",
)


def get_filter_config(page_key: str) -> FilterBarConfig | None:
    """Get filter configuration for a page.

    Args:
        page_key: Page identifier.

    Returns:
        FilterBarConfig or None if no config exists.
    """
    configs = {
        "jobs": JOB_LIST_FILTERS,
        "my_jobs": JOB_LIST_FILTERS,
        "admin_jobs": JOB_LIST_FILTERS,
        "users": USER_LIST_FILTERS,
        "admin_users": USER_LIST_FILTERS,
        "manager_team": USER_LIST_FILTERS,
        "audit": AUDIT_LOG_FILTERS,
    }
    return configs.get(page_key)


def filter_fields_for_role(
    config: FilterBarConfig,
    user_role: UserRole,
) -> list[FilterField]:
    """Get filter fields available to a user based on their role.

    Args:
        config: Filter bar configuration.
        user_role: Current user's role.

    Returns:
        List of FilterFields the user can access.
    """
    role_order = {UserRole.USER: 0, UserRole.MANAGER: 1, UserRole.ADMIN: 2}
    user_level = role_order[user_role]

    return [f for f in config.filters if role_order[f.min_role] <= user_level]


@dataclass
class AppliedFilters:
    """Container for filters applied from query params."""

    filters: dict[str, str] = field(default_factory=lambda: {})
    sort_by: str | None = None
    sort_order: SortOrder = SortOrder.DESC
    search: str = ""
    page: int = 1
    per_page: int = 25


def parse_filter_params(
    query_params: dict[str, str],
    config: FilterBarConfig,
) -> AppliedFilters:
    """Parse query parameters into AppliedFilters.

    Args:
        query_params: Request query parameters.
        config: Filter configuration for the page.

    Returns:
        AppliedFilters instance.
    """
    filters: dict[str, str] = {}
    for filter_field in config.filters:
        if filter_field.name in query_params:
            filters[filter_field.name] = query_params[filter_field.name]

    sort_by = query_params.get("sort")
    sort_order_str = query_params.get("order", "desc")
    sort_order = SortOrder.ASC if sort_order_str == "asc" else SortOrder.DESC

    search = query_params.get("q", "")
    page = int(query_params.get("page", "1"))
    per_page = int(query_params.get("per_page", "25"))

    return AppliedFilters(
        filters=filters,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        page=page,
        per_page=per_page,
    )


__all__ = [
    # Constants
    "AUDIT_LOG_FILTERS",
    "JOB_LIST_FILTERS",
    "USER_LIST_FILTERS",
    # Classes
    "AppliedFilters",
    "FilterBarConfig",
    "FilterField",
    "FilterOption",
    "SortField",
    "SortOrder",
    # Functions
    "filter_fields_for_role",
    "get_filter_config",
    "get_job_status_options",
    "get_user_role_options",
    "parse_filter_params",
]
