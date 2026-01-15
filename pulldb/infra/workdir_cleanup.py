"""Work directory cleanup for pullDB job management.

Provides cleanup of work directories (/work/pulldb.service/{job_id}) for:
1. Hard-deleted jobs (immediate cleanup after job record removal)
2. Orphan directories (periodic scanner for jobs that don't exist or are soft-deleted)

HCA Layer: shared (pulldb/infra/)

Design:
    - cleanup_job_work_dir(): Shared function for immediate cleanup on hard delete
    - WorkDirCleaner: Background thread that periodically scans for orphan directories
    - Uses MySQL advisory lock to prevent concurrent cleaners across workers
    - Dry-run mode for safe rollout (logs what would be deleted without deleting)

Usage:
    # Immediate cleanup on hard delete:
    from pulldb.infra.workdir_cleanup import cleanup_job_work_dir
    cleanup_job_work_dir(job_id, work_dir)

    # Periodic orphan scanner (in worker service):
    from pulldb.infra.workdir_cleanup import WorkDirCleaner

    cleaner = WorkDirCleaner(
        pool=mysql_pool,
        job_repo=job_repo,
        work_dir=config.work_dir,
    )
    cleaner.start()

    # Later, to stop:
    cleaner.stop()
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pulldb.domain.models import JobStatus
    from pulldb.infra.mysql import JobRepository, MySQLPool

logger = logging.getLogger(__name__)

# Default interval for orphan cleanup (1 hour)
DEFAULT_CLEANUP_INTERVAL = 3600

# MySQL advisory lock name for preventing concurrent cleaners
WORKDIR_CLEANUP_LOCK = "pulldb_workdir_cleanup"

# UUID format validation constants
UUID_LENGTH = 36
UUID_DASH_COUNT = 4


def cleanup_job_work_dir(
    job_id: str,
    work_dir: Path | str,
    dry_run: bool = False,
) -> bool:
    """Remove work directory for a specific job.

    This is the shared cleanup function used by:
    - Hard delete endpoint in admin routes
    - Bulk delete task handler
    - Orphan scanner

    Args:
        job_id: Job UUID whose work directory should be cleaned.
        work_dir: Base work directory path (e.g., /work/pulldb.service).
        dry_run: If True, log what would be deleted but don't delete.

    Returns:
        True if directory was removed (or didn't exist), False on error.
    """
    work_dir = Path(work_dir) if isinstance(work_dir, str) else work_dir
    job_dir = work_dir / job_id

    if not job_dir.exists():
        logger.debug("Work directory does not exist: %s", job_dir)
        return True

    # Get size for logging
    try:
        total_size = sum(f.stat().st_size for f in job_dir.rglob("*") if f.is_file())
        size_mb = total_size / (1024 * 1024)
    except Exception:
        size_mb = 0.0

    if dry_run:
        logger.info(
            "DRY-RUN: Would delete work directory %s (%.1f MB)",
            job_dir,
            size_mb,
        )
        return True

    try:
        shutil.rmtree(job_dir)
        logger.info(
            "Removed work directory %s (%.1f MB)",
            job_dir,
            size_mb,
        )
        return True
    except Exception as e:
        logger.warning("Failed to remove work directory %s: %s", job_dir, e)
        return False


class WorkDirCleaner:
    """Periodically scans for orphan work directories and cleans them up.

    An orphan directory is one where:
    - The job record doesn't exist in the database, OR
    - The job is soft-deleted (status='deleted')

    Uses MySQL advisory lock to ensure only one worker performs cleanup
    at a time across the cluster.
    """

    def __init__(
        self,
        pool: MySQLPool,
        job_repo: JobRepository,
        work_dir: Path | str,
        check_interval: float = DEFAULT_CLEANUP_INTERVAL,
        dry_run: bool = True,
    ) -> None:
        """Initialize the work directory cleaner.

        Args:
            pool: MySQL pool for job lookups and advisory lock.
            job_repo: JobRepository for checking job status.
            work_dir: Base work directory path.
            check_interval: Seconds between scans (default 3600 = 1 hour).
            dry_run: If True, log but don't delete (for safe rollout).
        """
        self._pool = pool
        self._job_repo = job_repo
        self._work_dir = Path(work_dir) if isinstance(work_dir, str) else work_dir
        self._check_interval = check_interval
        self._dry_run = dry_run
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the orphan scanner thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._cleanup_loop,
            name="WorkDirCleaner",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "WorkDirCleaner started (interval=%ds, dry_run=%s, work_dir=%s)",
            int(self._check_interval),
            self._dry_run,
            self._work_dir,
        )

    def stop(self) -> None:
        """Stop the orphan scanner thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("WorkDirCleaner stopped")

    def _cleanup_loop(self) -> None:
        """Main cleanup loop running in background thread."""
        while self._running:
            time.sleep(self._check_interval)

            if not self._running:
                return

            try:
                self._scan_and_cleanup()
            except Exception as e:
                logger.warning("WorkDirCleaner scan failed: %s", e)

    def _scan_and_cleanup(self) -> None:
        """Scan work directory and clean up orphan directories.

        Uses MySQL advisory lock to prevent concurrent cleanup across workers.
        """
        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT GET_LOCK(%s, 0)", (WORKDIR_CLEANUP_LOCK,))
            result = cursor.fetchone()
            lock_acquired = result and result[0] == 1
            cursor.close()

            if not lock_acquired:
                logger.debug(
                    "WorkDirCleaner: another worker holds the lock, skipping"
                )
                return

            try:
                self._do_cleanup()
            finally:
                # Release lock
                cursor = conn.cursor()
                cursor.execute("SELECT RELEASE_LOCK(%s)", (WORKDIR_CLEANUP_LOCK,))
                cursor.close()

    def _do_cleanup(self) -> None:
        """Perform the actual cleanup scan. Called while holding the lock."""
        from pulldb.domain.models import JobStatus

        if not self._work_dir.exists():
            logger.debug("Work directory does not exist: %s", self._work_dir)
            return

        orphan_count = 0
        orphan_bytes = 0
        cleaned_count = 0

        for entry in self._work_dir.iterdir():
            if not entry.is_dir():
                continue

            job_id = entry.name

            # Skip if not a UUID-like name
            if len(job_id) != UUID_LENGTH or job_id.count("-") != UUID_DASH_COUNT:
                continue

            # Check if job is orphaned (doesn't exist or is soft-deleted)
            is_orphan, dir_size = self._check_orphan_status(job_id, JobStatus)

            if is_orphan:
                orphan_count += 1
                orphan_bytes += dir_size

                success = cleanup_job_work_dir(
                    job_id, self._work_dir, dry_run=self._dry_run
                )
                if success and not self._dry_run:
                    cleaned_count += 1

        self._log_cleanup_summary(orphan_count, orphan_bytes, cleaned_count)

    def _check_orphan_status(
        self, job_id: str, job_status_enum: type[JobStatus]
    ) -> tuple[bool, int]:
        """Check if a job directory is orphaned and get its size.

        Args:
            job_id: The job UUID to check.
            job_status_enum: JobStatus enum class for comparison.

        Returns:
            Tuple of (is_orphan, directory_size_bytes).
        """
        job = self._job_repo.get_job_by_id(job_id)

        is_orphan = False
        if job is None:
            is_orphan = True
        elif job.status == job_status_enum.DELETED:
            is_orphan = True

        dir_size = 0
        if is_orphan:
            try:
                job_dir = self._work_dir / job_id
                dir_size = sum(
                    f.stat().st_size for f in job_dir.rglob("*") if f.is_file()
                )
            except Exception:
                pass

        return is_orphan, dir_size

    def _log_cleanup_summary(
        self, orphan_count: int, orphan_bytes: int, cleaned_count: int
    ) -> None:
        """Log summary of cleanup operation."""
        orphan_mb = orphan_bytes / (1024 * 1024)
        if orphan_count > 0:
            if self._dry_run:
                logger.info(
                    "WorkDirCleaner DRY-RUN: %d orphan dir(s) (%.1f MB) "
                    "identified but not removed",
                    orphan_count,
                    orphan_mb,
                )
            else:
                logger.info(
                    "WorkDirCleaner: cleaned %d/%d orphan dir(s) (%.1f MB)",
                    cleaned_count,
                    orphan_count,
                    orphan_mb,
                )
        else:
            logger.debug("WorkDirCleaner: no orphan directories found")

    def force_scan(self) -> None:
        """Force an immediate cleanup scan (for testing/manual trigger)."""
        self._scan_and_cleanup()
