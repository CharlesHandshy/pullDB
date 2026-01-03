"""CLI authentication module for pullDB.

Provides authentication headers for API requests. Supports multiple auth methods:

1. X-Trusted-User header (default) - Uses system username detection
2. API Key authentication (future) - Uses stored key/secret pair

Environment variables:
- PULLDB_API_KEY: API key ID for key-based auth
- PULLDB_API_SECRET: API secret for key-based auth
- PULLDB_AUTH_METHOD: 'trusted' (default) or 'apikey'

When API keys are configured, they take precedence over trusted-user mode.
"""

from __future__ import annotations

import base64
import getpass
import os
import subprocess


# Constants
KEY_ID_DISPLAY_LENGTH = 20


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
        'apikey' if API key is configured, otherwise 'trusted'
    """
    # Check for explicit method override
    method = os.environ.get("PULLDB_AUTH_METHOD", "").lower()
    if method in ("apikey", "api_key", "key"):
        return "apikey"
    
    # Auto-detect: if API key is set, use it
    if os.environ.get("PULLDB_API_KEY") and os.environ.get("PULLDB_API_SECRET"):
        return "apikey"
    
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


def get_auth_headers() -> dict[str, str]:
    """Get authentication headers for API requests.
    
    Returns headers based on configured auth method:
    - API Key: Authorization: Basic base64(key:secret)
    - Trusted: X-Trusted-User: <username>
    
    Returns:
        Dictionary of headers to include in requests.
    """
    headers: dict[str, str] = {}
    method = get_auth_method()
    
    if method == "apikey":
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
    For API key mode, returns the key ID (for display purposes).
    
    Returns:
        Username or key identifier.
    """
    method = get_auth_method()
    
    if method == "apikey":
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
