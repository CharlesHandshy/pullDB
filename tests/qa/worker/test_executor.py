"""Tests for pulldb.worker.executor module.

Tests job executor operations:
- Job directory preparation
- Backup discovery
- Download and extraction coordination
- Restore workflow execution
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulldb.domain.config import Config, S3BackupLocationConfig
from pulldb.domain.errors import (
    BackupDiscoveryError,
    CancellationError,
    DownloadError,
    ExtractionError,
)
from pulldb.domain.models import Job, JobStatus
from pulldb.worker.executor import (
    WorkerExecutorDependencies,
    WorkerExecutorHooks,
    WorkerExecutorTimeouts,
    WorkerJobExecutor,
    build_lookup_targets_for_location,
    derive_backup_lookup_target,
    extract_tar_archive,
)


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

SAMPLE_JOB_ID = "75777a4c-3dd9-48dd-b39c-62d8b35934da"
SAMPLE_TARGET = "charleqatemplate"
SAMPLE_USER_CODE = "charle"


# ---------------------------------------------------------------------------
# derive_backup_lookup_target Tests
# ---------------------------------------------------------------------------


class TestDeriveBackupLookupTarget:
    """Tests for derive_backup_lookup_target function."""

    @pytest.fixture
    def sample_job(self) -> MagicMock:
        """Create sample job mock."""
        job = MagicMock(spec=Job)
        job.id = SAMPLE_JOB_ID
        job.target = SAMPLE_TARGET
        job.owner_user_code = SAMPLE_USER_CODE
        job.options_json = {}
        return job

    def test_strips_user_code_prefix(self, sample_job: MagicMock) -> None:
        """Strips user_code prefix from target when no customer_id in options."""
        sample_job.target = "charleqatemplate"
        sample_job.owner_user_code = "charle"
        sample_job.options_json = {}  # No customer_id, fall back to prefix stripping

        result = derive_backup_lookup_target(sample_job)
        assert result == "qatemplate"

    def test_uses_customer_id_from_options(self, sample_job: MagicMock) -> None:
        """Uses customer_id from options_json as primary source."""
        sample_job.target = "charleantexzzz"  # target with user_code prefix and suffix
        sample_job.owner_user_code = "charle"
        sample_job.options_json = {"customer_id": "antex"}  # Clean customer name

        result = derive_backup_lookup_target(sample_job)
        # customer_id takes priority - returns clean customer name
        assert result == "antex"

    def test_customer_id_sanitized(self, sample_job: MagicMock) -> None:
        """customer_id is sanitized to lowercase alpha only."""
        sample_job.target = "charleqatemplate"
        sample_job.owner_user_code = "charle"
        sample_job.options_json = {"customer_id": "My-Customer-123"}

        result = derive_backup_lookup_target(sample_job)
        # Sanitized: lowercase, alpha only
        assert result == "mycustomer"

    def test_uses_qatemplate_for_is_qatemplate_flag(
        self, sample_job: MagicMock
    ) -> None:
        """Uses 'qatemplate' when is_qatemplate is true."""
        sample_job.target = "charleqatemplate"
        sample_job.owner_user_code = ""
        sample_job.options_json = {"is_qatemplate": "true"}

        result = derive_backup_lookup_target(sample_job)
        assert result == "qatemplate"

    def test_falls_back_to_target(self, sample_job: MagicMock) -> None:
        """Falls back to job.target when no other option."""
        sample_job.target = "mytarget"
        sample_job.owner_user_code = ""
        sample_job.options_json = {}

        result = derive_backup_lookup_target(sample_job)
        assert result == "mytarget"


# ---------------------------------------------------------------------------
# build_lookup_targets_for_location Tests
# ---------------------------------------------------------------------------


class TestBuildLookupTargetsForLocation:
    """Tests for build_lookup_targets_for_location function."""

    @pytest.fixture
    def sample_job(self) -> MagicMock:
        """Create sample job mock."""
        job = MagicMock(spec=Job)
        job.id = SAMPLE_JOB_ID
        job.target = SAMPLE_TARGET
        job.owner_user_code = SAMPLE_USER_CODE
        job.options_json = {}
        return job

    @pytest.fixture
    def sample_location(self) -> S3BackupLocationConfig:
        """Create sample location config."""
        return S3BackupLocationConfig(
            name="staging",
            bucket_path="s3://bucket/prefix/",
            bucket="bucket",
            prefix="prefix/",
            format_tag="legacy",
        )

    def test_returns_ordered_list(
        self, sample_job: MagicMock, sample_location: S3BackupLocationConfig
    ) -> None:
        """Returns ordered list of lookup targets."""
        result = build_lookup_targets_for_location(sample_job, sample_location)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_includes_base_target(
        self, sample_job: MagicMock, sample_location: S3BackupLocationConfig
    ) -> None:
        """Includes base target in candidates."""
        result = build_lookup_targets_for_location(sample_job, sample_location)
        # Should include derived target
        assert "qatemplate" in result or SAMPLE_TARGET in result


# ---------------------------------------------------------------------------
# extract_tar_archive Tests
# ---------------------------------------------------------------------------


class TestExtractTarArchive:
    """Tests for extract_tar_archive function."""

    def test_extracts_valid_archive(self, tmp_path: Path) -> None:
        """Extracts valid tar archive."""
        import tarfile

        # Create a test tar archive
        archive_path = tmp_path / "test.tar"
        extract_dir = tmp_path / "extract"

        # Create archive with test file
        src_file = tmp_path / "testfile.txt"
        src_file.write_text("test content")

        with tarfile.open(archive_path, "w") as tar:
            tar.add(src_file, arcname="testfile.txt")

        result = extract_tar_archive(str(archive_path), extract_dir, SAMPLE_JOB_ID)

        assert result == str(extract_dir)
        assert (extract_dir / "testfile.txt").exists()

    def test_creates_destination_directory(self, tmp_path: Path) -> None:
        """Creates destination directory if not exists."""
        import tarfile

        archive_path = tmp_path / "test.tar"
        extract_dir = tmp_path / "nested" / "extract"

        # Create empty archive
        with tarfile.open(archive_path, "w"):
            pass

        extract_tar_archive(str(archive_path), extract_dir, SAMPLE_JOB_ID)

        assert extract_dir.exists()

    def test_raises_for_invalid_archive(self, tmp_path: Path) -> None:
        """Raises ExtractionError for invalid archive."""
        archive_path = tmp_path / "invalid.tar"
        archive_path.write_text("not a tar file")
        extract_dir = tmp_path / "extract"

        with pytest.raises(ExtractionError):
            extract_tar_archive(str(archive_path), extract_dir, SAMPLE_JOB_ID)

    def test_emits_progress_callback(self, tmp_path: Path) -> None:
        """Progress callback is invoked during extraction with correct values."""
        import tarfile

        # Create archive with multiple files
        archive_path = tmp_path / "test.tar"
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        for i in range(10):
            (content_dir / f"file_{i}.txt").write_text("x" * 10000)

        with tarfile.open(archive_path, "w") as tar:
            for f in content_dir.iterdir():
                tar.add(f, arcname=f.name)

        progress_calls: list[tuple[int, int, float, float, int, int]] = []

        def callback(
            extracted: int,
            total: int,
            percent: float,
            elapsed: float,
            files_done: int,
            total_files: int,
        ) -> None:
            progress_calls.append((extracted, total, percent, elapsed, files_done, total_files))

        dest = tmp_path / "extracted"
        extract_tar_archive(str(archive_path), dest, SAMPLE_JOB_ID, callback)

        # Should have at least one progress callback (final completion)
        assert len(progress_calls) >= 1
        # Final call should show 100% complete
        final = progress_calls[-1]
        assert final[2] == 100.0  # percent
        assert final[4] == 10  # files_extracted
        assert final[5] == 10  # total_files

    def test_abort_raises_cancellation_error(self, tmp_path: Path) -> None:
        """Abort check triggers CancellationError during extraction."""
        import tarfile

        from pulldb.domain.errors import CancellationError

        # Create archive with multiple files
        archive_path = tmp_path / "test.tar"
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        for i in range(5):
            (content_dir / f"file_{i}.txt").write_text("test")

        with tarfile.open(archive_path, "w") as tar:
            for f in content_dir.iterdir():
                tar.add(f, arcname=f.name)

        call_count = [0]

        def abort_check() -> bool:
            # Abort is called before each file extraction
            # Abort after the 2nd call (i.e., after 1 file extracted)
            call_count[0] += 1
            return call_count[0] >= 3

        dest = tmp_path / "extracted"
        with pytest.raises(CancellationError):
            extract_tar_archive(
                str(archive_path), dest, SAMPLE_JOB_ID, None, abort_check
            )

    def test_progress_without_callback_succeeds(self, tmp_path: Path) -> None:
        """Extraction works without progress callback (backward compatible)."""
        import tarfile

        archive_path = tmp_path / "test.tar"
        src_file = tmp_path / "testfile.txt"
        src_file.write_text("test content")

        with tarfile.open(archive_path, "w") as tar:
            tar.add(src_file, arcname="testfile.txt")

        dest = tmp_path / "extracted"
        # Call without progress_callback or abort_check
        result = extract_tar_archive(str(archive_path), dest, SAMPLE_JOB_ID)

        assert result == str(dest)
        assert (dest / "testfile.txt").exists()


# ---------------------------------------------------------------------------
# WorkerExecutorDependencies Tests
# ---------------------------------------------------------------------------


class TestWorkerExecutorDependencies:
    """Tests for WorkerExecutorDependencies dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """Can create with required fields."""
        deps = WorkerExecutorDependencies(
            job_repo=MagicMock(),
            host_repo=MagicMock(),
            s3_client=MagicMock(),
        )
        assert deps.job_repo is not None
        assert deps.host_repo is not None
        assert deps.s3_client is not None


