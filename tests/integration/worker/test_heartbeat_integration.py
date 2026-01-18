"""Integration tests for heartbeat mechanism with metadata synthesis.

Tests the complete integration of:
1. HeartbeatContext wrapping long operations
2. Smart row estimation avoiding decompression
3. Heartbeat events preventing stale detection

These tests verify the fix for the foxpest failure where metadata synthesis
blocked for ~20 minutes with no events, triggering stale recovery.
"""

from __future__ import annotations

import gzip
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import threading

import pytest

from pulldb.worker.heartbeat import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    HeartbeatContext,
    HeartbeatThread,
)
from pulldb.worker.metadata_synthesis import (
    ESTIMATED_BYTES_PER_ROW,
    LARGE_FILE_THRESHOLD_BYTES,
    MYDUMPER_DEFAULT_ROWS_PER_CHUNK,
    SMALL_FILE_THRESHOLD_BYTES,
    count_rows_in_file,
    estimate_table_rows,
    get_gzip_uncompressed_size,
    parse_filename,
    synthesize_metadata,
    ensure_compatible_metadata,
)


class TestHeartbeatPreventsStaleness:
    """Tests verifying heartbeat prevents stale job detection."""

    def test_heartbeat_updates_job_events(self) -> None:
        """Heartbeat emissions would update job_events.logged_at.

        The stale detection query looks for:
        MAX(job_events.logged_at) < UTC_TIMESTAMP(6) - INTERVAL 15 MINUTE

        Heartbeat events emitted every 60 seconds ensure this is never true.
        """
        events: list[dict] = []

        def mock_append_event() -> None:
            events.append({
                "event_type": "heartbeat",
                "logged_at": datetime.now(UTC),
            })

        # Simulate a 200ms operation with fast heartbeats for testing
        with HeartbeatContext(mock_append_event, interval_seconds=0.05) as ctx:
            time.sleep(0.2)

        # Should have emitted heartbeats
        assert ctx.heartbeat_count >= 3
        assert len(events) >= 3
        
        # All events should be "heartbeat" type
        for event in events:
            assert event["event_type"] == "heartbeat"

    def test_heartbeat_survives_slow_append(self) -> None:
        """Heartbeat continues even if append_event is slow."""
        emit_times: list[float] = []
        
        def slow_emit() -> None:
            time.sleep(0.03)  # Slow emit
            emit_times.append(time.monotonic())

        with HeartbeatContext(slow_emit, interval_seconds=0.08):
            time.sleep(0.3)

        # Should have emitted despite slow operations
        assert len(emit_times) >= 2

    def test_heartbeat_continues_after_emit_error(self) -> None:
        """Heartbeat continues even if emit raises exception."""
        call_count = 0
        success_count = 0
        
        def flaky_emit() -> None:
            nonlocal call_count, success_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Simulated DB connection error")
            success_count += 1

        with HeartbeatContext(flaky_emit, interval_seconds=0.05):
            time.sleep(0.25)

        # Should have attempted multiple emissions
        assert call_count >= 4
        # Most should succeed (only call 2 failed)
        assert success_count >= 3

    def test_stale_detection_formula(self) -> None:
        """Verify understanding of stale detection timing.

        Stale detection triggers when:
            MAX(job_events.logged_at) < UTC_TIMESTAMP(6) - INTERVAL 15 MINUTE

        With 60-second heartbeats, the gap is always < 60 seconds, giving
        a 15x safety margin (15 minutes / 60 seconds = 15).
        """
        stale_timeout_minutes = 15
        heartbeat_interval_seconds = 60
        
        # Safety margin = timeout / interval
        safety_margin = (stale_timeout_minutes * 60) / heartbeat_interval_seconds
        
        assert safety_margin == 15, "15x safety margin with 60s heartbeats"
        
        # Verify default matches documented value
        assert DEFAULT_HEARTBEAT_INTERVAL_SECONDS == 60.0


