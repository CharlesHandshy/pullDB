"""MySQL job history summary repository for pullDB.

Implements the JobHistorySummaryRepository class for analytics,
error categorization, and historical job tracking.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from mysql.connector import errors as mysql_errors

from pulldb.infra.mysql_pool import (
    MySQLPool,
    TypedDictCursor,
    TypedTupleCursor,
)

logger = logging.getLogger(__name__)

class JobHistorySummaryRepository:
    """Repository for job history summary operations.
    
    Isolated table for long-term job analytics. No foreign keys, manual
    management only via admin UI.
    
    HCA Layer: shared (pulldb/infra/)
    """
    
    # Valid ENUM values matching schema definition
    VALID_STATUSES = frozenset({"complete", "failed", "canceled"})
    VALID_ERROR_CATEGORIES = frozenset({
        "download_timeout", "download_failed", "extraction_failed",
        "mysql_error", "disk_full", "s3_access_denied",
        "canceled_by_user", "worker_crash", "uncategorized",
    })
    
    # Error category mapping from exception types/messages
    # IMPORTANT: Order matters - first match wins. More specific patterns should come first.
    # mysql_error checked before download_timeout to properly categorize "MySQL timeout" errors.
    ERROR_CATEGORIES = {
        "mysql_error": ["mysql", "database error", "connection refused", "access denied"],
        "download_timeout": ["timeout", "timed out", "deadline exceeded"],
        "download_failed": ["download failed", "s3 download", "connection reset"],
        "extraction_failed": ["extraction", "unpack", "tarball", "decompress"],
        "disk_full": ["no space", "disk full", "quota exceeded", "enospc"],
        "s3_access_denied": ["accessdenied", "forbidden", "invalid credentials"],
        "canceled_by_user": ["cancel", "aborted by user"],
        "worker_crash": ["worker", "crash", "segfault", "killed"],
    }
    
    def __init__(self, pool: MySQLPool) -> None:
        """Initialize repository with connection pool."""
        self.pool = pool
    
    def insert(
        self,
        *,
        job_id: str,
        owner_user_id: str,
        owner_username: str,
        dbhost: str,
        target: str,
        custom_target: bool,
        submitted_at: datetime,
        started_at: datetime | None,
        completed_at: datetime,
        final_status: str,
        error_category: str | None = None,
        archive_size_bytes: int | None = None,
        extracted_size_bytes: int | None = None,
        table_count: int | None = None,
        total_rows: int | None = None,
        total_duration_seconds: float | None = None,
        discovery_duration_seconds: float | None = None,
        download_duration_seconds: float | None = None,
        extraction_duration_seconds: float | None = None,
        myloader_duration_seconds: float | None = None,
        post_sql_duration_seconds: float | None = None,
        metadata_duration_seconds: float | None = None,
        atomic_rename_duration_seconds: float | None = None,
        download_mbps: float | None = None,
        restore_rows_per_second: int | None = None,
        backup_date: datetime | None = None,
        backup_s3_path: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        """Insert a job history summary record.
        
        Args:
            All job summary fields.
            
        Returns:
            True if inserted, False if duplicate (already exists).
        """
        # Validate ENUM values before attempting insert
        if final_status not in self.VALID_STATUSES:
            logger.error(
                "Invalid final_status for job history: %s (job_id=%s)",
                final_status, job_id,
            )
            return False
        if error_category is not None and error_category not in self.VALID_ERROR_CATEGORIES:
            logger.error(
                "Invalid error_category for job history: %s (job_id=%s)",
                error_category, job_id,
            )
            return False
        
        try:
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO job_history_summary (
                        job_id, owner_user_id, owner_username, dbhost, target,
                        custom_target, submitted_at, started_at, completed_at,
                        final_status, error_category, archive_size_bytes,
                        extracted_size_bytes, table_count, total_rows,
                        total_duration_seconds, discovery_duration_seconds,
                        download_duration_seconds, extraction_duration_seconds,
                        myloader_duration_seconds, post_sql_duration_seconds,
                        metadata_duration_seconds, atomic_rename_duration_seconds,
                        download_mbps, restore_rows_per_second, backup_date,
                        backup_s3_path, worker_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        job_id, owner_user_id, owner_username, dbhost, target,
                        1 if custom_target else 0, submitted_at, started_at, completed_at,
                        final_status, error_category, archive_size_bytes,
                        extracted_size_bytes, table_count, total_rows,
                        total_duration_seconds, discovery_duration_seconds,
                        download_duration_seconds, extraction_duration_seconds,
                        myloader_duration_seconds, post_sql_duration_seconds,
                        metadata_duration_seconds, atomic_rename_duration_seconds,
                        download_mbps, restore_rows_per_second,
                        backup_date.date() if backup_date else None,
                        backup_s3_path, worker_id,
                    ),
                )
                conn.commit()
                logger.info("Inserted job history summary", extra={"job_id": job_id})
                return True
        except mysql_errors.IntegrityError:
            logger.debug("Job history summary already exists: %s", job_id)
            return False
        except mysql_errors.Error as e:
            logger.warning("Failed to insert job history summary: %s", e, exc_info=True)
            return False
    
    def delete_by_ids(self, job_ids: list[str]) -> int:
        """Delete specific history records by job ID.
        
        Args:
            job_ids: List of job IDs to delete.
            
        Returns:
            Number of records deleted.
        """
        if not job_ids:
            return 0
        
        # Batch large ID lists to avoid oversized queries
        batch_size = 1000
        total_deleted = 0
        
        for i in range(0, len(job_ids), batch_size):
            batch = job_ids[i:i + batch_size]
            placeholders = ",".join(["%s"] * len(batch))
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM job_history_summary WHERE job_id IN ({placeholders})",
                    batch,
                )
                conn.commit()
                total_deleted += cursor.rowcount
        
        logger.info("Deleted %d job history records by ID", total_deleted)
        return total_deleted
    
    def delete_by_date(
        self,
        before: datetime | None = None,
        after: datetime | None = None,
        batch_size: int = 10000,
    ) -> int:
        """Delete history records within a date range.
        
        Uses batched deletes to prevent long-running transactions.
        
        Args:
            before: Delete records completed before this date.
            after: Delete records completed after this date.
            batch_size: Max records to delete per transaction (default 10000).
            
        Returns:
            Number of records deleted.
            
        Raises:
            ValueError: If neither date boundary provided.
        """
        conditions: list[str] = []
        params: list[Any] = []
        
        if before:
            conditions.append("completed_at < %s")
            params.append(before)
        if after:
            conditions.append("completed_at > %s")
            params.append(after)
        
        if not conditions:
            raise ValueError("At least one date boundary required")
        
        total_deleted = 0
        while True:
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM job_history_summary WHERE {' AND '.join(conditions)} "
                    f"LIMIT %s",
                    params + [batch_size],
                )
                conn.commit()
                batch_deleted = cursor.rowcount
                total_deleted += batch_deleted
                if batch_deleted < batch_size:
                    break
        
        logger.info("Deleted %d job history records by date range", total_deleted)
        return total_deleted
    
    def delete_by_user(
        self,
        user_id: str | None = None,
        username: str | None = None,
        before: datetime | None = None,
        batch_size: int = 10000,
    ) -> int:
        """Delete history records for a specific user.
        
        Uses batched deletes to prevent long-running transactions.
        
        Args:
            user_id: User UUID to delete records for.
            username: Username to delete records for.
            before: Optional cutoff date.
            batch_size: Max records to delete per transaction (default 10000).
            
        Returns:
            Number of records deleted.
            
        Raises:
            ValueError: If neither user_id nor username provided.
        """
        conditions: list[str] = []
        params: list[Any] = []
        
        if user_id:
            conditions.append("owner_user_id = %s")
            params.append(user_id)
        elif username:
            conditions.append("owner_username = %s")
            params.append(username)
        else:
            raise ValueError("user_id or username required")
        
        if before:
            conditions.append("completed_at < %s")
            params.append(before)
        
        total_deleted = 0
        while True:
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM job_history_summary WHERE {' AND '.join(conditions)} "
                    f"LIMIT %s",
                    params + [batch_size],
                )
                conn.commit()
                batch_deleted = cursor.rowcount
                total_deleted += batch_deleted
                if batch_deleted < batch_size:
                    break
        
        logger.info("Deleted %d job history records for user", total_deleted)
        return total_deleted
    
    def delete_by_host(
        self,
        dbhost: str,
        before: datetime | None = None,
        batch_size: int = 10000,
    ) -> int:
        """Delete history records for a specific database host.
        
        Uses batched deletes to prevent long-running transactions.
        
        Args:
            dbhost: Database host to delete records for.
            before: Optional cutoff date.
            batch_size: Max records to delete per transaction (default 10000).
            
        Returns:
            Number of records deleted.
        """
        conditions = ["dbhost = %s"]
        params: list[Any] = [dbhost]
        
        if before:
            conditions.append("completed_at < %s")
            params.append(before)
        
        total_deleted = 0
        while True:
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM job_history_summary WHERE {' AND '.join(conditions)} "
                    f"LIMIT %s",
                    params + [batch_size],
                )
                conn.commit()
                batch_deleted = cursor.rowcount
                total_deleted += batch_deleted
                if batch_deleted < batch_size:
                    break
        
        logger.info("Deleted %d job history records for host %s", total_deleted, dbhost)
        return total_deleted
    
    def delete_by_status(
        self,
        status: str,
        before: datetime | None = None,
        batch_size: int = 10000,
    ) -> int:
        """Delete history records by final status.
        
        Uses batched deletes to prevent long-running transactions.
        
        Args:
            status: 'complete', 'failed', or 'canceled'.
            before: Optional cutoff date.
            batch_size: Max records to delete per transaction (default 10000).
            
        Returns:
            Number of records deleted.
            
        Raises:
            ValueError: If invalid status provided.
        """
        if status not in ("complete", "failed", "canceled"):
            raise ValueError(f"Invalid status: {status}")
        
        conditions = ["final_status = %s"]
        params: list[Any] = [status]
        
        if before:
            conditions.append("completed_at < %s")
            params.append(before)
        
        total_deleted = 0
        while True:
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM job_history_summary WHERE {' AND '.join(conditions)} "
                    f"LIMIT %s",
                    params + [batch_size],
                )
                conn.commit()
                batch_deleted = cursor.rowcount
                total_deleted += batch_deleted
                if batch_deleted < batch_size:
                    break
        
        logger.info("Deleted %d job history records with status %s", total_deleted, status)
        return total_deleted
    
    def count_matching(
        self,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        status: str | None = None,
        username: str | None = None,
        dbhost: str | None = None,
    ) -> int:
        """Count records matching filters (for preview before delete).
        
        Args:
            before: Filter by completed_at < date.
            after: Filter by completed_at > date.
            status: Filter by final_status.
            username: Filter by owner_username.
            dbhost: Filter by dbhost.
            
        Returns:
            Number of matching records.
        """
        # Validate status if provided
        if status is not None and status not in self.VALID_STATUSES:
            logger.warning(
                "Invalid status filter in count_matching: %s", status
            )
            return 0
        
        conditions: list[str] = []
        params: list[Any] = []
        
        if before:
            conditions.append("completed_at < %s")
            params.append(before)
        if after:
            conditions.append("completed_at > %s")
            params.append(after)
        if status:
            conditions.append("final_status = %s")
            params.append(status)
        if username:
            conditions.append("owner_username = %s")
            params.append(username)
        if dbhost:
            conditions.append("dbhost = %s")
            params.append(dbhost)
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                f"SELECT COUNT(*) FROM job_history_summary {where_clause}",
                params if params else None,
            )
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics for admin dashboard.
        
        Returns:
            Dict with total_records, oldest_record, newest_record,
            complete_count, failed_count, canceled_count.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT 
                    COUNT(*) AS total_records,
                    MIN(completed_at) AS oldest_record,
                    MAX(completed_at) AS newest_record,
                    SUM(CASE WHEN final_status = 'complete' THEN 1 ELSE 0 END) AS complete_count,
                    SUM(CASE WHEN final_status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN final_status = 'canceled' THEN 1 ELSE 0 END) AS canceled_count
                FROM job_history_summary
                """
            )
            row = cursor.fetchone()
            return row if row else {
                "total_records": 0,
                "oldest_record": None,
                "newest_record": None,
                "complete_count": 0,
                "failed_count": 0,
                "canceled_count": 0,
            }
    
    def get_records(
        self,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        status: str | None = None,
        username: str | None = None,
        dbhost: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get paginated history records with filters.
        
        Args:
            before: Filter by completed_at < date.
            after: Filter by completed_at > date.
            status: Filter by final_status.
            username: Filter by owner_username.
            dbhost: Filter by dbhost.
            offset: Pagination offset.
            limit: Max records to return.
            
        Returns:
            List of history record dicts.
        """
        # Validate status if provided
        if status is not None and status not in self.VALID_STATUSES:
            logger.warning(
                "Invalid status filter in get_records: %s", status
            )
            return []
        
        conditions: list[str] = []
        params: list[Any] = []
        
        if before:
            conditions.append("completed_at < %s")
            params.append(before)
        if after:
            conditions.append("completed_at > %s")
            params.append(after)
        if status:
            conditions.append("final_status = %s")
            params.append(status)
        if username:
            conditions.append("owner_username = %s")
            params.append(username)
        if dbhost:
            conditions.append("dbhost = %s")
            params.append(dbhost)
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        
        query = f"""
                SELECT * FROM job_history_summary
                {where_clause}
                ORDER BY completed_at DESC
                LIMIT %s OFFSET %s
                """
        logger.info("get_records query: %s with params: %s", query.strip(), params)
        
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(query, params)
            results = cursor.fetchall()
            logger.info("get_records returned %d rows", len(results))
            return results
    
    @classmethod
    def categorize_error(cls, error_detail: str | None) -> str:
        """Categorize an error message into a standard category.
        
        Args:
            error_detail: Error message or detail text.
            
        Returns:
            Error category string (one of ERROR_CATEGORIES keys or 'uncategorized').
        """
        if not error_detail:
            return "uncategorized"
        
        error_lower = error_detail.lower()
        
        for category, keywords in cls.ERROR_CATEGORIES.items():
            if any(kw in error_lower for kw in keywords):
                return category
        
        return "uncategorized"
