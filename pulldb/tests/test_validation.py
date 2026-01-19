"""Tests for pulldb.domain.validation module."""

from __future__ import annotations

"""HCA Layer: tests."""

import pytest

from pulldb.domain.validation import (
    ValidationError,
    is_valid_uuid,
    is_valid_uuid_prefix,
    validate_uuid,
)


class TestIsValidUUID:
    """Tests for is_valid_uuid function."""

    def test_valid_lowercase_uuid(self) -> None:
        """Valid lowercase UUID returns True."""
        assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_uppercase_uuid(self) -> None:
        """Valid uppercase UUID returns True (case insensitive)."""
        assert is_valid_uuid("550E8400-E29B-41D4-A716-446655440000") is True

    def test_valid_mixed_case_uuid(self) -> None:
        """Valid mixed case UUID returns True."""
        assert is_valid_uuid("550e8400-E29B-41d4-A716-446655440000") is True

    def test_sequential_uuid(self) -> None:
        """Sequential test UUIDs are valid."""
        assert is_valid_uuid("00000000-0000-0000-0000-000000000001") is True
        assert is_valid_uuid("00000000-0000-0000-0000-000000000099") is True

    def test_invalid_too_short(self) -> None:
        """Too short string returns False."""
        assert is_valid_uuid("550e8400") is False

    def test_invalid_no_dashes(self) -> None:
        """UUID without dashes returns False."""
        assert is_valid_uuid("550e8400e29b41d4a716446655440000") is False

    def test_invalid_wrong_format(self) -> None:
        """Wrong dash placement returns False."""
        assert is_valid_uuid("550e-8400-e29b-41d4-a716446655440000") is False

    def test_invalid_non_hex(self) -> None:
        """Non-hex characters return False."""
        assert is_valid_uuid("550e8400-e29b-41d4-a716-44665544GGGG") is False

    def test_empty_string(self) -> None:
        """Empty string returns False."""
        assert is_valid_uuid("") is False

    def test_none_returns_false(self) -> None:
        """None returns False (not error)."""
        assert is_valid_uuid(None) is False  # type: ignore[arg-type]

    def test_non_string_returns_false(self) -> None:
        """Non-string returns False (not error)."""
        assert is_valid_uuid(12345) is False  # type: ignore[arg-type]


class TestValidateUUID:
    """Tests for validate_uuid function."""

    def test_valid_uuid_returns_lowercase(self) -> None:
        """Valid UUID is returned lowercase normalized."""
        result = validate_uuid("550E8400-E29B-41D4-A716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_already_lowercase_unchanged(self) -> None:
        """Already lowercase UUID returned as-is."""
        result = validate_uuid("550e8400-e29b-41d4-a716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_invalid_raises_validation_error(self) -> None:
        """Invalid UUID raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid("invalid")
        assert exc_info.value.field == "id"
        assert "Invalid UUID format" in exc_info.value.message

    def test_custom_field_name_in_error(self) -> None:
        """Custom field name appears in error."""
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid("invalid", "job_id")
        assert exc_info.value.field == "job_id"

    def test_validation_error_inherits_valueerror(self) -> None:
        """ValidationError inherits from ValueError for compatibility."""
        with pytest.raises(ValueError):
            validate_uuid("invalid")


class TestIsValidUUIDPrefix:
    """Tests for is_valid_uuid_prefix function."""

    def test_valid_8_char_prefix(self) -> None:
        """8 character hex prefix is valid."""
        assert is_valid_uuid_prefix("550e8400") is True

    def test_valid_12_char_prefix(self) -> None:
        """12 character prefix (first segment + dash) is valid."""
        assert is_valid_uuid_prefix("550e8400-e29b") is True

    def test_valid_full_uuid_as_prefix(self) -> None:
        """Full UUID is also valid as prefix."""
        assert is_valid_uuid_prefix("550e8400-e29b-41d4-a716-446655440000") is True

    def test_too_short_default_min(self) -> None:
        """Less than 8 characters returns False by default."""
        assert is_valid_uuid_prefix("550e840") is False

    def test_custom_min_length(self) -> None:
        """Custom minimum length is respected."""
        assert is_valid_uuid_prefix("550e", min_length=4) is True
        assert is_valid_uuid_prefix("550", min_length=4) is False

    def test_invalid_non_hex_chars(self) -> None:
        """Non-hex characters return False."""
        assert is_valid_uuid_prefix("gggggggg") is False
        assert is_valid_uuid_prefix("550e840g") is False

    def test_empty_string(self) -> None:
        """Empty string returns False."""
        assert is_valid_uuid_prefix("") is False

    def test_none_returns_false(self) -> None:
        """None returns False (not error)."""
        assert is_valid_uuid_prefix(None) is False  # type: ignore[arg-type]
