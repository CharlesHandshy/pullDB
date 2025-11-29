"""RBAC permission checks for pullDB.

Phase 4: Role-based access control helpers. These functions implement
the permission matrix defined in the roadmap.

Permission Matrix:
| Operation        | user | manager | admin |
|------------------|------|---------|-------|
| Submit own job   |  ✓   |    ✓    |   ✓   |
| View own jobs    |  ✓   |    ✓    |   ✓   |
| Cancel own job   |  ✓   |    ✓    |   ✓   |
| View all jobs    |  ✗   |    ✓    |   ✓   |
| Cancel any job   |  ✗   |    ✓    |   ✓   |
| Submit for others|  ✗   |    ✓    |   ✓   |
| Manage users     |  ✗   |    ✗    |   ✓   |
| System config    |  ✗   |    ✗    |   ✓   |
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


def can_cancel_job(user: User, job_owner_id: str) -> bool:
    """Check if user can cancel a specific job.

    Managers and admins can cancel any job. Regular users can only
    cancel their own jobs.

    Args:
        user: The user attempting to cancel.
        job_owner_id: The user_id of the job owner.

    Returns:
        True if user can cancel the job, False otherwise.
    """
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.MANAGER:
        return True  # Managers can cancel any
    return user.user_id == job_owner_id


def can_submit_for_user(actor: User, target_user_id: str) -> bool:
    """Check if actor can submit jobs for target user.

    Managers and admins can submit jobs for any user. Regular users
    can only submit jobs for themselves.

    Args:
        actor: The user attempting to submit.
        target_user_id: The user_id to submit the job for.

    Returns:
        True if actor can submit for target, False otherwise.
    """
    if actor.role == UserRole.ADMIN:
        return True
    if actor.role == UserRole.MANAGER:
        return True
    return actor.user_id == target_user_id


def can_manage_users(user: User) -> bool:
    """Check if user can manage other users.

    Only admins can add, remove, or modify users.

    Args:
        user: The user to check.

    Returns:
        True if user can manage users, False otherwise.
    """
    return user.role == UserRole.ADMIN


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
