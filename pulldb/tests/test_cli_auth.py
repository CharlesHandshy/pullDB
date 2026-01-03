"""Tests for pulldb.cli.auth module."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from unittest import mock

import pytest

from pulldb.cli.auth import (
    KEY_ID_DISPLAY_LENGTH,
    SIGNATURE_TIMESTAMP_FORMAT,
    compute_request_signature,
    get_api_credentials,
    get_auth_headers,
    get_calling_username,
    get_current_username,
    get_signature_timestamp,
    has_api_credentials,
)


class TestGetCallingUsername:
    """Tests for get_calling_username function."""

    def test_returns_sudo_user_when_set(self) -> None:
        """Should prefer SUDO_USER environment variable."""
        with mock.patch.dict(os.environ, {"SUDO_USER": "testuser"}, clear=False):
            result = get_calling_username()
            assert result == "testuser"

    def test_ignores_root_sudo_user(self) -> None:
        """Should not return 'root' from SUDO_USER."""
        with mock.patch.dict(
            os.environ, {"SUDO_USER": "root", "USER": "fallback"}, clear=False
        ):
            result = get_calling_username()
            # Should fall through to USER or who am i
            assert result != "root"

    def test_returns_user_when_no_sudo_user(self) -> None:
        """Should fall back to USER environment variable."""
        with mock.patch.dict(
            os.environ, {"USER": "envuser"}, clear=False
        ):
            # Remove SUDO_USER if present
            env = os.environ.copy()
            env.pop("SUDO_USER", None)
            env["USER"] = "envuser"
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("subprocess.run") as mock_run:
                    # Make who am i fail
                    mock_run.return_value.returncode = 1
                    mock_run.return_value.stdout = ""
                    result = get_calling_username()
                    assert result == "envuser"


class TestGetApiCredentials:
    """Tests for get_api_credentials function."""

    def test_raises_when_not_configured(self) -> None:
        """Should raise RuntimeError when no API key configured."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="API credentials not configured"):
                get_api_credentials()

    def test_returns_credentials_when_configured(self) -> None:
        """Should return tuple of (key, secret) when configured."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "mykey", "PULLDB_API_SECRET": "mysecret"},
            clear=True,
        ):
            result = get_api_credentials()
            assert result == ("mykey", "mysecret")

    def test_raises_when_only_key(self) -> None:
        """Should raise when only key is set (no secret)."""
        with mock.patch.dict(os.environ, {"PULLDB_API_KEY": "mykey"}, clear=True):
            with pytest.raises(RuntimeError, match="API credentials not configured"):
                get_api_credentials()


class TestHasApiCredentials:
    """Tests for has_api_credentials function."""

    def test_returns_false_when_not_configured(self) -> None:
        """Should return False when no API key configured."""
        with mock.patch.dict(os.environ, {}, clear=True):
            assert has_api_credentials() is False

    def test_returns_true_when_configured(self) -> None:
        """Should return True when both key and secret are set."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "mykey", "PULLDB_API_SECRET": "mysecret"},
            clear=True,
        ):
            assert has_api_credentials() is True

    def test_returns_false_when_only_key(self) -> None:
        """Should return False when only key is set."""
        with mock.patch.dict(os.environ, {"PULLDB_API_KEY": "mykey"}, clear=True):
            assert has_api_credentials() is False


