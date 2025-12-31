"""CLI argument parsing for pullDB restore command.

Validation rules (strict FAIL HARD semantics):
 - Optional ``user=<username>`` token (admin override only; normally auto-detected)
 - Username must contain at least 6 alphabetic characters (letters only after
   sanitization) used for user_code derivation
 - Exactly one of ``customer=<id>`` or literal ``qatemplate`` must appear
 - Optional ``suffix=<abc>`` token for target database suffix (1-3 lowercase letters)
 - Optional ``dbhost=<hostname>`` token
 - Optional ``date=<YYYY-MM-DD>`` token for specific backup date
 - Optional ``s3env=<staging|prod>`` token to specify S3 environment
 - Optional ``overwrite`` flag token
 - Unknown tokens produce a validation error (never ignored)
 - Customer must be lowercase letters only (a-z), max 42 chars
 - Target length constraint: ``<user_code><customer><suffix>`` <= 51 chars
   (reserves 13 for staging suffix). For qatemplate the target becomes
   ``<user_code>qatemplate`` or ``<user_code>qatemplate<suffix>``.

Supported option syntax styles:
 - option=value
 - --option=value
 - --option value (space-separated)

Errors raise ``CLIParseError`` with actionable messages. No I/O performed; user
and target uniqueness enforced later by repositories.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


USER_CODE_LEN = 6
MAX_TARGET_LEN = 51  # Without staging suffix; see architecture docs
MAX_SUFFIX_LEN = 3  # Suffix: 1-3 lowercase letters
MAX_CUSTOMER_LEN = 42  # MAX_TARGET_LEN - USER_CODE_LEN - MAX_SUFFIX_LEN


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
        username: Raw username if provided via user= token (None if auto-detect).
        customer_id: Raw customer identifier if provided (None for qatemplate).
        is_qatemplate: True when qatemplate restore requested.
        suffix: Optional suffix for target database (1-3 lowercase letters, e.g., 'dev').
        dbhost: Optional explicit database host override.
        date: Optional specific backup date in YYYY-MM-DD format.
        s3env: Optional S3 environment (staging or prod).
        overwrite: Whether overwrite flag was supplied.
    """

    raw_tokens: tuple[str, ...]
    username: str | None
    customer_id: str | None
    is_qatemplate: bool
    suffix: str | None
    dbhost: str | None
    date: str | None
    s3env: str | None
    overwrite: bool


_TOKEN_USER = re.compile(r"^(?:--)?user=([A-Za-z0-9_.-]+)$")
_TOKEN_CUSTOMER = re.compile(r"^(?:--)?customer=([a-z]+)$")
_TOKEN_DBHOST = re.compile(r"^(?:--)?dbhost=([A-Za-z0-9_.-]+)$")
_TOKEN_DATE = re.compile(r"^(?:--)?date=(\d{4}-\d{2}-\d{2})$")
_TOKEN_S3ENV = re.compile(r"^(?:--)?s3env=(staging|prod)$")
_TOKEN_SUFFIX = re.compile(r"^(?:--)?suffix=([a-z]{1,3})$")


