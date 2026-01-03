"""CLI authentication module for pullDB.

Provides HMAC-signed authentication headers for API requests.

All API requests are cryptographically signed using HMAC-SHA256 to:
- Verify the request came from someone with the secret key
- Prevent request tampering (body is part of signature)
- Prevent replay attacks (timestamp is part of signature)

Required environment variables:
- PULLDB_API_KEY: API key ID (identifies the caller)
- PULLDB_API_SECRET: API secret key (used for HMAC signing, never transmitted)

Optional:
- PULLDB_API_KEY_USER: Username associated with this API key (server-side config)
"""

from __future__ import annotations

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

    This is used to identify the local system user for job submissions.
    Authentication is done separately via HMAC signatures.

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


def get_api_credentials() -> tuple[str, str]:
    """Get API key credentials from environment.

    Returns:
        Tuple of (key_id, secret)

    Raises:
        RuntimeError: If credentials are not configured.
    """
    key_id = os.environ.get("PULLDB_API_KEY")
    secret = os.environ.get("PULLDB_API_SECRET")

    if not key_id or not secret:
        raise RuntimeError(
            "API credentials not configured. Set PULLDB_API_KEY and PULLDB_API_SECRET "
            "environment variables. See: pulldb docs authentication"
        )

    return key_id, secret


def has_api_credentials() -> bool:
    """Check if API credentials are configured.

    Returns:
        True if both PULLDB_API_KEY and PULLDB_API_SECRET are set.
    """
    return bool(
        os.environ.get("PULLDB_API_KEY") and os.environ.get("PULLDB_API_SECRET")
    )


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
    """Get HMAC-signed authentication headers for API requests.

    All requests are signed with HMAC-SHA256 covering:
    - HTTP method
    - Request path
    - Timestamp (for replay protection)
    - Body hash (for tamper protection)

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path (e.g., /api/jobs)
        body: Request body (JSON string or bytes), None for GET requests

    Returns:
        Dictionary with X-API-Key, X-Timestamp, X-Signature headers.

    Raises:
        RuntimeError: If API credentials are not configured.
    """
    key_id, secret = get_api_credentials()
    timestamp = get_signature_timestamp()
    signature = compute_request_signature(method, path, body, timestamp, secret)

    return {
        "X-API-Key": key_id,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


def get_current_username() -> str:
    """Get display name for the current API authentication.

    Returns the API key ID (truncated for display) or indicates
    that credentials are not configured.

    Returns:
        Display string for the authenticated identity.
    """
    if has_api_credentials():
        key_id, _ = get_api_credentials()
        # Truncate long key IDs for display
        if len(key_id) > KEY_ID_DISPLAY_LENGTH:
            return f"[API Key: {key_id[:KEY_ID_DISPLAY_LENGTH]}...]"
        return f"[API Key: {key_id}]"

    return "[No API credentials configured]"


# Type alias for type hints
AuthHeaders = dict[str, str]
