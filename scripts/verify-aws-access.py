#!/usr/bin/env python3
"""Verify AWS cross-account S3 access for pullDB services.

This script tests:
1. EC2 instance profile credentials
2. Cross-account role assumption
3. S3 bucket access (list, head, get)
4. KMS decryption (if bucket is encrypted)
"""

import sys
from typing import Dict, Any

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:
    print("❌ boto3 not installed. Run: pip install boto3")
    sys.exit(1)


def test_instance_profile() -> bool:
    """Test if EC2 instance profile is working."""
    print("\n1. Testing EC2 Instance Profile...")
    try:
        session = boto3.Session()
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        print(f"   ✅ Instance profile working")
        print(f"   Account: {identity['Account']}")
        print(f"   ARN: {identity['Arn']}")
        return True
    except NoCredentialsError:
        print("   ❌ No credentials found - instance profile not attached")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def test_cross_account_role(profile_name: str, expected_account: str) -> bool:
    """Test cross-account role assumption."""
    print(f"\n2. Testing Cross-Account Access (profile: {profile_name})...")
    try:
        session = boto3.Session(profile_name=profile_name)
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        
        if identity['Account'] != expected_account:
            print(f"   ❌ Wrong account: {identity['Account']} (expected {expected_account})")
            return False
        
        print(f"   ✅ Cross-account role assumption working")
        print(f"   Account: {identity['Account']}")
        print(f"   ARN: {identity['Arn']}")
        return True
    except ClientError as e:
        print(f"   ❌ Access denied: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def test_s3_access(profile_name: str, bucket: str, prefix: str) -> Dict[str, Any]:
    """Test S3 bucket access."""
    print(f"\n3. Testing S3 Access ({bucket}/{prefix})...")
    results = {
        'list': False,
        'head': False,
        'get': False,
        'backup_count': 0,
        'test_key': None
    }
    
    try:
        session = boto3.Session(profile_name=profile_name)
        s3 = session.client('s3')
        
        # Test ListBucket
        try:
            response = s3.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=10
            )
            contents = response.get('Contents', [])
            results['backup_count'] = len(contents)
            results['list'] = True
            print(f"   ✅ ListBucket: Found {len(contents)} objects")
            
            if contents:
                results['test_key'] = contents[0]['Key']
                print(f"   Test object: {results['test_key']}")
        except ClientError as e:
            print(f"   ❌ ListBucket failed: {e.response['Error']['Code']}")
            return results
        
        # Test HeadObject
        if results['test_key']:
            try:
                metadata = s3.head_object(
                    Bucket=bucket,
                    Key=results['test_key']
                )
                results['head'] = True
                size_mb = metadata['ContentLength'] / (1024 * 1024)
                print(f"   ✅ HeadObject: {size_mb:.2f} MB")
                
                # Check encryption
                if 'ServerSideEncryption' in metadata:
                    print(f"   Encryption: {metadata['ServerSideEncryption']}")
            except ClientError as e:
                print(f"   ❌ HeadObject failed: {e.response['Error']['Code']}")
        
        # Test GetObject (just first 1KB to verify access)
        if results['test_key']:
            try:
                response = s3.get_object(
                    Bucket=bucket,
                    Key=results['test_key'],
                    Range='bytes=0-1023'
                )
                data = response['Body'].read()
                results['get'] = True
                print(f"   ✅ GetObject: Verified (read {len(data)} bytes)")
            except ClientError as e:
                print(f"   ❌ GetObject failed: {e.response['Error']['Code']}")
        
        return results
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return results


def test_write_denied(profile_name: str, bucket: str) -> bool:
    """Test that write operations are denied."""
    print(f"\n4. Testing Write Operations (should be denied)...")
    try:
        session = boto3.Session(profile_name=profile_name)
        s3 = session.client('s3')
        
        # Try to put an object
        try:
            s3.put_object(
                Bucket=bucket,
                Key='test-write-access.txt',
                Body=b'test'
            )
            print("   ❌ WARNING: Write access allowed (should be denied!)")
            
            # Clean up if write succeeded
            try:
                s3.delete_object(Bucket=bucket, Key='test-write-access.txt')
            except:
                pass
            return False
        except ClientError as e:
            if e.response['Error']['Code'] in ['AccessDenied', '403']:
                print("   ✅ Write operations properly denied")
                return True
            else:
                print(f"   ⚠️  Unexpected error: {e.response['Error']['Code']}")
                return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def main():
    """Run all verification tests."""
    print("=" * 70)
    print("pullDB AWS Access Verification")
    print("=" * 70)
    
    # Test 1: Instance profile
    if not test_instance_profile():
        print("\n❌ FAILED: Instance profile not working. Cannot continue.")
        sys.exit(1)
    
    # Test 2: Staging account
    staging_ok = test_cross_account_role('pr-staging', '333204494849')
    
    # Test 3: Staging S3 access
    if staging_ok:
        s3_results = test_s3_access(
            'pr-staging',
            'pestroutesrdsdbs',
            'daily/stg/'
        )
        
        # Test 4: Write denied
        write_denied = test_write_denied('pr-staging', 'pestroutesrdsdbs')
    else:
        print("\n⚠️  Skipping S3 tests (cross-account role not working)")
        s3_results = {'list': False, 'head': False, 'get': False}
        write_denied = False
    
    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Instance Profile:        {'✅ Working' if True else '❌ Failed'}")
    print(f"Cross-Account Role:      {'✅ Working' if staging_ok else '❌ Failed'}")
    print(f"S3 ListBucket:           {'✅ Working' if s3_results['list'] else '❌ Failed'}")
    print(f"S3 HeadObject:           {'✅ Working' if s3_results['head'] else '❌ Failed'}")
    print(f"S3 GetObject:            {'✅ Working' if s3_results['get'] else '❌ Failed'}")
    print(f"Write Operations Denied: {'✅ Working' if write_denied else '❌ Failed'}")
    print(f"Backups Found:           {s3_results.get('backup_count', 0)}")
    
    # Overall status
    all_good = (
        staging_ok and
        s3_results['list'] and
        s3_results['head'] and
        s3_results['get'] and
        write_denied
    )
    
    print("\n" + "=" * 70)
    if all_good:
        print("✅ ALL TESTS PASSED - AWS access properly configured")
        print("=" * 70)
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED - Review errors above")
        print("=" * 70)
        sys.exit(1)


if __name__ == '__main__':
    main()
