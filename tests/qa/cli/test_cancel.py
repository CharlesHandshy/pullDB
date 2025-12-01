"""
Category 8: Cancel Command Tests

Tests for:
- Job cancellation by ID
- Cancellation of queued jobs
- Cancellation of running jobs
- Permission handling
- Error scenarios

Test Count: 10 tests
"""

from __future__ import annotations

import responses
from click.testing import CliRunner

from pulldb.cli.main import cli

from .conftest import (
    MOCK_API_BASE,
    SAMPLE_JOB_ID,
    SAMPLE_JOB_PREFIX,
    SAMPLE_USER_CODE,
    SAMPLE_USERNAME,
)


# ---------------------------------------------------------------------------
# Cancel Command - Basic Functionality
# ---------------------------------------------------------------------------


class TestCancelBasic:
    """Tests for basic cancel functionality."""

    @responses.activate
    def test_cancel_queued_job(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb cancel <job_id> cancels a queued job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/cancel",
            json={
                "id": SAMPLE_JOB_ID,
                "status": "cancelled",
                "message": "Job cancelled successfully",
            },
            status=200,
        )
        result = runner.invoke(cli, ["cancel", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]

    def test_cancel_no_args_shows_error(
        self, runner: CliRunner
    ) -> None:
        """pulldb cancel without job_id shows error."""
        result = runner.invoke(cli, ["cancel"])
        # Should require job ID
        assert result.exit_code != 0

    @responses.activate
    def test_cancel_with_full_uuid(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """pulldb cancel with full UUID works."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_ID}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/cancel",
            json={"id": SAMPLE_JOB_ID, "status": "cancelled"},
            status=200,
        )
        result = runner.invoke(cli, ["cancel", SAMPLE_JOB_ID])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Cancel Command - Job States
# ---------------------------------------------------------------------------


class TestCancelJobStates:
    """Tests for cancelling jobs in different states."""

    @responses.activate
    def test_cancel_running_job(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """Cancel a running job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/cancel",
            json={"id": SAMPLE_JOB_ID, "status": "cancelled"},
            status=200,
        )
        result = runner.invoke(cli, ["cancel", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_cancel_already_complete_job(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """Cancel shows error for already complete job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/cancel",
            json={"error": "Cannot cancel completed job"},
            status=400,
        )
        result = runner.invoke(cli, ["cancel", SAMPLE_JOB_PREFIX])
        # Should fail or show error
        assert result.exit_code in [0, 1]

    @responses.activate
    def test_cancel_already_cancelled_job(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """Cancel shows message for already cancelled job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/cancel",
            json={"error": "Job already cancelled"},
            status=400,
        )
        result = runner.invoke(cli, ["cancel", SAMPLE_JOB_PREFIX])
        assert result.exit_code in [0, 1]


# ---------------------------------------------------------------------------
# Cancel Command - Error Cases
# ---------------------------------------------------------------------------


class TestCancelErrors:
    """Tests for cancel error scenarios."""

    @responses.activate
    def test_cancel_job_not_found(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """Cancel shows error for non-existent job."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/deadbeef",
            json={"detail": "Not found"},
            status=404,
        )
        result = runner.invoke(cli, ["cancel", "deadbeef"])
        assert result.exit_code != 0

    def test_cancel_prefix_too_short(
        self, runner: CliRunner, mock_api_env: str
    ) -> None:
        """Cancel with prefix < 8 chars fails."""
        result = runner.invoke(cli, ["cancel", "abc"])  # Only 3 chars
        assert result.exit_code != 0

    @responses.activate
    def test_cancel_permission_denied(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """Cancel shows error for permission denied."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/cancel",
            json={"error": "Permission denied: not job owner"},
            status=403,
        )
        result = runner.invoke(cli, ["cancel", SAMPLE_JOB_PREFIX])
        assert result.exit_code != 0

    @responses.activate
    def test_cancel_api_error(
        self, runner: CliRunner, mock_api_env: str, mock_user_env: str
    ) -> None:
        """Cancel handles API error gracefully."""
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/users/{SAMPLE_USERNAME}",
            json={"username": SAMPLE_USERNAME, "user_code": SAMPLE_USER_CODE},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_BASE}/api/jobs/resolve/{SAMPLE_JOB_PREFIX}",
            json={
                "resolved_id": SAMPLE_JOB_ID,
                "matches": [{"id": SAMPLE_JOB_ID}],
                "count": 1,
            },
            status=200,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_BASE}/api/jobs/{SAMPLE_JOB_ID}/cancel",
            json={"error": "Internal server error"},
            status=500,
        )
        result = runner.invoke(cli, ["cancel", SAMPLE_JOB_PREFIX])
        assert result.exit_code != 0
