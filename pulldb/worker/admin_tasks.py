"""Admin task executor for background admin operations.

Processes admin tasks from the admin_tasks queue. Currently supports:
- force_delete_user: Delete user with job history, optionally dropping databases

Integrates with audit logging for compliance. Uses pulldb_loader credentials
for database drops (resolved per-host via HostRepository).
"""

from __future__ import annotations

import logging
import typing as t

import mysql.connector

from pulldb.domain.models import AdminTask, AdminTaskStatus, AdminTaskType
from pulldb.infra.metrics import MetricLabels, emit_event


if t.TYPE_CHECKING:
    from pulldb.infra.mysql import (
        AdminTaskRepository,
        AuditRepository,
        HostRepository,
        JobRepository,
        MySQLPool,
        SettingsRepository,
        UserRepository,
    )
    from pulldb.infra.secrets import MySQLCredentials


logger = logging.getLogger(__name__)


# Protected databases that must NEVER be dropped
PROTECTED_DATABASES = frozenset({
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
    "pulldb",
    "pulldb_service",
})


class AdminTaskExecutor:
    """Executor for admin background tasks.

    Handles task dispatch by type and execution with error handling.
    All operations are logged to audit_logs for compliance.
    """

    def __init__(
        self,
        task_repo: AdminTaskRepository,
        job_repo: JobRepository,
        user_repo: UserRepository,
        host_repo: HostRepository,
        audit_repo: AuditRepository,
        pool: MySQLPool,
        settings_repo: "SettingsRepository | None" = None,
    ) -> None:
        """Initialize admin task executor.

        Args:
            task_repo: Repository for admin task operations.
            job_repo: Repository for job operations.
            user_repo: Repository for user operations.
            host_repo: Repository for host credentials.
            audit_repo: Repository for audit logging.
            pool: MySQL connection pool.
            settings_repo: Repository for settings (required for retention cleanup).
        """
        self.task_repo = task_repo
        self.job_repo = job_repo
        self.user_repo = user_repo
        self.host_repo = host_repo
        self.audit_repo = audit_repo
        self.pool = pool
        self.settings_repo = settings_repo

    def execute(self, task: AdminTask) -> None:
        """Execute an admin task.

        Dispatches to the appropriate handler based on task type.
        Handles completion/failure status updates.

        Args:
            task: The admin task to execute.
        """
        logger.info(
            f"Executing admin task {task.task_id} (type={task.task_type.value})",
            extra={"task_id": task.task_id, "task_type": task.task_type.value},
        )

        emit_event(
            "admin_task_started",
            f"task_id={task.task_id}",
            MetricLabels(phase="admin_task", status="started"),
        )

        try:
            if task.task_type == AdminTaskType.FORCE_DELETE_USER:
                self._execute_force_delete_user(task)
            elif task.task_type == AdminTaskType.SCAN_USER_ORPHANS:
                self._execute_scan_user_orphans(task)
            elif task.task_type == AdminTaskType.BULK_DELETE_JOBS:
                self._execute_bulk_delete_jobs(task)
            elif task.task_type == AdminTaskType.RETENTION_CLEANUP:
                self._execute_retention_cleanup(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type.value}")

            emit_event(
                "admin_task_completed",
                f"task_id={task.task_id}",
                MetricLabels(phase="admin_task", status="complete"),
            )

        except Exception as e:
            logger.exception(
                f"Admin task {task.task_id} failed: {e}",
                extra={"task_id": task.task_id, "error": str(e)},
            )
            emit_event(
                "admin_task_failed",
                f"task_id={task.task_id}",
                MetricLabels(phase="admin_task", status="failed"),
            )
            # Note: failure is recorded by the executor, not here
            raise

    def _execute_force_delete_user(self, task: AdminTask) -> None:
        """Execute force delete user task.

        Steps:
        1. Log force_delete_started to audit
        2. Drop each selected database (if any)
        3. Delete all job records for the user
        4. Delete the user
        5. Log force_delete_completed to audit
        6. Mark task complete

        Args:
            task: The admin task with parameters.
        """
        params = task.parameters_json or {}
        target_user_id = task.target_user_id
        target_username = params.get("target_username", "unknown")
        target_user_code = params.get("target_user_code", "")
        databases_to_drop = params.get("databases_to_drop", [])

        if not target_user_id:
            raise ValueError("target_user_id is required for force_delete_user")
        
        if not target_user_code:
            raise ValueError("target_user_code is required for force_delete_user")

        # Initialize result tracking
        result: dict[str, t.Any] = {
            "databases_dropped": [],
            "databases_failed": [],
            "databases_skipped": [],
            "jobs_deleted": 0,
            "user_deleted": False,
        }

        # Log task start
        self.audit_repo.log_action(
            actor_user_id=task.requested_by,
            action="force_delete_started",
            target_user_id=target_user_id,
            detail=f"Starting force delete of user '{target_username}'",
            context={
                "task_id": task.task_id,
                "databases_to_drop": len(databases_to_drop),
            },
        )

        # Step 1: Drop databases (if any selected)
        if databases_to_drop:
            for db_info in databases_to_drop:
                db_name = db_info.get("name")
                db_host = db_info.get("host")

                if not db_name or not db_host:
                    logger.warning(f"Skipping invalid database entry: {db_info}")
                    result["databases_skipped"].append(db_info)
                    continue

                # SAFETY: Only drop databases that contain the user's code
                # This prevents dropping databases that don't belong to this user
                if target_user_code not in db_name:
                    skip_msg = (
                        f"Skipping database '{db_name}' - "
                        f"does not contain user code '{target_user_code}'"
                    )
                    logger.warning(skip_msg)
                    result["databases_skipped"].append({
                        "name": db_name,
                        "host": db_host,
                        "reason": f"Name does not contain user code",
                    })
                    self.audit_repo.log_action(
                        actor_user_id=task.requested_by,
                        action="database_drop_skipped",
                        target_user_id=target_user_id,
                        detail=skip_msg,
                        context={
                            "task_id": task.task_id,
                            "database": db_name,
                            "host": db_host,
                        },
                    )
                    continue

                try:
                    self._drop_target_database(
                        db_name=db_name,
                        db_host=db_host,
                        task=task,
                        target_user_id=target_user_id,
                    )
                    result["databases_dropped"].append({
                        "name": db_name,
                        "host": db_host,
                    })
                    self.audit_repo.log_action(
                        actor_user_id=task.requested_by,
                        action="database_dropped",
                        target_user_id=target_user_id,
                        detail=f"Dropped database '{db_name}' on host '{db_host}'",
                        context={"task_id": task.task_id, "database": db_name, "host": db_host},
                    )
                except Exception as e:
                    error_msg = str(e)
                    result["databases_failed"].append({
                        "name": db_name,
                        "host": db_host,
                        "error": error_msg,
                    })
                    self.audit_repo.log_action(
                        actor_user_id=task.requested_by,
                        action="database_drop_failed",
                        target_user_id=target_user_id,
                        detail=f"Failed to drop database '{db_name}' on '{db_host}': {error_msg}",
                        context={
                            "task_id": task.task_id,
                            "database": db_name,
                            "host": db_host,
                            "error": error_msg,
                        },
                    )
                    logger.error(
                        f"Failed to drop database {db_name} on {db_host}: {e}",
                        extra={"task_id": task.task_id, "database": db_name},
                    )
                    # Continue with other databases (partial failure allowed)

                # Update progress
                self.task_repo.update_task_result(task.task_id, result)
        else:
            # Log that database drops were skipped
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="database_drop_skipped",
                target_user_id=target_user_id,
                detail="Database drops skipped by admin request",
                context={"task_id": task.task_id},
            )

        # Step 2: Delete job records
        try:
            jobs_deleted = self._delete_user_jobs(target_user_id)
            result["jobs_deleted"] = jobs_deleted
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="jobs_deleted",
                target_user_id=target_user_id,
                detail=f"Deleted {jobs_deleted} job records",
                context={"task_id": task.task_id, "jobs_deleted": jobs_deleted},
            )
            self.task_repo.update_task_result(task.task_id, result)
        except Exception as e:
            error_msg = f"Failed to delete jobs: {e}"
            self.task_repo.fail_task(task.task_id, error_msg, result)
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="force_delete_failed",
                target_user_id=target_user_id,
                detail=error_msg,
                context={"task_id": task.task_id, "error": str(e)},
            )
            raise

        # Step 3: Delete the user
        try:
            self._force_delete_user_record(target_user_id)
            result["user_deleted"] = True
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="user_deleted",
                target_user_id=target_user_id,
                detail=f"Deleted user '{target_username}'",
                context={"task_id": task.task_id, "username": target_username},
            )
        except Exception as e:
            error_msg = f"Failed to delete user: {e}"
            self.task_repo.fail_task(task.task_id, error_msg, result)
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="force_delete_failed",
                target_user_id=target_user_id,
                detail=error_msg,
                context={"task_id": task.task_id, "error": str(e)},
            )
            raise

        # Step 4: Complete the task
        self.audit_repo.log_action(
            actor_user_id=task.requested_by,
            action="force_delete_completed",
            target_user_id=target_user_id,
            detail=f"Force delete of user '{target_username}' completed",
            context={
                "task_id": task.task_id,
                "databases_dropped": len(result["databases_dropped"]),
                "databases_failed": len(result["databases_failed"]),
                "jobs_deleted": result["jobs_deleted"],
            },
        )
        self.task_repo.complete_task(task.task_id, result)

        logger.info(
            f"Force delete user task {task.task_id} completed: "
            f"dropped={len(result['databases_dropped'])}, "
            f"failed={len(result['databases_failed'])}, "
            f"jobs={result['jobs_deleted']}",
            extra={"task_id": task.task_id, "result": result},
        )

    def _drop_target_database(
        self,
        db_name: str,
        db_host: str,
        task: AdminTask,
        target_user_id: str,
    ) -> None:
        """Drop a target database on the specified host.

        Uses pulldb_loader credentials resolved via HostRepository.
        Includes safety checks for protected databases.

        Args:
            db_name: Database name to drop.
            db_host: Host where database exists.
            task: Current admin task (for logging).
            target_user_id: User being deleted (for logging).

        Raises:
            ValueError: If attempting to drop a protected database.
            Exception: On connection or SQL errors.
        """
        # Safety check: Never drop protected databases
        if db_name.lower() in PROTECTED_DATABASES:
            raise ValueError(
                f"FATAL: Cannot drop protected database: {db_name}. "
                "This is a critical safety violation."
            )

        # Resolve credentials for the host
        credentials = self.host_repo.get_host_credentials(db_host)

        logger.info(
            f"Dropping database '{db_name}' on host '{db_host}'",
            extra={"task_id": task.task_id, "database": db_name, "host": db_host},
        )

        conn = mysql.connector.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.username,
            password=credentials.password,
            connect_timeout=30,
            autocommit=True,
        )
        try:
            cursor = conn.cursor()
            # Use backticks to handle special characters in database names
            cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
            logger.info(f"Dropped database: {db_name}")
        finally:
            conn.close()

        # Verify database is gone
        if self._database_exists(credentials, db_name):
            raise RuntimeError(f"Database {db_name} still exists after DROP command")

    def _database_exists(self, credentials: MySQLCredentials, db_name: str) -> bool:
        """Check if a database exists on a host.

        Args:
            credentials: MySQL credentials for the host.
            db_name: Database name to check.

        Returns:
            True if database exists, False otherwise.
        """
        conn = mysql.connector.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.username,
            password=credentials.password,
            connect_timeout=30,
        )
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = %s",
                (db_name,),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def _delete_user_jobs(self, user_id: str) -> int:
        """Delete all job records for a user.

        Also deletes associated job_events via ON DELETE CASCADE.

        Args:
            user_id: User ID whose jobs to delete.

        Returns:
            Number of jobs deleted.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            # Delete job events first (they reference jobs)
            cursor.execute(
                """
                DELETE FROM job_events
                WHERE job_id IN (SELECT id FROM jobs WHERE owner_user_id = %s)
                """,
                (user_id,),
            )
            events_deleted = cursor.rowcount

            # Delete jobs
            cursor.execute(
                """
                DELETE FROM jobs
                WHERE owner_user_id = %s
                """,
                (user_id,),
            )
            jobs_deleted = cursor.rowcount
            conn.commit()

            logger.info(
                f"Deleted {jobs_deleted} jobs and {events_deleted} events for user {user_id}"
            )
            return jobs_deleted

    def _force_delete_user_record(self, user_id: str) -> None:
        """Delete user record (bypassing job count check).

        Uses direct SQL instead of UserRepository.delete_user() to bypass
        the job count validation.

        Args:
            user_id: User ID to delete.

        Raises:
            ValueError: If user not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Clear manager_id for any users managed by this user
            cursor.execute(
                """
                UPDATE auth_users
                SET manager_id = NULL
                WHERE manager_id = %s
                """,
                (user_id,),
            )
            orphaned_count = cursor.rowcount

            # Delete the user (cascades to sessions, credentials, user_hosts)
            cursor.execute(
                """
                DELETE FROM auth_users
                WHERE user_id = %s
                """,
                (user_id,),
            )

            if cursor.rowcount == 0:
                raise ValueError(f"User {user_id} not found")

            conn.commit()

            if orphaned_count > 0:
                logger.info(
                    f"Cleared manager_id for {orphaned_count} users formerly managed by {user_id}"
                )

    def _execute_scan_user_orphans(self, task: AdminTask) -> None:
        """Execute scan for user orphan databases task.

        Scans all enabled hosts for databases belonging to deleted users.
        Results are stored in the task result_json for admin review.

        Args:
            task: The admin task with parameters.
        """
        from pulldb.worker.cleanup import (
            detect_user_orphaned_databases,
            get_all_user_codes,
        )

        params = task.parameters_json or {}
        specific_hosts = params.get("hosts")  # Optional: limit to specific hosts

        # Initialize result tracking
        result: dict[str, t.Any] = {
            "hosts_scanned": 0,
            "hosts_failed": [],
            "orphans_found": 0,
            "orphans_by_host": {},
            "orphans_by_user_code": {},
        }

        # Log task start
        self.audit_repo.log_action(
            actor_user_id=task.requested_by,
            action="scan_user_orphans_started",
            target_user_id=None,
            detail="Starting scan for user-orphan databases",
            context={"task_id": task.task_id, "specific_hosts": specific_hosts},
        )

        try:
            # Get all valid user codes
            valid_user_codes = get_all_user_codes(self.user_repo)
            logger.info(f"Found {len(valid_user_codes)} valid user codes in system")

            # Get hosts to scan
            if specific_hosts:
                hosts_to_scan = [
                    h for h in self.host_repo.get_enabled_hosts()
                    if h.hostname in specific_hosts
                ]
            else:
                hosts_to_scan = self.host_repo.get_enabled_hosts()

            for host in hosts_to_scan:
                hostname = host.hostname
                logger.info(f"Scanning host {hostname} for user-orphan databases")

                scan_result = detect_user_orphaned_databases(
                    dbhost=hostname,
                    host_repo=self.host_repo,
                    valid_user_codes=valid_user_codes,
                )

                result["hosts_scanned"] += 1

                # Handle error case
                if isinstance(scan_result, str):
                    result["hosts_failed"].append({
                        "hostname": hostname,
                        "error": scan_result,
                    })
                    continue

                # Handle success case (UserOrphanReport)
                if scan_result.error:
                    result["hosts_failed"].append({
                        "hostname": hostname,
                        "error": scan_result.error,
                    })
                    continue

                # Process orphans found
                if scan_result.orphans:
                    host_orphans = []
                    for orphan in scan_result.orphans:
                        orphan_data = {
                            "database_name": orphan.database_name,
                            "extracted_user_code": orphan.extracted_user_code,
                            "size_mb": orphan.size_mb,
                        }
                        host_orphans.append(orphan_data)

                        # Track by user_code
                        user_code = orphan.extracted_user_code.lower()
                        if user_code not in result["orphans_by_user_code"]:
                            result["orphans_by_user_code"][user_code] = []
                        result["orphans_by_user_code"][user_code].append({
                            "database_name": orphan.database_name,
                            "dbhost": hostname,
                            "size_mb": orphan.size_mb,
                        })

                    result["orphans_by_host"][hostname] = host_orphans
                    result["orphans_found"] += len(host_orphans)

                # Update progress
                self.task_repo.update_task_result(task.task_id, result)

        except Exception as e:
            error_msg = f"Scan failed: {e}"
            self.task_repo.fail_task(task.task_id, error_msg, result)
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="scan_user_orphans_failed",
                target_user_id=None,
                detail=error_msg,
                context={"task_id": task.task_id, "error": str(e)},
            )
            raise

        # Complete the task
        self.audit_repo.log_action(
            actor_user_id=task.requested_by,
            action="scan_user_orphans_completed",
            target_user_id=None,
            detail=f"Scan complete: {result['orphans_found']} orphans found across {result['hosts_scanned']} hosts",
            context={
                "task_id": task.task_id,
                "orphans_found": result["orphans_found"],
                "hosts_scanned": result["hosts_scanned"],
                "hosts_failed": len(result["hosts_failed"]),
            },
        )
        self.task_repo.complete_task(task.task_id, result)

        logger.info(
            f"Scan user orphans task {task.task_id} completed: "
            f"hosts={result['hosts_scanned']}, orphans={result['orphans_found']}",
            extra={"task_id": task.task_id, "result": result},
        )

    def _execute_bulk_delete_jobs(self, task: AdminTask) -> None:
        """Execute bulk delete jobs task.

        Deletes databases (staging + target) for multiple jobs and updates
        job status. Supports both soft delete (status='deleted') and hard
        delete (remove job record entirely).

        Progress is tracked in result_json for resume on timeout/restart.
        Jobs already in 'deleted' status are skipped (idempotent).

        Args:
            task: The admin task with parameters.
        """
        from pulldb.worker.cleanup import delete_job_databases
        from pulldb.domain.models import JobStatus

        params = task.parameters_json or {}
        job_infos = params.get("job_infos", [])
        hard_delete = params.get("hard_delete", False)
        skip_database_drops = params.get("skip_database_drops", False)
        total_jobs = params.get("total_jobs", len(job_infos))

        # Initialize or restore result tracking (for resume)
        # Use 'progress' key to match what bulk_delete_status endpoint reads
        existing_result = task.result_json or {}
        existing_progress = existing_result.get("progress", {})
        
        # Internal tracking lists for resume capability
        processed_list: list[dict] = existing_result.get("_processed_list", [])
        failed_list: list[dict] = existing_result.get("_failed_list", [])
        skipped_list: list[dict] = existing_result.get("_skipped_list", [])
        
        # Progress dict for status polling (counts, not full lists)
        progress: dict[str, t.Any] = {
            "total": total_jobs,
            "processed": existing_progress.get("processed", 0),
            "soft_deleted": existing_progress.get("soft_deleted", 0),
            "hard_deleted": existing_progress.get("hard_deleted", 0),
            "errors": existing_progress.get("errors", []),
        }
        
        # Full result structure
        result: dict[str, t.Any] = {
            "progress": progress,
            "_processed_list": processed_list,
            "_failed_list": failed_list,
            "_skipped_list": skipped_list,
            "hard_delete": hard_delete,
        }

        # Track which jobs have already been processed (for resume)
        processed_ids = set(j["job_id"] for j in processed_list)
        failed_ids = set(j["job_id"] for j in failed_list)
        skipped_ids = set(j["job_id"] for j in skipped_list)
        done_ids = processed_ids | failed_ids | skipped_ids

        # Log task start (only if this is a fresh start)
        if not done_ids:
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="bulk_delete_started",
                target_user_id=None,
                detail=f"Starting bulk delete of {total_jobs} job(s)",
                context={
                    "task_id": task.task_id,
                    "total_jobs": total_jobs,
                    "hard_delete": hard_delete,
                },
            )

        try:
            for job_info in job_infos:
                job_id = job_info.get("job_id")
                if not job_id:
                    continue

                # Skip already processed jobs (for resume)
                if job_id in done_ids:
                    continue

                staging_name = job_info.get("staging_name", "")
                target_name = job_info.get("target", "")
                owner_user_code = job_info.get("owner_user_code", "")
                dbhost = job_info.get("dbhost", "")

                # Check current job status
                job = self.job_repo.get_job_by_id(job_id)
                if not job:
                    failed_list.append({
                        "job_id": job_id,
                        "error": "Job not found",
                    })
                    progress["errors"].append(f"{job_id[:12]}: not found")
                    self.task_repo.update_task_result(task.task_id, result)
                    continue

                # Skip already deleted jobs for soft delete (idempotent)
                # For hard delete, proceed to remove the job record
                if job.status == JobStatus.DELETED and not hard_delete:
                    skipped_list.append({
                        "job_id": job_id,
                        "reason": "Already soft-deleted (use hard delete to remove record)",
                    })
                    progress["processed"] += 1  # Count as processed (no-op)
                    self.task_repo.update_task_result(task.task_id, result)
                    continue
                
                # Skip jobs already deleting (worker will retry)
                if job.status == JobStatus.DELETING:
                    skipped_list.append({
                        "job_id": job_id,
                        "reason": "Delete already in progress - worker will retry automatically",
                    })
                    progress["processed"] += 1  # Count as processed (in-flight)
                    self.task_repo.update_task_result(task.task_id, result)
                    continue
                
                # Skip jobs that failed deletion (exhausted retries)
                # Only block if error_detail indicates delete failure, not other failures
                # (e.g., zombie detection, restore failure, etc. can still be deleted)
                if job.status == JobStatus.FAILED:
                    error_detail = job.error_detail or ""
                    if error_detail.startswith("Delete failed"):
                        failed_list.append({
                            "job_id": job_id,
                            "error": "Delete failed after max retries - use force-complete-delete admin endpoint",
                        })
                        progress["errors"].append(f"{job_id[:12]}: delete failed (max retries)")
                        self.task_repo.update_task_result(task.task_id, result)
                        continue
                    # Otherwise, job failed for other reasons (zombie, restore error, etc.)
                    # Allow deletion to proceed - databases may or may not exist

                # Fast path: already soft-deleted + hard_delete requested
                # Skip database checks (DBs already dropped), just remove record
                if job.status == JobStatus.DELETED and hard_delete:
                    self.audit_repo.log_action(
                        actor_user_id=task.requested_by,
                        action="job_hard_deleted",
                        target_user_id=job.owner_user_id,
                        detail=f"Hard deleted job {job_id} (was already soft-deleted)",
                        context={
                            "task_id": task.task_id,
                            "job_id": job_id,
                            "target": target_name,
                            "staging": staging_name,
                            "dbhost": dbhost,
                            "fast_path": True,
                        },
                    )
                    self.job_repo.hard_delete_job(job_id)
                    processed_list.append({
                        "job_id": job_id,
                        "staging_dropped": False,
                        "target_dropped": False,
                        "hard_deleted": True,
                    })
                    progress["processed"] += 1
                    progress["hard_deleted"] += 1
                    self.task_repo.update_task_result(task.task_id, result)
                    continue

                # Log the individual deletion to audit (BEFORE action)
                self.audit_repo.log_action(
                    actor_user_id=task.requested_by,
                    action="job_delete_started",
                    target_user_id=job.owner_user_id,
                    detail=f"Deleting job {job_id} databases (hard_delete={hard_delete})",
                    context={
                        "task_id": task.task_id,
                        "job_id": job_id,
                        "target": target_name,
                        "staging": staging_name,
                        "dbhost": dbhost,
                        "hard_delete": hard_delete,
                    },
                )

                try:
                    # SUPERSEDED jobs: Skip database deletion entirely
                    # When a job is superseded, its staging DB was already cleaned up
                    # and it no longer owns the target DB. No database work to do.
                    skip_database_deletion = (
                        job.status == JobStatus.SUPERSEDED or job.is_superseded
                    )
                    
                    if skip_database_deletion:
                        # Log skip event
                        self.job_repo.append_job_event(
                            job_id, "delete_skipped",
                            '{"reason": "superseded_job_no_databases_owned"}'
                        )
                        # Create dummy result for tracking
                        from pulldb.worker.cleanup import JobDeleteResult
                        delete_result = JobDeleteResult(
                            job_id=job_id,
                            staging_name=staging_name,
                            target_name=target_name,
                            dbhost=dbhost,
                        )
                        delete_result.staging_existed = False
                        delete_result.target_existed = False
                    else:
                        # Mark job as deleting BEFORE dropping databases
                        self.job_repo.mark_job_deleting(job_id)
                        
                        # Drop databases
                        delete_result = delete_job_databases(
                            job_id=job_id,
                            staging_name=staging_name,
                            target_name=target_name,
                            owner_user_code=owner_user_code,
                            dbhost=dbhost,
                            host_repo=self.host_repo,
                            job_repo=self.job_repo,
                            skip_database_drops=skip_database_drops,
                            custom_target=job.custom_target,
                        )

                    if delete_result.error:
                        failed_list.append({
                            "job_id": job_id,
                            "error": delete_result.error,
                        })
                        progress["errors"].append(f"{job_id[:12]}: {delete_result.error}")
                        self.audit_repo.log_action(
                            actor_user_id=task.requested_by,
                            action="job_delete_failed",
                            target_user_id=job.owner_user_id,
                            detail=f"Failed to delete job {job_id}: {delete_result.error}",
                            context={
                                "task_id": task.task_id,
                                "job_id": job_id,
                                "error": delete_result.error,
                            },
                        )
                        self.task_repo.update_task_result(task.task_id, result)
                        continue

                    # Build detailed event log entry (matching single delete behavior)
                    if delete_result.staging_existed or delete_result.target_existed:
                        details = []
                        if delete_result.staging_existed:
                            details.append(f"staging={'dropped' if delete_result.staging_dropped else 'failed'}")
                        else:
                            details.append("staging=did not exist")
                        if delete_result.target_existed:
                            details.append(f"target={'dropped' if delete_result.target_dropped else 'failed'}")
                        else:
                            details.append("target=did not exist")
                        event_detail = f"Bulk delete: databases deleted ({', '.join(details)})"
                    else:
                        event_detail = "Bulk delete: job marked deleted (databases did not exist)"

                    self.job_repo.append_job_event(
                        job_id=job_id,
                        event_type="deleted",
                        detail=event_detail,
                    )

                    # Update job status or hard delete
                    if hard_delete:
                        # Log to audit BEFORE hard delete (preserves record)
                        self.audit_repo.log_action(
                            actor_user_id=task.requested_by,
                            action="job_hard_deleted",
                            target_user_id=job.owner_user_id,
                            detail=f"Hard deleted job {job_id}",
                            context={
                                "task_id": task.task_id,
                                "job_id": job_id,
                                "target": target_name,
                                "staging": staging_name,
                                "dbhost": dbhost,
                                "staging_existed": delete_result.staging_existed,
                                "staging_dropped": delete_result.staging_dropped,
                                "target_existed": delete_result.target_existed,
                                "target_dropped": delete_result.target_dropped,
                            },
                        )
                        self.job_repo.hard_delete_job(job_id)
                    else:
                        self.job_repo.mark_job_deleted(job_id)
                        self.audit_repo.log_action(
                            actor_user_id=task.requested_by,
                            action="job_deleted",
                            target_user_id=job.owner_user_id,
                            detail=f"Soft deleted job {job_id}",
                            context={
                                "task_id": task.task_id,
                                "job_id": job_id,
                                "staging_existed": delete_result.staging_existed,
                                "staging_dropped": delete_result.staging_dropped,
                                "target_existed": delete_result.target_existed,
                                "target_dropped": delete_result.target_dropped,
                            },
                        )

                    processed_list.append({
                        "job_id": job_id,
                        "staging_dropped": delete_result.staging_dropped,
                        "target_dropped": delete_result.target_dropped,
                        "hard_deleted": hard_delete,
                    })
                    progress["processed"] += 1
                    if hard_delete:
                        progress["hard_deleted"] += 1
                    else:
                        progress["soft_deleted"] += 1

                except Exception as e:
                    failed_list.append({
                        "job_id": job_id,
                        "error": str(e),
                    })
                    progress["errors"].append(f"{job_id[:12]}: {e}")
                    logger.error(
                        f"Error deleting job {job_id}: {e}",
                        extra={"task_id": task.task_id, "job_id": job_id},
                    )

                # Update progress after each job
                self.task_repo.update_task_result(task.task_id, result)

        except Exception as e:
            error_msg = f"Bulk delete failed: {e}"
            self.task_repo.fail_task(task.task_id, error_msg, result)
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="bulk_delete_failed",
                target_user_id=None,
                detail=error_msg,
                context={"task_id": task.task_id, "error": str(e)},
            )
            raise

        # Complete the task
        self.audit_repo.log_action(
            actor_user_id=task.requested_by,
            action="bulk_delete_completed",
            target_user_id=None,
            detail=(
                f"Bulk delete complete: {len(processed_list)} deleted, "
                f"{len(failed_list)} failed, {len(skipped_list)} skipped"
            ),
            context={
                "task_id": task.task_id,
                "processed": len(processed_list),
                "failed": len(failed_list),
                "skipped": len(skipped_list),
                "hard_delete": hard_delete,
            },
        )
        self.task_repo.complete_task(task.task_id, result)

        logger.info(
            f"Bulk delete jobs task {task.task_id} completed: "
            f"processed={len(processed_list)}, failed={len(failed_list)}, "
            f"skipped={len(skipped_list)}",
            extra={"task_id": task.task_id, "result": result},
        )

    def _execute_retention_cleanup(self, task: AdminTask) -> None:
        """Execute retention cleanup task.

        Drops databases for expired jobs (past expiration + grace period).
        Only processes complete, non-locked jobs with db_dropped_at IS NULL.

        Args:
            task: The admin task with optional parameters.
        """
        from pulldb.worker.cleanup import run_retention_cleanup

        if not self.settings_repo:
            raise ValueError("SettingsRepository required for retention cleanup")

        params = task.parameters_json or {}
        dry_run = params.get("dry_run", False)

        # Log task start
        self.audit_repo.log_action(
            actor_user_id=task.requested_by,
            action="retention_cleanup_started",
            target_user_id=None,
            detail="Starting retention cleanup of expired databases",
            context={
                "task_id": task.task_id,
                "dry_run": dry_run,
            },
        )

        try:
            # Run the cleanup
            cleanup_result = run_retention_cleanup(
                job_repo=self.job_repo,
                host_repo=self.host_repo,
                settings_repo=self.settings_repo,
                dry_run=dry_run,
            )

            # Build result for task
            result: dict[str, t.Any] = {
                "candidates_found": cleanup_result.candidates_found,
                "databases_dropped": cleanup_result.databases_dropped,
                "databases_skipped": cleanup_result.databases_skipped,
                "errors": cleanup_result.errors,
                "dropped_jobs": cleanup_result.dropped_jobs,
                "grace_days": cleanup_result.grace_days,
                "dry_run": dry_run,
            }

            # Log completion
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="retention_cleanup_completed",
                target_user_id=None,
                detail=(
                    f"Retention cleanup complete: {cleanup_result.databases_dropped} dropped, "
                    f"{cleanup_result.databases_skipped} skipped, {len(cleanup_result.errors)} errors"
                ),
                context={
                    "task_id": task.task_id,
                    **result,
                },
            )

            # Mark task complete
            self.task_repo.complete_task(task.task_id, result)

            logger.info(
                f"Retention cleanup task {task.task_id} completed: "
                f"dropped={cleanup_result.databases_dropped}, "
                f"skipped={cleanup_result.databases_skipped}, "
                f"errors={len(cleanup_result.errors)}",
                extra={"task_id": task.task_id, "result": result},
            )

        except Exception as e:
            error_msg = f"Retention cleanup failed: {e}"
            self.task_repo.fail_task(task.task_id, error_msg, {})
            self.audit_repo.log_action(
                actor_user_id=task.requested_by,
                action="retention_cleanup_failed",
                target_user_id=None,
                detail=error_msg,
                context={"task_id": task.task_id, "error": str(e)},
            )
            raise
