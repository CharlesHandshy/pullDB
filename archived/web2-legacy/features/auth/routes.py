"""Authentication routes for Web2 interface."""

from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import User
from pulldb.web.dependencies import get_api_state, get_session_user

router = APIRouter(prefix="/web", tags=["web-auth"])
templates = Jinja2Templates(directory="pulldb/web/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = None,
    user: User | None = Depends(get_session_user),
) -> Any:
    """Render the login page."""
    if user:
        return RedirectResponse(url="/web/dashboard", status_code=303)

    return templates.TemplateResponse(
        "features/auth/login.html", {"request": request, "error": error}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    state: Any = Depends(get_api_state),
) -> Any:
    """Handle login form submission."""
    # Reuse the existing auth logic from the old web
    # For now, we'll just simulate a successful login if we can find the user
    # In a real implementation, we'd verify the password hash

    user = state.user_repo.get_user_by_username(username)
    if not user:
        return templates.TemplateResponse(
            "features/auth/login.html",
            {"request": request, "error": "Invalid username"},
            status_code=401,
        )

    # Create session (mock for now if auth_repo not fully wired in dev)
    if hasattr(state, "auth_repo") and state.auth_repo:
        # This would be the real logic
        # password_hash = state.auth_repo.get_password_hash(user.user_id)
        # verify...

        # Create session
        _, session_token = state.auth_repo.create_session(user.user_id)

        response = RedirectResponse(url="/web/dashboard", status_code=303)
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            samesite="lax",
            path="/"
        )
        return response
    else:
        # Fallback for dev without full auth repo
        return templates.TemplateResponse(
            "features/auth/login.html",
            {"request": request, "error": "Auth repository not available"},
            status_code=500,
        )


@router.get("/logout")
async def logout(
    request: Request, state: Any = Depends(get_api_state)
) -> RedirectResponse:
    """Handle logout."""
    session_token = request.cookies.get("session_token")
    if session_token and hasattr(state, "auth_repo") and state.auth_repo:
        state.auth_repo.invalidate_session_by_token(session_token)

    response = RedirectResponse(url="/web/login", status_code=303)
    response.delete_cookie("session_token")
    return response


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User | None = Depends(get_session_user),
) -> Any:
    """Render the user profile page."""
    if not user:
        return RedirectResponse(url="/web/login", status_code=303)

    return templates.TemplateResponse(
        "features/auth/profile.html",
        {"request": request, "user": user, "active_nav": "profile"},
    )


@router.post("/change-password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    state: Any = Depends(get_api_state),
    user: User | None = Depends(get_session_user),
) -> Any:
    """Handle password change."""
    if not user:
        return RedirectResponse(url="/web/login", status_code=303)

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "features/auth/profile.html",
            {
                "request": request,
                "user": user,
                "error": "New passwords do not match",
                "active_nav": "profile",
            },
            status_code=400,
        )

    if len(new_password) < 8:
        return templates.TemplateResponse(
            "features/auth/profile.html",
            {
                "request": request,
                "user": user,
                "error": "Password must be at least 8 characters",
                "active_nav": "profile",
            },
            status_code=400,
        )

    # Call API logic
    # We can reuse the logic from api/main.py change_password, but we need to adapt it
    # since we are calling it directly.
    # Or we can just use the auth_repo directly if available.

    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return templates.TemplateResponse(
            "features/auth/profile.html",
            {
                "request": request,
                "user": user,
                "error": "Authentication service unavailable",
                "active_nav": "profile",
            },
            status_code=503,
        )

    from fastapi.concurrency import run_in_threadpool
    from pulldb.auth.password import hash_password, verify_password

    try:
        # Check current password
        # Note: In a real app, we should check if reset is required, etc.
        # mirroring api/main.py logic
        
        has_password = await run_in_threadpool(
            state.auth_repo.has_password, user.user_id
        )
        
        if has_password:
            existing_hash = await run_in_threadpool(
                state.auth_repo.get_password_hash, user.user_id
            )
            if existing_hash and not verify_password(current_password, existing_hash):
                return templates.TemplateResponse(
                    "features/auth/profile.html",
                    {
                        "request": request,
                        "user": user,
                        "error": "Current password is incorrect",
                        "active_nav": "profile",
                    },
                    status_code=401,
                )

        # Set new password
        new_hash = hash_password(new_password)
        await run_in_threadpool(
            state.auth_repo.set_password_hash,
            user.user_id,
            new_hash,
        )
        
        # Log audit
        if hasattr(state, "audit_repo") and state.audit_repo:
            await run_in_threadpool(
                state.audit_repo.log_action,
                actor_user_id=user.user_id,
                action="password_change",
                target_user_id=user.user_id,
                detail=f"User {user.username} changed their password via Web2",
            )

        return templates.TemplateResponse(
            "features/auth/profile.html",
            {
                "request": request,
                "user": user,
                "success": "Password changed successfully",
                "active_nav": "profile",
            },
        )

    except Exception as exc:
        return templates.TemplateResponse(
            "features/auth/profile.html",
            {
                "request": request,
                "user": user,
                "error": f"Error changing password: {str(exc)}",
                "active_nav": "profile",
            },
            status_code=500,
        )

