"""AWS Secrets Manager and SSM Parameter Store credential resolution.

This module provides the CredentialResolver class for retrieving MySQL credentials
from AWS Secrets Manager or SSM Parameter Store. Supports credential references
in the format:
    - aws-secretsmanager:/pulldb/mysql/localhost-test
    - aws-ssm:/pulldb/mysql/localhost-test-credentials

IMPORTANT: For /pulldb/mysql/* secrets, Secrets Manager only stores:
    - host: MySQL server hostname
    - password: MySQL password

Username is set per-service via environment variables:
    - PULLDB_API_MYSQL_USER: API service MySQL user
    - PULLDB_WORKER_MYSQL_USER: Worker service MySQL user

Other connection parameters from environment:
    - PULLDB_MYSQL_PORT: MySQL port (optional, defaults to 3306)
    - PULLDB_MYSQL_DATABASE: Database name (optional)

See docs/AWS-SETUP.md for complete setup instructions.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MySQLCredentials:
    """MySQL database connection credentials.

    Attributes:
        username: MySQL username for authentication.
        password: MySQL password for authentication.
        host: MySQL server hostname or endpoint.
        port: MySQL server port (default: 3306).
        dbClusterIdentifier: Optional RDS/Aurora cluster identifier for rotation.

    Examples:
        >>> creds = MySQLCredentials(
        ...     username="pulldb_app",
        ...     password="secret123",
        ...     host="localhost",
        ...     port=3306,
        ... )
        >>> creds.host
        'localhost'
    """

    username: str
    password: str
    host: str
    port: int = 3306
    db_cluster_identifier: str | None = None

    def __repr__(self) -> str:
        """Return string representation with password redacted."""
        return (
            f"MySQLCredentials(username={self.username!r}, "
            f"password='***REDACTED***', "
            f"host={self.host!r}, "
            f"port={self.port})"
        )


class CredentialResolver:
    """Resolve MySQL credentials from AWS Secrets Manager or SSM Parameter Store.

    This class handles credential retrieval from AWS services based on
    credential reference strings. Supports both AWS Secrets Manager (recommended)
    and SSM Parameter Store.

    The AWS profile is determined by the PULLDB_AWS_PROFILE environment variable.
    If not set, uses the default AWS credentials chain (instance profile, etc.).

    The AWS region is determined by:
    1. aws_region parameter (if provided)
    2. PULLDB_AWS_REGION environment variable
    3. AWS_DEFAULT_REGION environment variable
    4. Defaults to 'us-east-1'

    Attributes:
        aws_profile: AWS profile name to use for credentials (None = default chain).
        aws_region: AWS region for API calls.
        _secrets_manager: Boto3 Secrets Manager client (lazy-initialized).
        _ssm: Boto3 SSM client (lazy-initialized).

    Examples:
        >>> resolver = CredentialResolver()
        >>> creds = resolver.resolve("aws-secretsmanager:/pulldb/mysql/localhost-test")
        >>> print(creds.username)
        pulldb_app

        >>> # With explicit profile and region
        >>> resolver = CredentialResolver(
        ...     aws_profile="production", aws_region="us-west-2"
        ... )
        >>> creds = resolver.resolve("aws-ssm:/pulldb/mysql/localhost-test-credentials")

    Raises:
        ValueError: If credential_ref format is invalid or unsupported.
        CredentialResolutionError: If credential retrieval fails.
    """

    def __init__(
        self,
        aws_profile: str | None = None,
        aws_region: str | None = None,
    ) -> None:
        """Initialize CredentialResolver.

        Args:
            aws_profile: AWS profile name to use. If None, uses PULLDB_AWS_PROFILE
                environment variable or default AWS credentials chain.
            aws_region: AWS region for API calls. If None, uses PULLDB_AWS_REGION,
                then AWS_DEFAULT_REGION, then defaults to 'us-east-1'.
        """
        self.aws_profile = aws_profile or os.getenv("PULLDB_AWS_PROFILE")
        self.aws_region = (
            aws_region
            or os.getenv("PULLDB_AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        self._secrets_manager: Any = None
        self._ssm: Any = None

        # Set AWS profile in environment if provided
        if self.aws_profile:
            os.environ["AWS_PROFILE"] = self.aws_profile
            logger.debug(f"Using AWS profile: {self.aws_profile}")
        logger.debug(f"Using AWS region: {self.aws_region}")

    def _get_secrets_manager_client(self) -> Any:
        """Get or create Secrets Manager client (lazy initialization).

        Returns:
            Boto3 Secrets Manager client.
        """
        if self._secrets_manager is None:
            session = boto3.Session(
                profile_name=self.aws_profile,
                region_name=self.aws_region,
            )
            self._secrets_manager = session.client("secretsmanager")
            logger.debug(
                f"Initialized Secrets Manager client "
                f"(region={self.aws_region}, profile={self.aws_profile})"
            )
        return self._secrets_manager

    def _get_ssm_client(self) -> Any:
        """Get or create SSM client (lazy initialization).

        Returns:
            Boto3 SSM client.
        """
        if self._ssm is None:
            session = boto3.Session(
                profile_name=self.aws_profile,
                region_name=self.aws_region,
            )
            self._ssm = session.client("ssm")
            logger.debug(
                f"Initialized SSM client "
                f"(region={self.aws_region}, profile={self.aws_profile})"
            )
        return self._ssm

    def resolve(self, credential_ref: str) -> MySQLCredentials:
        """Resolve credential reference to MySQL credentials.

        Args:
            credential_ref: Credential reference in format:
                - aws-secretsmanager:/pulldb/mysql/{db-name}
                - aws-ssm:/pulldb/mysql/{param-name}

        Returns:
            MySQLCredentials with resolved values.

        Raises:
            ValueError: If credential_ref format is invalid.
            CredentialResolutionError: If credential retrieval fails.

        Examples:
            >>> resolver = CredentialResolver()
            >>> creds = resolver.resolve(
            ...     "aws-secretsmanager:/pulldb/mysql/localhost-test"
            ... )
            >>> creds.username
            'pulldb_app'
        """
        if not credential_ref:
            raise ValueError("credential_ref cannot be empty")

        logger.debug(f"Resolving credential reference: {credential_ref}")

        # Parse credential reference
        if credential_ref.startswith("aws-secretsmanager:"):
            secret_id = credential_ref[len("aws-secretsmanager:") :]
            return self._resolve_from_secrets_manager(secret_id)
        elif credential_ref.startswith("aws-ssm:"):
            parameter_name = credential_ref[len("aws-ssm:") :]
            return self._resolve_from_ssm(parameter_name)
        else:
            raise ValueError(
                f"Unsupported credential reference format: {credential_ref}. "
                f"Expected 'aws-secretsmanager:' or 'aws-ssm:' prefix."
            )

    def _resolve_from_secrets_manager(self, secret_id: str) -> MySQLCredentials:
        """Resolve credentials from AWS Secrets Manager.

        Secrets Manager secrets for /pulldb/mysql/* paths contain only:
        - host: MySQL server hostname
        - password: MySQL password

        Username is set per-service by the caller (API or Worker).
        Port comes from PULLDB_MYSQL_PORT (optional, defaults to 3306).

        Args:
            secret_id: Secrets Manager secret ID (e.g., /pulldb/mysql/localhost-test).

        Returns:
            MySQLCredentials with resolved values (secret + environment).
            Note: username field is a placeholder; caller sets actual username.

        Raises:
            CredentialResolutionError: If secret retrieval or parsing fails.
        """
        try:
            logger.debug(f"Fetching secret from Secrets Manager: {secret_id}")
            client = self._get_secrets_manager_client()

            response = client.get_secret_value(SecretId=secret_id)
            secret_string = response["SecretString"]

            # Parse JSON secret
            secret_data = json.loads(secret_string)

            # Extract fields from Secrets Manager
            password = secret_data.get("password")
            host = secret_data.get("host")
            
            # Username can come from secret (for target db credentials)
            # or be empty (for coordination db where caller sets it)
            username = secret_data.get("username", "")

            # Validate required secret fields
            if password is None:
                raise CredentialResolutionError(
                    f"Secret {secret_id} missing required field 'password'"
                )
            if not host:
                raise CredentialResolutionError(
                    f"Secret {secret_id} missing required field 'host'"
                )

            port_str = os.getenv("PULLDB_MYSQL_PORT", "3306")
            try:
                port = int(port_str)
            except ValueError as e:
                raise CredentialResolutionError(
                    f"PULLDB_MYSQL_PORT must be a valid integer; got '{port_str}'"
                ) from e

            # dbClusterIdentifier is optional and still comes from secret if present
            cluster_id = secret_data.get("dbClusterIdentifier")

            logger.info(
                f"Successfully resolved credentials from Secrets Manager: "
                f"{secret_id} (host={host})"
            )

            return MySQLCredentials(
                username=username,
                password=password,
                host=host,
                port=port,
                db_cluster_identifier=cluster_id,
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "ResourceNotFoundException":
                raise CredentialResolutionError(
                    f"Secret not found: {secret_id}. "
                    f"Ensure the secret exists and you have permission to access it."
                ) from e
            elif error_code == "AccessDeniedException":
                raise CredentialResolutionError(
                    f"Access denied to secret: {secret_id}. "
                    f"Check IAM permissions for secretsmanager:GetSecretValue."
                ) from e
            else:
                raise CredentialResolutionError(
                    f"Failed to retrieve secret {secret_id}: {error_code} - {e}"
                ) from e
        except (json.JSONDecodeError, KeyError) as e:
            raise CredentialResolutionError(
                f"Invalid secret format for {secret_id}: {e}. "
                f"Expected JSON with username, password, and host fields."
            ) from e
        except (BotoCoreError, Exception) as e:
            raise CredentialResolutionError(
                f"Unexpected error resolving secret {secret_id}: {e}"
            ) from e

    def _resolve_from_ssm(self, parameter_name: str) -> MySQLCredentials:
        """Resolve credentials from AWS SSM Parameter Store.

        SSM parameters for /pulldb/mysql/* paths contain only:
        - host: MySQL server hostname
        - password: MySQL password

        Username is set per-service by the caller (API or Worker).
        Port comes from PULLDB_MYSQL_PORT (optional, defaults to 3306).

        Args:
            parameter_name: SSM parameter name
                (e.g., /pulldb/mysql/localhost-test-credentials).

        Returns:
            MySQLCredentials with resolved values (SSM + environment).
            Note: username field is a placeholder; caller sets actual username.

        Raises:
            CredentialResolutionError: If parameter retrieval or parsing fails.
                or if required environment variables are missing.
        """
        try:
            logger.debug(f"Fetching parameter from SSM: {parameter_name}")
            client = self._get_ssm_client()

            response = client.get_parameter(Name=parameter_name, WithDecryption=True)
            parameter_value = response["Parameter"]["Value"]

            # Parse JSON parameter value
            param_data = json.loads(parameter_value)

            # Extract fields from SSM (host and password only)
            password = param_data.get("password")
            host = param_data.get("host")

            # Validate required SSM fields
            if password is None:
                raise CredentialResolutionError(
                    f"Parameter {parameter_name} missing required field 'password'"
                )
            if not host:
                raise CredentialResolutionError(
                    f"Parameter {parameter_name} missing required field 'host'"
                )

            # Get remaining fields from environment variables
            # Note: username is set per-service via PULLDB_API_MYSQL_USER or PULLDB_WORKER_MYSQL_USER
            # The caller sets config.mysql_user before calling resolve()
            username = ""  # Placeholder - caller provides actual username

            port_str = os.getenv("PULLDB_MYSQL_PORT", "3306")
            try:
                port = int(port_str)
            except ValueError as e:
                raise CredentialResolutionError(
                    f"PULLDB_MYSQL_PORT must be a valid integer; got '{port_str}'"
                ) from e

            logger.info(
                f"Successfully resolved credentials from SSM: "
                f"{parameter_name} (host={host})"
            )

            return MySQLCredentials(
                username=username, password=password, host=host, port=port
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "ParameterNotFound":
                raise CredentialResolutionError(
                    f"Parameter not found: {parameter_name}. "
                    f"Ensure the parameter exists and you have permission to access it."
                ) from e
            elif error_code == "AccessDeniedException":
                raise CredentialResolutionError(
                    f"Access denied to parameter: {parameter_name}. "
                    f"Check IAM permissions for ssm:GetParameter."
                ) from e
            else:
                raise CredentialResolutionError(
                    f"Failed to retrieve parameter {parameter_name}: {error_code} - {e}"
                ) from e
        except (json.JSONDecodeError, KeyError) as e:
            raise CredentialResolutionError(
                f"Invalid parameter format for {parameter_name}: {e}. "
                f"Expected JSON with username, password, and host fields."
            ) from e
        except (BotoCoreError, Exception) as e:
            raise CredentialResolutionError(
                f"Unexpected error resolving parameter {parameter_name}: {e}"
            ) from e


class CredentialResolutionError(Exception):
    """Exception raised when credential resolution fails.

    This exception indicates that credential retrieval from AWS Secrets Manager
    or SSM Parameter Store failed. Common causes include:
    - Secret/parameter does not exist
    - Insufficient IAM permissions
    - Invalid credential format
    - AWS API errors

    Attributes:
        message: Human-readable error description.
    """

    pass


# Example usage for testing
if __name__ == "__main__":
    import sys

    # Configure logging for testing
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    MIN_ARGS = 2
    if len(sys.argv) < MIN_ARGS:
        print("Usage: python -m pulldb.infra.secrets <credential_ref>")
        print()
        print("Examples:")
        print(
            "  python -m pulldb.infra.secrets aws-secretsmanager:/pulldb/mysql/localhost-test"
        )
        print(
            "  python -m pulldb.infra.secrets aws-ssm:/pulldb/mysql/localhost-test-credentials"
        )
        sys.exit(1)

    credential_ref = sys.argv[1]

    try:
        resolver = CredentialResolver()
        credentials = resolver.resolve(credential_ref)
        print()
        print("✓ Credential resolution successful!")
        print(f"  Username: {credentials.username}")
        print(f"  Password: {'*' * len(credentials.password)}")
        print(f"  Host:     {credentials.host}")
        print(f"  Port:     {credentials.port}")
        if credentials.db_cluster_identifier:
            print(f"  Cluster:  {credentials.db_cluster_identifier}")
    except (ValueError, CredentialResolutionError) as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
