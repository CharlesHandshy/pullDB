"""Entry point for the `pulldb` CLI.

HCA Layer: pages
"""

from __future__ import annotations

import importlib
import json as json_module
import logging
import os
import re
import sys
import time

logger = logging.getLogger(__name__)
from collections.abc import Sequence
from datetime import datetime
from types import ModuleType
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol, cast

import click

from pulldb import __version__
from pulldb.cli.auth import get_auth_headers, get_calling_username, get_current_username
from pulldb.cli.parse import CLIParseError, parse_restore_args

# Default timeout for CLI HTTP requests to API (seconds)
# Defined locally to keep CLI client package self-contained (no infra dependency)
DEFAULT_API_CLIENT_TIMEOUT = 30.0

# UUID validation pattern (copied from domain.validation to keep CLI self-contained)
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Configuration is read directly from config files — NO environment variables.
# The API URL is a system-level setting managed at install time.
# Priority order (first readable file wins):
#   1. /opt/pulldb.client/config  (system-wide client config from .deb)
#   2. /opt/pulldb.service/.env   (server-side — only on the pullDB server)
#   3. .env (relative to source)  (developer checkout)
_CONFIG_SEARCH_PATHS = [
    "/opt/pulldb.client/config",
    "/opt/pulldb.service/.env",
    os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
]

DEFAULT_API_URL = "https://localhost:8080"


def _read_config_value(key: str, default: str | None = None) -> str | None:
    """Read a value from the first available config file.

    Parses KEY=VALUE lines directly from the config file.
    Does NOT use environment variables — config files are the single
    source of truth for client settings.
    """
    for cfg_path in _CONFIG_SEARCH_PATHS:
        try:
            if not os.path.exists(cfg_path) or not os.access(cfg_path, os.R_OK):
                continue
            with open(cfg_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == key:
                        return v
            # File was readable but key not found — continue to next file
        except (PermissionError, OSError):
            continue
    return default


# TLS certificate verification for HTTPS connections.
# If a CA bundle is deployed at /opt/pulldb.client/ca-cert.pem, use it.
# Otherwise disable verification (self-signed cert on the server).
_TLS_CA_CERT_PATH = "/opt/pulldb.client/ca-cert.pem"
_TLS_VERIFY: str | bool = (
    _TLS_CA_CERT_PATH
    if os.path.isfile(_TLS_CA_CERT_PATH)
    else False
)

# Suppress urllib3 InsecureRequestWarning when verify=False
if _TLS_VERIFY is False:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_STATUS_LIMIT = 1000

# Maximum retries for transient HTTP failures
_HTTP_MAX_RETRIES = 2
_HTTP_RETRY_BACKOFF = 1.0  # seconds between retries


class _RequestsModuleProtocol(Protocol):
    """Protocol for the requests module to enable proper type checking."""

    RequestException: type[Exception]
    Response: type

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = ...,
        headers: dict[str, str] | None = ...,
        timeout: float | None = ...,
        **kwargs: Any,
    ) -> Any: ...

    def post(
        self,
        url: str,
        data: str | bytes | None = ...,
        json: Any | None = ...,
        headers: dict[str, str] | None = ...,
        timeout: float | None = ...,
        **kwargs: Any,
    ) -> Any: ...


if TYPE_CHECKING:  # pragma: no cover - typing-only import
    import requests
    from requests import RequestException, Response

    # Use protocol-typed variable for type checking so pyright understands the API
    requests_module: _RequestsModuleProtocol = requests  # type: ignore[assignment]
else:
    requests_module = cast(
        _RequestsModuleProtocol, importlib.import_module("requests")
    )
    RequestException = cast(type[Exception], requests_module.RequestException)
    Response = cast(type, requests_module.Response)


_https_warned = False  # Module-level flag to warn about HTTP only once


def _warn_if_http(url: str) -> None:
    """Warn if connecting over plain HTTP.

    pullDB prefers HTTPS for API communication. Plain HTTP triggers a
    one-time warning for non-localhost addresses but does not block the
    request — the server enforces TLS independently.
    """
    global _https_warned
    if _https_warned:
        return
    parsed = url.lower().rstrip("/")
    if parsed.startswith("http://") and not any(
        parsed.startswith(f"http://{h}") for h in ("localhost", "127.0.0.1", "[::1]")
    ):
        click.echo(
            click.style(
                "Warning: API URL uses plain HTTP. "
                "Update PULLDB_API_URL in /opt/pulldb.client/config "
                "to an https:// endpoint.",
                fg="yellow",
            ),
            err=True,
        )
    _https_warned = True


def _load_api_config() -> tuple[str, float]:
    """Resolve API base URL and timeout from config file (no env vars)."""
    base_url = (_read_config_value("PULLDB_API_URL") or DEFAULT_API_URL).rstrip("/")
    _warn_if_http(base_url)
    timeout_raw = _read_config_value(
        "PULLDB_API_TIMEOUT", str(DEFAULT_API_CLIENT_TIMEOUT)
    ) or str(DEFAULT_API_CLIENT_TIMEOUT)
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:  # FAIL HARD: invalid timeout configuration
        raise click.ClickException(
            "PULLDB_API_TIMEOUT must be a numeric value (seconds). "
            f"Received '{timeout_raw}'."
        ) from exc
    if timeout <= 0:
        raise click.ClickException(
            "PULLDB_API_TIMEOUT must be greater than zero seconds."
        )
    return base_url, timeout


def _get_user_info(username: str) -> tuple[str, str | None]:
    """Lookup user in the system to get their user_code.

    Args:
        username: The username to lookup.

    Returns:
        Tuple of (username, user_code) where user_code may be None if not found.
    """
    from pulldb.cli.auth import has_api_credentials
    
    # Skip API call if no credentials - user is likely registering
    if not has_api_credentials():
        return username, None
    
    try:
        base_url, timeout = _load_api_config()
        path = f"/api/users/{username}"
        url = f"{base_url}{path}"
        headers = get_auth_headers(method="GET", path=path, body=None)
        response = requests_module.get(url, headers=headers, timeout=timeout, verify=_TLS_VERIFY)
        if response.status_code == 200:
            data = response.json()
            return username, data.get("user_code")
    except Exception:
        # Graceful fallback: user info is optional for help display
        logger.debug("Failed to get user info for %s", username, exc_info=True)
    return username, None


class UserState:
    """User registration state for CLI gating."""

    NOT_REGISTERED = "not_registered"
    NO_HOST_CREDENTIALS = "no_host_credentials"  # User exists but no local API key
    PENDING_APPROVAL = "pending_approval"  # Has credentials but API key not approved
    KEY_REVOKED = "key_revoked"  # Has credentials but API key has been revoked
    DISABLED = "disabled"
    ENABLED = "enabled"


def _get_user_state(username: str) -> tuple[str, str | None, bool]:
    """Get user registration state for CLI command gating.

    Args:
        username: The username to check.

    Returns:
        Tuple of (state, user_code, has_password) where:
        - state is one of UserState.NOT_REGISTERED, NO_HOST_CREDENTIALS, DISABLED, or ENABLED
        - user_code is the user's code if registered, else None
        - has_password indicates if password is set (for setpass flow)
    """
    from pulldb.cli.auth import has_api_credentials
    
    # If no credentials, check if user exists in database via unauthenticated endpoint
    if not has_api_credentials():
        try:
            base_url, timeout = _load_api_config()
            # Use the exists endpoint which doesn't require auth
            url = f"{base_url}/api/auth/user-exists/{username}"
            response = requests_module.get(url, timeout=timeout, verify=_TLS_VERIFY)
            if response.status_code == 200:
                data = response.json()
                if data.get("exists", False):
                    # User exists but no credentials on this host
                    return UserState.NO_HOST_CREDENTIALS, data.get("user_code"), False
        except Exception:
            # Fall through to NOT_REGISTERED on error
            logger.debug("Failed to check user existence for %s", username, exc_info=True)
        return UserState.NOT_REGISTERED, None, False
    
    try:
        base_url, timeout = _load_api_config()
        path = f"/api/users/{username}"
        url = f"{base_url}{path}"
        headers = get_auth_headers(method="GET", path=path, body=None)
        response = requests_module.get(url, headers=headers, timeout=timeout, verify=_TLS_VERIFY)
        if response.status_code == 404:
            return UserState.NOT_REGISTERED, None, False
        if response.status_code == 401:
            # Credentials exist but 401 - check error detail to determine reason
            try:
                error_detail = response.json().get("detail", "")
                # Check if the key was revoked
                if "revoked" in error_detail.lower():
                    # Get user_code from user-exists endpoint
                    exists_url = f"{base_url}/api/auth/user-exists/{username}"
                    exists_resp = requests_module.get(exists_url, timeout=timeout, verify=_TLS_VERIFY)
                    if exists_resp.status_code == 200:
                        data = exists_resp.json()
                        return UserState.KEY_REVOKED, data.get("user_code"), False
                    return UserState.KEY_REVOKED, None, False
                # Check if pending approval
                if "pending" in error_detail.lower():
                    exists_url = f"{base_url}/api/auth/user-exists/{username}"
                    exists_resp = requests_module.get(exists_url, timeout=timeout, verify=_TLS_VERIFY)
                    if exists_resp.status_code == 200:
                        data = exists_resp.json()
                        return UserState.PENDING_APPROVAL, data.get("user_code"), False
                    return UserState.PENDING_APPROVAL, None, False
                # Check if key was deleted (no longer exists in database)
                # "Invalid API key" means the key_id doesn't exist at all
                if "invalid api key" in error_detail.lower():
                    exists_url = f"{base_url}/api/auth/user-exists/{username}"
                    exists_resp = requests_module.get(exists_url, timeout=timeout, verify=_TLS_VERIFY)
                    if exists_resp.status_code == 200:
                        data = exists_resp.json()
                        if data.get("exists", False):
                            # User exists but key was deleted - treat as no credentials
                            return UserState.NO_HOST_CREDENTIALS, data.get("user_code"), False
                    return UserState.NOT_REGISTERED, None, False
                # Fallback: check if user exists (for unknown 401 reasons)
                exists_url = f"{base_url}/api/auth/user-exists/{username}"
                exists_resp = requests_module.get(exists_url, timeout=timeout, verify=_TLS_VERIFY)
                if exists_resp.status_code == 200:
                    data = exists_resp.json()
                    if data.get("exists", False):
                        # User exists, has credentials, unknown 401 - could be signature error
                        # Treat as no valid credentials (key may have been deleted/corrupted)
                        return UserState.NO_HOST_CREDENTIALS, data.get("user_code"), False
            except Exception:
                logger.debug("Failed to parse 401 response details", exc_info=True)
            return UserState.NOT_REGISTERED, None, False
        if response.status_code == 200:
            data = response.json()
            user_code = data.get("user_code")
            is_disabled = data.get("is_disabled", False)
            has_password = data.get("has_password", False)
            if is_disabled:
                return UserState.DISABLED, user_code, has_password
            return UserState.ENABLED, user_code, has_password
    except Exception:
        # On API error, allow access (fail open for connectivity issues)
        logger.debug("API error checking user state, failing open", exc_info=True)
    return UserState.ENABLED, None, False


