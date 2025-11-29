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
)


def test_parse_success_customer_minimal() -> None:
    opts = parse_restore_args(["customer=Acme-123"])
    assert isinstance(opts, RestoreCLIOptions)
    assert opts.customer_id == "Acme-123"
    assert not opts.is_qatemplate
    assert opts.username is None


def test_parse_success_customer_with_user() -> None:
    opts = parse_restore_args(["user=alphabetic", "customer=Acme-123"])
    assert opts.username == "alphabetic"
    assert opts.customer_id == "Acme-123"
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
        parse_restore_args(["customer=foo", "qatemplate"])
    assert "Cannot specify both" in str(exc.value)


def test_parse_rejects_duplicate_customer() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=foo", "customer=bar"])
    assert "customer specified more than once" in str(exc.value)


def test_parse_rejects_duplicate_dbhost() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(
            [
                "customer=foo",
                "dbhost=db1",
                "dbhost=db2",
            ]
        )
    assert "dbhost specified more than once" in str(exc.value)


def test_parse_rejects_unknown_token() -> None:
    with pytest.raises(CLIParseError) as exc:
        parse_restore_args(["customer=foo", "unknown=1"])
    assert "Unrecognized token" in str(exc.value)


def test_parse_dbhost_and_overwrite_flags() -> None:
    opts = parse_restore_args(
        [
            "customer=Acme-123",
            "dbhost=db1",
            "overwrite",
        ]
    )
    assert opts.dbhost == "db1"
    assert opts.overwrite is True


def test_parse_date_option() -> None:
    opts = parse_restore_args(["customer=foo", "date=2024-10-15"])
    assert opts.date == "2024-10-15"


def test_parse_s3env_option() -> None:
    opts = parse_restore_args(["customer=foo", "s3env=prod"])
    assert opts.s3env == "prod"


def test_parse_all_options() -> None:
    opts = parse_restore_args([
        "user=testuser",
        "customer=Acme",
        "dbhost=db1",
        "date=2024-10-15",
        "s3env=staging",
        "overwrite",
    ])
    assert opts.username == "testuser"
    assert opts.customer_id == "Acme"
    assert opts.dbhost == "db1"
    assert opts.date == "2024-10-15"
    assert opts.s3env == "staging"
    assert opts.overwrite is True


def test_parse_dashed_option_syntax() -> None:
    """Test --option=value syntax."""
    opts = parse_restore_args(["--customer=Acme", "--dbhost=db1"])
    assert opts.customer_id == "Acme"
    assert opts.dbhost == "db1"


def test_parse_space_separated_syntax() -> None:
    """Test --option value (space-separated) syntax."""
    opts = parse_restore_args(["--customer", "Acme", "--dbhost", "db1"])
    assert opts.customer_id == "Acme"
    assert opts.dbhost == "db1"


def test_parse_mixed_syntax() -> None:
    """Test mixing different option syntax styles."""
    opts = parse_restore_args([
        "customer=Acme",
        "--dbhost=db1",
        "--date", "2024-10-15",
        "overwrite",
    ])
    assert opts.customer_id == "Acme"
    assert opts.dbhost == "db1"
    assert opts.date == "2024-10-15"
    assert opts.overwrite is True