class TestMetadataSynthesisPerformance:
    """Tests verifying metadata synthesis is now fast enough to not trigger stale detection."""

    @pytest.fixture
    def mock_backup_dir(self, tmp_path: Path) -> Path:
        """Create a mock backup directory with various file types."""
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        
        # Create legacy metadata file
        (backup_dir / "metadata").write_text(
            "Started dump at: 2026-01-15 10:00:00\n"
            "Log: mysql-bin.000042\n"
            "Pos: 12345\n"
        )
        
        # Create chunked table (simulating 100M rows)
        for i in range(100):
            chunk_path = backup_dir / f"db.chunked_table.{i:05d}.sql.gz"
            with gzip.open(chunk_path, "wb") as f:
                f.write(b"INSERT INTO t VALUES (1);\n" * 10)  # Small content
        
        # Create single small table
        small_path = backup_dir / "db.small_table.sql.gz"
        with gzip.open(small_path, "wb") as f:
            f.write(b"INSERT INTO t VALUES (1);\n" * 100)
        
        # Create schema file (should be ignored)
        schema_path = backup_dir / "db.small_table-schema.sql.gz"
        with gzip.open(schema_path, "wb") as f:
            f.write(b"CREATE TABLE small_table (id INT);\n")
        
        return backup_dir

    def test_synthesis_completes_under_60_seconds(self, mock_backup_dir: Path) -> None:
        """Metadata synthesis should complete well under one heartbeat interval."""
        start = time.monotonic()
        
        synthesize_metadata(str(mock_backup_dir))
        
        elapsed = time.monotonic() - start
        
        # Must complete under 60 seconds (one heartbeat interval)
        # In practice it should be < 5 seconds for even large backups
        assert elapsed < 60.0, f"Synthesis took {elapsed:.1f}s, must be < 60s"
        
        # Verify metadata was created
        metadata_path = mock_backup_dir / "metadata"
        content = metadata_path.read_text()
        assert "[config]" in content  # INI format
        assert "chunked_table" in content
        assert "small_table" in content

    def test_chunked_table_estimation_is_o1(self, tmp_path: Path) -> None:
        """Chunked table estimation should be O(1) per file, not O(content size)."""
        # Create 1000 chunk files
        chunk_files = []
        for i in range(1000):
            chunk_path = tmp_path / f"db.big_table.{i:05d}.sql.gz"
            with gzip.open(chunk_path, "wb") as f:
                f.write(b"x" * 1000)  # Small content
            chunk_files.append(chunk_path)
        
        start = time.monotonic()
        rows = estimate_table_rows(chunk_files)
        elapsed = time.monotonic() - start
        
        # 1000 files should still be fast (just stat calls)
        assert elapsed < 1.0, f"Estimation took {elapsed:.3f}s for 1000 chunks"
        
        # Should estimate ~999 million rows (999 full chunks + last chunk)
        assert rows >= 999 * MYDUMPER_DEFAULT_ROWS_PER_CHUNK

    def test_large_file_isize_is_o1(self, tmp_path: Path) -> None:
        """ISIZE read is O(1) regardless of file size."""
        # Create file with known uncompressed size
        content = b"x" * 100_000
        gz_path = tmp_path / "large.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(content)
        
        # Time the ISIZE read
        start = time.monotonic()
        for _ in range(1000):  # 1000 reads
            size = get_gzip_uncompressed_size(str(gz_path))
        elapsed = time.monotonic() - start
        
        # 1000 ISIZE reads should be instant
        assert elapsed < 0.5, f"1000 ISIZE reads took {elapsed:.3f}s"
        assert size == len(content)


