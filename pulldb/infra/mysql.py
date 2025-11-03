"""MySQL infrastructure for pullDB.

Implements connection pooling and repository pattern for database access.
All database operations are encapsulated in repository classes to enforce
business rules and provide clean abstractions.
"""

from __future__ import annotations

import json
import typing as t
import uuid
from contextlib import contextmanager

import mysql.connector

from pulldb.domain.models import DBHost, Job, JobEvent, JobStatus, User
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials


class MySQLPool:
    """Very small wrapper around mysql.connector.connect for early prototype.

    Will be replaced with a real pooled implementation and per-host connections.
    """

    def __init__(self, **kwargs: t.Any) -> None:
        """Initialize MySQL connection pool.

        Args:
            **kwargs: Connection parameters passed to mysql.connector.connect().
        """
        self._kwargs = kwargs

    @contextmanager
    def connection(self) -> t.Iterator[t.Any]:
        """Get a database connection from the pool.

        Yields:
            MySQL connection object.
        """
        conn = mysql.connector.connect(**self._kwargs)
        try:
            yield conn
        finally:
            conn.close()


def build_default_pool(host: str, user: str, password: str, database: str) -> MySQLPool:
    """Build a MySQL connection pool with default configuration.

    Args:
        host: MySQL server hostname.
        user: MySQL username.
        password: MySQL password.
        database: Database name.

    Returns:
        Configured MySQLPool instance.
    """
    return MySQLPool(host=host, user=user, password=password, database=database)


