import boto3
import sys
import os

def find_backup():
    session = boto3.Session(profile_name='pr-prod')
    s3 = session.client('s3')
    bucket = 'pestroutes-rds-backup-prod-vpc-us-east-1-s3'
    prefix = 'daily/prod/'
    
    min_size = 1 * 1024 * 1024 * 1024 # 1 GB
    max_size = 1.5 * 1024 * 1024 * 1024 # 1.5 GB
    
    print(f"Searching for backups between {min_size/1024/1024/1024:.2f} GB and {max_size/1024/1024/1024:.2f} GB in s3://{bucket}/{prefix}")
    
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
    
    found_count = 0
    
    for page in pages:
        if 'Contents' not in page:
            continue
            
        for obj in page['Contents']:
            key = obj['Key']
            size = obj['Size']
            
            if key.endswith('.tar') and min_size <= size <= max_size:
                print(f"Found: {key} - {size/1024/1024/1024:.2f} GB")
                found_count += 1
                if found_count >= 5: # Just find a few
                    return

    if found_count == 0:
        print("No matching backups found.")

if __name__ == "__main__":
    find_backup()