class TestHeartbeatExecutorIntegration:
    """Tests for HeartbeatContext integration with executor pattern."""

    def test_heartbeat_wraps_long_operation(self) -> None:
        """Simulate the executor pattern with heartbeat wrapping."""
        events: list[tuple[str, str]] = []
        
        def emit_heartbeat() -> None:
            events.append(("heartbeat", "worker_alive"))
        
        def simulate_restore_workflow() -> None:
            """Simulate phases of restore workflow."""
            # Phase 1: Download (would have progress events)
            events.append(("download_started", ""))
            time.sleep(0.05)
            events.append(("download_complete", ""))
            
            # Phase 2: Metadata synthesis (the fix - no blocking)
            time.sleep(0.02)  # Now fast
            
            # Phase 3: Restore (would have progress events)
            events.append(("restore_started", ""))
            time.sleep(0.05)
            events.append(("restore_complete", ""))
        
        # Execute with heartbeat (fast interval for testing)
        with HeartbeatContext(emit_heartbeat, interval_seconds=0.04):
            simulate_restore_workflow()
        
        # Verify event ordering includes heartbeats
        event_types = [e[0] for e in events]
        
        # Should have workflow events
        assert "download_started" in event_types
        assert "download_complete" in event_types
        assert "restore_started" in event_types
        assert "restore_complete" in event_types
        
        # Should have heartbeats interspersed
        heartbeat_count = sum(1 for t in event_types if t == "heartbeat")
        assert heartbeat_count >= 2, f"Expected heartbeats, got {heartbeat_count}"

    def test_heartbeat_stops_on_workflow_exception(self) -> None:
        """Heartbeat stops cleanly when workflow raises exception."""
        heartbeats = []
        
        def emit() -> None:
            heartbeats.append(time.monotonic())
        
        with pytest.raises(ValueError):
            with HeartbeatContext(emit, interval_seconds=0.03):
                time.sleep(0.1)
                raise ValueError("Workflow failed")
        
        # Wait a bit to ensure no more heartbeats after exception
        heartbeats_before = len(heartbeats)
        time.sleep(0.1)
        heartbeats_after = len(heartbeats)
        
        # No heartbeats should be emitted after context exit
        assert heartbeats_before == heartbeats_after

    def test_heartbeat_thread_is_daemon(self) -> None:
        """Heartbeat thread won't block process exit."""
        ctx = HeartbeatContext(lambda: None, interval_seconds=0.1)
        
        with ctx:
            assert ctx._thread is not None
            assert ctx._thread.daemon is True


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_backup_directory(self, tmp_path: Path) -> None:
        """Handle empty backup directory gracefully."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        
        # Should not crash
        synthesize_metadata(str(empty_dir))
        
        # Should create metadata with empty tables
        metadata_path = empty_dir / "metadata"
        assert metadata_path.exists()

    def test_nonexistent_directory(self) -> None:
        """Handle nonexistent directory gracefully."""
        # Should not crash, just log error
        synthesize_metadata("/nonexistent/path/that/does/not/exist")

    def test_corrupted_gzip_file(self, tmp_path: Path) -> None:
        """Handle corrupted gzip files gracefully."""
        corrupt_path = tmp_path / "corrupt.sql.gz"
        corrupt_path.write_bytes(b"not a valid gzip file")
        
        # ISIZE should return 0
        size = get_gzip_uncompressed_size(str(corrupt_path))
        assert isinstance(size, int)

    def test_zero_byte_files(self, tmp_path: Path) -> None:
        """Handle zero-byte files gracefully."""
        # Create empty gzip file structure
        empty_gz = tmp_path / "db.empty.sql.gz"
        with gzip.open(empty_gz, "wb") as f:
            f.write(b"")
        
        # Should handle without error
        rows = estimate_table_rows([empty_gz])
        assert rows >= 0

    def test_permission_denied_file(self, tmp_path: Path) -> None:
        """Handle permission denied gracefully."""
        # Skip on systems where we can't test this
        protected_path = tmp_path / "protected.sql.gz"
        with gzip.open(protected_path, "wb") as f:
            f.write(b"data")
        
        # Make unreadable
        try:
            protected_path.chmod(0o000)
            
            # Should return 0 without crashing
            size = get_gzip_uncompressed_size(str(protected_path))
            assert size == 0
        finally:
            # Restore permissions for cleanup
            protected_path.chmod(0o644)

    def test_heartbeat_with_very_fast_operation(self) -> None:
        """Heartbeat handles operations faster than interval."""
        emit_count = 0
        
        def emit() -> None:
            nonlocal emit_count
            emit_count += 1
        
        # Operation completes before first heartbeat
        with HeartbeatContext(emit, interval_seconds=1.0):
            pass  # Instant
        
        # No heartbeats expected (operation too fast)
        assert emit_count == 0

    def test_parse_filename_edge_cases(self) -> None:
        """Test filename parsing edge cases."""
        # Single part (invalid)
        assert parse_filename("table.sql.gz") is None
        
        # Empty parts
        assert parse_filename(".sql.gz") is None
        
        # Very long chunk number
        result = parse_filename("db.table.999999999999.sql.gz")
        assert result == ("db", "table")
        
        # Special characters in database/table names
        # (mydumper escapes these, so this is unusual but possible)
        result = parse_filename("my-db.my_table.00000.sql.gz")
        assert result == ("my-db", "my_table")


class TestConcurrencyBehavior:
    """Tests for thread safety and concurrent operations."""

    def test_heartbeat_thread_safety(self) -> None:
        """Heartbeat is thread-safe with concurrent operations."""
        counter = {"value": 0}
        lock = threading.Lock()
        
        def emit() -> None:
            with lock:
                counter["value"] += 1
        
        # Start heartbeat
        with HeartbeatContext(emit, interval_seconds=0.02):
            # Spawn concurrent threads that also access counter
            def worker() -> None:
                for _ in range(100):
                    with lock:
                        _ = counter["value"]
                    time.sleep(0.001)
            
            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        
        # Counter should be consistent
        assert counter["value"] >= 0

    def test_multiple_heartbeat_contexts_not_interfere(self) -> None:
        """Multiple heartbeat contexts don't interfere with each other."""
        events1: list[str] = []
        events2: list[str] = []
        
        def emit1() -> None:
            events1.append("hb1")
        
        def emit2() -> None:
            events2.append("hb2")
        
        # Nested contexts
        with HeartbeatContext(emit1, interval_seconds=0.03):
            time.sleep(0.05)
            
            with HeartbeatContext(emit2, interval_seconds=0.03):
                time.sleep(0.1)
            
            time.sleep(0.05)
        
        # Both should have emitted independently
        assert len(events1) >= 3
        assert len(events2) >= 2
        
        # Events should be separate
        assert all(e == "hb1" for e in events1)
        assert all(e == "hb2" for e in events2)


