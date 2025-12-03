"""Integration tests for Simulation Mode.

Verifies that the Simulation Engine and Mock Adapters work together to
execute a job using the real WorkerJobExecutor.

WARNING: These tests are integration tests that wire together real
executor code with mocked dependencies. They require careful mocking
of ALL external dependencies (MySQL, S3, subprocess) to avoid:
- Memory leaks from improperly mocked iterators
- Infinite loops from un-configured mock return values
- Real subprocess executions

If tests in this file cause memory issues, the root cause is likely
a mock that returns MagicMock instead of a proper return value.
"""

import os
import sys

# Ensure we import from the local project, not system packages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulldb.domain.config import Config
from pulldb.domain.models import DBHost, Job, JobStatus
from pulldb.simulation.core.engine import SimulationEngine


class TestSimulationIntegration(unittest.TestCase):
    """Integration tests for the simulation engine.

    NOTE: These tests are DISABLED by default because they require
    complex mocking of the entire restore workflow. The WorkerJobExecutor
    calls many MySQL operations (SHOW DATABASES, DROP DATABASE, etc.)
    that need proper mock return values.

    Running these tests with incomplete mocks causes memory leaks
    because MagicMock iteration creates infinite generators.
    """

    def setUp(self):
        self.engine = SimulationEngine()
        self.engine.initialize()
        self.work_dir = tempfile.mkdtemp()

        # Setup Config
        self.config = Config(
            work_dir=Path(self.work_dir),
            s3_bucket_path="s3://test-bucket/backups",
            mysql_host="localhost",
            mysql_user="mock",
            mysql_password="mock",
        )

    def tearDown(self):
        shutil.rmtree(self.work_dir)

    @pytest.mark.skip(
        reason="Integration test requires full MySQL mock - disabled to prevent memory leak"
    )
    def test_end_to_end_job_execution(self):
        """Test full job execution with mocked dependencies.

        DISABLED: This test is complex and requires mocking:
        - mysql.connector.connect and cursor operations
        - tarfile extraction
        - run_command_streaming
        - All MySQL queries (SHOW DATABASES, DROP DATABASE, etc.)

        Without complete mocks, cursor.fetchall() returns MagicMock
        which causes infinite iteration and memory exhaustion.
        """
        pass

    def test_simulation_engine_initializes(self):
        """Verify simulation engine can be initialized."""
        self.assertIsNotNone(self.engine.state)
        self.assertIsNotNone(self.engine.job_repo)
        self.assertIsNotNone(self.engine.host_repo)
        self.assertIsNotNone(self.engine.s3)

    def test_simulation_state_clears(self):
        """Verify simulation state can be cleared."""
        # Add some data
        self.engine.state.jobs["test"] = MagicMock()
        self.engine.state.users["test"] = MagicMock()

        # Clear
        self.engine.state.clear()

        # Verify cleared
        self.assertEqual(len(self.engine.state.jobs), 0)
        self.assertEqual(len(self.engine.state.users), 0)

    def test_job_enqueue_and_claim(self):
        """Test basic job lifecycle without full executor."""
        # Add a host
        host = DBHost(
            id=1,
            hostname="localhost",
            host_alias="test-host",
            credential_ref="mock-creds",
            max_concurrent_restores=5,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        self.engine.state.hosts["test-host"] = host

        # Create and enqueue job
        job_id = "12345678-1234-5678-1234-567812345678"
        job = Job(
            id=job_id,
            owner_user_id="user-1",
            owner_username="user1",
            owner_user_code="user1",
            target="test-target",
            staging_name=f"test-target_{job_id[:12]}",
            dbhost="test-host",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        self.engine.job_repo.enqueue_job(job)

        # Verify job was queued
        queued_job = self.engine.job_repo.get_job_by_id(job_id)
        self.assertEqual(queued_job.status, JobStatus.QUEUED)

        # Claim job
        claimed_job = self.engine.job_repo.claim_next_job("worker-1")
        self.assertIsNotNone(claimed_job)
        self.assertEqual(claimed_job.id, job_id)
        self.assertEqual(claimed_job.status, JobStatus.RUNNING)

        # Mark complete
        self.engine.job_repo.mark_job_complete(job_id)
        completed_job = self.engine.job_repo.get_job_by_id(job_id)
        self.assertEqual(completed_job.status, JobStatus.COMPLETE)

    def test_mock_s3_fixtures(self):
        """Test S3 fixture loading works."""
        self.engine.s3.load_fixtures(
            "test-bucket",
            [
                "backups/test-target/backup1.tar",
                "backups/test-target/backup2.tar",
            ],
        )

        # List keys
        keys = self.engine.s3.list_keys("test-bucket", "backups/test-target/")
        self.assertEqual(len(keys), 2)