class JobRepository:
    """Repository for job queue operations.

    Manages job lifecycle in MySQL coordination database. Handles job creation,
    status transitions, event logging, and queue queries. Enforces business rules
    like per-target exclusivity via database constraints.

    Example:
        >>> pool = MySQLPool(host="localhost", user="root", database="pulldb")
        >>> repo = JobRepository(pool)
        >>> job_id = repo.enqueue_job(job)
        >>> next_job = repo.get_next_queued_job()
        >>> repo.mark_job_running(next_job.id)
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize repository with connection pool.

        Args:
            pool: MySQL connection pool for coordination database.
        """
        self.pool = pool

    def enqueue_job(self, job: Job) -> str:
        """Insert new job into queue.

        Generates UUID for job if not provided. Job enters 'queued' status and
        waits for worker to pick it up. Per-target exclusivity is enforced by
        unique constraint on active_target_key.

        Args:
            job: Job to enqueue (may have empty id, will be generated).

        Returns:
            job_id: UUID of enqueued job.

        Raises:
            mysql.connector.IntegrityError: If target already has active job.
        """
        job_id = job.id if job.id else str(uuid.uuid4())

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO jobs
                    (id, owner_user_id, owner_username, owner_user_code, target,
                     staging_name, dbhost, status, submitted_at, options_json,
                     retry_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), %s, %s)
                    """,
                    (
                        job_id,
                        job.owner_user_id,
                        job.owner_username,
                        job.owner_user_code,
                        job.target,
                        job.staging_name,
                        job.dbhost,
                        job.status.value,
                        json.dumps(job.options_json) if job.options_json else None,
                        job.retry_count,
                    ),
                )
                conn.commit()
                return job_id
            except mysql.connector.IntegrityError as e:
                if "idx_jobs_active_target" in str(e):
                    raise ValueError(
                        f"Target '{job.target}' on host '{job.dbhost}' "
                        f"already has an active job"
                    ) from e
                raise

    def get_next_queued_job(self) -> Job | None:
        """Get next queued job in FIFO order.

        Returns oldest queued job by submitted_at timestamp. Used by worker
        to poll for work.

        Returns:
            Next queued job or None if queue empty.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail
                FROM jobs
                WHERE status = 'queued'
                ORDER BY submitted_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def get_job_by_id(self, job_id: str) -> Job | None:
        """Get job by ID.

        Args:
            job_id: UUID of job.

        Returns:
            Job or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            return self._row_to_job(row) if row else None

    def mark_job_running(self, job_id: str) -> None:
        """Mark job as running and set started_at timestamp.

        Called by worker when it begins processing a job. Updates status from
        'queued' to 'running' and records start time.

        Args:
            job_id: UUID of job.

        Raises:
            ValueError: If job not found or not in queued status.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'running', started_at = UTC_TIMESTAMP(6)
                WHERE id = %s AND status = 'queued'
                """,
                (job_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Job {job_id} not found or not in queued status")
            conn.commit()

    def mark_job_complete(self, job_id: str) -> None:
        """Mark job as complete and set completed_at timestamp.

        Called by worker when job successfully finishes. Updates status to
        'complete' and records completion time.

        Args:
            job_id: UUID of job.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'complete', completed_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (job_id,),
            )
            conn.commit()

    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail.

        Called by worker when job execution fails. Updates status to 'failed',
        records completion time, and stores error message.

        Args:
            job_id: UUID of job.
            error: Error message describing failure.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed', completed_at = UTC_TIMESTAMP(6),
                    error_detail = %s
                WHERE id = %s
                """,
                (error, job_id),
            )
            conn.commit()

    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running).

        Uses active_jobs view for efficient querying. Jobs returned in
        submission order (oldest first).

        Returns:
            List of active jobs ordered by submitted_at.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       status, submitted_at, started_at
                FROM active_jobs
                ORDER BY submitted_at ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_active_job(row) for row in rows]

    def get_jobs_by_user(self, user_id: str) -> list[Job]:
        """Get all jobs for a user.

        Returns jobs in reverse chronological order (newest first) for user
        job history queries.

        Args:
            user_id: User UUID.

        Returns:
            List of jobs ordered by submitted_at DESC.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, owner_user_id, owner_username, owner_user_code, target,
                       staging_name, dbhost, status, submitted_at, started_at,
                       completed_at, options_json, retry_count, error_detail
                FROM jobs
                WHERE owner_user_id = %s
                ORDER BY submitted_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def check_target_exclusivity(self, target: str, dbhost: str) -> bool:
        """Check if target can accept new job (no active jobs).

        Verifies no jobs in 'queued' or 'running' status exist for the
        target/dbhost combination. Used by CLI before enqueueing.

        Args:
            target: Target database name.
            dbhost: Target host.

        Returns:
            True if no active jobs for target, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) as count
                FROM jobs
                WHERE target = %s AND dbhost = %s
                  AND status IN ('queued', 'running')
                """,
                (target, dbhost),
            )
            row = cursor.fetchone()
            return row[0] == 0 if row else True

    def append_job_event(
        self, job_id: str, event_type: str, detail: str | None = None
    ) -> None:
        """Append event to job audit log.

        Records significant events during job execution for troubleshooting
        and progress tracking. Events are timestamped with microsecond precision.

        Common event types:
        - queued: Job submitted
        - running: Job started
        - failed: Job failed
        - complete: Job completed
        - staging_auto_cleanup: Orphaned staging dropped
        - download_started: S3 download initiated
        - restore_started: myloader execution started

        Args:
            job_id: UUID of job.
            event_type: Type of event.
            detail: Optional detail message or JSON payload.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO job_events
                (job_id, event_type, detail, logged_at)
                VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                """,
                (job_id, event_type, detail),
            )
            conn.commit()

    def get_job_events(self, job_id: str) -> list[JobEvent]:
        """Get all events for a job.

        Returns events in chronological order for job history display.

        Args:
            job_id: UUID of job.

        Returns:
            List of events ordered by logged_at.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, job_id, event_type, detail, logged_at
                FROM job_events
                WHERE job_id = %s
                ORDER BY logged_at ASC
                """,
                (job_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_job_event(row) for row in rows]

    def _row_to_job(self, row: dict[str, t.Any]) -> Job:
        """Convert MySQL row to Job dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            Job instance with all fields populated.
        """
        # Deserialize options_json if present (MySQL connector returns JSON as string)
        options_json = row.get("options_json")
        if options_json and isinstance(options_json, str):
            options_json = json.loads(options_json)

        return Job(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            owner_username=row["owner_username"],
            owner_user_code=row["owner_user_code"],
            target=row["target"],
            staging_name=row["staging_name"],
            dbhost=row["dbhost"],
            status=JobStatus(row["status"]),
            submitted_at=row["submitted_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            options_json=options_json,
            retry_count=row.get("retry_count", 0),
            error_detail=row.get("error_detail"),
        )

    def _row_to_active_job(self, row: dict[str, t.Any]) -> Job:
        """Convert active_jobs view row to Job dataclass.

        The active_jobs view returns fewer fields than the full jobs table.
        This helper populates only available fields and leaves others as None.

        Args:
            row: Dictionary from active_jobs view query.

        Returns:
            Job instance with partial fields (view subset).
        """
        return Job(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            owner_username=row["owner_username"],
            owner_user_code=row["owner_user_code"],
            target=row["target"],
            staging_name="",  # Not in view
            dbhost="",  # Not in view
            status=JobStatus(row["status"]),
            submitted_at=row["submitted_at"],
            started_at=row.get("started_at"),
            completed_at=None,
            options_json=None,
            retry_count=0,
            error_detail=None,
        )

    def _row_to_job_event(self, row: dict[str, t.Any]) -> JobEvent:
        """Convert MySQL row to JobEvent dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            JobEvent instance with all fields populated.
        """
        return JobEvent(
            id=row["id"],
            job_id=row["job_id"],
            event_type=row["event_type"],
            detail=row.get("detail"),
            logged_at=row["logged_at"],
        )


class UserRepository:
    """Repository for user operations.

    Manages user creation, lookup, and user_code generation with collision
    handling. The user_code is a critical identifier used in database naming.

    Example:
        >>> repo = UserRepository(pool)
        >>> user = repo.get_or_create_user("jdoe")
        >>> print(user.user_code)  # "jdoejd" (first 6 letters)
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize UserRepository with connection pool.

        Args:
            pool: MySQL connection pool for database access.
        """
        self.pool = pool

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username.

        Args:
            username: Username to look up.

        Returns:
            User instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, created_at,
                       disabled_at
                FROM auth_users
                WHERE username = %s
                """,
                (username,),
            )
            row = cursor.fetchone()
            return self._row_to_user(row) if row else None

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by user_id.

        Args:
            user_id: User UUID to look up.

        Returns:
            User instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT user_id, username, user_code, is_admin, created_at,
                       disabled_at
                FROM auth_users
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            return self._row_to_user(row) if row else None

    def create_user(self, username: str, user_code: str) -> User:
        """Create new user with generated UUID.

        Args:
            username: Username for new user.
            user_code: Generated user code (6 characters).

        Returns:
            Newly created User instance.

        Raises:
            ValueError: If username or user_code already exists.
        """
        user_id = str(uuid.uuid4())

        try:
            with self.pool.connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    """
                    INSERT INTO auth_users
                        (user_id, username, user_code, is_admin, created_at)
                    VALUES (%s, %s, %s, FALSE, UTC_TIMESTAMP(6))
                    """,
                    (user_id, username, user_code),
                )
                conn.commit()

                # Fetch the created user
                cursor.execute(
                    """
                    SELECT user_id, username, user_code, is_admin,
                           created_at, disabled_at
                    FROM auth_users
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError(
                        f"Failed to retrieve user after creation: {user_id}"
                    )
                return self._row_to_user(row)

        except mysql.connector.IntegrityError as e:
            if "username" in str(e):
                raise ValueError(f"Username '{username}' already exists") from e
            if "user_code" in str(e):
                raise ValueError(f"User code '{user_code}' already exists") from e
            raise

    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create new one with generated user_code.

        This method handles the complete user lifecycle:
        1. Check if user exists
        2. If not, generate unique user_code
        3. Create new user
        4. Return user (existing or new)

        Args:
            username: Username to get or create.

        Returns:
            User instance (existing or newly created).

        Raises:
            ValueError: If user_code cannot be generated or username invalid.
        """
        # Try to get existing user
        user = self.get_user_by_username(username)
        if user:
            return user

        # Generate unique user_code and create new user
        user_code = self.generate_user_code(username)
        return self.create_user(username, user_code)

    def generate_user_code(self, username: str) -> str:
        """Generate unique 6-character user code from username.

        Algorithm:
        1. Extract first 6 alphabetic characters (lowercase, letters only)
        2. Check if code is unique in database
        3. If collision, replace 6th char with next unused letter from username
        4. If still collision, try 5th char, then 4th char (max 3 adjustments)
        5. Fail if unique code cannot be generated

        Examples:
            "jdoe" → ValueError (< 6 letters)
            "johndoe" → "johndo"
            "johndoe" (collision) → "johned" (try 6th position)
            "johndoe" (collision) → "johnoe" (try 5th position)
            "johndoe" (collision) → "johode" (try 4th position)

        Args:
            username: Username to generate code from.

        Returns:
            Unique 6-character code (lowercase letters only).

        Raises:
            ValueError: If unique code cannot be generated or username has
                < 6 letters.
        """
        user_letters_required = 6  # Magic number constant for user_code length
        # Step 1: Extract letters only, lowercase
        letters = [c.lower() for c in username if c.isalpha()]

        if len(letters) < user_letters_required:
            raise ValueError(
                f"Username '{username}' has insufficient letters "
                f"(need {user_letters_required}+, found {len(letters)})"
            )

        # Step 2: Try first 6 letters
        base_code = "".join(letters[:6])
        if not self.check_user_code_exists(base_code):
            return base_code

        # Step 3: Collision handling - try positions 5, 4, 3 (max 3 adjustments)
        # Positions tried for collision resolution (6th, then 5th, then 4th char)
        for position in [5, 4, 3]:
            # Get unused letters after position
            used_letters = set(base_code[: position + 1])
            available = [c for c in letters[position + 1 :] if c not in used_letters]

            for replacement in available:
                candidate = (
                    base_code[:position] + replacement + base_code[position + 1 :]
                )
                if not self.check_user_code_exists(candidate):
                    return candidate

        # Step 4: All collision strategies exhausted
        raise ValueError(
            f"Cannot generate unique user_code for '{username}' "
            "(collision limit exceeded after 3 adjustments)"
        )

    def check_user_code_exists(self, user_code: str) -> bool:
        """Check if user_code already exists in database.

        Args:
            user_code: 6-character code to check.

        Returns:
            True if code exists, False otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM auth_users WHERE user_code = %s",
                (user_code,),
            )
            result = cursor.fetchone()
            if result is None:
                return False
            count: int = result[0]
            return count > 0

    def _row_to_user(self, row: dict[str, t.Any]) -> User:
        """Convert database row to User dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            User instance with all fields populated.
        """
        return User(
            user_id=row["user_id"],
            username=row["username"],
            user_code=row["user_code"],
            is_admin=bool(row["is_admin"]),
            created_at=row["created_at"],
            disabled_at=row.get("disabled_at"),
        )


