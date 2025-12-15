"""Custom exceptions and handlers for pullDB Web UI.

HCA Layer: Foundation (shared across all layers)
Purpose: Centralized exception handling for web routes.
"""

from __future__ import annotations

import typing as t

from fastapi import Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from pulldb.domain.models import User


class SessionExpiredError(Exception):
    """Raised when a session is invalid or expired."""

    def __init__(self, is_htmx: bool = False) -> None:
        self.is_htmx = is_htmx
        super().__init__("Session expired")


class PasswordResetRequiredError(Exception):
    """Raised when a user must change their password before continuing."""

    def __init__(self, is_htmx: bool = False) -> None:
        self.is_htmx = is_htmx
        super().__init__("Password reset required")


class PermissionDeniedError(Exception):
    """Raised when user lacks permission for an action."""

    def __init__(self, message: str = "Permission denied") -> None:
        self.message = message
        super().__init__(message)


class ResourceNotFoundError(Exception):
    """Raised when a requested resource doesn't exist."""

    def __init__(self, resource_type: str, resource_id: str | int) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(f"{resource_type} not found: {resource_id}")


def create_session_expired_handler() -> t.Callable[[Request, SessionExpiredError], t.Awaitable[Response]]:
    """Create exception handler for SessionExpiredError.

    Returns a response that clears the session cookie and redirects to login.
    For HTMX requests, uses HX-Redirect header.
    For regular requests, uses HTTP 303 redirect.
    """

    async def handler(request: Request, exc: SessionExpiredError) -> Response:
        if exc.is_htmx:
            # For HTMX requests, return 200 with HX-Redirect header
            response = Response(
                content="",
                status_code=200,
                headers={"HX-Redirect": "/web/login"},
            )
        else:
            # For regular requests, use HTTP redirect
            response = RedirectResponse(
                url="/web/login",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        # Clear the invalid session cookie
        response.delete_cookie("session_token")
        return response

    return handler


def create_password_reset_required_handler() -> t.Callable[[Request, PasswordResetRequiredError], t.Awaitable[Response]]:
    """Create exception handler for PasswordResetRequiredError.

    Redirects user to the change-password page.
    For HTMX requests, uses HX-Redirect header.
    For regular requests, uses HTTP 303 redirect.
    """

    async def handler(request: Request, exc: PasswordResetRequiredError) -> Response:
        if exc.is_htmx:
            # For HTMX requests, return 200 with HX-Redirect header
            return Response(
                content="",
                status_code=200,
                headers={"HX-Redirect": "/web/change-password"},
            )
        else:
            # For regular requests, use HTTP redirect
            return RedirectResponse(
                url="/web/change-password",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    return handler


def render_error_page(
    request: Request,
    templates: Jinja2Templates,
    user: User | None,
    status_code: int,
    title: str,
    message: str,
    detail: str | None = None,
    suggestions: list[str] | None = None,
    back_url: str | None = None,
) -> Response:
    """Render a user-friendly error page.

    Args:
        request: The FastAPI request
        templates: Jinja2Templates instance
        user: Current user or None
        status_code: HTTP status code
        title: Error page title
        message: Main error message
        detail: Additional detail (optional)
        suggestions: List of suggestions to resolve (optional)
        back_url: URL for back button (defaults to referer)

    Returns:
        Rendered error page response
    """
    error_types = {
        404: "warning",
        403: "error",
        500: "error",
    }
    # Use referer header as back URL if not specified
    if back_url is None:
        back_url = request.headers.get("referer")

    return templates.TemplateResponse(
        request=request,
        name="features/errors/error.html",
        context={
            "user": user,
            "status_code": status_code,
            "title": title,
            "subtitle": message,
            "message": message,
            "detail": detail,
            "error_type": error_types.get(status_code, "warning"),
            "suggestions": suggestions,
            "back_url": back_url,
        },
        status_code=status_code,
    )
