# AWS Authentication Setup for pullDB

> **Primary AWS Documentation**: This is the complete, consolidated guide for AWS authentication supporting the two-service architecture (API Service + Worker Service).

## Overview

pullDB consists of two services that need AWS access with different permission levels:
- **API Service**: Read-only S3 access for backup discovery (ListBucket, HeadObject)
- **Worker Service**: Full S3 read access for downloading backups (GetObject)
- **CLI**: No AWS access - calls API service via HTTP

Both services run on an **EC2 instance** in the development AWS account and use **EC2 instance profile** for authentication (no access keys, automatic credential rotation).

## Account Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Development Account (345321506926)                               │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ EC2 Instance: pulldb-dev-01                                  │ │
│ │                                                               │ │
│ │ ┌─────────────────┐  ┌─────────────────┐                    │ │
│ │ │  API Service    │  │ Worker Service  │                    │ │
│ │ │ • List S3       │  │ • Download S3   │                    │ │
│ │ │ • HeadObject    │  │ • GetObject     │                    │ │
│ │ └─────────────────┘  └─────────────────┘                    │ │
│ │         ↓                    ↓                                │ │
│ │    ┌────────────────────────────────┐                        │ │
│ │    │ EC2 Instance Profile           │                        │ │
│ │    │ pulldb-instance-profile        │                        │ │
│ │    │   Attached Role:               │                        │ │
│ │    │   pulldb-ec2-service-role      │                        │ │
│ │    └────────────────────────────────┘                        │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                         ↓ AssumeRole                              │
└─────────────────────────┼───────────────────────────────────────┘
                          ↓
