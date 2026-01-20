"""MySQL utility functions for safe identifier handling.

Provides helper functions to safely construct SQL statements involving
dynamic identifiers (database names, table names, usernames). MySQL
does not support parameterized queries for identifiers, so we must
use string formatting with proper escaping.

Security Note:
    All functions in this module are defense-in-depth measures. The values
    passed to these functions should already come from trusted internal
    sources (job state, configuration, constants), not direct user input.

HCA Layer: shared
"""

from __future__ import annotations

import re


# Pattern for valid MySQL identifiers (alphanumeric, underscore, dollar sign)
# Must start with letter, underscore, or dollar sign
_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_$][a-zA-Z0-9_$]*$")

# MySQL maximum identifier length
_MAX_IDENTIFIER_LENGTH = 64


def quote_identifier(name: str) -> str:
    """Safely quote a MySQL identifier (database, table, column name).

    Escapes backticks by doubling them and wraps the identifier in backticks.
    This prevents SQL injection even if the identifier contains special characters.

    Args:
        name: The identifier to quote.

    Returns:
        Backtick-quoted identifier with internal backticks escaped.

    Raises:
        ValueError: If name is empty or exceeds MySQL's 64-character limit.

    Examples:
        >>> quote_identifier("my_database")
        '`my_database`'
        >>> quote_identifier("test`db")
        '`test``db`'
        >>> quote_identifier("customer_staging_abc123def456")
        '`customer_staging_abc123def456`'
    """
    if not name:
        raise ValueError("Identifier cannot be empty")
    if len(name) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"Identifier exceeds {_MAX_IDENTIFIER_LENGTH} char limit: {name[:20]}..."
        )

    # Escape backticks by doubling them (MySQL escape sequence)
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """Validate that an identifier matches the safe pattern.

    Use this for identifiers that will be used without backtick quoting
    (e.g., in string comparisons or when the identifier is known to be safe).

    Args:
        name: The identifier to validate.
        kind: Description for error messages (e.g., "database", "user", "table").

    Returns:
        The validated name (unchanged if valid).

    Raises:
        ValueError: If name is empty, too long, or contains invalid characters.

    Examples:
        >>> validate_identifier("my_database_123", "database")
        'my_database_123'
        >>> validate_identifier("test; DROP TABLE users;--", "database")
        Traceback (most recent call last):
            ...
        ValueError: Invalid database name 'test; DROP TABLE users;--': ...
    """
    if not name:
        raise ValueError(f"{kind.title()} name cannot be empty")
    if len(name) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"{kind.title()} name exceeds {_MAX_IDENTIFIER_LENGTH} char limit: {name[:20]}..."
        )
    if not _IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid {kind} name '{name}': must start with letter/underscore/$ "
            "and contain only alphanumeric characters, underscores, and dollar signs"
        )
    return name


def quote_string_literal(value: str) -> str:
    """Safely quote a MySQL string literal for use in SQL.

    Escapes single quotes by doubling them. Use this for string values
    in SQL statements where parameterized queries cannot be used.

    Args:
        value: The string value to quote.

    Returns:
        Single-quoted string with internal quotes escaped.

    Examples:
        >>> quote_string_literal("simple")
        "'simple'"
        >>> quote_string_literal("it's")
        "'it''s'"
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"
