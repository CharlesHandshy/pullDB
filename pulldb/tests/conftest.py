"""Shared pytest fixtures for pullDB test suite.

MANDATE: All tests must use AWS Secrets Manager for database login.
See .github/copilot-instructions.md for rationale and migration details.

AWS PROFILE CONFIGURATION:
    pullDB uses multiple AWS profiles for different resources:

    - pr-dev: AWS Secrets Manager access (development account 345321506926)
              Used for: MySQL coordination DB credentials, target host secrets

    - pr-staging: S3 bucket access (staging account 333204494849)
                  Used for: pestroutesrdsdbs bucket with daily/stg/ backups

    - pr-prod: S3 bucket access (production account 448509429610)
               Used for: pestroutes-rds-backup-prod-vpc-us-east-1-s3 bucket

    Set via environment or .env file:
        PULLDB_AWS_PROFILE=pr-dev         # For Secrets Manager (default)
        PULLDB_S3_AWS_PROFILE=pr-staging  # For S3 bucket access

    On EC2 with instance profile, leave PULLDB_AWS_PROFILE unset or empty.

LOCAL TESTING: If AWS secret resolves to unreachable host, override via:
    PULLDB_TEST_MYSQL_HOST=localhost
    PULLDB_TEST_MYSQL_USER=pulldb_app
    PULLDB_TEST_MYSQL_PASSWORD=<password>

.ENV FILE LOADING:
    Tests automatically load .env from:
    1. Repository root (.env)
    2. /opt/pulldb.service/.env (if exists, for installed environments)

    AWS configuration is loaded from:
    1. ~/.aws/config (standard AWS config location)
    2. AWS_CONFIG_FILE environment variable if set

    Use pytest.ini or pyproject.toml to set PYTHONDONTWRITEBYTECODE=1 to
    avoid .pyc pollution during testing.

DATABASE AUTO-SETUP:
    Tests will automatically:
    1. Create the 'pulldb' database if it doesn't exist
    2. Deploy the schema from schema/pulldb_service/*.sql
    3. Seed required settings
    4. Clean up (drop database) ONLY if it was created by tests

    Pre-existing databases are left untouched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import typing as t
from pathlib import Path
from typing import Any, cast

import pytest


# Track whether we created the database (for cleanup)
_DATABASE_CREATED_BY_TESTS = False
_PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load .env files early before any other imports that might use environment vars
def _path_exists_safe(path: Path) -> bool:
    """Check if path exists, returning False on permission errors."""
    try:
        return path.exists()
    except PermissionError:
        return False


try:
    from dotenv import load_dotenv

    # Load from repository root first (development environment)
    _repo_env = _PROJECT_ROOT / ".env"
    if _path_exists_safe(_repo_env):
        load_dotenv(_repo_env)

    # Load from installed location (production/staging)
    _installed_env = Path("/opt/pulldb.service/.env")
    if _path_exists_safe(_installed_env):
        load_dotenv(_installed_env, override=False)  # Don't override repo settings

except ImportError:
    pass  # dotenv not installed, use environment as-is

# Ensure AWS config file is discoverable
# Check standard locations and set AWS_CONFIG_FILE if not already set
if not os.getenv("AWS_CONFIG_FILE"):
    _aws_config_paths = [
        Path.home() / ".aws" / "config",
        Path("/opt/pulldb.service/.aws/config"),
    ]
    for _aws_config in _aws_config_paths:
        if _path_exists_safe(_aws_config):
            os.environ["AWS_CONFIG_FILE"] = str(_aws_config)
            break

from pulldb.infra.mysql import MySQLPool  # noqa: E402 - must load after .env
from pulldb.infra.secrets import (  # noqa: E402 - must load after .env
    CredentialResolver,
    MySQLCredentials,
)


def _wait_for_mysql(
    proc: subprocess.Popen[bytes], socket_path: Path, timeout: float = 10.0
) -> None:
    """Wait for MySQL socket to appear."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if socket_path.exists():
            return
        if proc.poll() is not None:
            raise RuntimeError("Isolated mysqld process exited prematurely.")
        time.sleep(0.1)
    raise RuntimeError(f"Isolated mysqld failed to start within {timeout}s")