class _APIError(RuntimeError):
    """Raised when the API returns an unexpected payload."""


# Minimum length for job ID prefix matching
MIN_JOB_ID_PREFIX_LENGTH = 8


def _get_default_s3env() -> str:
    """Get default S3 environment from config file or 'prod'."""
    return _read_config_value("PULLDB_S3ENV_DEFAULT", "prod") or "prod"


def _resolve_job_id(job_id_or_prefix: str) -> str:
    """Resolve a job ID prefix to the full job ID.

    Supports short 8-character prefixes (e.g., '8b4c4a3a') in addition to
    full UUIDs. If multiple jobs match the prefix, prompts user to select.

    Args:
        job_id_or_prefix: Full job ID or 8+ character prefix.

    Returns:
        Full job ID (UUID).

    Raises:
        click.ClickException: If not found or resolution fails.
        click.UsageError: If prefix too short.
    """
    # Validate minimum length
    if len(job_id_or_prefix) < MIN_JOB_ID_PREFIX_LENGTH:
        raise click.UsageError(
            f"Job ID must be at least {MIN_JOB_ID_PREFIX_LENGTH} characters. "
            "Use 'pulldb status' to find job IDs."
        )

    # If it's a valid full UUID, use directly (normalized to lowercase)
    if job_id_or_prefix and _UUID_PATTERN.match(job_id_or_prefix):
        return job_id_or_prefix.lower()

    # Call resolution API
    base_url, timeout = _load_api_config()
    path = f"/api/jobs/resolve/{job_id_or_prefix}"
    url = f"{base_url}{path}"
    headers = get_auth_headers(method="GET", path=path, body=None)
    try:
        response = requests_module.get(url, headers=headers, timeout=timeout, verify=_TLS_VERIFY)
    except RequestException as exc:
        raise click.ClickException(
            "Cannot connect to pullDB service. Is the API running?"
        ) from exc

    if response.status_code == 404:
        raise click.ClickException(
            f"No job found matching '{job_id_or_prefix}'. "
            "Use 'pulldb status' or 'pulldb history' to find valid job IDs."
        )
    if response.status_code >= 400:
        raise click.ClickException(_format_api_error(response))

    data = _parse_json_response(response)
    if not isinstance(data, dict):
        raise click.ClickException("Received invalid response from server.")

    resolved_id = data.get("resolved_id")
    matches = data.get("matches", [])
    count = data.get("count", 0)

    # Single match - return it
    if resolved_id:
        return str(resolved_id)

    # Multiple matches - prompt user to select
    if count > 1:
        click.echo(f"\nMultiple jobs match '{job_id_or_prefix}':\n")
        click.echo(f"{'#':<3} {'JOB_ID':<12} {'STATUS':<12} {'TARGET':<20} {'USER':<8}")
        click.echo("-" * 60)

        for idx, match in enumerate(matches, 1):
            job_id_short = match.get("id", "")[:12]
            status_val = match.get("status", "?")
            target = match.get("target", "?")[:20]
            user_code = match.get("user_code", "?")[:8]
            click.echo(f"{idx:<3} {job_id_short:<12} {status_val:<12} {target:<20} {user_code:<8}")

        click.echo("")

        # Prompt for selection
        while True:
            choice = click.prompt(
                "Enter number to select (or 'q' to quit)",
                type=str,
                default="q",
            )
            if choice.lower() == "q":
                raise click.Abort()
            try:
                idx = int(choice)
                if 1 <= idx <= len(matches):
                    return str(matches[idx - 1]["id"])
                click.echo(f"Please enter a number between 1 and {len(matches)}")
            except ValueError:
                click.echo("Invalid input. Enter a number or 'q' to quit.")

    # No matches (shouldn't reach here due to 404 above, but handle anyway)
    raise click.ClickException(f"No job found matching '{job_id_or_prefix}'.")


def _print_formatted_detail(detail: str, indent: str = "  ") -> None:
    """Print event detail in a readable, formatted way.

    Handles JSON data by pretty-printing it with proper indentation.
    For structured error messages, preserves their formatting.
    """
    # Try to parse as JSON for pretty printing
    try:
        parsed = json_module.loads(detail)
        if isinstance(parsed, dict):
            _print_formatted_dict(parsed, indent)
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    _print_formatted_dict(item, indent)
                    click.echo()
                else:
                    click.echo(f"{indent}{item}")
        else:
            click.echo(f"{indent}{parsed}")
    except (json_module.JSONDecodeError, ValueError):
        # Not JSON - print as-is, preserving newlines
        for line in detail.split("\n"):
            click.echo(f"{indent}{line}")


def _print_formatted_dict(
    data: dict[str, Any], indent: str = "  ", max_depth: int = 3, depth: int = 0
) -> None:
    """Recursively print a dictionary with proper formatting."""
    if depth >= max_depth:
        click.echo(f"{indent}{data}")
        return

    for key, value in data.items():
        if isinstance(value, dict):
            click.echo(f"{indent}{key}:")
            _print_formatted_dict(value, indent + "  ", max_depth, depth + 1)
        elif isinstance(value, list):
            click.echo(f"{indent}{key}:")
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    click.echo(f"{indent}  [{i + 1}]")
                    _print_formatted_dict(item, indent + "    ", max_depth, depth + 1)
                else:
                    # Handle strings that might have embedded newlines
                    item_str = str(item)
                    if "\n" in item_str:
                        click.echo(f"{indent}  [{i + 1}]")
                        for line in item_str.split("\n"):
                            click.echo(f"{indent}    {line}")
                    else:
                        click.echo(f"{indent}  - {item}")
        elif isinstance(value, str) and "\n" in value:
            # Multi-line string - format nicely
            click.echo(f"{indent}{key}:")
            for line in value.split("\n"):
                click.echo(f"{indent}  {line}")
        else:
            click.echo(f"{indent}{key}: {value}")


def _handle_auth_error(response: Response) -> None:
    """Handle 401 authentication failures consistently.

    Raises:
        click.ClickException: Always — with appropriate auth error message.
    """
    detail = ""
    try:
        err_payload = response.json()
        if isinstance(err_payload, dict):
            detail = err_payload.get("detail", "")
    except ValueError:
        pass
    if "pending approval" in detail.lower():
        raise click.ClickException(
            "API key is pending approval. Contact an administrator to approve your key."
        )
    raise click.ClickException(
        "Authentication required. Run 'pulldb register' to create an account, "
        "or check your API credentials in ~/.pulldb/credentials"
    )


def _handle_rate_limit(response: Response) -> None:
    """Handle 429 rate-limit responses consistently.

    Raises:
        click.ClickException: Always — with appropriate rate-limit message.
    """
    detail = ""
    try:
        err_payload = response.json()
        if isinstance(err_payload, dict):
            detail = err_payload.get("detail", "")
    except ValueError:
        pass
    if "User limit" in detail:
        raise click.ClickException(
            f"Rate limited: {detail}\n"
            "Tip: Use 'pulldb status' to see your active jobs."
        )
    elif "System at capacity" in detail:
        raise click.ClickException(
            f"Rate limited: {detail}\n"
            "The system is busy. Please try again in a few minutes."
        )
    else:
        raise click.ClickException(
            f"Rate limited: {detail or 'Too many requests'}\n"
            "Please wait before submitting more jobs."
        )


def _api_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Response:
    """Execute an authenticated API request with retry on transient failures.

    Retries up to ``_HTTP_MAX_RETRIES`` times on connection errors or 5xx
    responses, with exponential back-off.

    Args:
        method: HTTP method (GET or POST).
        path: API path (e.g. ``/api/jobs``).
        payload: JSON body for POST requests.
        params: Query parameters for GET requests.

    Returns:
        The HTTP response object.

    Raises:
        click.ClickException: On auth failure, rate-limit, or persistent error.
    """
    base_url, timeout = _load_api_config()
    url = f"{base_url}{path}"

    body: str | None = None
    headers: dict[str, str]
    if method == "POST" and payload is not None:
        body = json_module.dumps(payload, separators=(",", ":"), sort_keys=True)
        headers = get_auth_headers(method="POST", path=path, body=body)
        headers["Content-Type"] = "application/json"
    else:
        headers = get_auth_headers(method="GET", path=path, body=None)

    last_exc: Exception | None = None
    for attempt in range(_HTTP_MAX_RETRIES + 1):
        try:
            if method == "POST":
                response = requests_module.post(
                    url, data=body, headers=headers, timeout=timeout, verify=_TLS_VERIFY,
                )
            else:
                response = requests_module.get(
                    url, params=params, headers=headers, timeout=timeout, verify=_TLS_VERIFY,
                )
        except RequestException as exc:
            last_exc = exc
            if attempt < _HTTP_MAX_RETRIES:
                time.sleep(_HTTP_RETRY_BACKOFF * (attempt + 1))
                continue
            raise click.ClickException(
                "Cannot connect to pullDB service. Is the API running?"
            ) from exc

        # Retry on 5xx server errors (transient)
        if response.status_code >= 500 and attempt < _HTTP_MAX_RETRIES:
            time.sleep(_HTTP_RETRY_BACKOFF * (attempt + 1))
            continue

        # Non-retryable status handling
        if response.status_code == 401:
            _handle_auth_error(response)
        if response.status_code == 429:
            _handle_rate_limit(response)
        if response.status_code >= 400:
            raise click.ClickException(_format_api_error(response))

        return response

    # Should not reach here, but guard against it
    raise click.ClickException(
        "Cannot connect to pullDB service. Is the API running?"
    )


