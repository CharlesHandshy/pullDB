"""Service interface contracts for pullDB Web UI.

HCA Layer: shared

Defines interfaces for services that features depend on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pulldb.domain.models import User


class AuthService(Protocol):
    """Protocol for authentication service."""

    def validate_session(self, session_token: str) -> str | None:
        """Validate session token and return user_id if valid."""
        ...

    def create_session(self, user_id: str) -> str:
        """Create a new session for user, return session token."""
        ...

    def destroy_session(self, session_token: str) -> None:
        """Destroy/invalidate a session."""
        ...


class UserRepository(Protocol):
    """Protocol for user data access."""

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        ...

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username."""
        ...

    def list_users(self) -> list[User]:
        """List all users."""
        ...


class JobRepository(Protocol):
    """Protocol for job data access."""

    def get_job_by_id(self, job_id: str) -> object | None:
        """Get job by ID."""
        ...

    def get_recent_jobs(self, limit: int = 50) -> list[object]:
        """Get recent jobs."""
        ...

    def get_active_jobs(self) -> list[object]:
        """Get currently active jobs."""
        ...

    def get_job_events(self, job_id: str) -> list[object]:
        """Get events for a job."""
        ...
