import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append("/home/charleshandshy/Projects/pullDB")

from pulldb.infra.s3 import S3Client, discover_latest_backup
from pulldb.infra.logging import get_logger

# Set env vars as in systemd
os.environ["PULLDB_S3_AWS_PROFILE"] = "pr-prod"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
# os.environ["AWS_PROFILE"] = "pr-prod" # This is NOT set in systemd, but PULLDB_S3_AWS_PROFILE is.

# Initialize S3Client
print("Initializing S3Client...")
try:
    s3 = S3Client(profile="pr-prod")
    print("S3Client initialized.")

    bucket = "pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    prefix = "daily/prod/"
    target = "qatemplate"

    print(f"Calling discover_latest_backup for {bucket}/{prefix}{target}...")
    spec = discover_latest_backup(s3, bucket, prefix, target)
    print(f"Success! Found: {spec.key}")

except Exception as e:
    print(f"Failed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

sys.exit(0)
