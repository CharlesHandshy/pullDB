"""Tests for CLI restore argument parsing (prototype phase).

Covers success paths and failure modes for user/customer/qatemplate parsing
and length constraints. These tests ensure FAIL HARD semantics produce
actionable error messages.
"""

from __future__ import annotations

import pytest

from pulldb.cli.parse import (
    MAX_TARGET_LEN,
    USER_CODE_LEN,
    CLIParseError,
    RestoreCLIOptions,
    parse_restore_args,
)


def test_parse_success_customer_minimal() -> None:
    opts = parse_restore_args(["user=alphabetic", "customer=Acme-123"])
    assert isinstance(opts, RestoreCLIOptions)
    assert opts.username == "alphabetic"
    assert opts.customer_id == "Acme-123"
    assert not opts.is_qatemplate
    assert opts.user_code_candidate == "alphab"  # first 6 letters
    assert opts.target_candidate.startswith("alphab")


def test_parse_success_qatemplate() -> None:
    opts = parse_restore_args(["user=alphabetic", "qatemplate"])
    assert opts.is_qatemplate
    assert opts.customer_id is None
    assert opts.target_candidate == "alphabqatemplate"


def test_parse_requires_first_user() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=foo", "user=alphabetic"])
    assert "First argument must be user=" in str(exc.value)


def test_parse_username_requires_six_letters() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=a1-2", "qatemplate"])
    assert "at least 6 alphabetic" in str(exc.value)


def test_parse_rejects_missing_mode() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=alphabetic"])
    assert "Must specify exactly one" in str(exc.value)


def test_parse_rejects_both_modes() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=alphabetic", "customer=foo", "qatemplate"])
    assert "Cannot specify both" in str(exc.value)


def test_parse_rejects_duplicate_customer() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=alphabetic", "customer=foo", "customer=bar"])
    assert "Customer specified more than once" in str(exc.value)


def test_parse_rejects_duplicate_dbhost() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(
            [
                "user=alphabetic",
                "customer=foo",
                "dbhost=db1",
                "dbhost=db2",
            ]
        )
    assert "dbhost specified more than once" in str(exc.value)


def test_parse_rejects_unknown_token() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=alphabetic", "customer=foo", "unknown=1"])
    assert "Unrecognized token" in str(exc.value)


def test_parse_customer_must_have_letter() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=alphabetic", "customer=123-456"])
    assert "must contain at least one letter" in str(exc.value)


def test_parse_target_length_exceeded() -> None:
    long_customer = "a" * (MAX_TARGET_LEN - USER_CODE_LEN + 1)
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["user=alphabetic", f"customer={long_customer}"])
    assert "exceeds max length" in str(exc.value)


def test_parse_dbhost_and_overwrite_flags() -> None:
    opts = parse_restore_args(
        [
            "user=alphabetic",
            "customer=Acme-123",
            "dbhost=db1",
            "overwrite",
        ]
    )
    assert opts.dbhost == "db1"
    assert opts.overwrite is True
