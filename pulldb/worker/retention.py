"""Database retention and lifecycle management service.

Handles expiration, locking, and cleanup of restored databases. Provides
business logic for the maintenance modal and scheduled cleanup operations.

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pulldb.domain.models import Job, JobStatus, MaintenanceItems


if TYPE_CHECKING:
    from pulldb.infra.mysql import JobRepository, SettingsRepository, UserRepository


logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RetentionCleanupResult:
    """Result of a retention-based cleanup run."""

    started_at: datetime
    completed_at: datetime | None = None
    grace_days: int = 7
    candidates_found: int = 0
    databases_dropped: int = 0
    databases_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    dropped_jobs: list[str] = field(default_factory=list)  # Job IDs


@dataclass
class MaintenanceAction:
    """A single action from the maintenance modal."""

    job_id: str
    action: str  # "now", "unlock", or number of months as string ("1", "3", etc.)


# =============================================================================
# Retention Service
# =============================================================================


class RetentionService:
    """Service for managing database retention and lifecycle.

    Provides business logic for:
    - Extending database expiration
    - Locking/unlocking databases
    - Processing maintenance acknowledgments
    - Running retention-based cleanup
    - Checking for locked targets (restore blocking)
    """

    def __init__(
        self,
        job_repo: "JobRepository",
        user_repo: "UserRepository",
        settings_repo: "SettingsRepository",
    ) -> None:
        """Initialize retention service.

        Args:
            job_repo: Job repository for database operations.
            user_repo: User repository for maintenance ack tracking.
            settings_repo: Settings repository for retention config.
        """
        self.job_repo = job_repo
        self.user_repo = user_repo
        self.settings_repo = settings_repo

    def extend_job(self, job_id: str, months: int, user_id: str) -> bool:
        """Extend a job's database expiration.

        Args:
            job_id: Job ID to extend.
            months: Number of months to extend. If current expires_at is set,
                   extends from that date; otherwise extends from today.
                   months=0 means set to now (immediate cleanup).
            user_id: User performing the action (for audit).

        Returns:
            True if extended successfully, False if job not found.
        """
        job = self.job_repo.get_job_by_id(job_id)
        if not job:
            logger.warning("extend_job_not_found", job_id=job_id)
            return False

        if job.status not in (JobStatus.DEPLOYED, JobStatus.COMPLETE):
            logger.warning(
                "extend_job_not_deployed",
                job_id=job_id,
                status=job.status.value,
            )
            return False

        max_months = self.settings_repo.get_max_retention_months()
        if months > max_months:
            months = max_months

        now = datetime.now(UTC).replace(tzinfo=None)
        
        if months == 0:
            # Setting to "now" for immediate cleanup
            new_expires_at = now
            event_detail = f"Set expiration to now ({new_expires_at.isoformat()}) for immediate cleanup"
        else:
            # Extend from current expires_at if set, otherwise from today
            base_date = job.expires_at if job.expires_at else now
            # If base_date is in the past, use today instead
            if base_date < now:
                base_date = now
            new_expires_at = base_date + timedelta(days=months * 30)
            
            if job.expires_at:
                event_detail = f"Extended expiration by {months} month(s) from {job.expires_at.isoformat()} to {new_expires_at.isoformat()}"
            else:
                event_detail = f"Set expiration to {months} month(s) from now: {new_expires_at.isoformat()}"
        
        self.job_repo.set_job_expiration(job_id, new_expires_at)

        self.job_repo.append_job_event(
            job_id,
            "expiration_extended",
            event_detail,
        )

        logger.info(
            "job_expiration_extended",
            job_id=job_id,
            user_id=user_id,
            months=months,
            new_expires_at=new_expires_at.isoformat(),
        )
        return True

    def lock_job(self, job_id: str, user_id: str, username: str) -> bool:
        """Lock a job's database to protect from cleanup and overwrites.

        Args:
            job_id: Job ID to lock.
            user_id: User performing the action (for audit).
            username: Username for the locked_by field.

        Returns:
            True if locked successfully, False if job not found or already locked.
        """
        job = self.job_repo.get_job_by_id(job_id)
        if not job:
            logger.warning("lock_job_not_found", job_id=job_id)
            return False

        if job.status not in (JobStatus.DEPLOYED, JobStatus.COMPLETE):
            logger.warning(
                "lock_job_not_deployed",
                job_id=job_id,
                status=job.status.value,
            )
            return False

        if job.is_locked:
            logger.info("lock_job_already_locked", job_id=job_id)
            return False

        success = self.job_repo.lock_job(job_id, username)
        if success:
            self.job_repo.append_job_event(
                job_id,
                "database_locked",
                f"Locked by {username}",
            )
            logger.info(
                "job_database_locked",
                job_id=job_id,
                user_id=user_id,
                locked_by=username,
            )
        return success

    def unlock_job(self, job_id: str, user_id: str) -> bool:
        """Unlock a job's database.

        Args:
            job_id: Job ID to unlock.
            user_id: User performing the action (for audit).

        Returns:
            True if unlocked successfully, False if job not found or wasn't locked.
        """
        job = self.job_repo.get_job_by_id(job_id)
        if not job:
            logger.warning("unlock_job_not_found", job_id=job_id)
            return False

        if not job.is_locked:
            logger.info("unlock_job_not_locked", job_id=job_id)
            return False

        success = self.job_repo.unlock_job(job_id)
        if success:
            self.job_repo.append_job_event(
                job_id,
                "database_unlocked",
                f"Unlocked by user {user_id}",
            )
            logger.info(
                "job_database_unlocked",
                job_id=job_id,
                user_id=user_id,
            )
        return success

    def mark_for_removal(self, job_id: str, user_id: str) -> bool:
        """Mark a job's database for immediate removal.

        Sets expires_at to a past date so it will be picked up by next cleanup.

        Args:
            job_id: Job ID to mark.
            user_id: User performing the action (for audit).

        Returns:
            True if marked successfully, False if job not found or locked.
        """
        job = self.job_repo.get_job_by_id(job_id)
        if not job:
            logger.warning("mark_for_removal_not_found", job_id=job_id)
            return False

        if job.is_locked:
            logger.warning(
                "mark_for_removal_locked",
                job_id=job_id,
                locked_by=job.locked_by,
            )
            return False

        # Set expires_at to yesterday to make it eligible for cleanup
        past_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        self.job_repo.set_job_expiration(job_id, past_date)

        self.job_repo.append_job_event(
            job_id,
            "marked_for_removal",
            f"Marked for removal by user {user_id}",
        )

        logger.info(
            "job_marked_for_removal",
            job_id=job_id,
            user_id=user_id,
        )
        return True

    def check_target_locked(
        self, target: str, dbhost: str, owner_user_id: str
    ) -> Job | None:
        """Check if a target database is locked.

        Used before submitting a new restore to prevent overwriting locked databases.

        Args:
            target: Target database name.
            dbhost: Database host.
            owner_user_id: User ID attempting the restore.

        Returns:
            The locked Job if found, None otherwise.
        """
        return self.job_repo.get_locked_by_target(target, dbhost, owner_user_id)

    def get_maintenance_items(self, user_id: str) -> MaintenanceItems:
        """Get maintenance items for a user's daily modal.

        Args:
            user_id: User ID to get items for.

        Returns:
            MaintenanceItems with expired, expiring, and locked lists.
        """
        notice_days = self.settings_repo.get_expiring_notice_days()
        grace_days = self.settings_repo.get_cleanup_grace_days()
        return self.job_repo.get_maintenance_items(user_id, notice_days, grace_days)

    def should_show_maintenance_modal(self, user_id: str) -> bool:
        """Check if user should see the maintenance modal.

        Returns True if:
        - User hasn't acknowledged today
        - User has any maintenance items (expired, expiring, or locked)

        Args:
            user_id: User ID to check.

        Returns:
            True if modal should be shown.
        """
        # Check if already acknowledged today
        if not self.user_repo.needs_maintenance_ack(user_id):
            return False

        # Check if there are any items to show
        items = self.get_maintenance_items(user_id)
        return items.has_items

    def process_maintenance_acknowledgment(
        self,
        user_id: str,
        username: str,
        actions: list[MaintenanceAction],
    ) -> dict[str, bool]:
        """Process maintenance modal actions and record acknowledgment.

        Args:
            user_id: User ID acknowledging.
            username: Username for lock_job operations.
            actions: List of actions from the modal.

        Returns:
            Dict mapping job_id to success status for each action.
        """
        results: dict[str, bool] = {}

        for action in actions:
            if not action.action:
                # Empty action = skipped, no processing needed
                results[action.job_id] = True
                continue

            if action.action == "now":
                results[action.job_id] = self.mark_for_removal(action.job_id, user_id)
            elif action.action == "unlock":
                results[action.job_id] = self.unlock_job(action.job_id, user_id)
            elif action.action.isdigit():
                months = int(action.action)
                results[action.job_id] = self.extend_job(action.job_id, months, user_id)
            else:
                logger.warning(
                    "unknown_maintenance_action",
                    job_id=action.job_id,
                    action=action.action,
                )
                results[action.job_id] = False

        # Always record acknowledgment, regardless of actions taken
        from datetime import date

        self.user_repo.set_last_maintenance_ack(user_id, date.today())

        logger.info(
            "maintenance_acknowledged",
            user_id=user_id,
            actions_processed=len(actions),
            actions_skipped=sum(1 for a in actions if not a.action),
        )

        return results

    def get_retention_options(self, include_now: bool = False) -> list[tuple[str, str]]:
        """Get retention dropdown options based on settings.

        Args:
            include_now: Whether to include "Now" option.

        Returns:
            List of (value, label) tuples.
        """
        return self.settings_repo.get_retention_options(include_now=include_now)
