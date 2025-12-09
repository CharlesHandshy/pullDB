"""RBAC permission checks for pullDB.

Phase 4: Role-based access control helpers. These functions implement
the permission matrix defined in the roadmap.

Permission Matrix:
| Operation          | user | manager              | admin |
|--------------------|------|----------------------|-------|
| Submit own job     |  ✓   |    ✓                 |   ✓   |
| View own jobs      |  ✓   |    ✓                 |   ✓   |
| Cancel own job     |  ✓   |    ✓                 |   ✓   |
| View all jobs      |  ✗   |    ✓                 |   ✓   |
| Cancel any job     |  ✗   |    ✓                 |   ✓   |
| Submit for others  |  ✗   |    ✓ (managed users) |   ✓   |
| Create users       |  ✗   |    ✓ (become manager)|   ✓   |
| Manage own users   |  ✗   |    ✓                 |   ✓   |
| Manage all users   |  ✗   |    ✗                 |   ✓   |
| System config      |  ✗   |    ✗                 |   ✓   |
| View audit logs    |  ✓   |    ✓                 |   ✓   |

Manager Constraints:
- Managers can create new users (those users are automatically assigned to them)
- Managers can only modify/disable users they manage (manager_id = their user_id)
- Managers can submit jobs FOR users they manage (job owner = target user for naming)
- All "submit for user" actions are audit logged
- Anyone can view audit logs (transparency)
"""

from __future__ import annotations

from pulldb.domain.models import User, UserRole


def can_view_job(user: User, job_owner_id: str) -> bool:
    """Check if user can view a specific job.

    Managers and admins can view all jobs. Regular users can only
    view their own jobs.

    Args:
        user: The user attempting to view.
        job_owner_id: The user_id of the job owner.

    Returns:
        True if user can view the job, False otherwise.
    """
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.MANAGER:
        return True  # Managers can view all
    return user.user_id == job_owner_id


def can_cancel_job(user: User, job_owner_id: str, job_owner_manager_id: str | None = None) -> bool:
    """Check if user can cancel a specific job.

    Admins can cancel any job.
    Managers can only cancel jobs owned by users they manage.
    Regular users can only cancel their own jobs.

    Args:
        user: The user attempting to cancel.
        job_owner_id: The user_id of the job owner.
        job_owner_manager_id: The manager_id of the job owner (who manages them).

    Returns:
        True if user can cancel the job, False otherwise.
    """
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.MANAGER:
        # Managers can only cancel jobs for users they manage
        return job_owner_manager_id == user.user_id
    return user.user_id == job_owner_id


def can_submit_for_user(actor: User, target_user: User) -> bool:
    """Check if actor can submit jobs for target user.

    Admins can submit for any user.
    Managers can submit for users they manage (target.manager_id == actor.user_id).
    Regular users can only submit for themselves.

    When a manager submits for a user:
    - The job is created with the TARGET user's identity (for correct DB naming)
    - An audit log entry records: "manager X submitted job for user Y"

    Args:
        actor: The user attempting to submit.
        target_user: The user the job will be submitted for.

    Returns:
        True if actor can submit for target, False otherwise.
    """
    if actor.role == UserRole.ADMIN:
        return True
    if actor.role == UserRole.MANAGER:
        # Manager can submit for users they manage
        if target_user.manager_id == actor.user_id:
            return True
        # Manager can also submit for themselves
        if target_user.user_id == actor.user_id:
            return True
        return False
    return actor.user_id == target_user.user_id


def can_manage_users(user: User) -> bool:
    """Check if user can create new users.

    Admins can create any user.
    Managers can create users (who become their managed users).

    Args:
        user: The user to check.

    Returns:
        True if user can create users, False otherwise.
    """
    return user.role in (UserRole.MANAGER, UserRole.ADMIN)


def can_manage_user(actor: User, target_user: User) -> bool:
    """Check if actor can manage (modify/disable) a specific user.

    Admins can manage any user.
    Managers can only manage users they created (target.manager_id == actor.user_id).

    Args:
        actor: The user attempting to manage.
        target_user: The user being managed.

    Returns:
        True if actor can manage target, False otherwise.
    """
    if actor.role == UserRole.ADMIN:
        return True
    if actor.role == UserRole.MANAGER:
        return target_user.manager_id == actor.user_id
    return False


def can_reset_password(actor: User, target_user: User) -> bool:
    """Check if actor can reset target user's password.

    Users can always change their own password.
    Managers can issue password reset for their managed users.
    Admins can issue password reset for any user.

    Note: This only allows ISSUING a reset (marking the flag).
    Users must set their own new password via CLI.

    Args:
        actor: The user attempting to issue reset.
        target_user: The user whose password will be marked for reset.

    Returns:
        True if actor can reset password, False otherwise.
    """
    # Users can always change their own password
    if actor.user_id == target_user.user_id:
        return True
    # Admins can reset anyone
    if actor.role == UserRole.ADMIN:
        return True
    # Managers can reset their managed users
    if actor.role == UserRole.MANAGER:
        return target_user.manager_id == actor.user_id
    return False


def can_reassign_user(actor: User) -> bool:
    """Check if actor can reassign users to different managers.

    Only admins can reassign users between managers.

    Args:
        actor: The user attempting to reassign.

    Returns:
        True if actor can reassign users, False otherwise.
    """
    return actor.role == UserRole.ADMIN


def can_bulk_manage_users(actor: User) -> bool:
    """Check if actor can perform bulk user operations.

    Only admins can bulk enable/disable/reassign users.

    Args:
        actor: The user attempting bulk operations.

    Returns:
        True if actor can perform bulk operations, False otherwise.
    """
    return actor.role == UserRole.ADMIN


def can_change_user_role(actor: User, target_user: User, new_role: UserRole) -> bool:
    """Check if actor can change target user's role.

    Only admins can change roles.
    Managers cannot promote users to manager/admin.

    Args:
        actor: The user attempting the change.
        target_user: The user whose role is being changed.
        new_role: The new role to assign.

    Returns:
        True if actor can change role, False otherwise.
    """
    # Only admins can change roles
    return actor.role == UserRole.ADMIN


def can_manage_config(user: User) -> bool:
    """Check if user can modify system configuration.

    Only admins can change system settings.

    Args:
        user: The user to check.

    Returns:
        True if user can manage config, False otherwise.
    """
    return user.role == UserRole.ADMIN


def can_view_all_jobs(user: User) -> bool:
    """Check if user can view all jobs across the system.

    Managers and admins can view all jobs. Regular users see
    only their own jobs.

    Args:
        user: The user to check.

    Returns:
        True if user can view all jobs, False otherwise.
    """
    return user.role in (UserRole.MANAGER, UserRole.ADMIN)


def require_role(user: User, *roles: UserRole) -> None:
    """Require user to have one of the specified roles.

    Args:
        user: The user to check.
        *roles: One or more required roles.

    Raises:
        PermissionError: If user does not have any of the required roles.
    """
    if user.role not in roles:
        role_names = ", ".join(r.value for r in roles)
        raise PermissionError(
            f"Operation requires role(s): {role_names}. "
            f"User '{user.username}' has role: {user.role.value}"
        )
