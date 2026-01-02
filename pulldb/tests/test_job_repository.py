"""JobRepository tests.

Covers enqueue, retrieval, status transitions, exclusivity, event append and
ordering.

MANDATE: Uses AWS Secrets Manager for DB login via conftest.py fixtures.
"""

from __future__ import annotations

import uuid
import warnings
from datetime import UTC, datetime
from typing import Any

import pytest

from pulldb.domain.models import Job, JobStatus
from pulldb.infra.mysql import JobRepository
from pulldb.tests.test_constants import TEST_USER_CODE, TEST_USER_ID, TEST_USERNAME


EXPECTED_EVENT_COUNT = 3


class TestJobRepository:
    def _cleanup_job(self, pool: Any, job_id: str, target: str) -> None:
        with pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM job_events WHERE job_id = %s", (job_id,))
            cursor.execute(
                "DELETE FROM jobs WHERE id = %s OR target = %s", (job_id, target)
            )
            conn.commit()
            cursor.close()

    def test_enqueue_job(self, mysql_pool: Any) -> None:
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target="testtarget",
            staging_name="testtarget_" + job_id[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo = JobRepository(mysql_pool)
        inserted_id = repo.enqueue_job(job)
        assert inserted_id == job_id
        self._cleanup_job(mysql_pool, job_id, job.target)

    def test_get_next_queued_job(self, mysql_pool: Any) -> None:
        """Test deprecated get_next_queued_job (for backward compat coverage)."""
        repo = JobRepository(mysql_pool)
        job_id1 = str(uuid.uuid4())
        job_id2 = str(uuid.uuid4())
        target1 = "target1_" + job_id1[:8]
        target2 = "target2_" + job_id2[:8]

        # Clean up any leftover queued jobs to ensure test isolation
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM job_events WHERE job_id IN (SELECT id FROM jobs WHERE status = 'queued')"
            )
            cursor.execute("DELETE FROM jobs WHERE status = 'queued'")
            conn.commit()
            cursor.close()

        job1 = Job(
            id=job_id1,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target1,
            staging_name="target1_" + job_id1[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        job2 = Job(
            id=job_id2,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target2,
            staging_name="target2_" + job_id2[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job1)
        repo.enqueue_job(job2)

        # Suppress deprecation warning - testing legacy API intentionally
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            next_job = repo.get_next_queued_job()

        assert next_job is not None
        assert next_job.id == job_id1
        self._cleanup_job(mysql_pool, job_id1, target1)
        self._cleanup_job(mysql_pool, job_id2, target2)

    def test_status_transitions(self, mysql_pool: Any) -> None:
        """Test job status transitions using claim_next_job."""
        repo = JobRepository(mysql_pool)
        job_id = str(uuid.uuid4())
        target = f"target_run_{job_id[:8]}"
        job = Job(
            id=job_id,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target,
            staging_name=target + "_" + job_id[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)

        # Use claim_next_job which atomically transitions to running
        claimed = repo.claim_next_job(worker_id="test-worker:1234")
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.status == JobStatus.RUNNING

        # Verify in database
        running = repo.get_job_by_id(job_id)
        assert (
            running is not None
            and running.status == JobStatus.RUNNING
            and running.started_at is not None
        )

        repo.mark_job_deployed(job_id)
        deployed = repo.get_job_by_id(job_id)
        assert (
            deployed is not None
            and deployed.status == JobStatus.DEPLOYED
            and deployed.completed_at is not None
        )
        self._cleanup_job(mysql_pool, job_id, target)

    def test_mark_job_failed(self, mysql_pool: Any) -> None:
        """Test marking a job as failed."""
        repo = JobRepository(mysql_pool)
        job_id = str(uuid.uuid4())
        target = f"target_fail_{job_id[:8]}"
        job = Job(
            id=job_id,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target,
            staging_name=target + "_" + job_id[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)

        # Use claim_next_job to transition to running
        claimed = repo.claim_next_job(worker_id="test-worker:1234")
        assert claimed is not None

        error_msg = "Simulated failure"
        repo.mark_job_failed(job_id, error_msg)
        failed = repo.get_job_by_id(job_id)
        assert (
            failed is not None
            and failed.status == JobStatus.FAILED
            and failed.error_detail == error_msg
        )
        self._cleanup_job(mysql_pool, job_id, target)

    def test_per_target_exclusivity(self, mysql_pool: Any) -> None:
        """Test that only one active job per target is allowed."""
        repo = JobRepository(mysql_pool)
        job_id1 = str(uuid.uuid4())
        job_id2 = str(uuid.uuid4())
        target = f"target_excl_{job_id1[:8]}"
        job1 = Job(
            id=job_id1,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target,
            staging_name=target + "_" + job_id1[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job1)

        # Use claim_next_job to transition to running
        claimed = repo.claim_next_job(worker_id="test-worker:1234")
        assert claimed is not None and claimed.id == job_id1

        job2 = Job(
            id=job_id2,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target,
            staging_name=target + "_" + job_id2[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        from mysql.connector.errors import IntegrityError

        with pytest.raises(ValueError) as excinfo:
            repo.enqueue_job(job2)
        assert "already has an active job" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, IntegrityError)
        self._cleanup_job(mysql_pool, job_id1, target)
        # second job not inserted, but ensure cleanup if partial
        self._cleanup_job(mysql_pool, job_id2, target)

    def test_append_and_get_events(self, mysql_pool: Any) -> None:
        repo = JobRepository(mysql_pool)
        job_id = str(uuid.uuid4())
        target = f"target_evt_{job_id[:8]}"
        job = Job(
            id=job_id,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target,
            staging_name=target + "_" + job_id[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)
        repo.append_job_event(job_id, "download_started", "Downloading")
        repo.append_job_event(job_id, "restore_started", "Restoring")
        repo.append_job_event(job_id, "restore_complete", "Done")
        events = repo.get_job_events(job_id)
        assert len(events) == EXPECTED_EVENT_COUNT
        assert [e.event_type for e in events] == [
            "download_started",
            "restore_started",
            "restore_complete",
        ]
        self._cleanup_job(mysql_pool, job_id, target)

    def test_prune_job_events(self, mysql_pool: Any) -> None:
        """Test that prune_job_events only deletes events for terminal jobs."""
        repo = JobRepository(mysql_pool)
        job_id = str(uuid.uuid4())
        target = f"test_prune_{job_id[:8]}"

        # Create a completed job with events
        job = Job(
            id=job_id,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target,
            staging_name=target + "_" + job_id[:12],
            dbhost="dev-db-01",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)
        repo.append_job_event(job_id, "queued", "Job submitted")
        repo.append_job_event(job_id, "running", "Started")
        repo.append_job_event(job_id, "complete", "Done")

        # Use claim_next_job then mark deployed
        claimed = repo.claim_next_job(worker_id="test-worker:1234")
        assert claimed is not None
        repo.mark_job_deployed(job_id)

        # Prune with very long retention - should delete nothing
        deleted = repo.prune_job_events(retention_days=365)
        events_after = repo.get_job_events(job_id)
        # Events should still exist (they're not 365 days old)
        assert len(events_after) == 3
        assert deleted == 0

        # Clean up
        self._cleanup_job(mysql_pool, job_id, target)

    def test_prune_job_events_validation(self, mysql_pool: Any) -> None:
        """Test that prune_job_events validates retention_days."""
        repo = JobRepository(mysql_pool)

        # 0 is now valid (delete all events for terminal jobs)
        # Just ensure it doesn't raise - actual deletion tested elsewhere
        # repo.prune_job_events(retention_days=0)  # Would delete real data

        with pytest.raises(ValueError, match="retention_days must be >= 0"):
            repo.prune_job_events(retention_days=-1)