def _api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = _api_request("POST", path, payload=payload)
    parsed = _parse_json_response(response)
    if isinstance(parsed, dict):
        return parsed
    raise click.ClickException("Received invalid response from server.")


def _api_get(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    response = _api_request("GET", path, params=params)
    parsed = _parse_json_response(response)
    if isinstance(parsed, list):
        return parsed
    raise click.ClickException("Received invalid response from server.")


def _api_get_object(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET request expecting object (dict) response."""
    response = _api_request("GET", path, params=params)
    parsed = _parse_json_response(response)
    if isinstance(parsed, dict):
        return parsed
    raise click.ClickException("Received invalid response from server.")


def _parse_json_response(response: Response) -> Any:
    """Parse JSON response from API.

    Args:
        response: HTTP response object.

    Returns:
        Parsed JSON (may be dict, list, or primitive).

    Raises:
        click.ClickException: If response is not valid JSON.
    """
    try:
        return response.json()
    except ValueError as exc:
        raise click.ClickException(
            "Received invalid response from server. Please try again."
        ) from exc


def _format_api_error(response: Response) -> str:
    """Format API error response into a human-friendly message.

    Maps HTTP status codes to user-friendly categories and extracts
    the detail message without exposing technical HTTP codes.

    Args:
        response: The HTTP response object.

    Returns:
        Human-readable error message.
    """
    # Extract detail message from JSON response
    detail: str | None = None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        raw_detail = payload.get("detail") or payload.get("message")
        if isinstance(raw_detail, str) and raw_detail.strip():
            detail = raw_detail.strip()

    # If no JSON detail, try raw text
    if not detail:
        text = response.text.strip()
        if text:
            detail = text[:200]

    # Map status codes to human-friendly categories
    status = response.status_code
    if status == 400:
        # Bad request - validation error
        return detail or "Invalid request. Please check your input."
    elif status == 401:
        return detail or "Not authenticated. Run 'pulldb register' to create an account."
    elif status == 403:
        return detail or "Permission denied. You don't have access to this resource."
    elif status == 404:
        return detail or "Not found. The requested resource doesn't exist."
    elif status == 409:
        # Conflict - already in progress, etc. (just show the message)
        return detail or "Conflict. The operation cannot be completed."
    elif status == 422:
        # Validation error
        return detail or "Validation error. Please check your input."
    elif status == 429:
        # Rate limit (handled separately in _api_post, but just in case)
        return detail or "Rate limited. Please wait before trying again."
    elif status >= 500:
        # Server error - show detail if available, otherwise generic
        if detail:
            return f"Server error: {detail}"
        return "Server error. Please try again or contact support."
    else:
        # Unknown error - include code for debugging
        if detail:
            return detail
        return f"Request failed ({status}): {response.reason or 'Unknown error'}"


def _parse_iso(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        iso_value = value.strip()
        if not iso_value:
            return None
        if iso_value.endswith("Z"):
            iso_value = iso_value[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(iso_value)
        except ValueError:
            return None
    return None


class _JobSummary(Protocol):
    id: str
    target: str
    status: str
    user_code: str
    submitted_at: datetime | None
    started_at: datetime | None
    staging_name: str | None


class _JobRow(NamedTuple):
    id: str
    target: str
    status: str
    user_code: str
    submitted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    staging_name: str | None
    current_operation: str | None
    dbhost: str | None
    source: str | None


def _job_row_from_payload(payload: dict[str, Any]) -> _JobRow:
    try:
        job_id = str(payload["id"])
        target = str(payload["target"])
        status = str(payload["status"])
        user_code = str(payload["user_code"])
    except KeyError as exc:
        raise _APIError(f"Missing field in API response: {exc.args[0]}") from exc

    submitted_at = _parse_iso(payload.get("submitted_at"))
    started_at = _parse_iso(payload.get("started_at"))
    completed_at = _parse_iso(payload.get("completed_at"))
    staging_name_value = payload.get("staging_name")
    staging_name = str(staging_name_value) if staging_name_value else None
    current_operation = payload.get("current_operation")
    if current_operation:
        current_operation = str(current_operation)

    dbhost = payload.get("dbhost")
    if dbhost:
        dbhost = str(dbhost)

    source = payload.get("source")
    if source:
        source = str(source)

    return _JobRow(
        id=job_id,
        target=target,
        status=status,
        user_code=user_code,
        submitted_at=submitted_at,
        started_at=started_at,
        completed_at=completed_at,
        staging_name=staging_name,
        current_operation=current_operation,
        dbhost=dbhost,
        source=source,
    )


@click.group(
    help="pullDB - Development database restore tool",
    invoke_without_command=True,
)
@click.version_option(__version__, prog_name="pulldb")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """CLI entry point for pullDB commands.

    This is the main Click group that organizes all pullDB subcommands.
    Provides restore and status commands for end users.

    When invoked without a subcommand, displays help with user identity.

    Access control:
    - Not registered: Only 'register', 'setpass', '--help', '--version' allowed
    - No host credentials: Only 'register', 'setpass', '--help', '--version' allowed
    - Key revoked: Only 'register', '--help', '--version' allowed
    - Registered but disabled: Show contact admin message
    - Registered and enabled: Full access

    Note: Administrative commands (settings) are available via pulldb-admin.
    """
    # Commands that unregistered users can access
    UNREGISTERED_ALLOWED_COMMANDS = {"register", "setpass", None}  # None = help display
    # Commands for users who exist but don't have credentials on this host
    NO_CREDENTIALS_ALLOWED_COMMANDS = {"register", "setpass", None}
    # Commands for users whose key has been revoked
    KEY_REVOKED_ALLOWED_COMMANDS = {"register", None}

    username = get_calling_username()
    user_state, user_code, _ = _get_user_state(username)

    # Store user state in context for commands that need it
    ctx.ensure_object(dict)
    ctx.obj["username"] = username
    ctx.obj["user_state"] = user_state
    ctx.obj["user_code"] = user_code

    # Gate access based on user state
    if user_state == UserState.NOT_REGISTERED:
        if ctx.invoked_subcommand not in UNREGISTERED_ALLOWED_COMMANDS:
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (not registered)")
            click.echo("")
            click.echo("You must register before using pullDB commands.")
            click.echo("")
            click.echo("To create an account:")
            click.echo("  pulldb register")
            click.echo("")
            click.echo("After registering, contact an administrator to enable your account.")
            ctx.exit(1)

    elif user_state == UserState.NO_HOST_CREDENTIALS:
        if ctx.invoked_subcommand not in NO_CREDENTIALS_ALLOWED_COMMANDS:
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (code: {user_code})")
            click.echo("")
            click.echo("This machine is not registered with your pullDB account.")
            click.echo("")
            click.echo("To register this machine:")
            click.echo("  pulldb register")
            click.echo("")
            click.echo("After requesting, contact an administrator to approve the key.")
            ctx.exit(1)

    elif user_state == UserState.PENDING_APPROVAL:
        # User has credentials on this host but key is not yet approved
        click.echo("pullDB - Database restore tool")
        click.echo(f"User: {username} (code: {user_code})")
        click.echo("")
        click.echo("Your API key for this machine is pending approval.")
        click.echo("Contact an administrator to approve your key.")
        click.echo("")
        click.echo("Once approved, you can use 'pulldb restore' from this machine.")
        ctx.exit(1)

    elif user_state == UserState.KEY_REVOKED:
        # User has credentials but the key has been revoked
        # Allow register to get a new key
        if ctx.invoked_subcommand not in KEY_REVOKED_ALLOWED_COMMANDS:
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (code: {user_code})")
            click.echo("")
            click.echo("Your API key for this machine has been revoked.")
            click.echo("")
            click.echo("To request a new key:")
            click.echo("  pulldb register")
            click.echo("")
            click.echo("Contact an administrator if you believe this is an error.")
            ctx.exit(1)

    elif user_state == UserState.DISABLED:
        # Disabled users cannot run any commands (including register/setpass)
        click.echo("pullDB - Database restore tool")
        click.echo(f"User: {username} (code: {user_code})")
        click.echo("")
        click.echo("Your account is pending approval.")
        click.echo("Contact an administrator to enable your account.")
        ctx.exit(1)

    # Handle no subcommand (show help)
    if ctx.invoked_subcommand is None:
        # Display user identity and appropriate help
        if user_state == UserState.NOT_REGISTERED:
            # Unregistered users see only registration instructions
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (not registered)")
            click.echo("")
            click.echo("You must register before using pullDB.")
            click.echo("")
            click.echo("To create an account:")
            click.echo("  pulldb register")
            click.echo("")
            click.echo("After registering, contact an administrator to enable your account.")
        elif user_state == UserState.NO_HOST_CREDENTIALS:
            # User exists but no credentials on this host
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (code: {user_code})")
            click.echo("")
            click.echo("This machine is not registered with your pullDB account.")
            click.echo("")
            click.echo("To register this machine:")
            click.echo("  pulldb register")
            click.echo("")
            click.echo("After requesting, contact an administrator to approve the key.")
        elif user_state == UserState.PENDING_APPROVAL:
            # User has credentials but key not approved yet
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (code: {user_code})")
            click.echo("")
            click.echo("Your API key for this machine is pending approval.")
            click.echo("Contact an administrator to approve your key.")
            click.echo("")
            click.echo("Once approved, you can use 'pulldb restore' from this machine.")
        elif user_state == UserState.KEY_REVOKED:
            # User has credentials but key has been revoked
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (code: {user_code})")
            click.echo("")
            click.echo("Your API key for this machine has been revoked.")
            click.echo("")
            click.echo("To request a new key:")
            click.echo("  pulldb register")
            click.echo("")
            click.echo("Contact an administrator if you believe this is an error.")
        elif user_code:
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username} (code: {user_code})")
            
            # Show default host info
            try:
                base_url, timeout = _load_api_config()
                path = "/api/hosts"
                url = f"{base_url}{path}"
                headers = get_auth_headers(method="GET", path=path, body=None)
                response = requests_module.get(url, headers=headers, timeout=timeout, verify=_TLS_VERIFY)
                if response.status_code == 200:
                    data = _parse_json_response(response)
                    default_host = data.get("default_host")
                    default_alias = data.get("default_alias")
                    if default_host:
                        if default_alias:
                            click.echo(f"Default host: {default_alias} ({default_host})")
                        else:
                            click.echo(f"Default host: {default_host}")
            except Exception:
                # Silently skip if we can't get host info
                logger.debug("Failed to get default host info", exc_info=True)
            
            click.echo("")
            click.echo(ctx.get_help())
        else:
            click.echo("pullDB - Database restore tool")
            click.echo(f"User: {username}")
            click.echo("")
            click.echo(ctx.get_help())


@cli.command("restore",
             context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})
@click.argument("options", nargs=-1, type=click.UNPROCESSED)
def restore_cmd(options: tuple[str, ...]) -> None:
    """Submit a database restore job.

    \b
    REQUIRED:
      <customer>          Customer database to restore (lowercase letters only)
        OR
      customer=<id>       Alternative syntax for customer
        OR
      qatemplate          Restore the QA template database

    \b
    OPTIONS:
      <dbhost>              Target database host (positional, after customer)
      dbhost=<hostname>     Target database host (named parameter)
      target=<name>         Custom target database name (1-51 lowercase letters)
      suffix=<abc>          Suffix for target database (1-3 lowercase letters)
      date=<YYYY-MM-DD>     Specific backup date (default: latest)
      s3env=<staging|prod|both>  S3 environment (default: PULLDB_S3ENV_DEFAULT or prod)
      overwrite             Allow overwriting existing database

    \b
    ADMIN ONLY:
      user=<username>       Submit job on behalf of another user

    \b
    NOTE: target= and suffix= cannot be used together. If using target=,
    include any suffix in the target name directly (e.g., target=mytestdev).

    \b
    EXAMPLES:
      pulldb restore actionpest
      pulldb restore actionpest dev               # dbhost as positional arg
      pulldb restore actionpest suffix=dev
      pulldb restore actionpest date=2025-11-25
      pulldb restore customer=actionpest
      pulldb restore qatemplate
      pulldb restore qatemplate dev               # qatemplate with dbhost
      pulldb restore qatemplate suffix=dev
      pulldb restore actionpest dbhost=dev        # dbhost as named arg
      pulldb restore actionpest overwrite
      pulldb restore actionpest s3env=prod
      pulldb restore actionpest target=mytest     # custom target name
      pulldb restore qatemplate target=qatest     # qatemplate with custom target
    """
    # Step 1: Parse and validate CLI arguments
    try:
        parsed = parse_restore_args(options)
    except CLIParseError as e:  # FAIL HARD surface to user
        raise click.UsageError(str(e)) from e

    # Display warning if customer name was normalized (truncated + hashed)
    if parsed.customer_normalized and parsed.normalization_message:
        click.secho(f"⚠ {parsed.normalization_message}", fg="yellow", err=True)

    # Step 2: Get username - use parsed value or auto-detect
    if parsed.username:
        username = parsed.username
    else:
        username = get_calling_username()

    # Step 3: Relay request to API service
    payload: dict[str, Any] = {
        "user": username,
        "customer": parsed.customer_id,
        "qatemplate": parsed.is_qatemplate,
        "suffix": parsed.suffix,
        "dbhost": parsed.dbhost,
        "date": parsed.date,
        "overwrite": parsed.overwrite,
        "custom_target": parsed.custom_target,
    }
    
    # Add environment - use parsed value or default
    s3env = parsed.s3env or _get_default_s3env()
    if s3env != "both":
        payload["env"] = s3env

    api_response = _api_post("/api/jobs", payload)

    if not isinstance(api_response, dict):
        raise click.ClickException("Received invalid response from server.")

    job_id = str(api_response.get("job_id", ""))
    target = str(api_response.get("target", ""))
    staging_name = str(api_response.get("staging_name", ""))
    status = str(api_response.get("status", "")) or "queued"
    owner_username = str(api_response.get("owner_username", username))
    owner_user_code = str(api_response.get("owner_user_code", ""))

    if not job_id or not target:
        raise click.ClickException("API response missing job_id or target fields.")

    # Display job info with customer and target prominently
    if parsed.customer_id:
        customer_display = parsed.customer_id
    elif parsed.suffix:
        customer_display = f"qatemplate (suffix={parsed.suffix})"
    else:
        customer_display = "qatemplate"
    click.echo("Job queued successfully!")
    click.echo(f"  customer:     {customer_display}")
    click.echo(f"  target:       {target}")
    click.echo(f"  staging_name: {staging_name}")
    click.echo(f"  job_id:       {job_id}")
    click.echo(f"  status:       {status}")
    click.echo(f"  user:         {owner_username} ({owner_user_code})")
    click.echo("\nUse 'pulldb status' to monitor progress.")


@cli.command("status")
@click.argument("job_id", required=False)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table.",
)
@click.option(
    "--wide",
    is_flag=True,
    help="Show additional columns (staging_name).",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    show_default=True,
    help="Maximum number of jobs to display.",
)
@click.option(
    "--active",
    is_flag=True,
    help="Show only active jobs (queued/running).",
)
@click.option(
    "--history",
    is_flag=True,
    help="Show historical jobs (completed/failed/canceled).",
)
@click.option(
    "--status",
    "filter_status",
    type=click.Choice(["queued", "running", "complete", "failed", "canceled"]),
    help="Filter by specific job status.",
)
@click.option(
    "--rt",
    is_flag=True,
    help="Stream job events in realtime. Auto-exits when job completes.",
)
def status_cmd(
    job_id: str | None,
    json_out: bool,
    wide: bool,
    limit: int,
    active: bool,
    history: bool,
    filter_status: str | None,
    rt: bool,
) -> None:
    """Show job status and history.

    \b
    USAGE:
      pulldb status                  # Your last submitted job
      pulldb status <job_id>         # Specific job details
      pulldb status --active         # All active jobs (queued/running)
      pulldb status --history        # Historical jobs
      pulldb status --status failed  # Filter by status
      pulldb status --rt             # Stream your last job's events
      pulldb status --rt <job_id>    # Stream specific job's events

    \b
    STATUS VALUES:
      queued    - Job waiting to be processed
      running   - Job currently executing
      complete  - Job finished successfully
      failed    - Job failed with error
      canceled  - Job was canceled

    \b
    EXAMPLES:
      pulldb status                  # Quick check on your last job
      pulldb status f19f06a1         # Check job by ID prefix
      pulldb status --rt             # Watch your job in realtime
      pulldb status --history --status failed  # Failed jobs only
    """
    if rt:
        resolved_id: str | None = None
        job_status: str | None = None
        
        if job_id:
            # User provided a job ID, resolve it
            resolved_id = _resolve_job_id(job_id)
            # Get job status
            try:
                job_data = _api_get_object(f"/api/jobs/{resolved_id}", {})
                job_status = job_data.get("status")
            except _APIError:
                pass
        else:
            # No job ID provided - find user's last submitted job
            try:
                username = get_calling_username()
                _, user_code = _get_user_info(username)
                if user_code:
                    result = _api_get_object("/api/jobs/my-last", {"user_code": user_code})
                    job_data_maybe = result.get("job")
                    if isinstance(job_data_maybe, dict):
                        resolved_id = job_data_maybe.get("id")
                        job_status = job_data_maybe.get("status")
            except _APIError:
                pass
        
        if not resolved_id:
            raise click.UsageError(
                "No job found. Provide a job_id or submit a restore first.\n"
                "  pulldb status --rt <job_id>   # stream specific job\n"
                "  pulldb restore <customer>     # submit a new restore"
            )
        
        # Check if job is active (queued or running)
        is_active = job_status in ("queued", "running")
        
        if is_active:
            click.echo(f"Streaming events for active job {resolved_id[:8]}...")
            _stream_job_events(resolved_id)
        else:
            # Job is not active - dump events once and exit
            click.echo(f"Job {resolved_id[:8]} ({job_status}):\n")
            _dump_job_events(resolved_id)
        return

    if limit <= 0 or limit > MAX_STATUS_LIMIT:
        raise click.UsageError(f"--limit must be between 1 and {MAX_STATUS_LIMIT}")

    # Helper for datetime formatting (used multiple places in this command)
    def _fmt_dt(dt: datetime | None) -> str:
        return dt.isoformat(timespec="seconds") if dt else "—"

    # When no arguments/flags: show user's last submitted job
    if not job_id and not active and not history and not filter_status:
        try:
            username = get_calling_username()
            _, user_code = _get_user_info(username)
            if user_code:
                result = _api_get_object("/api/jobs/my-last", {"user_code": user_code})
                job_data_maybe = result.get("job")
                if isinstance(job_data_maybe, dict):
                    click.echo(click.style("Your last submitted job:", bold=True))
                    click.echo()
                    if json_out:
                        click.echo(json_module.dumps(job_data_maybe, separators=(",", ":")))
                    else:
                        # Format single job display
                        row = _job_row_from_payload(job_data_maybe)

                        # Build table for single job
                        fields: list[tuple[str, str]] = [
                            ("STATUS", row.status),
                        ]
                        # Only show OPERATION if job is running
                        if row.current_operation:
                            fields.append(("OPERATION", row.current_operation))
                        fields.extend([
                            ("JOB_ID", row.id[:8]),
                            ("CUSTOMER", row.source or "—"),
                            ("TARGET", row.target),
                            ("DB", row.dbhost or "—"),
                            ("USER", row.user_code),
                            ("SUBMITTED", _fmt_dt(row.submitted_at)),
                            ("STARTED", _fmt_dt(row.started_at)),
                        ])
                        # Show COMPLETED for finished jobs
                        if row.completed_at:
                            fields.append(("COMPLETED", _fmt_dt(row.completed_at)))
                        if wide:
                            fields.append(("STAGING", row.staging_name or "—"))

                        max_label = max(len(f[0]) for f in fields)
                        for label, value in fields:
                            click.echo(f"  {label.ljust(max_label)}: {value}")
                    return
                else:
                    click.echo("No jobs found for your user. Submit a restore with:")
                    click.echo("  pulldb restore customer=<id>")
                    return
        except _APIError:
            # Fall through to normal listing if we can't get user's last job
            pass

    params: dict[str, Any] = {"limit": limit}
    if active:
        params["active"] = "true"
    if history:
        params["history"] = "true"
    if filter_status:
        params["filter"] = json_module.dumps({"status": filter_status})

    # If job_id provided, resolve and filter by it
    if job_id:
        # Resolve short prefix to full job ID
        resolved_id = _resolve_job_id(job_id)
        current_filter = {}
        if filter_status:
            current_filter = {"status": filter_status}
        current_filter["id"] = resolved_id
        params["filter"] = json_module.dumps(current_filter)

    try:
        payloads = _api_get("/api/jobs", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    summaries: list[_JobRow] = []
    for payload in payloads[:limit]:
        try:
            summaries.append(_job_row_from_payload(payload))
        except _APIError as exc:
            raise click.ClickException(str(exc)) from exc

    if not summaries:
        click.echo(
            "No matching jobs found. Submit a restore with:\n"
            "  pulldb restore customer=<id>"
        )
        return

    if json_out:
        if wide:
            filtered = payloads[:limit]
        else:
            filtered = [
                {key: value for key, value in entry.items() if key != "staging_name"}
                for entry in payloads[:limit]
            ]
        click.echo(json_module.dumps(filtered, separators=(",", ":")))
        return

    # Table output
    primary_rows: list[list[str]] = []
    staging_values: list[str] = []
    for summary in summaries:
        primary_rows.append(
            [
                summary.status,
                summary.current_operation or "—",
                summary.id[:8],
                summary.source or "—",
                summary.target,
                summary.dbhost or "—",
                summary.user_code,
                _fmt_dt(summary.submitted_at),
                _fmt_dt(summary.started_at),
            ]
        )
        staging_values.append(summary.staging_name or "")

    headers = [
        "STATUS",
        "OPERATION",
        "JOB_ID",
        "SOURCE",
        "TARGET",
        "DB",
        "USER",
        "SUBMITTED",
        "STARTED",
    ]
    if wide:
        headers.append("STAGING")
    # Compute widths
    col_widths: list[int] = []
    for idx, header in enumerate(headers[:9]):
        col_widths.append(max(len(header), *(len(row[idx]) for row in primary_rows)))
    if wide:
        col_widths.append(max(len("STAGING"), *(len(v) for v in staging_values)))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for idx, entry in enumerate(primary_rows):
        line = "  ".join(entry[i].ljust(col_widths[i]) for i in range(9))
        if wide:
            staging_val = staging_values[idx]
            line = f"{line}  {staging_val.ljust(col_widths[-1])}"
        click.echo(line)

    click.echo(f"\n{len(primary_rows)} recent job(s) displayed (limit={limit}).")


def _parse_search_args(
    args: tuple[str, ...],
) -> tuple[str, int | None, bool]:
    """Parse search command arguments.

    Returns:
        Tuple of (query, limit, json_out)
    """
    query: str | None = None
    limit: int | None = None
    json_out = False
    
    i = 0
    while i < len(args):
        arg = args[i]
        
        # Handle --option=value or option=value
        if "=" in arg:
            key, value = arg.lstrip("-").split("=", 1)
            if key == "limit":
                try:
                    limit = int(value)
                except ValueError:
                    raise click.UsageError(f"Invalid limit value: {value}")
            else:
                # Treat as query if no recognized key
                if query is None:
                    query = arg
                else:
                    raise click.UsageError(f"Unrecognized option: {arg}")
        elif arg in ("--json", "json"):
            json_out = True
        elif arg.startswith("--"):
            # Handle --option value syntax
            opt = arg[2:]
            if opt == "limit" and i + 1 < len(args):
                i += 1
                try:
                    limit = int(args[i])
                except ValueError:
                    raise click.UsageError(f"Invalid limit value: {args[i]}")
            elif opt == "json":
                json_out = True
            else:
                raise click.UsageError(f"Unrecognized option: {arg}")
        else:
            # Positional argument - treat as query
            if query is None:
                query = arg
            else:
                raise click.UsageError(f"Unexpected argument: {arg}")
        i += 1
    
    if query is None:
        raise click.UsageError("Missing required argument: QUERY")
    
    return query, limit, json_out


def _parse_list_args(
    args: tuple[str, ...],
) -> tuple[str, str | None, int | None, bool, str]:
    """Parse list command arguments.

    Returns:
        Tuple of (customer, start_date, limit, json_out, s3env)
    """
    customer: str | None = None
    start_date: str | None = None
    limit: int | None = None
    json_out = False
    s3env: str | None = None
    
    i = 0
    while i < len(args):
        arg = args[i]
        
        # Handle --option=value or option=value
        if "=" in arg:
            key, value = arg.lstrip("-").split("=", 1)
            if key == "date":
                start_date = value
            elif key == "limit":
                try:
                    limit = int(value)
                except ValueError:
                    raise click.UsageError(f"Invalid limit value: {value}")
            elif key == "s3env":
                if value not in ("staging", "prod", "both"):
                    raise click.UsageError(f"s3env must be staging, prod, or both. Got: {value}")
                s3env = value
            else:
                # Treat as customer if no recognized key
                if customer is None:
                    customer = arg
                else:
                    raise click.UsageError(f"Unrecognized option: {arg}")
        elif arg in ("--json", "json"):
            json_out = True
        elif arg.startswith("--"):
            # Handle --option value syntax
            opt = arg[2:]
            if opt == "date" and i + 1 < len(args):
                i += 1
                start_date = args[i]
            elif opt == "limit" and i + 1 < len(args):
                i += 1
                try:
                    limit = int(args[i])
                except ValueError:
                    raise click.UsageError(f"Invalid limit value: {args[i]}")
            elif opt == "s3env" and i + 1 < len(args):
                i += 1
                if args[i] not in ("staging", "prod", "both"):
                    raise click.UsageError(f"s3env must be staging, prod, or both. Got: {args[i]}")
                s3env = args[i]
            elif opt == "json":
                json_out = True
            else:
                raise click.UsageError(f"Unrecognized option: {arg}")
        else:
            # Positional argument - treat as customer
            if customer is None:
                customer = arg
            else:
                raise click.UsageError(f"Unexpected argument: {arg}")
        i += 1
    
    if customer is None:
        raise click.UsageError("Missing required argument: CUSTOMER")
    
    # Use default s3env if not specified
    if s3env is None:
        s3env = _get_default_s3env()
    
    return customer, start_date, limit, json_out, s3env


@cli.command("search",
              context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def search_cmd(args: tuple[str, ...]) -> None:
    """Search for customers by name pattern.

    \b
    USAGE:
      pulldb search <query> [options]

    \b
    OPTIONS:
      limit=<N>               Maximum results to show (default: 20)
      json                    Output JSON instead of list

    \b
    EXAMPLES:
      pulldb search action           # Find customers containing 'action'
      pulldb search action*          # Find customers starting with 'action'
      pulldb search *pest            # Find customers ending with 'pest'
      pulldb search actionpest       # Exact match
      pulldb search action limit=50  # Show up to 50 results
    """
    # Parse arguments
    query, limit_arg, json_out = _parse_search_args(args)
    limit = limit_arg if limit_arg is not None else 20

    if limit <= 0 or limit > 500:
        raise click.UsageError("limit must be between 1 and 500")

    # Call customer search API
    params: dict[str, Any] = {
        "q": query,
        "limit": limit,
    }

    try:
        response = _api_get_object("/api/customers/search", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    customers = response.get("customers", [])
    
    if not customers:
        click.echo(f"No customers found matching '{query}'")
        if "*" not in query and "?" not in query:
            click.echo("Tip: Use wildcards like 'action*' to broaden your search.")
        return

    if json_out:
        click.echo(json_module.dumps(customers, indent=2))
        return

    # List output
    click.echo(f"\nCustomers matching '{query}':\n")
    
    for customer in customers:
        click.echo(f"  {customer}")

    click.echo(f"\n{len(customers)} customer(s) found.")
    if len(customers) == limit:
        click.echo(f"(showing first {limit}, use limit=N to see more)")
    click.echo("\nUse 'pulldb list <customer>' to see available backups.")


@cli.command("list",
              context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def list_cmd(args: tuple[str, ...]) -> None:
    """List available backups for a customer.

    \b
    USAGE:
      pulldb list <customer> [options]

    \b
    OPTIONS:
      date=<YYYYMMDD>         Start date (show backups from this date onwards)
      limit=<N>               Maximum backups to show (default: 10)
      s3env=<staging|prod|both>  S3 environment (default: PULLDB_S3ENV_DEFAULT or prod)
      json                    Output JSON instead of table

    \b
    EXAMPLES:
      pulldb list actionpest
      pulldb list actionpest date=20251101
      pulldb list actionpest limit=20
      pulldb list actionpest s3env=prod
    """
    # Parse arguments
    customer, start_date, limit_arg, json_out, environment = _parse_list_args(args)
    limit = limit_arg if limit_arg is not None else 10
    
    # Validate date format if provided
    if start_date:
        if not re.match(r"^\d{8}$", start_date):
            raise click.UsageError(
                f"Invalid date format: '{start_date}'. Use YYYYMMDD (e.g., 20251101)"
            )
        try:
            datetime.strptime(start_date, "%Y%m%d")
        except ValueError as e:
            raise click.UsageError(f"Invalid date: {start_date}") from e

    if limit <= 0 or limit > 100:
        raise click.UsageError("limit must be between 1 and 100")

    # Call backup search API
    params: dict[str, Any] = {
        "customer": customer,
        "environment": environment,
        "limit": limit,
    }
    if start_date:
        params["date_from"] = start_date

    try:
        response = _api_get_object("/api/backups/search", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    backups = response.get("backups", [])
    
    if not backups:
        click.echo(f"No backups found for '{customer}'")
        click.echo("Tip: Use 'pulldb search' to find available customers.")
        return

    if json_out:
        click.echo(json_module.dumps(backups, indent=2))
        return

    # Table output
    click.echo(f"\nBackups for '{customer}':\n")

    headers = ["DATE", "TIME (UTC)", "SIZE", "ENV", "FILENAME"]
    rows: list[list[str]] = []

    for b in backups:
        # Parse timestamp from ISO format
        ts_str = b.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            ts = None
        
        size_mb = float(b.get("size_mb", 0))
        if size_mb >= 1024:
            size_str = f"{size_mb / 1024:.1f} GB"
        else:
            size_str = f"{size_mb:.1f} MB"

        filename = b.get("key", "").rsplit("/", 1)[-1]
        # Truncate long filenames
        if len(filename) > 50:
            filename = filename[:47] + "..."

        rows.append(
            [
                ts.strftime("%Y-%m-%d") if ts else "—",
                ts.strftime("%H:%M:%S") if ts else "—",
                size_str,
                b.get("environment", "")[:4],
                filename,
            ]
        )

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for row in rows:
        click.echo("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    click.echo(f"\n{len(rows)} backup(s) found.")
    if len(backups) == limit:
        click.echo(f"(showing first {limit}, use limit=N to see more)")
    click.echo(f"\nRestore with: pulldb restore {customer}")


def _dump_job_events(job_id: str) -> None:
    """Fetch and display all events for a job once (non-streaming)."""
    try:
        events = _api_get(f"/api/jobs/{job_id}/events", {})
    except _APIError as exc:
        click.echo(f"Error fetching events: {exc}")
        return

    if not events:
        click.echo("No events found for this job.")
        return

    for event in events:
        ts = _parse_iso(event.get("logged_at"))
        ts_str = ts.strftime("%H:%M:%S") if ts else "??:??:??"
        event_type = event.get("event_type", "unknown")
        detail = event.get("detail") or ""
        click.echo(f"[{ts_str}] {event_type}: {detail}")


def _stream_job_events(job_id: str) -> None:
    """Stream job events with deduplication and in-place progress updates.

    For TTY output, restore progress is shown as in-place updates (52% -> 53%)
    rather than flooding the terminal with repetitive lines.
    For piped output, duplicate progress events are simply filtered.
    """
    import sys

    last_id: int | None = None
    last_progress_percent: int | None = None  # Track last displayed progress
    is_tty = sys.stdout.isatty()

    click.echo("(Ctrl+C to stop)")
    while True:
        params: dict[str, Any] = {}
        if last_id is not None:
            params["since_id"] = last_id

        try:
            events = _api_get(f"/api/jobs/{job_id}/events", params)
        except _APIError as exc:
            click.echo(f"Error fetching events: {exc}")
            time.sleep(5)
            continue

        for event in events:
            ts = _parse_iso(event.get("logged_at"))
            ts_str = ts.strftime("%H:%M:%S") if ts else "??:??:??"
            event_type = event.get("event_type", "unknown")
            detail = event.get("detail") or ""

            # Deduplicate restore_progress events - only show when percent changes
            if event_type == "restore_progress" and isinstance(detail, dict):
                percent = int(detail.get("percent", 0))
                if percent == last_progress_percent:
                    last_id = int(event["id"])
                    continue  # Skip duplicate
                last_progress_percent = percent

                # Format compact progress line
                inner = detail.get("detail", {})
                status = inner.get("status", "")
                threads = inner.get("active_threads", "?")
                progress_line = f"[{ts_str}] restore: {percent}% ({threads} threads) {status}"

                if is_tty:
                    # In-place update for TTY - overwrite current line
                    click.echo(f"\r{progress_line:<70}", nl=False)
                else:
                    click.echo(progress_line)
            else:
                # Non-progress events: print normally
                if is_tty and last_progress_percent is not None:
                    click.echo()  # Finish the in-place line with newline
                click.echo(f"[{ts_str}] {event_type}: {detail}")
                last_progress_percent = None  # Reset so next progress starts fresh

            last_id = int(event["id"])

        # Check if job is still active
        try:
            job_data = _api_get_object(f"/api/jobs/{job_id}", {})
            status = job_data.get("status")
            if status not in ("queued", "running", "canceling"):
                if is_tty and last_progress_percent is not None:
                    click.echo()  # Finish any in-place line
                click.echo(f"\nJob {job_id[:8]} finished with status: {status}")
                return
        except _APIError:
            pass  # Continue streaming if we can't check status

        time.sleep(2)


@cli.command("cancel", help="Cancel a queued or running job")
@click.argument("job_id")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompt",
)
def cancel_cmd(job_id: str, force: bool) -> None:
    """Request cancellation of a job.

    For queued jobs, cancellation is immediate.
    For running jobs, the worker will stop at the next checkpoint
    (between major operations like download, restore, post-SQL).

    Job ID can be specified as a full UUID or a short 8-character prefix.
    If multiple jobs match the prefix, you'll be prompted to select one.

    Args:
        job_id: UUID or 8+ char prefix of the job to cancel.
        force: Skip confirmation prompt.

    Examples:
        pulldb cancel 8b4c4a3a                # Short 8-char prefix
        pulldb cancel 8b4c4a3a-85a1-4da2-...  # Full UUID
        pulldb cancel 8b4c4a3a --force        # Skip confirmation
    """
    # Resolve short prefix to full job ID
    resolved_id = _resolve_job_id(job_id)

    # Confirm unless --force
    if not force:
        click.echo(f"Requesting cancellation for job: {resolved_id[:8]}...")
        if not click.confirm("Are you sure you want to cancel this job?"):
            click.echo("Aborted.")
            return

    try:
        response = _api_post(f"/api/jobs/{resolved_id}/cancel", {})
    except click.ClickException:
        # Re-raise click exceptions (404, 409, etc. formatted by _api_post)
        raise

    status = response.get("status", "unknown")
    message = response.get("message", "")

    if status == "canceled":
        click.echo(f"✓ Job {resolved_id[:8]}... canceled successfully.")
        click.echo(f"  {message}")
    elif status == "pending":
        click.echo(f"⏳ Cancellation requested for job {resolved_id[:8]}...")
        click.echo(f"  {message}")
        click.echo(f"\nUse 'pulldb status {resolved_id[:8]}' to monitor.")
    else:
        click.echo(f"Unexpected status: {status}")
        click.echo(f"  {message}")


@cli.command("events", help="Show event log for a job")
@click.argument("job_id")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Follow mode: stream new events as they occur (Ctrl+C to stop)",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    show_default=True,
    help="Maximum number of events to show",
)
@click.option(
    "--full",
    is_flag=True,
    help="Show full event details without truncation",
)
def events_cmd(job_id: str, json_out: bool, follow: bool, limit: int, full: bool) -> None:
    """Show detailed event log for a job.

    Displays timestamped events including job state transitions, progress
    updates, and any errors. Use --follow to stream events in realtime.

    Job ID can be specified as a full UUID or a short 8-character prefix.
    If multiple jobs match the prefix, you'll be prompted to select one.

    Args:
        job_id: UUID or 8+ char prefix of the job.
        json_out: Output raw JSON instead of formatted table.
        follow: Stream events as they occur (Ctrl+C to stop).
        limit: Maximum number of events to retrieve.
        full: Show complete event details without truncation.

    Examples:
        pulldb events 8b4c4a3a              # Short 8-char prefix
        pulldb events 8b4c4a3a --follow     # Stream events
        pulldb events 8b4c4a3a --json       # JSON output
        pulldb events 8b4c4a3a --full       # Full details
    """
    # Resolve short prefix to full job ID
    resolved_id = _resolve_job_id(job_id)

    if follow:
        _stream_job_events(resolved_id)
        return

    # Fetch events
    params: dict[str, Any] = {"limit": limit}
    try:
        events = _api_get(f"/api/jobs/{resolved_id}/events", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    if not events:
        click.echo(f"No events found for job {resolved_id[:8]}...")
        return

    if json_out:
        click.echo(json_module.dumps(events, indent=2, default=str))
        return

    # Table output
    click.echo(f"Events for job {resolved_id[:8]}...\n")

    if full:
        # Full detail mode - show each event with complete formatted detail
        for event in events:
            ts = _parse_iso(event.get("logged_at"))
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "-"
            event_type = event.get("event_type", "unknown")
            detail = event.get("detail") or "-"

            click.echo(f"[{ts_str}] {event_type}")
            click.echo("-" * 60)
            # Format detail - try to parse as JSON for pretty printing
            _print_formatted_detail(detail)
            click.echo()
    else:
        # Compact table mode
        headers = ["TIMESTAMP", "EVENT TYPE", "DETAIL"]
        rows: list[list[str]] = []

        for event in events:
            ts = _parse_iso(event.get("logged_at"))
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "-"
            event_type = event.get("event_type", "unknown")
            detail = event.get("detail") or "-"
            # Truncate long details
            if len(detail) > 60:
                detail = detail[:57] + "..."
            rows.append([ts_str, event_type, detail])

        # Calculate column widths
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))

        # Print header
        header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        click.echo(header_line)
        click.echo("  ".join("-" * w for w in col_widths))

        # Print rows
        for row in rows:
            line = "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
            click.echo(line)

    click.echo(f"\nTotal: {len(events)} event(s)")


@cli.command("history", help="Show job history (completed/failed/canceled jobs)")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of table",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Limit number of rows",
)
@click.option(
    "--days",
    type=int,
    default=30,
    show_default=True,
    help="Show jobs from last N days",
)
@click.option(
    "--user",
    "user_code",
    help="Filter by user code",
)
@click.option(
    "--target",
    help="Filter by target database name",
)
@click.option(
    "--dbhost",
    help="Filter by database host",
)
@click.option(
    "--status",
    "job_status",
    type=click.Choice(["complete", "failed", "canceled"]),
    help="Filter by job status",
)
@click.option(
    "--wide",
    is_flag=True,
    help="Show additional columns including error details",
)
def history_cmd(
    json_out: bool,
    limit: int,
    days: int,
    user_code: str | None,
    target: str | None,
    dbhost: str | None,
    job_status: str | None,
    wide: bool,
) -> None:
    """Show job history with filtering options.

    \b
    USAGE:
      pulldb history                    # Last 30 days of history
      pulldb history --days 7           # Last week only
      pulldb history --status failed    # Only failed jobs
      pulldb history --user jdoe        # Jobs by user code
      pulldb history --wide             # Include error details

    \b
    STATUS VALUES (for --status):
      complete  - Job finished successfully
      failed    - Job failed with error
      canceled  - Job was canceled
    """
    if limit <= 0 or limit > 1000:
        raise click.UsageError("--limit must be between 1 and 1000")

    if days <= 0 or days > 365:
        raise click.UsageError("--days must be between 1 and 365")

    # Build query params
    params: dict[str, Any] = {
        "limit": limit,
        "days": days,
    }
    if user_code:
        params["user_code"] = user_code
    if target:
        params["target"] = target
    if dbhost:
        params["dbhost"] = dbhost
    if job_status:
        params["status"] = job_status

    try:
        history = _api_get("/api/jobs/history", params)
    except _APIError as exc:
        raise click.ClickException(str(exc)) from exc

    if not history:
        click.echo("No job history found matching filters.")
        return

    if json_out:
        click.echo(json_module.dumps(history, indent=2, default=str))
        return

    # Table output
    def _fmt_dt(dt_str: str | None) -> str:
        if not dt_str:
            return "-"
        dt = _parse_iso(dt_str)
        if dt:
            return dt.strftime("%Y-%m-%d %H:%M")
        return "-"

    def _fmt_duration(seconds: float | None) -> str:
        if seconds is None:
            return "-"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            return f"{seconds / 60:.1f}m"
        return f"{seconds / 3600:.1f}h"

    def _status_icon(status: str) -> str:
        if status == "complete":
            return "✓"
        if status == "failed":
            return "✗"
        if status == "canceled":
            return "○"
        return "?"

    # Determine columns
    headers = ["STATUS", "JOB_ID", "TARGET", "USER", "COMPLETED", "DURATION"]
    if wide:
        headers.append("ERROR")

    rows: list[list[str]] = []
    for item in history:
        status_val = item.get("status", "?")
        row = [
            f"{_status_icon(status_val)} {status_val}",
            item.get("id", "")[:12],
            item.get("target", "")[:20],
            item.get("user_code", "")[:6],
            _fmt_dt(item.get("completed_at")),
            _fmt_duration(item.get("duration_seconds")),
        ]
        if wide:
            error = item.get("error_detail") or "-"
            if len(error) > 40:
                error = error[:37] + "..."
            row.append(error)
        rows.append(row)

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    # Print rows
    for row in rows:
        line = "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        click.echo(line)

    # Summary
    complete_count = sum(1 for item in history if item.get("status") == "complete")
    failed_count = sum(1 for item in history if item.get("status") == "failed")
    canceled_count = sum(1 for item in history if item.get("status") == "canceled")

    click.echo(
        f"\n{len(history)} job(s): {complete_count} complete, {failed_count} failed, {canceled_count} canceled"
    )
    click.echo(f"(showing last {days} days, limit {limit})")


@cli.command("profile", help="Show performance profile for a completed job")
@click.argument("job_id")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of formatted display",
)
def profile_cmd(job_id: str, json_out: bool) -> None:
    """Show performance profile for a completed job.

    Displays timing breakdown by restore phase (discovery, download,
    extraction, myloader, post_sql, metadata, atomic_rename) with
    throughput metrics for data-intensive phases.

    Profile data is available after a job completes (success or failure).

    Args:
        job_id: UUID of the job to get profile for (can use short prefix).
        json_out: Output raw JSON instead of formatted display.

    Examples:
        pulldb profile abc12345-6789-...   # Full job ID
        pulldb profile abc12345            # Short prefix
        pulldb profile abc12345 --json     # Raw JSON output
    """
    # Resolve job_id (supports short prefixes)
    resolved_job_id = _resolve_job_id(job_id)

    path = f"/api/jobs/{resolved_job_id}/profile"
    response = _api_request("GET", path, params={})

    if response.status_code == 404:
        error_detail = response.json().get("detail", "Not found")
        raise click.ClickException(error_detail)

    profile = _parse_json_response(response)
    if not isinstance(profile, dict):
        raise click.ClickException("Received invalid response from server.")

    if json_out:
        click.echo(json_module.dumps(profile, indent=2, default=str))
        return

    # Formatted display
    job_id_short = profile.get("job_id", "unknown")[:12]
    total_duration = profile.get("total_duration_seconds")
    total_bytes = profile.get("total_bytes", 0)
    error = profile.get("error")

    click.echo(f"Performance Profile: {job_id_short}...")
    click.echo("=" * 60)

    if error:
        click.echo("Status: Failed")
        click.echo("\nError Details:")
        click.echo("-" * 40)
        # Format multi-line error properly
        for line in str(error).split("\n"):
            click.echo(f"  {line}")
        click.echo("-" * 40)
    else:
        click.echo("Status: Complete")

    if total_duration:
        click.echo(f"Total Duration: {_format_profile_duration(total_duration)}")
    if total_bytes:
        click.echo(f"Total Data: {_format_bytes(total_bytes)}")

    click.echo("\nPhase Breakdown:")
    click.echo("-" * 60)

    # Table headers
    click.echo(f"{'PHASE':<16} {'DURATION':>12} {'%':>8} {'THROUGHPUT':>12}")
    click.echo(f"{'-' * 16} {'-' * 12} {'-' * 8} {'-' * 12}")

    phases = profile.get("phases", {})
    breakdown = profile.get("phase_breakdown_percent", {})

    # Order phases logically
    phase_order = [
        "discovery",
        "download",
        "extraction",
        "myloader",
        "post_sql",
        "metadata",
        "atomic_rename",
    ]

    for phase_name in phase_order:
        if phase_name not in phases:
            continue
        phase = phases[phase_name]
        duration = phase.get("duration_seconds")
        pct = breakdown.get(phase_name, 0)
        mbps = phase.get("mbps")

        duration_str = _format_profile_duration(duration) if duration else "-"
        pct_str = f"{pct:.1f}%" if pct else "-"
        throughput_str = f"{mbps:.1f} MB/s" if mbps else "-"

        click.echo(
            f"{phase_name:<16} {duration_str:>12} {pct_str:>8} {throughput_str:>12}"
        )

    click.echo("-" * 60)

    # Tips based on profile
    if breakdown:
        slowest = max(breakdown.items(), key=lambda x: x[1])
        if slowest[1] > 50:
            click.echo(f"\n💡 Tip: {slowest[0]} took {slowest[1]:.0f}% of total time.")


def _format_profile_duration(seconds: float | None) -> str:
    """Format duration for profile display."""
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.0f}s"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    return f"{hours}h {mins}m"


def _format_bytes(num_bytes: int) -> str:
    """Format bytes for human-readable display."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


# NOTE: Admin-only commands (prune-logs, cleanup-staging, orphan-report, delete-orphans)
# are NOT exposed in the user-facing pulldb CLI.
# They will be available via the pulldb-admin CLI.
# See docs/KNOWLEDGE-POOL.md "CLI Architecture & Scope" for rationale.


@cli.command("hosts", help="Show available database hosts")
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of formatted table",
)
def hosts_cmd(json_out: bool) -> None:
    """Show available database hosts.

    Lists all enabled database hosts where you can restore databases.
    The alias column shows short names you can use with dbhost= parameter.

    Examples:
        pulldb hosts                        # Show available hosts
        pulldb hosts --json                 # Raw JSON output
        pulldb restore customer dbhost=dev  # Use alias in restore
    """
    path = "/api/hosts"
    response = _api_request("GET", path, params={})

    data = _parse_json_response(response)
    if not isinstance(data, dict):
        raise click.ClickException("Received invalid response from server.")

    hosts = data.get("hosts", [])

    if json_out:
        click.echo(json_module.dumps(data, indent=2, default=str))
        return

    if not hosts:
        click.echo("No database hosts available.")
        return

    # Get user's default host
    default_host = data.get("default_host")
    
    # Formatted table display
    click.echo("\nAvailable Database Hosts")
    click.echo("=" * 50)
    click.echo(f"{'ALIAS':<16} {'HOSTNAME':<32}")
    click.echo(f"{'-' * 16} {'-' * 32}")

    for host in hosts:
        alias = host.get("alias") or "—"
        hostname = host.get("hostname", "unknown")
        
        # Mark default host with *
        if default_host and hostname == default_host:
            alias = f"{alias} *"
        
        click.echo(f"{alias:<16} {hostname:<32}")

    click.echo(f"{'-' * 16} {'-' * 32}")
    click.echo(f"\nTotal: {len(hosts)} host(s)")
    if default_host:
        default_alias = data.get("default_alias")
        if default_alias:
            click.echo(f"* = default host")
        else:
            click.echo(f"* = default host")
    click.echo("\nUse alias or hostname with: pulldb restore <customer> dbhost=<alias>")


@cli.command("register", help="Register a new pullDB account or request access from a new machine")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=False,  # Only confirm for new accounts (handled below)
    help="Password for authentication",
)
@click.pass_context
def register_cmd(ctx: click.Context, password: str) -> None:
    """Register a new pullDB account or request access from a new machine.

    This command handles two scenarios:
    
    1. NEW USER: Creates a new user account with your system username.
       The account will be created in a disabled state and must be
       enabled by an administrator before you can submit restore jobs.

    2. EXISTING USER: If you already have an account but are running
       from a new machine (or your key was revoked), this command will
       request a new API key for this host.

    After registering (new or existing):
    1. Contact an administrator to approve your access
    2. Once approved, you can use 'pulldb restore' to submit jobs

    Example:
        pulldb register
    """
    import socket

    username = ctx.obj.get("username") or get_calling_username()
    user_state = ctx.obj.get("user_state", UserState.NOT_REGISTERED)
    base_url, timeout = _load_api_config()

    # Auto-detect hostname for tracking
    host_name = socket.gethostname()

    # Check if this is an existing user scenario
    if user_state in (UserState.NO_HOST_CREDENTIALS, UserState.KEY_REVOKED):
        # Existing user - request a new host key
        _request_host_key_for_existing_user(
            username=username,
            password=password,
            host_name=host_name,
            base_url=base_url,
            timeout=timeout,
            user_state=user_state,
        )
        return

    # New user - require password confirmation
    confirm_password = click.prompt(
        "Confirm password",
        hide_input=True,
        default="",
        show_default=False,
    )
    if password != confirm_password:
        raise click.ClickException("Passwords do not match")

    # Validate password minimum requirements
    if len(password) < 8:
        raise click.ClickException("Password must be at least 8 characters")

    # Call API to register new user
    url = f"{base_url}/api/auth/register"
    payload = {
        "username": username,
        "password": password,
        "host_name": host_name,
    }

    try:
        response = requests_module.post(url, json=payload, timeout=timeout, verify=_TLS_VERIFY)

        if response.status_code == 201:
            data = response.json()
            user_code = data.get("user_code", "unknown")
            api_key = data.get("api_key")
            api_secret = data.get("api_secret")

            click.echo("✓ Account created successfully!")
            click.echo("")
            click.echo(f"  Username:  {username}")
            click.echo(f"  User Code: {user_code}")

            # Save API credentials to config file
            if api_key and api_secret:
                from pulldb.cli.auth import save_credentials_to_file

                try:
                    save_credentials_to_file(api_key, api_secret)
                    click.echo("")
                    click.echo("✓ API credentials saved to ~/.pulldb/credentials")
                except Exception as exc:
                    click.echo("", err=True)
                    click.echo(f"⚠ Could not save credentials: {exc}", err=True)
                    click.echo("", err=True)
                    click.echo("Save these credentials manually:", err=True)
                    click.echo(f"  PULLDB_API_KEY={api_key}", err=True)
                    click.echo(f"  PULLDB_API_SECRET={api_secret}", err=True)

            click.echo("")
            click.echo("Your account is pending approval.")
            click.echo("Contact an administrator to enable your account.")
        elif response.status_code == 409:
            # User exists - try to request a new host key instead
            click.echo(f"User '{username}' already exists. Requesting API key for this machine...")
            click.echo("")
            _request_host_key_for_existing_user(
                username=username,
                password=password,
                host_name=host_name,
                base_url=base_url,
                timeout=timeout,
                user_state=UserState.NO_HOST_CREDENTIALS,
            )
        elif response.status_code == 400:
            error_detail = response.json().get("detail", "Invalid request")
            raise click.ClickException(f"Registration failed: {error_detail}")
        elif response.status_code == 503:
            raise click.ClickException(
                "Authentication service not available. Contact an administrator."
            )
        else:
            error_msg = _format_api_error(response)
            raise click.ClickException(f"Registration failed: {error_msg}")

    except RequestException as exc:
        raise click.ClickException(f"Cannot connect to API: {exc}") from exc