# ---------------------------------------------------------------------------
# WorkerExecutorTimeouts Tests
# ---------------------------------------------------------------------------


class TestWorkerExecutorTimeouts:
    """Tests for WorkerExecutorTimeouts dataclass."""

    def test_default_values(self) -> None:
        """Has sensible default timeouts."""
        timeouts = WorkerExecutorTimeouts()
        assert timeouts.staging_seconds == 7200
        assert timeouts.post_sql_seconds == 600

    def test_custom_values(self) -> None:
        """Can override timeouts."""
        timeouts = WorkerExecutorTimeouts(
            staging_seconds=3600,
            post_sql_seconds=300,
        )
        assert timeouts.staging_seconds == 3600
        assert timeouts.post_sql_seconds == 300


# ---------------------------------------------------------------------------
# WorkerJobExecutor Tests
# ---------------------------------------------------------------------------


class TestWorkerJobExecutor:
    """Tests for WorkerJobExecutor class."""

    @pytest.fixture
    def mock_config(self, tmp_path: Path) -> Config:
        """Create mock config."""
        config = Config.minimal_from_env()
        config.work_dir = str(tmp_path / "work")
        config.s3_bucket_path = "s3://test-bucket/backups/"
        config.myloader_binary = "/usr/bin/myloader"
        config.myloader_threads = 4
        config.myloader_timeout_seconds = 3600.0
        return config

    @pytest.fixture
    def mock_deps(self) -> WorkerExecutorDependencies:
        """Create mock dependencies."""
        return WorkerExecutorDependencies(
            job_repo=MagicMock(),
            host_repo=MagicMock(),
            s3_client=MagicMock(),
        )

    def test_creates_work_directory(
        self, mock_config: Config, mock_deps: WorkerExecutorDependencies
    ) -> None:
        """Creates work directory on init."""
        executor = WorkerJobExecutor(config=mock_config, deps=mock_deps)
        assert executor.work_dir.exists()

    def test_uses_config_work_dir(
        self, mock_config: Config, mock_deps: WorkerExecutorDependencies
    ) -> None:
        """Uses work_dir from config."""
        executor = WorkerJobExecutor(config=mock_config, deps=mock_deps)
        assert str(executor.work_dir) == mock_config.work_dir

    def test_callable_invokes_execute(
        self, mock_config: Config, mock_deps: WorkerExecutorDependencies
    ) -> None:
        """Executor is callable and invokes execute."""
        executor = WorkerJobExecutor(config=mock_config, deps=mock_deps)

        mock_job = MagicMock(spec=Job)
        mock_job.id = SAMPLE_JOB_ID

        with patch.object(executor, "execute") as mock_execute:
            executor(mock_job)
            mock_execute.assert_called_once_with(mock_job)

    def test_sets_backup_locations(
        self, mock_config: Config, mock_deps: WorkerExecutorDependencies
    ) -> None:
        """Parses backup locations from config."""
        executor = WorkerJobExecutor(config=mock_config, deps=mock_deps)
        assert len(executor.backup_locations) > 0

    def test_raises_without_backup_location(
        self, mock_deps: WorkerExecutorDependencies, tmp_path: Path
    ) -> None:
        """Raises ValueError without backup location config."""
        # Create a config with no backup locations configured
        config = Config(
            mysql_host="localhost",
            mysql_user="test",
            mysql_password="test",
            work_dir=tmp_path / "work",
            s3_bucket_path=None,
            s3_backup_locations=(),  # Empty - no backup locations
        )

        with pytest.raises(ValueError) as exc_info:
            WorkerJobExecutor(config=config, deps=mock_deps)
        assert "backup" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# WorkerExecutorHooks Tests
# ---------------------------------------------------------------------------


class TestWorkerExecutorHooks:
    """Tests for WorkerExecutorHooks dataclass."""

    def test_default_hooks_are_functions(self) -> None:
        """Default hooks are callable."""
        hooks = WorkerExecutorHooks()
        assert callable(hooks.discover_backup)
        assert callable(hooks.download_backup)
        assert callable(hooks.extract_archive)

    def test_custom_hooks(self) -> None:
        """Can provide custom hooks."""
        custom_discover = MagicMock()
        custom_download = MagicMock()
        custom_extract = MagicMock()

        hooks = WorkerExecutorHooks(
            discover_backup=custom_discover,
            download_backup=custom_download,
            extract_archive=custom_extract,
        )

        assert hooks.discover_backup is custom_discover
        assert hooks.download_backup is custom_download
        assert hooks.extract_archive is custom_extract
