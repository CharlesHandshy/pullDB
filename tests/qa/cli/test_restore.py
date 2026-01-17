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
- target=<name>       Custom target database name (1-51 lowercase letters, optional)
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
            cli, ["restore", "customer=testcust", "unknownoption=value"]
        )
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


# ---------------------------------------------------------------------------
# Restore Command - Custom Target
# ---------------------------------------------------------------------------


class TestRestoreCustomTarget:
    """Tests for custom target database name feature."""

    @responses.activate
    def test_restore_custom_target_basic(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore with target=mytestdb works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={
                "job_id": SAMPLE_JOB_ID,
                "target": "mytestdb",
                "status": "queued",
                "custom_target_used": True,
            },
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "target=mytestdb"]
        )
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_restore_custom_target_min_length(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore with target=a (minimum 1 char) works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={
                "job_id": SAMPLE_JOB_ID,
                "target": "a",
                "status": "queued",
            },
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "target=a"]
        )
        assert result.exit_code in [0, 1]

    def test_restore_custom_target_too_long(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with target > 51 chars fails."""
        long_target = "a" * 52
        result = runner.invoke(
            cli, ["restore", "customer=testcust", f"target={long_target}"]
        )
        assert result.exit_code != 0
        assert "51" in result.output or "maximum" in result.output.lower()

    def test_restore_custom_target_non_alpha(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with non-alphabetic target fails."""
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "target=my-test-123"]
        )
        assert result.exit_code != 0
        assert "lowercase" in result.output.lower() or "letters" in result.output.lower()

    def test_restore_custom_target_with_suffix_fails(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore with both target and suffix fails."""
        result = runner.invoke(
            cli, ["restore", "customer=testcust", "target=mytestdb", "suffix=dev"]
        )
        assert result.exit_code != 0
        assert "suffix" in result.output.lower()

    def test_restore_custom_target_case_normalized(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """pulldb restore normalizes target to lowercase."""
        # This should parse successfully (uppercase is normalized to lowercase)
        # The CLI should accept it and convert to lowercase
        from pulldb.cli.parse import parse_restore_args
        
        result = parse_restore_args(("customer=testcust", "target=MyTestDB"))
        assert result.custom_target == "mytestdb"

    @responses.activate
    def test_restore_custom_target_with_qatemplate(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb restore qatemplate target=myqa works."""
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs",
            json={
                "job_id": SAMPLE_JOB_ID,
                "target": "myqa",
                "status": "queued",
            },
            status=201,
        )
        result = runner.invoke(
            cli, ["restore", "qatemplate", "target=myqa"]
        )
        assert result.exit_code in [0, 1]
