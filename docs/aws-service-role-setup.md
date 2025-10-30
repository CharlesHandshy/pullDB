# AWS Service Role Setup for pullDB (Cross-Account S3 Access)

## Overview

This guide shows how to configure **service-based authentication** for pullDB using IAM roles instead of IAM users. This is the **recommended approach** for production deployments where pullDB runs as a service (EC2, ECS, Lambda, etc.) and needs cross-account S3 access.

**Key Difference from User-Based Auth:**
- ❌ No access keys or credentials in files
- ✅ Service assumes IAM role automatically via instance metadata
- ✅ AWS SDK handles credential refresh automatically
- ✅ More secure - credentials never leave AWS infrastructure

## Architecture

```
┌─────────────────────────────────────┐
│   Production AWS Account            │
│   (448509429610)                    │
│                                     │
│   ┌──────────────────────────────┐ │
│   │ IAM Role                     │ │
│   │ pulldb-cross-account-role    │ │
│   │                              │ │
│   │ Trust Policy:                │ │
│   │ • Allows dev/staging accts   │ │
│   │ • Requires ExternalId        │ │
│   │                              │ │
│   │ Permissions:                 │ │
│   │ • S3 Read (daily/prod/*)     │ │
│   │ • SSM GetParameter           │ │
│   │ • KMS Decrypt                │ │
│   └──────────────────────────────┘ │
│                                     │
│   ┌──────────────────────────────┐ │
│   │ S3 Bucket + KMS Encryption   │ │
│   │ pestroutes-rds-backup-prod   │ │
│   └──────────────────────────────┘ │
└─────────────────────────────────────┘
           ↑ AssumeRole
           │
┌──────────┴──────────────────────────┐
│   Dev/Staging AWS Account           │
│   (345321506926 / 333204494849)     │
│                                     │
│   ┌──────────────────────────────┐ │
│   │ IAM Role (Service Role)      │ │
│   │ pulldb-service-role          │ │
│   │                              │ │
│   │ Trust Policy:                │ │
│   │ • ec2.amazonaws.com          │ │
│   │ • ecs-tasks.amazonaws.com    │ │
│   │ • lambda.amazonaws.com       │ │
│   │                              │ │
│   │ Permissions:                 │ │
│   │ • sts:AssumeRole on          │ │
│   │   prod cross-account role    │ │
│   └──────────────────────────────┘ │
│              ↓                      │
│   ┌──────────────────────────────┐ │
│   │ EC2 Instance Profile         │ │
│   │ OR ECS Task Role             │ │
│   │ OR Lambda Execution Role     │ │
│   │                              │ │
│   │ Attached to:                 │ │
│   │ • EC2 instance running       │ │
│   │   pullDB daemon              │ │
│   └──────────────────────────────┘ │
│              ↓                      │
│   ┌──────────────────────────────┐ │
│   │ pullDB Application           │ │
│   │ • No credentials in .env     │ │
│   │ • Uses AWS SDK default chain │ │
│   │ • Auto-assumes prod role     │ │
│   └──────────────────────────────┘ │
└─────────────────────────────────────┘
```

## Prerequisites

| Item | Description | Example |
|------|-------------|---------|
| **Prod Account ID** | Production AWS account | `111111111111` |
| **Dev Account ID** | Development AWS account | `222222222222` |
| **S3 Bucket Name** | Production backup bucket | `pestroutes-rds-backup-prod-vpc-us-east-1-s3` |
| **Service Type** | Where pullDB runs | `EC2`, `ECS`, or `Lambda` |

---

## Part 1: Production Account Setup (Cross-Account Role)

**This is the same as the IAM user setup** - create the cross-account role in the production account.

### Step 1.1: Create Cross-Account Role with Trust Policy

**Create trust policy** `prod-cross-account-trust-policy.json`:

```json
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowDevStagingAccountsAssumeRole",
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::345321506926:root",
          "arn:aws:iam::333204494849:root"
        ]
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-dev-to-prod-20250101"
        }
      }
    }
  ]
}
```
```

**Note:** This trusts the **entire dev account**, which allows any role in the dev account (with the right permissions) to assume this role.

**Create the role:**

```bash
export AWS_PROFILE=prod-admin

