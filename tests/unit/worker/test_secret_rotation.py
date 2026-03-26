"""Unit tests for pulldb.worker.secret_rotation.rotate_host_secret.

Covers the happy path and all failure / rollback scenarios:

  Phase 1  (fetch_credentials)   — AWS resolver raises
  Phase 2  (validate_current)    — current MySQL credentials rejected
  Phase 4  (mysql_update)        — ALTER USER fails (no rollback needed)
  Phase 5  (verify_new_password) — new password rejected after ALTER USER:
      5a   rollback with new password → old password succeeds
      5b   rollback with new password fails, retry with old password succeeds
      5c   both rollback attempts fail → manual_fix_required
  Phase 6  (aws_update)          — Secrets Manager update fails → manual_fix_required
  Phase 7  (final_verify)        — AWS credential mismatch; final MySQL test fails

HCA Layer: features (tests)
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from pulldb.domain.models import MySQLCredentials
from pulldb.infra.secrets import SecretUpsertResult
from pulldb.worker.secret_rotation import RotationResult, rotate_host_secret


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_CREDENTIAL_REF = "aws-secretsmanager:/pulldb/mysql/testdb"
_SECRET_PATH = "/pulldb/mysql/testdb"
_HOST_ID = "host-uuid-1234"
_HOSTNAME = "db.example.com"

_OLD_CREDS = MySQLCredentials(
    username="pulldb_loader",
    password="old-password-abc",
    host=_HOSTNAME,
    port=3306,
)

_NEW_PASSWORD = "new-password-xyz"

_NEW_CREDS = MySQLCredentials(
    username="pulldb_loader",
    password=_NEW_PASSWORD,
    host=_HOSTNAME,
    port=3306,
)


def _make_resolver_mock(creds: MySQLCredentials) -> MagicMock:
    """Return a CredentialResolver mock whose resolve() returns creds."""
    mock = MagicMock()
    mock.return_value.resolve.return_value = creds
    return mock


def _run(
    resolver_mock: MagicMock,
    test_conn_side_effect: object,
    alter_side_effect: object,
    upsert_result: SecretUpsertResult | None = None,
    *,
    new_password: str = _NEW_PASSWORD,
) -> RotationResult:
    """Run rotate_host_secret with all external calls mocked."""
    with (
        patch("pulldb.worker.secret_rotation.CredentialResolver", resolver_mock),
        patch(
            "pulldb.worker.secret_rotation._test_mysql_connection",
            side_effect=test_conn_side_effect,
        ),
        patch(
            "pulldb.worker.secret_rotation._alter_mysql_password",
            side_effect=alter_side_effect,
        ),
        patch(
            "pulldb.worker.secret_rotation.safe_upsert_single_secret",
            return_value=upsert_result or SecretUpsertResult(success=True),
        ),
    ):
        return rotate_host_secret(
            host_id=_HOST_ID,
            hostname=_HOSTNAME,
            credential_ref=_CREDENTIAL_REF,
            new_password=new_password,
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_full_rotation_succeeds(self) -> None:
        resolver = _make_resolver_mock(_OLD_CREDS)
        # Second resolve() call (phase 7 fresh resolver) returns _NEW_CREDS
        resolver.return_value.resolve.side_effect = [_OLD_CREDS, _NEW_CREDS]

        result = _run(
            resolver_mock=resolver,
            # Phase 2 (validate current) → OK
            # Phase 5 (verify new)       → OK
            # Phase 7 (final MySQL test) → OK
            test_conn_side_effect=[(True, None), (True, None), (True, None)],
            alter_side_effect=[(True, None)],  # Phase 4 ALTER USER → OK
        )

        assert result.success is True
        assert result.phase is None
        assert result.error is None
        assert result.rollback_attempted is False
        assert "fetch_credentials" in result.timing
        assert "mysql_update" in result.timing
        assert "final_verify" in result.timing

    def test_timing_records_all_phases(self) -> None:
        resolver = _make_resolver_mock(_OLD_CREDS)
        resolver.return_value.resolve.side_effect = [_OLD_CREDS, _NEW_CREDS]

        result = _run(
            resolver_mock=resolver,
            test_conn_side_effect=[(True, None), (True, None), (True, None)],
            alter_side_effect=[(True, None)],
        )

        for phase in (
            "fetch_credentials",
            "validate_current",
            "generate_password",
            "mysql_update",
            "verify_new_password",
            "aws_update",
            "final_verify",
            "total",
        ):
            assert phase in result.timing, f"Missing timing key: {phase}"


# ---------------------------------------------------------------------------
# Phase 1 — fetch_credentials failure
# ---------------------------------------------------------------------------


class TestPhase1FetchCredentials:
    def test_aws_resolver_raises_returns_failure(self) -> None:
        resolver = MagicMock()
        resolver.return_value.resolve.side_effect = Exception("AccessDeniedException")

        with (
            patch("pulldb.worker.secret_rotation.CredentialResolver", resolver),
            patch("pulldb.worker.secret_rotation._test_mysql_connection") as mock_test,
            patch("pulldb.worker.secret_rotation._alter_mysql_password") as mock_alter,
        ):
            result = rotate_host_secret(
                host_id=_HOST_ID,
                hostname=_HOSTNAME,
                credential_ref=_CREDENTIAL_REF,
                new_password=_NEW_PASSWORD,
            )

        assert result.success is False
        assert result.phase == "fetch_credentials"
        assert "AccessDeniedException" in (result.error or "")
        mock_test.assert_not_called()
        mock_alter.assert_not_called()

    def test_invalid_credential_ref_prefix_rejected(self) -> None:
        result = rotate_host_secret(
            host_id=_HOST_ID,
            hostname=_HOSTNAME,
            credential_ref="ssm:/wrong/path",  # Not aws-secretsmanager:
            new_password=_NEW_PASSWORD,
        )

        assert result.success is False
        assert result.phase == "validation"


# ---------------------------------------------------------------------------
# Phase 2 — validate_current failure
# ---------------------------------------------------------------------------


class TestPhase2ValidateCurrent:
    def test_invalid_current_credentials_aborts_without_alter(self) -> None:
        resolver = _make_resolver_mock(_OLD_CREDS)

        with (
            patch("pulldb.worker.secret_rotation.CredentialResolver", resolver),
            patch(
                "pulldb.worker.secret_rotation._test_mysql_connection",
                return_value=(False, "Access denied (invalid credentials)"),
            ),
            patch("pulldb.worker.secret_rotation._alter_mysql_password") as mock_alter,
        ):
            result = rotate_host_secret(
                host_id=_HOST_ID,
                hostname=_HOSTNAME,
                credential_ref=_CREDENTIAL_REF,
                new_password=_NEW_PASSWORD,
            )

        assert result.success is False
        assert result.phase == "validate_current"
        # MySQL must NOT have been touched
        mock_alter.assert_not_called()

    def test_missing_privilege_aborts(self) -> None:
        resolver = _make_resolver_mock(_OLD_CREDS)

        with (
            patch("pulldb.worker.secret_rotation.CredentialResolver", resolver),
            patch(
                "pulldb.worker.secret_rotation._test_mysql_connection",
                return_value=(False, "User lacks ALTER USER privilege"),
            ),
            patch("pulldb.worker.secret_rotation._alter_mysql_password") as mock_alter,
        ):
            result = rotate_host_secret(
                host_id=_HOST_ID,
                hostname=_HOSTNAME,
                credential_ref=_CREDENTIAL_REF,
                new_password=_NEW_PASSWORD,
            )

        assert result.success is False
        assert result.phase == "validate_current"
        mock_alter.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 4 — mysql_update failure
# ---------------------------------------------------------------------------


class TestPhase4MysqlUpdate:
    def test_alter_user_failure_no_rollback(self) -> None:
        resolver = _make_resolver_mock(_OLD_CREDS)

        result = _run(
            resolver_mock=resolver,
            test_conn_side_effect=[(True, None)],  # Phase 2 ok
            alter_side_effect=[(False, "MySQL error (1227): Access denied")],  # Phase 4 fails
        )

        assert result.success is False
        assert result.phase == "mysql_update"
        # Rollback should NOT be attempted since MySQL wasn't updated
        assert result.rollback_attempted is False

    def test_alter_failure_preserves_original_credentials(self) -> None:
        """When Phase 4 fails, the password is unchanged — no manual fix needed."""
        resolver = _make_resolver_mock(_OLD_CREDS)

        result = _run(
            resolver_mock=resolver,
            test_conn_side_effect=[(True, None)],
            alter_side_effect=[(False, "MySQL error (1396): User does not exist")],
        )

        assert result.success is False
        assert result.manual_fix_required is False
        assert result.rollback_attempted is False


# ---------------------------------------------------------------------------
# Phase 5 — verify_new_password failure + rollback
# ---------------------------------------------------------------------------


class TestPhase5VerifyNewPasswordRollback:
    def test_rollback_succeeds_with_new_password_auth(self) -> None:
        """Phase 5 fails → rollback attempt using the new password to auth → succeeds."""
        resolver = _make_resolver_mock(_OLD_CREDS)

        result = _run(
            resolver_mock=resolver,
            # Phase 2 ok, Phase 5 FAILS
            test_conn_side_effect=[(True, None), (False, "Connection refused after update")],
            # Phase 4 ALTER succeeds; rollback (first attempt with new pw auth) succeeds
            alter_side_effect=[(True, None), (True, None)],
        )

        assert result.success is False
        assert result.phase == "verify_new_password"
        assert result.rollback_attempted is True
        assert result.rollback_success is True
        assert result.manual_fix_required is False

    def test_rollback_first_attempt_fails_second_succeeds(self) -> None:
        """Phase 5 fails → first rollback attempt (new pw auth) fails → second (old pw auth) succeeds."""
        resolver = _make_resolver_mock(_OLD_CREDS)

        result = _run(
            resolver_mock=resolver,
            # Phase 2 ok, Phase 5 FAILS
            test_conn_side_effect=[(True, None), (False, "Bad handshake")],
            # Phase 4 ALTER succeeds; rollback attempt 1 fails; rollback attempt 2 succeeds
            alter_side_effect=[(True, None), (False, "Can't auth with new pw"), (True, None)],
        )

        assert result.success is False
        assert result.phase == "verify_new_password"
        assert result.rollback_attempted is True
        assert result.rollback_success is True
        assert result.manual_fix_required is False

    def test_rollback_both_attempts_fail_manual_fix_required(self) -> None:
        """Phase 5 fails → both rollback attempts fail → manual_fix_required=True."""
        resolver = _make_resolver_mock(_OLD_CREDS)

        result = _run(
            resolver_mock=resolver,
            # Phase 2 ok, Phase 5 FAILS
            test_conn_side_effect=[(True, None), (False, "Host unreachable")],
            # Phase 4 ALTER succeeds; both rollback attempts fail
            alter_side_effect=[
                (True, None),   # Phase 4
                (False, "Attempt 1 failed"),  # Rollback attempt 1
                (False, "Attempt 2 failed"),  # Rollback attempt 2
            ],
        )

        assert result.success is False
        assert result.phase == "verify_new_password"
        assert result.rollback_attempted is True
        assert result.rollback_success is False
        assert result.manual_fix_required is True
        assert result.manual_fix_instructions is not None
        assert "CRITICAL" in (result.manual_fix_instructions or "")

    def test_rollback_attempt_order(self) -> None:
        """Rollback must first try authenticating with the new password, then old."""
        resolver = _make_resolver_mock(_OLD_CREDS)
        alter_calls: list[tuple] = []

        def capture_alter(
            host: str,
            port: int,
            current_username: str,
            current_password: str,
            new_password: str,
        ) -> tuple[bool, str | None]:
            alter_calls.append((current_password, new_password))
            if len(alter_calls) == 1:
                return True, None  # Phase 4 — success
            if len(alter_calls) == 2:
                return False, "fail"  # Rollback attempt 1 fails
            return True, None  # Rollback attempt 2 succeeds

        with (
            patch("pulldb.worker.secret_rotation.CredentialResolver", resolver),
            patch(
                "pulldb.worker.secret_rotation._test_mysql_connection",
                side_effect=[(True, None), (False, "phase 5 fail")],
            ),
            patch(
                "pulldb.worker.secret_rotation._alter_mysql_password",
                side_effect=capture_alter,
            ),
            patch(
                "pulldb.worker.secret_rotation.safe_upsert_single_secret",
                return_value=SecretUpsertResult(success=True),
            ),
        ):
            rotate_host_secret(
                host_id=_HOST_ID,
                hostname=_HOSTNAME,
                credential_ref=_CREDENTIAL_REF,
                new_password=_NEW_PASSWORD,
            )

        # Phase 4: auth with old password, set new password
        assert alter_calls[0] == (_OLD_CREDS.password, _NEW_PASSWORD)
        # Rollback attempt 1: auth with new password, restore old
        assert alter_calls[1] == (_NEW_PASSWORD, _OLD_CREDS.password)
        # Rollback attempt 2: auth with old password (in case new was never applied), set old
        assert alter_calls[2] == (_OLD_CREDS.password, _OLD_CREDS.password)


# ---------------------------------------------------------------------------
# Phase 6 — aws_update failure
# ---------------------------------------------------------------------------


class TestPhase6AwsUpdateFailure:
    def test_aws_failure_after_mysql_update_requires_manual_fix(self) -> None:
        resolver = _make_resolver_mock(_OLD_CREDS)

        result = _run(
            resolver_mock=resolver,
            # Phase 2 ok, Phase 5 ok
            test_conn_side_effect=[(True, None), (True, None)],
            alter_side_effect=[(True, None)],  # Phase 4 ok
            upsert_result=SecretUpsertResult(success=False, error="ThrottlingException"),
        )

        assert result.success is False
        assert result.phase == "aws_update"
        assert result.manual_fix_required is True
        assert result.manual_fix_instructions is not None
        # Instructions must mention the secret path
        assert _SECRET_PATH in (result.manual_fix_instructions or "")

    def test_aws_failure_includes_manual_aws_cli_command(self) -> None:
        resolver = _make_resolver_mock(_OLD_CREDS)

        result = _run(
            resolver_mock=resolver,
            test_conn_side_effect=[(True, None), (True, None)],
            alter_side_effect=[(True, None)],
            upsert_result=SecretUpsertResult(success=False, error="AccessDeniedException"),
        )

        instructions = result.manual_fix_instructions or ""
        assert "aws secretsmanager put-secret-value" in instructions

    def test_aws_failure_no_rollback_of_mysql(self) -> None:
        """When Phase 6 fails, MySQL already has the new password — do NOT rollback."""
        resolver = _make_resolver_mock(_OLD_CREDS)

        with (
            patch("pulldb.worker.secret_rotation.CredentialResolver", resolver),
            patch(
                "pulldb.worker.secret_rotation._test_mysql_connection",
                side_effect=[(True, None), (True, None)],
            ),
            patch(
                "pulldb.worker.secret_rotation._alter_mysql_password",
            ) as mock_alter,
            patch(
                "pulldb.worker.secret_rotation.safe_upsert_single_secret",
                return_value=SecretUpsertResult(success=False, error="Throttled"),
            ),
        ):
            mock_alter.return_value = (True, None)
            result = rotate_host_secret(
                host_id=_HOST_ID,
                hostname=_HOSTNAME,
                credential_ref=_CREDENTIAL_REF,
                new_password=_NEW_PASSWORD,
            )

        # ALTER USER called exactly once (Phase 4) — no rollback ALTER
        assert mock_alter.call_count == 1
        assert result.rollback_attempted is False


# ---------------------------------------------------------------------------
# Phase 7 — final_verify failure
# ---------------------------------------------------------------------------


class TestPhase7FinalVerify:
    def test_aws_password_mismatch_returns_failure(self) -> None:
        """Phase 7: freshly fetched credentials have wrong password."""
        resolver = MagicMock()
        stale_creds = MySQLCredentials(
            username="pulldb_loader",
            password="wrong-password",  # Mismatch
            host=_HOSTNAME,
            port=3306,
        )
        # First resolve → old creds (phase 1), second resolve → stale creds (phase 7)
        resolver.return_value.resolve.side_effect = [_OLD_CREDS, stale_creds]

        result = _run(
            resolver_mock=resolver,
            # Phase 2 ok, Phase 5 ok; Phase 7 MySQL test is never reached due to mismatch
            test_conn_side_effect=[(True, None), (True, None)],
            alter_side_effect=[(True, None)],
        )

        assert result.success is False
        assert result.phase == "final_verify"
        assert "mismatch" in (result.error or "").lower() or "doesn't match" in (result.error or "")

    def test_final_mysql_connection_fails_returns_failure(self) -> None:
        """Phase 7: AWS credential fetched OK but MySQL connect test fails."""
        resolver = MagicMock()
        resolver.return_value.resolve.side_effect = [_OLD_CREDS, _NEW_CREDS]

        result = _run(
            resolver_mock=resolver,
            # Phase 2 ok, Phase 5 ok, Phase 7 MySQL FAILS
            test_conn_side_effect=[(True, None), (True, None), (False, "Connection refused")],
            alter_side_effect=[(True, None)],
        )

        assert result.success is False
        assert result.phase == "final_verify"

    def test_final_verify_exception_captured_gracefully(self) -> None:
        """Phase 7: resolver raises — exception caught, not propagated."""
        resolver = MagicMock()
        # First resolve ok, second raises
        resolver.return_value.resolve.side_effect = [
            _OLD_CREDS,
            Exception("Network timeout"),
        ]

        result = _run(
            resolver_mock=resolver,
            test_conn_side_effect=[(True, None), (True, None)],
            alter_side_effect=[(True, None)],
        )

        assert result.success is False
        assert result.phase == "final_verify"
        assert "Network timeout" in (result.error or "")
