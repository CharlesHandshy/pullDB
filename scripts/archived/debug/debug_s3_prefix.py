import boto3
import sys
import time

bucket = "pestroutes-rds-backup-prod-vpc-us-east-1-s3"
prefix = "daily/prod/"
target = "qatemplate"
search_prefix = f"{prefix}daily_mydumper_{target}_"

print(f"Searching bucket: {bucket}")
print(f"Prefix: {search_prefix}")

try:
    s3 = boto3.client("s3", region_name="us-east-1")
    start = time.time()
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=search_prefix, MaxKeys=10)
    duration = time.time() - start

    print(f"Call took {duration:.4f} seconds")

    if "Contents" in resp:
        print(f"Found {len(resp['Contents'])} objects")
        for obj in resp["Contents"]:
            print(f" - {obj['Key']}")
    else:
        print("No objects found")

except Exception as e:
    print(f"Error: {e}")
