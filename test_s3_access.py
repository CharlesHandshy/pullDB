import boto3
import os
import sys

profile = os.environ.get("PULLDB_S3_AWS_PROFILE", "pr-prod")
print(f"Using profile: {profile}")

try:
    session = boto3.Session(profile_name=profile)
    s3 = session.client("s3")
    bucket = "pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    prefix = "daily/prod/"
    print(f"Listing {bucket}/{prefix}...")
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=5)
    print("Success!")
    for obj in resp.get("Contents", []):
        print(obj["Key"])
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
