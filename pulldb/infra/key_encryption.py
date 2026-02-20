"""AES-256-GCM at-rest encryption for API key secrets.

HCA Layer: shared / infra  (pulldb/infra/)

Wire format for encrypted values:
    aes256gcm:<base64url(12-byte-nonce || ciphertext || 16-byte-tag)>

The prefix acts as a version sentinel so that plaintext values that
pre-date encryption are still readable during the migration window.

Key configuration
-----------------
Primary key (required for encryption to be active)::

    PULLDB_KEY_ENCRYPTION_KEY=<base64url-encoded 32 bytes>

Old key (set during rotation only, removed once migration completes)::

    PULLDB_KEY_ENCRYPTION_KEY_OLD=<previous value of PULLDB_KEY_ENCRYPTION_KEY>

When only the primary key is set, the module encrypts all new values and
decrypts all stored values as normal.

When the old key is also set (rotation in progress):

* ``decrypt_secret()`` tries the primary key first; if the GCM tag check
  fails it transparently tries the old key.  Auth never breaks mid-rotation.
* ``reencrypt_if_needed()`` detects rows encrypted with the old key and
  re-encrypts them with the primary key.  Call via
  ``migrate_encrypt_existing_keys()`` to complete the rotation.
* Once all rows are re-encrypted, remove ``PULLDB_KEY_ENCRYPTION_KEY_OLD``
  and restart the service.

When both variables are absent the module operates in **passthrough mode**:
encrypt returns the value unchanged, decrypt returns the value unchanged.

Key generation::

    python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

Usage example
-------------
    from pulldb.infra.key_encryption import encrypt_secret, decrypt_secret

    stored  = encrypt_secret(raw_secret)   # persisted to DB
    raw     = decrypt_secret(stored)       # retrieved from DB (transparent fallback to old key)
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
_OLD_ENV_VAR = "PULLDB_KEY_ENCRYPTION_KEY_OLD"
_PREFIX = "aes256gcm:"
_NONCE_BYTES = 12  # 96-bit nonce recommended for AES-GCM


# -------------------------------------------------------------------
# Key management
# -------------------------------------------------------------------


def _decode_key(env_var: str, raw: str) -> bytes:
    """Decode a base64url key string and validate it is exactly 32 bytes.

    Args:
        env_var: Name of the environment variable (for error messages).
        raw: Raw base64url string from the environment.

    Returns:
        32-byte key.

    Raises:
        ValueError: If the string isn't valid base64 or doesn't decode to 32 bytes.
    """
    try:
        stripped = raw.rstrip("=")
        padding = (4 - len(stripped) % 4) % 4
        key = base64.urlsafe_b64decode(stripped + "=" * padding)
    except Exception as exc:
        raise ValueError(f"{env_var} is not valid base64: {exc}") from exc
    if len(key) != 32:
        raise ValueError(
            f"{env_var} must decode to exactly 32 bytes; got {len(key)}"
        )
    return key


def get_encryption_key() -> bytes | None:
    """Return the primary 32-byte AES key, or None if not configured.

    Raises:
        ValueError: If the env var is set but invalid.
    """
    raw = os.environ.get(_ENV_VAR)
    if not raw:
        return None
    return _decode_key(_ENV_VAR, raw)


def get_old_encryption_key() -> bytes | None:
    """Return the old (previous) 32-byte AES key used during key rotation.

    Set ``PULLDB_KEY_ENCRYPTION_KEY_OLD`` to the previous value of
    ``PULLDB_KEY_ENCRYPTION_KEY`` while rotating.  Once all rows have been
    re-encrypted with the primary key, remove this variable.

    Returns:
        32-byte key bytes, or None if rotation is not in progress.

    Raises:
        ValueError: If set but not valid base64 or wrong length.
    """
    raw = os.environ.get(_OLD_ENV_VAR)
    if not raw:
        return None
    return _decode_key(_OLD_ENV_VAR, raw)


def is_rotation_in_progress() -> bool:
    """Return True when both the primary key and old key are configured."""
    return get_encryption_key() is not None and get_old_encryption_key() is not None


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _decode_blob(value: str) -> bytes:
    """Strip the prefix and base64-decode an encrypted value to raw bytes."""
    blob_b64 = value[len(_PREFIX):]
    stripped = blob_b64.rstrip("=")
    padding = (4 - len(stripped) % 4) % 4
    try:
        return base64.urlsafe_b64decode(stripped + "=" * padding)
    except Exception as exc:
        raise ValueError(f"Malformed encrypted secret (base64 error): {exc}") from exc


def _try_decrypt(blob: bytes, key: bytes) -> bytes | None:
    """Attempt AES-GCM decryption. Returns plaintext bytes or None on failure."""
    if len(blob) < _NONCE_BYTES + 16:
        return None
    nonce = blob[:_NONCE_BYTES]
    ciphertext_with_tag = blob[_NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext_with_tag, None)
    except Exception:
        return None


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------


def is_encrypted(value: str) -> bool:
    """Return True if *value* carries the ``aes256gcm:`` prefix."""
    return value.startswith(_PREFIX)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM and return the wire-format string.

    If ``PULLDB_KEY_ENCRYPTION_KEY`` is not set the function returns *plaintext*
    unchanged (passthrough mode).

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
    ciphertext_with_tag = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    blob = base64.urlsafe_b64encode(nonce + ciphertext_with_tag).decode()
    return f"{_PREFIX}{blob}"


def decrypt_secret(value: str) -> str:
    """Decrypt a wire-format secret back to plaintext.

    Decryption order:
    1. If *value* has no prefix → return unchanged (legacy plaintext, migration window).
    2. Try the primary key (``PULLDB_KEY_ENCRYPTION_KEY``).
    3. If the primary key fails **and** the old key is set
       (``PULLDB_KEY_ENCRYPTION_KEY_OLD``), try the old key.  This keeps
       auth working transparently while a key rotation is in progress.
    4. If no key decrypts successfully → raise ``ValueError``.

    Args:
        value: The stored secret (may be plaintext or encrypted).

    Returns:
        The plaintext secret.

    Raises:
        RuntimeError: If *value* is encrypted but no key is configured.
        ValueError: If the blob is malformed or neither key can decrypt it.
    """
    if not is_encrypted(value):
        return value  # legacy plaintext — passthrough during migration

    primary = get_encryption_key()
    if primary is None:
        raise RuntimeError(
            f"Cannot decrypt value: {_ENV_VAR} is not set. "
            "Configure the encryption key or restore a plaintext backup."
        )

    blob = _decode_blob(value)

    if len(blob) < _NONCE_BYTES + 16:
        raise ValueError("Encrypted secret blob is too short to be valid.")

    # Try primary key first
    plaintext_bytes = _try_decrypt(blob, primary)
    if plaintext_bytes is not None:
        return plaintext_bytes.decode()

    # Primary key failed — try old key if rotation is in progress
    old = get_old_encryption_key()
    if old is not None:
        plaintext_bytes = _try_decrypt(blob, old)
        if plaintext_bytes is not None:
            logger.debug(
                "decrypt_secret: decrypted using old key — "
                "run 'pulldb-admin keys encrypt-secrets' to complete rotation"
            )
            return plaintext_bytes.decode()

    raise ValueError(
        "AES-GCM decryption failed (key mismatch or corruption): "
        "neither the primary key nor the old key could decrypt this value."
    )


def reencrypt_if_needed(value: str) -> tuple[str, bool]:
    """Re-encrypt *value* with the primary key if it was encrypted with the old key.

    Used by the migration pass to complete a key rotation.

    Returns:
        ``(value, changed)`` where *changed* is True only when the value was
        re-encrypted with the primary key during this call.  When *changed* is
        True the caller must write the new value to the database.

    Behaviour summary:
    - Plaintext value → returns as-is, ``False``.
    - Encrypted with primary key → returns as-is, ``False`` (already current).
    - Encrypted with old key → decrypts and re-encrypts with primary, ``True``.
    - No old key configured → returns as-is, ``False`` (no rotation in progress).

    Raises:
        ValueError: If the value is encrypted but neither key can decrypt it.
        RuntimeError: If the value is encrypted but no primary key is configured.
    """
    if not is_encrypted(value):
        return value, False

    primary = get_encryption_key()
    if primary is None:
        raise RuntimeError(
            f"Cannot re-encrypt: {_ENV_VAR} is not set."
        )

    old = get_old_encryption_key()
    if old is None:
        return value, False  # No rotation in progress — nothing to do

    blob = _decode_blob(value)
    if len(blob) < _NONCE_BYTES + 16:
        raise ValueError("Encrypted secret blob is too short to be valid.")

    # If primary key decrypts it, it's already using the new key — no-op
    plaintext_bytes = _try_decrypt(blob, primary)
    if plaintext_bytes is not None:
        return value, False

    # Primary failed — try old key
    plaintext_bytes = _try_decrypt(blob, old)
    if plaintext_bytes is not None:
        new_value = encrypt_secret(plaintext_bytes.decode())
        return new_value, True

    raise ValueError(
        "reencrypt_if_needed: neither key could decrypt the value — "
        "data may be corrupted or was encrypted with an unknown key."
    )
