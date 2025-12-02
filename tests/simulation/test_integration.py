"""Integration tests for Simulation Mode.

Verifies that the Simulation Engine and Mock Adapters work together to
execute a job using the real WorkerJobExecutor.
"""

import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from pulldb.domain.config import Config
from pulldb.domain.models import DBHost, Job, JobStatus
from pulldb.simulation.core.engine import SimulationEngine
from pulldb.worker.executor import WorkerJobExecutor

class TestSimulationIntegration(unittest.TestCase):
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
            mysql_password="mock"
        )

    def tearDown(self):
        shutil.rmtree(self.work_dir)

    def test_end_to_end_job_execution(self):
        # 1. Setup Environment
        # Add a host
        host = DBHost(
            id=1,
            hostname="localhost",
            host_alias="test-host",
            credential_ref="mock-creds",
            max_concurrent_restores=5,
            enabled=True,
            created_at=datetime.now(UTC)
        )
        self.engine.state.hosts["test-host"] = host
        
        # Add a backup to S3
        self.engine.s3.load_fixtures(
            "test-bucket", 
            ["backups/test-target/daily_mydumper_test-target_2023-10-27T12-00-00Z_Friday_dbimp.tar"]
        )
        
        # 2. Create and Enqueue Job
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
            submitted_at=datetime.now(UTC)
        )
        self.engine.job_repo.enqueue_job(job)
        
        # 3. Prepare Executor Dependencies
        class TestDependencies:
            def __init__(self, job_repo, host_repo, s3_client):
                self.job_repo = job_repo
                self.host_repo = host_repo
                self.s3_client = s3_client
                
        deps = TestDependencies(
            self.engine.job_repo,
            self.engine.host_repo,
            self.engine.s3
        )
        
        # 4. Initialize WorkerJobExecutor and Run
        # Patch run_command_streaming in pulldb.worker.restore to use our mock executor
        with patch(
            'pulldb.worker.restore.run_command_streaming', 
            side_effect=self.engine.executor.run_command_streaming
        ), patch('mysql.connector.connect') as mock_connect:
            
            # Configure mock MySQL connection
            mock_conn = mock_connect.return_value
            mock_cursor = mock_conn.cursor.return_value
            mock_cursor.rowcount = 0
            
            executor = WorkerJobExecutor(config=self.config, deps=deps)
            
            # We need to mock tarfile extraction because we provided dummy bytes
            with patch('tarfile.open'):
                executor(job)
        
        # 5. Verify Job Status
        updated_job = self.engine.state.jobs[job_id]
        self.assertEqual(updated_job.status, JobStatus.COMPLETE)
