"""Bulk action widget for admin operations.

HCA Layer: widgets
Provides reusable bulk action controls for admin pages.
Admin-only feature for mass user management.
"""

from dataclasses import dataclass
from enum import Enum


class BulkActionType(Enum):
    """Types of bulk actions available."""

    DISABLE_USERS = "disable_users"
    ENABLE_USERS = "enable_users"
    REASSIGN_USERS = "reassign_users"


@dataclass(frozen=True)
class BulkAction:
    """Definition of a bulk action."""

    action_type: BulkActionType
    label: str
    icon: str
    confirm_message: str
    requires_selection: bool = True
    requires_target: bool = False  # e.g., reassign needs target manager


# Pre-defined bulk actions for admin user management
BULK_USER_ACTIONS: tuple[BulkAction, ...] = (
    BulkAction(
        action_type=BulkActionType.DISABLE_USERS,
        label="Disable Selected",
        icon="ban",
        confirm_message="Disable {count} selected user(s)?",
        requires_selection=True,
    ),
    BulkAction(
        action_type=BulkActionType.ENABLE_USERS,
        label="Enable Selected",
        icon="check-circle",
        confirm_message="Enable {count} selected user(s)?",
        requires_selection=True,
    ),
    BulkAction(
        action_type=BulkActionType.REASSIGN_USERS,
        label="Reassign to Manager",
        icon="user-switch",
        confirm_message="Reassign {count} selected user(s) to {target}?",
        requires_selection=True,
        requires_target=True,
    ),
)


@dataclass
class BulkActionRequest:
    """Request to perform a bulk action."""

    action_type: BulkActionType
    selected_ids: list[int]
    target_id: int | None = None  # For reassign


@dataclass
class BulkActionResult:
    """Result of a bulk action."""

    success: bool
    action_type: BulkActionType
    affected_count: int
    message: str
    errors: list[str] | None = None


def validate_bulk_action(
    request: BulkActionRequest,
    action_def: BulkAction,
) -> tuple[bool, str | None]:
    """Validate a bulk action request.

    Args:
        request: The bulk action request.
        action_def: The action definition.

    Returns:
        Tuple of (is_valid, error_message).
    """
    if action_def.requires_selection and not request.selected_ids:
        return False, "No items selected"

    if action_def.requires_target and request.target_id is None:
        return False, "Target required for this action"

    return True, None


def get_action_definition(action_type: BulkActionType) -> BulkAction | None:
    """Get the action definition for a given type.

    Args:
        action_type: The action type to look up.

    Returns:
        BulkAction definition or None if not found.
    """
    for action in BULK_USER_ACTIONS:
        if action.action_type == action_type:
            return action
    return None


__all__ = [
    # Constants
    "BULK_USER_ACTIONS",
    # Classes
    "BulkAction",
    "BulkActionRequest",
    "BulkActionResult",
    "BulkActionType",
    # Functions
    "get_action_definition",
    "validate_bulk_action",
]
