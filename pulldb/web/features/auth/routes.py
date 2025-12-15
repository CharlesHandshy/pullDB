"""Authentication routes for Web2 interface."""

from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from pulldb.domain.models import User
from pulldb.web.dependencies import get_api_state, get_session_user, templates

router = APIRouter(prefix="/web", tags=["web-auth"])


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
    from pulldb.auth.password import verify_password

    # Check user exists
    user = state.user_repo.get_user_by_username(username)
    if not user:
        return templates.TemplateResponse(
            "features/auth/login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    # Verify auth repo available
    if not hasattr(state, "auth_repo") or not state.auth_repo:
        return templates.TemplateResponse(
            "features/auth/login.html",
            {"request": request, "error": "Auth service unavailable"},
            status_code=503,
        )

    # Verify password
    password_hash = state.auth_repo.get_password_hash(user.user_id)
    if not password_hash or not verify_password(password, password_hash):
        return templates.TemplateResponse(
            "features/auth/login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    # Check if user is disabled
    if user.disabled:
        return templates.TemplateResponse(
            "features/auth/login.html",
            {"request": request, "error": "Account is disabled"},
            status_code=403,
        )

    # Create session
    _, session_token = state.auth_repo.create_session(user.user_id)

    response = RedirectResponse(url="/web/dashboard/", status_code=303)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        samesite="lax",
        path="/"
    )
    return response


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


# =============================================================================
# Forced Password Change (for users with force_password_reset flag)
# =============================================================================

def validate_password_policy(password: str) -> tuple[bool, str]:
    """Validate password against policy: 8+ chars, upper, lower, number, symbol.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    import re
    
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;\'`~]', password):
        return False, "Password must contain at least one symbol (!@#$%^&*...)"
    return True, ""


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    error: str | None = None,
    user: User | None = Depends(get_session_user),
    state: Any = Depends(get_api_state),
) -> Any:
    """Render the forced password change page.
    
    This page is shown to users who have the force_password_reset flag set.
    They cannot navigate away until they set a new password.
    """
    if not user:
        return RedirectResponse(url="/web/login", status_code=303)
    
    # Check if user actually needs to change password
    reset_required = False
    if hasattr(state, "auth_repo") and state.auth_repo:
        if hasattr(state.auth_repo, "is_password_reset_required"):
            reset_required = state.auth_repo.is_password_reset_required(user.user_id)
    
    # If no reset required, redirect to dashboard
    if not reset_required:
        return RedirectResponse(url="/web/dashboard/", status_code=303)
    
    return templates.TemplateResponse(
        "features/auth/change_password.html",
        {"request": request, "user": user, "error": error},
    )


@router.post("/change-password", response_class=HTMLResponse)
async def change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    state: Any = Depends(get_api_state),
    user: User | None = Depends(get_session_user),
) -> Any:
    """Handle forced password change submission."""
    from pulldb.auth.password import hash_password
    
    if not user:
        return RedirectResponse(url="/web/login", status_code=303)
    
    # Verify user needs to change password
    reset_required = False
    if hasattr(state, "auth_repo") and state.auth_repo:
        if hasattr(state.auth_repo, "is_password_reset_required"):
            reset_required = state.auth_repo.is_password_reset_required(user.user_id)
    
    if not reset_required:
        return RedirectResponse(url="/web/dashboard/", status_code=303)
    
    # Validate passwords match
    if new_password != confirm_password:
        return templates.TemplateResponse(
            "features/auth/change_password.html",
            {"request": request, "user": user, "error": "Passwords do not match"},
            status_code=400,
        )
    
    # Validate password policy
    is_valid, error_msg = validate_password_policy(new_password)
    if not is_valid:
        return templates.TemplateResponse(
            "features/auth/change_password.html",
            {"request": request, "user": user, "error": error_msg},
            status_code=400,
        )
    
    # Set new password
    new_hash = hash_password(new_password)
    if hasattr(state.auth_repo, "set_password_hash"):
        state.auth_repo.set_password_hash(user.user_id, new_hash)
    
    # Clear the password reset flag
    if hasattr(state.auth_repo, "clear_password_reset"):
        state.auth_repo.clear_password_reset(user.user_id)
    
    # Redirect to dashboard
    return RedirectResponse(url="/web/dashboard/", status_code=303)


# =============================================================================
# User Profile
# =============================================================================

@router.get("/auth/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User | None = Depends(get_session_user),
    state: Any = Depends(get_api_state),
) -> Any:
    """Render the user profile page."""
    if not user:
        return RedirectResponse(url="/web/login", status_code=303)

    breadcrumbs = [
        {"label": "Dashboard", "url": "/web/dashboard"},
        {"label": "Profile", "url": None},
    ]

    # Get manager username if user has a manager
    manager_username = None
    if user.manager_id and hasattr(state, "user_repo") and state.user_repo:
        manager = state.user_repo.get_user_by_id(user.manager_id)
        if manager:
            manager_username = manager.username

    # Format member since date
    member_since = user.created_at.strftime("%b %Y") if user.created_at else "N/A"

    return templates.TemplateResponse(
        "features/auth/profile.html",
        {
            "request": request,
            "user": user,
            "active_nav": "profile",
            "breadcrumbs": breadcrumbs,
            "manager_username": manager_username,
            "member_since": member_since,
        },
    )


@router.post("/auth/change-password", response_class=HTMLResponse)
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


@router.post("/auth/set-default-host")
async def set_default_host(
    request: Request,
    state: Any = Depends(get_api_state),
    user: User | None = Depends(get_session_user),
) -> dict:
    """Set user's default database host."""
    from fastapi.responses import JSONResponse

    if not user:
        return JSONResponse(
            {"success": False, "error": "Not authenticated"},
            status_code=401,
        )

    try:
        body = await request.json()
        host = body.get("host", "")
    except Exception:
        return JSONResponse(
            {"success": False, "error": "Invalid request body"},
            status_code=400,
        )

    # Validate host is in user's allowed hosts
    if host and host not in (user.allowed_hosts or []):
        return JSONResponse(
            {"success": False, "error": "Host not in allowed hosts"},
            status_code=400,
        )

    # Update user's default host
    if hasattr(state, "user_repo") and state.user_repo:
        try:
            state.user_repo.update_default_host(user.user_id, host or None)
            
            # Log audit
            if hasattr(state, "audit_repo") and state.audit_repo:
                from fastapi.concurrency import run_in_threadpool
                await run_in_threadpool(
                    state.audit_repo.log_action,
                    actor_user_id=user.user_id,
                    action="default_host_change",
                    target_user_id=user.user_id,
                    detail=f"User {user.username} changed default host to: {host or 'None'}",
                )
            
            return {"success": True, "host": host}
        except Exception as exc:
            return JSONResponse(
                {"success": False, "error": str(exc)},
                status_code=500,
            )
    
    return JSONResponse(
        {"success": False, "error": "User service unavailable"},
        status_code=503,
    )


