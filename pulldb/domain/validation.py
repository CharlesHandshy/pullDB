"""Validation utilities for pullDB domain entities.

This module provides consistent validation functions for IDs and other
domain-level constraints. All validation follows the FAIL HARD principle -
invalid inputs raise exceptions rather than silently degrading.

HCA Layer: entities (pulldb/domain/)
"""

from __future__ import annotations

import re

# =============================================================================
# Username Validation Constants
# =============================================================================

# Minimum username length for pullDB accounts
MIN_USERNAME_LENGTH = 6

# Hardcoded disallowed usernames - system accounts and reserved names
# These are ALWAYS blocked and cannot be overridden via database configuration.
# Case-insensitive: all comparisons done via lowercase.
DISALLOWED_USERS_HARDCODED: frozenset[str] = frozenset({
    # Core system accounts
    "root",
    "daemon",
    "bin",
    "sys",
    "sync",
    "games",
    "man",
    "lp",
    "mail",
    "news",
    "uucp",
    "proxy",
    "backup",
    "list",
    "irc",
    "gnats",
    "nobody",
    # Systemd accounts
    "systemd-network",
    "systemd-resolve",
    "systemd-timesync",
    "messagebus",
    "syslog",
    # Package/service accounts
    "_apt",
    "tss",
    "uuidd",
    "tcpdump",
    "avahi-autoipd",
    "usbmux",
    "rtkit",
    "dnsmasq",
    "cups-pk-helper",
    "speech-dispatcher",
    "avahi",
    "kernoops",
    "saned",
    "nm-openvpn",
    "hplip",
    "whoopsie",
    "colord",
    "geoclue",
    "pulse",
    "gnome-initial-setup",
    "gdm",
    "sssd",
    # Web/database service accounts
    "www-data",
    "mysql",
    "postgres",
    "redis",
    "nginx",
    "apache",
    "apache2",
    "httpd",
    # Cloud/VM accounts
    "ubuntu",
    "ec2-user",
    "admin",
    # Reserved pullDB names
    "pulldb",
    "pulldb_service",  # Service Bootstrap/CLI Admin Account (sbcacc)
    "system",
    "service",
    "api",
    "web",
    "worker",
    "anonymous",
    "guest",
    "test",
    "demo",
})


def is_username_disallowed_hardcoded(username: str) -> bool:
    """Check if username is in the hardcoded disallowed list.

    Args:
        username: Username to check (case-insensitive).

    Returns:
        True if username is in hardcoded disallowed list.
    """
    return username.lower() in DISALLOWED_USERS_HARDCODED


def validate_username_format(username: str) -> None:
    """Validate username meets basic format requirements.

    FAIL HARD: Raises ValidationError if invalid.

    Checks:
    1. Not empty
    2. At least MIN_USERNAME_LENGTH characters
    3. Contains only allowed characters (a-z, 0-9, _, -)
    4. Starts with a letter

    Args:
        username: Username to validate.

    Raises:
        ValidationError: If format is invalid.
    """
    if not username:
        raise ValidationError("username", "Username cannot be empty")

    username_lower = username.lower()

    if len(username_lower) < MIN_USERNAME_LENGTH:
        raise ValidationError(
            "username",
            f"Username must be at least {MIN_USERNAME_LENGTH} characters long",
        )

    if not re.match(r"^[a-z][a-z0-9_-]*$", username_lower):
        raise ValidationError(
            "username",
            "Username must start with a letter and contain only "
            "lowercase letters, numbers, underscore, and hyphen",
        )


def validate_username_not_disallowed(username: str) -> None:
    """Validate username is not in the hardcoded disallowed list.

    FAIL HARD: Raises ValidationError if disallowed.

    Args:
        username: Username to validate (case-insensitive).

    Raises:
        ValidationError: If username is disallowed.
    """
    if is_username_disallowed_hardcoded(username):
        raise ValidationError(
            "username",
            f"Username '{username}' is not allowed. "
            "This is a reserved system name. Please choose a different username.",
        )


# =============================================================================
# UUID Validation
# =============================================================================

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


