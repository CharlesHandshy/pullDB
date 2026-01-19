"""Tests for password hashing utilities.

Phase 4: Verifies bcrypt hashing and verification works correctly.
"""

from __future__ import annotations

"""HCA Layer: tests."""

import pytest

from pulldb.auth.password import (
    DEFAULT_ROUNDS,
    hash_password,
    needs_rehash,
    verify_password,
)


class TestHashPassword:
    """Tests for hash_password function."""

    def test_hash_password_returns_bcrypt_hash(self) -> None:
        """Hash should be a valid bcrypt hash string."""
        hashed = hash_password("password123")
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60  # bcrypt hashes are 60 chars

    def test_hash_password_includes_rounds(self) -> None:
        """Hash should include the configured rounds."""
        hashed = hash_password("password123")
        parts = hashed.split("$")
        rounds = int(parts[2])
        assert rounds == DEFAULT_ROUNDS

    def test_hash_password_custom_rounds(self) -> None:
        """Custom rounds should be respected."""
        hashed = hash_password("password123", rounds=10)
        parts = hashed.split("$")
        rounds = int(parts[2])
        assert rounds == 10

    def test_hash_password_different_each_time(self) -> None:
        """Each hash should be unique due to random salt."""
        hash1 = hash_password("same_password")
        hash2 = hash_password("same_password")
        assert hash1 != hash2

    def test_hash_password_empty_raises(self) -> None:
        """Empty password should raise ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            hash_password("")

    def test_hash_password_unicode(self) -> None:
        """Unicode passwords should be hashed correctly."""
        # Use emoji as unicode test since cyrillic triggers lint warnings
        password = "password\U0001F512key"  # password🔒key
        hashed = hash_password(password)
        assert hashed.startswith("$2b$")
        assert verify_password(password, hashed)


class TestVerifyPassword:
    """Tests for verify_password function."""

    def test_verify_password_correct(self) -> None:
        """Correct password should return True."""
        hashed = hash_password("correct_password")
        assert verify_password("correct_password", hashed) is True

    def test_verify_password_incorrect(self) -> None:
        """Incorrect password should return False."""
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_empty_plain(self) -> None:
        """Empty plain password should return False."""
        hashed = hash_password("password")
        assert verify_password("", hashed) is False

    def test_verify_password_empty_hash(self) -> None:
        """Empty hash should return False."""
        assert verify_password("password", "") is False

    def test_verify_password_malformed_hash(self) -> None:
        """Malformed hash should return False (not raise)."""
        assert verify_password("password", "not_a_valid_hash") is False

    def test_verify_password_case_sensitive(self) -> None:
        """Password verification should be case-sensitive."""
        hashed = hash_password("Password")
        assert verify_password("Password", hashed) is True
        assert verify_password("password", hashed) is False


class TestNeedsRehash:
    """Tests for needs_rehash function."""

    def test_needs_rehash_same_rounds(self) -> None:
        """Hash with same rounds should not need rehash."""
        hashed = hash_password("password", rounds=12)
        assert needs_rehash(hashed, target_rounds=12) is False

    def test_needs_rehash_lower_rounds(self) -> None:
        """Hash with lower rounds should need rehash."""
        hashed = hash_password("password", rounds=10)
        assert needs_rehash(hashed, target_rounds=12) is True

    def test_needs_rehash_higher_rounds(self) -> None:
        """Hash with higher rounds should not need rehash."""
        hashed = hash_password("password", rounds=14)
        assert needs_rehash(hashed, target_rounds=12) is False

    def test_needs_rehash_empty(self) -> None:
        """Empty hash should not need rehash."""
        assert needs_rehash("", target_rounds=12) is False

    def test_needs_rehash_malformed(self) -> None:
        """Malformed hash should not cause error."""
        assert needs_rehash("not_a_hash", target_rounds=12) is False
