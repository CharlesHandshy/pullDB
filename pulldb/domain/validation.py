"""Validation utilities for pullDB domain entities.

This module provides consistent validation functions for IDs and other
domain-level constraints. All validation follows the FAIL HARD principle -
invalid inputs raise exceptions rather than silently degrading.

HCA Layer: entities (pulldb/domain/)
"""

from __future__ import annotations

import re

# UUID v4 pattern: 8-4-4-4-12 hex characters with dashes
# Case-insensitive to handle both lowercase and uppercase UUIDs
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ValidationError(ValueError):
    """Raised when validation fails.

    Inherits from ValueError for compatibility with existing error handling.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID format.

    Validates UUID format (8-4-4-4-12 hex pattern with dashes).
    Does NOT validate UUID version - accepts any valid format.

    Args:
        value: String to validate.

    Returns:
        True if valid UUID format, False otherwise.

    Examples:
        >>> is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_uuid("not-a-uuid")
        False
        >>> is_valid_uuid("")
        False
    """
    if not value or not isinstance(value, str):
        return False
    return bool(UUID_PATTERN.match(value))


def validate_uuid(value: str, field_name: str = "id") -> str:
    """Validate and return a UUID string.

    FAIL HARD: Raises ValidationError if format is invalid.

    Args:
        value: String to validate.
        field_name: Name of the field for error messages.

    Returns:
        The validated UUID string (lowercase normalized).

    Raises:
        ValidationError: If value is not a valid UUID format.

    Examples:
        >>> validate_uuid("550e8400-e29b-41d4-a716-446655440000")
        '550e8400-e29b-41d4-a716-446655440000'
        >>> validate_uuid("invalid", "job_id")
        ValidationError: job_id: Invalid UUID format 'invalid'
    """
    if not is_valid_uuid(value):
        raise ValidationError(
            field_name,
            f"Invalid UUID format '{value}'. "
            "Expected format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        )
    return value.lower()


def is_valid_uuid_prefix(value: str, min_length: int = 8) -> bool:
    """Check if a string is a valid UUID prefix.

    Used for job ID prefix resolution where users can provide
    shortened IDs (e.g., first 8 characters).

    Args:
        value: String to validate.
        min_length: Minimum required length (default 8).

    Returns:
        True if valid hex prefix with sufficient length.

    Examples:
        >>> is_valid_uuid_prefix("550e8400")
        True
        >>> is_valid_uuid_prefix("550e")
        False  # Too short
        >>> is_valid_uuid_prefix("gggggggg")
        False  # Invalid hex
    """
    if not value or not isinstance(value, str):
        return False
    if len(value) < min_length:
        return False
    # Allow hex characters and dashes only
    return bool(re.match(r"^[0-9a-f-]+$", value, re.IGNORECASE))