# =============================================================================
# Path and Directory Validation
# =============================================================================

import os
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of a validation operation.

    Attributes:
        valid: Whether validation passed
        error: Error message if invalid
        warning: Warning message (validation passed but with caveats)
        can_create: For directories, whether we can offer to create it
    """

    valid: bool
    error: str | None = None
    warning: str | None = None
    can_create: bool = False


def validate_file_exists(path: str, field_name: str = "path") -> ValidationResult:
    """Validate that a file exists at the given path.

    Args:
        path: File path to validate.
        field_name: Name of the field for error messages.

    Returns:
        ValidationResult with valid=True if file exists.
    """
    if not path or not path.strip():
        return ValidationResult(valid=False, error=f"{field_name}: Path cannot be empty")

    path = path.strip()

    if not os.path.exists(path):
        return ValidationResult(valid=False, error=f"{field_name}: Path does not exist: {path}")

    if not os.path.isfile(path):
        return ValidationResult(valid=False, error=f"{field_name}: Not a file: {path}")

    return ValidationResult(valid=True)


def validate_executable(path: str, field_name: str = "binary") -> ValidationResult:
    """Validate that a file exists and is executable.

    Args:
        path: File path to validate.
        field_name: Name of the field for error messages.

    Returns:
        ValidationResult with valid=True if file exists and is executable.
    """
    file_result = validate_file_exists(path, field_name)
    if not file_result.valid:
        return file_result

    if not os.access(path.strip(), os.X_OK):
        return ValidationResult(
            valid=False,
            error=f"{field_name}: File is not executable: {path}",
        )

    return ValidationResult(valid=True)


def validate_directory(
    path: str, field_name: str = "directory", check_writable: bool = True
) -> ValidationResult:
    """Validate that a directory exists and is optionally writable.

    If the directory doesn't exist, checks if it can be created.

    Args:
        path: Directory path to validate.
        field_name: Name of the field for error messages.
        check_writable: Whether to check write permissions.

    Returns:
        ValidationResult with valid=True if directory exists (and is writable if required).
        If directory doesn't exist but parent is writable, can_create=True.
    """
    if not path or not path.strip():
        return ValidationResult(valid=False, error=f"{field_name}: Path cannot be empty")

    path = path.strip()

    if not os.path.exists(path):
        # Check if we can create it (parent directory exists and is writable)
        parent = os.path.dirname(path)
        if parent and os.path.isdir(parent) and os.access(parent, os.W_OK):
            return ValidationResult(
                valid=False,
                error=f"{field_name}: Directory does not exist: {path}",
                can_create=True,
            )
        return ValidationResult(
            valid=False,
            error=f"{field_name}: Directory does not exist and cannot be created: {path}",
        )

    if not os.path.isdir(path):
        return ValidationResult(valid=False, error=f"{field_name}: Not a directory: {path}")

    if check_writable and not os.access(path, os.W_OK):
        return ValidationResult(
            valid=False,
            error=f"{field_name}: Directory is not writable: {path}",
        )

    return ValidationResult(valid=True)


def validate_integer(
    value: str,
    field_name: str = "value",
    min_value: int | None = None,
    max_value: int | None = None,
) -> ValidationResult:
    """Validate that a value is an integer within optional bounds.

    Args:
        value: String value to validate.
        field_name: Name of the field for error messages.
        min_value: Minimum allowed value (inclusive).
        max_value: Maximum allowed value (inclusive).

    Returns:
        ValidationResult with valid=True if value is valid integer within bounds.
    """
    if not value or not value.strip():
        return ValidationResult(valid=False, error=f"{field_name}: Value cannot be empty")

    try:
        int_value = int(value.strip())
    except ValueError:
        return ValidationResult(
            valid=False,
            error=f"{field_name}: Must be a valid integer, got '{value}'",
        )

    if min_value is not None and int_value < min_value:
        return ValidationResult(
            valid=False,
            error=f"{field_name}: Must be at least {min_value}, got {int_value}",
        )

    if max_value is not None and int_value > max_value:
        return ValidationResult(
            valid=False,
            error=f"{field_name}: Must be at most {max_value}, got {int_value}",
        )

    return ValidationResult(valid=True)


def validate_positive_integer(value: str, field_name: str = "value") -> ValidationResult:
    """Validate that a value is a positive integer (>0).

    Args:
        value: String value to validate.
        field_name: Name of the field for error messages.

    Returns:
        ValidationResult with valid=True if value is positive integer.
    """
    return validate_integer(value, field_name, min_value=1)


def validate_non_negative_integer(value: str, field_name: str = "value") -> ValidationResult:
    """Validate that a value is a non-negative integer (>=0).

    Args:
        value: String value to validate.
        field_name: Name of the field for error messages.

    Returns:
        ValidationResult with valid=True if value is non-negative integer.
    """
    return validate_integer(value, field_name, min_value=0)


def try_create_directory(path: str) -> tuple[bool, str | None]:
    """Attempt to create a directory.

    Args:
        path: Directory path to create.

    Returns:
        Tuple of (success, error_message). If success is True, error is None.
    """
    if not path or not path.strip():
        return False, "Path cannot be empty"

    path = path.strip()

    if os.path.exists(path):
        if os.path.isdir(path):
            return True, None  # Already exists
        return False, f"Path exists but is not a directory: {path}"

    try:
        os.makedirs(path, mode=0o755)
        return True, None
    except PermissionError:
        return False, f"Permission denied creating directory: {path}"
    except OSError as e:
        return False, f"Failed to create directory: {e}"


# =============================================================================
# Password Policy Validation
# =============================================================================


def validate_password_policy(password: str) -> tuple[bool, str]:
    """Validate password against policy: 8+ chars, upper, lower, number, symbol.

    Args:
        password: Password to validate.

    Returns:
        Tuple of (is_valid, error_message). error_message is empty string on success.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;\'`~]', password):
        return False, "Password must contain at least one symbol (!@#$%^&*...)"
    return True, ""


