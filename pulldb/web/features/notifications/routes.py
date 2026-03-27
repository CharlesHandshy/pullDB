"""Notifications inbox feature routes.

Shows unread notifications for the logged-in user and marks them read
on dismissal. Currently the only notification type is 'ownership_claimed',
fired when another user takes ownership of a database the viewer had deployed.

HCA Layer: pages (pulldb/web/features/)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from starlette.requests import Request

from pulldb.domain.models import User
from pulldb.web.dependencies import get_api_state, require_login, templates

router = APIRouter(tags=["web-notifications"])


@router.get("/")
async def notifications_page(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> Any:
    notifications = []
    if hasattr(state, "user_repo") and state.user_repo:
        if hasattr(state.user_repo, "get_pending_notifications"):
            try:
                notifications = state.user_repo.get_pending_notifications(user.user_id)
            except Exception:
                logger.warning("Failed to fetch notifications for user %s", user.user_id, exc_info=True)

    return templates.TemplateResponse(
        "features/notifications/notifications.html",
        {
            "request": request,
            "user": user,
            "active_nav": "",
            "notifications": notifications,
        },
    )


@router.post("/dismiss")
async def notifications_dismiss(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> Any:
    if hasattr(state, "user_repo") and state.user_repo:
        if hasattr(state.user_repo, "mark_notifications_read"):
            try:
                state.user_repo.mark_notifications_read(user.user_id)
            except Exception:
                logger.warning("Failed to mark notifications read for user %s", user.user_id, exc_info=True)

    return RedirectResponse(url="/web/dashboard/", status_code=303)
