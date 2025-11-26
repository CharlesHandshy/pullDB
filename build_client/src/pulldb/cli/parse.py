"""CLI argument parsing for pullDB restore command.

Validation rules (strict FAIL HARD semantics):
 - First token must be ``user=<username>``
 - Username must contain at least 6 alphabetic characters (letters only after
   sanitization) used for user_code derivation
 - Exactly one of ``customer=<id>`` or literal ``qatemplate`` must appear
 - Optional ``dbhost=<hostname>`` token
 - Optional ``overwrite`` flag token
 - Unknown tokens produce a validation error (never ignored)
 - Target length constraint: ``<user_code><sanitized_customer>`` <= 51 chars
   (reserves 13 for staging suffix). For qatemplate the target becomes
   ``<user_code>qatemplate``.

Errors raise ``CLIParseError`` with actionable messages. No I/O performed; user
and target uniqueness enforced later by repositories.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass


USER_CODE_LEN = 6
MAX_TARGET_LEN = 51  # Without staging suffix; see architecture docs


class CLIParseError(ValueError):
    """Raised when CLI restore arguments fail validation.

    Error messages MUST be actionable, describing what failed and how to
    correct it. Downstream logic expects explicit failure—never silently
    degrade or assume defaults.
    """


@dataclass(frozen=True)
class RestoreCLIOptions:
    """Parsed and validated restore CLI options.

    Attributes:
        raw_tokens: Original token sequence for audit/logging.
        username: Raw username provided after ``user=`` prefix.
        customer_id: Raw customer identifier if provided (None for qatemplate).
        is_qatemplate: True when qatemplate restore requested.
        dbhost: Optional explicit database host override.
        overwrite: Whether overwrite flag was supplied.
        user_code_candidate: First 6 letters of sanitized username (lowercase).
        target_candidate: Candidate target database name (user_code + customer
            or qatemplate) for length validation / preview purposes.
    """

    raw_tokens: tuple[str, ...]
    username: str
    customer_id: str | None
    is_qatemplate: bool
    dbhost: str | None
    overwrite: bool
    user_code_candidate: str
    target_candidate: str


_TOKEN_USER = re.compile(r"^user=([A-Za-z0-9_.-]+)$")
_TOKEN_CUSTOMER = re.compile(r"^customer=([A-Za-z0-9_.-]+)$")
_TOKEN_DBHOST = re.compile(r"^dbhost=([A-Za-z0-9_.-]+)$")


def _sanitize_letters(value: str) -> str:
    """Return lowercase letters-only version of value.

    Args:
        value: Input string.

    Returns:
        Sanitized string containing only lowercase a-z letters.
    """
    return "".join(ch for ch in value.lower() if ch.isalpha())


def _initial_username(tokens: Sequence[str]) -> tuple[str, str]:
    if not tokens:
        raise CLIParseError(
            "No arguments supplied. Usage: pullDB user=<name> customer=<id>|qatemplate "
            "[dbhost=<host>] [overwrite]"
        )
    first = tokens[0]
    m_user = _TOKEN_USER.match(first)
    if not m_user:
        raise CLIParseError(
            "First argument must be user=<username>. Received: '" + first + "'"
        )
    username = m_user.group(1)
    sanitized_username = _sanitize_letters(username)
    if len(sanitized_username) < USER_CODE_LEN:
        raise CLIParseError(
            "Username must contain at least 6 alphabetic letters after sanitization. "
            f"Provided '{username}' -> '{sanitized_username}'."
        )
    return username, sanitized_username[:USER_CODE_LEN]


def _tokenize(tokens: Sequence[str]) -> tuple[str | None, bool, str | None, bool]:
    customer_id: str | None = None
    is_qatemplate = False
    dbhost: str | None = None
    overwrite = False

    def handle_qatemplate() -> None:
        nonlocal is_qatemplate
        if customer_id is not None:
            raise CLIParseError(
                "Cannot specify both customer=<id> and qatemplate. Choose one."
            )
        is_qatemplate = True

    for tok in tokens:
        if tok in {"qatemplate", "overwrite"}:
            if tok == "overwrite":
                overwrite = True
            else:
                handle_qatemplate()
            continue
        m_cust = _TOKEN_CUSTOMER.match(tok)
        if m_cust:
            if is_qatemplate:
                raise CLIParseError(
                    "Cannot specify both customer=<id> and qatemplate. Choose one."
                )
            if customer_id is not None:
                raise CLIParseError(
                    f"Customer specified more than once ('{customer_id}', '{tok}')."
                )
            customer_id = m_cust.group(1)
            continue
        m_host = _TOKEN_DBHOST.match(tok)
        if m_host:
            if dbhost is not None:
                raise CLIParseError(
                    f"dbhost specified more than once ('{dbhost}', '{tok}')."
                )
            dbhost = m_host.group(1)
            continue
        raise CLIParseError(f"Unrecognized token: '{tok}'")
    return customer_id, is_qatemplate, dbhost, overwrite


def parse_restore_args(tokens: Sequence[str]) -> RestoreCLIOptions:
    """Parse restore command tokens into structured options.

    Args:
        tokens: Sequence of CLI tokens (excluding program name). Order matters
            for the first token (must be ``user=``); other tokens may appear in
            any order.

    Returns:
        ``RestoreCLIOptions`` instance with validated fields.

    Raises:
        CLIParseError: On any validation failure.
    """
    # First token / username processing
    username, user_code_candidate = _initial_username(tokens)

    # Remaining tokens processing
    customer_id, is_qatemplate, dbhost, overwrite = _tokenize(tokens[1:])

    # Enforce exactly one of customer or qatemplate specified
    if customer_id is None and not is_qatemplate:
        raise CLIParseError(
            "Must specify exactly one of customer=<id> or qatemplate. None provided."
        )
    if customer_id is not None and is_qatemplate:
        # Defensive; _tokenize already prevents this
        raise CLIParseError(
            "Cannot specify both customer=<id> and qatemplate. Choose one."
        )

    # Customer / qatemplate sanitization
    if customer_id is not None:
        sanitized_customer = _sanitize_letters(customer_id)
        if not sanitized_customer:
            raise CLIParseError(
                f"Customer identifier '{customer_id}' must contain at least one letter."
            )
    else:
        sanitized_customer = "qatemplate"

    target_candidate = user_code_candidate + sanitized_customer
    if len(target_candidate) > MAX_TARGET_LEN:
        raise CLIParseError(
            "Target database name '"
            f"{target_candidate}' exceeds max length {MAX_TARGET_LEN}. "
            "Shorten username or customer id."
        )

    return RestoreCLIOptions(
        raw_tokens=tuple(tokens),
        username=username,
        customer_id=customer_id,
        is_qatemplate=is_qatemplate,
        dbhost=dbhost,
        overwrite=overwrite,
        user_code_candidate=user_code_candidate,
        target_candidate=target_candidate,
    )


__all__ = ["CLIParseError", "RestoreCLIOptions", "parse_restore_args"]