def _tokenize(
    tokens: Sequence[str],
) -> tuple[str | None, str | None, bool, str | None, str | None, str | None, str | None, bool]:
    """Parse all tokens and return extracted values.
    
    Supports multiple syntax styles:
    - option=value
    - --option=value  
    - --option value (space-separated)
    
    Returns:
        Tuple of (username, customer_id, is_qatemplate, suffix, dbhost, date, s3env, overwrite)
    """
    username: str | None = None
    customer_id: str | None = None
    is_qatemplate = False
    suffix: str | None = None
    dbhost: str | None = None
    date: str | None = None
    s3env: str | None = None
    overwrite = False
    
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        
        # Check for flag tokens first (with or without --)
        tok_stripped = tok.lstrip("-")
        if tok_stripped == "qatemplate":
            if customer_id is not None:
                raise CLIParseError(
                    "Cannot specify both customer=<id> and qatemplate. Choose one."
                )
            is_qatemplate = True
            i += 1
            continue
        if tok_stripped == "overwrite":
            overwrite = True
            i += 1
            continue
        
        # Handle --option value (space-separated) syntax
        if tok.startswith("--") and "=" not in tok:
            opt_name = tok[2:]
            if i + 1 >= len(tokens):
                raise CLIParseError(f"Option {tok} requires a value")
            opt_value = tokens[i + 1]
            
            if opt_name == "user":
                if username is not None:
                    raise CLIParseError("user specified more than once")
                username = opt_value
                i += 2
                continue
            elif opt_name == "customer":
                if is_qatemplate:
                    raise CLIParseError("Cannot specify both customer and qatemplate")
                if customer_id is not None:
                    raise CLIParseError("customer specified more than once")
                # Validate: lowercase letters only
                if not re.match(r"^[a-z]+$", opt_value):
                    raise CLIParseError(
                        f"customer must contain only lowercase letters (a-z). Got: '{opt_value}'. "
                        "Use lowercase letters only, e.g., 'acme' instead of 'Acme123'."
                    )
                if len(opt_value) > MAX_CUSTOMER_LEN:
                    raise CLIParseError(
                        f"customer exceeds maximum length of {MAX_CUSTOMER_LEN} characters "
                        f"(got {len(opt_value)}). Shorten the customer name."
                    )
                customer_id = opt_value
                i += 2
                continue
            elif opt_name == "dbhost":
                if dbhost is not None:
                    raise CLIParseError("dbhost specified more than once")
                dbhost = opt_value
                i += 2
                continue
            elif opt_name == "date":
                if date is not None:
                    raise CLIParseError("date specified more than once")
                # Validate date format
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", opt_value):
                    raise CLIParseError(f"Invalid date format '{opt_value}'. Use YYYY-MM-DD")
                try:
                    datetime.strptime(opt_value, "%Y-%m-%d")
                except ValueError:
                    raise CLIParseError(f"Invalid date '{opt_value}'") from None
                date = opt_value
                i += 2
                continue
            elif opt_name == "s3env":
                if s3env is not None:
                    raise CLIParseError("s3env specified more than once")
                if opt_value not in ("staging", "prod"):
                    raise CLIParseError(f"s3env must be staging or prod. Got: {opt_value}")
                s3env = opt_value
                i += 2
                continue
            elif opt_name == "suffix":
                if suffix is not None:
                    raise CLIParseError("suffix specified more than once")
                if not re.match(r"^[a-z]{1,3}$", opt_value):
                    if len(opt_value) > MAX_SUFFIX_LEN:
                        raise CLIParseError(
                            f"suffix must be 1-3 lowercase letters (a-z). Got: '{opt_value}' "
                            f"({len(opt_value)} chars). Maximum is {MAX_SUFFIX_LEN} characters, e.g., 'dev'."
                        )
                    raise CLIParseError(
                        f"suffix must be 1-3 lowercase letters (a-z). Got: '{opt_value}'. "
                        "Use lowercase letters only, e.g., 'dev' instead of 'DEV'."
                    )
                suffix = opt_value
                i += 2
                continue
            else:
                raise CLIParseError(f"Unrecognized option: {tok}")

        # Check user= token (with optional --)
        m_user = _TOKEN_USER.match(tok)
        if m_user:
            if username is not None:
                raise CLIParseError(
                    f"user specified more than once ('{username}', '{tok}')."
                )
            username = m_user.group(1)
            i += 1
            continue

        # Check customer= token - must be lowercase letters only
        if tok.lstrip("-").startswith("customer="):
            if is_qatemplate:
                raise CLIParseError(
                    "Cannot specify both customer=<id> and qatemplate. Choose one."
                )
            if customer_id is not None:
                raise CLIParseError(
                    f"customer specified more than once ('{customer_id}', '{tok}')."
                )
            # Extract value after customer=
            cust_value = tok.split("=", 1)[1] if "=" in tok else ""
            if not re.match(r"^[a-z]+$", cust_value):
                raise CLIParseError(
                    f"customer must contain only lowercase letters (a-z). Got: '{cust_value}'. "
                    "Use lowercase letters only, e.g., 'acme' instead of 'Acme123'."
                )
            if len(cust_value) > MAX_CUSTOMER_LEN:
                raise CLIParseError(
                    f"customer exceeds maximum length of {MAX_CUSTOMER_LEN} characters "
                    f"(got {len(cust_value)}). Shorten the customer name."
                )
            customer_id = cust_value
            i += 1
            continue

        # Check dbhost= token
        m_host = _TOKEN_DBHOST.match(tok)
        if m_host:
            if dbhost is not None:
                raise CLIParseError(
                    f"dbhost specified more than once ('{dbhost}', '{tok}')."
                )
            dbhost = m_host.group(1)
            i += 1
            continue

        # Check date= token
        m_date = _TOKEN_DATE.match(tok)
        if m_date:
            if date is not None:
                raise CLIParseError(
                    f"date specified more than once ('{date}', '{tok}')."
                )
            date_str = m_date.group(1)
            # Validate date is a real date
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise CLIParseError(
                    f"Invalid date '{date_str}'. Must be a valid date in YYYY-MM-DD format."
                ) from None
            date = date_str
            i += 1
            continue

        # Check s3env= token
        m_s3env = _TOKEN_S3ENV.match(tok)
        if m_s3env:
            if s3env is not None:
                raise CLIParseError(
                    f"s3env specified more than once ('{s3env}', '{tok}')."
                )
            s3env = m_s3env.group(1)
            i += 1
            continue

        # Check suffix= token - must be 1-3 lowercase letters
        if tok.lstrip("-").startswith("suffix="):
            if suffix is not None:
                raise CLIParseError(
                    f"suffix specified more than once ('{suffix}', '{tok}')."
                )
            suffix_value = tok.split("=", 1)[1] if "=" in tok else ""
            if not re.match(r"^[a-z]{1,3}$", suffix_value):
                if len(suffix_value) > MAX_SUFFIX_LEN:
                    raise CLIParseError(
                        f"suffix must be 1-3 lowercase letters (a-z). Got: '{suffix_value}' "
                        f"({len(suffix_value)} chars). Maximum is {MAX_SUFFIX_LEN} characters, e.g., 'dev'."
                    )
                raise CLIParseError(
                    f"suffix must be 1-3 lowercase letters (a-z). Got: '{suffix_value}'. "
                    "Use lowercase letters only, e.g., 'dev' instead of 'DEV'."
                )
            suffix = suffix_value
            i += 1
            continue

        # Handle bare tokens (no = sign) - could be customer or dbhost
        if "=" not in tok and re.match(r"^[A-Za-z0-9_.-]+$", tok):
            # If we don't have a customer yet and token is lowercase letters only,
            # treat it as customer
            if customer_id is None and not is_qatemplate and re.match(r"^[a-z]+$", tok):
                if len(tok) > MAX_CUSTOMER_LEN:
                    raise CLIParseError(
                        f"customer exceeds maximum length of {MAX_CUSTOMER_LEN} characters "
                        f"(got {len(tok)}). Shorten the customer name."
                    )
                customer_id = tok
                i += 1
                continue
            
            # If we already have customer/qatemplate, treat bare token as dbhost
            if customer_id is not None or is_qatemplate:
                if dbhost is not None:
                    raise CLIParseError(
                        f"dbhost specified more than once ('{dbhost}', '{tok}')."
                    )
                dbhost = tok
                i += 1
                continue
            
            # Token doesn't fit customer pattern but we don't have customer yet
            raise CLIParseError(
                f"Unrecognized token: '{tok}'. "
                "Customer must be lowercase letters only (a-z)."
            )

        raise CLIParseError(f"Unrecognized token: '{tok}'")

    return username, customer_id, is_qatemplate, suffix, dbhost, date, s3env, overwrite


