"""Tests for Mock MySQL repositories."""

import os
import sys

# Ensure we import from the local project, not system packages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import unittest
from datetime import UTC, datetime, timedelta

from pulldb.domain.models import Job, JobStatus
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedHostRepository,
    SimulatedJobRepository,
    SimulatedSettingsRepository,
    SimulatedUserRepository,
)
from pulldb.simulation.core.state import get_simulation_state, reset_simulation


class TestMockRepositories(unittest.TestCase):
    def setUp(self):
        reset_simulation()
        self.state = get_simulation_state()
        
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
        
        # Deploy job
        self.job_repo.mark_job_deployed("job-123")
        deployed = self.job_repo.get_job_by_id("job-123")
        self.assertEqual(deployed.status, JobStatus.DEPLOYED)
        self.assertIsNotNone(deployed.completed_at)

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
        
        # Deploy first job
        self.job_repo.mark_job_deployed("job-1")
        
        # Now second job should be claimable
        claimed2 = self.job_repo.claim_next_job("worker-2")
        self.assertIsNotNone(claimed2)
        self.assertEqual(claimed2.id, "job-2")


class TestPruneJobEvents(unittest.TestCase):
    """Tests for job event pruning methods."""

    def setUp(self):
        reset_simulation()
        self.state = get_simulation_state()
        self.job_repo = SimulatedJobRepository()
        self.user_repo = SimulatedUserRepository()

    def _create_job(self, job_id: str, status: JobStatus) -> Job:
        """Helper to create a test job."""
        user = self.user_repo.get_user_by_username("testuser")
        if not user:
            user = self.user_repo.create_user("testuser", "test01")
        
        job = Job(
            id=job_id,
            owner_user_id=user.user_id,
            owner_username=user.username,
            owner_user_code=user.user_code,
            target="test_db",
            staging_name=f"staging_{job_id}",
            dbhost="db-01",
            status=status,
            submitted_at=datetime.now(UTC) - timedelta(days=100),
            completed_at=datetime.now(UTC) - timedelta(days=95) if status != JobStatus.RUNNING else None,
        )
        self.state.jobs[job_id] = job
        return job

    def _add_old_event(self, job_id: str, event_type: str, days_ago: int):
        """Helper to add an event with a specific age."""
        from pulldb.domain.models import JobEvent
        event = JobEvent(
            id=len(self.state.job_events) + 1,
            job_id=job_id,
            event_type=event_type,
            detail=f"Test event {event_type}",
            logged_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
        self.state.job_events.append(event)
        return event

    def test_get_prune_candidates_returns_old_terminal_jobs(self):
        """get_prune_candidates should return jobs with events older than retention."""
        # Create terminal jobs with old events
        self._create_job("job-old-complete", JobStatus.COMPLETE)
        self._add_old_event("job-old-complete", "queued", 100)
        self._add_old_event("job-old-complete", "complete", 95)

        self._create_job("job-old-failed", JobStatus.FAILED)
        self._add_old_event("job-old-failed", "queued", 100)
        self._add_old_event("job-old-failed", "failed", 95)

        # Create running job (should NOT be included)
        self._create_job("job-running", JobStatus.RUNNING)
        self._add_old_event("job-running", "queued", 100)

        result = self.job_repo.get_prune_candidates(retention_days=90)

        self.assertEqual(result["totalCount"], 2)
        self.assertEqual(result["totalEvents"], 4)
        job_ids = {row["job_id"] for row in result["rows"]}
        self.assertIn("job-old-complete", job_ids)
        self.assertIn("job-old-failed", job_ids)
        self.assertNotIn("job-running", job_ids)

    def test_get_prune_candidates_excludes_recent_events(self):
        """get_prune_candidates should not include jobs with only recent events."""
        # Create job with recent events only
        self._create_job("job-recent", JobStatus.COMPLETE)
        self._add_old_event("job-recent", "queued", 30)  # Only 30 days old
        self._add_old_event("job-recent", "complete", 30)

        result = self.job_repo.get_prune_candidates(retention_days=90)

        self.assertEqual(result["totalCount"], 0)
        self.assertEqual(result["totalEvents"], 0)

    def test_get_prune_candidates_pagination(self):
        """get_prune_candidates should support pagination."""
        # Create 5 jobs with old events
        for i in range(5):
            self._create_job(f"job-{i}", JobStatus.COMPLETE)
            self._add_old_event(f"job-{i}", "complete", 100 + i)

        # Page 1
        result1 = self.job_repo.get_prune_candidates(retention_days=90, offset=0, limit=2)
        self.assertEqual(len(result1["rows"]), 2)
        self.assertEqual(result1["totalCount"], 5)

        # Page 2
        result2 = self.job_repo.get_prune_candidates(retention_days=90, offset=2, limit=2)
        self.assertEqual(len(result2["rows"]), 2)

        # Ensure no overlap
        ids1 = {r["job_id"] for r in result1["rows"]}
        ids2 = {r["job_id"] for r in result2["rows"]}
        self.assertEqual(len(ids1 & ids2), 0)

    def test_prune_job_events_by_ids_deletes_all_events(self):
        """prune_job_events_by_ids should delete ALL events for specified jobs."""
        # Create jobs with events
        self._create_job("job-to-delete", JobStatus.COMPLETE)
        self._add_old_event("job-to-delete", "queued", 100)
        self._add_old_event("job-to-delete", "complete", 95)

        self._create_job("job-to-keep", JobStatus.COMPLETE)
        self._add_old_event("job-to-keep", "queued", 100)
        self._add_old_event("job-to-keep", "complete", 95)

        # Initial counts
        self.assertEqual(len(self.state.job_events), 4)

        # Delete events for one job
        deleted = self.job_repo.prune_job_events_by_ids(["job-to-delete"])

        self.assertEqual(deleted, 2)
        self.assertEqual(len(self.state.job_events), 2)
        
        # Verify correct events remain
        remaining_job_ids = {e.job_id for e in self.state.job_events}
        self.assertNotIn("job-to-delete", remaining_job_ids)
        self.assertIn("job-to-keep", remaining_job_ids)

    def test_prune_job_events_by_ids_cascades_to_get_job_events(self):
        """After pruning, get_job_events should return empty for pruned jobs."""
        self._create_job("job-pruned", JobStatus.COMPLETE)
        self._add_old_event("job-pruned", "queued", 100)
        self._add_old_event("job-pruned", "complete", 95)

        # Before prune
        events_before = self.job_repo.get_job_events("job-pruned")
        self.assertEqual(len(events_before), 2)

        # Prune
        self.job_repo.prune_job_events_by_ids(["job-pruned"])

        # After prune - cascade effect visible
        events_after = self.job_repo.get_job_events("job-pruned")
        self.assertEqual(len(events_after), 0)

    def test_prune_job_events_excluding_preserves_excluded(self):
        """prune_job_events_excluding should preserve events for excluded jobs."""
        # Create jobs with old events
        self._create_job("job-exclude", JobStatus.COMPLETE)
        self._add_old_event("job-exclude", "queued", 100)
        self._add_old_event("job-exclude", "complete", 95)

        self._create_job("job-delete", JobStatus.COMPLETE)
        self._add_old_event("job-delete", "queued", 100)
        self._add_old_event("job-delete", "complete", 95)

        # Prune excluding one job
        deleted = self.job_repo.prune_job_events_excluding(
            retention_days=90,
            exclude_job_ids=["job-exclude"],
        )

        self.assertEqual(deleted, 2)
        
        # Verify excluded job still has events
        events_excluded = self.job_repo.get_job_events("job-exclude")
        self.assertEqual(len(events_excluded), 2)

        # Verify non-excluded job has no events
        events_deleted = self.job_repo.get_job_events("job-delete")
        self.assertEqual(len(events_deleted), 0)

    def test_prune_job_events_excluding_ignores_running_jobs(self):
        """prune_job_events_excluding should not delete events for running jobs."""
        # Create running job with old events
        self._create_job("job-running", JobStatus.RUNNING)
        self._add_old_event("job-running", "queued", 100)

        # Prune with no exclusions
        deleted = self.job_repo.prune_job_events_excluding(retention_days=90)

        self.assertEqual(deleted, 0)
        events = self.job_repo.get_job_events("job-running")
        self.assertEqual(len(events), 1)

    def test_prune_job_events_by_ids_empty_list(self):
        """prune_job_events_by_ids with empty list should delete nothing."""
        self._create_job("job-1", JobStatus.COMPLETE)
        self._add_old_event("job-1", "complete", 100)

        deleted = self.job_repo.prune_job_events_by_ids([])
        
        self.assertEqual(deleted, 0)
        self.assertEqual(len(self.state.job_events), 1)

    def test_prune_multiple_jobs_at_once(self):
        """prune_job_events_by_ids should handle multiple job IDs."""
        for i in range(5):
            self._create_job(f"job-{i}", JobStatus.COMPLETE)
            self._add_old_event(f"job-{i}", "complete", 100)

        # Delete 3 of 5
        deleted = self.job_repo.prune_job_events_by_ids(["job-0", "job-2", "job-4"])

        self.assertEqual(deleted, 3)
        self.assertEqual(len(self.state.job_events), 2)
        
        remaining_job_ids = {e.job_id for e in self.state.job_events}
        self.assertEqual(remaining_job_ids, {"job-1", "job-3"})


class TestCleanupStagingDatabases(unittest.TestCase):
    """Tests for cleanup-staging mock functionality."""

    def setUp(self):
        """Reset simulation state before each test."""
        reset_simulation()
        self.state = get_simulation_state()
        
        # Create repositories
        self.job_repo = SimulatedJobRepository()
        self.user_repo = SimulatedUserRepository()
        
        # Create a test user
        self.user = self.user_repo.create_user("testuser", "TU01")

    def _create_job_with_staging(self, job_id: str, status: JobStatus, days_ago: int, target: str = "test_db") -> Job:
        """Helper to create a job with staging database and completion time."""
        from dataclasses import replace
        job = Job(
            id=job_id,
            owner_user_id=self.user.user_id,
            owner_username=self.user.username,
            owner_user_code=self.user.user_code,
            target=target,
            staging_name=f"staging_{job_id}",
            dbhost="db-01",
            status=status,
            submitted_at=datetime.now(UTC) - timedelta(days=days_ago + 5),
            completed_at=datetime.now(UTC) - timedelta(days=days_ago) if status != JobStatus.RUNNING else None,
        )
        self.state.jobs[job_id] = job
        return job

    def test_get_cleanup_candidates_returns_old_terminal_jobs(self):
        """get_cleanup_candidates should return terminal jobs with staging_name."""
        # Create terminal job with staging
        self._create_job_with_staging("job-old-complete", JobStatus.COMPLETE, days_ago=30)
        
        # Create running job with DIFFERENT target (safety check shouldn't block the terminal job)
        self._create_job_with_staging("job-running", JobStatus.RUNNING, days_ago=30, target="other_db")

        result = self.job_repo.get_cleanup_candidates(retention_days=7)

        self.assertEqual(result["totalCount"], 1)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["database_name"], "staging_job-old-complete")

    def test_get_cleanup_candidates_excludes_recently_completed_jobs(self):
        """get_cleanup_candidates should exclude jobs completed within retention period."""
        # Create job completed recently
        self._create_job_with_staging("job-recent", JobStatus.COMPLETE, days_ago=3)

        result = self.job_repo.get_cleanup_candidates(retention_days=7)

        self.assertEqual(result["totalCount"], 0)

    def test_get_cleanup_candidates_excludes_already_cleaned(self):
        """get_cleanup_candidates should exclude jobs already cleaned."""
        from dataclasses import replace
        job = self._create_job_with_staging("job-cleaned", JobStatus.COMPLETE, days_ago=30)
        # Mark as already cleaned
        self.state.jobs[job.id] = replace(job, staging_cleaned_at=datetime.now(UTC))

        result = self.job_repo.get_cleanup_candidates(retention_days=7)

        self.assertEqual(result["totalCount"], 0)

    def test_cleanup_staging_by_names_marks_cleaned(self):
        """cleanup_staging_by_names should mark jobs as cleaned."""
        job = self._create_job_with_staging("job-to-clean", JobStatus.COMPLETE, days_ago=30)
        
        result = self.job_repo.cleanup_staging_by_names(
            database_names=["staging_job-to-clean"]
        )

        self.assertEqual(result["dropped_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        
        # Verify job is marked as cleaned
        updated_job = self.state.jobs[job.id]
        self.assertIsNotNone(updated_job.staging_cleaned_at)

    def test_cleanup_staging_by_names_skips_active_jobs(self):
        """cleanup_staging_by_names should skip active jobs."""
        self._create_job_with_staging("job-running", JobStatus.RUNNING, days_ago=0)

        result = self.job_repo.cleanup_staging_by_names(
            database_names=["staging_job-running"]
        )

        self.assertEqual(result["dropped_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        
        # Verify job is NOT marked as cleaned
        job = self.state.jobs["job-running"]
        self.assertIsNone(job.staging_cleaned_at)

    def test_cleanup_staging_by_names_unknown_database(self):
        """cleanup_staging_by_names should handle unknown database names gracefully."""
        result = self.job_repo.cleanup_staging_by_names(
            database_names=["nonexistent_staging"]
        )

        self.assertEqual(result["dropped_count"], 0)
        self.assertEqual(result["skipped_count"], 0)

    def test_cleanup_staging_by_names_mixed_results(self):
        """cleanup_staging_by_names should handle mix of cleanable and skippable."""
        # Terminal job (cleanable) - uses target1
        self._create_job_with_staging("job-terminal", JobStatus.COMPLETE, days_ago=30, target="target1")
        # Running job (should skip) - uses target2, so won't block target1's cleanup
        self._create_job_with_staging("job-running", JobStatus.RUNNING, days_ago=0, target="target2")

        result = self.job_repo.cleanup_staging_by_names(
            database_names=["staging_job-terminal", "staging_job-running"]
        )

        self.assertEqual(result["dropped_count"], 1)
        self.assertEqual(result["skipped_count"], 1)

    def test_mark_job_staging_cleaned_updates_timestamp(self):
        """mark_job_staging_cleaned should set staging_cleaned_at."""
        job = self._create_job_with_staging("job-1", JobStatus.COMPLETE, days_ago=30)
        
        self.job_repo.mark_job_staging_cleaned(job.id)

        updated_job = self.state.jobs[job.id]
        self.assertIsNotNone(updated_job.staging_cleaned_at)


class TestSimulatedUserRepositoryDelete(unittest.TestCase):
    """Tests for delete_user functionality in SimulatedUserRepository."""

    def setUp(self):
        reset_simulation()
        self.state = get_simulation_state()
        self.user_repo = SimulatedUserRepository()
        self.job_repo = SimulatedJobRepository()

    def test_delete_user_no_jobs(self):
        """Can delete user with no job history."""
        user = self.user_repo.create_user("deletable_user", "dltabl")
        
        result = self.user_repo.delete_user(user.user_id)
        
        self.assertEqual(result["user_deleted"], 1)
        self.assertIsNone(self.user_repo.get_user_by_id(user.user_id))

    def test_delete_user_with_jobs_fails(self):
        """Cannot delete user with job history."""
        user = self.user_repo.create_user("user_with_jobs", "usrjob")
        
        # Create a job for this user
        job = Job(
            id="job-for-delete-test",
            owner_user_id=user.user_id,
            owner_username=user.username,
            owner_user_code=user.user_code,
            target="test_db",
            staging_name="staging_test",
            dbhost="localhost",
            status=JobStatus.COMPLETE,
            submitted_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.state.jobs[job.id] = job
        
        with self.assertRaises(ValueError) as ctx:
            self.user_repo.delete_user(user.user_id)
        
        self.assertIn("job(s) in history", str(ctx.exception))
        # User should still exist
        self.assertIsNotNone(self.user_repo.get_user_by_id(user.user_id))

    def test_delete_user_not_found(self):
        """Delete non-existent user raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.user_repo.delete_user("non-existent-id")
        
        self.assertIn("not found", str(ctx.exception))

    def test_delete_user_clears_manager_relationships(self):
        """Deleting a manager clears manager_id for their managed users."""
        manager = self.user_repo.create_user("manager_user", "mngrus")
        subordinate = self.user_repo.create_user("subordinate_user", "subord")
        
        # Set manager relationship
        self.user_repo.set_user_manager(subordinate.user_id, manager.user_id)
        
        # Verify relationship exists
        updated_sub = self.user_repo.get_user_by_id(subordinate.user_id)
        self.assertEqual(updated_sub.manager_id, manager.user_id)
        
        # Delete manager
        result = self.user_repo.delete_user(manager.user_id)
        
        self.assertEqual(result["managed_users_updated"], 1)
        
        # Verify subordinate's manager_id is cleared
        updated_sub = self.user_repo.get_user_by_id(subordinate.user_id)
        self.assertIsNone(updated_sub.manager_id)


class TestOrphanDetectionSimulation(unittest.TestCase):
    """Tests for orphan detection simulation bug fix.
    
    CRITICAL: This tests the fix for the bug where running jobs
    were incorrectly classified as orphans in simulation mode.
    
    The fix ensures _detect_orphaned_databases_simulation() checks
    if a matching job exists before classifying a database as orphan,
    matching production behavior.
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        reset_simulation()
        self.state = get_simulation_state()
        
        self.job_repo = SimulatedJobRepository()
        self.user_repo = SimulatedUserRepository()
        
        # Create a test user
        self.user = self.user_repo.create_user("testuser", "test01")
        
        # Set simulation mode
        import os
        os.environ["PULLDB_SIMULATION"] = "1"

    def tearDown(self) -> None:
        """Clean up after tests."""
        import os
        os.environ.pop("PULLDB_SIMULATION", None)
        # Full reset ensures event bus and scenario manager are also cleaned
        reset_simulation()

    def test_staging_database_with_active_job_not_orphan(self) -> None:
        """A staging database WITH an active job should NOT be classified as orphan.
        
        This was the bug: simulation didn't check for matching jobs.
        """
        from pulldb.worker.cleanup import _detect_orphaned_databases_simulation
        
        dbhost = "mysql-staging-01.example.com"
        target = "devusrtestdb"
        job_id = "abc123def456-7890-abcd-ef12-345678901234"
        job_prefix = job_id[:12]  # "abc123def456"
        staging_name = f"{target}_{job_prefix}"
        
        # Add staging database to simulation state
        self.state.staging_databases[dbhost] = {staging_name}
        
        # Create a RUNNING job for this staging database
        job = Job(
            id=job_id,
            owner_user_id=self.user.user_id,
            owner_username=self.user.username,
            owner_user_code=self.user.user_code,
            target=target,
            staging_name=staging_name,
            dbhost=dbhost,
            status=JobStatus.RUNNING,
            submitted_at=datetime.now(UTC),
        )
        self.state.jobs[job_id] = job
        
        # Detect orphans - this database should NOT be an orphan
        report = _detect_orphaned_databases_simulation(dbhost)
        
        assert not isinstance(report, str), f"Expected OrphanReport, got error: {report}"
        self.assertEqual(len(report.orphans), 0, 
            "Database with active job should not be classified as orphan")

    def test_staging_database_without_job_is_orphan(self) -> None:
        """A staging database WITHOUT any job should be classified as orphan."""
        from pulldb.worker.cleanup import _detect_orphaned_databases_simulation
        
        dbhost = "mysql-staging-01.example.com"
        target = "devusrorphandb"
        job_prefix = "999888777666"
        staging_name = f"{target}_{job_prefix}"
        
        # Add staging database to simulation state (but NO matching job)
        self.state.staging_databases[dbhost] = {staging_name}
        
        # Detect orphans - this database SHOULD be an orphan
        report = _detect_orphaned_databases_simulation(dbhost)
        
        assert not isinstance(report, str), f"Expected OrphanReport, got error: {report}"
        self.assertEqual(len(report.orphans), 1,
            "Database without job should be classified as orphan")
        self.assertEqual(report.orphans[0].database_name, staging_name)
        self.assertEqual(report.orphans[0].target_name, target)

    def test_mixed_staging_databases(self) -> None:
        """Mixed scenario: some databases have jobs, some don't."""
        from pulldb.worker.cleanup import _detect_orphaned_databases_simulation
        
        dbhost = "mysql-staging-01.example.com"
        
        # Database 1: Has active job - NOT orphan
        target1 = "devusractivejob"
        job_id1 = "aaa111bbb222-7890-abcd-ef12-345678901234"
        staging1 = f"{target1}_{job_id1[:12]}"
        
        # Database 2: No job - IS orphan
        target2 = "devusrnojoborg"
        staging2 = f"{target2}_ccc333ddd444"
        
        # Database 3: Has COMPLETE job - NOT orphan (job still exists)
        target3 = "devusrcompletejob"
        job_id3 = "eee555fff666-7890-abcd-ef12-345678901234"
        staging3 = f"{target3}_{job_id3[:12]}"
        
        # Add all staging databases
        self.state.staging_databases[dbhost] = {staging1, staging2, staging3}
        
        # Create jobs for database 1 and 3
        job1 = Job(
            id=job_id1,
            owner_user_id=self.user.user_id,
            owner_username=self.user.username,
            owner_user_code=self.user.user_code,
            target=target1,
            staging_name=staging1,
            dbhost=dbhost,
            status=JobStatus.RUNNING,
            submitted_at=datetime.now(UTC),
        )
        self.state.jobs[job_id1] = job1
        
        job3 = Job(
            id=job_id3,
            owner_user_id=self.user.user_id,
            owner_username=self.user.username,
            owner_user_code=self.user.user_code,
            target=target3,
            staging_name=staging3,
            dbhost=dbhost,
            status=JobStatus.COMPLETE,
            submitted_at=datetime.now(UTC) - timedelta(hours=5),
            completed_at=datetime.now(UTC) - timedelta(hours=4),
        )
        self.state.jobs[job_id3] = job3
        
        # Detect orphans
        report = _detect_orphaned_databases_simulation(dbhost)
        
        assert not isinstance(report, str), f"Expected OrphanReport, got error: {report}"
        # Only database 2 (no job) should be orphan
        self.assertEqual(len(report.orphans), 1,
            "Only database without job should be classified as orphan")
        self.assertEqual(report.orphans[0].database_name, staging2)
        self.assertEqual(report.orphans[0].target_name, target2)

    def test_simulation_matches_production_behavior(self) -> None:
        """Verify simulation orphan detection matches production logic.
        
        Production checks: job_repo.find_job_by_staging_prefix(target, dbhost, prefix)
        Simulation must do the same check.
        """
        from pulldb.worker.cleanup import _detect_orphaned_databases_simulation
        
        dbhost = "mysql-staging-01.example.com"
        target = "devusrparity"
        job_id = "parity123456-7890-abcd-ef12-345678901234"
        job_prefix = job_id[:12]
        staging_name = f"{target}_{job_prefix}"
        
        # Add staging database
        self.state.staging_databases[dbhost] = {staging_name}
        
        # Verify find_job_by_staging_prefix works correctly
        result = self.job_repo.find_job_by_staging_prefix(target, dbhost, job_prefix)
        self.assertIsNone(result, "No job exists yet")
        
        # Create the job
        job = Job(
            id=job_id,
            owner_user_id=self.user.user_id,
            owner_username=self.user.username,
            owner_user_code=self.user.user_code,
            target=target,
            staging_name=staging_name,
            dbhost=dbhost,
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        self.state.jobs[job_id] = job
        
        # Now find_job_by_staging_prefix should find it
        result = self.job_repo.find_job_by_staging_prefix(target, dbhost, job_prefix)
        self.assertIsNotNone(result, "Job should be found")
        assert result is not None
        self.assertEqual(result.id, job_id)
        
        # And orphan detection should NOT report it as orphan
        report = _detect_orphaned_databases_simulation(dbhost)
        assert not isinstance(report, str), f"Expected OrphanReport, got error: {report}"
        self.assertEqual(len(report.orphans), 0,
            "Database with matching job should not be orphan")
