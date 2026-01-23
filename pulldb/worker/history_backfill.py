"""History backfill safety net for job_history_summary.

Periodically scans for terminal jobs (complete/failed/canceled) that don't have
a corresponding job_history_summary record. This can happen if the worker crashes
or the best-effort history save in _save_job_history_summary() fails.

The primary path is still the worker's synchronous insertion at job completion.
This module provides a safety net to ensure 100% of terminal jobs get history
records, reconstructing data from job_events when the worker path fails.

Data sources for reconstruction:
- jobs table: Core job metadata (owner, target, timestamps)
- backup_selected event: S3 path, size, backup date
- restore_complete event: table_count, total_rows
- restore_profile event: Phase durations, throughput metrics

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pulldb.infra.metrics import MetricLabels, emit_event, emit_gauge

if TYPE_CHECKING:
    from pulldb.infra.mysql import (
        JobHistorySummaryRepository,
        JobRepository,
        MySQLPool,
    )


logger = logging.getLogger(__name__)


# Grace period before considering a job orphaned (worker still inserting)
GRACE_PERIOD_MINUTES = 5

# Don't backfill jobs older than this (historical data loss is accepted)
MAX_AGE_DAYS = 7

# Minimum interval between backfill runs (avoid hammering DB)
MIN_BACKFILL_INTERVAL_SECONDS = 300  # 5 minutes


@dataclass
class BackfillResult:
    """Result of a history backfill run."""

    jobs_found: int
    jobs_backfilled: int
    jobs_failed: int
    job_ids_backfilled: list[str]
    job_ids_failed: list[str]

    @property
    def total_processed(self) -> int:
        return self.jobs_backfilled + self.jobs_failed


@dataclass
class OrphanJob:
    """Job without a history record, with event data for reconstruction."""

    job_id: str
    owner_user_id: str
    owner_username: str
    dbhost: str
    target: str
    custom_target: bool
    submitted_at: datetime
    started_at: datetime | None
    completed_at: datetime
    status: str
    error_detail: str | None
    worker_id: str | None
    # Event data (may be None if events missing)
    backup_selected_event: dict[str, Any] | None
    restore_complete_event: dict[str, Any] | None
    restore_profile_event: dict[str, Any] | None


def find_orphan_jobs(
    pool: "MySQLPool",
    grace_period_minutes: int = GRACE_PERIOD_MINUTES,
    max_age_days: int = MAX_AGE_DAYS,
    limit: int = 100,
) -> list[OrphanJob]:
    """Find terminal jobs without history records.

    Args:
        pool: MySQL connection pool.
        grace_period_minutes: Don't consider jobs orphaned until this many
            minutes after completion (worker may still be inserting).
        max_age_days: Don't backfill jobs older than this (data loss accepted).
        limit: Maximum jobs to return per call.

    Returns:
        List of OrphanJob with event data for reconstruction.
    """
    # Only deployed jobs should have history records
    # (complete = pre-deploy success, deployed = final success after rename)
    # Using direct string for single status - avoids MySQL connector tuple issues
    terminal_status = "deployed"

    with pool.connection() as conn:
        cursor = conn.cursor(dictionary=True)

        # Find jobs without history records within the age window
        cursor.execute(
            """
            SELECT 
                j.id AS job_id,
                j.owner_user_id,
                j.owner_username,
                j.dbhost,
                j.target,
                j.custom_target,
                j.submitted_at,
                j.started_at,
                j.completed_at,
                j.status,
                j.error_detail,
                j.worker_id
            FROM jobs j
            LEFT JOIN job_history_summary h ON j.id = h.job_id
            WHERE j.status = %s
              AND h.job_id IS NULL
              AND j.completed_at < NOW() - INTERVAL %s MINUTE
              AND j.completed_at > NOW() - INTERVAL %s DAY
            ORDER BY j.completed_at ASC
            LIMIT %s
            """,
            (terminal_status, grace_period_minutes, max_age_days, limit),
        )
        job_rows = cursor.fetchall()

        if not job_rows:
            return []

        orphans: list[OrphanJob] = []

        for row in job_rows:
            job_id = row["job_id"]

            # Fetch relevant events for this job
            cursor.execute(
                """
                SELECT event_type, detail
                FROM job_events
                WHERE job_id = %s
                  AND event_type IN ('backup_selected', 'restore_complete', 'restore_profile')
                ORDER BY logged_at ASC
                """,
                (job_id,),
            )
            event_rows = cursor.fetchall()

            # Parse event data
            backup_selected: dict[str, Any] | None = None
            restore_complete: dict[str, Any] | None = None
            restore_profile: dict[str, Any] | None = None

            for event in event_rows:
                event_type = event["event_type"]
                detail = event["detail"]

                if detail:
                    try:
                        parsed = json.loads(detail) if isinstance(detail, str) else detail
                    except json.JSONDecodeError:
                        parsed = None

                    if event_type == "backup_selected" and parsed:
                        backup_selected = parsed
                    elif event_type == "restore_complete" and parsed:
                        restore_complete = parsed
                    elif event_type == "restore_profile" and parsed:
                        restore_profile = parsed

            orphans.append(
                OrphanJob(
                    job_id=job_id,
                    owner_user_id=row["owner_user_id"],
                    owner_username=row["owner_username"],
                    dbhost=row["dbhost"],
                    target=row["target"],
                    custom_target=bool(row["custom_target"]),
                    submitted_at=row["submitted_at"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    status=row["status"],
                    error_detail=row["error_detail"],
                    worker_id=row["worker_id"],
                    backup_selected_event=backup_selected,
                    restore_complete_event=restore_complete,
                    restore_profile_event=restore_profile,
                )
            )

        return orphans


def _map_job_status_to_final_status(status: str) -> str:
    """Map job status to final_status for history table.

    Jobs can be in various terminal states, but history only tracks:
    complete, failed, canceled.
    """
    if status in ("complete", "deployed", "expired", "superseded"):
        return "complete"
    elif status == "failed":
        return "failed"
    elif status == "canceled":
        return "canceled"
    else:
        # Shouldn't happen, but default to complete
        logger.warning("Unexpected status in history backfill: %s", status)
        return "complete"


def _extract_phase_duration(
    profile: dict[str, Any] | None,
    phase_name: str,
) -> float | None:
    """Extract phase duration from restore_profile event."""
    if not profile:
        return None

    phases = profile.get("phases", {})
    phase = phases.get(phase_name, {})
    duration = phase.get("duration_seconds")

    if duration is not None:
        return round(float(duration), 2)
    return None


def _extract_backup_date(s3_key: str | None) -> datetime | None:
    """Extract backup date from S3 key path (format: .../YYYY-MM-DD/...)."""
    if not s3_key:
        return None

    match = re.search(r"/(\d{4}-\d{2}-\d{2})/", s3_key)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    return None


def backfill_orphan_job(
    orphan: OrphanJob,
    history_repo: "JobHistorySummaryRepository",
) -> bool:
    """Backfill a single orphan job's history record.

    Args:
        orphan: OrphanJob with event data.
        history_repo: Repository for inserting history.

    Returns:
        True if successfully backfilled, False otherwise.
    """
    from pulldb.infra.mysql import JobHistorySummaryRepository

    # Map status
    final_status = _map_job_status_to_final_status(orphan.status)

    # Extract from backup_selected event
    backup = orphan.backup_selected_event or {}
    archive_size_bytes = backup.get("size_bytes")
    backup_bucket = backup.get("bucket")
    backup_key = backup.get("key")
    backup_s3_path = f"s3://{backup_bucket}/{backup_key}" if backup_bucket and backup_key else None
    backup_date = _extract_backup_date(backup_key)

    # Extract from restore_complete event
    restore = orphan.restore_complete_event or {}
    table_count = restore.get("table_count")
    total_rows = restore.get("total_rows")

    # Extract from restore_profile event
    profile = orphan.restore_profile_event
    total_duration = profile.get("total_duration_seconds") if profile else None
    if total_duration is not None:
        total_duration = round(float(total_duration), 2)

    # Phase durations
    discovery_duration = _extract_phase_duration(profile, "discovery")
    download_duration = _extract_phase_duration(profile, "download")
    extraction_duration = _extract_phase_duration(profile, "extraction")
    myloader_duration = _extract_phase_duration(profile, "myloader")
    post_sql_duration = _extract_phase_duration(profile, "post_sql")
    metadata_duration = _extract_phase_duration(profile, "metadata")
    atomic_rename_duration = _extract_phase_duration(profile, "atomic_rename")

    # Calculate throughput metrics from profile
    download_mbps: float | None = None
    extracted_size_bytes: int | None = None
    if profile:
        phases = profile.get("phases", {})
        download_phase = phases.get("download", {})
        bytes_per_second = download_phase.get("bytes_per_second")
        if bytes_per_second:
            download_mbps = round(float(bytes_per_second) / (1024 * 1024), 2)
        extracted_size_bytes = download_phase.get("bytes_processed")

    restore_rows_per_second: int | None = None
    if total_rows and myloader_duration and myloader_duration > 0:
        restore_rows_per_second = int(total_rows / myloader_duration)

    # Categorize error if failed
    error_category: str | None = None
    if final_status in ("failed", "canceled") and orphan.error_detail:
        if final_status == "canceled":
            error_category = "canceled_by_user"
        else:
            error_category = JobHistorySummaryRepository.categorize_error(orphan.error_detail)

    # Insert the backfilled record
    return history_repo.insert(
        job_id=orphan.job_id,
        owner_user_id=orphan.owner_user_id,
        owner_username=orphan.owner_username,
        dbhost=orphan.dbhost,
        target=orphan.target,
        custom_target=orphan.custom_target,
        submitted_at=orphan.submitted_at,
        started_at=orphan.started_at,
        completed_at=orphan.completed_at,
        final_status=final_status,
        error_category=error_category,
        archive_size_bytes=archive_size_bytes,
        extracted_size_bytes=extracted_size_bytes,
        table_count=table_count,
        total_rows=total_rows,
        total_duration_seconds=total_duration,
        discovery_duration_seconds=discovery_duration,
        download_duration_seconds=download_duration,
        extraction_duration_seconds=extraction_duration,
        myloader_duration_seconds=myloader_duration,
        post_sql_duration_seconds=post_sql_duration,
        metadata_duration_seconds=metadata_duration,
        atomic_rename_duration_seconds=atomic_rename_duration,
        download_mbps=download_mbps,
        restore_rows_per_second=restore_rows_per_second,
        backup_date=backup_date,
        backup_s3_path=backup_s3_path,
        worker_id=orphan.worker_id,
    )


def run_history_backfill(
    pool: "MySQLPool",
    history_repo: "JobHistorySummaryRepository",
) -> BackfillResult:
    """Run the history backfill safety net.

    Finds orphan jobs and backfills their history records from event data.

    Args:
        pool: MySQL connection pool.
        history_repo: Repository for job history summary operations.

    Returns:
        BackfillResult with counts and IDs.
    """
    orphans = find_orphan_jobs(pool)

    if not orphans:
        return BackfillResult(
            jobs_found=0,
            jobs_backfilled=0,
            jobs_failed=0,
            job_ids_backfilled=[],
            job_ids_failed=[],
        )

    logger.info(
        "Found %d orphan jobs for history backfill",
        len(orphans),
        extra={"phase": "history_backfill"},
    )

    backfilled: list[str] = []
    failed: list[str] = []

    for orphan in orphans:
        try:
            if backfill_orphan_job(orphan, history_repo):
                backfilled.append(orphan.job_id)
                logger.info(
                    "Backfilled history for job %s",
                    orphan.job_id,
                    extra={"job_id": orphan.job_id, "phase": "history_backfill"},
                )
            else:
                # Insert returned False - likely duplicate
                failed.append(orphan.job_id)
                logger.debug(
                    "Backfill insert returned False for job %s (may already exist)",
                    orphan.job_id,
                    extra={"job_id": orphan.job_id, "phase": "history_backfill"},
                )
        except Exception as e:
            failed.append(orphan.job_id)
            logger.warning(
                "Failed to backfill history for job %s: %s",
                orphan.job_id,
                e,
                extra={"job_id": orphan.job_id, "phase": "history_backfill"},
                exc_info=True,
            )

    result = BackfillResult(
        jobs_found=len(orphans),
        jobs_backfilled=len(backfilled),
        jobs_failed=len(failed),
        job_ids_backfilled=backfilled,
        job_ids_failed=failed,
    )

    # Emit metrics
    emit_gauge(
        "history_backfill_count",
        result.jobs_backfilled,
        MetricLabels(phase="history_backfill"),
    )

    if result.jobs_backfilled > 0:
        logger.warning(
            "Backfilled %d history records (worker history saves may be failing)",
            result.jobs_backfilled,
            extra={
                "phase": "history_backfill",
                "backfilled": result.jobs_backfilled,
                "failed": result.jobs_failed,
            },
        )
        emit_event(
            "history_backfill_completed",
            f"Backfilled {result.jobs_backfilled} records",
            MetricLabels(phase="history_backfill", status="warning"),
        )

    return result


class HistoryBackfillTracker:
    """Tracks last backfill run to enforce minimum interval.

    Used in the poll loop to avoid running backfill too frequently.
    """

    def __init__(self, min_interval_seconds: int = MIN_BACKFILL_INTERVAL_SECONDS) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._last_run: datetime | None = None

    def should_run(self) -> bool:
        """Check if enough time has passed since last run."""
        if self._last_run is None:
            return True
        elapsed = (datetime.now(UTC) - self._last_run).total_seconds()
        return elapsed >= self.min_interval_seconds

    def mark_run(self) -> None:
        """Mark that a backfill run just completed."""
        self._last_run = datetime.now(UTC)


# Module-level tracker for poll loop integration
_backfill_tracker = HistoryBackfillTracker()


def try_run_history_backfill(
    pool: "MySQLPool",
    history_repo: "JobHistorySummaryRepository",
) -> BackfillResult | None:
    """Run history backfill if interval has elapsed.

    Used by poll loop to periodically run backfill without flooding.

    Args:
        pool: MySQL connection pool.
        history_repo: Repository for job history summary operations.

    Returns:
        BackfillResult if backfill ran, None if skipped (too soon).
    """
    if not _backfill_tracker.should_run():
        return None

    result = run_history_backfill(pool, history_repo)
    _backfill_tracker.mark_run()
    return result
