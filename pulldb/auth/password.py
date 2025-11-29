"""Password hashing utilities for pullDB.

Phase 4: Uses bcrypt for secure password storage. This module provides
a simple interface for hashing and verifying passwords.

Note: Requires bcrypt>=4.2.0 to be installed.
"""

from __future__ import annotations

import logging

import bcrypt


logger = logging.getLogger(__name__)


# Default cost factor (work factor)
# 12 rounds is the current recommended minimum (2024)
# Each increment doubles the computation time
DEFAULT_ROUNDS = 12

# bcrypt hash format has at least 4 parts: $version$rounds$salt+hash
_BCRYPT_MIN_PARTS = 3


def hash_password(password: str, rounds: int = DEFAULT_ROUNDS) -> str:
    """Hash a password using bcrypt.

    Args:
        password: Plain text password to hash.
        rounds: Cost factor for bcrypt (default: 12).

    Returns:
        Bcrypt hash string (includes salt and algorithm info).

    Raises:
        ValueError: If password is empty.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    # bcrypt expects bytes
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=rounds)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a bcrypt hash.

    Args:
        plain_password: Plain text password to verify.
        hashed_password: Bcrypt hash to verify against.

    Returns:
        True if password matches, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        password_bytes = plain_password.encode("utf-8")
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception as e:
        # Log but don't expose hash verification errors
        logger.warning("Password verification error: %s", type(e).__name__)
        return False


def needs_rehash(hashed_password: str, target_rounds: int = DEFAULT_ROUNDS) -> bool:
    """Check if a password hash needs to be upgraded.

    Hashes may need upgrading if the number of rounds has been increased.

    Args:
        hashed_password: Existing bcrypt hash.
        target_rounds: Desired cost factor.

    Returns:
        True if hash should be regenerated, False otherwise.
    """
    if not hashed_password:
        return False

    try:
        # bcrypt hash format: $2b$rounds$salt+hash
        # Extract current rounds from the hash
        parts = hashed_password.split("$")
        if len(parts) >= _BCRYPT_MIN_PARTS:
            current_rounds = int(parts[2])
            return current_rounds < target_rounds
        return False
    except (ValueError, IndexError):
        # Can't parse hash, assume it doesn't need rehash
        return False
