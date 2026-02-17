"""Overlord companies management business logic.

Orchestrates operations on overlord.companies table with safety checks.
This is the main entry point for all overlord integration operations.

SAFETY RULES (enforced by this module):
1. ALWAYS verify job ownership before any operation
2. ALWAYS backup before modifying existing rows  
3. RESTORE if row existed before, DELETE only if we created it
4. LOG everything to audit trail

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pulldb.domain.overlord import (
    OverlordAlreadyClaimedError,
    OverlordCompany,
    OverlordExternalChangeError,
    OverlordOwnershipError,
    OverlordRowDeletedError,
    OverlordSafetyError,
    OverlordTracking,
    OverlordTrackingStatus,
)
from pulldb.infra.overlord import (
    OverlordConnection,
    OverlordRepository,
    OverlordTrackingRepository,
)

if TYPE_CHECKING:
    from pulldb.infra.mysql import AuditRepository, JobRepository, MySQLPool


logger = logging.getLogger(__name__)


# =============================================================================
# Release Actions
# =============================================================================


class ReleaseAction(str, Enum):
    """Action to take when releasing overlord control."""
    
    RESTORE = "restore"   # Restore original dbHost values
    CLEAR = "clear"       # Clear dbHost fields (set to empty)
    DELETE = "delete"     # Delete the row completely


@dataclass
class ReleaseResult:
    """Result of a release operation."""
    
    success: bool
    action_taken: ReleaseAction
    message: str
    restored_dbhost: str | None = None
    restored_dbhost_read: str | None = None
    external_change_detected: bool = False


@dataclass
class ExternalStateCheck:
    """Result of checking if overlord row was modified externally.
    
    Used to detect edge cases where external systems modified or deleted
    the overlord.companies row while pullDB had it claimed.
    """
    
    row_exists: bool
    """Whether the row still exists in overlord.companies"""
    
    dbhost_changed: bool
    """Whether dbHost differs from what we set"""
    
    subdomain_changed: bool
    """Whether subdomain differs from what we set"""
    
    current_dbhost: str | None
    """Current dbHost value in overlord (None if row deleted)"""
    
    expected_dbhost: str | None
    """dbHost value we expected (from tracking.current_dbhost)"""
    
    current_subdomain: str | None
    """Current subdomain value in overlord (None if row deleted)"""
    
    expected_subdomain: str | None
    """Subdomain value we expected (from tracking.current_subdomain)"""
    
    @property
    def is_safe_to_proceed(self) -> bool:
        """Check if it's safe to proceed with release."""
        # Safe if row exists and neither dbHost nor subdomain changed
        return self.row_exists and not self.dbhost_changed and not self.subdomain_changed


# =============================================================================
# Overlord Manager
# =============================================================================