def _request_host_key_for_existing_user(
    username: str,
    password: str,
    host_name: str,
    base_url: str,
    timeout: float,
    user_state: str,
) -> None:
    """Request a new API key for an existing user from a new host.
    
    This is called when:
    - User exists but no credentials on this host
    - User's API key was revoked
    
    Args:
        username: The username
        password: User's password for authentication
        host_name: Hostname of this machine
        base_url: API base URL
        timeout: Request timeout
        user_state: Current user state for messaging
    """
    from pulldb.cli.auth import save_credentials_to_file

    context_msg = "revoked" if user_state == UserState.KEY_REVOKED else "new machine"
    
    url = f"{base_url}/api/auth/request-host-key"
    payload = {
        "username": username,
        "password": password,
        "host_name": host_name,
    }

    try:
        response = requests_module.post(url, json=payload, timeout=timeout, verify=_TLS_VERIFY)

        if response.status_code == 200:
            data = response.json()
            api_key = data.get("api_key")
            api_secret = data.get("api_secret")
            user_code = data.get("user_code", "unknown")

            click.echo(f"✓ API key requested for {context_msg}!")
            click.echo("")
            click.echo(f"  Username:  {username}")
            click.echo(f"  User Code: {user_code}")
            click.echo(f"  Hostname:  {host_name}")

            # Save API credentials to config file
            if api_key and api_secret:
                try:
                    save_credentials_to_file(api_key, api_secret)
                    click.echo("")
                    click.echo("✓ API credentials saved to ~/.pulldb/credentials")
                except Exception as exc:
                    click.echo("", err=True)
                    click.echo(f"⚠ Could not save credentials: {exc}", err=True)
                    click.echo("", err=True)
                    click.echo("Save these credentials manually:", err=True)
                    click.echo(f"  PULLDB_API_KEY={api_key}", err=True)
                    click.echo(f"  PULLDB_API_SECRET={api_secret}", err=True)

            click.echo("")
            click.echo("⚠ Your API key is PENDING APPROVAL")
            click.echo("Contact an administrator to approve your key.")
            click.echo("Commands will fail with 'API key pending approval' until approved.")

        elif response.status_code == 401:
            raise click.ClickException("Invalid username or password.")
        elif response.status_code == 403:
            raise click.ClickException(
                "Your account is disabled. Contact an administrator."
            )
        elif response.status_code == 503:
            raise click.ClickException(
                "Authentication service not available. Contact an administrator."
            )
        else:
            error_msg = _format_api_error(response)
            raise click.ClickException(f"Request failed: {error_msg}")

    except RequestException as exc:
        raise click.ClickException(f"Cannot connect to API: {exc}") from exc

