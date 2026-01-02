"""
Worker Test Fixtures for pullDB QA Testing

Provides fixtures for:
- MySQL connection mocking
- S3 client mocking
- Job/Host repository mocking
- Sample data factories
- Worker configuration

Usage:
    pytest tests/qa/worker/ -v
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pulldb.domain.config import Config
from pulldb.domain.models import Job, JobStatus


# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"
SAMPLE_TARGET = "charleqatemplate"
SAMPLE_STAGING_NAME = "charleqatemplate_75777a4c3dd9"
SAMPLE_USER_CODE = "charle"
SAMPLE_USERNAME = "charleshandshy"
SAMPLE_DBHOST = "db-host-1.example.com"
SAMPLE_BUCKET = "test-backup-bucket"
SAMPLE_BACKUP_KEY = "daily/stg/qatemplate/backup-2025-01-15.tar"
SAMPLE_BACKUP_SIZE = 1024 * 1024 * 100  # 100 MB


# ---------------------------------------------------------------------------
# Config Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config() -> Config:
    """Create a mock Config object with test values."""
    config = Config.minimal_from_env()
    config.mysql_host = "localhost"
    config.mysql_user = "pulldb_worker"
    config.mysql_password = "test_password"
    config.mysql_database = "pulldb"
    config.work_dir = "/tmp/pulldb_test"
    config.myloader_binary = "/usr/bin/myloader"
    config.myloader_threads = 4
    config.myloader_timeout_seconds = 3600.0
    config.aws_profile = "test-profile"
    return config


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up worker environment variables."""
    monkeypatch.setenv("PULLDB_WORKER_MYSQL_USER", "pulldb_worker")
    monkeypatch.setenv("PULLDB_MYSQL_HOST", "localhost")
    monkeypatch.setenv("PULLDB_MYSQL_PASSWORD", "test_password")
    monkeypatch.setenv("PULLDB_MYSQL_DATABASE", "pulldb")


# ---------------------------------------------------------------------------
# Job Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_job() -> Job:
    """Create a sample job for testing."""
    return Job(
        id=SAMPLE_JOB_ID,
        owner_user_id="1",
        owner_username=SAMPLE_USERNAME,
        owner_user_code=SAMPLE_USER_CODE,
        target=SAMPLE_TARGET,
        dbhost=SAMPLE_DBHOST,
        staging_name=SAMPLE_STAGING_NAME,
        status=JobStatus.QUEUED,
        created_at=datetime.now(UTC),
        options_json={"customer_id": "qatemplate"},
    )


@pytest.fixture
def job_factory() -> Callable[..., Job]:
    """Factory for creating jobs with custom attributes."""
    def _create_job(
        job_id: str | None = None,
        status: JobStatus = JobStatus.QUEUED,
        target: str = SAMPLE_TARGET,
        dbhost: str = SAMPLE_DBHOST,
        **kwargs: Any,
    ) -> Job:
        return Job(
            id=job_id or str(uuid.uuid4()),
            owner_user_id=kwargs.get("owner_user_id", "1"),
            owner_username=kwargs.get("owner_username", SAMPLE_USERNAME),
            owner_user_code=kwargs.get("owner_user_code", SAMPLE_USER_CODE),
            target=target,
            dbhost=dbhost,
            staging_name=kwargs.get("staging_name", f"{target}_{'a' * 12}"),
            status=status,
            created_at=kwargs.get("created_at", datetime.now(UTC)),
            options_json=kwargs.get("options_json", {}),
        )
    return _create_job


# ---------------------------------------------------------------------------
# Repository Mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_job_repo() -> MagicMock:
    """Create a mock JobRepository."""
    mock = MagicMock()
    mock.claim_next_job.return_value = None
    mock.get_job.return_value = None
    mock.get_active_jobs.return_value = []
    mock.mark_job_running.return_value = None
    mock.mark_job_deployed.return_value = None
    mock.mark_job_failed.return_value = None
    mock.add_job_event.return_value = None
    return mock


@pytest.fixture
def mock_host_repo() -> MagicMock:
    """Create a mock HostRepository."""
    mock = MagicMock()
    mock.get_host_credentials.return_value = MagicMock(
        host=SAMPLE_DBHOST,
        port=3306,
        username="restore_user",
        password="restore_password",
    )
    mock.get_enabled_hosts.return_value = []
    return mock


@pytest.fixture
def mock_settings_repo() -> MagicMock:
    """Create a mock SettingsRepository."""
    mock = MagicMock()
    mock.get_setting.return_value = None
    mock.set_setting.return_value = None
    return mock


