"""Overlord Companies API routes.

Feature: 54166071 - Button to update overlord.companies
HCA Layer: pages (API routes)

These routes provide the API endpoints for managing overlord.companies
integration. They coordinate with OverlordManager for business logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from pulldb.infra.overlord import (
    OverlordAlreadyClaimedError,
    OverlordConnectionError,
    OverlordOwnershipError,
    OverlordSafetyError,
)

if TYPE_CHECKING:
    from pulldb.api.auth import AuthUser
    from pulldb.api.types import APIState


logger = logging.getLogger(__name__)


# =============================================================================
# Request/Response Models
# =============================================================================


class OverlordClaimRequest(BaseModel):
    """Request to claim overlord control for a database."""
    
    job_id: str


class OverlordSyncRequest(BaseModel):
    """Request to sync changes to overlord.companies."""
    
    job_id: str
    database: str
    subdomain: str = Field(
        ...,
        max_length=30,
        pattern=r'^[a-z0-9]([a-z0-9-]{0,28}[a-z0-9])?$',
        description="DNS-safe subdomain for routing (lowercase alphanumeric and hyphens, 1-30 chars)",
    )
    name: str | None = None
    dbHost: str
    dbHostRead: str | None = None
    release_action: str = "restore"  # restore, clear, delete


class OverlordReleaseRequest(BaseModel):
    """Request to release overlord control."""
    
    job_id: str
    action: str = "restore"  # restore, clear, delete


class SubdomainDuplicateEntry(BaseModel):
    """A company record that shares the same subdomain."""
    
    company_id: int
    database: str
    subdomain: str
    dbHost: str


class OverlordStateResponse(BaseModel):
    """Response with current overlord state for a job."""
    
    job: dict[str, Any]
    tracking: dict[str, Any] | None
    company: dict[str, Any] | None
    enabled: bool
    subdomain_duplicates: list[SubdomainDuplicateEntry] | None = None


class OverlordSyncResponse(BaseModel):
    """Response after syncing to overlord."""
    
    success: bool
    message: str
    tracking: dict[str, Any] | None = None


class OverlordReleaseResponse(BaseModel):
    """Response after releasing overlord control."""
    
    success: bool
    action_taken: str
    message: str


# =============================================================================
# Router Factory
# =============================================================================


def create_overlord_router(
    get_api_state: Any,
    require_auth: Any,
) -> APIRouter:
    """Create overlord API router with injected dependencies.
    
    Args:
        get_api_state: Dependency to get API state
        require_auth: Dependency to require authenticated user
        
    Returns:
        Configured APIRouter
    """
    router = APIRouter(prefix="/api/v1/overlord", tags=["overlord"])
    
    @router.get("/{job_id}", response_model=OverlordStateResponse)
    async def get_overlord_state(
        job_id: str,
        state: Any = Depends(get_api_state),
        user: Any = Depends(require_auth),
    ) -> OverlordStateResponse:
        """Get current overlord state for a job.
        
        Returns tracking record (if any) and current overlord.companies row.
        """
        # Check if overlord is enabled
        overlord_manager = getattr(state, "overlord_manager", None)
        if not overlord_manager or not overlord_manager.is_enabled:
            return OverlordStateResponse(
                job={"id": job_id},
                tracking=None,
                company=None,
                enabled=False,
            )
        
        # Get job
        job = state.job_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Check permissions (owner or manager)
        if not _can_manage_overlord(user, job):
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to manage overlord for this job"
            )
        
        # Get current state (handle errors gracefully - Security Rule 6: Error Differentiation)
        try:
            tracking, company = overlord_manager.get_state(job.target)
        except OverlordConnectionError as e:
            logger.warning(f"Overlord connection failed for job {job_id}: {e}")
            raise HTTPException(
                status_code=503,
                detail="Unable to connect to overlord database. Please try again later."
            ) from e
        except Exception as e:
            # Catch MySQL errors and provide specific messages
            error_str = str(e)
            if "SELECT command denied" in error_str or "Access denied" in error_str:
                logger.error(f"Overlord permission denied for job {job_id}: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Permission denied on overlord database. Contact administrator."
                ) from e
            elif "Can't connect" in error_str or "Connection refused" in error_str:
                logger.error(f"Overlord connection refused for job {job_id}: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Unable to connect to overlord database. Please try again later."
                ) from e
            else:
                logger.exception(f"Unexpected error getting overlord state for job {job_id}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error retrieving overlord data: {error_str}"
                ) from e
        
        # Check for subdomain duplicates if company has a subdomain
        subdomain_duplicates = None
        if company and company.subdomain:
            try:
                dupes = overlord_manager.check_subdomain_duplicates(
                    company.subdomain, exclude_database=job.target
                )
                if dupes:
                    subdomain_duplicates = [
                        SubdomainDuplicateEntry(
                            company_id=d["companyID"],
                            database=d["database"],
                            subdomain=d["subdomain"],
                            dbHost=_shorten_host(d.get("dbHost", "")),
                        )
                        for d in dupes
                    ]
            except Exception:
                logger.debug("Subdomain duplicate check failed (non-critical)", exc_info=True)
        
        return OverlordStateResponse(
            job={
                "id": job.id,
                "target": job.target,
                "status": job.status.value,
                "dbhost": job.dbhost,
            },
            tracking=_tracking_to_dict(tracking) if tracking else None,
            company=_company_to_dict(company) if company else None,
            enabled=True,
            subdomain_duplicates=subdomain_duplicates,
        )
    
    @router.post("/{job_id}/claim", response_model=OverlordSyncResponse)
    async def claim_overlord(
        job_id: str,
        state: Any = Depends(get_api_state),
        user: Any = Depends(require_auth),
    ) -> OverlordSyncResponse:
        """Claim overlord control for a job's database.
        
        This creates a tracking record and backs up the current overlord state.
        """
        overlord_manager = getattr(state, "overlord_manager", None)
        if not overlord_manager or not overlord_manager.is_enabled:
            raise HTTPException(
                status_code=400,
                detail="Overlord integration is not enabled"
            )
        
        # Get job and verify status (Security Rule 5: API Job Status Verification)
        job = state.job_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        if job.status.value not in ("deployed", "expiring"):
            raise HTTPException(
                status_code=400,
                detail=f"Job is '{job.status.value}', must be 'deployed' or 'expiring' to claim overlord"
            )
        
        # Check permissions
        if not _can_manage_overlord(user, job):
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to manage overlord for this job"
            )
        
        try:
            tracking = overlord_manager.claim(
                database_name=job.target,
                job_id=job_id,
                created_by=user.username,
            )
            
            return OverlordSyncResponse(
                success=True,
                message="Successfully claimed overlord control",
                tracking=_tracking_to_dict(tracking),
            )
            
        except (OverlordOwnershipError, OverlordAlreadyClaimedError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OverlordConnectionError as e:
            logger.error(f"Overlord connection failed during claim for job {job_id}: {e}")
            raise HTTPException(
                status_code=503,
                detail="Unable to connect to overlord database. Please try again later.",
            ) from e
        except Exception as e:
            logger.exception(f"Failed to claim overlord for job {job_id}")
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred. Check server logs for details.",
            ) from e
    
    @router.post("/{job_id}/sync", response_model=OverlordSyncResponse)
    async def sync_overlord(
        job_id: str,
        request: OverlordSyncRequest,
        state: Any = Depends(get_api_state),
        user: Any = Depends(require_auth),
    ) -> OverlordSyncResponse:
        """Sync changes to overlord.companies.
        
        Creates or updates the overlord row with provided values.
        Also stores the release action preference.
        """
        overlord_manager = getattr(state, "overlord_manager", None)
        if not overlord_manager or not overlord_manager.is_enabled:
            raise HTTPException(
                status_code=400,
                detail="Overlord integration is not enabled"
            )
        
        # Get job and verify status (Security Rule 5: API Job Status Verification)
        job = state.job_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        if job.status.value not in ("deployed", "expiring"):
            raise HTTPException(
                status_code=400,
                detail=f"Job is '{job.status.value}', must be 'deployed' or 'expiring' to sync overlord"
            )
        
        # Check permissions
        if not _can_manage_overlord(user, job):
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to manage overlord for this job"
            )
        
        try:
            # Auto-claim if not already claimed
            tracking = overlord_manager.get_tracking(job.target)
            if not tracking:
                tracking = overlord_manager.claim(
                    database_name=job.target,
                    job_id=job_id,
                    created_by=user.username,
                )
            
            # Sync to overlord
            data = {
                "database": job.target,
                "subdomain": request.subdomain,
                "dbHost": request.dbHost,
            }
            if request.name:
                data["name"] = request.name
            if request.dbHostRead:
                data["dbHostRead"] = request.dbHostRead
            
            overlord_manager.sync(
                database_name=job.target,
                job_id=job_id,
                data=data,
            )
            
            # Get updated tracking
            tracking = overlord_manager.get_tracking(job.target)
            
            return OverlordSyncResponse(
                success=True,
                message="Successfully synced to overlord",
                tracking=_tracking_to_dict(tracking),
            )
            
        except (OverlordOwnershipError, OverlordAlreadyClaimedError, OverlordSafetyError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OverlordConnectionError as e:
            logger.error(f"Overlord connection failed during sync for job {job_id}: {e}")
            raise HTTPException(
                status_code=503,
                detail="Unable to connect to overlord database. Please try again later.",
            ) from e
        except Exception as e:
            logger.exception(f"Failed to sync overlord for job {job_id}")
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred. Check server logs for details.",
            ) from e
    
    @router.post("/{job_id}/release", response_model=OverlordReleaseResponse)
    async def release_overlord(
        job_id: str,
        request: OverlordReleaseRequest,
        state: Any = Depends(get_api_state),
        user: Any = Depends(require_auth),
    ) -> OverlordReleaseResponse:
        """Release overlord control for a job's database.
        
        Applies the specified action (restore, clear, or delete) and marks
        the tracking record as released.
        
        Note: Release is allowed for non-deployed jobs (cleanup scenario).
        """
        from pulldb.worker.overlord_manager import ReleaseAction
        
        overlord_manager = getattr(state, "overlord_manager", None)
        if not overlord_manager or not overlord_manager.is_enabled:
            return OverlordReleaseResponse(
                success=True,
                action_taken="none",
                message="Overlord integration is not enabled",
            )
        
        # Get job (Security Rule 5: Job must exist, but release allowed for any status)
        job = state.job_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Log warning if releasing for non-deployed job (unusual but allowed for cleanup)
        if job.status.value not in ("deployed", "expiring"):
            logger.warning(
                f"Releasing overlord for non-deployed job {job_id} (status={job.status.value})"
            )
        
        # Check permissions
        if not _can_manage_overlord(user, job):
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to manage overlord for this job"
            )
        
        try:
            # Map action string to enum
            action_map = {
                "restore": ReleaseAction.RESTORE,
                "clear": ReleaseAction.CLEAR,
                "delete": ReleaseAction.DELETE,
            }
            action = action_map.get(request.action, ReleaseAction.RESTORE)
            
            result = overlord_manager.release(
                database_name=job.target,
                job_id=job_id,
                action=action,
            )
            
            return OverlordReleaseResponse(
                success=result.success,
                action_taken=result.action_taken.value,
                message=result.message,
            )
            
        except (OverlordOwnershipError, OverlordSafetyError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OverlordConnectionError as e:
            logger.error(f"Overlord connection failed during release for job {job_id}: {e}")
            raise HTTPException(
                status_code=503,
                detail="Unable to connect to overlord database. Please try again later.",
            ) from e
        except Exception as e:
            logger.exception(f"Failed to release overlord for job {job_id}")
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred. Check server logs for details.",
            ) from e
    
    @router.get("/subdomain-check/{subdomain}")
    async def check_subdomain(
        subdomain: str,
        exclude_database: str | None = None,
        state: Any = Depends(get_api_state),
        user: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        """Check for existing companies using the given subdomain.
        
        Returns a list of duplicate records for the UI to display.
        Query param ?exclude_database= omits the current record.
        """
        overlord_manager = getattr(state, "overlord_manager", None)
        if not overlord_manager or not overlord_manager.is_enabled:
            return {"duplicates": []}
        
        try:
            dupes = overlord_manager.check_subdomain_duplicates(
                subdomain, exclude_database=exclude_database
            )
            return {
                "duplicates": [
                    {
                        "company_id": d["companyID"],
                        "database": d["database"],
                        "subdomain": d["subdomain"],
                        "dbHost": _shorten_host(d.get("dbHost", "")),
                    }
                    for d in dupes
                ],
            }
        except Exception as e:
            logger.warning(f"Subdomain check failed: {e}")
            return {"duplicates": [], "error": "Check failed"}
    
    return router


# =============================================================================
# Helpers
# =============================================================================


def _can_manage_overlord(user: Any, job: Any) -> bool:
    """Check if user can manage overlord for a job.
    
    Returns True if:
    - User is the job owner
    - User is a manager or admin
    """
    from pulldb.domain.models import UserRole
    
    # Managers and admins can manage any job
    if hasattr(user, "role"):
        if user.role in (UserRole.MANAGER, UserRole.ADMIN):
            return True
    
    # Owner can manage their own jobs
    # Compare user_code to user_code (not username to user_code)
    if hasattr(job, "owner_user_code") and hasattr(user, "user_code"):
        return job.owner_user_code == user.user_code
    
    return False


def _shorten_host(host: str, max_len: int = 35) -> str:
    """Shorten a dbHost value for display in duplicate tables.
    
    Truncates long hostnames with ellipsis while keeping the meaningful prefix.
    
    Args:
        host: Full dbHost string.
        max_len: Maximum display length.
        
    Returns:
        Shortened host string.
    """
    if not host or len(host) <= max_len:
        return host or ""
    return host[: max_len - 1] + "\u2026"


def _tracking_to_dict(tracking: Any) -> dict[str, Any]:
    """Convert tracking record to dict for API response."""
    if not tracking:
        return {}
    
    return {
        "id": tracking.id,
        "database_name": tracking.database_name,
        "job_id": tracking.job_id,
        "status": tracking.status.value if hasattr(tracking.status, "value") else tracking.status,
        "row_existed_before": tracking.row_existed_before,
        "previous_dbhost": tracking.previous_dbhost,
        "previous_dbhost_read": tracking.previous_dbhost_read,
        "current_dbhost": tracking.current_dbhost,
        "current_subdomain": tracking.current_subdomain,
        "company_id": tracking.company_id,
        "created_at": tracking.created_at.isoformat() if tracking.created_at else None,
        "updated_at": tracking.updated_at.isoformat() if tracking.updated_at else None,
        "released_at": tracking.released_at.isoformat() if tracking.released_at else None,
    }


def _company_to_dict(company: Any) -> dict[str, Any]:
    """Convert company record to dict for API response."""
    if not company:
        return {}
    
    return {
        "company_id": company.company_id,
        "database": company.database,
        "name": company.name,
        "subdomain": company.subdomain,
        "dbHost": company.db_host,
        "dbHostRead": company.db_host_read,
    }
