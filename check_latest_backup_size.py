import boto3
import re
from datetime import datetime
import sys

def check_latest(customer):
    try:
        s3 = boto3.Session(profile_name='pr-staging').client('s3')
    except Exception:
        # Fallback if profile not found or other issue, though previous command worked with env var
        s3 = boto3.client('s3')

    bucket = 'pestroutesrdsdbs'
    prefix = f'daily/stg/{customer}/'
    
    print(f"Checking latest backup for '{customer}' in s3://{bucket}/{prefix}...")
    
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
    
    # Regex from pulldb/infra/s3.py
    regex = re.compile(r"^daily_mydumper_(?P<target>.+?)_(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_[A-Za-z]+_(?:dbimp|db\d+)\.tar$")
    
    candidates = []
    
    for page in pages:
        if 'Contents' not in page:
            continue
        for obj in page['Contents']:
            key = obj['Key']
            filename = key.rsplit("/", 1)[-1]
            match = regex.match(filename)
            if match:
                ts_str = match.group("ts")
                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%SZ")
                candidates.append((ts, obj))
                
    if not candidates:
        print(f"No backups found for {customer}")
        return False

    candidates.sort(key=lambda x: x[0], reverse=True)
    latest_ts, latest_obj = candidates[0]
    
    size_gb = latest_obj['Size'] / (1024**3)
    print(f"Latest backup: {latest_obj['Key']}")
    print(f"Timestamp: {latest_ts}")
    print(f"Size: {size_gb:.2f} GB")
    
    if 1.0 <= size_gb <= 1.5:
        print("SIZE OK")
        return True
    else:
        print("SIZE MISMATCH")
        return False

if __name__ == "__main__":
    customer = sys.argv[1] if len(sys.argv) > 1 else 'appalachian'
    if check_latest(customer):
        sys.exit(0)
    else:
        sys.exit(1)