aws iam create-role \
    --role-name pulldb-cross-account-read-role \
    --assume-role-policy-document file://prod-cross-account-trust-policy.json \
    --description "Allows dev account services to read production S3 backups" \
    --tags Key=Purpose,Value=CrossAccountAccess Key=Service,Value=pullDB

# Save the ARN
PROD_ROLE_ARN=$(aws iam get-role --role-name pulldb-cross-account-read-role --query 'Role.Arn' --output text)
echo "Production Role ARN: $PROD_ROLE_ARN"
```

### Step 1.2: Attach Permission Policy

**Create permission policy** `prod-cross-account-permissions.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3BucketReadAccess",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    },
    {
      "Sid": "S3ObjectReadAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/*"
    },
    {
      "Sid": "ExplicitDenyWrite",
      "Effect": "Deny",
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:DeleteObjectVersion",
        "s3:PutBucketPolicy",
        "s3:DeleteBucket"
      ],
      "Resource": [
        "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3",
        "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/*"
      ]
    },
    {
      "Sid": "ParameterStoreReadAccess",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": "arn:aws:ssm:us-east-1:111111111111:parameter/pulldb/prod/mysql/*"
    },
    {
      "Sid": "KMSDecryptForSSM",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": [
            "ssm.us-east-1.amazonaws.com",
            "s3.us-east-1.amazonaws.com"
          ]
        }
      }
    }
  ]
}
```

**Create and attach policy:**

```bash
export AWS_PROFILE=prod-admin

aws iam create-policy \
    --policy-name pulldb-cross-account-read-policy \
    --policy-document file://prod-cross-account-permissions.json \
    --description "Read-only S3 and SSM access for pullDB service"

POLICY_ARN=$(aws iam list-policies \
    --query 'Policies[?PolicyName==`pulldb-cross-account-read-policy`].Arn' \
    --output text)

aws iam attach-role-policy \
    --role-name pulldb-cross-account-read-role \
    --policy-arn "$POLICY_ARN"
```

### Step 1.3: Update S3 Bucket Policy (if needed)

Follow the same steps as in `aws-cross-account-setup.md` Step 1.3 to update the S3 bucket policy.

### Step 1.4: Update KMS Key Policy (if bucket encrypted)

Follow the same steps as in `aws-cross-account-setup.md` Step 1.4 to update the KMS key policy.

---

## Part 2: Development Account Setup (Service Role)

Now create a service role in the dev account that can assume the production role.

### Option A: EC2 Instance Role

**Best for:** pullDB running directly on EC2 instances

#### Step 2A.1: Create EC2 Service Role

**Create trust policy** `ec2-trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Create the role:**

```bash
export AWS_PROFILE=dev-admin

aws iam create-role \
    --role-name pulldb-ec2-service-role \
    --assume-role-policy-document file://ec2-trust-policy.json \
    --description "EC2 service role for pullDB with cross-account S3 access" \
    --tags Key=Service,Value=pullDB Key=Environment,Value=development
```

#### Step 2A.2: Create Assume Role Permission Policy

**Create policy** `dev-assume-prod-role-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAssumeProductionRole",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::111111111111:role/pulldb-cross-account-read-role",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-service-2025"
        }
      }
    }
  ]
}
```

**Create and attach policy:**

```bash
export AWS_PROFILE=dev-admin

aws iam create-policy \
    --policy-name pulldb-assume-prod-role-policy \
    --policy-document file://dev-assume-prod-role-policy.json \
    --description "Allows pullDB service to assume production cross-account role"

ASSUME_POLICY_ARN=$(aws iam list-policies \
    --query 'Policies[?PolicyName==`pulldb-assume-prod-role-policy`].Arn' \
    --output text)

aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn "$ASSUME_POLICY_ARN"
```

#### Step 2A.3: Create Instance Profile

```bash
export AWS_PROFILE=dev-admin

# Create instance profile
aws iam create-instance-profile \
    --instance-profile-name pulldb-ec2-instance-profile

# Add role to instance profile
aws iam add-role-to-instance-profile \
    --instance-profile-name pulldb-ec2-instance-profile \
    --role-name pulldb-ec2-service-role
```

#### Step 2A.4: Attach to EC2 Instance

```bash
export AWS_PROFILE=dev-admin

# Attach to existing instance
aws ec2 associate-iam-instance-profile \
    --instance-id i-1234567890abcdef0 \
    --iam-instance-profile Name=pulldb-ec2-instance-profile

# Or specify when launching new instance
aws ec2 run-instances \
    --image-id ami-12345678 \
    --instance-type t3.medium \
    --iam-instance-profile Name=pulldb-ec2-instance-profile \
    --key-name my-key \
    --subnet-id subnet-12345678 \
    --security-group-ids sg-12345678
```

---

### Option B: ECS Task Role

**Best for:** pullDB running as ECS container

#### Step 2B.1: Create ECS Task Role

**Create trust policy** `ecs-trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Create the role:**

```bash
export AWS_PROFILE=dev-admin

aws iam create-role \
    --role-name pulldb-ecs-task-role \
    --assume-role-policy-document file://ecs-trust-policy.json \
    --description "ECS task role for pullDB with cross-account S3 access" \
    --tags Key=Service,Value=pullDB Key=Environment,Value=development
```

#### Step 2B.2: Attach Assume Role Policy

```bash
export AWS_PROFILE=dev-admin

# Use the same assume role policy created earlier
aws iam attach-role-policy \
    --role-name pulldb-ecs-task-role \
    --policy-arn "$ASSUME_POLICY_ARN"
```

#### Step 2B.3: Update ECS Task Definition

Add the task role to your ECS task definition:

```json
{
  "family": "pulldb-task",
  "taskRoleArn": "arn:aws:iam::222222222222:role/pulldb-ecs-task-role",
  "executionRoleArn": "arn:aws:iam::222222222222:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "pulldb",
      "image": "pulldb:latest",
      "memory": 2048,
      "cpu": 1024,
      "essential": true,
      "environment": [
        {
          "name": "PULLDB_AWS_PROFILE",
          "value": "default"
        }
      ]
    }
  ]
}
```

---

### Option C: Lambda Execution Role

**Best for:** pullDB triggered as Lambda function

#### Step 2C.1: Create Lambda Execution Role

**Create trust policy** `lambda-trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Create the role:**

```bash
export AWS_PROFILE=dev-admin

aws iam create-role \
    --role-name pulldb-lambda-execution-role \
    --assume-role-policy-document file://lambda-trust-policy.json \
    --description "Lambda execution role for pullDB with cross-account S3 access"

# Attach AWS managed policy for Lambda basic execution
aws iam attach-role-policy \
    --role-name pulldb-lambda-execution-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Attach cross-account assume role policy
aws iam attach-role-policy \
    --role-name pulldb-lambda-execution-role \
    --policy-arn "$ASSUME_POLICY_ARN"
```

---

## Part 3: Configure AWS Profile for Role Assumption

On the EC2 instance (or ECS container), configure AWS to automatically assume the production role.

### Step 3.1: Create AWS Config File

**On the EC2 instance**, create `~/.aws/config`:

```bash
mkdir -p ~/.aws
cat > ~/.aws/config << 'EOF'
[default]
region = us-east-1
output = json

[profile prod-cross-account]
region = us-east-1
output = json
role_arn = arn:aws:iam::111111111111:role/pulldb-cross-account-read-role
credential_source = Ec2InstanceMetadata
external_id = pulldb-service-2025
EOF
```

**Key Setting:** `credential_source = Ec2InstanceMetadata`
- This tells AWS SDK to get base credentials from EC2 instance metadata
- No access keys needed in files!

**For ECS:** Use `credential_source = EcsContainer` instead

**For Lambda:** Lambda automatically uses its execution role, no config file needed

### Step 3.2: Update pullDB .env File

Edit `/path/to/pullDB/.env`:

```bash
# ============================================
# AWS Configuration - Service Role Setup
# ============================================
# Use the cross-account profile that assumes production role
PULLDB_AWS_PROFILE=prod-cross-account

# MySQL connection
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_USER=root
PULLDB_MYSQL_PASSWORD=your_password
PULLDB_MYSQL_DATABASE=pulldb

# S3 bucket path (production bucket via cross-account role)
PULLDB_S3_BUCKET_PATH=pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod

# Default database host
PULLDB_DEFAULT_DBHOST=db-mysql-db4-dev

# Working directory
PULLDB_WORK_DIR=/mnt/data/pulldb/work
```

---

## Part 4: Test Service Role Access

### Step 4.1: Verify Instance Role

From the EC2 instance:

```bash
# Check instance metadata for role
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Should return: pulldb-ec2-service-role

# Get temporary credentials
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/pulldb-ec2-service-role
```

### Step 4.2: Test Base Role Identity

```bash
# Test using instance role (default)
aws sts get-caller-identity

# Should show:
# {
#   "UserId": "AROAI...:i-1234567890abcdef0",
#   "Account": "222222222222",  # Dev account
#   "Arn": "arn:aws:sts::222222222222:assumed-role/pulldb-ec2-service-role/i-1234567890abcdef0"
# }
```

### Step 4.3: Test Cross-Account Role Assumption

```bash
# Test using cross-account profile
AWS_PROFILE=prod-cross-account aws sts get-caller-identity

# Should show:
# {
#   "UserId": "AROAI...:botocore-session-...",
#   "Account": "111111111111",  # Production account!
#   "Arn": "arn:aws:sts::111111111111:assumed-role/pulldb-cross-account-read-role/botocore-session-..."
# }
```

### Step 4.4: Test S3 Access

```bash
# List production S3 bucket via cross-account role
AWS_PROFILE=prod-cross-account aws s3 ls \
    s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/ \
    --max-items 5

# Should list backup files
```

### Step 4.5: Test from Python

```bash
python3 << 'EOF'
import os
from pulldb.domain.config import Config

# Load config
cfg = Config.minimal_from_env()
print(f"AWS Profile: {cfg.aws_profile}")

# Set profile for boto3
if cfg.aws_profile:
    os.environ['AWS_PROFILE'] = cfg.aws_profile

import boto3

# Test identity
sts = boto3.client('sts')
identity = sts.get_caller_identity()
print(f"\nIdentity ARN: {identity['Arn']}")
print(f"Account: {identity['Account']}")

# Test S3 access
s3 = boto3.client('s3')
bucket_name = cfg.s3_bucket_path.split('/')[0]

print(f"\nListing bucket: {bucket_name}")
response = s3.list_objects_v2(Bucket=bucket_name, Prefix='daily/prod/', MaxKeys=5)

if 'Contents' in response:
    print(f"✓ Listed {len(response['Contents'])} objects")
    for obj in response['Contents'][:3]:
        print(f"  - {obj['Key']}")
else:
    print("✓ Bucket accessible (empty)")
EOF
```

**Expected output:**
```
AWS Profile: prod-cross-account

Identity ARN: arn:aws:sts::111111111111:assumed-role/pulldb-cross-account-read-role/...
Account: 111111111111

Listing bucket: pestroutes-rds-backup-prod-vpc-us-east-1-s3
✓ Listed 5 objects
  - daily/prod/customer123/daily_mydumper_customer123_2025-10-30T00-00-00Z_Wed_dbimp.tar
  - daily/prod/customer456/daily_mydumper_customer456_2025-10-30T00-00-00Z_Wed_dbimp.tar
  - daily/prod/qatemplate/daily_mydumper_qatemplate_2025-10-30T00-00-00Z_Wed_dbimp.tar
```

---

## Security Benefits of Service Roles

✅ **No Credentials in Files**
- Access keys never written to disk
- Cannot be accidentally committed to git
- Cannot be exposed in logs or environment dumps

✅ **Automatic Rotation**
- AWS rotates temporary credentials automatically
- No manual key rotation needed
- Credentials expire quickly (default 1 hour)

✅ **Least Privilege**
- Service role only has permission to assume production role
- Production role has minimal read-only permissions
- External ID prevents unauthorized role assumption

✅ **Audit Trail**
- All role assumptions logged in CloudTrail
- Can track which service instance accessed what
- Easy to revoke access by detaching instance profile

✅ **Defense in Depth**
- Network security (Security Groups)
- IAM permissions (role policies)
- Resource policies (S3 bucket policy)
- Encryption (KMS keys)
- External ID (confused deputy protection)

---

## Troubleshooting

### Issue: "Unable to locate credentials"

**Cause:** Instance profile not attached or AWS config incorrect

**Solution:**

```bash
# Check instance profile
aws ec2 describe-instances \
    --instance-ids i-1234567890abcdef0 \
    --query 'Reservations[0].Instances[0].IamInstanceProfile'

# Check instance metadata
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Verify config file
cat ~/.aws/config
```

### Issue: "AccessDenied" when assuming cross-account role

**Cause:** Service role lacks sts:AssumeRole permission

**Solution:**

```bash
# Check attached policies on service role
AWS_PROFILE=dev-admin aws iam list-attached-role-policies \
    --role-name pulldb-ec2-service-role

# Verify policy content
AWS_PROFILE=dev-admin aws iam get-policy-version \
    --policy-arn "$ASSUME_POLICY_ARN" \
    --version-id v1
```

### Issue: "Invalid credential_source"

**Cause:** Wrong credential_source for service type

**Solution:**

Update `~/.aws/config`:

```ini
# For EC2
credential_source = Ec2InstanceMetadata

# For ECS
credential_source = EcsContainer

# For Lambda - don't use credential_source, use role directly
```

---

## Comparison: Service Role vs IAM User

| Aspect | Service Role | IAM User |
|--------|--------------|----------|
| **Credentials** | None (metadata) | Access keys in files |
| **Rotation** | Automatic (hourly) | Manual (quarterly) |
| **Security Risk** | Low | Medium |
| **Setup Complexity** | Medium | Low |
| **Use Case** | Production services | Local development |
| **Best Practice** | ✅ Recommended | ⚠️ Dev only |

---

## Production Checklist

- [ ] Production account cross-account role created
- [ ] S3 bucket policy updated (if needed)
- [ ] KMS key policy updated (if encrypted)
- [ ] Service role created in dev account (EC2/ECS/Lambda)
- [ ] Assume role policy attached to service role
- [ ] Instance profile created and attached (EC2 only)
- [ ] AWS config file created with `credential_source`
- [ ] `.env` file updated with profile name
- [ ] Test: `aws sts get-caller-identity` shows correct role
- [ ] Test: S3 list works with cross-account profile
- [ ] Test: Python pullDB can load config and access S3
- [ ] CloudTrail logging enabled in production account
- [ ] CloudWatch alarms configured for unauthorized access

---

## Summary

You've configured **service-based cross-account access** for pullDB:

✅ **Production Account:**
- Cross-account IAM role trusting dev account
- S3 and Parameter Store read permissions
- KMS decryption permissions

✅ **Development Account:**
- Service role (EC2/ECS/Lambda) with assume role permissions
- Instance profile attached to service
- No credentials in files

✅ **Security:**
- Automatic credential rotation
- External ID for confused deputy protection
- Explicit deny on write operations
- Complete audit trail via CloudTrail

## Next Steps

1. Deploy pullDB to the service (EC2/ECS/Lambda)
2. Test full restore workflow
3. Configure CloudWatch monitoring
4. Set up alerting for access anomalies
5. Document External ID in secure location

## Related Documentation

- [AWS Cross-Account Access with IAM Users](aws-cross-account-setup.md) - For local development
- [AWS IAM Setup](aws-iam-setup.md) - IAM concepts and policies
- [AWS Setup Guide](aws-setup.md) - AWS CLI and SDK basics
- [Parameter Store Setup](parameter-store-setup.md) - Secure credential storage