class TestGetAuthHeaders:
    """Tests for get_auth_headers function (signed-only mode)."""

    def test_returns_signature_headers_when_configured(self) -> None:
        """Should return HMAC signature headers."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "testkey", "PULLDB_API_SECRET": "testsecret"},
            clear=True,
        ):
            result = get_auth_headers(method="POST", path="/api/jobs", body='{"db":"test"}')

            assert "X-API-Key" in result
            assert result["X-API-Key"] == "testkey"
            assert "X-Timestamp" in result
            assert "X-Signature" in result
            # Signature should be 64 hex chars
            assert len(result["X-Signature"]) == 64

    def test_raises_when_not_configured(self) -> None:
        """Should raise RuntimeError when credentials not configured."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="API credentials not configured"):
                get_auth_headers()

    def test_get_request_no_body(self) -> None:
        """Should work for GET requests with no body."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "testkey", "PULLDB_API_SECRET": "testsecret"},
            clear=True,
        ):
            result = get_auth_headers(method="GET", path="/api/status")
            assert "X-API-Key" in result
            assert "X-Timestamp" in result
            assert "X-Signature" in result


class TestGetCurrentUsername:
    """Tests for get_current_username function."""

    def test_returns_key_display_when_configured(self) -> None:
        """Should return formatted key ID when credentials configured."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "shortkey", "PULLDB_API_SECRET": "secret"},
            clear=True,
        ):
            result = get_current_username()
            assert "[API Key: shortkey]" in result

    def test_truncates_long_keys(self) -> None:
        """Should truncate long key IDs for display."""
        long_key = "a" * 50  # Longer than KEY_ID_DISPLAY_LENGTH
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": long_key, "PULLDB_API_SECRET": "secret"},
            clear=True,
        ):
            result = get_current_username()
            assert f"[API Key: {'a' * KEY_ID_DISPLAY_LENGTH}...]" in result

    def test_returns_not_configured_when_missing(self) -> None:
        """Should indicate when credentials are not configured."""
        with mock.patch.dict(os.environ, {}, clear=True):
            result = get_current_username()
            assert "No API credentials" in result


class TestSignedAuthentication:
    """Tests for HMAC signature functions."""

    def test_get_signature_timestamp_format(self) -> None:
        """Should return timestamp in correct ISO 8601 format."""
        timestamp = get_signature_timestamp()
        # Should parse without error
        parsed = datetime.strptime(timestamp, SIGNATURE_TIMESTAMP_FORMAT)
        assert parsed is not None
        # Should end with Z (UTC)
        assert timestamp.endswith("Z")

    def test_compute_request_signature_basic(self) -> None:
        """Should compute consistent HMAC-SHA256 signature."""
        method = "POST"
        path = "/api/jobs"
        body = '{"database":"test_db"}'
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        sig1 = compute_request_signature(method, path, body, timestamp, secret)
        sig2 = compute_request_signature(method, path, body, timestamp, secret)

        # Should be consistent
        assert sig1 == sig2
        # Should be hex string
        assert all(c in "0123456789abcdef" for c in sig1)
        # Should be 64 chars (SHA256 hex)
        assert len(sig1) == 64

    def test_compute_request_signature_different_body_different_sig(self) -> None:
        """Different body should produce different signature."""
        method = "POST"
        path = "/api/jobs"
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        sig1 = compute_request_signature(method, path, '{"a":1}', timestamp, secret)
        sig2 = compute_request_signature(method, path, '{"a":2}', timestamp, secret)

        assert sig1 != sig2

    def test_compute_request_signature_different_secret_different_sig(self) -> None:
        """Different secret should produce different signature."""
        method = "POST"
        path = "/api/jobs"
        body = '{"database":"test"}'
        timestamp = "2026-01-03T15:42:00Z"

        sig1 = compute_request_signature(method, path, body, timestamp, "secret1")
        sig2 = compute_request_signature(method, path, body, timestamp, "secret2")

        assert sig1 != sig2

    def test_compute_request_signature_none_body(self) -> None:
        """Should handle None body (GET requests)."""
        method = "GET"
        path = "/api/status"
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        sig = compute_request_signature(method, path, None, timestamp, secret)
        assert len(sig) == 64

    def test_compute_request_signature_bytes_body(self) -> None:
        """Should handle bytes body."""
        method = "POST"
        path = "/api/jobs"
        body = b'{"database":"test"}'
        timestamp = "2026-01-03T15:42:00Z"
        secret = "mysecret123"

        sig = compute_request_signature(method, path, body, timestamp, secret)
        assert len(sig) == 64

    def test_signature_headers_complete(self) -> None:
        """Should return all required signature headers."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "testkey", "PULLDB_API_SECRET": "testsecret"},
            clear=True,
        ):
            result = get_auth_headers(method="POST", path="/api/jobs", body='{"db":"test"}')

            assert "X-API-Key" in result
            assert result["X-API-Key"] == "testkey"
            assert "X-Timestamp" in result
            assert "X-Signature" in result
            # Signature should be 64 hex chars
            assert len(result["X-Signature"]) == 64