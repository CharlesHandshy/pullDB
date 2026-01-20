"""Restore profiling module.

Provides instrumentation for measuring restore workflow phase durations
and data throughput. Captures per-phase timing and sizes for performance
analysis and bottleneck identification.

Phase 1 Feature: Performance Profiling
- Instrument restore phases: discovery, download, extraction, myloader, post-SQL, rename
- Capture per-phase timing and data volume metrics
- Generate percentile distributions from production runs
- Profile storage and retrieval via job_events

FAIL HARD Boundaries:
- Profiling overhead must not degrade restore performance >5%
- Profile data collection failures must not fail restores
- Missing profile data triggers warning log but continues restore

HCA Layer: features
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pulldb.infra.logging import get_logger


logger = get_logger("pulldb.worker.profiling")


class RestorePhase(str, Enum):
    """Restore workflow phases for profiling."""

    DISCOVERY = "discovery"
    DOWNLOAD = "download"
    EXTRACTION = "extraction"
    MYLOADER = "myloader"
    POST_SQL = "post_sql"
    METADATA = "metadata"
    ATOMIC_RENAME = "atomic_rename"
    TOTAL = "total"


@dataclass
class PhaseProfile:
    """Profile data for a single restore phase.

    Attributes:
        phase: Phase identifier.
        started_at: When phase started (UTC).
        completed_at: When phase completed (UTC).
        duration_seconds: Elapsed wall-clock time.
        bytes_processed: Data volume processed (if applicable).
        bytes_per_second: Throughput rate (if applicable).
        metadata: Additional phase-specific metrics.
    """

    phase: RestorePhase
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    bytes_processed: int | None = None
    bytes_per_second: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def mbps(self) -> float | None:
        """Calculate throughput in MB/s for display."""
        if self.bytes_per_second is None:
            return None
        return self.bytes_per_second / (1024 * 1024)

    def complete(self, bytes_processed: int | None = None) -> None:
        """Mark phase as complete and calculate duration.

        Args:
            bytes_processed: Optional data volume for throughput calculation.
        """
        self.completed_at = datetime.now(UTC)
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        if bytes_processed is not None:
            self.bytes_processed = bytes_processed
            if self.duration_seconds > 0:
                self.bytes_per_second = bytes_processed / self.duration_seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat(),
        }
        if self.completed_at:
            result["completed_at"] = self.completed_at.isoformat()
        if self.duration_seconds is not None:
            result["duration_seconds"] = round(self.duration_seconds, 3)
        if self.bytes_processed is not None:
            result["bytes_processed"] = self.bytes_processed
        if self.bytes_per_second is not None:
            result["bytes_per_second"] = round(self.bytes_per_second, 2)
            result["mbps"] = round(self.bytes_per_second / (1024 * 1024), 2)
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class RestoreProfile:
    """Complete profile for a restore workflow.

    Aggregates phase profiles and provides summary statistics.

    Attributes:
        job_id: Job UUID.
        started_at: When profiling started.
        completed_at: When profiling completed.
        phases: Individual phase profiles.
        total_bytes: Total data volume processed.
    """

    job_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    phases: dict[RestorePhase, PhaseProfile] = field(default_factory=dict)
    total_bytes: int = 0
    error: str | None = None

    def start_phase(
        self,
        phase: RestorePhase,
        metadata: dict[str, Any] | None = None,
    ) -> PhaseProfile:
        """Begin profiling a phase.

        Args:
            phase: Phase to profile.
            metadata: Optional initial metadata.

        Returns:
            PhaseProfile for the started phase.
        """
        profile = PhaseProfile(
            phase=phase,
            started_at=datetime.now(UTC),
            metadata=metadata or {},
        )
        self.phases[phase] = profile
        logger.debug(
            f"Phase started: {phase.value}",
            extra={"job_id": self.job_id, "phase": phase.value},
        )
        return profile

    def complete_phase(
        self,
        phase: RestorePhase,
        bytes_processed: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PhaseProfile | None:
        """Complete profiling for a phase.

        Args:
            phase: Phase to complete.
            bytes_processed: Optional data volume.
            metadata: Optional additional metadata to merge.

        Returns:
            Completed PhaseProfile or None if phase wasn't started.
        """
        profile = self.phases.get(phase)
        if profile is None:
            logger.warning(
                f"Cannot complete unstarted phase: {phase.value}",
                extra={"job_id": self.job_id, "phase": phase.value},
            )
            return None

        profile.complete(bytes_processed)
        if metadata:
            profile.metadata.update(metadata)

        if bytes_processed:
            self.total_bytes += bytes_processed

        logger.debug(
            f"Phase completed: {phase.value} ({profile.duration_seconds:.2f}s)",
            extra={
                "job_id": self.job_id,
                "phase": phase.value,
                "duration_seconds": profile.duration_seconds,
                "bytes_processed": bytes_processed,
            },
        )
        return profile

    def complete(self, error: str | None = None) -> None:
        """Mark entire profile as complete.

        Args:
            error: Optional error message if restore failed.
        """
        self.completed_at = datetime.now(UTC)
        self.error = error

    @property
    def total_duration_seconds(self) -> float | None:
        """Total wall-clock duration of restore."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    @property
    def phase_breakdown(self) -> dict[str, float]:
        """Percentage breakdown of time per phase."""
        total = self.total_duration_seconds
        if not total or total == 0:
            return {}
        breakdown = {}
        for phase, profile in self.phases.items():
            if profile.duration_seconds is not None:
                breakdown[phase.value] = round(
                    (profile.duration_seconds / total) * 100, 1
                )
        return breakdown

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "job_id": self.job_id,
            "started_at": self.started_at.isoformat(),
            "phases": {p.value: prof.to_dict() for p, prof in self.phases.items()},
        }
        if self.completed_at:
            result["completed_at"] = self.completed_at.isoformat()
        if self.total_duration_seconds is not None:
            result["total_duration_seconds"] = round(self.total_duration_seconds, 3)
        if self.total_bytes:
            result["total_bytes"] = self.total_bytes
        result["phase_breakdown_percent"] = self.phase_breakdown
        if self.error:
            result["error"] = self.error
        return result

    def to_event_detail(self) -> str:
        """Generate JSON string for job_events detail column."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


class RestoreProfiler:
    """Context manager for profiling restore workflows.

    Usage:
        profiler = RestoreProfiler(job_id)
        with profiler.phase(RestorePhase.DOWNLOAD) as p:
            # do download
            p.metadata["bucket"] = "my-bucket"
        profiler.complete()
        event_detail = profiler.profile.to_event_detail()

    FAIL HARD Note: Profiler failures are logged but never propagate.
    """

    def __init__(self, job_id: str, enabled: bool = True) -> None:
        """Initialize profiler.

        Args:
            job_id: Job UUID to profile.
            enabled: Whether profiling is active (default True).
        """
        self.job_id = job_id
        self.enabled = enabled
        self.profile = RestoreProfile(job_id=job_id)
        self._active_phase: RestorePhase | None = None
        self._phase_start_time: float | None = None

    @contextmanager
    def phase(
        self,
        phase: RestorePhase,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[PhaseProfile, None, None]:
        """Context manager for profiling a phase.

        Args:
            phase: Phase to profile.
            metadata: Optional initial metadata.

        Yields:
            PhaseProfile that can be enriched with metadata.

        Note:
            Exceptions in the phase are NOT caught - profiling is
            best-effort and should never affect restore behavior.
        """
        if not self.enabled:
            # Return a dummy profile that won't be stored
            dummy = PhaseProfile(phase=phase, started_at=datetime.now(UTC))
            yield dummy
            return

        try:
            profile = self.profile.start_phase(phase, metadata)
            self._active_phase = phase
            self._phase_start_time = time.perf_counter()
        except Exception:
            # FAIL HARD: profiling setup failure must not stop restore
            logger.exception(
                "Failed to start phase profiling",
                extra={"job_id": self.job_id, "phase": phase.value},
            )
            dummy = PhaseProfile(phase=phase, started_at=datetime.now(UTC))
            yield dummy
            return

        try:
            yield profile
        finally:
            try:
                # Calculate bytes from metadata if available
                bytes_processed = profile.metadata.get("bytes_processed")
                self.profile.complete_phase(phase, bytes_processed)
                self._active_phase = None
                self._phase_start_time = None
            except Exception:
                # FAIL HARD: profiling completion failure must not stop restore
                logger.exception(
                    "Failed to complete phase profiling",
                    extra={"job_id": self.job_id, "phase": phase.value},
                )

    def complete(self, error: str | None = None) -> None:
        """Complete profiling for the entire restore.

        Args:
            error: Optional error message if restore failed.
        """
        if not self.enabled:
            return
        try:
            self.profile.complete(error)
            logger.info(
                "Restore profile complete",
                extra={
                    "job_id": self.job_id,
                    "total_duration_seconds": self.profile.total_duration_seconds,
                    "phase_breakdown": self.profile.phase_breakdown,
                    "total_bytes": self.profile.total_bytes,
                    "error": error,
                },
            )
        except Exception:
            # FAIL HARD: profile completion failure must not stop restore
            logger.exception(
                "Failed to complete restore profiling",
                extra={"job_id": self.job_id},
            )


def parse_profile_from_event(event_detail: str) -> RestoreProfile | None:
    """Parse a RestoreProfile from job_events detail JSON.

    Args:
        event_detail: JSON string from job_events.detail column.

    Returns:
        Parsed RestoreProfile or None if parsing fails.
    """
    try:
        data = json.loads(event_detail)
        profile = RestoreProfile(
            job_id=data.get("job_id", ""),
            started_at=datetime.fromisoformat(data["started_at"]),
            total_bytes=data.get("total_bytes", 0),
            error=data.get("error"),
        )
        if data.get("completed_at"):
            profile.completed_at = datetime.fromisoformat(data["completed_at"])

        for phase_name, phase_data in data.get("phases", {}).items():
            try:
                phase = RestorePhase(phase_name)
                phase_profile = PhaseProfile(
                    phase=phase,
                    started_at=datetime.fromisoformat(phase_data["started_at"]),
                )
                if phase_data.get("completed_at"):
                    phase_profile.completed_at = datetime.fromisoformat(
                        phase_data["completed_at"]
                    )
                phase_profile.duration_seconds = phase_data.get("duration_seconds")
                phase_profile.bytes_processed = phase_data.get("bytes_processed")
                phase_profile.bytes_per_second = phase_data.get("bytes_per_second")
                phase_profile.metadata = phase_data.get("metadata", {})
                profile.phases[phase] = phase_profile
            except (KeyError, ValueError):
                continue

        return profile
    except Exception:
        logger.exception("Failed to parse profile from event")
        return None


__all__ = [
    "PhaseProfile",
    "RestorePhase",
    "RestoreProfile",
    "RestoreProfiler",
    "parse_profile_from_event",
]