┌─────────────────────────┼───────────────────────────────────────┐
│ Staging Account (333204494849)                                   │
│                         ↓                                         │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ IAM Role: pulldb-cross-account-readonly                      ││
│ │ Trust: Dev account (345321506926) + ExternalId               ││
│ │ Permissions: S3 Read (pestroutesrdsdbs/*), SSM, KMS          ││
│ └──────────────────────────────────────────────────────────────┘│
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ S3 Bucket: pestroutesrdsdbs                                  ││
│ │ Path: s3://pestroutesrdsdbs/daily/stg/                       ││
│ │ Contains: Both mydumper formats (newer + older)              ││
│ │ Bucket Policy: Allows pulldb-cross-account-readonly          ││
│ │ KMS Encryption: Key policy allows dev account                ││
│ └──────────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────┼───────────────────────────────────────┐
│ Production Account (448509429610)                                │
│                         ↓                                         │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ IAM Role: pulldb-cross-account-readonly                      ││
│ │ Trust: Dev account (345321506926) + ExternalId               ││
│ │ Permissions: S3 Read (pestroutes-rds-backup-prod/*), SSM, KMS││
│ └──────────────────────────────────────────────────────────────┘│
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ S3 Bucket: pestroutes-rds-backup-prod-vpc-us-east-1-s3      ││
│ │ Path: s3://.../daily/prod/                                   ││
│ │ Contains: Older mydumper format (migrating to newer)         ││
│ │ Bucket Policy: Allows pulldb-cross-account-readonly          ││
│ │ KMS Encryption: Key policy allows dev account                ││
│ └──────────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### EC2 Instance Profile
- Attached to EC2 instance at launch
- Contains IAM role with permissions
- AWS SDK automatically retrieves credentials from instance metadata service
- No credential files needed - credentials never leave AWS infrastructure
- Automatic rotation - SDK refreshes before expiration

### Cross-Account Role Assumption
1. EC2 instance profile grants `sts:AssumeRole` permission
2. Services call STS to assume role in staging/production accounts
3. STS validates trust policy and external ID
4. Returns temporary credentials (valid 1-12 hours)
5. Services use temporary credentials to access S3

### Permission Separation
- **API Service IAM Policy**: Allows `s3:ListBucket` and `s3:HeadObject` only (no GetObject on `*.tar` files)
- **Worker Service IAM Policy**: Allows full S3 read including `s3:GetObject` for downloads
- Both services share same instance profile but have different code paths enforcing least privilege

## Step 1: Development Account Setup

### 1.1 Create or Modify EC2 Service Role

The `pulldb-ec2-service-role` should already exist in the development account. Verify and modify it if needed.

**Current Role Configuration**:
- **Role Name**: `pulldb-ec2-service-role`
- **Role ARN**: `arn:aws:iam::345321506926:role/pulldb-ec2-service-role`
- **Description**: EC2 service role for pullDB API and Worker services
- **Tags**: `Service=pulldb`, `Environment=development`

**Trust Policy** (allows EC2 and RDS Export services):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "export.rds.amazonaws.com",
          "ec2.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Attached Policies** (existing policies to preserve):
- `pestroutes-dev-pr-vpc-us-east-1-agents-policy` - CloudWatch agent permissions
- `pestroutes-dev-pr-vpc-us-east-1-s3-policy` - S3 access for dev VPC
- `pestroutes-dev-pr-vpc-us-east-1-ssm-policy` - Systems Manager permissions
- `pestroutes-dev-pr-vpc-us-east-1-codedeploy-policy` - CodeDeploy permissions
- `AmazonRDSFullAccess` - RDS management (AWS managed)
- `AmazonSQSFullAccess` - SQS access (AWS managed)
- `pulldb-cross-account-assume-role` - Cross-account S3 access (add if missing)

**Verify Role Exists**:
```bash
# Check role configuration
aws iam get-role --role-name pulldb-ec2-service-role

# List attached policies
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

**If role doesn't exist, create it**:
```bash
# Create trust policy for EC2 and RDS Export
cat > /tmp/pulldb-ec2-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "export.rds.amazonaws.com",
          "ec2.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create the role
aws iam create-role \
    --role-name pulldb-ec2-service-role \
    --assume-role-policy-document file:///tmp/pulldb-ec2-trust-policy.json \
    --description "EC2 service role for pullDB API and Worker services" \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development
```

### 1.2 Add Cross-Account Assumption Policy

This policy allows the EC2 role to assume roles in staging and production accounts.

**Check if policy already exists**:
```bash
# Check for existing policy
aws iam get-policy --policy-arn arn:aws:iam::345321506926:policy/pulldb-cross-account-assume-role 2>/dev/null

# If policy exists, verify it's attached to role
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role | grep pulldb-cross-account-assume-role
```

**If policy doesn't exist, create it**:
```bash
cat > /tmp/pulldb-assume-role-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeRoleInStagingAccount",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::333204494849:role/pulldb-cross-account-readonly",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-dev-access-2025"
        }
      }
    },
    {
      "Sid": "AssumeRoleInProductionAccount",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::448509429610:role/pulldb-cross-account-readonly",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-dev-access-2025"
        }
      }
    }
  ]
}
EOF

# Create policy
aws iam create-policy \
    --policy-name pulldb-cross-account-assume-role \
    --policy-document file:///tmp/pulldb-assume-role-policy.json \
    --description "Allows pullDB to assume cross-account roles for S3 access"
```

**Attach policy to role** (if not already attached):
```bash
aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-cross-account-assume-role

# Verify attachment
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

### 1.3 Create Instance Profile

```bash
# Create instance profile
aws iam create-instance-profile \
    --instance-profile-name pulldb-instance-profile

# Add role to instance profile
aws iam add-role-to-instance-profile \
    --instance-profile-name pulldb-instance-profile \
    --role-name pulldb-ec2-service-role

# Verify
aws iam get-instance-profile --instance-profile-name pulldb-instance-profile
```

### 1.4 Attach Instance Profile to EC2

```bash
# If launching new instance
aws ec2 run-instances \
    --image-id ami-0c55b159cbfafe1f0 \
    --instance-type t3.medium \
    --iam-instance-profile Name=pulldb-instance-profile \
    --key-name your-key-pair \
    --security-group-ids sg-xxxxxxxxx \
    --subnet-id subnet-xxxxxxxxx \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=pulldb-dev-01},{Key=Service,Value=pulldb}]'

# If attaching to existing instance (requires stop/start)
INSTANCE_ID="i-xxxxxxxxx"
aws ec2 stop-instances --instance-ids $INSTANCE_ID
aws ec2 wait instance-stopped --instance-ids $INSTANCE_ID
aws ec2 associate-iam-instance-profile \
    --instance-id $INSTANCE_ID \
    --iam-instance-profile Name=pulldb-instance-profile
aws ec2 start-instances --instance-ids $INSTANCE_ID
```

## Step 2: Staging Account Setup (333204494849)

> **Prerequisites**: Staging account admin must have AWS console or CLI access to account `333204494849`.

### 2.1 Create Cross-Account Role

```bash
# Create trust policy allowing dev account
cat > /tmp/pulldb-staging-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-dev-access-2025"
        }
      }
    }
  ]
}
EOF

# Create role
aws iam create-role \
    --role-name pulldb-cross-account-readonly \
    --assume-role-policy-document file:///tmp/pulldb-staging-trust-policy.json \
    --description "Cross-account read-only access for pullDB from dev account" \
    --tags Key=Service,Value=pulldb Key=Purpose,Value=cross-account-access
```

### 2.2 Create S3 Read-Only Policy

```bash
cat > /tmp/pulldb-staging-s3-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListStagingBucket",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs"
    },
    {
      "Sid": "GetStagingBackupObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectMetadata",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
    },
    {
      "Sid": "DenyWriteOperations",
      "Effect": "Deny",
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:DeleteObjectVersion"
      ],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs/*"
    },
    {
      "Sid": "KMSDecryptForS3",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "s3.us-east-1.amazonaws.com"
        }
      }
    },
    {
      "Sid": "SSMParameterRead",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": "arn:aws:ssm:us-east-1:333204494849:parameter/pulldb/*"
    }
  ]
}
EOF

# Create and attach policy
aws iam create-policy \
    --policy-name pulldb-staging-s3-readonly \
    --policy-document file:///tmp/pulldb-staging-s3-policy.json \
    --description "Read-only access to staging S3 backups and SSM parameters"

aws iam attach-role-policy \
    --role-name pulldb-cross-account-readonly \
    --policy-arn arn:aws:iam::333204494849:policy/pulldb-staging-s3-readonly
```

### 2.3 Update S3 Bucket Policy

```bash
# Get existing bucket policy
aws s3api get-bucket-policy --bucket pestroutesrdsdbs > /tmp/current-bucket-policy.json

# Add pullDB access to bucket policy
cat > /tmp/updated-bucket-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowPullDBCrossAccountRead",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::333204494849:role/pulldb-cross-account-readonly"
      },
      "Action": [
        "s3:GetObject",
        "s3:GetObjectMetadata",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::pestroutesrdsdbs",
        "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
      ]
    }
  ]
}
EOF

# Apply updated policy
aws s3api put-bucket-policy --bucket pestroutesrdsdbs --policy file:///tmp/updated-bucket-policy.json
```

### 2.4 Update KMS Key Policy

```bash
# Get KMS key ID for S3 bucket encryption
KEY_ID=$(aws s3api get-bucket-encryption --bucket pestroutesrdsdbs \
    --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.KMSMasterKeyID' \
    --output text)

# Add dev account to KMS key policy
cat > /tmp/kms-key-policy-addition.json <<'EOF'
{
  "Sid": "AllowPullDBDecryption",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::333204494849:role/pulldb-cross-account-readonly"
  },
  "Action": [
    "kms:Decrypt",
    "kms:DescribeKey"
  ],
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "kms:ViaService": "s3.us-east-1.amazonaws.com"
    }
  }
}
EOF

# Note: Merge this statement into existing KMS key policy via console or CLI
echo "Add this statement to KMS key $KEY_ID policy"
cat /tmp/kms-key-policy-addition.json
```

## Step 3: Production Account Setup (448509429610)

> **Prerequisites**: Production account admin must have AWS console or CLI access to account `448509429610`.

**Repeat Step 2 instructions** with these modifications:
- Role name: `pulldb-cross-account-readonly` (same name, different account)
- Bucket: `pestroutes-rds-backup-prod-vpc-us-east-1-s3`
- Path: `daily/prod/*` instead of `daily/stg/*`
- All ARNs use production account ID `448509429610`

<details>
<summary>Click to expand full production account configuration</summary>

### 3.1 Create Cross-Account Role (Production)

```bash
cat > /tmp/pulldb-prod-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-dev-access-2025"
        }
      }
    }
  ]
}
EOF

aws iam create-role \
    --role-name pulldb-cross-account-readonly \
    --assume-role-policy-document file:///tmp/pulldb-prod-trust-policy.json \
    --description "Cross-account read-only access for pullDB from dev account"
```

### 3.2 Create S3 Read-Only Policy (Production)

```bash
cat > /tmp/pulldb-prod-s3-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListProductionBucket",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    },
    {
      "Sid": "GetProductionBackupObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectMetadata",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/*"
    },
    {
      "Sid": "DenyWriteOperations",
      "Effect": "Deny",
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:DeleteObjectVersion"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/*"
    },
    {
      "Sid": "KMSDecryptForS3",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "s3.us-east-1.amazonaws.com"
        }
      }
    },
    {
      "Sid": "SSMParameterRead",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": "arn:aws:ssm:us-east-1:448509429610:parameter/pulldb/*"
    }
  ]
}
EOF

aws iam create-policy \
    --policy-name pulldb-prod-s3-readonly \
    --policy-document file:///tmp/pulldb-prod-s3-policy.json

aws iam attach-role-policy \
    --role-name pulldb-cross-account-readonly \
    --policy-arn arn:aws:iam::448509429610:policy/pulldb-prod-s3-readonly
```

</details>

## Step 4: AWS Profile Configuration

Configure AWS profiles on the EC2 instance for both services to use.

### 4.1 Create AWS Config

```bash
# On EC2 instance (as pulldb service user)
mkdir -p ~/.aws
cat > ~/.aws/config <<'EOF'
[profile pr-staging]
role_arn = arn:aws:iam::333204494849:role/pulldb-cross-account-readonly
credential_source = Ec2InstanceMetadata
external_id = pulldb-dev-access-2025
region = us-east-1

[profile pr-prod]
role_arn = arn:aws:iam::448509429610:role/pulldb-cross-account-readonly
credential_source = Ec2InstanceMetadata
external_id = pulldb-dev-access-2025
region = us-east-1
EOF
```

**Key Settings**:
- `credential_source = Ec2InstanceMetadata` - Uses instance profile instead of access keys
- `external_id` - Prevents confused deputy problem
- No `[default]` profile needed - services explicitly use named profiles

### 4.2 Environment Configuration

```bash
# /etc/pulldb/api.env (API Service)
PULLDB_AWS_PROFILE=pr-staging
PULLDB_S3_BUCKET_STAGING=pestroutesrdsdbs
PULLDB_S3_BUCKET_PROD=pestroutes-rds-backup-prod-vpc-us-east-1-s3
PULLDB_S3_PREFIX_STAGING=daily/stg
PULLDB_S3_PREFIX_PROD=daily/prod

# /etc/pulldb/worker.env (Worker Service)
PULLDB_AWS_PROFILE=pr-staging
PULLDB_S3_BUCKET_STAGING=pestroutesrdsdbs
PULLDB_S3_BUCKET_PROD=pestroutes-rds-backup-prod-vpc-us-east-1-s3
PULLDB_S3_PREFIX_STAGING=daily/stg
PULLDB_S3_PREFIX_PROD=daily/prod
PULLDB_WORK_DIR=/mnt/data/pulldb/work
```

## Step 5: Verification

### 5.1 Test Instance Profile

```bash
# SSH to EC2 instance
# Verify instance metadata service
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Should return: pulldb-ec2-service-role

# Get temporary credentials
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/pulldb-ec2-service-role

# Should return JSON with AccessKeyId, SecretAccessKey, Token
```

### 5.2 Test Cross-Account Role Assumption

```bash
# Test staging account access
AWS_PROFILE=pr-staging aws sts get-caller-identity

# Should return:
# {
#   "UserId": "AROAXXXXX:botocore-session-12345",
#   "Account": "333204494849",
#   "Arn": "arn:aws:sts::333204494849:assumed-role/pulldb-cross-account-readonly/..."
# }

# Test production account access
AWS_PROFILE=pr-prod aws sts get-caller-identity

# Should return production account (448509429610)
```

### 5.3 Test S3 Access

```bash
# List staging backups
AWS_PROFILE=pr-staging aws s3 ls s3://pestroutesrdsdbs/daily/stg/

# List production backups
AWS_PROFILE=pr-prod aws s3 ls s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/

# Test read access
AWS_PROFILE=pr-staging aws s3api head-object \
    --bucket pestroutesrdsdbs \
    --key daily/stg/customer/daily_mydumper_customer_2025-10-30T03-00-00Z_Wed_dbimp.tar

# Verify write is denied
AWS_PROFILE=pr-staging aws s3 cp /tmp/test.txt s3://pestroutesrdsdbs/test.txt
# Should return: Access Denied error
```

### 5.4 Test from Python (Services)

```python
import boto3

# Test as API service would (read-only listing)
session = boto3.Session(profile_name='pr-staging')
s3_client = session.client('s3')

# List objects (allowed)
response = s3_client.list_objects_v2(
    Bucket='pestroutesrdsdbs',
    Prefix='daily/stg/',
    MaxKeys=10
)
print(f"Found {len(response.get('Contents', []))} backups")

# Head object metadata (allowed)
metadata = s3_client.head_object(
    Bucket='pestroutesrdsdbs',
    Key='daily/stg/customer/daily_mydumper_customer_2025-10-30T03-00-00Z_Wed_dbimp.tar'
)
print(f"Backup size: {metadata['ContentLength']} bytes")

# Download object (allowed for worker, depends on IAM policy)
try:
    s3_client.download_file(
        'pestroutesrdsdbs',
        'daily/stg/customer/daily_mydumper_customer_2025-10-30T03-00-00Z_Wed_dbimp.tar',
        '/tmp/test-backup.tar'
    )
    print("Download successful")
except Exception as e:
    print(f"Download failed: {e}")
```

## Permission Matrix

| Operation | API Service | Worker Service | Notes |
|-----------|-------------|----------------|-------|
| `s3:ListBucket` | ✅ Allowed | ✅ Allowed | Discover backups |
| `s3:HeadObject` | ✅ Allowed | ✅ Allowed | Get metadata |
| `s3:GetObject` (small) | ✅ Allowed | ✅ Allowed | Schema files |
| `s3:GetObject` (*.tar) | ❌ Denied by policy | ✅ Allowed | Large backups |
| `s3:PutObject` | ❌ Denied | ❌ Denied | No writes |
| `s3:DeleteObject` | ❌ Denied | ❌ Denied | No deletes |
| `kms:Decrypt` | ✅ Allowed (via S3) | ✅ Allowed (via S3) | SSE-KMS |
| `ssm:GetParameter` | ✅ Allowed | ✅ Allowed | MySQL creds |

## Security Best Practices

### 1. External ID Usage
- Prevents confused deputy attacks
- Same external ID used across staging and production
- Stored in AWS profiles config
- Must match in trust policies

### 2. Explicit Deny for Writes
- IAM policies include explicit `Deny` for PutObject, DeleteObject
- Protects against policy expansion or accidental grants
- Explicit deny overrides all allows

### 3. Instance Profile Benefits
- No long-lived credentials in files
- Automatic credential rotation (AWS SDK handles)
- Credentials never leave AWS infrastructure
- Easy to revoke - just detach instance profile

### 4. Least Privilege
- API service policy denies GetObject on `*.tar` files
- Worker service has full read but no write
- SSM parameter access scoped to `/pulldb/*` prefix only
- KMS decrypt only via S3 service (not direct)

### 5. Audit Trail
- All role assumptions logged in CloudTrail
- S3 access logs capture all operations
- CloudWatch metrics track AssumeRole calls
- Parameter Store access logged

## Troubleshooting

### Error: Access Denied when assuming role

**Symptom**: `An error occurred (AccessDenied) when calling the AssumeRole operation`

**Causes**:
1. Trust policy doesn't include dev account principal
2. External ID mismatch
3. IAM role doesn't have sts:AssumeRole permission

**Fix**:
```bash
# Verify trust policy in target account
aws iam get-role --role-name pulldb-cross-account-readonly \
    --query 'Role.AssumeRolePolicyDocument'

# Verify EC2 role has AssumeRole permission
AWS_PROFILE=default aws iam list-attached-role-policies \
    --role-name pulldb-ec2-service-role
```

### Error: Unable to locate credentials

**Symptom**: `Unable to locate credentials. You can configure credentials by running "aws configure"`

**Causes**:
1. Instance profile not attached to EC2 instance
2. Wrong credential_source in ~/.aws/config
3. Metadata service unavailable

**Fix**:
```bash
# Check instance profile
aws ec2 describe-instances --instance-ids i-xxxxx \
    --query 'Reservations[0].Instances[0].IamInstanceProfile'

# Test metadata service
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Verify ~/.aws/config has credential_source = Ec2InstanceMetadata
```

### Error: KMS Decrypt Access Denied

**Symptom**: `An error occurred (AccessDenied) when calling the GetObject operation: Access Denied`

**Cause**: KMS key policy doesn't allow dev account to decrypt

**Fix**:
```bash
# Get KMS key ID from bucket encryption
KEY_ID=$(aws s3api get-bucket-encryption --bucket pestroutesrdsdbs \
    --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.KMSMasterKeyID' \
    --output text)

# Check key policy (in staging/prod account)
aws kms get-key-policy --key-id $KEY_ID --policy-name default

# Add pulldb-cross-account-readonly role to key policy
```

## Maintenance

### Rotating External ID

```bash
# 1. Create new external ID
NEW_EXTERNAL_ID="pulldb-dev-access-2026"

# 2. Update trust policies in staging and production accounts
# (Update both trust policies to accept EITHER old or new external ID)

# 3. Update AWS profiles on EC2 instance
sed -i "s/pulldb-dev-access-2025/$NEW_EXTERNAL_ID/g" ~/.aws/config

# 4. Test with new external ID
AWS_PROFILE=pr-staging aws sts get-caller-identity

# 5. Remove old external ID from trust policies after verification
```

### Monitoring

```bash
# CloudWatch Metrics for role assumptions
aws cloudwatch get-metric-statistics \
    --namespace AWS/IAM \
    --metric-name AssumeRole \
    --dimensions Name=RoleName,Value=pulldb-cross-account-readonly \
    --start-time 2025-10-30T00:00:00Z \
    --end-time 2025-10-31T00:00:00Z \
    --period 3600 \
    --statistics Sum

# CloudTrail events for AssumeRole
aws cloudtrail lookup-events \
    --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRole \
    --max-results 50
```

## Related Documentation

- **Two-Service Architecture**: See `design/two-service-architecture.md` for API/Worker separation
- **Parameter Store Setup**: See `parameter-store-setup.md` for MySQL credential storage
- **MySQL Setup**: See `mysql-setup.md` for coordination database
- **Deployment**: See `aws-ec2-deployment-setup.md` for complete EC2 setup

## Summary

This authentication setup provides:
- ✅ Secure cross-account S3 access from dev to staging/production
- ✅ No long-lived credentials - uses EC2 instance profile
- ✅ Automatic credential rotation via AWS SDK
- ✅ Permission separation between API and Worker services
- ✅ External ID prevents confused deputy attacks
- ✅ Explicit denies prevent accidental writes
- ✅ Complete audit trail via CloudTrail

Both API and Worker services use the same instance profile but implement different S3 access patterns:
- API service lists and inspects backups (discovery)
- Worker service downloads and restores backups (execution)
