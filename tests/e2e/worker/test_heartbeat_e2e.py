"""End-to-end tests for heartbeat mechanism with executor pattern.

Tests the complete integration of heartbeat with the restore workflow,
verifying that heartbeats are emitted during all phases including
the fixed metadata synthesis.
"""

from __future__ import annotations

import gzip
import tempfile
import time
import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

import pytest

from pulldb.worker.heartbeat import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    HeartbeatContext,
    HeartbeatThread,
)
from pulldb.worker.backup_metadata import (
    synthesize_metadata,
    ensure_compatible_metadata,
)


@dataclass
class MockJobEvent:
    """Simulates a job_event record as would be stored in MySQL."""
    job_id: str
    event_type: str
    detail: str | None
    logged_at: datetime


class TestExecutorHeartbeatE2E:
    """End-to-end tests simulating the executor's heartbeat integration."""

    def test_heartbeat_emits_during_all_workflow_phases(self) -> None:
        """Simulate complete executor workflow with heartbeat.

        This test replicates the pattern from WorkerJobExecutor.execute():
        1. Create heartbeat emission function
        2. Wrap workflow in HeartbeatContext
        3. Verify heartbeats are emitted during all phases
        """
        job_events: list[MockJobEvent] = []
        job_id = "test-job-12345"
        
        # Simulates JobRepository.append_job_event()
        def mock_append_job_event(event_type: str, detail: dict | None = None) -> None:
            job_events.append(MockJobEvent(
                job_id=job_id,
                event_type=event_type,
                detail=str(detail) if detail else None,
                logged_at=datetime.now(UTC),
            ))
        
        # Simulates _emit_heartbeat() in executor
        def _emit_heartbeat() -> None:
            mock_append_job_event("heartbeat", {"status": "worker_alive"})
        
        # Simulate workflow phases with varying durations
        def _simulate_download_phase() -> None:
            mock_append_job_event("download_started", {})
            time.sleep(0.08)  # Download takes time
            mock_append_job_event("download_progress", {"percent": 50})
            time.sleep(0.08)
            mock_append_job_event("download_complete", {})
        
        def _simulate_extraction_phase() -> None:
            mock_append_job_event("extraction_started", {})
            time.sleep(0.06)
            mock_append_job_event("extraction_complete", {})
        
        def _simulate_metadata_synthesis() -> None:
            # This is the fixed phase - now fast instead of blocking
            time.sleep(0.02)  # Was 20 minutes, now ~2 seconds
        
        def _simulate_restore_phase() -> None:
            mock_append_job_event("restore_started", {})
            time.sleep(0.1)
            mock_append_job_event("restore_progress", {"percent": 50})
            time.sleep(0.1)
            mock_append_job_event("restore_complete", {})
        
        # Execute with heartbeat (fast interval for testing)
        with HeartbeatContext(_emit_heartbeat, interval_seconds=0.05):
            _simulate_download_phase()
            _simulate_extraction_phase()
            _simulate_metadata_synthesis()
            _simulate_restore_phase()
        
        # Analyze events
        event_types = [e.event_type for e in job_events]
        
        # Verify workflow events are present
        assert "download_started" in event_types
        assert "download_complete" in event_types
        assert "extraction_started" in event_types
        assert "extraction_complete" in event_types
        assert "restore_started" in event_types
        assert "restore_complete" in event_types
        
        # Verify heartbeats were emitted
        heartbeat_count = sum(1 for t in event_types if t == "heartbeat")
        assert heartbeat_count >= 6, f"Expected >=6 heartbeats, got {heartbeat_count}"
        
        # Verify heartbeats are interspersed throughout workflow
        # (not all at the beginning or end)
        heartbeat_indices = [i for i, e in enumerate(job_events) if e.event_type == "heartbeat"]
        first_heartbeat = heartbeat_indices[0]
        last_heartbeat = heartbeat_indices[-1]
        
        # Heartbeats should span most of the workflow
        assert first_heartbeat < 5, "First heartbeat should be early"
        assert last_heartbeat > len(job_events) - 5, "Last heartbeat should be late"

    def test_stale_detection_would_not_trigger(self) -> None:
        """Verify that stale detection query would not find our job stale.

        The stale detection query is:
        WHERE MAX(job_events.logged_at) < UTC_TIMESTAMP(6) - INTERVAL 15 MINUTE

        With heartbeats every 60 seconds, the max gap is always < 60 seconds.
        """
        event_times: list[datetime] = []
        
        def emit() -> None:
            event_times.append(datetime.now(UTC))
        
        # Simulate a 2-second operation with 0.3s heartbeat interval
        with HeartbeatContext(emit, interval_seconds=0.3):
            time.sleep(2)
        
        # Check that no gap between events exceeds threshold
        MAX_GAP_ALLOWED = 0.5  # Half second for test (real: 60 seconds)
        
        for i in range(1, len(event_times)):
            gap = (event_times[i] - event_times[i-1]).total_seconds()
            assert gap < MAX_GAP_ALLOWED, f"Gap of {gap}s exceeds threshold"

    def test_heartbeat_continues_during_blocking_io(self) -> None:
        """Heartbeat continues even when main thread does blocking I/O.

        This simulates the original problem: metadata synthesis doing
        blocking I/O (decompressing files) with no events.
        """
        heartbeat_times: list[float] = []
        io_operations: list[str] = []
        
        def emit() -> None:
            heartbeat_times.append(time.monotonic())
        
        def blocking_io() -> None:
            """Simulate blocking I/O operations."""
            for i in range(5):
                io_operations.append(f"io_{i}")
                time.sleep(0.1)  # Blocking operation
        
        start = time.monotonic()
        with HeartbeatContext(emit, interval_seconds=0.15):
            blocking_io()
        total_time = time.monotonic() - start
        
        # All I/O should complete
        assert len(io_operations) == 5
        
        # Heartbeats should have been emitted during I/O
        # With 0.5s of I/O and 0.15s interval, expect ~3-4 heartbeats
        assert len(heartbeat_times) >= 3


