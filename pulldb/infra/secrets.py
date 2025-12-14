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
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from pulldb.domain.models import MySQLCredentials

logger = logging.getLogger(__name__)


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
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
    ) -> None:
        """Initialize CredentialResolver.

        Args:
            aws_profile: AWS profile name to use. If None, uses PULLDB_AWS_PROFILE
                environment variable or default AWS credentials chain.
            aws_region: AWS region for API calls. If None, uses PULLDB_AWS_REGION,
                then AWS_DEFAULT_REGION, then defaults to 'us-east-1'.
            connect_timeout: Connection timeout in seconds (default: 5.0).
            read_timeout: Read timeout in seconds (default: 10.0).
        """
        self.aws_profile = aws_profile or os.getenv("PULLDB_AWS_PROFILE")
        self.aws_region = (
            aws_region
            or os.getenv("PULLDB_AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        self._boto_config = BotoConfig(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": 3, "mode": "standard"},
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
            self._secrets_manager = session.client(
                "secretsmanager",
                config=self._boto_config,
            )
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
            self._ssm = session.client("ssm", config=self._boto_config)
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
        elif credential_ref.startswith("mock/"):
            # Mock credentials for simulation mode - return fake but valid structure
            logger.info(f"Using mock credentials for simulation: {credential_ref}")
            return MySQLCredentials(
                username="mock_user",
                password="mock_password",
                host="localhost",
                port=3306,
            )
        else:
            raise ValueError(
                f"Unsupported credential reference format: {credential_ref}. "
                f"Expected 'aws-secretsmanager:', 'aws-ssm:', or 'mock/' prefix."
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

    def get_secret_path(self, credential_ref: str) -> str | None:
        """Extract secret path from credential_ref for display or AWS console linking.

        Parses the credential reference URI and returns just the path portion,
        suitable for building AWS console URLs or displaying in UI.

        Args:
            credential_ref: Credential reference in format:
                - aws-secretsmanager:/pulldb/mysql/{db-name}
                - aws-ssm:/pulldb/mysql/{param-name}

        Returns:
            The secret/parameter path (e.g., "/pulldb/mysql/dev-db-01"),
            or None if the format is not recognized.

        Examples:
            >>> resolver = CredentialResolver()
            >>> resolver.get_secret_path("aws-secretsmanager:/pulldb/mysql/dev-db-01")
            '/pulldb/mysql/dev-db-01'
            >>> resolver.get_secret_path("aws-ssm:/pulldb/mysql/param")
            '/pulldb/mysql/param'
            >>> resolver.get_secret_path("invalid")
            None
        """
        if credential_ref.startswith("aws-secretsmanager:"):
            return credential_ref[len("aws-secretsmanager:"):]
        elif credential_ref.startswith("aws-ssm:"):
            return credential_ref[len("aws-ssm:"):]
        return None

    def get_credential_type(self, credential_ref: str) -> str | None:
        """Get the credential storage type from credential_ref.

        Args:
            credential_ref: Credential reference URI.

        Returns:
            "secretsmanager" or "ssm", or None if format not recognized.
        """
        if credential_ref.startswith("aws-secretsmanager:"):
            return "secretsmanager"
        elif credential_ref.startswith("aws-ssm:"):
            return "ssm"
        return None


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


class SecretExistsResult:
    """Result of checking if a secret exists.

    Attributes:
        exists: Whether the secret exists.
        secret_data: The secret data if exists and retrieved, else None.
        error: Error message if check failed, else None.
    """

    def __init__(
        self,
        exists: bool,
        secret_data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.exists = exists
        self.secret_data = secret_data
        self.error = error


class SecretUpsertResult:
    """Result of creating or updating a secret.

    Attributes:
        success: Whether the operation succeeded.
        was_new: True if secret was created, False if updated.
        secret_path: The secret path that was created/updated.
        error: Error message if operation failed, else None.
    """

    def __init__(
        self,
        success: bool,
        was_new: bool = False,
        secret_path: str = "",
        error: str | None = None,
    ) -> None:
        self.success = success
        self.was_new = was_new
        self.secret_path = secret_path
        self.error = error


def check_secret_exists(
    secret_path: str,
    aws_profile: str | None = None,
    aws_region: str | None = None,
    fetch_value: bool = False,
) -> SecretExistsResult:
    """Check if a secret exists in AWS Secrets Manager.

    Uses describe_secret (lightweight) or get_secret_value based on fetch_value.
    This is the "try settings first" check before creating new secrets.

    Args:
        secret_path: The secret path (e.g., /pulldb/mysql/dev-db-01).
        aws_profile: AWS profile name. Defaults to PULLDB_AWS_PROFILE env var.
        aws_region: AWS region. Defaults to PULLDB_AWS_REGION env var.
        fetch_value: If True, also retrieves the secret value (requires decrypt permission).

    Returns:
        SecretExistsResult with exists=True/False and optional secret_data.

    Examples:
        >>> result = check_secret_exists("/pulldb/mysql/dev-db-01")
        >>> if result.exists:
        ...     print("Secret already exists, reusing")
    """
    try:
        resolver = CredentialResolver(aws_profile=aws_profile, aws_region=aws_region)
        client = resolver._get_secrets_manager_client()

        if fetch_value:
            # Get full secret value (requires decrypt permission)
            response = client.get_secret_value(SecretId=secret_path)
            secret_data = json.loads(response["SecretString"])
            return SecretExistsResult(exists=True, secret_data=secret_data)
        else:
            # Just check existence (lightweight metadata call)
            client.describe_secret(SecretId=secret_path)
            return SecretExistsResult(exists=True)

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "ResourceNotFoundException":
            return SecretExistsResult(exists=False)
        elif error_code == "AccessDeniedException":
            return SecretExistsResult(
                exists=False,
                error=f"Access denied checking secret {secret_path}. Check IAM permissions.",
            )
        else:
            return SecretExistsResult(
                exists=False, error=f"Error checking secret {secret_path}: {error_code}"
            )
    except Exception as e:
        return SecretExistsResult(
            exists=False, error=f"Unexpected error checking secret: {e}"
        )


def safe_upsert_single_secret(
    secret_path: str,
    secret_data: dict[str, Any],
    aws_profile: str | None = None,
    aws_region: str | None = None,
    create_only: bool = False,
    update_only: bool = False,
) -> SecretUpsertResult:
    """Safely create or update a single secret in AWS Secrets Manager.

    SAFETY: This function only touches the single secret at secret_path.
    It never deletes or modifies other secrets.

    Args:
        secret_path: The secret path (e.g., /pulldb/mysql/dev-db-01).
        secret_data: Dict with secret values (host, password, username).
        aws_profile: AWS profile name. Defaults to PULLDB_AWS_PROFILE env var.
        aws_region: AWS region. Defaults to PULLDB_AWS_REGION env var.
        create_only: If True, fail if secret already exists.
        update_only: If True, fail if secret doesn't exist.

    Returns:
        SecretUpsertResult with success, was_new, and error info.

    Examples:
        >>> result = safe_upsert_single_secret(
        ...     "/pulldb/mysql/dev-db-01",
        ...     {"host": "db.example.com", "password": "secret", "username": "pulldb_loader"}
        ... )
        >>> if result.success:
        ...     print(f"Secret {'created' if result.was_new else 'updated'}")
    """
    try:
        resolver = CredentialResolver(aws_profile=aws_profile, aws_region=aws_region)
        client = resolver._get_secrets_manager_client()

        # Step 1: Check if secret exists (lightweight metadata call)
        exists = True
        try:
            client.describe_secret(SecretId=secret_path)
            logger.debug(f"Secret exists: {secret_path}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                exists = False
                logger.debug(f"Secret does not exist: {secret_path}")
            else:
                raise

        # Step 2: Apply safety constraints
        if create_only and exists:
            return SecretUpsertResult(
                success=False,
                was_new=False,
                secret_path=secret_path,
                error=f"Secret {secret_path} already exists (create_only=True)",
            )
        if update_only and not exists:
            return SecretUpsertResult(
                success=False,
                was_new=False,
                secret_path=secret_path,
                error=f"Secret {secret_path} does not exist (update_only=True)",
            )

        # Step 3: Perform the operation
        secret_string = json.dumps(secret_data)

        if exists:
            # Update existing secret
            client.put_secret_value(SecretId=secret_path, SecretString=secret_string)
            logger.info(f"Updated secret: {secret_path}")
            return SecretUpsertResult(
                success=True, was_new=False, secret_path=secret_path
            )
        else:
            # Create new secret with required pulldb tag
            client.create_secret(
                Name=secret_path,
                SecretString=secret_string,
                Tags=[{"Key": "Service", "Value": "pulldb"}],
            )
            logger.info(f"Created secret: {secret_path}")
            return SecretUpsertResult(
                success=True, was_new=True, secret_path=secret_path
            )

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        if error_code == "AccessDeniedException":
            return SecretUpsertResult(
                success=False,
                secret_path=secret_path,
                error=f"Access denied for secret {secret_path}. Check IAM permissions for secretsmanager:CreateSecret and secretsmanager:PutSecretValue.",
            )
        else:
            return SecretUpsertResult(
                success=False,
                secret_path=secret_path,
                error=f"AWS error ({error_code}): {error_msg}",
            )
    except Exception as e:
        return SecretUpsertResult(
            success=False,
            secret_path=secret_path,
            error=f"Unexpected error: {e}",
        )


def delete_secret_if_new(
    secret_path: str,
    was_new: bool,
    aws_profile: str | None = None,
    aws_region: str | None = None,
) -> bool:
    """Delete a secret only if it was newly created (for rollback).

    SAFETY: Only deletes if was_new=True. Pre-existing secrets are never deleted.
    Uses 7-day recovery window for safety.

    Args:
        secret_path: The secret path to potentially delete.
        was_new: Whether this secret was newly created in current operation.
        aws_profile: AWS profile name.
        aws_region: AWS region.

    Returns:
        True if deleted (or was_new=False so no action needed), False on error.
    """
    if not was_new:
        logger.debug(f"Secret {secret_path} was pre-existing, not deleting")
        return True

    try:
        resolver = CredentialResolver(aws_profile=aws_profile, aws_region=aws_region)
        client = resolver._get_secrets_manager_client()

        # Use recovery window for safety (can be recovered within 7 days)
        client.delete_secret(
            SecretId=secret_path,
            RecoveryWindowInDays=7,
        )
        logger.info(f"Deleted newly-created secret (rollback): {secret_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete secret {secret_path} during rollback: {e}")
        return False


def generate_credential_ref(host_alias: str) -> str:
    """Generate the credential_ref URI for a host alias.

    Auto-generates the credential reference path that is stored with the host.
    Users never see this - it's computed from the host alias.

    Args:
        host_alias: The host alias (e.g., "dev-db-01").

    Returns:
        Full credential_ref URI (e.g., "aws-secretsmanager:/pulldb/mysql/dev-db-01").
    """
    # Sanitize alias: lowercase, replace spaces/special chars with dashes
    safe_alias = host_alias.lower().strip()
    safe_alias = "".join(c if c.isalnum() or c == "-" else "-" for c in safe_alias)
    safe_alias = "-".join(part for part in safe_alias.split("-") if part)  # Remove consecutive dashes

    secret_path = f"/pulldb/mysql/{safe_alias}"
    return f"aws-secretsmanager:{secret_path}"


def get_secret_path_from_alias(host_alias: str) -> str:
    """Get the secret path for a host alias (without the URI prefix).

    Args:
        host_alias: The host alias (e.g., "dev-db-01").

    Returns:
        Secret path (e.g., "/pulldb/mysql/dev-db-01").
    """
    credential_ref = generate_credential_ref(host_alias)
    return credential_ref.replace("aws-secretsmanager:", "")


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
