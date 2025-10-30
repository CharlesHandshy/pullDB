"""Configuration dataclass with AWS Parameter Store support.

Milestone 1.3 will implement full loading from env + MySQL settings + secrets.
Supports AWS Systems Manager Parameter Store for secure credential storage.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re


@dataclass(slots=True)
class Config:
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
            value: Either a direct value or AWS SSM parameter path (e.g., '/pulldb/prod/mysql/password')
            aws_profile: AWS profile to use for parameter store access
            
        Returns:
            Resolved value from Parameter Store or original value if not a parameter reference
        """
        if not value or not value.startswith('/'):
            return value
            
        # Value is a parameter path - fetch from AWS SSM
        try:
            import boto3
            
            # Set profile if provided
            if aws_profile:
                os.environ['AWS_PROFILE'] = aws_profile
                
            ssm = boto3.client('ssm')
            response = ssm.get_parameter(Name=value, WithDecryption=True)
            return response['Parameter']['Value']
        except Exception as e:
            raise ValueError(
                f"Failed to resolve AWS Parameter Store reference '{value}': {e}\n"
                f"Ensure the parameter exists and your AWS profile has ssm:GetParameter permissions."
            )

    @classmethod
    def minimal_from_env(cls) -> "Config":
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

