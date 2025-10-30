"""Configuration dataclass placeholder.

Milestone 1.3 will implement full loading from env + MySQL settings + secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


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

    @classmethod
    def minimal_from_env(cls) -> "Config":
        """Temporary minimal loader using environment variables only.

        This will be replaced with `from_env_and_mysql` in Milestone 1.3.
        Required vars for now (fallbacks allowed for prototype stubs).
        """
        return cls(
            mysql_host=os.getenv("PULLDB_MYSQL_HOST", "localhost"),
            mysql_user=os.getenv("PULLDB_MYSQL_USER", "root"),
            mysql_password=os.getenv("PULLDB_MYSQL_PASSWORD", ""),
            s3_bucket_path=os.getenv("PULLDB_S3_BUCKET_PATH"),
            aws_profile=os.getenv("PULLDB_AWS_PROFILE"),
            default_dbhost=os.getenv("PULLDB_DEFAULT_DBHOST"),
        )