def parse_restore_args(tokens: Sequence[str]) -> RestoreCLIOptions:
    """Parse restore command tokens into structured options.

    Args:
        tokens: Sequence of CLI tokens (excluding program name). Tokens may
            appear in any order.

    Returns:
        ``RestoreCLIOptions`` instance with validated fields.

    Raises:
        CLIParseError: On any validation failure.
    """
    if not tokens:
        raise CLIParseError(
            "No arguments supplied. Usage: pulldb restore <customer> [options]\n"
            "  or: pulldb restore customer=<id> [options]\n"
            "  or: pulldb restore qatemplate [options]"
        )

    # Parse all tokens
    username, customer_id, is_qatemplate, suffix, dbhost, date, s3env, overwrite = _tokenize(tokens)

    # Enforce exactly one of customer or qatemplate specified
    if customer_id is None and not is_qatemplate:
        raise CLIParseError(
            "Must specify a customer. Usage: pulldb restore <customer> [options]\n"
            "  or: pulldb restore customer=<id> [options]\n"
            "  or: pulldb restore qatemplate [options]"
        )
    if customer_id is not None and is_qatemplate:
        # Defensive; _tokenize already prevents this
        raise CLIParseError(
            "Cannot specify both customer=<id> and qatemplate. Choose one."
        )

    return RestoreCLIOptions(
        raw_tokens=tuple(tokens),
        username=username,
        customer_id=customer_id,
        is_qatemplate=is_qatemplate,
        suffix=suffix,
        dbhost=dbhost,
        date=date,
        s3env=s3env,
        overwrite=overwrite,
    )


__all__ = ["CLIParseError", "RestoreCLIOptions", "parse_restore_args"]
