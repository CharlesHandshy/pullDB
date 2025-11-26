import boto3
import os

# Force the profile that the worker uses
os.environ["AWS_PROFILE"] = "pr-prod"

def list_qatemplate():
    session = boto3.Session(profile_name="pr-prod")
    s3 = session.client("s3")
    
    bucket = "pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    prefix = "daily/prod/qatemplate/"
    
    print(f"Listing {bucket}/{prefix}...")
    
    try:
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=10)
        if "Contents" in resp:
            for obj in resp["Contents"]:
                print(f" - {obj['Key']}")
            
            # Test head_object on the first key
            first_key = resp["Contents"][0]["Key"]
            print(f"Testing head_object on {first_key}...")
            head = s3.head_object(Bucket=bucket, Key=first_key)
            print(f"Size: {head['ContentLength']} bytes")
            
        else:
            print("No objects found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_qatemplate()