class TestMetadataSynthesisE2E:
    """End-to-end tests for metadata synthesis with realistic data."""

    @pytest.fixture
    def realistic_backup_dir(self, tmp_path: Path) -> Path:
        """Create a realistic backup directory structure."""
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        
        # Create legacy metadata
        (backup_dir / "metadata").write_text(
            "Started dump at: 2026-01-15 10:00:00\n"
            "SHOW MASTER STATUS:\n"
            "\tLog: mysql-bin.000042\n"
            "\tPos: 154789\n"
            "Finished dump at: 2026-01-15 10:15:00\n"
        )
        
        # Create various table types
        
        # 1. Small tables (direct count)
        for i in range(50):
            path = backup_dir / f"mydb.small_table_{i:02d}.sql.gz"
            content = b"INSERT INTO t VALUES (1);\n" * 100
            with gzip.open(path, "wb") as f:
                f.write(content)
        
        # 2. Chunked tables (mydumper math)
        for t in range(5):
            for c in range(20):  # 20 chunks each
                path = backup_dir / f"mydb.chunked_{t:02d}.{c:05d}.sql.gz"
                content = b"INSERT INTO t VALUES (1);\n" * 1000
                with gzip.open(path, "wb") as f:
                    f.write(content)
        
        # 3. Schema files (should be ignored)
        for t in range(5):
            path = backup_dir / f"mydb.chunked_{t:02d}-schema.sql.gz"
            content = b"CREATE TABLE t (id INT);\n"
            with gzip.open(path, "wb") as f:
                f.write(content)
        
        return backup_dir

    def test_synthesis_produces_valid_ini(self, realistic_backup_dir: Path) -> None:
        """Verify synthesized metadata is valid INI format."""
        synthesize_metadata(str(realistic_backup_dir))
        
        metadata_path = realistic_backup_dir / "metadata"
        content = metadata_path.read_text()
        
        # Check INI structure
        assert "[config]" in content
        assert "[source]" in content
        assert "quote-character = BACKTICK" in content
        
        # Check binlog info preserved
        assert "mysql-bin.000042" in content
        assert "154789" in content
        
        # Check tables are present
        for i in range(50):
            assert f"small_table_{i:02d}" in content
        for t in range(5):
            assert f"chunked_{t:02d}" in content

    def test_ensure_compatible_handles_ini_already(self, realistic_backup_dir: Path) -> None:
        """ensure_compatible_metadata doesn't modify valid INI."""
        # First synthesis
        ensure_compatible_metadata(str(realistic_backup_dir))
        content1 = (realistic_backup_dir / "metadata").read_text()
        mtime1 = (realistic_backup_dir / "metadata").stat().st_mtime
        
        # Wait a tiny bit
        time.sleep(0.01)
        
        # Second call should detect INI and skip
        ensure_compatible_metadata(str(realistic_backup_dir))
        content2 = (realistic_backup_dir / "metadata").read_text()
        mtime2 = (realistic_backup_dir / "metadata").stat().st_mtime
        
        # Content should be identical (no re-synthesis)
        assert content1 == content2
        # mtime might be same (no write) or different (write same content)
        # The key is content is preserved

    def test_synthesis_performance_with_many_tables(self, tmp_path: Path) -> None:
        """Test synthesis performance with many tables."""
        backup_dir = tmp_path / "large_backup"
        backup_dir.mkdir()
        
        # Create legacy metadata
        (backup_dir / "metadata").write_text("Log: bin.001\nPos: 1\n")
        
        # Create 1000 small tables
        for i in range(1000):
            path = backup_dir / f"db.table_{i:04d}.sql.gz"
            with gzip.open(path, "wb") as f:
                f.write(b"INSERT INTO t VALUES (1);\n" * 10)
        
        start = time.monotonic()
        synthesize_metadata(str(backup_dir))
        elapsed = time.monotonic() - start
        
        # 1000 small tables should process quickly
        assert elapsed < 30, f"1000 tables took {elapsed:.1f}s"
        
        # Verify output - count INI sections (each table gets one [section])
        content = (backup_dir / "metadata").read_text()
        # Count section headers for tables: [`db`.`table_XXXX`]
        section_count = content.count("[`db`.`table_")
        assert section_count == 1000, f"Expected 1000 table sections, got {section_count}"


