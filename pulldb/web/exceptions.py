"""Custom exceptions and handlers for pullDB Web UI.

HCA Layer: Foundation (shared across all layers)
Purpose: Centralized exception handling for web routes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

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


class MaintenanceRequiredError(Exception):
    """Raised when user must acknowledge database maintenance before continuing.
    
    This is triggered on first daily login when there are expiring or locked
    databases that require user attention.
    """

    def __init__(self, is_htmx: bool = False) -> None:
        self.is_htmx = is_htmx
        super().__init__("Maintenance acknowledgment required")


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


def create_session_expired_handler() -> Callable[[Request, SessionExpiredError], Awaitable[Response]]:
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


def create_password_reset_required_handler() -> Callable[[Request, PasswordResetRequiredError], Awaitable[Response]]:
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


def create_maintenance_required_handler() -> Callable[[Request, MaintenanceRequiredError], Awaitable[Response]]:
    """Create exception handler for MaintenanceRequiredError.

    Redirects user to the maintenance acknowledgment page.
    For HTMX requests, uses HX-Redirect header.
    For regular requests, uses HTTP 303 redirect.
    """

    async def handler(request: Request, exc: MaintenanceRequiredError) -> Response:
        if exc.is_htmx:
            # For HTMX requests, return 200 with HX-Redirect header
            return Response(
                content="",
                status_code=200,
                headers={"HX-Redirect": "/web/maintenance"},
            )
        else:
            # For regular requests, use HTTP redirect
            return RedirectResponse(
                url="/web/maintenance",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    return handler


def create_http_exception_handler(
    templates: Jinja2Templates,
) -> Callable[[Request, Any], Awaitable[Response]]:
    """Create exception handler for HTTPException that renders HTML for web routes.

    For requests to /web/* paths, renders a user-friendly error page.
    For API requests, returns standard JSON error response.
    """
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from fastapi.responses import JSONResponse

    async def handler(request: Request, exc: StarletteHTTPException) -> Response:
        # Only render HTML for web routes
        if not request.url.path.startswith("/web"):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )

        # Map status codes to user-friendly messages
        error_messages = {
            404: ("Page Not Found", "The page you're looking for doesn't exist or has been moved."),
            403: ("Access Denied", "You don't have permission to access this resource."),
            500: ("Server Error", "Something went wrong on our end. Please try again later."),
        }

        title, message = error_messages.get(
            exc.status_code,
            ("Error", str(exc.detail) if exc.detail else "An error occurred"),
        )

        suggestions = None
        if exc.status_code == 404:
            suggestions = [
                "Check the URL for typos",
                "Use the navigation menu to find what you're looking for",
                "Go back to the dashboard and start fresh",
            ]

        return render_error_page(
            request=request,
            templates=templates,
            user=None,  # No user context available in exception handler
            status_code=exc.status_code,
            title=title,
            message=message,
            detail=str(exc.detail) if exc.detail and exc.status_code != 404 else None,
            suggestions=suggestions,
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