@cli.command("setpass", help="Set a new password (required after password reset)")
@click.option(
    "--current-password",
    prompt=True,
    hide_input=True,
    help="Current password (or temporary password if first-time setup)",
)
@click.option(
    "--new-password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="New password",
)
@click.pass_context
def setpass_cmd(ctx: click.Context, current_password: str, new_password: str) -> None:
    """Set a new password for the current user.

    This command is used to:
    - Change password after an admin/manager issued a password reset
    - Voluntarily change your password

    If you don't have an account yet, use 'pulldb register' first.

    When your password has been reset by a manager or admin, you must
    use this command to set a new password before you can log in again.

    Example:
        pulldb setpass
    """
    username = ctx.obj.get("username") or get_calling_username()
    user_state = ctx.obj.get("user_state", UserState.ENABLED)
    base_url, timeout = _load_api_config()

    # Check if user is registered
    if user_state == UserState.NOT_REGISTERED:
        raise click.ClickException(
            f"User '{username}' is not registered. "
            "Use 'pulldb register' to create an account first."
        )

    # Validate new password minimum requirements
    if len(new_password) < 8:
        raise click.ClickException("New password must be at least 8 characters")

    # Call API to change password
    url = f"{base_url}/api/auth/change-password"
    payload = {
        "username": username,
        "current_password": current_password,
        "new_password": new_password,
    }

    try:
        response = requests_module.post(url, json=payload, timeout=timeout, verify=_TLS_VERIFY)

        if response.status_code == 200:
            click.echo("✓ Password changed successfully")
            click.echo("You can now log in with your new password.")
        elif response.status_code == 401:
            raise click.ClickException(
                "Current password is incorrect. "
                "If this is a new account, use the temporary password provided."
            )
        elif response.status_code == 403:
            raise click.ClickException(
                "Password change not allowed. Contact your administrator."
            )
        elif response.status_code == 404:
            raise click.ClickException(
                f"User '{username}' not found in the system."
            )
        else:
            error_msg = _format_api_error(response)
            raise click.ClickException(f"Password change failed: {error_msg}")

    except RequestException as exc:
        raise click.ClickException(f"Cannot connect to API: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point for pullDB CLI.

    Args:
        argv: Command-line arguments. If None, uses sys.argv.

    Returns:
        Exit code: 0 for success, non-zero for errors.
    """
    try:
        cli.main(args=list(argv) if argv is not None else None, standalone_mode=False)
        return 0
    except click.exceptions.NoArgsIsHelpError as exc:
        click.echo(exc.ctx.get_help())
        return 1
    except click.exceptions.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 1
    except SystemExit as exc:  # click may raise SystemExit
        # exc.code can be str | int | None, but we need to return int
        if isinstance(exc.code, int):
            return exc.code
        return 1 if exc.code else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