def _deploy_schema(socket_path: Path) -> None:
    """Deploy schema to isolated MySQL instance."""
    # Create database first
    import mysql.connector

    conn = mysql.connector.connect(
        user="root",
        password="",
        unix_socket=str(socket_path),
    )
    cursor = conn.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS pulldb")
    conn.close()

    # Deploy schema files (schema dir is pulldb_service/)
    # Skip 300_mysql_users.sql - it contains GRANT statements for pulldb_service.*
    # which don't apply to isolated test instances using 'pulldb' database
    project_root = Path(__file__).parent.parent.parent
    schema_dir = project_root / "schema" / "pulldb_service"

    # Files to skip in isolated testing (production-only setup)
    skip_files = {"300_mysql_users.sql"}

    mysql_client = shutil.which("mysql")
    if mysql_client and schema_dir.exists():
        for sql_file in sorted(schema_dir.glob("*.sql")):
            if sql_file.name in skip_files:
                continue
            with open(sql_file) as f:
                subprocess.run(
                    [
                        mysql_client,
                        "-u",
                        "root",
                        "--socket",
                        str(socket_path),
                        "pulldb",
                    ],
                    stdin=f,
                    check=True,
                )


def _seed_isolated_settings(socket_path: Path) -> None:
    """Seed settings in isolated MySQL instance."""
    import mysql.connector

    conn = mysql.connector.connect(
        user="root",
        password="",
        unix_socket=str(socket_path),
        database="pulldb",
    )
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO settings (setting_key, setting_value)
        VALUES ('s3_bucket_stg','pestroutesrdsdbs')
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """
    )
    cursor.execute(
        """
        INSERT INTO settings (setting_key, setting_value)
        VALUES ('s3_bucket_path','pestroutesrdsdbs/daily/stg/')
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """
    )
    cursor.execute(
        """
        INSERT INTO settings (setting_key, setting_value)
        VALUES ('default_dbhost','localhost')
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """
    )
    conn.commit()
    conn.close()


def _check_database_exists(
    host: str = "localhost",
    user: str = "root",
    password: str = "",
    socket: str | None = None,
) -> bool:
    """Check if the pulldb database exists in the MySQL server."""
    import mysql.connector

    try:
        connect_kwargs: dict[str, Any] = {
            "user": user,
            "password": password,
        }
        if socket:
            connect_kwargs["unix_socket"] = socket
        else:
            connect_kwargs["host"] = host

        conn = mysql.connector.connect(**connect_kwargs)
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES LIKE 'pulldb'")
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception:
        return False


def _create_database_and_schema(
    host: str = "localhost",
    user: str = "root",
    password: str = "",
    socket: str | None = None,
) -> bool:
    """Create the pulldb database and deploy schema.

    Returns:
        True if database was created, False if it already existed.
    """
    global _DATABASE_CREATED_BY_TESTS  # noqa: PLW0603 - required for cleanup tracking
    import mysql.connector

    connect_kwargs: dict[str, Any] = {
        "user": user,
        "password": password,
    }
    if socket:
        connect_kwargs["unix_socket"] = socket
    else:
        connect_kwargs["host"] = host

    # Check if database already exists
    if _check_database_exists(host, user, password, socket):
        return False

    # Create database
    conn = mysql.connector.connect(**connect_kwargs)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE DATABASE pulldb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    conn.close()
    _DATABASE_CREATED_BY_TESTS = True

    # Deploy schema files
    # Schema lives in pulldb_service/ but we create test db named "pulldb"
    schema_dir = _PROJECT_ROOT / "schema" / "pulldb_service"
    mysql_client = shutil.which("mysql")

    if mysql_client and schema_dir.exists():
        for sql_file in sorted(schema_dir.glob("*.sql")):
            cmd = [mysql_client, "-u", user, "pulldb"]
            if password:
                cmd.extend([f"-p{password}"])
            if socket:
                cmd.extend(["--socket", socket])
            else:
                cmd.extend(["-h", host])

            with open(sql_file) as f:
                result = subprocess.run(
                    cmd,
                    check=False,
                    stdin=f,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"Failed to deploy {sql_file.name}: {result.stderr}"
                    )

    return True


def _drop_database_if_created(
    host: str = "localhost",
    user: str = "root",
    password: str = "",
    socket: str | None = None,
) -> None:
    """Drop the pulldb database if it was created by tests."""
    global _DATABASE_CREATED_BY_TESTS  # noqa: PLW0603 - required for cleanup tracking

    if not _DATABASE_CREATED_BY_TESTS:
        return

    import mysql.connector

    try:
        connect_kwargs: dict[str, Any] = {
            "user": user,
            "password": password,
        }
        if socket:
            connect_kwargs["unix_socket"] = socket
        else:
            connect_kwargs["host"] = host

        conn = mysql.connector.connect(**connect_kwargs)
        cursor = conn.cursor()
        cursor.execute("DROP DATABASE IF EXISTS pulldb")
        conn.close()
        _DATABASE_CREATED_BY_TESTS = False
    except Exception as e:
        # Log but don't fail - cleanup is best-effort
        print(f"Warning: Failed to drop test database: {e}")


@pytest.fixture(scope="session")
def aws_region() -> str:
    """Ensure AWS region is set for boto3 operations.

    Returns:
        AWS region name (default: us-east-1 per IMPLEMENTATION-PLAN.md).
    """
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    os.environ["AWS_DEFAULT_REGION"] = region
    return region


@pytest.fixture(scope="session")
def aws_profile(aws_region: str) -> str:
    """Get AWS profile for credential resolution (Secrets Manager).

    This profile is used for AWS Secrets Manager access to resolve
    MySQL credentials. The secrets reside in the development account
    (345321506926) under the pr-dev profile.

    Environment Variables:
        PULLDB_AWS_PROFILE: Primary profile for Secrets Manager
        AWS_PROFILE: Fallback if PULLDB_AWS_PROFILE not set

    Returns:
        AWS profile name, or empty string to use default credential chain.
    """
    profile = os.getenv("PULLDB_AWS_PROFILE", os.getenv("AWS_PROFILE", "default"))

    # If an explicitly specified profile looks like a production profile and may
    # not exist in local AWS config, fall back to 'default' to avoid ProfileNotFound
    # during secret resolution in local dev test runs.
    if profile in {"production", "pr-prod"}:
        return "default"
    # Treat literal 'default' as None so boto3 uses standard credential chain
    # without attempting to validate a profile section that might not exist.
    return "" if profile == "default" else profile


@pytest.fixture(scope="session")
def s3_aws_profile(aws_profile: str) -> str:
    """Get AWS profile for S3 bucket access.

    S3 backups are stored in different accounts than secrets:
    - pr-staging: pestroutesrdsdbs bucket (account 333204494849)
    - pr-prod: pestroutes-rds-backup-prod-vpc-us-east-1-s3 (account 448509429610)

    The S3 profile is separate from the Secrets Manager profile because
    backups are in staging/production accounts while secrets are in dev.

    Environment Variables:
        PULLDB_S3_AWS_PROFILE: Dedicated S3 profile (recommended)
        Falls back to PULLDB_AWS_PROFILE if not set

    Returns:
        AWS profile name for S3 operations.
    """
    s3_profile = os.getenv("PULLDB_S3_AWS_PROFILE")
    if s3_profile:
        return s3_profile
    # Fall back to main AWS profile
    return aws_profile


@pytest.fixture(scope="session")
def coordination_db_secret() -> str:
    """Get AWS Secrets Manager secret name for coordination database."""
    return os.getenv(
        "PULLDB_COORDINATION_DB_SECRET",
        "aws-secretsmanager:/pulldb/mysql/coordination-db",
    )


@pytest.fixture(scope="session")
def verify_secret_residency(
    aws_profile: str, coordination_db_secret: str, aws_region: str
) -> None:
    """Verify that secrets exist only in development account (345321506926).

    MANDATE: All pullDB secrets must reside in the development AWS account.
    Secrets must NOT exist in staging (333204494849) or production (448509429610).

    This fixture runs once per test session and asserts the secret ARN
    contains the correct account ID. Returns without verification if local
    overrides are set (offline development).

    Raises:
        AssertionError: If secret exists in wrong account or cannot be described.
    """
    # Return early if using local override (offline development)
    # No need to verify AWS residency when not using AWS credentials
    if any(
        [
            all(
                [
                    os.getenv("PULLDB_TEST_MYSQL_HOST"),
                    os.getenv("PULLDB_TEST_MYSQL_USER"),
                    os.getenv("PULLDB_TEST_MYSQL_PASSWORD") is not None,
                ]
            ),
            os.getenv("PULLDB_TEST_MYSQL_SOCKET"),
        ]
    ):
        return  # Local overrides in use, no AWS verification needed

    # Import boto3 only when needed to avoid dependency in local-only mode
    try:
        import boto3
    except ImportError:
        pytest.skip("boto3 not available - cannot verify secret residency")

    # Expected development account ID
    dev_account_id = "345321506926"
    staging_account_id = "333204494849"
    prod_account_id = "448509429610"

    # Extract secret ID from credential reference
    if not coordination_db_secret.startswith("aws-secretsmanager:"):
        pytest.skip(f"Not a Secrets Manager reference: {coordination_db_secret}")

    secret_id = coordination_db_secret.split(":", 1)[1]

    # Create Secrets Manager client with appropriate profile
    session_kwargs: dict[str, str] = {"region_name": aws_region}
    if aws_profile:
        session_kwargs["profile_name"] = aws_profile

    try:
        session = boto3.Session(
            profile_name=session_kwargs.get("profile_name"),
            region_name=session_kwargs.get("region_name"),
        )
        client = cast(Any, session.client("secretsmanager"))
        response = cast(dict[str, Any], client.describe_secret(SecretId=secret_id))
        secret_arn = str(response.get("ARN", ""))
    except Exception as e:  # pragma: no cover - allow graceful skip for local dev
        pytest.skip(f"Cannot verify secret residency: {e}")
        return  # Satisfy type checker

    # Extract account ID from ARN: arn:aws:secretsmanager:region:ACCOUNT:secret:name
    # ARN format has 6+ parts, account is at index 4
    arn_parts = secret_arn.split(":")
    min_arn_parts = 5
    if len(arn_parts) >= min_arn_parts:
        account_id = arn_parts[4]
        # Assert secret is in development account
        assert account_id == dev_account_id, (
            f"Secret {secret_id} must exist in development account "
            f"({dev_account_id}), but found in account {account_id}. "
            f"Staging={staging_account_id}, Prod={prod_account_id}"
        )
    else:
        pytest.fail(f"Invalid ARN format: {secret_arn}")


@pytest.fixture(scope="session")
def mysql_credentials(
    aws_profile: str,
    coordination_db_secret: str,
    verify_secret_residency: None,
) -> MySQLCredentials:
    """Resolve MySQL credentials from AWS Secrets Manager.

    CRITICAL: Uses AWS Secrets Manager for all database authentication.
    Direct test user logins are deprecated per Nov 2025 mandate.

    FAIL HARD: When AWS credentials unavailable and local override not set,
    tests skip with diagnostic message. Never silently falls back to defaults.

    LOCAL TESTING: Set PULLDB_TEST_MYSQL_* env vars to override when AWS
    secret points to unreachable host (e.g., placeholder RDS endpoint).
    This triggers residency check skip and uses local credentials explicitly.
    """
    # Check for local testing overrides first
    local_host = os.getenv("PULLDB_TEST_MYSQL_HOST")
    local_user = os.getenv("PULLDB_TEST_MYSQL_USER")
    local_password = os.getenv("PULLDB_TEST_MYSQL_PASSWORD")
    local_socket = os.getenv("PULLDB_TEST_MYSQL_SOCKET")

    # If socket override is set (Ephemeral Isolation)
    if local_socket and local_user is not None:
        return MySQLCredentials(
            username=local_user,
            password=local_password or "",
            host="localhost",
            port=0,
            db_cluster_identifier=None,
        )

    # If ALL local overrides set, use them (explicit dev-only bypass)
    # Note: password can be empty string (e.g., local MySQL root with no password)
    if local_host and local_user and local_password is not None:
        return MySQLCredentials(
            username=local_user,
            password=local_password,
            host=local_host,
            port=3306,
            db_cluster_identifier=None,
        )

    # Primary path: resolve from AWS Secrets Manager
    resolver_profile = aws_profile or None
    resolver = CredentialResolver(aws_profile=resolver_profile)

    try:
        return resolver.resolve(coordination_db_secret)
    except Exception as e:
        # FAIL HARD: Don't silently fall back to defaults
        # Provide diagnostic message with remediation steps
        secret_id = coordination_db_secret.split(":")[-1]
        pytest.skip(
            f"Cannot resolve MySQL credentials from AWS Secrets Manager: {e}\n\n"
            f"Secret: {coordination_db_secret}\n"
            f"AWS Profile: {aws_profile or '(default credential chain)'}\n\n"
            f"Solutions:\n"
            f"  1. Configure AWS credentials:\n"
            f"     aws configure --profile {aws_profile or 'default'}\n"
            f"     export AWS_PROFILE={aws_profile or 'default'}\n"
            f"     export AWS_DEFAULT_REGION=us-east-1\n\n"
            f"  2. Verify secret exists:\n"
            f"     aws secretsmanager describe-secret --secret-id {secret_id}\n\n"
            f"  3. Use local override (dev-only):\n"
            f"     export PULLDB_TEST_MYSQL_HOST=localhost\n"
            f"     export PULLDB_TEST_MYSQL_USER=pulldb_app\n"
            f"     export PULLDB_TEST_MYSQL_PASSWORD=your-password\n\n"
            f"See docs/testing.md for complete setup guide."
        )
        raise e  # Should be unreachable due to skip, but satisfies type checker


@pytest.fixture(scope="session")
def ensure_database(
    mysql_credentials: MySQLCredentials,
) -> t.Generator[bool, None, None]:
    """Ensure the pulldb database exists, creating it if necessary.

    This fixture:
    1. Checks if 'pulldb' database exists
    2. If not, creates it and deploys schema from schema/pulldb_service/*.sql
    3. Tracks whether it was created for cleanup
    4. On teardown, drops the database ONLY if it was created by tests

    Pre-existing databases are preserved - this fixture will not modify
    or drop them.

    Yields:
        bool: True if database was created by this fixture, False if pre-existing.
    """
    creds = mysql_credentials
    socket_path = os.getenv("PULLDB_TEST_MYSQL_SOCKET")

    # Attempt to create database if it doesn't exist
    try:
        created = _create_database_and_schema(
            host=creds.host,
            user=creds.username,
            password=creds.password,
            socket=socket_path,
        )
        if created:
            print(
                "\n[TEST SETUP] Created pulldb database (will be removed after tests)"
            )
        else:
            print("\n[TEST SETUP] Using existing pulldb database (will NOT be removed)")
    except Exception as e:
        pytest.fail(
            f"Failed to ensure pulldb database exists: {e}\n\n"
            f"Manual setup:\n"
            f"  mysql -u {creds.username} -p -e 'CREATE DATABASE pulldb'\n"
            f"  cat schema/pulldb_service/*.sql | mysql -u {creds.username} -p pulldb"
        )

    yield created

    # Cleanup: only drop if we created it
    if created:
        _drop_database_if_created(
            host=creds.host,
            user=creds.username,
            password=creds.password,
            socket=socket_path,
        )
        print("\n[TEST CLEANUP] Dropped pulldb database (created by tests)")


@pytest.fixture(scope="session")
def mysql_pool(
    mysql_credentials: MySQLCredentials,
    ensure_database: bool,
) -> MySQLPool:
    """Create MySQLPool for tests using AWS Secrets Manager credentials.

    Depends on ensure_database to guarantee the pulldb database exists.
    Also seeds test data (settings + test user) required by FK constraints.

    Returns:
        MySQLPool: Shared connection pool for tests.
    """
    from pulldb.tests.test_constants import (
        TEST_USER_CODE,
        TEST_USER_ID,
        TEST_USERNAME,
    )

    creds = mysql_credentials
    kwargs: dict[str, Any] = {
        "host": creds.host,
        "user": creds.username,
        "password": creds.password,
        "database": "pulldb",
    }

    # Check for socket override
    socket_path = os.getenv("PULLDB_TEST_MYSQL_SOCKET")
    if socket_path:
        kwargs["unix_socket"] = socket_path

    pool = MySQLPool(**kwargs)

    # Seed test data (test user + settings) - required by FK constraints
    with pool.connection() as conn:
        cursor = conn.cursor()
        # Seed test user first (jobs table has FK to auth_users)
        cursor.execute(
            """
            INSERT INTO auth_users (user_id, username, user_code, created_at)
            VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
            ON DUPLICATE KEY UPDATE username = VALUES(username)
            """,
            (TEST_USER_ID, TEST_USERNAME, TEST_USER_CODE),
        )
        # Seed required settings
        cursor.execute(
            """
            INSERT INTO settings (setting_key, setting_value)
            VALUES ('default_dbhost','localhost')
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
            """
        )
        cursor.execute(
            """
            INSERT INTO settings (setting_key, setting_value)
            VALUES ('s3_bucket_stg','pestroutesrdsdbs')
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
            """
        )
        cursor.execute(
            """
            INSERT INTO settings (setting_key, setting_value)
            VALUES ('s3_bucket_path','pestroutesrdsdbs/daily/stg/')
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
            """
        )
        conn.commit()
        cursor.close()

    return pool


@pytest.fixture(scope="session")
def mysql_network_credentials(
    mysql_credentials: MySQLCredentials,
) -> tuple[str, str, str]:
    """Return (host, user, password) tuple for network login.

    For local development tests we force host=localhost while retaining
    username and password from test environment.

    Note: In production, mysql_user is set per-service:
    - PULLDB_API_MYSQL_USER for API service
    - PULLDB_WORKER_MYSQL_USER for Worker service

    For tests, we pass credentials directly rather than through env vars.
    """
    return ("localhost", mysql_credentials.username, mysql_credentials.password)


@pytest.fixture(scope="session")
def isolated_mysql(
    tmp_path_factory: pytest.TempPathFactory,
) -> t.Generator[str, None, None]:
    """Create an ephemeral, isolated MySQL instance for testing.

    This fixture:
    1. Creates a temporary data directory.
    2. Initializes a fresh MySQL database.
    3. Starts mysqld bound ONLY to a Unix socket (no TCP ports).
    4. Sets PULLDB_TEST_MYSQL_* environment variables to point to it.
    5. Cleans up the process on teardown.

    This enables parallel test execution on the same machine without port conflicts
    or root privileges.
    """
    # 1. Setup directories
    base_dir = tmp_path_factory.mktemp("mysql_data")
    data_dir = base_dir / "data"
    socket_path = base_dir / "mysql.sock"
    pid_file = base_dir / "mysql.pid"

    # Check for mysqld
    mysqld_bin = shutil.which("mysqld")
    if not mysqld_bin:
        pytest.skip(
            "mysqld not found in PATH. Install mysql-server to use isolated testing."
        )
    mysqld_bin = cast(str, mysqld_bin)

    # 2. Initialize Database
    try:
        subprocess.run(
            [
                mysqld_bin,
                "--no-defaults",
                "--initialize-insecure",
                f"--datadir={data_dir}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        pytest.skip(f"Failed to initialize isolated MySQL: {e.stderr}")

    # 3. Start mysqld
    server_cmd = [
        mysqld_bin,
        "--no-defaults",
        f"--datadir={data_dir}",
        f"--socket={socket_path}",
        f"--pid-file={pid_file}",
        "--skip-networking",
        "--mysqlx=0",
    ]

    proc = subprocess.Popen(
        server_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 4. Wait for readiness
    try:
        _wait_for_mysql(proc, socket_path)
    except RuntimeError as e:
        proc.terminate()
        pytest.fail(str(e))

    # 5. Configure Environment
    os.environ["PULLDB_TEST_MYSQL_HOST"] = "localhost"
    os.environ["PULLDB_TEST_MYSQL_USER"] = "root"
    os.environ["PULLDB_TEST_MYSQL_PASSWORD"] = ""
    os.environ["PULLDB_TEST_MYSQL_SOCKET"] = str(socket_path)
    os.environ["PULLDB_TEST_MYSQL_DATABASE"] = "pulldb"

    # Set env vars for direct MySQL connections in tests.
    # Note: PULLDB_MYSQL_USER is deprecated; in production, services use:
    # - PULLDB_API_MYSQL_USER for API service
    # - PULLDB_WORKER_MYSQL_USER for Worker service
    # Config.minimal_from_env() does NOT read PULLDB_MYSQL_USER.
    # We set it here for test fixtures that connect directly to MySQL.
    os.environ["PULLDB_MYSQL_HOST"] = "localhost"
    os.environ["PULLDB_MYSQL_USER"] = "root"  # Only for test fixtures
    os.environ["PULLDB_MYSQL_PASSWORD"] = ""
    os.environ["PULLDB_MYSQL_SOCKET"] = str(socket_path)
    os.environ["PULLDB_MYSQL_DATABASE"] = "pulldb"

    # 6. Deploy Schema
    try:
        _deploy_schema(socket_path)
        _seed_isolated_settings(socket_path)
    except Exception as e:
        proc.terminate()
        pytest.fail(f"Failed to configure isolated MySQL: {e}")

    yield str(socket_path)

    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def isolated_mysql_pool(
    isolated_mysql: str,
) -> MySQLPool:
    """Create MySQLPool for isolated MySQL testing.

    Unlike mysql_pool, this does NOT depend on ensure_database or mysql_credentials.
    The isolated_mysql fixture sets up the database and schema directly.

    Args:
        isolated_mysql: Socket path from isolated_mysql fixture.

    Returns:
        MySQLPool: Connection pool for isolated MySQL instance.
    """
    return MySQLPool(
        host="localhost",
        user="root",
        password="",
        database="pulldb",
        unix_socket=isolated_mysql,
    )


@pytest.fixture
def isolated_worker(
    isolated_mysql: str,
) -> t.Generator[subprocess.Popen[bytes], None, None]:
    """Start a worker process connected to the isolated database.

    This fixture starts the worker service as a subprocess, ensuring it
    connects to the ephemeral MySQL instance via the environment variables
    set by isolated_mysql.
    """
    cmd = [sys.executable, "-m", "pulldb.worker.service"]

    # Ensure PYTHONPATH includes project root
    env = os.environ.copy()

    # Prevent secret resolution from overriding isolated credentials
    # We set it to empty string instead of popping to prevent load_dotenv from
    # restoring it from a local .env file.
    env["PULLDB_COORDINATION_SECRET"] = ""

    # Worker service requires per-service MySQL user env var
    # In isolated mode, we use root with no password
    env["PULLDB_WORKER_MYSQL_USER"] = "root"
    env["PULLDB_WORKER_MYSQL_PASSWORD"] = ""

    project_root = str(Path(__file__).parent.parent.parent)
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{project_root}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = project_root

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Give it a moment to start
    time.sleep(1)
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        pytest.fail(
            f"Worker failed to start:\n"
            f"STDOUT: {stdout.decode()}\n"
            f"STDERR: {stderr.decode()}"
        )

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