class HostRepository:
    """Repository for database host operations.

    Manages host configuration and credential resolution for target MySQL
    servers. Integrates with AWS Secrets Manager for secure credential
    storage.

    Example:
        >>> resolver = CredentialResolver()
        >>> repo = HostRepository(pool, resolver)
        >>> host = repo.get_host_by_hostname("db-mysql-db4-dev")
        >>> creds = repo.get_host_credentials("db-mysql-db4-dev")
        >>> print(creds.username)  # "root" (from Secrets Manager)
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
            hostname: Hostname to look up (e.g., "db-mysql-db4-dev").

        Returns:
            DBHost instance if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, credential_ref, max_concurrent_restores,
                       enabled, created_at
                FROM db_hosts
                WHERE hostname = %s
                """,
                (hostname,),
            )
            row = cursor.fetchone()
            return self._row_to_dbhost(row) if row else None

    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled database hosts.

        Returns:
            List of enabled DBHost instances, ordered by hostname.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, hostname, credential_ref, max_concurrent_restores,
                       enabled, created_at
                FROM db_hosts
                WHERE enabled = TRUE
                ORDER BY hostname ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_dbhost(row) for row in rows]

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

    def check_host_capacity(self, hostname: str) -> bool:
        """Check if host has capacity for new restore job.

        Compares count of running jobs against max_concurrent_restores limit.

        Args:
            hostname: Hostname to check capacity for.

        Returns:
            True if host has capacity (running < max), False otherwise.

        Raises:
            ValueError: If host not found.
        """
        host = self.get_host_by_hostname(hostname)
        if host is None:
            raise ValueError(f"Host '{hostname}' not found")

        with self.pool.connection() as conn:
            cursor = conn.cursor()
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

            return running_count < host.max_concurrent_restores

    def _row_to_dbhost(self, row: dict[str, t.Any]) -> DBHost:
        """Convert database row to DBHost dataclass.

        Args:
            row: Dictionary from cursor.fetchone(dictionary=True).

        Returns:
            DBHost instance with all fields populated.
        """
        return DBHost(
            id=row["id"],
            hostname=row["hostname"],
            credential_ref=row["credential_ref"],
            max_concurrent_restores=row["max_concurrent_restores"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )


class SettingsRepository:
    """Repository for settings operations.

    Manages configuration settings stored in the database. Settings supplement
    environment variables and provide runtime configuration that can be updated
    without redeployment.

    Example:
        >>> repo = SettingsRepository(pool)
        >>> default_host = repo.get_setting("default_dbhost")
        >>> print(default_host)  # "db-mysql-db4-dev"
        >>> all_settings = repo.get_all_settings()
        >>> print(all_settings["s3_bucket_path"])
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize SettingsRepository with connection pool.

        Args:
            pool: MySQL connection pool for coordination database access.
        """
        self.pool = pool

    def get_setting(self, key: str) -> str | None:
        """Get setting value by key.

        Args:
            key: Setting key to look up.

        Returns:
            Setting value if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT setting_value
                FROM settings
                WHERE setting_key = %s
                """,
                (key,),
            )
            row = cursor.fetchone()
            return row["setting_value"] if row else None

    def get_setting_required(self, key: str) -> str:
        """Get required setting value.

        Args:
            key: Setting key to look up.

        Returns:
            Setting value.

        Raises:
            ValueError: If setting not found.
        """
        value = self.get_setting(key)
        if value is None:
            raise ValueError(f"Required setting '{key}' not found")
        return value

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Set setting value (INSERT or UPDATE).

        Uses INSERT ... ON DUPLICATE KEY UPDATE to handle both new settings
        and updates to existing settings in a single operation.

        Args:
            key: Setting key.
            value: Setting value.
            description: Optional description of setting purpose.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            if description is not None:
                cursor.execute(
                    """
                    INSERT INTO settings
                        (setting_key, setting_value, description, updated_at)
                    VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        description = VALUES(description),
                        updated_at = UTC_TIMESTAMP(6)
                    """,
                    (key, value, description),
                )
            else:
                # Don't update description if not provided
                cursor.execute(
                    """
                    INSERT INTO settings
                        (setting_key, setting_value, updated_at)
                    VALUES (%s, %s, UTC_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        updated_at = UTC_TIMESTAMP(6)
                    """,
                    (key, value),
                )
            conn.commit()

    def get_all_settings(self) -> dict[str, str]:
        """Get all settings as dictionary.

        Returns:
            Dictionary mapping setting keys to values.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT setting_key, setting_value
                FROM settings
                ORDER BY setting_key ASC
                """
            )
            rows = cursor.fetchall()
            return {row["setting_key"]: row["setting_value"] for row in rows}