# =============================================================================
# Setting-Type Validators (for SettingMeta.validators)
# =============================================================================

def validate_setting_value(
    key: str,
    value: str,
    setting_type: str,
    validators: list[str],
) -> ValidationResult:
    """Validate a setting value based on its type and validators.

    Args:
        key: Setting key name.
        value: Value to validate.
        setting_type: SettingType value as string.
        validators: List of validator names to apply.

    Returns:
        ValidationResult from the first failing validator, or success if all pass.
    """
    # Type-based validation
    if setting_type == "integer":
        result = validate_integer(value, key)
        if not result.valid:
            return result
    elif setting_type == "executable":
        result = validate_executable(value, key)
        if not result.valid:
            return result
    elif setting_type == "directory":
        result = validate_directory(value, key)
        if not result.valid:
            return result
    elif setting_type == "path":
        result = validate_file_exists(value, key)
        if not result.valid:
            return result

    # Named validators
    for validator in validators:
        if validator == "is_positive_integer":
            result = validate_positive_integer(value, key)
            if not result.valid:
                return result
        elif validator == "is_non_negative_integer":
            result = validate_non_negative_integer(value, key)
            if not result.valid:
                return result
        elif validator == "file_exists":
            result = validate_file_exists(value, key)
            if not result.valid:
                return result
        elif validator == "is_executable":
            result = validate_executable(value, key)
            if not result.valid:
                return result
        elif validator == "directory_exists":
            result = validate_directory(value, key, check_writable=False)
            if not result.valid:
                return result
        elif validator == "is_writable":
            result = validate_directory(value, key, check_writable=True)
            if not result.valid:
                return result
        elif validator.startswith("is_one_of:"):
            allowed = validator.split(":", 1)[1].split(",")
            if value not in allowed:
                return ValidationResult(
                    valid=False,
                    error=f"'{key}' must be one of [{', '.join(allowed)}], got '{value}'",
                )
        elif validator == "is_csv_integers":
            for part in value.split(","):
                part = part.strip()
                if part and not part.isdigit():
                    return ValidationResult(
                        valid=False,
                        error=f"'{key}' must be comma-separated integers, got '{part}'",
                    )

    return ValidationResult(valid=True)
