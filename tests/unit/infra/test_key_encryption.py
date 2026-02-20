"""Unit tests for pulldb.infra.key_encryption.

Covers:
- get_encryption_key(): presence, absence, invalid value
- get_old_encryption_key(): same contract as primary
- is_encrypted(): prefix detection
- encrypt_secret(): with/without key, output format
- decrypt_secret(): passthrough for plaintext, correct decryption, error cases
- decrypt_secret(): fallback to old key during rotation
- Round-trip invariant
- Nonce randomness (different ciphertext for same input)
- reencrypt_if_needed(): no-op for primary-key rows, re-encrypts old-key rows
- is_rotation_in_progress(): True/False based on env vars
"""

from __future__ import annotations

import base64
import os
from unittest.mock import patch

import pytest

# Module under test
from pulldb.infra.key_encryption import (
    _ENV_VAR,
    _OLD_ENV_VAR,
    _PREFIX,
    decrypt_secret,
    encrypt_secret,
    get_encryption_key,
    get_old_encryption_key,
    is_encrypted,
    is_rotation_in_progress,
    reencrypt_if_needed,
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


# ---------------------------------------------------------------------------
# Key rotation helpers
# ---------------------------------------------------------------------------


class TestGetOldEncryptionKey:
    def test_returns_none_when_not_set(self, monkeypatch):
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        assert get_old_encryption_key() is None

    def test_returns_32_bytes_when_set(self, monkeypatch):
        import secrets as _s
        key_b64 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        monkeypatch.setenv(_OLD_ENV_VAR, key_b64)
        key = get_old_encryption_key()
        assert key is not None
        assert len(key) == 32

    def test_raises_value_error_on_wrong_length(self, monkeypatch):
        short_b64 = base64.urlsafe_b64encode(b"\x00" * 16).decode()
        monkeypatch.setenv(_OLD_ENV_VAR, short_b64)
        with pytest.raises(ValueError, match="32 bytes"):
            get_old_encryption_key()

    def test_raises_value_error_on_invalid_base64(self, monkeypatch):
        monkeypatch.setenv(_OLD_ENV_VAR, "not-valid!!!")
        with pytest.raises(ValueError):
            get_old_encryption_key()


class TestIsRotationInProgress:
    def test_false_with_no_keys(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        assert is_rotation_in_progress() is False

    def test_false_with_only_primary(self, monkeypatch):
        import secrets as _s
        key_b64 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        monkeypatch.setenv(_ENV_VAR, key_b64)
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        assert is_rotation_in_progress() is False

    def test_false_with_only_old(self, monkeypatch):
        import secrets as _s
        key_b64 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        monkeypatch.delenv(_ENV_VAR, raising=False)
        monkeypatch.setenv(_OLD_ENV_VAR, key_b64)
        assert is_rotation_in_progress() is False

    def test_true_with_both_set(self, monkeypatch):
        import secrets as _s
        key1 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        key2 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        monkeypatch.setenv(_ENV_VAR, key1)
        monkeypatch.setenv(_OLD_ENV_VAR, key2)
        assert is_rotation_in_progress() is True


class TestDecryptSecretRotation:
    """Tests for the old-key fallback during key rotation."""

    def test_falls_back_to_old_key(self, monkeypatch):
        """Value encrypted with old key is decryptable after key rotation."""
        import secrets as _s
        old_key = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        new_key = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()

        # Encrypt with old key (simulates pre-rotation DB value)
        monkeypatch.setenv(_ENV_VAR, old_key)
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        encrypted = encrypt_secret("rotation_test_value")

        # Now rotate: new key is primary, old key in fallback slot
        monkeypatch.setenv(_ENV_VAR, new_key)
        monkeypatch.setenv(_OLD_ENV_VAR, old_key)

        result = decrypt_secret(encrypted)
        assert result == "rotation_test_value"

    def test_primary_key_used_first(self, monkeypatch):
        """Value encrypted with new (primary) key is decrypted without touching old."""
        import secrets as _s
        old_key = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        new_key = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()

        # Encrypt with new primary key
        monkeypatch.setenv(_ENV_VAR, new_key)
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        encrypted = encrypt_secret("fresh_value")

        # Both keys present during rotation check
        monkeypatch.setenv(_OLD_ENV_VAR, old_key)
        assert decrypt_secret(encrypted) == "fresh_value"

    def test_raises_if_both_keys_fail(self, monkeypatch):
        """Neither primary nor old key can decrypt → ValueError."""
        import secrets as _s
        key_enc = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        key_a = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        key_b = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()

        # Encrypt with a third unrelated key
        monkeypatch.setenv(_ENV_VAR, key_enc)
        encrypted = encrypt_secret("secret")

        # Set primary + old to two different, non-matching keys
        monkeypatch.setenv(_ENV_VAR, key_a)
        monkeypatch.setenv(_OLD_ENV_VAR, key_b)
        with pytest.raises(ValueError, match="decryption failed"):
            decrypt_secret(encrypted)


class TestReencryptIfNeeded:
    """Tests for reencrypt_if_needed() used during rotation migration."""

    def test_plaintext_passthrough(self, monkeypatch):
        """Plaintext value is returned unchanged with changed=False."""
        import secrets as _s
        key1 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        key2 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        monkeypatch.setenv(_ENV_VAR, key1)
        monkeypatch.setenv(_OLD_ENV_VAR, key2)
        val, changed = reencrypt_if_needed("just_plaintext")
        assert val == "just_plaintext"
        assert changed is False

    def test_already_primary_key_no_change(self, monkeypatch):
        """Row encrypted with primary key is returned as-is (changed=False)."""
        import secrets as _s
        primary = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        old = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()

        monkeypatch.setenv(_ENV_VAR, primary)
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        encrypted = encrypt_secret("already_current")

        # Set old key to trigger rotation path
        monkeypatch.setenv(_OLD_ENV_VAR, old)
        val, changed = reencrypt_if_needed(encrypted)
        assert val == encrypted
        assert changed is False

    def test_reencrypts_old_key_row(self, monkeypatch):
        """Row encrypted with old key is re-encrypted with primary (changed=True)."""
        import secrets as _s
        old = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        new = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()

        # Create value encrypted with old key
        monkeypatch.setenv(_ENV_VAR, old)
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        old_encrypted = encrypt_secret("secret_needing_rotation")

        # Rotate: new is primary, old is fallback
        monkeypatch.setenv(_ENV_VAR, new)
        monkeypatch.setenv(_OLD_ENV_VAR, old)

        new_encrypted, changed = reencrypt_if_needed(old_encrypted)
        assert changed is True
        assert new_encrypted != old_encrypted
        assert is_encrypted(new_encrypted)

        # Verify the new value decrypts correctly with primary key only
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        assert decrypt_secret(new_encrypted) == "secret_needing_rotation"

    def test_no_old_key_no_rotation(self, monkeypatch):
        """When no old key is set, always returns as-is regardless of encryption state."""
        import secrets as _s
        primary = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        monkeypatch.setenv(_ENV_VAR, primary)
        monkeypatch.delenv(_OLD_ENV_VAR, raising=False)
        encrypted = encrypt_secret("value")
        val, changed = reencrypt_if_needed(encrypted)
        assert val == encrypted
        assert changed is False

    def test_raises_if_neither_key_matches(self, monkeypatch):
        """Neither primary nor old key matches → ValueError raised."""
        import secrets as _s
        key_enc = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        key_a = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        key_b = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()

        # Encrypt with unrelated key
        monkeypatch.setenv(_ENV_VAR, key_enc)
        encrypted = encrypt_secret("value")

        monkeypatch.setenv(_ENV_VAR, key_a)
        monkeypatch.setenv(_OLD_ENV_VAR, key_b)
        with pytest.raises(ValueError, match="neither key"):
            reencrypt_if_needed(encrypted)

    def test_raises_runtime_error_without_primary_key(self, monkeypatch):
        """Calling reencrypt_if_needed without a primary key raises RuntimeError."""
        import secrets as _s
        key_b64 = base64.urlsafe_b64encode(_s.token_bytes(32)).decode()
        # Encrypt with a key, then remove it
        monkeypatch.setenv(_ENV_VAR, key_b64)
        encrypted = encrypt_secret("value")

        monkeypatch.delenv(_ENV_VAR, raising=False)
        monkeypatch.setenv(_OLD_ENV_VAR, key_b64)
        with pytest.raises(RuntimeError, match=_ENV_VAR):
            reencrypt_if_needed(encrypted)