class TestStaleRecoveryIntegration:
    """Tests verifying heartbeat prevents false stale recovery."""

    def test_heartbeat_interval_vs_stale_timeout(self) -> None:
        """Verify timing relationship prevents false positives.

        STALE_RUNNING_TIMEOUT_MINUTES = 15 (900 seconds)
        HEARTBEAT_INTERVAL = 60 seconds
        Safety margin = 900 / 60 = 15x
        """
        STALE_TIMEOUT_SECONDS = 15 * 60  # 900
        HEARTBEAT_INTERVAL = DEFAULT_HEARTBEAT_INTERVAL_SECONDS  # 60
        
        # Safety margin
        safety_margin = STALE_TIMEOUT_SECONDS / HEARTBEAT_INTERVAL
        assert safety_margin >= 10, "Need at least 10x safety margin"
        
        # With 15x margin, a single missed heartbeat won't trigger stale
        # detection. Would need 15 consecutive misses (15 minutes of silence).
        max_consecutive_misses = safety_margin - 1
        assert max_consecutive_misses >= 14

    def test_simulated_stale_detection_query(self) -> None:
        """Simulate the stale detection query logic.

        The real query:
        SELECT ... FROM jobs j
        LEFT JOIN (
            SELECT job_id, MAX(logged_at) AS last_logged_at
            FROM job_events
            GROUP BY job_id
        ) last_event ON last_event.job_id = j.id
        WHERE COALESCE(last_event.last_logged_at, j.started_at)
              < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 15 MINUTE)
        """
        STALE_THRESHOLD_MINUTES = 15
        
        class SimulatedJob:
            def __init__(self):
                self.started_at = datetime.now(UTC)
                self.events: list[datetime] = []
            
            def add_event(self) -> None:
                self.events.append(datetime.now(UTC))
            
            def is_stale(self) -> bool:
                """Check if job would be detected as stale."""
                now = datetime.now(UTC)
                threshold = now - timedelta(minutes=STALE_THRESHOLD_MINUTES)
                
                # COALESCE(last_event, started_at)
                last_activity = self.events[-1] if self.events else self.started_at
                
                return last_activity < threshold
        
        from datetime import timedelta
        
        # Job with no events but just started - not stale
        job = SimulatedJob()
        assert not job.is_stale()
        
        # Job with recent event - not stale
        job.add_event()
        assert not job.is_stale()
        
        # Simulate job with heartbeats during 30-minute operation
        events: list[datetime] = []
        
        def emit() -> None:
            events.append(datetime.now(UTC))
        
        # Fast simulation: 0.3s = 30 minutes, 0.01s = 1 minute
        with HeartbeatContext(emit, interval_seconds=0.02):  # ~2 min intervals
            time.sleep(0.3)  # ~30 minutes
        
        # Should have many events
        assert len(events) >= 10
        
        # Check no gap exceeds stale threshold (scaled)
        # Real: 15 min threshold, 60s interval = 15x margin
        # Test: 0.15s threshold, 0.02s interval = 7.5x margin (lower but still safe)
        for i in range(1, len(events)):
            gap = (events[i] - events[i-1]).total_seconds()
            # Allow 3x the interval (0.06s) for timing variance
            assert gap < 0.06, f"Gap of {gap}s is too large"


