"""Tests for the simulation system.

Phase 4 validation tests to ensure the Mock System works correctly.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime

import pytest

from pulldb.domain.models import Job, JobStatus
from pulldb.simulation import (
    EventType,
    MockCommandConfig,
    MockProcessExecutor,
    MockS3Client,
    ScenarioType,
    SimulatedHostRepository,
    SimulatedJobRepository,
    SimulatedSettingsRepository,
    SimulatedUserRepository,
    get_event_bus,
    get_scenario_manager,
    get_simulation_state,
    reset_scenario_manager,
    reset_simulation,
)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """Reset simulation state before each test."""
    reset_simulation()
    reset_scenario_manager()


class TestSimulationState:
    """Tests for simulation state management."""

    def test_state_is_singleton(self) -> None:
        """State should be a singleton."""
        state1 = get_simulation_state()
        state2 = get_simulation_state()
        assert state1 is state2

    def test_reset_clears_state(self) -> None:
        """Reset should clear all state."""
        state = get_simulation_state()
        state.jobs["test-id"] = "test-job"  # type: ignore
        reset_simulation()
        state = get_simulation_state()
        assert "test-id" not in state.jobs


class TestEventBus:
    """Tests for the simulation event bus."""

    def test_emit_and_get_history(self) -> None:
        """Events should be recorded in history."""
        bus = get_event_bus()
        bus.emit(EventType.JOB_CREATED, source="test", data={"id": "123"})

        history = bus.get_history()
        assert len(history) == 1
        assert history[0].event_type == EventType.JOB_CREATED
        assert history[0].source == "test"
        assert history[0].data["id"] == "123"

    def test_emit_with_job_id(self) -> None:
        """Events can include job_id."""
        bus = get_event_bus()
        bus.emit(EventType.JOB_CLAIMED, source="test", data={}, job_id="job-456")

        history = bus.get_history()
        assert history[0].job_id == "job-456"

    def test_subscribe_receives_events(self) -> None:
        """Subscribers should receive events."""
        bus = get_event_bus()
        received: list[EventType] = []

        def handler(event: object) -> None:
            received.append(event.event_type)  # type: ignore

        bus.subscribe(handler, EventType.JOB_COMPLETED)
        bus.emit(EventType.JOB_COMPLETED, source="test", data={})
        bus.emit(EventType.JOB_FAILED, source="test", data={})  # Should not receive

        assert len(received) == 1
        assert received[0] == EventType.JOB_COMPLETED

    def test_filter_by_event_type(self) -> None:
        """History can be filtered by event type."""
        bus = get_event_bus()
        bus.emit(EventType.JOB_CREATED, source="test", data={})
        bus.emit(EventType.JOB_COMPLETED, source="test", data={})
        bus.emit(EventType.JOB_CREATED, source="test", data={})

        created_events = bus.get_history(event_type=EventType.JOB_CREATED)
        assert len(created_events) == 2

    def test_filter_by_job_id(self) -> None:
        """History can be filtered by job_id."""
        bus = get_event_bus()
        bus.emit(EventType.JOB_CREATED, source="test", data={}, job_id="job-1")
        bus.emit(EventType.JOB_CLAIMED, source="test", data={}, job_id="job-1")
        bus.emit(EventType.JOB_CREATED, source="test", data={}, job_id="job-2")

        job1_events = bus.get_history(job_id="job-1")
        assert len(job1_events) == 2

    def test_clear_history(self) -> None:
        """History can be cleared."""
        bus = get_event_bus()
        bus.emit(EventType.JOB_CREATED, source="test", data={})
        bus.clear_history()
        assert len(bus.get_history()) == 0

    def test_wait_for_event_success(self) -> None:
        """wait_for_event should return when event is emitted."""
        bus = get_event_bus()

        def emit_later() -> None:
            time.sleep(0.1)
            bus.emit(EventType.JOB_COMPLETED, source="test", data={})

        threading.Thread(target=emit_later, daemon=True).start()
        event = bus.wait_for_event(EventType.JOB_COMPLETED, timeout=2.0)
        assert event is not None
        assert event.event_type == EventType.JOB_COMPLETED

    def test_wait_for_event_timeout(self) -> None:
        """wait_for_event should return None on timeout."""
        bus = get_event_bus()
        event = bus.wait_for_event(EventType.JOB_FAILED, timeout=0.1)
        assert event is None


class TestSimulatedJobRepository:
    """Tests for the simulated job repository."""

    def _create_test_job(self, job_id: str | None = None) -> Job:
        """Create a test job."""
        return Job(
            id=job_id or str(uuid.uuid4()),
            owner_user_id="user-1",
            owner_username="testuser",
            owner_user_code="test",
            target="test_db",
            staging_name="test_db_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )

    def test_enqueue_job(self) -> None:
        """Job can be enqueued."""
        repo = SimulatedJobRepository()
        job = self._create_test_job()
        job_id = repo.enqueue_job(job)

        assert job_id == job.id
        fetched = repo.get_job_by_id(job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.QUEUED

    def test_enqueue_emits_event(self) -> None:
        """Enqueue should emit JOB_CREATED event."""
        bus = get_event_bus()
        repo = SimulatedJobRepository()
        job = self._create_test_job()
        repo.enqueue_job(job)

        events = bus.get_history(event_type=EventType.JOB_CREATED)
        assert len(events) == 1
        assert events[0].job_id == job.id

    def test_claim_next_job(self) -> None:
        """Next queued job can be claimed."""
        repo = SimulatedJobRepository()
        job = self._create_test_job()
        repo.enqueue_job(job)

        claimed = repo.claim_next_job("worker-1")
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status == JobStatus.RUNNING
        assert claimed.worker_id == "worker-1"

    def test_claim_emits_event(self) -> None:
        """Claim should emit JOB_CLAIMED event."""
        bus = get_event_bus()
        repo = SimulatedJobRepository()
        job = self._create_test_job()
        repo.enqueue_job(job)
        repo.claim_next_job("worker-1")

        events = bus.get_history(event_type=EventType.JOB_CLAIMED)
        assert len(events) == 1
        assert events[0].job_id == job.id

    def test_claim_returns_none_if_no_jobs(self) -> None:
        """Claim should return None if no jobs available."""
        repo = SimulatedJobRepository()
        claimed = repo.claim_next_job("worker-1")
        assert claimed is None

    def test_mark_job_complete(self) -> None:
        """Job can be marked complete."""
        repo = SimulatedJobRepository()
        job = self._create_test_job()
        repo.enqueue_job(job)
        repo.claim_next_job("worker-1")
        repo.mark_job_complete(job.id)

        fetched = repo.get_job_by_id(job.id)
        assert fetched is not None
        assert fetched.status == JobStatus.COMPLETE

    def test_mark_job_failed(self) -> None:
        """Job can be marked failed."""
        repo = SimulatedJobRepository()
        job = self._create_test_job()
        repo.enqueue_job(job)
        repo.claim_next_job("worker-1")
        repo.mark_job_failed(job.id, "Test failure")

        fetched = repo.get_job_by_id(job.id)
        assert fetched is not None
        assert fetched.status == JobStatus.FAILED
        assert fetched.error_detail == "Test failure"

    def test_list_jobs(self) -> None:
        """Jobs can be listed."""
        repo = SimulatedJobRepository()
        job1 = self._create_test_job()
        job2 = self._create_test_job()
        repo.enqueue_job(job1)
        repo.enqueue_job(job2)

        jobs = repo.list_jobs()
        assert len(jobs) == 2


class TestMockS3Client:
    """Tests for the mock S3 client."""

    def test_load_fixtures_and_list_keys(self) -> None:
        """Fixtures can be loaded and listed."""
        s3 = MockS3Client()
        s3.load_fixtures("test-bucket", ["path/to/file1.txt", "path/to/file2.txt"])

        keys = s3.list_keys("test-bucket", "path/to/")
        assert len(keys) == 2
        assert "path/to/file1.txt" in keys

    def test_list_keys_emits_event(self) -> None:
        """list_keys should emit S3_LIST_KEYS event."""
        bus = get_event_bus()
        s3 = MockS3Client()
        s3.load_fixtures("test-bucket", ["key1.txt"])
        s3.list_keys("test-bucket", "")

        events = bus.get_history(event_type=EventType.S3_LIST_KEYS)
        assert len(events) == 1
        assert events[0].data["bucket"] == "test-bucket"

    def test_head_object_found(self) -> None:
        """head_object returns metadata for existing keys."""
        s3 = MockS3Client()
        s3.load_fixtures("test-bucket", ["existing.txt"])

        metadata = s3.head_object("test-bucket", "existing.txt")
        assert "ContentLength" in metadata
        assert "ContentType" in metadata

    def test_head_object_not_found(self) -> None:
        """head_object raises for missing keys."""
        s3 = MockS3Client()
        with pytest.raises(ValueError, match="not found"):
            s3.head_object("test-bucket", "missing.txt")

    def test_get_object_found(self) -> None:
        """get_object returns body for existing keys."""
        s3 = MockS3Client()
        s3.load_fixtures("test-bucket", ["file.txt"])

        result = s3.get_object("test-bucket", "file.txt")
        assert "Body" in result
        content = result["Body"].read()
        assert content == b"mock content"


class TestMockProcessExecutor:
    """Tests for the mock process executor."""

    def test_run_command_default_success(self) -> None:
        """Default command should succeed."""
        executor = MockProcessExecutor()
        exit_code = executor.run_command(["echo", "hello"])
        assert exit_code == 0

    def test_run_command_emits_events(self) -> None:
        """run_command should emit EXEC_START and EXEC_COMPLETE events."""
        bus = get_event_bus()
        executor = MockProcessExecutor()
        executor.run_command(["test-cmd"])

        start_events = bus.get_history(event_type=EventType.EXEC_START)
        complete_events = bus.get_history(event_type=EventType.EXEC_COMPLETE)
        assert len(start_events) == 1
        assert len(complete_events) == 1

    def test_configure_command_failure(self) -> None:
        """Commands can be configured to fail."""
        executor = MockProcessExecutor()
        executor.configure_command(
            "failing-cmd",
            MockCommandConfig(exit_code=1, stderr="Error!"),
        )

        exit_code = executor.run_command(["failing-cmd", "arg1"])
        assert exit_code == 1

    def test_run_command_streaming(self) -> None:
        """Streaming command captures output."""
        executor = MockProcessExecutor()
        executor.configure_command(
            "test",
            MockCommandConfig(stdout="line1\nline2\nline3"),
        )

        lines: list[str] = []
        result = executor.run_command_streaming(
            ["test"], line_callback=lines.append
        )

        assert result.exit_code == 0
        assert len(lines) == 3
        assert lines[0] == "line1"


class TestScenarioManager:
    """Tests for the scenario manager."""

    def test_list_scenarios(self) -> None:
        """All default scenarios should be available."""
        manager = get_scenario_manager()
        scenarios = manager.list_scenarios()

        names = [s.scenario_type for s in scenarios]
        assert ScenarioType.HAPPY_PATH in names
        assert ScenarioType.MYLOADER_FAILURE in names
        assert ScenarioType.S3_NOT_FOUND in names

    def test_activate_happy_path(self) -> None:
        """Happy path scenario should load S3 fixtures."""
        manager = get_scenario_manager()
        executor = MockProcessExecutor()

        scenario = manager.activate_scenario(ScenarioType.HAPPY_PATH, executor)

        assert scenario.name == "Happy Path"

        # Verify S3 fixtures loaded
        state = get_simulation_state()
        assert "pulldb-backups" in state.s3_buckets
        assert len(state.s3_buckets["pulldb-backups"]) > 0

    def test_activate_scenario_emits_event(self) -> None:
        """Activating scenario should emit SCENARIO_CHANGED event."""
        manager = get_scenario_manager()

        manager.activate_scenario(ScenarioType.HAPPY_PATH)

        # Get bus after activation since activation resets and creates new bus
        bus = get_event_bus()
        events = bus.get_history(event_type=EventType.SCENARIO_CHANGED)
        assert len(events) == 1
        assert events[0].data["scenario_type"] == "happy_path"

    def test_myloader_failure_scenario(self) -> None:
        """Myloader failure scenario should configure executor to fail."""
        manager = get_scenario_manager()
        executor = MockProcessExecutor()

        manager.activate_scenario(ScenarioType.MYLOADER_FAILURE, executor)

        exit_code = executor.run_command(["myloader", "--some-args"])
        assert exit_code == 1

    def test_s3_not_found_scenario(self) -> None:
        """S3 not found scenario should have no fixtures."""
        manager = get_scenario_manager()

        manager.activate_scenario(ScenarioType.S3_NOT_FOUND)

        state = get_simulation_state()
        # No buckets or empty buckets
        total_keys = sum(len(keys) for keys in state.s3_buckets.values())
        assert total_keys == 0


class TestIntegrationScenarios:
    """Integration tests for end-to-end simulation scenarios."""

    def test_full_job_lifecycle_happy_path(self) -> None:
        """Test complete job lifecycle in happy path scenario."""
        # Setup
        manager = get_scenario_manager()
        executor = MockProcessExecutor()
        manager.activate_scenario(ScenarioType.HAPPY_PATH, executor)

        # Create job
        repo = SimulatedJobRepository()
        job = Job(
            id=str(uuid.uuid4()),
            owner_user_id="user-1",
            owner_username="testuser",
            owner_user_code="test",
            target="test_db",
            staging_name="test_db_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)

        # Claim job
        claimed = repo.claim_next_job("worker-1")
        assert claimed is not None

        # "Execute" myloader
        exit_code = executor.run_command(["myloader"])
        assert exit_code == 0

        # Complete job
        repo.mark_job_complete(job.id)

        # Verify final state
        final_job = repo.get_job_by_id(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETE

        # Verify event sequence
        bus = get_event_bus()
        events = bus.get_history(job_id=job.id)
        event_types = [e.event_type for e in events]
        assert EventType.JOB_CREATED in event_types
        assert EventType.JOB_CLAIMED in event_types
        assert EventType.JOB_COMPLETED in event_types

    def test_job_failure_scenario(self) -> None:
        """Test job failure when myloader fails."""
        # Setup
        manager = get_scenario_manager()
        executor = MockProcessExecutor()
        manager.activate_scenario(ScenarioType.MYLOADER_FAILURE, executor)

        # Create and claim job
        repo = SimulatedJobRepository()
        job = Job(
            id=str(uuid.uuid4()),
            owner_user_id="user-1",
            owner_username="testuser",
            owner_user_code="test",
            target="test_db",
            staging_name="test_db_staging",
            dbhost="localhost",
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        repo.enqueue_job(job)
        repo.claim_next_job("worker-1")

        # "Execute" myloader - should fail
        exit_code = executor.run_command(["myloader"])
        assert exit_code == 1

        # Mark job failed
        repo.mark_job_failed(job.id, "myloader failed")

        # Verify event sequence includes failure
        bus = get_event_bus()
        events = bus.get_history(job_id=job.id)
        event_types = [e.event_type for e in events]
        assert EventType.JOB_FAILED in event_types
