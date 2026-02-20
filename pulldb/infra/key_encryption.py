"""AES-256-GCM at-rest encryption for API key secrets.

HCA Layer: shared / infra  (pulldb/infra/)

Wire format for encrypted values:
    aes256gcm:<base64url(12-byte-nonce || ciphertext || 16-byte-tag)>

The prefix acts as a version sentinel so that plaintext values that
pre-date encryption are still readable during the migration window.

Key configuration
-----------------
Set ``PULLDB_KEY_ENCRYPTION_KEY`` to a URL-safe base64-encoded 32-byte key.
Generate one with::

    python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

When the environment variable is absent the module operates in **passthrough
mode**: encrypt_secret() returns the value unchanged and decrypt_secret()
also returns the value unchanged.  This lets the server start in development
environments without the key configured.

Usage example
-------------
    from pulldb.infra.key_encryption import encrypt_secret, decrypt_secret

    stored  = encrypt_secret(raw_secret)   # persisted to DB
    raw     = decrypt_secret(stored)       # retrieved from DB
"""

from __future__ import annotations

import base64
import logging
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

_ENV_VAR = "PULLDB_KEY_ENCRYPTION_KEY"
_PREFIX = "aes256gcm:"
_NONCE_BYTES = 12  # 96-bit nonce recommended for AES-GCM


# -------------------------------------------------------------------
# Key management
# -------------------------------------------------------------------


def get_encryption_key() -> bytes | None:
    """Return the 32-byte AES key from the environment, or None if not set.

    Returns:
        32-byte key bytes, or None if ``PULLDB_KEY_ENCRYPTION_KEY`` is absent.

    Raises:
        ValueError: If the env var is set but does not decode to exactly 32 bytes.
    """
    raw = os.environ.get(_ENV_VAR)
    if not raw:
        return None
    try:
        # Strip any existing padding, then re-pad to a multiple of 4
        stripped = raw.rstrip("=")
        padding = (4 - len(stripped) % 4) % 4
        key = base64.urlsafe_b64decode(stripped + "=" * padding)
    except Exception as exc:
        raise ValueError(
            f"{_ENV_VAR} is not valid base64: {exc}"
        ) from exc
    if len(key) != 32:
        raise ValueError(
            f"{_ENV_VAR} must decode to exactly 32 bytes; got {len(key)}"
        )
    return key


# -------------------------------------------------------------------
# Encrypt / decrypt
# -------------------------------------------------------------------


def is_encrypted(value: str) -> bool:
    """Return True if *value* carries the ``aes256gcm:`` prefix."""
    return value.startswith(_PREFIX)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM and return the wire-format string.

    If ``PULLDB_KEY_ENCRYPTION_KEY`` is not set the function returns *plaintext*
    unchanged (passthrough mode).  This intentional fallback lets the service
    run in development without encryption while production always uses the key.

    Each call generates a fresh 12-byte random nonce, so identical inputs
    produce different ciphertexts.

    Args:
        plaintext: The secret string to encrypt.

    Returns:
        ``aes256gcm:<base64url(nonce + ciphertext + tag)>`` or the original
        *plaintext* when no key is configured.
    """
    key = get_encryption_key()
    if key is None:
        return plaintext

    nonce = secrets.token_bytes(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
    blob = base64.urlsafe_b64encode(nonce + ciphertext_with_tag).decode()
    return f"{_PREFIX}{blob}"


def decrypt_secret(value: str) -> str:
    """Decrypt a wire-format secret back to plaintext.

    * If *value* has the ``aes256gcm:`` prefix: decrypt it.
    * If *value* has no prefix: return it unchanged (migration-safe passthrough).
    * If no key is configured but *value* is encrypted: raise ``RuntimeError``.

    Args:
        value: The stored secret (may be plaintext or encrypted).

    Returns:
        The plaintext secret.

    Raises:
        RuntimeError: If *value* is encrypted but no key is configured.
        ValueError: If the base64 or AES-GCM decryption fails (corrupted data).
    """
    if not is_encrypted(value):
        return value  # legacy plaintext — passthrough during migration

    key = get_encryption_key()
    if key is None:
        raise RuntimeError(
            f"Cannot decrypt value: {_ENV_VAR} is not set. "
            "Configure the encryption key or restore a plaintext backup."
        )

    blob_b64 = value[len(_PREFIX):]
    try:
        stripped = blob_b64.rstrip("=")
        padding = (4 - len(stripped) % 4) % 4
        blob = base64.urlsafe_b64decode(stripped + "=" * padding)
    except Exception as exc:
        raise ValueError(f"Malformed encrypted secret (base64 error): {exc}") from exc

    if len(blob) < _NONCE_BYTES + 16:  # nonce + minimum tag
        raise ValueError("Encrypted secret blob is too short to be valid.")

    nonce = blob[:_NONCE_BYTES]
    ciphertext_with_tag = blob[_NONCE_BYTES:]

    try:
        aesgcm = AESGCM(key)
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
    except Exception as exc:
        raise ValueError(f"AES-GCM decryption failed (key mismatch or corruption): {exc}") from exc

    return plaintext_bytes.decode()
