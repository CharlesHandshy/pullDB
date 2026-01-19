"""Feature Requests routes for Web UI.

HCA Layer: features
Purpose: Feature request submission, voting, and browsing with LazyTable pagination.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from pulldb.domain.models import User
from pulldb.web.dependencies import get_api_state, require_login, templates
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

router = APIRouter(prefix="/web/requests", tags=["web-requests"])


@router.get("/", response_class=HTMLResponse)
async def requests_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the feature requests page with LazyTable."""
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    # Get stats
    stats = {
        "total": 0,
        "open": 0,
        "in_progress": 0,
        "complete": 0,
        "declined": 0,
    }
    
    try:
        service = FeatureRequestService(state.pool)
        stats_obj = await service.get_stats()
        stats = {
            "total": stats_obj.total,
            "open": stats_obj.open,
            "in_progress": stats_obj.in_progress,
            "complete": stats_obj.complete,
            "declined": stats_obj.declined,
        }
    except Exception:
        pass

    return templates.TemplateResponse(
        "features/requests/index.html",
        {
            "request": request,
            "active_nav": "requests",
            "user": user,
            "stats": stats,
            "breadcrumbs": get_breadcrumbs("feature_requests"),
        },
    )


@router.get("/api/list")
async def get_requests_api(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=50, ge=1, le=500),
    sortColumn: str = Query(default="vote_score"),
    sortDirection: str = Query(default="desc"),
) -> dict:
    """API endpoint for LazyTable pagination.
    
    Returns:
        {
            "rows": [...],
            "totalCount": int,
            "filteredCount": int,
            "pageIndex": int,
            "pageSize": int
        }
    """
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    try:
        service = FeatureRequestService(state.pool)
        
        # Parse filters from query params
        filter_params = {}
        for key, value in request.query_params.items():
            if key.startswith("filter_") and value:
                filter_key = key[7:]  # Remove "filter_" prefix
                filter_params[filter_key] = value.split(",") if "," in value else [value]
        
        # Get status filter if present
        status_filter = filter_params.get("status")
        
        # Map sort column names
        sort_col = sortColumn
        if sort_col == "vote_score":
            sort_col = "vote_score"
        elif sort_col == "created_at":
            sort_col = "created_at"
        elif sort_col == "status":
            sort_col = "status"
        elif sort_col == "title":
            sort_col = "title"
        else:
            sort_col = "vote_score"  # Default
        
        requests, total = await service.list_requests(
            current_user_id=user.user_id,
            status_filter=status_filter,
            sort_by=sort_col,
            sort_order=sortDirection,
            limit=pageSize,
            offset=page * pageSize,
        )
        
        # Convert to dict rows for LazyTable
        rows = []
        for r in requests:
            rows.append({
                "request_id": r.request_id,
                "title": r.title,
                "description": r.description,
                "status": r.status.value,
                "vote_score": r.vote_score,
                "upvote_count": r.upvote_count,
                "downvote_count": r.downvote_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "admin_response": r.admin_response,
                "submitted_by_username": r.submitted_by_username,
                "submitted_by_user_code": r.submitted_by_user_code,
                "user_vote": r.user_vote,
            })
        
        return {
            "rows": rows,
            "totalCount": total,
            "filteredCount": total,  # For now, server-side filtering counts match
            "pageIndex": page,
            "pageSize": pageSize,
        }
        
    except Exception as e:
        return {
            "rows": [],
            "totalCount": 0,
            "filteredCount": 0,
            "pageIndex": page,
            "pageSize": pageSize,
            "error": str(e),
        }


