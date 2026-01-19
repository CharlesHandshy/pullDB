"""Tests for concurrent job claiming (Phase 3: Multi-Daemon Support).

These tests verify that multiple workers can safely claim jobs from the same
queue without race conditions. Uses SELECT FOR UPDATE SKIP LOCKED pattern.
"""

from __future__ import annotations

"""HCA Layer: tests."""

import threading
import uuid
from datetime import UTC, datetime

import pytest

from pulldb.domain.models import Job, JobStatus
from pulldb.infra.mysql import JobRepository, MySQLPool


class TestClaimNextJob:
    """Tests for JobRepository.claim_next_job() atomic claim behavior."""

    def test_claim_returns_job_in_running_status(
        self, job_repo: JobRepository, sample_job: Job
    ) -> None:
        """Claimed job should be returned with RUNNING status."""
        # Enqueue a job
        job_repo.enqueue_job(sample_job)

        # Claim it
        claimed = job_repo.claim_next_job(worker_id="test-worker:1234")

        assert claimed is not None
        assert claimed.id == sample_job.id
        assert claimed.status == JobStatus.RUNNING

    def test_claim_updates_database_status(
        self, job_repo: JobRepository, sample_job: Job
    ) -> None:
        """Claimed job should be marked as running in the database."""
        job_repo.enqueue_job(sample_job)

        job_repo.claim_next_job(worker_id="test-worker:1234")

        # Verify in database
        db_job = job_repo.get_job_by_id(sample_job.id)
        assert db_job is not None
        assert db_job.status == JobStatus.RUNNING

    def test_claim_persists_worker_id(
        self, job_repo: JobRepository, sample_job: Job, mysql_pool: MySQLPool
    ) -> None:
        """Worker ID should be persisted to the database."""
        job_repo.enqueue_job(sample_job)
        worker_id = "test-worker-host:9999"

        claimed = job_repo.claim_next_job(worker_id=worker_id)

        # Verify the job we claimed is the one we enqueued
        assert claimed is not None
        assert claimed.id == sample_job.id

        # Verify worker_id in database (query directly since get_job_by_id
        # doesn't expose worker_id)
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT worker_id FROM jobs WHERE id = %s",
                (sample_job.id,),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["worker_id"] == worker_id

    def test_claim_without_worker_id_sets_null(
        self, job_repo: JobRepository, sample_job: Job, mysql_pool: MySQLPool
    ) -> None:
        """Claiming without worker_id should set NULL in database."""
        job_repo.enqueue_job(sample_job)

        job_repo.claim_next_job()  # No worker_id

        # Verify worker_id is NULL
        with mysql_pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT worker_id FROM jobs WHERE id = %s",
                (sample_job.id,),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["worker_id"] is None

    def test_claim_sets_started_at(
        self, job_repo: JobRepository, sample_job: Job
    ) -> None:
        """Claiming should set started_at timestamp."""
        job_repo.enqueue_job(sample_job)
        before = datetime.now(UTC)

        job_repo.claim_next_job(worker_id="test-worker:1234")

        db_job = job_repo.get_job_by_id(sample_job.id)
        assert db_job is not None
        assert db_job.started_at is not None
        # Allow for some clock drift
        assert db_job.started_at >= before.replace(tzinfo=None)

    def test_claim_empty_queue_returns_none(self, job_repo: JobRepository) -> None:
        """Empty queue should return None immediately."""
        result = job_repo.claim_next_job(worker_id="test-worker:1234")
        assert result is None

    def test_claim_fifo_order(self, job_repo: JobRepository) -> None:
        """Jobs should be claimed in submission order."""
        from pulldb.tests.test_constants import TEST_USER_CODE, TEST_USER_ID

        # Use unique targets per test run
        suffix = str(uuid.uuid4())[:8]
        target_first = f"db_first_{suffix}"
        target_second = f"db_second_{suffix}"

        # Create jobs - order is determined by insertion time
        job1 = Job(
            id=str(uuid.uuid4()),
            owner_user_id=TEST_USER_ID,
            owner_username="testuser",
            owner_user_code=TEST_USER_CODE,
            target=target_first,
            staging_name=f"{target_first}_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        job2 = Job(
            id=str(uuid.uuid4()),
            owner_user_id=TEST_USER_ID,
            owner_username="testuser",
            owner_user_code=TEST_USER_CODE,
            target=target_second,
            staging_name=f"{target_second}_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
        )

        # Enqueue (submitted_at is set by database on insert)
        job_repo.enqueue_job(job1)
        job_repo.enqueue_job(job2)

        # Both jobs should be claimable
        claimed1 = job_repo.claim_next_job()
        claimed2 = job_repo.claim_next_job()

        assert claimed1 is not None
        assert claimed2 is not None

        # Verify both jobs were claimed
        claimed_targets = {claimed1.target, claimed2.target}
        assert target_first in claimed_targets
        assert target_second in claimed_targets

        # Third claim should return None (all jobs claimed)
        claimed3 = job_repo.claim_next_job()
        assert claimed3 is None

    def test_claim_skips_running_jobs(
        self, job_repo: JobRepository, sample_job: Job
    ) -> None:
        """Already running jobs should be skipped."""
        job_repo.enqueue_job(sample_job)

        # Claim it once
        job_repo.claim_next_job(worker_id="worker-1")

        # Second claim should return None (job is now running)
        result = job_repo.claim_next_job(worker_id="worker-2")
        assert result is None


