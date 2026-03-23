"""Unit tests for pulldb.cli.parse.

Tests the pure argument-parsing layer with no I/O dependency:
  - normalize_customer_name: customer name truncation + hashing
  - parse_restore_args: full token validation and parsing
  - CLIParseError: error cases

HCA Layer: features (tests)
"""

from __future__ import annotations

import pytest

from pulldb.cli.parse import (
    CLIParseError,
    MAX_CUSTOMER_LEN,
    RestoreCLIOptions,
    normalize_customer_name,
    parse_restore_args,
)


# ---------------------------------------------------------------------------
# normalize_customer_name
# ---------------------------------------------------------------------------

class TestNormalizeCustomerName:
    def test_short_name_unchanged(self) -> None:
        assert normalize_customer_name("acme") == "acme"

    def test_exactly_max_len_unchanged(self) -> None:
        name = "a" * MAX_CUSTOMER_LEN
        assert normalize_customer_name(name) == name

    def test_one_over_max_len_truncated(self) -> None:
        name = "a" * (MAX_CUSTOMER_LEN + 1)
        result = normalize_customer_name(name)
        assert len(result) == MAX_CUSTOMER_LEN

    def test_result_deterministic(self) -> None:
        long_name = "verylongcustomername" * 3  # 60 chars
        assert normalize_customer_name(long_name) == normalize_customer_name(long_name)

    def test_different_long_names_different_results(self) -> None:
        name_a = "a" * 43
        name_b = "b" * 43
        assert normalize_customer_name(name_a) != normalize_customer_name(name_b)

    def test_empty_string_unchanged(self) -> None:
        assert normalize_customer_name("") == ""


# ---------------------------------------------------------------------------
# parse_restore_args — happy paths
# ---------------------------------------------------------------------------

class TestParseRestoreArgsHappyPaths:
    def test_positional_customer(self) -> None:
        opts = parse_restore_args(["acme"])
        assert opts.customer_id == "acme"
        assert not opts.is_qatemplate

    def test_customer_kwarg(self) -> None:
        opts = parse_restore_args(["customer=acme"])
        assert opts.customer_id == "acme"

    def test_qatemplate(self) -> None:
        opts = parse_restore_args(["qatemplate"])
        assert opts.is_qatemplate
        assert opts.customer_id is None

    def test_suffix_option(self) -> None:
        opts = parse_restore_args(["acme", "suffix=dev"])
        assert opts.suffix == "dev"

    def test_dbhost_option(self) -> None:
        opts = parse_restore_args(["acme", "dbhost=db01.example.com"])
        assert opts.dbhost == "db01.example.com"

    def test_date_option(self) -> None:
        opts = parse_restore_args(["acme", "date=2026-01-15"])
        assert opts.date == "2026-01-15"

    def test_s3env_staging(self) -> None:
        opts = parse_restore_args(["acme", "s3env=staging"])
        assert opts.s3env == "staging"

    def test_s3env_prod(self) -> None:
        opts = parse_restore_args(["acme", "s3env=prod"])
        assert opts.s3env == "prod"

    def test_overwrite_flag(self) -> None:
        opts = parse_restore_args(["acme", "overwrite"])
        assert opts.overwrite

    def test_user_option(self) -> None:
        opts = parse_restore_args(["acme", "user=johndoe"])
        assert opts.username == "johndoe"

    def test_combined_options(self) -> None:
        opts = parse_restore_args([
            "customer=bigcorp", "suffix=qa", "s3env=prod",
            "date=2026-03-01", "overwrite",
        ])
        assert opts.customer_id == "bigcorp"
        assert opts.suffix == "qa"
        assert opts.s3env == "prod"
        assert opts.date == "2026-03-01"
        assert opts.overwrite

    def test_double_dash_option_style(self) -> None:
        opts = parse_restore_args(["acme", "--suffix=dev"])
        assert opts.suffix == "dev"

    def test_raw_tokens_preserved(self) -> None:
        tokens = ["acme", "suffix=dev"]
        opts = parse_restore_args(tokens)
        assert opts.raw_tokens == tuple(tokens)

    def test_custom_target(self) -> None:
        opts = parse_restore_args(["acme", "target=mycustomdb"])
        assert opts.custom_target == "mycustomdb"

    def test_long_customer_normalized(self) -> None:
        long_name = "a" * (MAX_CUSTOMER_LEN + 5)
        opts = parse_restore_args([f"customer={long_name}"])
        assert opts.customer_normalized
        assert opts.original_customer == long_name
        assert len(opts.customer_id) == MAX_CUSTOMER_LEN  # type: ignore[arg-type]

    def test_defaults_are_none_or_false(self) -> None:
        opts = parse_restore_args(["acme"])
        assert opts.username is None
        assert opts.suffix is None
        assert opts.dbhost is None
        assert opts.date is None
        assert opts.s3env is None
        assert not opts.overwrite
        assert not opts.customer_normalized


# ---------------------------------------------------------------------------
# parse_restore_args — error cases
# ---------------------------------------------------------------------------

class TestParseRestoreArgsErrors:
    def test_empty_tokens_raises(self) -> None:
        with pytest.raises(CLIParseError, match="No arguments"):
            parse_restore_args([])

    def test_customer_and_qatemplate_raises(self) -> None:
        with pytest.raises(CLIParseError, match="both"):
            parse_restore_args(["customer=acme", "qatemplate"])

    def test_no_customer_no_qatemplate_raises(self) -> None:
        with pytest.raises(CLIParseError, match="customer"):
            parse_restore_args(["suffix=dev"])

    def test_unknown_token_raises(self) -> None:
        with pytest.raises(CLIParseError, match="Unrecognized"):
            parse_restore_args(["acme", "foobar=value"])

    def test_invalid_s3env_raises(self) -> None:
        with pytest.raises(CLIParseError):
            parse_restore_args(["acme", "s3env=invalid"])

    def test_suffix_too_long_raises(self) -> None:
        with pytest.raises(CLIParseError):
            parse_restore_args(["acme", "suffix=toolong"])

    def test_customer_with_uppercase_raises(self) -> None:
        with pytest.raises(CLIParseError):
            parse_restore_args(["customer=ACME"])

    def test_suffix_and_target_together_raises(self) -> None:
        with pytest.raises(CLIParseError, match="suffix"):
            parse_restore_args(["acme", "suffix=dev", "target=mydb"])


# ---------------------------------------------------------------------------
# RestoreCLIOptions is frozen
# ---------------------------------------------------------------------------

class TestRestoreCLIOptionsFrozen:
    def test_immutable(self) -> None:
        opts = parse_restore_args(["acme"])
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            opts.customer_id = "other"  # type: ignore[misc]
