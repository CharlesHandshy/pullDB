import os
import sys
import boto3
from pulldb.domain.config import Config
from pulldb.infra.mysql import MySQLPool, SettingsRepository
from pulldb.infra.secrets import CredentialResolver


def main():
    print("--- Environment Variables ---")
    print(f"PULLDB_AWS_PROFILE: {os.getenv('PULLDB_AWS_PROFILE')}")
    print(f"PULLDB_S3_AWS_PROFILE: {os.getenv('PULLDB_S3_AWS_PROFILE')}")
    print(f"PULLDB_S3_BUCKET_PATH: {os.getenv('PULLDB_S3_BUCKET_PATH')}")
    print(f"PULLDB_S3_BACKUP_LOCATIONS: {os.getenv('PULLDB_S3_BACKUP_LOCATIONS')}")
    print(f"AWS_PROFILE: {os.getenv('AWS_PROFILE')}")

    print("\n--- MySQL Settings ---")
    try:
        resolver = CredentialResolver()
        creds = resolver.resolve("aws-secretsmanager:/pulldb/mysql/coordination-db")
        pool = MySQLPool(
            host=creds.host,
            user=creds.username,
            password=creds.password,
            database="pulldb",
        )
        repo = SettingsRepository(pool)
        settings = repo.get_all_settings()
        for k, v in settings.items():
            print(f"{k}: {v}")

        print("\n--- Effective Config ---")
        config = Config.from_env_and_mysql(pool)
        print(f"s3_bucket_path: {config.s3_bucket_path}")
        print(f"aws_profile: {config.aws_profile}")
        print(f"s3_aws_profile: {config.s3_aws_profile}")
        print(f"s3_backup_locations: {config.s3_backup_locations}")

        print("\n--- S3 Access Test ---")

        locations = config.s3_backup_locations
        if not locations and config.s3_bucket_path:
            # Fallback logic from Config._load_s3_backup_locations
            from pulldb.infra.s3 import parse_s3_bucket_path

            bucket, prefix = parse_s3_bucket_path(config.s3_bucket_path)
            from pulldb.domain.config import S3BackupLocationConfig

            locations = (
                S3BackupLocationConfig(
                    name="default",
                    bucket_path=config.s3_bucket_path,
                    bucket=bucket,
                    prefix=prefix,
                    format_tag="legacy",
                ),
            )

        for loc in locations:
            print(
                f"Testing location: {loc.name} (Bucket: {loc.bucket}, Prefix: {loc.prefix})"
            )
            profile = loc.profile or config.s3_aws_profile or config.aws_profile
            print(f"Using profile: {profile}")

            try:
                session = boto3.Session(profile_name=profile)
                s3 = session.client("s3")
                response = s3.list_objects_v2(
                    Bucket=loc.bucket, Prefix=loc.prefix, MaxKeys=5
                )
                if "Contents" in response:
                    print(f"Successfully listed {len(response['Contents'])} objects.")
                    for obj in response["Contents"]:
                        print(f" - {obj['Key']}")
                else:
                    print("Successfully listed, but no objects found.")
            except Exception as e:
                print(f"FAILED: {e}")

    except Exception as e:
        print(f"Error during config/mysql check: {e}")


if __name__ == "__main__":
    main()