class TestFailureScenarios:
    """Tests for failure scenarios and recovery."""

    def test_heartbeat_stops_on_workflow_failure(self) -> None:
        """Heartbeat stops cleanly when workflow fails."""
        heartbeats_after_error: list[float] = []
        error_time = [None]
        
        def emit() -> None:
            if error_time[0]:
                heartbeats_after_error.append(time.monotonic())
        
        with pytest.raises(RuntimeError):
            with HeartbeatContext(emit, interval_seconds=0.02):
                time.sleep(0.1)
                error_time[0] = time.monotonic()
                raise RuntimeError("Workflow failed")
        
        # Wait a bit after context exit
        time.sleep(0.1)
        
        # No heartbeats should have been emitted after error
        assert len(heartbeats_after_error) == 0

    def test_heartbeat_handles_db_connection_failure(self) -> None:
        """Heartbeat continues after database connection failure."""
        emit_results: list[str] = []
        connection_available = [False]
        
        def flaky_db_emit() -> None:
            if not connection_available[0]:
                emit_results.append("failed")
                raise ConnectionError("DB connection lost")
            emit_results.append("success")
        
        # Start with DB down, then restore
        with HeartbeatContext(flaky_db_emit, interval_seconds=0.03):
            time.sleep(0.1)  # DB down
            connection_available[0] = True  # DB restored
            time.sleep(0.1)  # DB up
        
        # Should have both failures and successes
        assert "failed" in emit_results
        assert "success" in emit_results

    def test_concurrent_job_heartbeats_isolated(self) -> None:
        """Multiple concurrent jobs have isolated heartbeats."""
        job1_events: list[str] = []
        job2_events: list[str] = []
        
        def run_job1() -> None:
            def emit() -> None:
                job1_events.append("job1")
            with HeartbeatContext(emit, interval_seconds=0.03):
                time.sleep(0.15)
        
        def run_job2() -> None:
            def emit() -> None:
                job2_events.append("job2")
            with HeartbeatContext(emit, interval_seconds=0.03):
                time.sleep(0.15)
        
        # Run jobs concurrently
        t1 = threading.Thread(target=run_job1)
        t2 = threading.Thread(target=run_job2)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Each job should have its own heartbeats
        assert len(job1_events) >= 3
        assert len(job2_events) >= 3
        
        # Events should be isolated
        assert all(e == "job1" for e in job1_events)
        assert all(e == "job2" for e in job2_events)
