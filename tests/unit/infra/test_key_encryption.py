"""Unit tests for pulldb.infra.key_encryption.

Covers:
- get_encryption_key(): presence, absence, invalid value
- is_encrypted(): prefix detection
- encrypt_secret(): with/without key, output format
- decrypt_secret(): passthrough for plaintext, correct decryption, error cases
- Round-trip invariant
- Nonce randomness (different ciphertext for same input)
"""

from __future__ import annotations

import base64
import os
from unittest.mock import patch

import pytest

# Module under test
from pulldb.infra.key_encryption import (
    _ENV_VAR,
    _PREFIX,
    decrypt_secret,
    encrypt_secret,
    get_encryption_key,
    is_encrypted,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_key_b64() -> str:
    """Return a valid base64-encoded 32-byte key."""
    import secrets as _s
    return base64.urlsafe_b64encode(_s.token_bytes(32)).decode()


def _env_with_key(key_b64: str) -> dict[str, str]:
    return {_ENV_VAR: key_b64}


# ---------------------------------------------------------------------------
# get_encryption_key
# ---------------------------------------------------------------------------


class TestGetEncryptionKey:
    def test_returns_none_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure var is absent
            env = {k: v for k, v in os.environ.items() if k != _ENV_VAR}
            with patch.dict(os.environ, env, clear=True):
                result = get_encryption_key()
        assert result is None

    def test_returns_32_bytes_when_set(self):
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            result = get_encryption_key()
        assert result is not None
        assert len(result) == 32
        assert isinstance(result, bytes)

    def test_raises_when_key_wrong_length_short(self):
        # 16 bytes encoded instead of 32
        import secrets as _s
        short_b64 = base64.urlsafe_b64encode(_s.token_bytes(16)).decode()
        with patch.dict(os.environ, {_ENV_VAR: short_b64}):
            with pytest.raises(ValueError, match="32 bytes"):
                get_encryption_key()

    def test_raises_when_key_wrong_length_long(self):
        import secrets as _s
        long_b64 = base64.urlsafe_b64encode(_s.token_bytes(48)).decode()
        with patch.dict(os.environ, {_ENV_VAR: long_b64}):
            with pytest.raises(ValueError, match="32 bytes"):
                get_encryption_key()


# ---------------------------------------------------------------------------
# is_encrypted
# ---------------------------------------------------------------------------


class TestIsEncrypted:
    def test_plaintext_returns_false(self):
        assert is_encrypted("somerandomplaintextsecret") is False

    def test_empty_string_returns_false(self):
        assert is_encrypted("") is False

    def test_encrypted_value_returns_true(self):
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            encrypted = encrypt_secret("mysecret")
        assert is_encrypted(encrypted) is True

    def test_prefix_only_returns_true(self):
        # Technically malformed but is_encrypted only checks the prefix
        assert is_encrypted(f"{_PREFIX}garbage") is True


# ---------------------------------------------------------------------------
# encrypt_secret
# ---------------------------------------------------------------------------


class TestEncryptSecret:
    def test_without_key_returns_plaintext(self):
        plaintext = "super_secret_value"
        env = {k: v for k, v in os.environ.items() if k != _ENV_VAR}
        with patch.dict(os.environ, env, clear=True):
            result = encrypt_secret(plaintext)
        assert result == plaintext

    def test_with_key_returns_encrypted_prefix(self):
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            result = encrypt_secret("mysecret")
        assert result.startswith(_PREFIX)

    def test_encrypted_value_is_valid_base64(self):
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            encrypted = encrypt_secret("mysecret")
        blob_b64 = encrypted[len(_PREFIX):]
        # Should not raise
        decoded = base64.urlsafe_b64decode(blob_b64 + "==")
        # 12-byte nonce + at least 1 byte ciphertext + 16-byte tag = 29 bytes min
        assert len(decoded) >= 29

    def test_different_nonce_each_call(self):
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            enc1 = encrypt_secret("same_plaintext")
            enc2 = encrypt_secret("same_plaintext")
        assert enc1 != enc2, "Each encryption should use a fresh nonce"

    def test_empty_string_encrypts(self):
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            result = encrypt_secret("")
        assert result.startswith(_PREFIX)


# ---------------------------------------------------------------------------
# decrypt_secret
# ---------------------------------------------------------------------------


class TestDecryptSecret:
    def test_plaintext_passthrough(self):
        """Values without prefix come back unchanged (migration safety)."""
        plaintext = "raw_plaintext_secret"
        assert decrypt_secret(plaintext) == plaintext

    def test_round_trip(self):
        """encrypt then decrypt returns the original value."""
        key_b64 = _make_key_b64()
        original = "super_secret_value_abc123"
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            encrypted = encrypt_secret(original)
            recovered = decrypt_secret(encrypted)
        assert recovered == original

    def test_round_trip_unicode(self):
        """Unicode secrets survive the round-trip."""
        key_b64 = _make_key_b64()
        original = "секрет_パスワード_🔑"
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            encrypted = encrypt_secret(original)
            recovered = decrypt_secret(encrypted)
        assert recovered == original

    def test_raises_runtime_error_when_key_absent_but_encrypted(self):
        """Encrypted value, no key configured → RuntimeError not silent failure."""
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            encrypted = encrypt_secret("secret")

        # Now remove the key and try to decrypt
        env = {k: v for k, v in os.environ.items() if k != _ENV_VAR}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match=_ENV_VAR):
                decrypt_secret(encrypted)

    def test_raises_value_error_on_corrupted_blob(self):
        """Blob that can't be decoded raises ValueError."""
        malformed = f"{_PREFIX}!!NOT_BASE64!!"
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            with pytest.raises(ValueError):
                decrypt_secret(malformed)

    def test_raises_value_error_on_too_short_blob(self):
        """Blob that is too short to contain nonce+tag raises ValueError."""
        # Encode only 4 bytes (nonce is 12 bytes minimum)
        short_blob = base64.urlsafe_b64encode(b"\x00" * 4).decode()
        malformed = f"{_PREFIX}{short_blob}"
        key_b64 = _make_key_b64()
        with patch.dict(os.environ, {_ENV_VAR: key_b64}):
            with pytest.raises(ValueError, match="too short"):
                decrypt_secret(malformed)

    def test_raises_value_error_on_wrong_key(self):
        """Decrypting with a different key raises ValueError (GCM tag mismatch)."""
        import secrets as _s
        key1_b64 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        key2_b64 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()

        with patch.dict(os.environ, {_ENV_VAR: key1_b64}):
            encrypted = encrypt_secret("original_secret")

        with patch.dict(os.environ, {_ENV_VAR: key2_b64}):
            with pytest.raises(ValueError, match="decryption failed"):
                decrypt_secret(encrypted)