@router.post("/api/vote/{request_id}")
async def vote_api(
    request_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Cast or change a vote on a feature request."""
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    try:
        body = await request.json()
        vote_value = body.get("vote_value", 0)
        
        if vote_value not in (-1, 0, 1):
            return {"error": "vote_value must be -1, 0, or 1"}
        
        service = FeatureRequestService(state.pool)
        result = await service.vote(request_id, user.user_id, vote_value)
        
        if not result:
            return {"error": "Feature request not found"}
        
        return {
            "success": True,
            "vote_score": result.vote_score,
            "upvote_count": result.upvote_count,
            "downvote_count": result.downvote_count,
            "user_vote": result.user_vote,
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/create")
async def create_request_api(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Create a new feature request."""
    from pulldb.domain.feature_request import FeatureRequestCreate
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    try:
        body = await request.json()
        title = body.get("title", "").strip()
        description = body.get("description", "").strip() or None
        
        if not title or len(title) < 5:
            return {"error": "Title must be at least 5 characters"}
        
        if len(title) > 200:
            return {"error": "Title must be at most 200 characters"}
        
        if description and len(description) > 2000:
            return {"error": "Description must be at most 2000 characters"}
        
        service = FeatureRequestService(state.pool)
        result = await service.create_request(
            FeatureRequestCreate(title=title, description=description),
            user.user_id,
        )
        
        return {
            "success": True,
            "request_id": result.request_id,
            "title": result.title,
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/update/{request_id}")
async def update_request_api(
    request_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),  # We'll check primary admin inside
) -> dict:
    """Update a feature request (primary admin only)."""
    from pulldb.domain.feature_request import (
        FeatureRequestStatus,
        FeatureRequestUpdate,
        PRIMARY_ADMIN_ID,
    )
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    # Check primary admin - only the first installed admin can change status
    if user.user_id != PRIMARY_ADMIN_ID:
        return {"error": "Only the primary administrator can update feature request status"}
    
    try:
        body = await request.json()
        status_str = body.get("status")
        admin_response = body.get("admin_response")
        
        status_enum = None
        if status_str:
            try:
                status_enum = FeatureRequestStatus(status_str)
            except ValueError:
                return {"error": f"Invalid status: {status_str}"}
        
        service = FeatureRequestService(state.pool)
        result = await service.update_request(
            request_id,
            FeatureRequestUpdate(status=status_enum, admin_response=admin_response),
        )
        
        if not result:
            return {"error": "Feature request not found"}
        
        return {
            "success": True,
            "status": result.status.value,
            "admin_response": result.admin_response,
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.delete("/api/delete/{request_id}")
async def delete_request_api(
    request_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Delete/withdraw a feature request (owner or admin only)."""
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    try:
        service = FeatureRequestService(state.pool)
        
        # Get the request to check ownership
        request_obj = await service.get_request(request_id, user.user_id)
        if not request_obj:
            return {"error": "Feature request not found"}
        
        # Check authorization: owner or admin
        is_owner = request_obj.submitted_by_user_id == user.user_id
        is_admin = user.role.value == 'admin'
        
        if not is_owner and not is_admin:
            return {"error": "You can only withdraw your own feature requests"}
        
        # Delete the request
        deleted = await service.delete_request(request_id)
        
        if not deleted:
            return {"error": "Failed to delete feature request"}
        
        return {"success": True}
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/notes/{request_id}")
async def get_notes_api(
    request_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Get all notes for a feature request."""
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    try:
        service = FeatureRequestService(state.pool)
        notes = await service.list_notes(request_id)
        
        return {
            "notes": [
                {
                    "note_id": n.note_id,
                    "user_id": n.user_id,
                    "note_text": n.note_text,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                    "username": n.username,
                    "user_code": n.user_code,
                    "is_mine": n.user_id == user.user_id,
                }
                for n in notes
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/notes/{request_id}")
async def add_note_api(
    request_id: str,
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Add a note to a feature request."""
    from pulldb.domain.feature_request import NoteCreate
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    try:
        body = await request.json()
        note_text = body.get("note_text", "").strip()
        
        if not note_text:
            return {"error": "Note text is required"}
        
        if len(note_text) > 2000:
            return {"error": "Note must be at most 2000 characters"}
        
        service = FeatureRequestService(state.pool)
        result = await service.add_note(
            request_id,
            user.user_id,
            NoteCreate(note_text=note_text),
        )
        
        if not result:
            return {"error": "Feature request not found"}
        
        return {
            "success": True,
            "note": {
                "note_id": result.note_id,
                "user_id": result.user_id,
                "note_text": result.note_text,
                "created_at": result.created_at.isoformat() if result.created_at else None,
                "username": result.username,
                "user_code": result.user_code,
                "is_mine": True,
            },
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.delete("/api/notes/{note_id}")
async def delete_note_api(
    note_id: str,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> dict:
    """Delete a note (own notes only, unless admin)."""
    from pulldb.worker.feature_request_service import FeatureRequestService
    
    try:
        service = FeatureRequestService(state.pool)
        
        # Admins can delete any note, users can only delete their own
        user_id_check = None if user.role == "admin" else user.user_id
        deleted = await service.delete_note(note_id, user_id_check)
        
        if not deleted:
            return {"error": "Note not found or not authorized"}
        
        return {"success": True}
        
    except Exception as e:
        return {"error": str(e)}