# ---------------------------------------------------------------------------
# S3 Mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_s3_client() -> MagicMock:
    """Create a mock S3Client."""
    mock = MagicMock()
    mock.list_objects.return_value = []
    mock.get_object.return_value = {
        "Body": MagicMock(),
        "ContentLength": SAMPLE_BACKUP_SIZE,
    }
    return mock


@pytest.fixture
def mock_backup_spec() -> MagicMock:
    """Create a mock BackupSpec."""
    mock = MagicMock()
    mock.bucket = SAMPLE_BUCKET
    mock.key = SAMPLE_BACKUP_KEY
    mock.filename = "backup-2025-01-15.tar"
    mock.size_bytes = SAMPLE_BACKUP_SIZE
    mock.profile = "test-profile"
    return mock


# ---------------------------------------------------------------------------
# MySQL Connection Mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mysql_connection() -> MagicMock:
    """Create a mock MySQL connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    return mock_conn


@pytest.fixture
def mock_mysql_connector(mock_mysql_connection: MagicMock) -> Generator:
    """Patch mysql.connector.connect to return mock connection."""
    with patch("mysql.connector.connect", return_value=mock_mysql_connection):
        yield mock_mysql_connection


# ---------------------------------------------------------------------------
# Staging Connection Specs
# ---------------------------------------------------------------------------


@pytest.fixture
def staging_conn_spec():
    """Create a StagingConnectionSpec for testing."""
    from pulldb.worker.staging import StagingConnectionSpec
    return StagingConnectionSpec(
        mysql_host=SAMPLE_DBHOST,
        mysql_port=3306,
        mysql_user="restore_user",
        mysql_password="restore_password",
        timeout_seconds=300,
    )


@pytest.fixture
def post_sql_conn_spec():
    """Create a PostSQLConnectionSpec for testing."""
    from pulldb.worker.post_sql import PostSQLConnectionSpec
    return PostSQLConnectionSpec(
        mysql_host=SAMPLE_DBHOST,
        mysql_port=3306,
        mysql_user="restore_user",
        mysql_password="restore_password",
        timeout_seconds=600,
        script_dir="/opt/pulldb/post_sql",
    )


# ---------------------------------------------------------------------------
# Filesystem Mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_disk_usage() -> Generator:
    """Mock shutil.disk_usage to return sufficient space."""
    mock_usage = MagicMock()
    mock_usage.free = 100 * 1024 * 1024 * 1024  # 100 GB
    with patch("shutil.disk_usage", return_value=mock_usage):
        yield mock_usage


@pytest.fixture
def temp_work_dir(tmp_path) -> str:
    """Create a temporary work directory."""
    work_dir = tmp_path / "pulldb_work"
    work_dir.mkdir()
    return str(work_dir)


# ---------------------------------------------------------------------------
# Process Mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_subprocess() -> Generator:
    """Mock subprocess.run for command execution."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


# ---------------------------------------------------------------------------
# Credential Mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_credentials() -> MagicMock:
    """Create mock MySQL credentials."""
    mock = MagicMock()
    mock.host = SAMPLE_DBHOST
    mock.port = 3306
    mock.username = "restore_user"
    mock.password = "restore_password"
    return mock


@pytest.fixture
def mock_credential_resolver(mock_credentials: MagicMock) -> Generator:
    """Patch CredentialResolver to return mock credentials."""
    with patch("pulldb.infra.secrets.CredentialResolver") as mock_cls:
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_credentials
        mock_cls.return_value = mock_resolver
        yield mock_resolver


# ---------------------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------------------


def create_mock_job_event(
    event_type: str = "status_change",
    detail: str | dict | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock job event."""
    mock = MagicMock()
    mock.event_type = event_type
    mock.detail = detail if isinstance(detail, str) else (
        detail if detail else "{}"
    )
    mock.created_at = created_at or datetime.now(UTC)
    return mock


def create_mock_cleanup_result(
    dbhost: str = SAMPLE_DBHOST,
    jobs_processed: int = 0,
    databases_dropped: int = 0,
    errors: list[str] | None = None,
) -> MagicMock:
    """Create a mock CleanupResult."""
    mock = MagicMock()
    mock.dbhost = dbhost
    mock.jobs_processed = jobs_processed
    mock.databases_dropped = databases_dropped
    mock.databases_not_found = 0
    mock.databases_skipped = 0
    mock.jobs_archived = 0
    mock.errors = errors or []
    mock.dropped_names = []
    return mock