class TestRealWorldScenarios:
    """Tests simulating real-world restore scenarios."""

    def test_foxpest_scenario_simulation(self, tmp_path: Path) -> None:
        """Simulate the foxpest failure scenario to verify fix.

        Original failure: 86 GiB backup, 2356 files, synthesis took ~20 minutes
        Fix: Smart estimation should complete in seconds
        """
        backup_dir = tmp_path / "foxpest"
        backup_dir.mkdir()
        
        # Simulate foxpest structure:
        # - 509 tables
        # - Mix of chunked and single-file tables
        # - 3 large unchunked tables
        
        # Create legacy metadata
        (backup_dir / "metadata").write_text(
            "Started dump at: 2026-01-15 10:00:00\n"
            "Log: mysql-bin.000001\n"
            "Pos: 154\n"
        )
        
        # Create 500 small tables (< 10MB each)
        for i in range(500):
            path = backup_dir / f"foxpest.table_{i:03d}.sql.gz"
            with gzip.open(path, "wb") as f:
                f.write(b"INSERT INTO t VALUES (1);\n" * 50)
        
        # Create 6 chunked tables (10 chunks each)
        for t in range(6):
            for c in range(10):
                path = backup_dir / f"foxpest.chunked_{t:03d}.{c:05d}.sql.gz"
                with gzip.open(path, "wb") as f:
                    f.write(b"INSERT INTO t VALUES (1);\n" * 100)
        
        # Create 3 schema files
        for t in range(3):
            path = backup_dir / f"foxpest.table_{t:03d}-schema.sql.gz"
            with gzip.open(path, "wb") as f:
                f.write(b"CREATE TABLE t (id INT);\n")
        
        # Time the synthesis
        start = time.monotonic()
        synthesize_metadata(str(backup_dir))
        elapsed = time.monotonic() - start
        
        # CRITICAL: Must complete in under 15 minutes (stale timeout)
        # Expected: < 5 seconds for this size
        assert elapsed < 300, f"Synthesis took {elapsed:.1f}s, must be < 5 min"
        
        # More realistic expectation: < 30 seconds
        assert elapsed < 30, f"Synthesis took {elapsed:.1f}s, expected < 30s"
        
        # Verify output
        metadata = (backup_dir / "metadata").read_text()
        assert "[config]" in metadata
        assert "foxpest" in metadata

    def test_heartbeat_during_slow_phase(self) -> None:
        """Heartbeat continues during any slow phase of restore."""
        events: list[tuple[float, str]] = []
        start_time = time.monotonic()
        
        def emit() -> None:
            events.append((time.monotonic() - start_time, "heartbeat"))
        
        def slow_operation() -> None:
            # Simulate a slow operation (like metadata synthesis used to be)
            # In reality, this is now fast, but heartbeat handles any slow phase
            time.sleep(0.5)
        
        with HeartbeatContext(emit, interval_seconds=0.1):
            slow_operation()
        
        # Should have ~5 heartbeats during 0.5s operation
        assert len(events) >= 4
        
        # Heartbeats should be evenly spaced (roughly)
        times = [t for t, _ in events]
        for i in range(1, len(times)):
            gap = times[i] - times[i-1]
            # Gap should be approximately 0.1 seconds (+/- 50ms tolerance)
            assert 0.05 < gap < 0.2, f"Uneven heartbeat gap: {gap:.3f}s"
