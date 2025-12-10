"""Integration tests for job event pruning against real MySQL.

These tests create isolated test data, verify pruning behavior,
and clean up after themselves. They require a running MySQL instance
with the pulldb schema.

Run with: pytest tests/integration/test_prune_job_events.py -v
"""

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

import pytest

# Ensure we import from the local project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from pulldb.domain.models import JobStatus


# Skip all tests if MySQL is not available
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_MYSQL_TESTS", "1") == "1",
    reason="MySQL tests disabled. Set SKIP_MYSQL_TESTS=0 to enable.",
)


@pytest.fixture(scope="module")
def job_repo():
    """Get a JobRepository connected to test MySQL."""
    from pulldb.infra.mysql import JobRepository, MySQLPool
    from pulldb.infra.secrets import SecretsManager
    
    secrets = SecretsManager()
    pool = MySQLPool(secrets)
    repo = JobRepository(pool)
    yield repo
    pool.close()


@pytest.fixture(scope="module")
def mysql_pool():
    """Get a MySQL pool for direct queries."""
    from pulldb.infra.mysql import MySQLPool
    from pulldb.infra.secrets import SecretsManager
    
    secrets = SecretsManager()
    pool = MySQLPool(secrets)
    yield pool
    pool.close()


class TestPruneJobEventsMySQL:
    """Integration tests for pruning job events in MySQL."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, job_repo, mysql_pool):
        """Create isolated test data for each test."""
        self.job_repo = job_repo
        self.pool = mysql_pool
        self.test_prefix = f"test_{uuid.uuid4().hex[:8]}_"
        self.created_job_ids = []
        
        yield
        
        # Cleanup: Remove test data
        self._cleanup_test_data()

    def _cleanup_test_data(self):
        """Remove all test data created during the test."""
        if not self.created_job_ids:
            return
            
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            placeholders = ", ".join(["%s"] * len(self.created_job_ids))
            
            # Delete events first (FK constraint)
            cursor.execute(
                f"DELETE FROM job_events WHERE job_id IN ({placeholders})",
                tuple(self.created_job_ids),
            )
            
            # Delete jobs
            cursor.execute(
                f"DELETE FROM jobs WHERE id IN ({placeholders})",
                tuple(self.created_job_ids),
            )
            conn.commit()

    def _create_test_job(
        self,
        status: str,
        days_ago_completed: int = 100,
    ) -> str:
        """Create a test job with the given status.
        
        Returns the job ID.
        """
        job_id = f"{self.test_prefix}{uuid.uuid4()}"
        submitted_at = datetime.now(UTC) - timedelta(days=days_ago_completed + 5)
        completed_at = datetime.now(UTC) - timedelta(days=days_ago_completed)
        
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO jobs (
                    id, owner_user_id, owner_username, owner_user_code,
                    target, staging_name, dbhost, status,
                    submitted_at, completed_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    job_id,
                    "test-user-id",
                    "testuser",
                    "test01",
                    "test_db",
                    f"staging_{job_id[:12]}",
                    "test-host",
                    status,
                    submitted_at,
                    completed_at if status != "running" else None,
                ),
            )
            conn.commit()
        
        self.created_job_ids.append(job_id)
        return job_id

    def _add_test_event(
        self,
        job_id: str,
        event_type: str,
        days_ago: int,
    ) -> int:
        """Add a test event for a job.
        
        Returns the event ID.
        """
        logged_at = datetime.now(UTC) - timedelta(days=days_ago)
        
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO job_events (job_id, event_type, detail, logged_at)
                VALUES (%s, %s, %s, %s)
                """,
                (job_id, event_type, f"Test {event_type}", logged_at),
            )
            conn.commit()
            return cursor.lastrowid

    def _count_events_for_job(self, job_id: str) -> int:
        """Count events for a specific job."""
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM job_events WHERE job_id = %s",
                (job_id,),
            )
            return cursor.fetchone()[0]

    # ==================== Tests ====================

    def test_get_prune_candidates_returns_old_terminal_jobs(self):
        """get_prune_candidates should return jobs with old events."""
        # Create terminal job with old events
        job_id = self._create_test_job("completed", days_ago_completed=100)
        self._add_test_event(job_id, "queued", 100)
        self._add_test_event(job_id, "complete", 95)

        result = self.job_repo.get_prune_candidates(retention_days=90)

        # Find our test job in results
        our_jobs = [r for r in result["rows"] if r["job_id"] == job_id]
        assert len(our_jobs) == 1
        assert our_jobs[0]["event_count"] == 2
        assert our_jobs[0]["status"] == "completed"

    def test_get_prune_candidates_excludes_running_jobs(self):
        """get_prune_candidates should not include running jobs."""
        # Create running job with old events
        job_id = self._create_test_job("running")
        self._add_test_event(job_id, "queued", 100)

        result = self.job_repo.get_prune_candidates(retention_days=90)

        # Our running job should not be in results
        our_jobs = [r for r in result["rows"] if r["job_id"] == job_id]
        assert len(our_jobs) == 0

    def test_get_prune_candidates_excludes_recent_events(self):
        """get_prune_candidates should not include jobs with only recent events."""
        # Create job with recent events only
        job_id = self._create_test_job("completed", days_ago_completed=30)
        self._add_test_event(job_id, "complete", 30)

        result = self.job_repo.get_prune_candidates(retention_days=90)

        # Our job should not be in results (events too recent)
        our_jobs = [r for r in result["rows"] if r["job_id"] == job_id]
        assert len(our_jobs) == 0

    def test_prune_job_events_by_ids_deletes_events(self):
        """prune_job_events_by_ids should delete events for specified jobs."""
        # Create two jobs
        job_to_delete = self._create_test_job("completed")
        job_to_keep = self._create_test_job("completed")
        
        self._add_test_event(job_to_delete, "queued", 100)
        self._add_test_event(job_to_delete, "complete", 95)
        self._add_test_event(job_to_keep, "queued", 100)
        self._add_test_event(job_to_keep, "complete", 95)

        # Verify initial state
        assert self._count_events_for_job(job_to_delete) == 2
        assert self._count_events_for_job(job_to_keep) == 2

        # Delete events for one job
        deleted = self.job_repo.prune_job_events_by_ids([job_to_delete])

        assert deleted == 2
        assert self._count_events_for_job(job_to_delete) == 0
        assert self._count_events_for_job(job_to_keep) == 2

    def test_prune_job_events_by_ids_only_affects_terminal_jobs(self):
        """prune_job_events_by_ids should not delete events for running jobs."""
        # Create running job
        running_job = self._create_test_job("running")
        self._add_test_event(running_job, "queued", 100)

        # Attempt to delete
        deleted = self.job_repo.prune_job_events_by_ids([running_job])

        # Should not delete events for running job
        assert deleted == 0
        assert self._count_events_for_job(running_job) == 1

    def test_prune_job_events_by_ids_empty_list(self):
        """prune_job_events_by_ids with empty list should return 0."""
        deleted = self.job_repo.prune_job_events_by_ids([])
        assert deleted == 0

    def test_prune_job_events_excluding_preserves_excluded(self):
        """prune_job_events_excluding should preserve events for excluded jobs."""
        # Create two jobs with old events
        job_exclude = self._create_test_job("completed")
        job_delete = self._create_test_job("completed")
        
        self._add_test_event(job_exclude, "complete", 100)
        self._add_test_event(job_delete, "complete", 100)

        # Prune excluding one job
        deleted = self.job_repo.prune_job_events_excluding(
            retention_days=90,
            exclude_job_ids=[job_exclude],
        )

        # Excluded job should still have events
        assert self._count_events_for_job(job_exclude) == 1
        # Non-excluded job should have events deleted
        assert self._count_events_for_job(job_delete) == 0
        assert deleted >= 1  # At least our test job's event

    def test_prune_job_events_excluding_respects_retention(self):
        """prune_job_events_excluding should only delete old events."""
        # Create job with mix of old and recent events
        job_id = self._create_test_job("completed", days_ago_completed=30)
        self._add_test_event(job_id, "old_event", 100)  # Old
        self._add_test_event(job_id, "recent_event", 30)  # Recent

        # Prune with 90 day retention
        self.job_repo.prune_job_events_excluding(retention_days=90)

        # Only old event should be deleted
        assert self._count_events_for_job(job_id) == 1

    def test_prune_multiple_jobs_at_once(self):
        """prune_job_events_by_ids should handle multiple job IDs."""
        # Create 5 jobs
        job_ids = [self._create_test_job("completed") for _ in range(5)]
        for job_id in job_ids:
            self._add_test_event(job_id, "complete", 100)

        # Delete events for 3 jobs
        to_delete = job_ids[:3]
        to_keep = job_ids[3:]
        
        deleted = self.job_repo.prune_job_events_by_ids(to_delete)

        assert deleted == 3
        for job_id in to_delete:
            assert self._count_events_for_job(job_id) == 0
        for job_id in to_keep:
            assert self._count_events_for_job(job_id) == 1

    def test_fk_integrity_after_prune(self):
        """Pruning events should not violate FK constraints."""
        # Create job and events
        job_id = self._create_test_job("completed")
        self._add_test_event(job_id, "complete", 100)

        # Delete events
        self.job_repo.prune_job_events_by_ids([job_id])

        # Job should still exist
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == job_id

    def test_cascade_to_get_job_events(self):
        """After pruning, get_job_events should return empty."""
        # Create job with events
        job_id = self._create_test_job("completed")
        self._add_test_event(job_id, "queued", 100)
        self._add_test_event(job_id, "complete", 95)

        # Before prune
        events_before = self.job_repo.get_job_events(job_id)
        assert len(events_before) == 2

        # Prune
        self.job_repo.prune_job_events_by_ids([job_id])

        # After prune
        events_after = self.job_repo.get_job_events(job_id)
        assert len(events_after) == 0