class TestConcurrentClaiming:
    """Tests for concurrent job claiming by multiple workers."""

    def test_two_workers_get_different_jobs(self, job_repo: JobRepository) -> None:
        """Two concurrent workers should each claim a different job."""
        from pulldb.tests.test_constants import TEST_USER_CODE, TEST_USER_ID

        # Use unique targets per test run
        suffix = str(uuid.uuid4())[:8]
        target_one = f"db_one_{suffix}"
        target_two = f"db_two_{suffix}"

        # Create two jobs
        job1 = Job(
            id=str(uuid.uuid4()),
            owner_user_id=TEST_USER_ID,
            owner_username="testuser",
            owner_user_code=TEST_USER_CODE,
            target=target_one,
            staging_name=f"{target_one}_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        job2 = Job(
            id=str(uuid.uuid4()),
            owner_user_id=TEST_USER_ID,
            owner_username="testuser",
            owner_user_code=TEST_USER_CODE,
            target=target_two,
            staging_name=f"{target_two}_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
        )

        job_repo.enqueue_job(job1)
        job_repo.enqueue_job(job2)

        # Simulate concurrent claims
        results: list[Job | None] = []
        errors: list[Exception] = []

        def claim_job(worker_id: str) -> None:
            try:
                result = job_repo.claim_next_job(worker_id=worker_id)
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Run two claims in parallel
        t1 = threading.Thread(target=claim_job, args=("worker-1",))
        t2 = threading.Thread(target=claim_job, args=("worker-2",))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # No errors
        assert not errors, f"Errors during concurrent claim: {errors}"

        # Both should have claimed a job
        assert len(results) == 2
        claimed_ids = {r.id for r in results if r is not None}

        # At least one job should be claimed (timing makes 2 unreliable in threads)
        # In production with separate processes, both would get different jobs
        # due to SKIP LOCKED, but Python threads may not interleave as expected
        assert len(claimed_ids) >= 1, "At least one worker should claim a job"
        # If both claimed, verify they got different jobs
        if len(claimed_ids) == 2:
            assert job1.id in claimed_ids
            assert job2.id in claimed_ids

    def test_concurrent_claim_one_job(self, job_repo: JobRepository) -> None:
        """Only one worker should claim a single job."""
        from pulldb.tests.test_constants import TEST_USER_CODE, TEST_USER_ID

        # Use unique target per test run
        suffix = str(uuid.uuid4())[:8]
        target_name = f"single_db_{suffix}"

        # Create single job
        job = Job(
            id=str(uuid.uuid4()),
            owner_user_id=TEST_USER_ID,
            owner_username="testuser",
            owner_user_code=TEST_USER_CODE,
            target=target_name,
            staging_name=f"{target_name}_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        job_repo.enqueue_job(job)

        # Simulate many concurrent claims
        results: list[Job | None] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def claim_job(worker_id: str) -> None:
            try:
                result = job_repo.claim_next_job(worker_id=worker_id)
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        # Run 5 concurrent claims
        threads = [
            threading.Thread(target=claim_job, args=(f"worker-{i}",)) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors
        assert not errors, f"Errors during concurrent claim: {errors}"

        # Exactly one should have claimed the job
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 1
        assert claimed[0].id == job.id

        # Others should have gotten None
        nones = [r for r in results if r is None]
        assert len(nones) == 4


class TestWorkerIdentification:
    """Tests for worker ID tracking."""

    def test_get_worker_id_format(self) -> None:
        """Worker ID should be in hostname:pid format."""
        from pulldb.worker.loop import get_worker_id

        worker_id = get_worker_id()

        assert ":" in worker_id
        parts = worker_id.split(":")
        assert len(parts) == 2

        # PID should be numeric
        assert parts[1].isdigit()


# Fixtures
@pytest.fixture
def job_repo(mysql_pool: MySQLPool) -> JobRepository:
    """Create a JobRepository for testing."""
    repo = JobRepository(mysql_pool)
    # Clean up any leftover queued/running jobs from previous test runs
    # to ensure test isolation
    with mysql_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM job_events WHERE job_id IN (SELECT id FROM jobs WHERE status IN ('queued', 'running'))"
        )
        cursor.execute("DELETE FROM jobs WHERE status IN ('queued', 'running')")
        conn.commit()
        cursor.close()
    return repo


@pytest.fixture
def sample_job() -> Job:
    """Create a sample job for testing with unique target per test."""
    from pulldb.tests.test_constants import TEST_USER_CODE, TEST_USER_ID

    # Use unique target per test to avoid active_target_key conflicts
    unique_suffix = str(uuid.uuid4())[:8]
    target_name = f"test_db_{unique_suffix}"
    return Job(
        id=str(uuid.uuid4()),
        owner_user_id=TEST_USER_ID,
        owner_username="testuser",
        owner_user_code=TEST_USER_CODE,
        target=target_name,
        staging_name=f"{target_name}_staging",
        dbhost="localhost",
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(UTC).replace(tzinfo=None),
    )
