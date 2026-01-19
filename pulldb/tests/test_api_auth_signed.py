"""Tests for HMAC signature verification in pulldb.api.auth."""

from __future__ import annotations

"""HCA Layer: tests."""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from pulldb.api.auth import (
    SIGNATURE_MAX_AGE_SECONDS,
    SIGNATURE_TIMESTAMP_FORMAT,
    get_api_secret,
    get_user_for_api_key,
    validate_signature_timestamp,
    verify_signature,
)


class TestGetApiSecret:
    """Tests for get_api_secret function."""

    def test_returns_secret_for_matching_key(self) -> None:
        """Should return secret when key matches."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "mykey", "PULLDB_API_SECRET": "mysecret"},
            clear=True,
        ):
            result = get_api_secret("mykey")
            assert result == "mysecret"

    def test_returns_none_for_wrong_key(self) -> None:
        """Should return None for non-matching key."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "mykey", "PULLDB_API_SECRET": "mysecret"},
            clear=True,
        ):
            result = get_api_secret("wrongkey")
            assert result is None

    def test_returns_none_when_not_configured(self) -> None:
        """Should return None when no API key configured."""
        with mock.patch.dict(os.environ, {}, clear=True):
            result = get_api_secret("anykey")
            assert result is None


class TestGetUserForApiKey:
    """Tests for get_user_for_api_key function."""

    def test_returns_configured_user(self) -> None:
        """Should return configured user for matching key."""
        with mock.patch.dict(
            os.environ,
            {
                "PULLDB_API_KEY": "mykey",
                "PULLDB_API_KEY_USER": "apiuser",
            },
            clear=True,
        ):
            result = get_user_for_api_key("mykey")
            assert result == "apiuser"

    def test_returns_default_user_when_not_configured(self) -> None:
        """Should return 'api-user' if user not configured but key matches."""
        with mock.patch.dict(
            os.environ, {"PULLDB_API_KEY": "mykey"}, clear=True
        ):
            result = get_user_for_api_key("mykey")
            assert result == "api-user"

    def test_returns_none_for_wrong_key(self) -> None:
        """Should return None for non-matching key."""
        with mock.patch.dict(os.environ, {"PULLDB_API_KEY": "mykey"}, clear=True):
            result = get_user_for_api_key("wrongkey")
            assert result is None


class TestValidateSignatureTimestamp:
    """Tests for validate_signature_timestamp function."""

    def test_valid_recent_timestamp(self) -> None:
        """Should accept recent timestamp."""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime(SIGNATURE_TIMESTAMP_FORMAT)
        assert validate_signature_timestamp(timestamp) is True

    def test_valid_timestamp_within_window(self) -> None:
        """Should accept timestamp within acceptable window."""
        # 2 minutes ago (within 5-minute window)
        past = datetime.now(timezone.utc) - timedelta(seconds=120)
        timestamp = past.strftime(SIGNATURE_TIMESTAMP_FORMAT)
        assert validate_signature_timestamp(timestamp) is True

    def test_invalid_old_timestamp(self) -> None:
        """Should reject timestamp older than max age."""
        # 10 minutes ago (outside 5-minute window)
        old = datetime.now(timezone.utc) - timedelta(seconds=SIGNATURE_MAX_AGE_SECONDS + 60)
        timestamp = old.strftime(SIGNATURE_TIMESTAMP_FORMAT)
        assert validate_signature_timestamp(timestamp) is False

    def test_invalid_future_timestamp(self) -> None:
        """Should reject timestamp too far in the future."""
        # 10 minutes in the future
        future = datetime.now(timezone.utc) + timedelta(seconds=SIGNATURE_MAX_AGE_SECONDS + 60)
        timestamp = future.strftime(SIGNATURE_TIMESTAMP_FORMAT)
        assert validate_signature_timestamp(timestamp) is False

    def test_invalid_format(self) -> None:
        """Should reject invalid timestamp format."""
        assert validate_signature_timestamp("not-a-timestamp") is False
        assert validate_signature_timestamp("2026-01-03") is False
        assert validate_signature_timestamp("") is False


class TestVerifySignature:
    """Tests for verify_signature function."""

    def _compute_expected_signature(
        self, method: str, path: str, body: bytes | None, timestamp: str, secret: str
    ) -> str:
        """Helper to compute expected signature using same algorithm."""
        if body:
            body_hash = hashlib.sha256(body).hexdigest()
        else:
            body_hash = hashlib.sha256(b"").hexdigest()

        string_to_sign = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}"
        return hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def test_valid_signature(self) -> None:
        """Should accept valid signature."""
        method = "POST"
        path = "/api/jobs"
        body = b'{"database":"test_db"}'
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        signature = self._compute_expected_signature(method, path, body, timestamp, secret)
        assert verify_signature(method, path, body, timestamp, signature, secret) is True

    def test_valid_signature_no_body(self) -> None:
        """Should accept valid signature for GET request (no body)."""
        method = "GET"
        path = "/api/status"
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        signature = self._compute_expected_signature(method, path, None, timestamp, secret)
        assert verify_signature(method, path, None, timestamp, signature, secret) is True

    def test_invalid_signature_wrong_secret(self) -> None:
        """Should reject signature computed with different secret."""
        method = "POST"
        path = "/api/jobs"
        body = b'{"database":"test"}'
        timestamp = "2026-01-03T15:42:00Z"

        # Compute with one secret, verify with another
        signature = self._compute_expected_signature(method, path, body, timestamp, "secret1")
        assert verify_signature(method, path, body, timestamp, signature, "secret2") is False

    def test_invalid_signature_tampered_body(self) -> None:
        """Should reject signature if body was tampered."""
        method = "POST"
        path = "/api/jobs"
        original_body = b'{"database":"test"}'
        tampered_body = b'{"database":"production"}'
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        # Sign original, verify with tampered
        signature = self._compute_expected_signature(method, path, original_body, timestamp, secret)
        assert verify_signature(method, path, tampered_body, timestamp, signature, secret) is False

    def test_invalid_signature_tampered_path(self) -> None:
        """Should reject signature if path was tampered."""
        method = "POST"
        body = b'{"database":"test"}'
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        # Sign one path, verify with another
        signature = self._compute_expected_signature(method, "/api/jobs", body, timestamp, secret)
        assert verify_signature(method, "/api/admin/delete", body, timestamp, signature, secret) is False

    def test_invalid_signature_tampered_method(self) -> None:
        """Should reject signature if method was tampered."""
        path = "/api/jobs"
        body = b'{"database":"test"}'
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        # Sign POST, verify with DELETE
        signature = self._compute_expected_signature("POST", path, body, timestamp, secret)
        assert verify_signature("DELETE", path, body, timestamp, signature, secret) is False

    def test_case_insensitive_method(self) -> None:
        """Method comparison should be case-insensitive."""
        path = "/api/jobs"
        body = b'{"database":"test"}'
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        # Sign with lowercase, verify with uppercase
        signature = self._compute_expected_signature("post", path, body, timestamp, secret)
        assert verify_signature("POST", path, body, timestamp, signature, secret) is True
