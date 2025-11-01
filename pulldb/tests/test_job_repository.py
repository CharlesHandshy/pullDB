"""JobRepository tests.

Covers enqueue, retrieval, status transitions, exclusivity, event append and
ordering.

MANDATE: Uses AWS Secrets Manager for DB login via conftest.py fixtures.
"""

from __future__ import annotations

import uuid
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
            dbhost="db-mysql-db4-dev",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo = JobRepository(mysql_pool)
        inserted_id = repo.enqueue_job(job)
        assert inserted_id == job_id
        self._cleanup_job(mysql_pool, job_id, job.target)

    def test_get_next_queued_job(self, mysql_pool: Any) -> None:
        repo = JobRepository(mysql_pool)
        job_id1 = str(uuid.uuid4())
        job_id2 = str(uuid.uuid4())
        job1 = Job(
            id=job_id1,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target="target1_" + job_id1[:8],
            staging_name="target1_" + job_id1[:12],
            dbhost="db-mysql-db4-dev",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        job2 = Job(
            id=job_id2,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target="target2_" + job_id2[:8],
            staging_name="target2_" + job_id2[:12],
            dbhost="db-mysql-db4-dev",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job1)
        repo.enqueue_job(job2)
        next_job = repo.get_next_queued_job()
        assert next_job is not None
        assert next_job.id == job_id1
        self._cleanup_job(mysql_pool, job_id1, job1.target)
        self._cleanup_job(mysql_pool, job_id2, job2.target)

    def test_status_transitions(self, mysql_pool: Any) -> None:
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
            dbhost="db-mysql-db4-dev",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)
        repo.mark_job_running(job_id)
        running = repo.get_job_by_id(job_id)
        assert (
            running is not None
            and running.status == JobStatus.RUNNING
            and running.started_at is not None
        )
        repo.mark_job_complete(job_id)
        complete = repo.get_job_by_id(job_id)
        assert (
            complete is not None
            and complete.status == JobStatus.COMPLETE
            and complete.completed_at is not None
        )
        self._cleanup_job(mysql_pool, job_id, target)

    def test_mark_job_failed(self, mysql_pool: Any) -> None:
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
            dbhost="db-mysql-db4-dev",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)
        repo.mark_job_running(job_id)
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
            dbhost="db-mysql-db4-dev",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job1)
        repo.mark_job_running(job_id1)
        job2 = Job(
            id=job_id2,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=target,
            staging_name=target + "_" + job_id2[:12],
            dbhost="db-mysql-db4-dev",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        from mysql.connector.errors import IntegrityError

        with pytest.raises(IntegrityError):
            repo.enqueue_job(job2)
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
            dbhost="db-mysql-db4-dev",
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
