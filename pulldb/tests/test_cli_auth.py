"""Tests for pulldb.cli.auth module."""

from __future__ import annotations

import base64
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
    get_api_key_credentials,
    get_auth_headers,
    get_auth_method,
    get_calling_username,
    get_current_username,
    get_signature_timestamp,
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


class TestGetAuthMethod:
    """Tests for get_auth_method function."""

    def test_default_is_trusted(self) -> None:
        """Should default to trusted mode."""
        with mock.patch.dict(os.environ, {}, clear=True):
            result = get_auth_method()
            assert result == "trusted"

    def test_explicit_apikey_method(self) -> None:
        """Should respect PULLDB_AUTH_METHOD=apikey."""
        with mock.patch.dict(os.environ, {"PULLDB_AUTH_METHOD": "apikey"}, clear=True):
            result = get_auth_method()
            assert result == "apikey"

    def test_auto_detect_signed_from_credentials(self) -> None:
        """Should auto-detect signed mode when credentials are set (most secure)."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "key123", "PULLDB_API_SECRET": "secret456"},
            clear=True,
        ):
            result = get_auth_method()
            assert result == "signed"

    def test_partial_credentials_not_detected(self) -> None:
        """Should not detect apikey mode with only key (no secret)."""
        with mock.patch.dict(os.environ, {"PULLDB_API_KEY": "key123"}, clear=True):
            result = get_auth_method()
            assert result == "trusted"


class TestGetApiKeyCredentials:
    """Tests for get_api_key_credentials function."""

    def test_returns_none_when_not_configured(self) -> None:
        """Should return None when no API key configured."""
        with mock.patch.dict(os.environ, {}, clear=True):
            result = get_api_key_credentials()
            assert result is None

    def test_returns_credentials_when_configured(self) -> None:
        """Should return tuple of (key, secret) when configured."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "mykey", "PULLDB_API_SECRET": "mysecret"},
            clear=True,
        ):
            result = get_api_key_credentials()
            assert result == ("mykey", "mysecret")

    def test_returns_none_when_only_key(self) -> None:
        """Should return None when only key is set (no secret)."""
        with mock.patch.dict(os.environ, {"PULLDB_API_KEY": "mykey"}, clear=True):
            result = get_api_key_credentials()
            assert result is None


class TestGetAuthHeaders:
    """Tests for get_auth_headers function."""

    def test_trusted_mode_returns_trusted_user_header(self) -> None:
        """Should return X-Trusted-User header in trusted mode."""
        with mock.patch.dict(os.environ, {"SUDO_USER": "testuser"}, clear=False):
            with mock.patch(
                "pulldb.cli.auth.get_auth_method", return_value="trusted"
            ):
                result = get_auth_headers()
                assert "X-Trusted-User" in result
                assert result["X-Trusted-User"] == "testuser"

    def test_apikey_mode_returns_authorization_header(self) -> None:
        """Should return Authorization: Basic header in apikey mode."""
        with mock.patch.dict(
            os.environ,
            {
                "PULLDB_AUTH_METHOD": "apikey",
                "PULLDB_API_KEY": "testkey",
                "PULLDB_API_SECRET": "testsecret",
            },
            clear=True,
        ):
            result = get_auth_headers()
            assert "Authorization" in result
            assert result["Authorization"].startswith("Basic ")
            # Verify the encoding
            encoded = result["Authorization"].replace("Basic ", "")
            decoded = base64.b64decode(encoded).decode()
            assert decoded == "testkey:testsecret"

    def test_apikey_mode_without_credentials_falls_back_to_trusted(self) -> None:
        """Should fall back to trusted mode if apikey mode but no credentials."""
        with mock.patch.dict(
            os.environ, {"PULLDB_AUTH_METHOD": "apikey", "USER": "fallbackuser"}, clear=True
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 1
                mock_run.return_value.stdout = ""
                result = get_auth_headers()
                # Should fall back to X-Trusted-User
                assert "X-Trusted-User" in result


class TestGetCurrentUsername:
    """Tests for get_current_username function."""

    def test_trusted_mode_returns_system_username(self) -> None:
        """Should return system username in trusted mode."""
        with mock.patch("pulldb.cli.auth.get_auth_method", return_value="trusted"):
            with mock.patch(
                "pulldb.cli.auth.get_calling_username", return_value="systemuser"
            ):
                result = get_current_username()
                assert result == "systemuser"

    def test_apikey_mode_returns_key_display(self) -> None:
        """Should return formatted key ID in apikey mode."""
        with mock.patch("pulldb.cli.auth.get_auth_method", return_value="apikey"):
            with mock.patch(
                "pulldb.cli.auth.get_api_key_credentials",
                return_value=("shortkey", "secret"),
            ):
                result = get_current_username()
                assert "[API Key: shortkey]" in result

    def test_apikey_mode_truncates_long_keys(self) -> None:
        """Should truncate long key IDs for display."""
        long_key = "a" * 50  # Longer than KEY_ID_DISPLAY_LENGTH
        with mock.patch("pulldb.cli.auth.get_auth_method", return_value="apikey"):
            with mock.patch(
                "pulldb.cli.auth.get_api_key_credentials",
                return_value=(long_key, "secret"),
            ):
                result = get_current_username()
                assert f"[API Key: {'a' * KEY_ID_DISPLAY_LENGTH}...]" in result


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

    def test_signed_mode_detected_with_credentials(self) -> None:
        """Should auto-detect signed mode when credentials are set."""
        with mock.patch.dict(
            os.environ,
            {"PULLDB_API_KEY": "key123", "PULLDB_API_SECRET": "secret456"},
            clear=True,
        ):
            result = get_auth_method()
            # With credentials and no explicit method, should default to signed
            assert result == "signed"

    def test_explicit_signed_method(self) -> None:
        """Should respect PULLDB_AUTH_METHOD=signed."""
        with mock.patch.dict(os.environ, {"PULLDB_AUTH_METHOD": "signed"}, clear=True):
            result = get_auth_method()
            assert result == "signed"

    def test_signed_mode_returns_signature_headers(self) -> None:
        """Should return signature headers in signed mode."""
        with mock.patch.dict(
            os.environ,
            {
                "PULLDB_AUTH_METHOD": "signed",
                "PULLDB_API_KEY": "testkey",
                "PULLDB_API_SECRET": "testsecret",
            },
            clear=True,
        ):
            result = get_auth_headers(method="POST", path="/api/jobs", body='{"db":"test"}')

            assert "X-API-Key" in result
            assert result["X-API-Key"] == "testkey"
            assert "X-Timestamp" in result
            assert "X-Signature" in result
            # Signature should be 64 hex chars
            assert len(result["X-Signature"]) == 64

    def test_signed_mode_without_credentials_falls_back(self) -> None:
        """Should fall back to trusted if signed mode but no credentials."""
        with mock.patch.dict(
            os.environ, {"PULLDB_AUTH_METHOD": "signed", "USER": "fallbackuser"}, clear=True
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 1
                mock_run.return_value.stdout = ""
                result = get_auth_headers(method="GET", path="/api/status")
                # Should fall back to X-Trusted-User
                assert "X-Trusted-User" in result