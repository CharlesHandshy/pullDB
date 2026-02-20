"""Feature Requests API router.

Handles CRUD and voting for feature requests submitted by users.

HCA Layer: pages (API routes)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import fastapi
import pydantic
from fastapi import APIRouter, Depends, HTTPException

from pulldb.api.auth import AdminUser, AuthUser
from pulldb.api.types import APIState

if TYPE_CHECKING:
    from pulldb.worker.feature_request_service import FeatureRequestService

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class FeatureRequestResponse(pydantic.BaseModel):
    """Response for a single feature request."""

    request_id: str
    title: str
    description: str | None
    status: str
    vote_score: int
    upvote_count: int
    downvote_count: int
    created_at: str
    updated_at: str
    completed_at: str | None
    admin_response: str | None
    submitted_by_username: str | None
    submitted_by_user_code: str | None
    user_vote: int | None = None  # Current user's vote: 1, -1, or None


class FeatureRequestListResponse(pydantic.BaseModel):
    """Paginated list of feature requests."""

    requests: list[FeatureRequestResponse]
    total: int
    limit: int
    offset: int


class FeatureRequestCreateRequest(pydantic.BaseModel):
    """Request to create a new feature request."""

    title: str = pydantic.Field(..., min_length=5, max_length=200)
    description: str | None = pydantic.Field(None, max_length=2000)


class FeatureRequestUpdateRequest(pydantic.BaseModel):
    """Request to update a feature request (primary admin only)."""

    status: str | None = None  # open, in_progress, complete, rejected
    admin_response: str | None = pydantic.Field(None, max_length=2000)


class VoteRequest(pydantic.BaseModel):
    """Request to cast a vote."""

    vote_value: int = pydantic.Field(..., ge=0, le=1)  # 0 (remove), 1 (vote)


class FeatureRequestStatsResponse(pydantic.BaseModel):
    """Statistics for feature requests."""

    total: int
    open: int
    in_progress: int
    complete: int
    declined: int


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_feature_requests_router(
    get_api_state: Callable[[], "APIState"],
) -> APIRouter:
    """Build the feature-requests APIRouter.

    Args:
        get_api_state: FastAPI dependency that returns the shared APIState.
            Injected here rather than imported to avoid a circular import with
            api/main.py.

    Returns:
        Configured APIRouter with all /api/feature-requests/* routes.
    """
    router = APIRouter(tags=["feature-requests"])

    # Module-level cache for FeatureRequestService (avoids re-creating per request)
    _cache: dict[str, "FeatureRequestService"] = {}

    def _get_feature_service(state: "APIState") -> "FeatureRequestService":
        from pulldb.worker.feature_request_service import FeatureRequestService

        if "service" not in _cache:
            if state.pool is None:
                raise RuntimeError("FeatureRequestService requires database pool")
            _cache["service"] = FeatureRequestService(state.pool)
        return _cache["service"]

    def _to_response(r: Any) -> FeatureRequestResponse:
        return FeatureRequestResponse(
            request_id=r.request_id,
            title=r.title,
            description=r.description,
            status=r.status.value,
            vote_score=r.vote_score,
            upvote_count=r.upvote_count,
            downvote_count=r.downvote_count,
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat(),
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            admin_response=r.admin_response,
            submitted_by_username=r.submitted_by_username,
            submitted_by_user_code=r.submitted_by_user_code,
            user_vote=r.user_vote,
        )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @router.get("/api/feature-requests/stats", response_model=FeatureRequestStatsResponse)
    async def get_feature_request_stats(
        user: "AuthUser",
        state: "APIState" = Depends(get_api_state),
    ) -> FeatureRequestStatsResponse:
        """Get feature request statistics."""
        service = _get_feature_service(state)
        stats = await service.get_stats()
        return FeatureRequestStatsResponse(
            total=stats.total,
            open=stats.open,
            in_progress=stats.in_progress,
            complete=stats.complete,
            declined=stats.declined,
        )

    @router.get("/api/feature-requests", response_model=FeatureRequestListResponse)
    async def list_feature_requests(
        user: "AuthUser",
        status_filter: str | None = fastapi.Query(None, description="Comma-separated statuses to filter"),
        sort_by: str = fastapi.Query("vote_score", description="Sort column: vote_score, created_at, status"),
        sort_order: str = fastapi.Query("desc", description="Sort direction: asc, desc"),
        limit: int = fastapi.Query(100, ge=1, le=500),
        offset: int = fastapi.Query(0, ge=0),
        state: "APIState" = Depends(get_api_state),
    ) -> FeatureRequestListResponse:
        """List feature requests with filtering and pagination."""
        service = _get_feature_service(state)
        status_list = status_filter.split(",") if status_filter else None
        requests, total = await service.list_requests(
            current_user_id=user.user_id,
            status_filter=status_list,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
        return FeatureRequestListResponse(
            requests=[_to_response(r) for r in requests],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/feature-requests/{request_id}", response_model=FeatureRequestResponse)
    async def get_feature_request(
        request_id: str,
        user: "AuthUser",
        state: "APIState" = Depends(get_api_state),
    ) -> FeatureRequestResponse:
        """Get a single feature request by ID."""
        service = _get_feature_service(state)
        r = await service.get_request(request_id, user.user_id)
        if not r:
            raise HTTPException(status_code=404, detail="Feature request not found")
        return _to_response(r)

    @router.post("/api/feature-requests", response_model=FeatureRequestResponse, status_code=201)
    async def create_feature_request(
        data: FeatureRequestCreateRequest,
        user: "AuthUser",
        state: "APIState" = Depends(get_api_state),
    ) -> FeatureRequestResponse:
        """Create a new feature request."""
        from pulldb.domain.feature_request import FeatureRequestCreate

        service = _get_feature_service(state)
        r = await service.create_request(
            FeatureRequestCreate(title=data.title, description=data.description),
            user.user_id,
        )
        return _to_response(r)

    @router.patch("/api/feature-requests/{request_id}", response_model=FeatureRequestResponse)
    async def update_feature_request(
        request_id: str,
        data: FeatureRequestUpdateRequest,
        user: "AdminUser",
        state: "APIState" = Depends(get_api_state),
    ) -> FeatureRequestResponse:
        """Update a feature request status/response (admin only)."""
        from pulldb.domain.feature_request import FeatureRequestStatus, FeatureRequestUpdate

        service = _get_feature_service(state)
        status_enum = None
        if data.status:
            try:
                status_enum = FeatureRequestStatus(data.status)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status: {data.status}. Valid values: open, in_progress, complete, rejected",
                )
        r = await service.update_request(
            request_id,
            FeatureRequestUpdate(status=status_enum, admin_response=data.admin_response),
        )
        if not r:
            raise HTTPException(status_code=404, detail="Feature request not found")
        return _to_response(r)

    @router.post("/api/feature-requests/{request_id}/vote", response_model=FeatureRequestResponse)
    async def vote_on_feature_request(
        request_id: str,
        data: VoteRequest,
        user: "AuthUser",
        state: "APIState" = Depends(get_api_state),
    ) -> FeatureRequestResponse:
        """Cast or change vote on a feature request.

        vote_value: 1 = upvote, 0 = remove vote
        """
        service = _get_feature_service(state)
        r = await service.vote(request_id, user.user_id, data.vote_value)
        if not r:
            raise HTTPException(status_code=404, detail="Feature request not found")
        return _to_response(r)

    @router.delete("/api/feature-requests/{request_id}", status_code=204)
    async def delete_feature_request(
        request_id: str,
        user: "AdminUser",
        state: "APIState" = Depends(get_api_state),
    ) -> None:
        """Delete a feature request (admin only)."""
        service = _get_feature_service(state)
        deleted = await service.delete_request(request_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Feature request not found")

    return router
