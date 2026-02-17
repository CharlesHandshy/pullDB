"""MySQL host repository for pullDB.

Implements the HostRepository class for database host configuration,
credentials, capacity management, and host CRUD operations.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import logging
from typing import Any

import mysql.connector

from pulldb.domain.models import DBHost
from pulldb.infra.mysql_pool import (
    MySQLPool,
    TypedDictCursor,
    TypedTupleCursor,
)
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials
from pulldb.infra.timeouts import (
    DEFAULT_MYSQL_CONNECT_TIMEOUT_API,
    DEFAULT_MYSQL_CONNECT_TIMEOUT_WORKER,
)

logger = logging.getLogger(__name__)

class HostRepository:
    """Repository for database host operations.

    Manages host configuration and credential resolution for target MySQL
    servers. Integrates with AWS Secrets Manager for secure credential
    storage.

    Example:
        >>> resolver = CredentialResolver()
        >>> repo = HostRepository(pool, resolver)
        >>> host = repo.get_host_by_hostname("localhost")
        >>> creds = repo.get_host_credentials("localhost")
        >>> # username is empty - caller sets it per-service
        >>> # via PULLDB_API_MYSQL_USER or PULLDB_WORKER_MYSQL_USER
        >>> print(creds.host)  # From Secrets Manager
    """

    def __init__(
        self, pool: MySQLPool, credential_resolver: CredentialResolver
    ) -> None:
        """Initialize HostRepository with pool and credential resolver.

        Args:
            pool: MySQL connection pool for coordination database access.
            credential_resolver: Resolver for AWS credential references.
        """
        self.pool = pool
        self.credential_resolver = credential_resolver

    def get_host_by_hostname(self, hostname: str) -> DBHost | None:
        """Get host configuration by hostname.

        Args:
            hostname: Hostname to look up (e.g., "localhost").

        Returns:
            DBHost instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE hostname = %s
                """,
                (hostname,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def get_host_by_id(self, host_id: str) -> DBHost | None:
        """Get host configuration by ID.

        Args:
            host_id: UUID string of the host.

        Returns:
            DBHost instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE id = %s
                """,
                (host_id,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def get_host_by_alias(self, alias: str) -> DBHost | None:
        """Get host configuration by alias.

        Args:
            alias: Host alias to look up (e.g., "dev-db-01").

        Returns:
            DBHost instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE host_alias = %s
                """,
                (alias,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def resolve_hostname(self, name: str) -> str | None:
        """Resolve a hostname or alias to the canonical hostname.

        Looks up by hostname first, then by alias if not found.
        This allows users to use short aliases like "dev-db-01" instead
        of full FQDNs like "dev-db-01.example.com".

        Args:
            name: Hostname or alias to resolve.

        Returns:
            Canonical hostname if found, None otherwise.
        """
        # Try exact hostname match first
        host = self.get_host_by_hostname(name)
        if host:
            return host.hostname

        # Try alias match
        host = self.get_host_by_alias(name)
        if host:
            return host.hostname

        return None

    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled database hosts.

        Returns:
            List of enabled DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE enabled = TRUE
                ORDER BY hostname ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

    def get_all_hosts(self) -> list[DBHost]:
        """Get all database hosts.

        Returns:
            List of DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                ORDER BY hostname ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

    def list_hosts(self) -> list[DBHost]:
        """Get all hosts (alias for get_all_hosts).

        Provided for API consistency with SimulatedHostRepository.

        Returns:
            List of all DBHost instances.
        """
        return self.get_all_hosts()

    def database_exists(self, hostname: str, db_name: str) -> bool:
        """Check if a database exists on the specified host.

        Opens a direct MySQL connection to the host and runs
        ``SHOW DATABASES LIKE`` to check existence.

        Args:
            hostname: Database host to check.
            db_name: Database name to look for.

        Returns:
            True if the database exists, False otherwise.

        Raises:
            Exception: If the connection to the host fails.
        """
        creds = self.get_host_credentials(hostname)
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.username,
            password=creds.password,
            connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_API,
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW DATABASES LIKE %s", (db_name,))
            exists = cursor.fetchone() is not None
            cursor.close()
            return exists
        finally:
            conn.close()

    def get_pulldb_metadata_owner(
        self, hostname: str, db_name: str
    ) -> tuple[bool, str | None, str | None]:
        """Check if a database has a pullDB metadata table and get the owner.

        Opens a direct MySQL connection, checks for a ``pullDB`` table,
        and reads the ``owner_user_id`` / ``owner_user_code`` columns.

        Args:
            hostname: Database host to check.
            db_name: Database name to inspect.

        Returns:
            Tuple of ``(has_pulldb_table, owner_user_id, owner_user_code)``.
        """
        creds = self.get_host_credentials(hostname)
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.username,
            password=creds.password,
            database=db_name,
            connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_API,
        )
        try:
            cursor = conn.cursor()

            cursor.execute("SHOW TABLES LIKE 'pullDB'")
            if cursor.fetchone() is None:
                cursor.close()
                return (False, None, None)

            cursor.execute("SHOW COLUMNS FROM `pullDB` LIKE 'owner_user_id'")
            has_owner_columns = cursor.fetchone() is not None

            if not has_owner_columns:
                cursor.close()
                return (True, None, None)

            cursor.execute(
                "SELECT owner_user_id, owner_user_code FROM `pullDB` "
                "ORDER BY restored_at DESC LIMIT 1"
            )
            row: tuple | None = cursor.fetchone()  # type: ignore[assignment]
            cursor.close()

            if row:
                owner_user_id = str(row[0]) if row[0] else None
                owner_user_code = str(row[1]) if row[1] else None
                return (True, owner_user_id, owner_user_code)
            return (True, None, None)
        finally:
            conn.close()

    def get_host_credentials(self, hostname: str) -> MySQLCredentials:
        """Get resolved MySQL credentials for host.

        Looks up the host configuration, then resolves its credential_ref
        using the CredentialResolver (AWS Secrets Manager or SSM).

        Args:
            hostname: Hostname to get credentials for.

        Returns:
            Resolved MySQLCredentials instance.

        Raises:
            ValueError: If host not found or disabled.
            CredentialResolutionError: If credentials cannot be resolved
                from AWS Secrets Manager or SSM Parameter Store.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")
        if not host.enabled:
            raise ValueError(f"Host '{hostname}' is disabled")

        # Delegate to CredentialResolver (from Milestone 1.4)
        return self.credential_resolver.resolve(host.credential_ref)

    def get_host_credentials_for_maintenance(self, hostname: str) -> MySQLCredentials:
        """Get resolved MySQL credentials for maintenance operations.

        Similar to get_host_credentials but allows disabled hosts.
        Use for cleanup, deletion, and staging operations that need
        to work on disabled hosts.

        Args:
            hostname: Hostname to get credentials for.

        Returns:
            Resolved MySQLCredentials instance.

        Raises:
            ValueError: If host not found (deleted from db_hosts).
            CredentialResolutionError: If credentials cannot be resolved
                from AWS Secrets Manager or SSM Parameter Store.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")
        # NO enabled check - maintenance operations need access to disabled hosts

        # Delegate to CredentialResolver
        return self.credential_resolver.resolve(host.credential_ref)

    def check_host_running_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for running jobs (worker enforcement).

        Compares count of running jobs against max_running_jobs limit.

        Args:
            hostname: Hostname to check capacity for.

        Returns:
            True if host has capacity (running < max_running_jobs), False otherwise.

        Raises:
            ValueError: If host not found.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE dbhost = %s AND status = 'running'
                """,
                (hostname,),
            )
            result = cursor.fetchone()
            if result is None:
                running_count: int = 0
            else:
                running_count = result[0]

            return running_count < host.max_running_jobs

    def check_host_active_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for active jobs (API enforcement).

        Compares count of active jobs (queued + running) against max_active_jobs limit.

        Args:
            hostname: Hostname to check capacity for.

        Returns:
            True if host has capacity (active < max_active_jobs), False otherwise.

        Raises:
            ValueError: If host not found.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE dbhost = %s AND status IN ('queued', 'running')
                """,
                (hostname,),
            )
            result = cursor.fetchone()
            if result is None:
                active_count: int = 0
            else:
                active_count = result[0]

            return active_count < host.max_active_jobs

    def update_host_limits(
        self, hostname: str, max_active_jobs: int, max_running_jobs: int
    ) -> None:
        """Update job limits for a host.

        Args:
            hostname: Hostname to update.
            max_active_jobs: Maximum active (queued + running) jobs.
            max_running_jobs: Maximum concurrent running jobs.

        Raises:
            ValueError: If host not found or limits invalid.
        """
        if max_active_jobs < 0:
            raise ValueError("max_active_jobs cannot be negative")
        if max_running_jobs < 1:
            raise ValueError("max_running_jobs must be at least 1")
        if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
            raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                UPDATE db_hosts 
                SET max_active_jobs = %s, max_running_jobs = %s 
                WHERE hostname = %s
                """,
                (max_active_jobs, max_running_jobs, hostname),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def add_host(
        self,
        hostname: str,
        max_concurrent: int,
        credential_ref: str | None,
        *,
        host_id: str | None = None,
        host_alias: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Add a new database host.

        Args:
            hostname: Hostname of the database server.
            max_concurrent: Maximum concurrent running jobs allowed.
            credential_ref: AWS Secrets Manager reference.
            host_id: Optional UUID (generated if not provided).
            host_alias: Optional short alias for the host.
            max_running_jobs: Optional max running jobs (uses max_concurrent if not set).
            max_active_jobs: Optional max active jobs (defaults to 10).

        Raises:
            ValueError: If host already exists.
        """
        import uuid
        if host_id is None:
            host_id = str(uuid.uuid4())
        if max_active_jobs is None:
            max_active_jobs = 10
        # Use max_concurrent as fallback for max_running_jobs
        actual_max_running = max_running_jobs if max_running_jobs is not None else max_concurrent

        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO db_hosts 
                            (id, hostname, host_alias, max_running_jobs, max_active_jobs, 
                             enabled, credential_ref)
                        VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                        """,
                        (host_id, hostname, host_alias, actual_max_running, max_active_jobs, 
                         credential_ref),
                    )
                    conn.commit()
        except mysql.connector.IntegrityError as e:
            if "Duplicate" in str(e):
                raise ValueError(f"Host already exists: {hostname}") from e
            raise

    def delete_host(self, hostname: str) -> None:
        """Delete a database host by hostname.

        Args:
            hostname: Hostname to delete.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM db_hosts WHERE hostname = %s",
                (hostname,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def enable_host(self, hostname: str) -> None:
        """Enable a database host.

        Args:
            hostname: Hostname to enable.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "UPDATE db_hosts SET enabled = TRUE WHERE hostname = %s",
                (hostname,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def disable_host(self, hostname: str) -> None:
        """Disable a database host.

        Args:
            hostname: Hostname to disable.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "UPDATE db_hosts SET enabled = FALSE WHERE hostname = %s",
                (hostname,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {hostname}")

    def hard_delete_host(self, host_id: str) -> None:
        """Permanently delete a database host record.

        WARNING: This is a hard delete - the record cannot be recovered.
        Use this only after cleaning up associated resources (MySQL user, AWS secret).
        
        Args:
            host_id: UUID of host to delete.

        Raises:
            ValueError: If host not found.
        """
        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                "DELETE FROM db_hosts WHERE id = %s",
                (host_id,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Host not found: {host_id}")

    def search_hosts(self, query: str, limit: int = 10) -> list[DBHost]:
        """Search for hosts by hostname or alias.

        Used by searchable dropdown components.

        Args:
            query: Search string (minimum 3 characters recommended).
            limit: Maximum number of results to return.

        Returns:
            List of matching DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            search_pattern = f"%{query}%"
            cursor.execute(
                """
                SELECT id, hostname, host_alias, credential_ref, max_running_jobs,
                       max_active_jobs, enabled, created_at
                FROM db_hosts
                WHERE hostname LIKE %s OR host_alias LIKE %s
                ORDER BY
                    CASE WHEN hostname LIKE %s THEN 0 ELSE 1 END,
                    hostname
                LIMIT %s
                """,
                (search_pattern, search_pattern, f"{query}%", limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

    def update_host_config(
        self,
        host_id: str,
        *,
        host_alias: str | None = None,
        credential_ref: str | None = None,
        max_running_jobs: int | None = None,
        max_active_jobs: int | None = None,
    ) -> None:
        """Update host configuration by ID.

        Updates only the fields that are explicitly provided (non-None).

        Args:
            host_id: UUID string of the host to update.
            host_alias: New alias (use empty string to clear, None to skip).
            credential_ref: New credential reference (None to skip).
            max_running_jobs: New max running jobs (None to skip).
            max_active_jobs: New max active jobs (None to skip).

        Raises:
            ValueError: If host not found or limits invalid.
        """
        updates = []
        params: list[Any] = []

        if host_alias is not None:
            updates.append("host_alias = %s")
            params.append(host_alias or None)  # Empty string -> NULL
        if credential_ref is not None:
            updates.append("credential_ref = %s")
            params.append(credential_ref)
        if max_running_jobs is not None:
            if max_running_jobs < 1:
                raise ValueError("max_running_jobs must be at least 1")
            updates.append("max_running_jobs = %s")
            params.append(max_running_jobs)
        if max_active_jobs is not None:
            if max_active_jobs < 0:
                raise ValueError("max_active_jobs cannot be negative")
            updates.append("max_active_jobs = %s")
            params.append(max_active_jobs)

        if not updates:
            return  # Nothing to update

        # Validate running <= active if both are being updated (and active > 0)
        if max_running_jobs is not None and max_active_jobs is not None:
            if max_active_jobs > 0 and max_running_jobs > max_active_jobs:
                raise ValueError("max_running_jobs cannot exceed max_active_jobs")

        params.append(host_id)

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                f"UPDATE db_hosts SET {', '.join(updates)} WHERE id = %s",
                tuple(params),
            )
            conn.commit()
            # rowcount == 0 can mean either "host not found" OR "no values changed"
            # MySQL default is to return affected rows, not matched rows
            # If rowcount is 0, verify the host actually exists before reporting error
            if cursor.rowcount == 0:
                cursor.execute("SELECT 1 FROM db_hosts WHERE id = %s", (host_id,))
                if cursor.fetchone() is None:
                    raise ValueError(f"Host not found: {host_id}")

    def is_staging_db_active(
        self,
        hostname: str,
        staging_name: str,
        check_count: int = 3,
        check_delay_seconds: float = 2.0,
    ) -> bool:
        """Check if a staging database has active MySQL processes.

        Performs multiple SHOW PROCESSLIST checks to verify if a restore is
        still actively running on the staging database. This prevents false
        positives from treating long-running restores as stale jobs.

        The check runs `check_count` times with `check_delay_seconds` between
        each check. Returns True if ANY check finds activity, False only if
        ALL checks find no activity.

        Args:
            hostname: Database host to check.
            staging_name: Staging database name to look for in processlist.
            check_count: Number of times to check (default 3).
            check_delay_seconds: Delay between checks in seconds (default 2.0).

        Returns:
            True if any process is using the staging database, False otherwise.

        Raises:
            ValueError: If host not found or disabled.
            mysql.connector.Error: If connection fails.
        """
        import time

        credentials = self.get_host_credentials(hostname)

        conn = mysql.connector.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.username,
            password=credentials.password,
            connect_timeout=DEFAULT_MYSQL_CONNECT_TIMEOUT_WORKER,
        )
        try:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))

            for i in range(check_count):
                cursor.execute("SHOW PROCESSLIST")
                rows: list[dict[str, Any]] = cursor.fetchall()

                # Check if any process is using the staging database
                for row in rows:
                    if row.get("db") == staging_name:
                        logger.info(
                            "Active process found on staging database",
                            extra={
                                "staging_name": staging_name,
                                "hostname": hostname,
                                "process_id": row.get("Id"),
                                "process_user": row.get("User"),
                                "process_command": row.get("Command"),
                                "check_attempt": i + 1,
                            },
                        )
                        return True

                # Delay before next check (except on last iteration)
                if i < check_count - 1:
                    time.sleep(check_delay_seconds)

            # No activity found in any check
            logger.info(
                "No active processes found on staging database",
                extra={
                    "staging_name": staging_name,
                    "hostname": hostname,
                    "checks_performed": check_count,
                },
            )
            return False

        finally:
            conn.close()

    def _row_to_dbhost(self, row: dict[str, Any]) -> DBHost:
        """Convert database row to DBHost dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            DBHost instance with all fields populated.
        """
        return DBHost(
            id=row["id"],
            hostname=row["hostname"],
            host_alias=row.get("host_alias"),
            credential_ref=row["credential_ref"],
            max_running_jobs=row["max_running_jobs"],
            max_active_jobs=row["max_active_jobs"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )


