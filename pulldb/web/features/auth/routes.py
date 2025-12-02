"""Authentication routes for pullDB web UI.

HCA Feature Module: auth
Handles: login, logout, session management
Size: ~110 lines (HCA compliant)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from pulldb.web.dependencies import get_api_state, get_session_user, templates
from pulldb.domain.models import User

if TYPE_CHECKING:
    from pulldb.api.main import APIState

router = APIRouter(prefix="/web", tags=["web-auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = None,
    user: User | None = Depends(get_session_user),
) -> Response:
    """Display login form."""
    if user:
        return RedirectResponse(url="/web/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Process login form submission."""
    from pulldb.auth.password import verify_password
    
    user = state.user_repo.get_user_by_username(username)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    
    if user.disabled_at:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Account is disabled"},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Authentication not configured"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    
    password_hash = state.auth_repo.get_password_hash(user.user_id)
    if not password_hash or not verify_password(password, password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    _, session_token = state.auth_repo.create_session(
        user.user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    
    response = RedirectResponse(url="/web/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=os.getenv("PULLDB_SECURE_COOKIES", "false").lower() == "true",
        samesite="lax",
        max_age=86400,
    )
    return response


@router.get("/logout")
async def logout(
    request: Request,
    state: "APIState" = Depends(get_api_state),
) -> Response:
    """Log out user and clear session."""
    session_token = request.cookies.get("session_token")
    
    if session_token and hasattr(state, "auth_repo") and state.auth_repo:
        state.auth_repo.invalidate_session_by_token(session_token)
    
    response = RedirectResponse(url="/web/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_token")
    return response
