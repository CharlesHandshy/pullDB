"""CLI authentication module for pullDB.

Provides authentication headers for API requests. Supports multiple auth methods:

1. X-Trusted-User header (default) - Uses system username detection
2. API Key authentication (future) - Uses stored key/secret pair
3. Signed requests (most secure) - HMAC signature for request integrity

Environment variables:
- PULLDB_API_KEY: API key ID for key-based auth
- PULLDB_API_SECRET: API secret for key-based auth
- PULLDB_AUTH_METHOD: 'trusted' (default), 'apikey', or 'signed'

When API keys are configured, they take precedence over trusted-user mode.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import subprocess
from datetime import datetime, timezone


# Constants
KEY_ID_DISPLAY_LENGTH = 20
SIGNATURE_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def get_calling_username() -> str:
    """Get the original SSH user, even after sudo su -.

    Detection order:
    1. SUDO_USER - works for plain 'sudo' commands
    2. 'who am i' - works after 'sudo su -' by checking TTY owner
    3. USER - fallback to current user

    Returns:
        The original SSH username that initiated the session.
    """
    # Try SUDO_USER first (works for plain sudo)
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        return sudo_user

    # Fall back to 'who am i' (works after sudo su -)
    # This returns the user who owns the current TTY/pts
    try:
        result = subprocess.run(
            ["who", "am", "i"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,  # Don't raise on non-zero exit
        )
        if result.returncode == 0 and result.stdout.strip():
            # Output format: "username pts/0 2025-12-31 10:00 (192.168.1.1)"
            parts = result.stdout.split()
            if parts and parts[0] != "root":
                return parts[0]
    except Exception:
        pass  # Fall through to USER

    return os.environ.get("USER") or getpass.getuser() or "unknown"


def get_auth_method() -> str:
    """Get configured authentication method.

    Returns:
        'signed' for HMAC-signed requests (most secure)
        'apikey' for simple API key auth
        'trusted' for X-Trusted-User header (default)
    """
    # Check for explicit method override
    method = os.environ.get("PULLDB_AUTH_METHOD", "").lower()
    if method in ("signed", "hmac"):
        return "signed"
    if method in ("apikey", "api_key", "key"):
        return "apikey"

    # Auto-detect: if API key is set, use signed mode (most secure)
    if os.environ.get("PULLDB_API_KEY") and os.environ.get("PULLDB_API_SECRET"):
        return "signed"

    return "trusted"


def get_api_key_credentials() -> tuple[str, str] | None:
    """Get API key credentials from environment.
    
    Returns:
        Tuple of (key_id, secret) if configured, None otherwise.
    """
    key_id = os.environ.get("PULLDB_API_KEY")
    secret = os.environ.get("PULLDB_API_SECRET")

    if key_id and secret:
        return key_id, secret
    return None


def compute_request_signature(
    method: str,
    path: str,
    body: str | bytes | None,
    timestamp: str,
    secret: str,
) -> str:
    """Compute HMAC-SHA256 signature for a request.

    The signature covers the HTTP method, path, timestamp, and body hash
    to prevent tampering and replay attacks.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path (e.g., /api/jobs)
        body: Request body (JSON string or bytes), or None for GET requests
        timestamp: ISO 8601 timestamp (UTC)
        secret: API secret key

    Returns:
        Hex-encoded HMAC-SHA256 signature
    """
    # Hash the body (or empty string for GET)
    if body:
        if isinstance(body, str):
            body = body.encode("utf-8")
        body_hash = hashlib.sha256(body).hexdigest()
    else:
        body_hash = hashlib.sha256(b"").hexdigest()

    # Build string to sign
    string_to_sign = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}"

    # Compute HMAC-SHA256
    signature = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return signature


def get_signature_timestamp() -> str:
    """Get current UTC timestamp in signature format.

    Returns:
        ISO 8601 formatted UTC timestamp (e.g., 2026-01-03T15:42:00Z)
    """
    return datetime.now(timezone.utc).strftime(SIGNATURE_TIMESTAMP_FORMAT)


def get_auth_headers(
    method: str = "GET",
    path: str = "/",
    body: str | bytes | None = None,
) -> dict[str, str]:
    """Get authentication headers for API requests.

    Returns headers based on configured auth method:
    - Signed: HMAC signature for request integrity (most secure)
    - API Key: Authorization: Basic base64(key:secret)
    - Trusted: X-Trusted-User: <username>

    Args:
        method: HTTP method (GET, POST, etc.) - needed for signed mode
        path: Request path - needed for signed mode
        body: Request body - needed for signed mode

    Returns:
        Dictionary of headers to include in requests.
    """
    headers: dict[str, str] = {}
    auth_method = get_auth_method()

    if auth_method == "signed":
        credentials = get_api_key_credentials()
        if credentials:
            key_id, secret = credentials
            timestamp = get_signature_timestamp()
            signature = compute_request_signature(method, path, body, timestamp, secret)

            headers["X-API-Key"] = key_id
            headers["X-Timestamp"] = timestamp
            headers["X-Signature"] = signature
            return headers

    if auth_method == "apikey":
        credentials = get_api_key_credentials()
        if credentials:
            key_id, secret = credentials
            # Use HTTP Basic auth format
            auth_string = f"{key_id}:{secret}"
            encoded = base64.b64encode(auth_string.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
            return headers

    # Default to trusted mode
    username = get_calling_username()
    headers["X-Trusted-User"] = username
    return headers


def get_current_username() -> str:
    """Get the username that will be used for API authentication.

    For trusted mode, returns the detected system username.
    For API key/signed mode, returns the key ID (for display purposes).

    Returns:
        Username or key identifier.
    """
    method = get_auth_method()

    if method in ("apikey", "signed"):
        credentials = get_api_key_credentials()
        if credentials:
            key_id, _ = credentials
            # Truncate long key IDs for display
            if len(key_id) > KEY_ID_DISPLAY_LENGTH:
                return f"[API Key: {key_id[:KEY_ID_DISPLAY_LENGTH]}...]"
            return f"[API Key: {key_id}]"

    return get_calling_username()


# Type alias for type hints
AuthHeaders = dict[str, str]
