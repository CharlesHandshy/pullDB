"""Configuration dataclass with AWS Secrets Manager and Parameter Store support.

Milestone 1.3 implementation: Full loading from env + MySQL settings
+ AWS Secrets Manager.
Supports both AWS Secrets Manager (recommended) and SSM Parameter Store
for credentials.

Milestone 2.7 update: Uses SettingsRepository for MySQL settings access.
"""

from __future__ import annotations

import json
import os
import shlex
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

import boto3


if t.TYPE_CHECKING:
    from pulldb.infra.mysql import MySQLPool

from pulldb.infra.s3 import parse_s3_bucket_path


@dataclass(slots=True)
class S3BackupLocationConfig:
    """Declarative description of an S3 backup location and target aliases."""

    name: str
    bucket_path: str
    bucket: str
    prefix: str
    format_tag: str
    target_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def aliases_for_target(self, target: str) -> tuple[str, ...]:
        """Return configured alias tuple for target (empty tuple when missing)."""
        return self.target_aliases.get(target, ())


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
        aws_profile: AWS CLI profile name for authentication (Secrets Manager,
            MySQL settings, etc.).
        s3_aws_profile: Optional AWS CLI profile dedicated to S3 discovery
            (falls back to aws_profile when unset).
        default_dbhost: Default target database host when not specified in CLI.
        work_dir: Temporary working directory for downloads and extraction.
        customers_after_sql_dir: Directory containing post-restore SQL scripts
            for customer databases.
        qa_template_after_sql_dir: Directory containing post-restore SQL scripts
            for QA templates.
        myloader_binary: Binary name or absolute path for myloader execution.
        myloader_extra_args: Additional myloader CLI arguments sourced from
            environment or MySQL settings.
        myloader_timeout_seconds: Maximum seconds to allow myloader to run
            before timing out.
        myloader_threads: Preferred myloader thread count when not supplied by
            per-job overrides.

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
    s3_aws_profile: str | None = None

    default_dbhost: str | None = None

    work_dir: Path = Path("/tmp/pulldb-work")
    customers_after_sql_dir: Path = Path("customers_after_sql")
    qa_template_after_sql_dir: Path = Path("qa_template_after_sql")
    myloader_binary: str = "/opt/pulldb/bin/myloader-0.19.3-3"
    myloader_extra_args: tuple[str, ...] = ()
    myloader_timeout_seconds: float = 7200.0
    myloader_threads: int = 8
    s3_backup_locations: tuple[S3BackupLocationConfig, ...] = ()

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
        # Get AWS profiles first (Secrets + optional distinct S3 profile)
        aws_profile = os.getenv("PULLDB_AWS_PROFILE")
        s3_aws_profile = os.getenv("PULLDB_S3_AWS_PROFILE") or aws_profile

        # Load values (may be direct or parameter references)
        mysql_host_raw = os.getenv("PULLDB_MYSQL_HOST", "localhost")
        mysql_user_raw = os.getenv("PULLDB_MYSQL_USER", "root")
        mysql_password_raw = os.getenv("PULLDB_MYSQL_PASSWORD", "")
        mysql_database_raw = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb")

        myloader_binary = _strip_or_none(os.getenv("PULLDB_MYLOADER_BINARY"))
        extra_args_env = _strip_or_none(os.getenv("PULLDB_MYLOADER_EXTRA_ARGS"))
        timeout_env = _strip_or_none(os.getenv("PULLDB_MYLOADER_TIMEOUT_SECONDS"))
        threads_env = _strip_or_none(os.getenv("PULLDB_MYLOADER_THREADS"))

        myloader_timeout_seconds = (
            _parse_positive_float(
                timeout_env,
                source="PULLDB_MYLOADER_TIMEOUT_SECONDS",
            )
            if timeout_env
            else 7200.0
        )
        myloader_threads = (
            _parse_positive_int(
                threads_env,
                source="PULLDB_MYLOADER_THREADS",
            )
            if threads_env
            else 8
        )

        # Resolve parameters if needed
        return cls(
            mysql_host=cls._resolve_parameter(mysql_host_raw, aws_profile),
            mysql_user=cls._resolve_parameter(mysql_user_raw, aws_profile),
            mysql_password=cls._resolve_parameter(mysql_password_raw, aws_profile),
            mysql_database=cls._resolve_parameter(mysql_database_raw, aws_profile),
            s3_bucket_path=os.getenv("PULLDB_S3_BUCKET_PATH"),
            aws_profile=aws_profile,
            s3_aws_profile=s3_aws_profile,
            default_dbhost=os.getenv("PULLDB_DEFAULT_DBHOST"),
            myloader_binary=myloader_binary or "/opt/pulldb/bin/myloader-0.19.3-3",
            myloader_extra_args=_parse_extra_args(
                extra_args_env,
                source="PULLDB_MYLOADER_EXTRA_ARGS",
            ),
            myloader_timeout_seconds=myloader_timeout_seconds,
            myloader_threads=myloader_threads,
            s3_backup_locations=_load_s3_backup_locations(
                os.getenv("PULLDB_S3_BACKUP_LOCATIONS"),
                os.getenv("PULLDB_S3_BUCKET_PATH"),
            ),
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

        myloader_binary = base_config.myloader_binary
        if "PULLDB_MYLOADER_BINARY" not in os.environ:
            mysql_binary = _strip_or_none(settings.get("myloader_binary"))
            if mysql_binary:
                myloader_binary = mysql_binary

        myloader_extra_args = base_config.myloader_extra_args
        if "PULLDB_MYLOADER_EXTRA_ARGS" not in os.environ:
            mysql_extra = _strip_or_none(settings.get("myloader_extra_args"))
            if mysql_extra:
                myloader_extra_args = _parse_extra_args(
                    mysql_extra,
                    source="settings.myloader_extra_args",
                )

        myloader_timeout_seconds = base_config.myloader_timeout_seconds
        if "PULLDB_MYLOADER_TIMEOUT_SECONDS" not in os.environ:
            mysql_timeout = _strip_or_none(settings.get("myloader_timeout_seconds"))
            if mysql_timeout:
                myloader_timeout_seconds = _parse_positive_float(
                    mysql_timeout,
                    source="settings.myloader_timeout_seconds",
                )

        myloader_threads = base_config.myloader_threads
        if "PULLDB_MYLOADER_THREADS" not in os.environ:
            mysql_threads = _strip_or_none(settings.get("myloader_threads"))
            if mysql_threads:
                myloader_threads = _parse_positive_int(
                    mysql_threads,
                    source="settings.myloader_threads",
                )

        backup_locations_source = os.getenv(
            "PULLDB_S3_BACKUP_LOCATIONS"
        ) or settings.get("s3_backup_locations")
        s3_backup_locations = _load_s3_backup_locations(
            backup_locations_source,
            s3_bucket_path,
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
            s3_aws_profile=base_config.s3_aws_profile,
            # Operational settings from MySQL (with environment override)
            s3_bucket_path=s3_bucket_path,
            default_dbhost=default_dbhost,
            work_dir=Path(work_dir_str),
            customers_after_sql_dir=Path(customers_after_sql_dir_str),
            qa_template_after_sql_dir=Path(qa_template_after_sql_dir_str),
            myloader_binary=myloader_binary,
            myloader_extra_args=myloader_extra_args,
            myloader_timeout_seconds=myloader_timeout_seconds,
            myloader_threads=myloader_threads,
            s3_backup_locations=s3_backup_locations,
        )


def _strip_or_none(value: str | None) -> str | None:
    """Return stripped value or None when empty."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_extra_args(value: str | None, *, source: str) -> tuple[str, ...]:
    """Parse space-delimited CLI args into tuple preserving order."""
    if not value:
        return ()
    try:
        tokens = shlex.split(value)
    except ValueError as exc:  # pragma: no cover - invalid quoting is rare
        raise ValueError(
            f"{source} contains invalid quoting: {value}. "
            "Use shell-style quoting for arguments with spaces."
        ) from exc
    return tuple(tokens)


def _parse_positive_float(value: str, *, source: str) -> float:
    """Parse positive float from string with FAIL HARD diagnostics."""
    try:
        parsed = float(value)
    except ValueError as exc:  # pragma: no cover - invalid literal
        raise ValueError(
            f"{source} must be a positive number; received '{value}'"
        ) from exc
    if parsed <= 0:
        raise ValueError(f"{source} must be greater than zero; received '{value}'")
    return parsed


def _parse_positive_int(value: str, *, source: str) -> int:
    """Parse positive integer from string with FAIL HARD diagnostics."""
    try:
        parsed = int(value)
    except ValueError as exc:  # pragma: no cover - invalid literal
        raise ValueError(
            f"{source} must be a positive integer; received '{value}'"
        ) from exc
    if parsed <= 0:
        raise ValueError(f"{source} must be a positive integer; received '{value}'")
    return parsed


def _load_s3_backup_locations(
    raw_locations: str | None,
    fallback_bucket_path: str | None,
) -> tuple[S3BackupLocationConfig, ...]:
    """Parse configured S3 backup locations or build fallback from bucket path."""
    if raw_locations:
        return _parse_s3_backup_locations(raw_locations)

    if fallback_bucket_path:
        bucket, prefix = parse_s3_bucket_path(fallback_bucket_path)
        return (
            S3BackupLocationConfig(
                name="default",
                bucket_path=fallback_bucket_path,
                bucket=bucket,
                prefix=prefix,
                format_tag="legacy",
            ),
        )

    return ()


def _parse_s3_backup_locations(
    raw_locations: str,
) -> tuple[S3BackupLocationConfig, ...]:
    try:
        payload = json.loads(raw_locations)
    except json.JSONDecodeError as exc:  # pragma: no cover - invalid json rare
        raise ValueError(
            "PULLDB_S3_BACKUP_LOCATIONS must contain valid JSON array"
        ) from exc

    if not isinstance(payload, list):
        raise ValueError("S3 backup locations must be a JSON array of objects")

    locations: list[S3BackupLocationConfig] = []
    for idx, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise ValueError(
                "Each S3 backup location must be an object with bucket_path and optional metadata"
            )
        bucket_path = _strip_or_none(entry.get("bucket_path"))
        if not bucket_path:
            raise ValueError("S3 backup location missing bucket_path")
        bucket, prefix = parse_s3_bucket_path(bucket_path)
        name = _strip_or_none(entry.get("name")) or f"location_{idx}"
        format_tag = _strip_or_none(entry.get("format")) or "legacy"
        raw_aliases = entry.get("target_aliases") or {}
        target_aliases: dict[str, tuple[str, ...]] = {}
        if not isinstance(raw_aliases, dict):
            raise ValueError(
                "target_aliases must be an object mapping target to alias list"
            )
        for target_key, aliases in raw_aliases.items():
            if not isinstance(target_key, str):
                raise ValueError("target_aliases keys must be strings")
            if not isinstance(aliases, list):
                raise ValueError(
                    f"target_aliases[{target_key}] must be a list of alias strings"
                )
            cleaned_aliases = tuple(
                alias.strip()
                for alias in (str(item) for item in aliases)
                if alias.strip()
            )
            if cleaned_aliases:
                target_aliases[target_key] = cleaned_aliases
        locations.append(
            S3BackupLocationConfig(
                name=name,
                bucket_path=bucket_path,
                bucket=bucket,
                prefix=prefix,
                format_tag=format_tag,
                target_aliases=target_aliases,
            )
        )
    return tuple(locations)
