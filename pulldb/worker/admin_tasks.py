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
    ) -> None:
        """Initialize admin task executor.

        Args:
            task_repo: Repository for admin task operations.
            job_repo: Repository for job operations.
            user_repo: Repository for user operations.
            host_repo: Repository for host credentials.
            audit_repo: Repository for audit logging.
            pool: MySQL connection pool.
        """
        self.task_repo = task_repo
        self.job_repo = job_repo
        self.user_repo = user_repo
        self.host_repo = host_repo
        self.audit_repo = audit_repo
        self.pool = pool

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
