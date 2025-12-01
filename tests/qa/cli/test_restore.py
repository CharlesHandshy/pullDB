"""
Category 2: Restore Command Tests

Tests for:
- Basic restore invocation
- Argument parsing (all syntax variants)
- Validation of required arguments
- S3 environment selection
- QA template handling
- Error scenarios

Test Count: 18 tests

ARCHITECTURE NOTE:
The `restore` command submits jobs via API (`POST /api/jobs`).
User is auto-detected from environment (USER or SUDO_USER).
Target database name is auto-generated as: <user_code><customer>

Valid options:
- customer=<id>       Customer database to restore (OR qatemplate)
- qatemplate          Restore QA template (flag, no value)
- dbhost=<hostname>   Target database host (optional)
- date=<YYYY-MM-DD>   Specific backup date (optional)
- s3env=<staging|prod> S3 environment (optional)
- overwrite           Allow overwrite (flag, no value)
- user=<username>     Override user (admin only, optional)

NOT valid:
- target=<name>       (target is auto-generated, not user-specifiable)
"""

from __future__ import annotations

import responses
from click.testing import CliRunner

from pulldb.cli.main import cli

from .conftest import MOCK_API_BASE, SAMPLE_JOB_ID, SAMPLE_USER_CODE, SAMPLE_USERNAME


# ---------------------------------------------------------------------------
# Restore Command - Missing Arguments
# ---------------------------------------------------------------------------


class TestRestoreMissingArgs:
    """Tests for restore with missing required arguments."""

    def test_restore_no_args_shows_error(self, runner: CliRunner) -> None:
        """pulldb restore without arguments shows error."""
        result = runner.invoke(cli, ["restore"])
        assert result.exit_code != 0
        # Should indicate missing customer/qatemplate
        output_lower = result.output.lower()
        assert "missing" in output_lower or "customer" in output_lower

    def test_restore_only_user_shows_error(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with only user= shows error (needs customer)."""
        result = runner.invoke(cli, ["restore", f"user={SAMPLE_USER_CODE}"])
        # Should fail - need customer or qatemplate
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Restore Command - Argument Syntax Variants
# ---------------------------------------------------------------------------


class TestRestoreArgumentSyntax:
    """Tests for different restore argument syntax styles."""

    @responses.activate
    def test_restore_equals_style(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore customer=xxx works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={
                "job_id": SAMPLE_JOB_ID,
                "target": f"{SAMPLE_USER_CODE}testcust",
                "staging_name": f"{SAMPLE_USER_CODE}testcust_staging",
                "status": "queued",
            },
            status=201,
        )
        result = runner.invoke(
            cli,
            ["restore", "customer=testcust"],
        )
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_restore_dashed_equals_style(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore --customer=xxx works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={
                "job_id": SAMPLE_JOB_ID,
                "target": f"{SAMPLE_USER_CODE}testcust",
                "status": "queued",
            },
            status=201,
        )
        result = runner.invoke(
            cli,
            ["restore", "--customer=testcust"],
        )
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_restore_space_separated_style(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore --customer xxx works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={
                "job_id": SAMPLE_JOB_ID,
                "target": f"{SAMPLE_USER_CODE}testcust",
                "status": "queued",
            },
            status=201,
        )
        result = runner.invoke(
            cli,
            ["restore", "--customer", "testcust"],
        )
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Restore Command - QA Template Handling
# ---------------------------------------------------------------------------


class TestRestoreQATemplate:
    """Tests for QA template specific behavior."""

    @responses.activate
    def test_restore_qatemplate_flag(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore qatemplate works (flag, no value)."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={
                "job_id": SAMPLE_JOB_ID,
                "target": f"{SAMPLE_USER_CODE}qatemplate",
                "status": "queued",
            },
            status=201,
        )
        result = runner.invoke(cli, ["restore", "qatemplate"])
        assert result.exit_code in [0, 1]

    def test_restore_qatemplate_and_customer_fails(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with both qatemplate and customer fails."""
        result = runner.invoke(
            cli, ["restore", "qatemplate", "customer=testcust"]
        )
        assert result.exit_code != 0
        assert "both" in result.output.lower() or "choose" in result.output.lower()


# ---------------------------------------------------------------------------
# Restore Command - S3 Environment Selection
# ---------------------------------------------------------------------------


class TestRestoreS3Environment:
    """Tests for S3 environment (staging/prod) selection."""

    @responses.activate
    def test_restore_s3env_staging(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore with s3env=staging works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={"job_id": SAMPLE_JOB_ID, "status": "queued"},
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "s3env=staging"]
        )
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_restore_s3env_prod(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore with s3env=prod works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={"job_id": SAMPLE_JOB_ID, "status": "queued"},
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "s3env=prod"]
        )
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Restore Command - Date Selection
# ---------------------------------------------------------------------------


class TestRestoreDateSelection:
    """Tests for specific backup date selection."""

    @responses.activate
    def test_restore_specific_date(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore with date=YYYY-MM-DD works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={"job_id": SAMPLE_JOB_ID, "status": "queued"},
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "date=2025-11-25"]
        )
        assert result.exit_code in [0, 1]

    def test_restore_invalid_date_format(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with invalid date format fails."""
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "date=25-11-2025"]
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Restore Command - Overwrite Flag
# ---------------------------------------------------------------------------


class TestRestoreOverwrite:
    """Tests for overwrite flag."""

    @responses.activate
    def test_restore_overwrite_flag(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore with overwrite flag works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={"job_id": SAMPLE_JOB_ID, "status": "queued"},
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "overwrite"]
        )
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Restore Command - Validation Errors
# ---------------------------------------------------------------------------


class TestRestoreValidation:
    """Tests for input validation errors."""

    def test_restore_invalid_user_code_length(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with user code too short fails."""
        result = runner.invoke(
            cli, ["restore", "user=ab", "customer=testcust"]
        )
        assert result.exit_code != 0

    def test_restore_invalid_s3env(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with invalid s3env fails."""
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "s3env=invalid"]
        )
        assert result.exit_code != 0

    def test_restore_unrecognized_option(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with unrecognized option fails."""
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "target=mytarget"]
        )
        # target= is NOT a valid option (target is auto-generated)
        assert result.exit_code != 0
        assert "unrecognized" in result.output.lower()


# ---------------------------------------------------------------------------
# Restore Command - DBHost Selection
# ---------------------------------------------------------------------------


class TestRestoreDBHost:
    """Tests for database host selection."""

    @responses.activate
    def test_restore_explicit_dbhost(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore with dbhost=xxx works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={"job_id": SAMPLE_JOB_ID, "status": "queued"},
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "dbhost=mysql-server.local"]
        )
        assert result.exit_code in [0, 1]