class OverlordManager:
    """Manages overlord.companies integration with safety enforcement.
    
    This class coordinates between:
    - pulldb_service.overlord_tracking (our tracking table)
    - overlord.companies (external routing table)
    - pulldb_service.jobs (ownership verification)
    - pulldb_service.audit_logs (change tracking)
    
    Example:
        >>> manager = OverlordManager(pool, overlord_conn, job_repo, audit_repo)
        >>> 
        >>> # Claim and get current state
        >>> result = manager.claim("acme_prod", job_id, "user123")
        >>> 
        >>> # Update overlord record
        >>> manager.sync("acme_prod", job_id, {"dbHost": "new.host.com"})
        >>> 
        >>> # Release with restore
        >>> manager.release("acme_prod", job_id, ReleaseAction.RESTORE)
    """
    
    def __init__(
        self,
        pool: MySQLPool,
        overlord_connection: OverlordConnection | None,
        job_repo: JobRepository,
        audit_repo: AuditRepository,
        overlord_table: str = "companies",
    ) -> None:
        """Initialize manager.
        
        Args:
            pool: MySQL pool for pulldb_service database
            overlord_connection: Connection to overlord database (None if disabled)
            job_repo: Job repository for ownership verification
            audit_repo: Audit repository for logging
            overlord_table: Table name in overlord database
        """
        self._pool = pool
        self._tracking_repo = OverlordTrackingRepository(pool)
        self._job_repo = job_repo
        self._audit_repo = audit_repo
        
        # Overlord connection (may be None if feature disabled)
        self._overlord_conn = overlord_connection
        self._overlord_repo = (
            OverlordRepository(overlord_connection, overlord_table)
            if overlord_connection else None
        )
    
    @property
    def is_enabled(self) -> bool:
        """Check if overlord integration is enabled."""
        return self._overlord_conn is not None

    @property
    def overlord_repo(self) -> OverlordRepository | None:
        """Public accessor for the overlord repository."""
        return self._overlord_repo

    @property
    def tracking_repo(self) -> OverlordTrackingRepository | None:
        """Public accessor for the tracking repository."""
        return self._tracking_repo

    @property
    def overlord_conn(self) -> OverlordConnection | None:
        """Public accessor for the overlord connection."""
        return self._overlord_conn

    def replace_connection(
        self,
        new_conn: OverlordConnection,
        table: str = "companies",
    ) -> None:
        """Replace the overlord connection and recreate the repository.

        Used after provisioning to hot-swap credentials without a restart.

        Args:
            new_conn: New OverlordConnection instance
            table: Overlord table name (default 'companies')
        """
        self._overlord_conn = new_conn
        self._overlord_repo = OverlordRepository(new_conn, table)

    def refresh_credentials(self) -> bool:
        """Refresh overlord connection credentials from AWS Secrets Manager.
        
        Call this after rotating credentials to update the cached password
        without requiring a service restart.
        
        Returns:
            True if credentials were refreshed successfully
            
        Raises:
            OverlordConnectionError: If refresh fails or not enabled
        """
        if not self._overlord_conn:
            raise OverlordConnectionError("Overlord integration is not enabled")
        
        return self._overlord_conn.refresh_credentials()
    
    # -------------------------------------------------------------------------
    # Ownership Verification
    # -------------------------------------------------------------------------
    
    def verify_ownership(self, database_name: str, job_id: str) -> bool:
        """Verify the job owns this database.
        
        Args:
            database_name: Database name to check
            job_id: Job UUID claiming ownership
            
        Returns:
            True if job owns the database
            
        Raises:
            OverlordOwnershipError: If job doesn't own the database
        """
        job = self._job_repo.get_job_by_id(job_id)
        if not job:
            raise OverlordOwnershipError(f"Job {job_id} not found")
        
        if job.target != database_name:
            raise OverlordOwnershipError(
                f"Job {job_id} target is '{job.target}', not '{database_name}'"
            )
        
        if job.status.value != "deployed":
            raise OverlordOwnershipError(
                f"Job {job_id} is '{job.status.value}', not 'deployed'"
            )
        
        return True
    
    # -------------------------------------------------------------------------
    # Claim Operation
    # -------------------------------------------------------------------------
    
    def claim(
        self,
        database_name: str,
        job_id: str,
        created_by: str,
    ) -> OverlordTracking:
        """Claim a database for overlord management.
        
        Creates a tracking record and backs up current overlord state.
        
        Args:
            database_name: Database name to claim
            job_id: Job UUID
            created_by: User initiating the claim
            
        Returns:
            OverlordTracking record
            
        Raises:
            OverlordOwnershipError: If job doesn't own the database
            OverlordAlreadyClaimedError: If already claimed by another job
        """
        if not self.is_enabled:
            raise OverlordOwnershipError("Overlord integration is disabled")
        
        # Verify ownership
        self.verify_ownership(database_name, job_id)
        
        # Check if already claimed by another job
        existing = self._tracking_repo.get(database_name)
        if existing and existing.status != OverlordTrackingStatus.RELEASED:
            if existing.job_id != job_id:
                raise OverlordAlreadyClaimedError(
                    f"Database '{database_name}' is already claimed by job {existing.job_id}"
                )
            # Already claimed by this job - return existing
            return existing
        
        # Get current overlord state (if exists)
        current = self._overlord_repo.get_row_snapshot(database_name)
        
        # Create tracking record
        self._tracking_repo.create(
            database_name=database_name,
            job_id=job_id,
            job_target=database_name,
            created_by=created_by,
            row_existed_before=current is not None,
            previous_dbhost=current.get("dbHost") if current else None,
            previous_dbhost_read=current.get("dbHostRead") if current else None,
            previous_snapshot=current,
            company_id=current.get("companyID") if current else None,
        )
        
        # Audit log
        self._audit_repo.log_action(
            actor_user_id=created_by,  # Using created_by as actor
            action="overlord_claim",
            detail=f"Claimed overlord control for database '{database_name}'",
            context={
                "database_name": database_name,
                "job_id": job_id,
                "row_existed_before": current is not None,
            }
        )
        
        return self._tracking_repo.get(database_name)
    
    # -------------------------------------------------------------------------
    # Get Current State
    # -------------------------------------------------------------------------
    
    def get_state(self, database_name: str) -> tuple[OverlordTracking | None, OverlordCompany | None]:
        """Get current tracking and overlord state.
        
        Args:
            database_name: Database name
            
        Returns:
            Tuple of (tracking record, overlord company) - either may be None
        """
        tracking = self._tracking_repo.get(database_name)
        
        company = None
        if self._overlord_repo:
            company = self._overlord_repo.get_by_database(database_name)
        
        return tracking, company

    def get_full_row(self, database_name: str) -> dict[str, Any] | None:
        """Get full raw row from overlord.companies as a dict.
        
        Returns all columns without domain model filtering.
        Used by the user modal to expose all editable fields.
        
        Args:
            database_name: Database name
            
        Returns:
            Full row dict or None if not found
        """
        if not self._overlord_repo:
            return None
        return self._overlord_repo.get_row_snapshot(database_name)
    
    def get_tracking(self, database_name: str) -> OverlordTracking | None:
        """Get tracking record for a database.
        
        Args:
            database_name: Database name
            
        Returns:
            OverlordTracking if found
        """
        return self._tracking_repo.get(database_name)
    
    def get_tracking_by_job(self, job_id: str) -> OverlordTracking | None:
        """Get tracking record for a job.
        
        Args:
            job_id: Job UUID
            
        Returns:
            OverlordTracking if found
        """
        return self._tracking_repo.get_by_job_id(job_id)
    
    def check_subdomain_duplicates(
        self,
        subdomain: str,
        exclude_database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Check for other companies using the same subdomain.
        
        Args:
            subdomain: Subdomain value to check.
            exclude_database: Database name of the current record to exclude from results.
            
        Returns:
            List of duplicate records with companyID, database, subdomain, dbHost.
        """
        if not self.is_enabled or not self._overlord_repo:
            return []
        return self._overlord_repo.find_by_subdomain(subdomain, exclude_database)
    
    def verify_external_state(
        self,
        database_name: str,
        tracking: OverlordTracking,
    ) -> ExternalStateCheck:
        """Verify overlord row hasn't been modified externally.
        
        Compares current overlord.companies state against what we expect
        based on our tracking record. Detects:
        - Row deleted externally
        - dbHost changed externally
        - subdomain changed externally
        
        Args:
            database_name: Database name to check
            tracking: Our tracking record with expected values
            
        Returns:
            ExternalStateCheck with current state
        """
        current = self._overlord_repo.get_by_database(database_name)
        
        # Row deleted?
        if current is None:
            return ExternalStateCheck(
                row_exists=False,
                dbhost_changed=False,
                subdomain_changed=False,
                current_dbhost=None,
                expected_dbhost=tracking.current_dbhost,
                current_subdomain=None,
                expected_subdomain=tracking.current_subdomain,
            )
        
        # dbHost changed?
        expected = tracking.current_dbhost
        actual = current.db_host
        host_changed = (
            expected is not None
            and actual != expected
        )
        
        if host_changed:
            logger.warning(
                f"External modification detected for {database_name}: "
                f"expected dbHost='{expected}', found='{actual}'"
            )
        
        # subdomain changed?
        expected_sub = tracking.current_subdomain
        actual_sub = current.subdomain
        sub_changed = (
            expected_sub is not None
            and actual_sub != expected_sub
        )
        
        if sub_changed:
            logger.warning(
                f"External subdomain modification detected for {database_name}: "
                f"expected subdomain='{expected_sub}', found='{actual_sub}'"
            )
        
        return ExternalStateCheck(
            row_exists=True,
            dbhost_changed=host_changed,
            subdomain_changed=sub_changed,
            current_dbhost=actual,
            expected_dbhost=expected,
            current_subdomain=actual_sub,
            expected_subdomain=expected_sub,
        )
    
    # -------------------------------------------------------------------------
    # Sync Operation (Write to Overlord)
    # -------------------------------------------------------------------------
    
    def sync(
        self,
        database_name: str,
        job_id: str,
        data: dict[str, Any],
    ) -> bool:
        """Sync changes to overlord.companies.
        
        Creates or updates the overlord row. Requires existing claim.
        
        Args:
            database_name: Database name
            job_id: Job UUID (for ownership verification)
            data: Column values to write (e.g., dbHost, name, subdomain)
            
        Returns:
            True if sync successful
            
        Raises:
            OverlordOwnershipError: If not claimed or wrong job
        """
        if not self.is_enabled:
            raise OverlordOwnershipError("Overlord integration is disabled")
        
        # Verify we have a claim
        tracking = self._tracking_repo.get(database_name)
        if not tracking or tracking.status == OverlordTrackingStatus.RELEASED:
            raise OverlordOwnershipError(
                f"No active claim for '{database_name}' - call claim() first"
            )
        
        if tracking.job_id != job_id:
            raise OverlordOwnershipError(
                f"Claim is owned by job {tracking.job_id}, not {job_id}"
            )
        
        # Ensure database field is set
        data["database"] = database_name
        
        # Check if row exists
        existing = self._overlord_repo.get_by_database(database_name)
        
        if existing:
            # Update existing row
            self._overlord_repo.update(database_name, data)
            company_id = existing.company_id
        else:
            # Insert new row
            company_id = self._overlord_repo.insert(data)
        
        # Update tracking
        self._tracking_repo.update_synced(
            database_name=database_name,
            current_dbhost=data.get("dbHost", ""),
            current_dbhost_read=data.get("dbHostRead"),
            company_id=company_id,
            current_subdomain=data.get("subdomain"),
        )
        
        # Audit log
        self._audit_repo.log_action(
            actor_user_id=tracking.created_by,
            action="overlord_sync",
            detail=f"Synced overlord data for database '{database_name}'",
            context={
                "database_name": database_name,
                "job_id": job_id,
                "action": "update" if existing else "insert",
                "dbHost": data.get("dbHost"),
            }
        )
        
        logger.info(f"Synced overlord for {database_name}: {'update' if existing else 'insert'}")
        return True
    
    # -------------------------------------------------------------------------
    # Release Operation
    # -------------------------------------------------------------------------
    
    def release(
        self,
        database_name: str,
        job_id: str,
        action: ReleaseAction,
    ) -> ReleaseResult:
        """Release overlord control for a database.
        
        Args:
            database_name: Database name
            job_id: Job UUID (for ownership verification)
            action: What to do with the overlord row
            
        Returns:
            ReleaseResult with details
            
        Raises:
            OverlordOwnershipError: If not claimed or wrong job
            OverlordSafetyError: If safety check fails
        """
        if not self.is_enabled:
            return ReleaseResult(
                success=True,
                action_taken=action,
                message="Overlord integration is disabled - nothing to release"
            )
        
        # Get tracking record
        tracking = self._tracking_repo.get(database_name)
        if not tracking or tracking.status == OverlordTrackingStatus.RELEASED:
            return ReleaseResult(
                success=True,
                action_taken=action,
                message=f"No active claim for '{database_name}'"
            )
        
        if tracking.job_id != job_id:
            raise OverlordOwnershipError(
                f"Claim is owned by job {tracking.job_id}, not {job_id}"
            )
        
        # EDGE CASE HANDLING: Verify external state before release
        # The overlord.companies table can be modified externally
        external_state = self.verify_external_state(database_name, tracking)
        external_change_detected = False
        
        if not external_state.row_exists:
            # Row was deleted externally
            if action == ReleaseAction.DELETE:
                # That's what we wanted anyway - success
                logger.info(
                    f"Row already deleted externally for {database_name} - "
                    "marking release as successful"
                )
                self._tracking_repo.update_released(database_name, tracking.job_id)
                return ReleaseResult(
                    success=True,
                    action_taken=action,
                    message="Row was already deleted externally",
                    external_change_detected=True,
                )
            else:
                # Can't restore/clear a non-existent row
                logger.warning(
                    f"Cannot {action.value} for {database_name} - "
                    "row was deleted externally"
                )
                # Still mark as released (we're done with it)
                self._tracking_repo.update_released(database_name, tracking.job_id)
                return ReleaseResult(
                    success=False,
                    action_taken=action,
                    message=f"Cannot {action.value} - row was deleted externally",
                    external_change_detected=True,
                )
        
        if external_state.dbhost_changed:
            external_change_detected = True
            # For DELETE, we already have safety check in _release_delete
            # For RESTORE/CLEAR, log warning but proceed (user chose this action)
            if action != ReleaseAction.DELETE:
                logger.warning(
                    f"Proceeding with {action.value} despite external change for "
                    f"{database_name}: expected='{external_state.expected_dbhost}', "
                    f"found='{external_state.current_dbhost}'"
                )
        
        if external_state.subdomain_changed:
            external_change_detected = True
            logger.warning(
                f"Proceeding with {action.value} despite external subdomain change for "
                f"{database_name}: expected='{external_state.expected_subdomain}', "
                f"found='{external_state.current_subdomain}'"
            )
        
        result: ReleaseResult
        
        if action == ReleaseAction.RESTORE:
            result = self._release_restore(database_name, tracking)
        elif action == ReleaseAction.CLEAR:
            result = self._release_clear(database_name, tracking)
        elif action == ReleaseAction.DELETE:
            result = self._release_delete(database_name, tracking)
        else:
            raise ValueError(f"Unknown release action: {action}")
        
        # Update result with external change flag
        result.external_change_detected = external_change_detected
        
        # Mark tracking as released (use optimistic locking with job_id)
        self._tracking_repo.update_released(database_name, tracking.job_id)
        
        # Audit log
        self._audit_repo.log_action(
            actor_user_id=tracking.created_by,
            action=f"overlord_release_{action.value}",
            detail=f"Released overlord control for '{database_name}' ({action.value})",
            context={
                "database_name": database_name,
                "job_id": job_id,
                "action": action.value,
                "row_existed_before": tracking.row_existed_before,
                "external_change_detected": external_change_detected,
                "result": result.message,
            }
        )
        
        logger.info(f"Released overlord for {database_name}: {action.value}")
        return result
    
    def _release_restore(self, database_name: str, tracking: OverlordTracking) -> ReleaseResult:
        """Restore ALL original values from previous_snapshot.
        
        Uses the full JSON snapshot to restore all fields that may have been
        modified (dbHost, dbHostRead, subdomain, name, etc.), not just the
        host fields.
        """
        if not tracking.row_existed_before:
            return ReleaseResult(
                success=False,
                action_taken=ReleaseAction.RESTORE,
                message="Cannot restore - row was created by pullDB (no previous values)"
            )
        
        # Build restore data from previous_snapshot (full restore) or fall back to individual fields
        if tracking.previous_snapshot:
            # Full restore from JSON snapshot - restore all modifiable fields
            restore_data: dict[str, Any] = {}
            
            # Routing fields (the critical ones)
            if "dbHost" in tracking.previous_snapshot:
                restore_data["dbHost"] = tracking.previous_snapshot["dbHost"] or ""
            if "dbHostRead" in tracking.previous_snapshot:
                restore_data["dbHostRead"] = tracking.previous_snapshot["dbHostRead"] or ""
            if "subdomain" in tracking.previous_snapshot:
                restore_data["subdomain"] = tracking.previous_snapshot["subdomain"] or ""
            
            # Company info fields
            if "name" in tracking.previous_snapshot:
                restore_data["name"] = tracking.previous_snapshot["name"] or ""
            
            if not restore_data:
                return ReleaseResult(
                    success=False,
                    action_taken=ReleaseAction.RESTORE,
                    message="Cannot restore - previous_snapshot contains no restorable fields"
                )
            
            logger.info(
                f"Restoring {len(restore_data)} fields for {database_name} from snapshot: "
                f"{list(restore_data.keys())}"
            )
        else:
            # Fallback to individual tracking fields (legacy behavior)
            if not tracking.previous_dbhost:
                return ReleaseResult(
                    success=False,
                    action_taken=ReleaseAction.RESTORE,
                    message="Cannot restore - no previous values stored"
                )
            
            restore_data = {
                "dbHost": tracking.previous_dbhost,
                "dbHostRead": tracking.previous_dbhost_read or "",
            }
            logger.info(
                f"Restoring {database_name} from tracking fields (no snapshot available)"
            )
        
        updated = self._overlord_repo.update(database_name, restore_data)
        
        if not updated:
            # Row disappeared between our check and update (race condition)
            logger.warning(
                f"Restore failed - row disappeared during update for {database_name}"
            )
            return ReleaseResult(
                success=False,
                action_taken=ReleaseAction.RESTORE,
                message="Restore failed - row was deleted during operation",
                external_change_detected=True,
            )
        
        # Build descriptive message
        restored_fields = list(restore_data.keys())
        restored_dbhost = restore_data.get("dbHost", tracking.previous_dbhost)
        restored_dbhost_read = restore_data.get("dbHostRead", tracking.previous_dbhost_read)
        
        return ReleaseResult(
            success=True,
            action_taken=ReleaseAction.RESTORE,
            message=f"Restored {len(restored_fields)} fields: {', '.join(restored_fields)}",
            restored_dbhost=restored_dbhost,
            restored_dbhost_read=restored_dbhost_read,
        )
    
    def _release_clear(self, database_name: str, tracking: OverlordTracking) -> ReleaseResult:
        """Clear dbHost fields (set to empty)."""
        updated = self._overlord_repo.update(database_name, {
            "dbHost": "",
            "dbHostRead": "",
        })
        
        if not updated:
            # Row disappeared between our check and update (race condition)
            logger.warning(
                f"Clear failed - row disappeared during update for {database_name}"
            )
            return ReleaseResult(
                success=False,
                action_taken=ReleaseAction.CLEAR,
                message="Clear failed - row was deleted during operation",
                external_change_detected=True,
            )
        
        return ReleaseResult(
            success=True,
            action_taken=ReleaseAction.CLEAR,
            message="Cleared dbHost and dbHostRead fields",
        )
    
    def _release_delete(self, database_name: str, tracking: OverlordTracking) -> ReleaseResult:
        """Delete the overlord row completely."""
        # Safety guard: refuse to delete a pre-existing row we never synced.
        # If current_dbhost is None we never wrote to overlord, so deleting
        # a row we didn't create or modify is unsafe. (G3)
        if tracking.current_dbhost is None and tracking.row_existed_before:
            raise OverlordSafetyError(
                f"Cannot delete '{database_name}': row existed before pullDB "
                f"claimed it and was never synced. Use 'restore' or 'clear' instead."
            )

        # Safety check: verify current dbHost matches what we set
        if tracking.current_dbhost:
            current = self._overlord_repo.get_by_database(database_name)
            if current and current.db_host != tracking.current_dbhost:
                raise OverlordSafetyError(
                    f"Safety check failed: dbHost mismatch. "
                    f"Expected '{tracking.current_dbhost}', found '{current.db_host}'. "
                    f"Someone else may have modified this row."
                )
        
        deleted = self._overlord_repo.delete(database_name)
        
        return ReleaseResult(
            success=deleted,
            action_taken=ReleaseAction.DELETE,
            message="Deleted row from overlord.companies" if deleted else "Row not found",
        )
    
    # -------------------------------------------------------------------------
    # Cleanup Hook (Called on Job Delete)
    # -------------------------------------------------------------------------
    
    def cleanup_on_job_delete(self, job_id: str, default_action: ReleaseAction = ReleaseAction.RESTORE) -> ReleaseResult | None:
        """Cleanup overlord tracking when a job is deleted.
        
        Called from job deletion flow. Uses default action based on whether
        row existed before.
        
        Args:
            job_id: Job UUID being deleted
            default_action: Default action if row existed before
            
        Returns:
            ReleaseResult if cleanup performed, None if no tracking found
        """
        tracking = self._tracking_repo.get_by_job_id(job_id)
        if not tracking:
            return None
        
        # Determine action based on history
        if not tracking.row_existed_before:
            # We created it, safe to delete
            action = ReleaseAction.DELETE
        else:
            # Row existed, use default (usually restore)
            action = default_action
        
        logger.info(f"Cleanup overlord for deleted job {job_id}: {action.value}")
        return self.release(tracking.database_name, job_id, action)

    # -------------------------------------------------------------------------
    # Orphaned Tracking Cleanup
    # -------------------------------------------------------------------------

    def cleanup_orphaned_tracking(self) -> int:
        """Remove tracking records whose database no longer exists in overlord.

        Compares local tracking records against the remote overlord
        ``companies`` table.  Any tracking record whose ``database_name``
        has no matching ``database`` column in the remote table is deleted.

        Returns:
            Number of orphaned tracking records removed.
        """
        if not self.is_enabled:
            return 0

        try:
            remote_rows = self._overlord_repo.get_all()
        except Exception:
            logger.warning(
                "Cannot fetch remote overlord data for orphan cleanup",
                exc_info=True,
            )
            return 0

        remote_databases = {r.get("database") for r in remote_rows if r.get("database")}

        all_tracking = self._tracking_repo.list_active()
        orphans = [t for t in all_tracking if t.database_name not in remote_databases]

        removed = 0
        for t in orphans:
            try:
                self._tracking_repo.delete_by_database_name(t.database_name)
                removed += 1
                logger.info(
                    "Removed orphaned tracking record: database=%s, job_id=%s",
                    t.database_name,
                    t.job_id,
                )
            except Exception:
                logger.warning(
                    "Failed to remove orphaned tracking: database=%s",
                    t.database_name,
                    exc_info=True,
                )

        if removed:
            logger.info("Orphaned tracking cleanup: removed %d records", removed)
        return removed
