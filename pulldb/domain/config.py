"""Configuration dataclass with AWS Secrets Manager and Parameter Store support.

Milestone 1.3 implementation: Full loading from env + MySQL settings
+ AWS Secrets Manager.
Supports both AWS Secrets Manager (recommended) and SSM Parameter Store
for credentials.

Milestone 2.7 update: Uses SettingsRepository for MySQL settings access.
"""

from __future__ import annotations

import os
import typing as t
from dataclasses import dataclass
from pathlib import Path

import boto3


if t.TYPE_CHECKING:
    from pulldb.infra.mysql import MySQLPool


@dataclass(slots=True)
class Config:
    """Configuration for pullDB with AWS Parameter Store support.

    Stores configuration values for database connections, S3 paths, AWS profiles,
    and working directories. Supports loading secure credentials from AWS Systems
    Manager Parameter Store.

    Attributes:
        mysql_host: MySQL server hostname for pullDB coordination database.
        mysql_user: MySQL username for authentication.
        mysql_password: MySQL password for authentication.
        mysql_database: MySQL database name (default: "pulldb").
        s3_bucket_path: S3 bucket path for backup archives (e.g., s3://bucket/prefix/).
        aws_profile: AWS CLI profile name for authentication.
        default_dbhost: Default target database host when not specified in CLI.
        work_dir: Temporary working directory for downloads and extraction.
        customers_after_sql_dir: Directory containing post-restore SQL scripts
            for customer databases.
        qa_template_after_sql_dir: Directory containing post-restore SQL scripts
            for QA templates.

    Examples:
        >>> config = Config(
        ...     mysql_host="localhost",
        ...     mysql_user="pulldb",
        ...     mysql_password="secret",
        ... )
        >>> config.mysql_database
        'pulldb'
    """

    mysql_host: str
    mysql_user: str
    mysql_password: str
    mysql_database: str = "pulldb"

    s3_bucket_path: str | None = None
    aws_profile: str | None = None

    default_dbhost: str | None = None

    work_dir: Path = Path("/tmp/pulldb-work")
    customers_after_sql_dir: Path = Path("customers_after_sql")
    qa_template_after_sql_dir: Path = Path("qa_template_after_sql")

    @staticmethod
    def _resolve_parameter(value: str, aws_profile: str | None = None) -> str:
        """Resolve AWS Parameter Store reference if value starts with '/'.

        Args:
            value: Either a direct value or AWS SSM parameter path
                (e.g., '/pulldb/prod/mysql/password')
            aws_profile: AWS profile to use for parameter store access

        Returns:
            Resolved value from Parameter Store or original value if not a
            parameter reference

        Raises:
            ValueError: If parameter resolution fails
        """
        if not value or not value.startswith("/"):
            return value

        # Value is a parameter path - fetch from AWS SSM
        try:
            # Set profile if provided
            if aws_profile:
                os.environ["AWS_PROFILE"] = aws_profile

            ssm: t.Any = boto3.client("ssm")  # boto3 lacks precise type stubs here
            response = ssm.get_parameter(Name=value, WithDecryption=True)
            parameter_value: str = response["Parameter"]["Value"]
            return parameter_value
        except Exception as e:
            raise ValueError(
                f"Failed to resolve AWS Parameter Store reference "
                f"'{value}': {e}\n"
                f"Ensure the parameter exists and your AWS profile has "
                f"ssm:GetParameter permissions."
            ) from e

    @classmethod
    def minimal_from_env(cls) -> Config:
        """Load configuration from environment variables.

        Supports both direct values and AWS Parameter Store references.
        Values starting with '/' are treated as AWS SSM parameter paths.

        This will be replaced with `from_env_and_mysql` in Milestone 1.3.
        Required vars for now (fallbacks allowed for prototype stubs).
        """
        # Get AWS profile first (needed for parameter resolution)
        aws_profile = os.getenv("PULLDB_AWS_PROFILE")

        # Load values (may be direct or parameter references)
        mysql_host_raw = os.getenv("PULLDB_MYSQL_HOST", "localhost")
        mysql_user_raw = os.getenv("PULLDB_MYSQL_USER", "root")
        mysql_password_raw = os.getenv("PULLDB_MYSQL_PASSWORD", "")
        mysql_database_raw = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb")

        # Resolve parameters if needed
        return cls(
            mysql_host=cls._resolve_parameter(mysql_host_raw, aws_profile),
            mysql_user=cls._resolve_parameter(mysql_user_raw, aws_profile),
            mysql_password=cls._resolve_parameter(mysql_password_raw, aws_profile),
            mysql_database=cls._resolve_parameter(mysql_database_raw, aws_profile),
            s3_bucket_path=os.getenv("PULLDB_S3_BUCKET_PATH"),
            aws_profile=aws_profile,
            default_dbhost=os.getenv("PULLDB_DEFAULT_DBHOST"),
        )

    @classmethod
    def from_env_and_mysql(cls, pool: MySQLPool) -> Config:
        """Load configuration from environment variables and MySQL settings.

        Two-phase loading pattern:
        1. Bootstrap from environment (MySQL credentials, AWS profile)
        2. Override operational settings from MySQL settings table

        The environment provides bootstrap credentials and AWS configuration.
        MySQL settings table provides operational overrides (S3 paths, work
        directories, default dbhost).

        Args:
            pool: MySQL connection pool to pulldb coordination database

        Returns:
            Fully configured Config instance with environment + MySQL settings

        Raises:
            ValueError: If required settings are missing or invalid

        Examples:
            >>> # Bootstrap: Load minimal config from environment
            >>> bootstrap_config = Config.minimal_from_env()
            >>> # Connect to MySQL using bootstrap credentials
            >>> from pulldb.infra.mysql import MySQLPool
            >>> pool = MySQLPool(
            ...     host=bootstrap_config.mysql_host,
            ...     user=bootstrap_config.mysql_user,
            ...     password=bootstrap_config.mysql_password,
            ...     database=bootstrap_config.mysql_database,
            ... )
            >>> # Enrich: Load full config with MySQL overrides
            >>> config = Config.from_env_and_mysql(pool)
        """
        # Import here to avoid circular dependency (module-level would create loop)
        from pulldb.infra.mysql import SettingsRepository  # noqa: PLC0415

        # Phase 1: Load base config from environment
        base_config = cls.minimal_from_env()

        # Phase 2: Load settings from MySQL using repository pattern
        repo = SettingsRepository(pool)
        settings = repo.get_all_settings()

        # Phase 3: Apply MySQL overrides (environment takes precedence if set)
        s3_bucket_path: str | None = (
            os.getenv("PULLDB_S3_BUCKET_PATH")
            or settings.get("s3_bucket_stg")  # Use staging as default for dev
            or settings.get("s3_bucket_prod")
        )

        default_dbhost: str | None = os.getenv("PULLDB_DEFAULT_DBHOST") or settings.get(
            "default_dbhost"
        )

        work_dir_str: str = (
            os.getenv("PULLDB_WORK_DIR")
            or settings.get("work_directory")
            or "/tmp/pulldb-work"
        )

        customers_after_sql_dir_str: str = (
            os.getenv("PULLDB_CUSTOMERS_AFTER_SQL_DIR")
            or settings.get("customers_after_sql_dir")
            or "customers_after_sql"
        )

        qa_template_after_sql_dir_str: str = (
            os.getenv("PULLDB_QA_TEMPLATE_AFTER_SQL_DIR")
            or settings.get("qa_template_after_sql_dir")
            or "qa_template_after_sql"
        )

        # Phase 4: Return fully configured instance
        return cls(
            # MySQL credentials from environment (Phase 1)
            mysql_host=base_config.mysql_host,
            mysql_user=base_config.mysql_user,
            mysql_password=base_config.mysql_password,
            mysql_database=base_config.mysql_database,
            # AWS profile from environment
            aws_profile=base_config.aws_profile,
            # Operational settings from MySQL (with environment override)
            s3_bucket_path=s3_bucket_path,
            default_dbhost=default_dbhost,
            work_dir=Path(work_dir_str),
            customers_after_sql_dir=Path(customers_after_sql_dir_str),
            qa_template_after_sql_dir=Path(qa_template_after_sql_dir_str),
        )
