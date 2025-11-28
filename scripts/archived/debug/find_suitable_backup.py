import boto3
import sys
from botocore.exceptions import ClientError


def find_suitable_backup(bucket, target_date, min_size_gb, max_size_gb):
    session = boto3.Session(profile_name="pr-prod")
    s3 = session.client("s3")

    min_size_bytes = min_size_gb * 1024 * 1024 * 1024
    max_size_bytes = max_size_gb * 1024 * 1024 * 1024

    print(f"Listing tenants in s3://{bucket}/daily/prod/...")

    try:
        # List tenants (common prefixes)
        paginator = s3.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(
            Bucket=bucket, Prefix="daily/prod/", Delimiter="/"
        )

        for page in page_iterator:
            if "CommonPrefixes" not in page:
                continue

            for prefix_info in page["CommonPrefixes"]:
                tenant_prefix = prefix_info["Prefix"]
                tenant_name = tenant_prefix.split("/")[-2]

                # Construct specific prefix for today's backup
                # Format: daily/prod/{tenant}/daily_mydumper_{tenant}_{date}
                # Example: daily/prod/aptivepest/daily_mydumper_aptivepest_2025-11-25
                search_prefix = (
                    f"{tenant_prefix}daily_mydumper_{tenant_name}_{target_date}"
                )

                # Check for objects with this prefix
                response = s3.list_objects_v2(
                    Bucket=bucket,
                    Prefix=search_prefix,
                    MaxKeys=5,  # Should only be 1 or 2 usually
                )

                if "Contents" in response:
                    for obj in response["Contents"]:
                        size = obj["Size"]
                        key = obj["Key"]

                        # Check if it's a tar file (ignore metadata files if any)
                        if not key.endswith(".tar"):
                            continue

                        size_gb = size / (1024 * 1024 * 1024)

                        if min_size_bytes <= size <= max_size_bytes:
                            print(f"\nFOUND MATCH!")
                            print(f"Tenant: {tenant_name}")
                            print(f"Key: {key}")
                            print(f"Size: {size_gb:.2f} GB")
                            return key
                        elif (
                            size > 100 * 1024 * 1024
                        ):  # Print anything over 100MB to show progress
                            print(
                                f"Checked {tenant_name}: {size_gb:.2f} GB (Too {'small' if size < min_size_bytes else 'large'})"
                            )

    except ClientError as e:
        print(f"Error: {e}")
        return None


if __name__ == "__main__":
    bucket = "pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    date = "2025-11-25"
    find_suitable_backup(bucket, date, 1.0, 1.6)
