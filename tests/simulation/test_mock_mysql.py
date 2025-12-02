"""Tests for Mock MySQL repositories."""

import unittest
from datetime import UTC, datetime, timedelta

from pulldb.domain.models import Job, JobStatus
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedHostRepository,
    SimulatedJobRepository,
    SimulatedSettingsRepository,
    SimulatedUserRepository,
)
from pulldb.simulation.core.state import get_simulation_state


class TestMockRepositories(unittest.TestCase):
    def setUp(self):
        self.state = get_simulation_state()
        self.state.clear()
        
        self.job_repo = SimulatedJobRepository()
        self.user_repo = SimulatedUserRepository()
        self.host_repo = SimulatedHostRepository()
        self.settings_repo = SimulatedSettingsRepository()

    def test_user_creation(self):
        user = self.user_repo.create_user("testuser", "test01")
        self.assertIsNotNone(user.user_id)
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.user_code, "test01")
        
        fetched = self.user_repo.get_user_by_username("testuser")
        self.assertEqual(fetched, user)

    def test_job_lifecycle(self):
        user = self.user_repo.create_user("testuser", "test01")
        
        job = Job(
            id="job-123",
            owner_user_id=user.user_id,
            owner_username=user.username,
            owner_user_code=user.user_code,
            target="test01_db",
            staging_name="test01_db_staging",
            dbhost="db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        
        self.job_repo.enqueue_job(job)
        self.assertEqual(self.job_repo.get_job_by_id("job-123"), job)
        
        # Claim job
        claimed = self.job_repo.claim_next_job("worker-1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, "job-123")
        self.assertEqual(claimed.status, JobStatus.RUNNING)
        self.assertEqual(claimed.worker_id, "worker-1")
        
        # Complete job
        self.job_repo.mark_job_complete("job-123")
        completed = self.job_repo.get_job_by_id("job-123")
        self.assertEqual(completed.status, JobStatus.COMPLETE)
        self.assertIsNotNone(completed.completed_at)

    def test_host_management(self):
        self.host_repo.add_host("db-01", 5, None)
        host = self.host_repo.get_host_by_hostname("db-01")
        self.assertIsNotNone(host)
        self.assertTrue(host.enabled)
        
        self.host_repo.disable_host("db-01")
        host = self.host_repo.get_host_by_hostname("db-01")
        self.assertFalse(host.enabled)

    def test_settings(self):
        self.settings_repo.set_setting("foo", "bar")
        self.assertEqual(self.settings_repo.get_setting("foo"), "bar")
        
        with self.assertRaises(ValueError):
            self.settings_repo.get_setting_required("missing")

    def test_target_exclusivity(self):
        user = self.user_repo.create_user("testuser", "test01")
        
        job1 = Job(
            id="job-1",
            owner_user_id=user.user_id,
            owner_username=user.username,
            owner_user_code=user.user_code,
            target="target_db",
            staging_name="staging_1",
            dbhost="db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        
        job2 = Job(
            id="job-2",
            owner_user_id=user.user_id,
            owner_username=user.username,
            owner_user_code=user.user_code,
            target="target_db",  # Same target
            staging_name="staging_2",
            dbhost="db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        
        self.job_repo.enqueue_job(job1)
        self.job_repo.enqueue_job(job2)
        
        # Claim first job
        claimed1 = self.job_repo.claim_next_job("worker-1")
        self.assertEqual(claimed1.id, "job-1")
        
        # Try to claim second job (should fail due to exclusivity)
        claimed2 = self.job_repo.claim_next_job("worker-2")
        self.assertIsNone(claimed2)
        
        # Complete first job
        self.job_repo.mark_job_complete("job-1")
        
        # Now second job should be claimable
        claimed2 = self.job_repo.claim_next_job("worker-2")
        self.assertIsNotNone(claimed2)
        self.assertEqual(claimed2.id, "job-2")
