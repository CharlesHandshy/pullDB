"""Tests for CLI restore argument parsing (prototype phase).

Covers success paths and failure modes for customer/qatemplate parsing.
These tests ensure FAIL HARD semantics produce actionable error messages.
"""

from __future__ import annotations

import pytest

from pulldb.cli.parse import (
    CLIParseError,
    RestoreCLIOptions,
    parse_restore_args,
    MAX_CUSTOMER_LEN,
    MAX_SUFFIX_LEN,
)


def test_parse_success_customer_minimal() -> None:
    opts = parse_restore_args(["customer=acme"])
    assert isinstance(opts, RestoreCLIOptions)
    assert opts.customer_id == "acme"
    assert not opts.is_qatemplate
    assert opts.username is None


def test_parse_success_customer_with_user() -> None:
    opts = parse_restore_args(["user=alphabetic", "customer=acme"])
    assert opts.username == "alphabetic"
    assert opts.customer_id == "acme"
    assert not opts.is_qatemplate


def test_parse_success_qatemplate() -> None:
    opts = parse_restore_args(["qatemplate"])
    assert opts.is_qatemplate
    assert opts.customer_id is None


def test_parse_success_qatemplate_with_user() -> None:
    opts = parse_restore_args(["user=alphabetic", "qatemplate"])
    assert opts.is_qatemplate
    assert opts.customer_id is None
    assert opts.username == "alphabetic"


def test_parse_rejects_missing_mode() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=alphabetic"])
    assert "Must specify exactly one" in str(exc.value)


def test_parse_rejects_both_modes() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=acme", "qatemplate"])
    assert "Cannot specify both" in str(exc.value)


def test_parse_rejects_duplicate_customer() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=acme", "customer=test"])
    assert "customer specified more than once" in str(exc.value)


def test_parse_rejects_duplicate_dbhost() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(
            [
                "customer=acme",
                "dbhost=db1",
                "dbhost=db2",
            ]
        )
    assert "dbhost specified more than once" in str(exc.value)


def test_parse_rejects_unknown_token() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=acme", "unknown=1"])
    assert "Unrecognized token" in str(exc.value)


def test_parse_dbhost_and_overwrite_flags() -> None:
    opts = parse_restore_args(
        [
            "customer=acme",
            "dbhost=db1",
            "overwrite",
        ]
    )
    assert opts.dbhost == "db1"
    assert opts.overwrite is True


def test_parse_date_option() -> None:
    opts = parse_restore_args(["customer=acme", "date=2024-10-15"])
    assert opts.date == "2024-10-15"


def test_parse_s3env_option() -> None:
    opts = parse_restore_args(["customer=acme", "s3env=prod"])
    assert opts.s3env == "prod"


def test_parse_all_options() -> None:
    opts = parse_restore_args([
        "user=testuser",
        "customer=acme",
        "dbhost=db1",
        "date=2024-10-15",
        "s3env=staging",
        "overwrite",
    ])
    assert opts.username == "testuser"
    assert opts.customer_id == "acme"
    assert opts.dbhost == "db1"
    assert opts.date == "2024-10-15"
    assert opts.s3env == "staging"
    assert opts.overwrite is True


def test_parse_dashed_option_syntax() -> None:
    """Test --option=value syntax."""
    opts = parse_restore_args(["--customer=acme", "--dbhost=db1"])
    assert opts.customer_id == "acme"
    assert opts.dbhost == "db1"


def test_parse_space_separated_syntax() -> None:
    """Test --option value (space-separated) syntax."""
    opts = parse_restore_args(["--customer", "acme", "--dbhost", "db1"])
    assert opts.customer_id == "acme"
    assert opts.dbhost == "db1"


def test_parse_mixed_syntax() -> None:
    """Test mixing different option syntax styles."""
    opts = parse_restore_args([
        "customer=acme",
        "--dbhost=db1",
        "--date", "2024-10-15",
        "overwrite",
    ])
    assert opts.customer_id == "acme"
    assert opts.dbhost == "db1"
    assert opts.date == "2024-10-15"
    assert opts.overwrite is True


# --- Suffix tests ---

def test_parse_suffix_with_qatemplate() -> None:
    """Suffix works with qatemplate."""
    opts = parse_restore_args(["qatemplate", "suffix=dev"])
    assert opts.is_qatemplate
    assert opts.suffix == "dev"


def test_parse_suffix_with_customer() -> None:
    """Suffix now works for customer restores too."""
    opts = parse_restore_args(["customer=acme", "suffix=abc"])
    assert opts.customer_id == "acme"
    assert opts.suffix == "abc"


def test_parse_suffix_space_separated() -> None:
    """Test --suffix value syntax."""
    opts = parse_restore_args(["customer=acme", "--suffix", "xyz"])
    assert opts.suffix == "xyz"


def test_parse_suffix_dashed_syntax() -> None:
    """Test --suffix=value syntax."""
    opts = parse_restore_args(["qatemplate", "--suffix=dev"])
    assert opts.suffix == "dev"


# --- Validation failure tests (FAIL HARD) ---

def test_parse_rejects_uppercase_customer() -> None:
    """Customer must be lowercase only."""
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=Acme"])
    assert "lowercase letters (a-z)" in str(exc.value)
    assert "Acme" in str(exc.value)


def test_parse_rejects_customer_with_numbers() -> None:
    """Customer must not contain numbers."""
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=acme123"])
    assert "lowercase letters (a-z)" in str(exc.value)
    assert "acme123" in str(exc.value)


def test_parse_rejects_customer_with_symbols() -> None:
    """Customer must not contain symbols."""
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=acme-corp"])
    assert "lowercase letters (a-z)" in str(exc.value)


def test_parse_rejects_customer_too_long() -> None:
    """Customer must not exceed MAX_CUSTOMER_LEN."""
    long_customer = "a" * (MAX_CUSTOMER_LEN + 1)
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args([f"customer={long_customer}"])
    assert f"exceeds maximum length of {MAX_CUSTOMER_LEN}" in str(exc.value)


def test_parse_rejects_uppercase_suffix() -> None:
    """Suffix must be lowercase only."""
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["qatemplate", "suffix=DEV"])
    assert "lowercase letters (a-z)" in str(exc.value)
    assert "DEV" in str(exc.value)


def test_parse_rejects_suffix_with_numbers() -> None:
    """Suffix must not contain numbers."""
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["qatemplate", "suffix=dev1"])
    assert "lowercase letters (a-z)" in str(exc.value)


def test_parse_rejects_suffix_too_long() -> None:
    """Suffix must not exceed MAX_SUFFIX_LEN."""
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["qatemplate", "suffix=development"])
    assert f"Maximum is {MAX_SUFFIX_LEN} characters" in str(exc.value)
