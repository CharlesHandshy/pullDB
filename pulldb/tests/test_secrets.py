"""Tests for AWS credential resolution (Secrets Manager and SSM).

These tests use moto to mock AWS services for unit testing.
Integration tests against real AWS services should be run separately.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator

import pytest
from moto import mock_aws

from pulldb.infra.secrets import (
    CredentialResolutionError,
    CredentialResolver,
    MySQLCredentials,
)


# Constants
DEFAULT_MYSQL_PORT = 3306


@pytest.fixture(autouse=True)
def clear_aws_profile() -> Generator[None, None, None]:
    """Clear AWS profile environment variable for tests."""
    old_profile = os.environ.pop("PULLDB_AWS_PROFILE", None)
    old_aws_profile = os.environ.pop("AWS_PROFILE", None)
    # Set default region for boto3
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    if old_profile:
        os.environ["PULLDB_AWS_PROFILE"] = old_profile
    if old_aws_profile:
        os.environ["AWS_PROFILE"] = old_aws_profile
    os.environ.pop("AWS_DEFAULT_REGION", None)


class TestMySQLCredentials:
    """Test MySQLCredentials dataclass."""

    def test_create_credentials(self) -> None:
        """Test creating credentials with all fields."""
        creds = MySQLCredentials(
            username="test_user",
            password="test_pass",
            host="db.example.com",
            port=3306,
            db_cluster_identifier="cluster-123",
        )

        assert creds.username == "test_user"
        assert creds.password == "test_pass"
        assert creds.host == "db.example.com"
        assert creds.port == DEFAULT_MYSQL_PORT
        assert creds.db_cluster_identifier == "cluster-123"

    def test_create_credentials_defaults(self) -> None:
        """Test credentials with default port."""
        creds = MySQLCredentials(username="user", password="pass", host="host.com")

        assert creds.port == DEFAULT_MYSQL_PORT
        assert creds.db_cluster_identifier is None

    def test_repr_redacts_password(self) -> None:
        """Test that __repr__ redacts the password."""
        creds = MySQLCredentials(username="user", password="secret123", host="host.com")

        repr_str = repr(creds)
        assert "secret123" not in repr_str
        assert "***REDACTED***" in repr_str
        assert "user" in repr_str
        assert "host.com" in repr_str


class TestCredentialResolver:
    """Test CredentialResolver class."""

    def test_init_default(self) -> None:
        """Test resolver initialization with defaults."""
        resolver = CredentialResolver()
        assert resolver.aws_profile is None or isinstance(resolver.aws_profile, str)

    def test_init_with_profile(self) -> None:
        """Test resolver initialization with explicit profile."""
        resolver = CredentialResolver(aws_profile="test-profile")
        assert resolver.aws_profile == "test-profile"

    def test_resolve_empty_credential_ref(self) -> None:
        """Test that empty credential_ref raises ValueError."""
        resolver = CredentialResolver()

        with pytest.raises(ValueError, match="credential_ref cannot be empty"):
            resolver.resolve("")

    def test_resolve_invalid_format(self) -> None:
        """Test that invalid credential_ref format raises ValueError."""
        resolver = CredentialResolver()

        with pytest.raises(ValueError, match="Unsupported credential reference"):
            resolver.resolve("invalid-format:/path/to/secret")


@mock_aws
class TestSecretsManagerResolution:
    """Test Secrets Manager credential resolution."""

    def test_resolve_from_secrets_manager_success(self) -> None:
        """Test successful credential resolution from Secrets Manager."""
        import boto3

        # Create mock secret
        secrets_client = boto3.client("secretsmanager", region_name="us-east-1")
        secret_value = json.dumps(
            {
                "username": "pulldb_app",
                "password": "secret123",
                "host": "localhost",
                "port": 3306,
                "dbClusterIdentifier": "localhost-test",
            }
        )
        secrets_client.create_secret(
            Name="/pulldb/mysql/localhost-test", SecretString=secret_value
        )

        # Resolve credentials
        resolver = CredentialResolver()
        creds = resolver.resolve("aws-secretsmanager:/pulldb/mysql/localhost-test")

        assert creds.username == "pulldb_app"
        assert creds.password == "secret123"
        assert creds.host == "localhost"
        assert creds.port == DEFAULT_MYSQL_PORT
        assert creds.db_cluster_identifier == "localhost-test"

    def test_resolve_missing_username(self) -> None:
        """Test that missing username field raises error."""
        import boto3

        secrets_client = boto3.client("secretsmanager", region_name="us-east-1")
        secret_value = json.dumps({"password": "secret123", "host": "db.example.com"})
        secrets_client.create_secret(
            Name="/pulldb/mysql/test", SecretString=secret_value
        )

        resolver = CredentialResolver()
        with pytest.raises(
            CredentialResolutionError, match="missing required field 'username'"
        ):
            resolver.resolve("aws-secretsmanager:/pulldb/mysql/test")

    def test_resolve_secret_not_found(self) -> None:
        """Test that non-existent secret raises appropriate error."""
        resolver = CredentialResolver()

        with pytest.raises(CredentialResolutionError, match="Secret not found"):
            resolver.resolve("aws-secretsmanager:/pulldb/mysql/nonexistent")


@mock_aws
class TestSSMResolution:
    """Test SSM Parameter Store credential resolution."""

    def test_resolve_from_ssm_success(self) -> None:
        """Test successful credential resolution from SSM."""
        import boto3

        # Create mock parameter
        ssm_client = boto3.client("ssm", region_name="us-east-1")
        parameter_value = json.dumps(
            {
                "username": "pulldb_app",
                "password": "secret456",
                "host": "localhost",
                "port": 3306,
            }
        )
        ssm_client.put_parameter(
            Name="/pulldb/mysql/localhost-test-credentials",
            Value=parameter_value,
            Type="SecureString",
        )

        # Resolve credentials
        resolver = CredentialResolver()
        creds = resolver.resolve("aws-ssm:/pulldb/mysql/localhost-test-credentials")

        assert creds.username == "pulldb_app"
        assert creds.password == "secret456"
        assert creds.host == "localhost"
        assert creds.port == DEFAULT_MYSQL_PORT

    def test_resolve_parameter_not_found(self) -> None:
        """Test that non-existent parameter raises appropriate error."""
        resolver = CredentialResolver()

        with pytest.raises(CredentialResolutionError, match="Parameter not found"):
            resolver.resolve("aws-ssm:/pulldb/mysql/nonexistent")


class TestCredentialResolutionError:
    """Test CredentialResolutionError exception."""

    def test_exception_can_be_raised(self) -> None:
        """Test that exception can be raised and caught."""
        with pytest.raises(CredentialResolutionError):
            raise CredentialResolutionError("Test error message")

    def test_exception_message(self) -> None:
        """Test that exception preserves message."""
        try:
            raise CredentialResolutionError("Custom error message")
        except CredentialResolutionError as e:
            assert str(e) == "Custom error message"
