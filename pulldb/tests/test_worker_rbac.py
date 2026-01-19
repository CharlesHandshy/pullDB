"""Integration tests for Worker Service RBAC using Simulation Mode.

Phase 4: Validates that the Worker Service correctly handles jobs with
different user roles and permissions.
"""

from __future__ import annotations

"""HCA Layer: tests."""

import os
import uuid
from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime
from unittest import mock

import pytest

from pulldb.domain.models import Job, JobStatus, UserRole
from pulldb.simulation import (
    SimulatedJobRepository,
    SimulatedUserRepository,
    reset_simulation,
)
from pulldb.simulation.core.state import get_simulation_state


@pytest.fixture(autouse=True)
def simulation_mode() -> Generator[None, None, None]:
    """Force simulation mode for these tests."""
    with mock.patch.dict(os.environ, {"PULLDB_MODE": "SIMULATION"}):
        reset_simulation()
        yield


class TestWorkerRBAC:
    """Tests for Worker Service RBAC handling."""

    def test_worker_processes_user_job(self) -> None:
        """Worker should process job submitted by regular user."""
        # Setup
        user_repo = SimulatedUserRepository()
        job_repo = SimulatedJobRepository()

        # Create user
        user = user_repo.create_user("regular_user", "regusr")
        assert user.role == UserRole.USER

        # Submit job (simulating API enqueue)
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            owner_user_id=user.user_id,
            owner_username=user.username,
            owner_user_code=user.user_code,
            target="regusrtest",
            staging_name="staging_regusrtest",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
            options_json={},
        )
        job_repo.enqueue_job(job)

        # Verify job is queued with correct owner
        queued_job = job_repo.get_job_by_id(job_id)
        assert queued_job is not None
        assert queued_job.owner_username == "regular_user"
        assert queued_job.owner_user_code == "regusr"

        # Simulate worker claiming job
        claimed_job = job_repo.claim_next_job("worker-1")
        assert claimed_job is not None
        assert claimed_job.id == job_id
        assert claimed_job.status == JobStatus.RUNNING

        # Verify event log contains owner info
        state = get_simulation_state()
        with state.lock:
            events = [e for e in state.job_events if e.job_id == job_id]
            # Check creation event (event_type is "queued" in repository)
            assert any(e.event_type == "queued" for e in events)

    def test_worker_processes_admin_job(self) -> None:
        """Worker should process job submitted by admin."""
        # Setup
        user_repo = SimulatedUserRepository()
        job_repo = SimulatedJobRepository()

        # Create admin
        admin = user_repo.create_user("admin_user", "admin")
        # Manually upgrade to admin since create_user defaults to USER
        state = get_simulation_state()
        with state.lock:
            state.users[admin.user_id] = replace(
                admin, role=UserRole.ADMIN, is_admin=True
            )
            admin = state.users[admin.user_id]

        assert admin.role == UserRole.ADMIN

        # Submit job
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            owner_user_id=admin.user_id,
            owner_username=admin.username,
            owner_user_code=admin.user_code,
            target="admintest",
            staging_name="staging_admintest",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
            options_json={},
        )
        job_repo.enqueue_job(job)

        # Simulate worker claiming job
        claimed_job = job_repo.claim_next_job("worker-1")
        assert claimed_job is not None
        assert claimed_job.id == job_id
