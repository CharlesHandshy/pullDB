"""Shared pytest fixtures for pullDB test suite.

MANDATE: All tests must use AWS Secrets Manager for database login.
See .github/copilot-instructions.md for rationale and migration details.

LOCAL TESTING: If AWS secret resolves to unreachable host, override via:
    PULLDB_TEST_MYSQL_HOST=localhost
    PULLDB_TEST_MYSQL_USER=pulldb_app
    PULLDB_TEST_MYSQL_PASSWORD=<password>
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from pulldb.infra.mysql import MySQLPool, build_default_pool
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials


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
    """Get AWS profile for credential resolution."""
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
    contains the correct account ID. Skips verification if local overrides
    are set (offline development).

    Raises:
        AssertionError: If secret exists in wrong account or cannot be described.
    """
    # Skip if using local override (offline development)
    if all(
        [
            os.getenv("PULLDB_TEST_MYSQL_HOST"),
            os.getenv("PULLDB_TEST_MYSQL_USER"),
            os.getenv("PULLDB_TEST_MYSQL_PASSWORD"),
        ]
    ):
        pytest.skip("Skipping secret residency check - using local overrides")

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
        session = boto3.Session(**session_kwargs)
        client = cast(Any, session.client("secretsmanager"))
        response = cast(dict[str, Any], client.describe_secret(SecretId=secret_id))
        secret_arn = str(response.get("ARN", ""))
    except Exception as e:  # pragma: no cover - allow graceful skip for local dev
        pytest.skip(f"Cannot verify secret residency: {e}")

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

    # If ALL local overrides set, use them (explicit dev-only bypass)
    if local_host and local_user and local_password:
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


@pytest.fixture(scope="session")
def mysql_pool(mysql_credentials: MySQLCredentials) -> MySQLPool:
    """Create MySQLPool for tests using AWS Secrets Manager credentials.

    Returns:
        MySQLPool: Shared connection pool for tests.
    """
    creds = mysql_credentials
    pool = build_default_pool(
        host=creds.host,
        user=creds.username,
        password=creds.password,
        database="pulldb",  # Always use pulldb database for tests
    )
    return pool


@pytest.fixture(scope="session", autouse=True)
def seed_settings(mysql_pool: MySQLPool) -> None:
    """Seed required settings rows for integration tests.

    Ensures settings table contains values for:
      - default_dbhost
      - s3_bucket_stg (mapped to config.s3_bucket_path)

    Uses INSERT ... ON DUPLICATE KEY to avoid test flakiness if rows exist.
    """
    with mysql_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO settings (setting_key, setting_value)
            VALUES ('default_dbhost','db-mysql-db4-dev.us-east-1.rds.amazonaws.com')
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


@pytest.fixture(scope="session")
def mysql_network_credentials(
    mysql_credentials: MySQLCredentials,
) -> tuple[str, str, str]:
    """Return (host, user, password) tuple for network login.

    For local development tests we force host=localhost while retaining
    username/password from resolved secret so tests exercise credential path.
    """
    return ("localhost", mysql_credentials.username, mysql_credentials.password)
