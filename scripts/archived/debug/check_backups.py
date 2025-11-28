import sys
import logging
import os
from pulldb.domain.config import Config
from pulldb.infra.s3 import S3Client, discover_latest_backup, parse_s3_bucket_path
from pulldb.infra.mysql import build_default_pool
from pulldb.infra.secrets import CredentialResolver

logging.basicConfig(level=logging.INFO)


def main():
    # Bootstrap config to get credentials for pool
    base_config = Config.minimal_from_env()

    # Resolve coordination secret if needed
    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if (
        coordination_secret
        and base_config.mysql_user == "root"
        and not base_config.mysql_password
    ):
        try:
            resolver = CredentialResolver(base_config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            base_config.mysql_host = creds.host
            base_config.mysql_user = creds.username
            base_config.mysql_password = creds.password
        except Exception as e:
            print(f"Failed to resolve coordination secret: {e}")
            # Proceeding might fail if defaults are wrong, but let's try
            pass

    try:
        pool = build_default_pool(
            host=base_config.mysql_host,
            user=base_config.mysql_user,
            password=base_config.mysql_password,
            database=base_config.mysql_database,
        )
        config = Config.from_env_and_mysql(pool)
    except Exception as e:
        print(f"Failed to load config from MySQL: {e}")
        # Fallback to minimal if DB fails, but likely won't have S3 path
        config = base_config

    if not config.s3_bucket_path:
        print("s3_bucket_path not found in config or DB settings.")
        sys.exit(1)

    bucket, prefix = parse_s3_bucket_path(config.s3_bucket_path)
    print(f"Checking bucket: {bucket}, prefix: {prefix}")

    s3 = S3Client(profile=config.s3_aws_profile)

    target = "appalachian"
    try:
        backup = discover_latest_backup(
            s3, bucket, prefix, target, profile=config.s3_aws_profile
        )
        print(f"Found backup: {backup.key}")
        print(f"Size: {backup.size_bytes}")
        print(f"Timestamp: {backup.timestamp}")
    except Exception as e:
        print(f"Failed to find backup for {target}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
