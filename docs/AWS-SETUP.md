# AWS Setup Guide for pullDB

> **Complete Step-by-Step AWS Configuration**
>
> This is the **single authoritative guide** for configuring all AWS resources needed for pullDB. Follow these steps in order to set up cross-account S3 access, Secrets Manager credential storage, and EC2 instance authentication.
>
> **Last Updated**: November 4, 2025

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Quick Start Summary](#quick-start-summary)
- [Part 1: Development Account Setup](#part-1-development-account-setup)
- [Part 2: Staging Account Setup](#part-2-staging-account-setup)
- [Part 3: Production Account Setup (Optional)](#part-3-production-account-setup-optional)
- [Part 4: Secrets Manager Configuration](#part-4-secrets-manager-configuration)
- [Part 5: Verification](#part-5-verification)
- [Troubleshooting](#troubleshooting)
- [Security Best Practices](#security-best-practices)
- [Cost Optimization](#cost-optimization)

---

## Overview

### Architecture

pullDB uses a three-account architecture with cross-account S3 access:

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
│                         ↓                                         │
│  ┌──────────────────────────────────────────────────────────── │
│  │ AWS Secrets Manager                                          │
│  │ • /pulldb/mysql/coordination-db (test + runtime)            │
│  │ • /pulldb/mysql/localhost-test                              │
│  │ • /pulldb/mysql/db3-dev                                     │
│  │ • /pulldb/mysql/db4-dev                                     │
│  │ • /pulldb/mysql/db5-dev                                     │
│  └─────────────────────────────────────────────────────────────┘│
│                         ↓ Direct OR AssumeRole                   │
└─────────────────────────┼───────────────────────────────────────┘
                          ↓
┌─────────────────────────┼───────────────────────────────────────┐
│ Staging Account (333204494849)                                   │
│                         ↓                                         │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ S3 Bucket: pestroutesrdsdbs                                  ││
│ │ Path: s3://pestroutesrdsdbs/daily/stg/                       ││
│ │ Contains: Both mydumper formats (newer + older)              ││
│ │ Bucket Policy: Allows dev account role                       ││
│ │ KMS Encryption: Key policy allows dev account                ││
│ └──────────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────┼───────────────────────────────────────┐
│ Production Account (448509429610)                                │
│                         ↓                                         │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ S3 Bucket: pestroutes-rds-backup-prod-vpc-us-east-1-s3      ││
│ │ Path: s3://.../daily/prod/                                   ││
│ │ Contains: Older mydumper format (migrating to newer)         ││
│ │ Bucket Policy: Allows cross-account readonly role            ││
│ │ KMS Encryption: Key policy allows dev account                ││
│ └──────────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────────────┘
```

### Access Patterns

**Staging Bucket Access** (Recommended: Direct):
1. Dev account role → Staging S3 bucket policy → Bucket access
2. No AssumeRole overhead, simpler configuration

**Production Bucket Access** (Recommended: Cross-Account Role):
1. Dev account role → AssumeRole → Production account role → S3 access
2. Stronger security boundary, external ID validation

### Components

| Component | AWS Access | Identity Source | Accesses |
|-----------|----------|-----------------|----------|
| **CLI** | ❌ None | SSH username | Daemon API only |
| **API Service** | ✅ Yes | EC2 instance profile | S3 (list/head), Secrets Manager |
| **Worker Service** | ✅ Yes | EC2 instance profile | S3 (download), MySQL, Secrets Manager |

---

## Prerequisites

### AWS Accounts Access

You'll need appropriate permissions in:
- ✅ **Development account** (345321506926) - Admin or IAM role creation permissions
- ✅ **Staging account** (333204494849) - S3 bucket policy modification permissions
- ⚠️ **Production account** (448509429610) - Optional, only if configuring production access

### AWS CLI Setup

```bash
# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Verify installation
aws --version
# Output: aws-cli/2.x.x Python/3.x.x Linux/x.x.x
```

### EC2 Instance

- Ubuntu 24.04 LTS or later
- Instance ID known (for attaching instance profile)
- SSH access to instance

---

## Quick Start Summary

**Minimum viable setup for staging access** (30 minutes):

1. Development Account:
   - Create EC2 service role with S3 read policy for staging bucket
   - Create instance profile and attach to EC2 instance
   - Create Secrets Manager secrets for MySQL credentials
   - Attach Secrets Manager policy to role

2. Staging Account:
   - Add bucket policy statement allowing dev account role

3. Verify:
   - Test S3 listing from EC2 instance
   - Test secret retrieval
   - Run pullDB integration tests

---

## Part 1: Development Account Setup

All commands in this section run in the **development account (345321506926)**.

### Step 1.1: Create EC2 Service Role

Create the IAM role that will be attached to the EC2 instance.

**Create trust policy file:**

```bash
cat > /tmp/pulldb-ec2-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "ec2.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
```

**Create the role:**

```bash
aws iam create-role \
    --role-name pulldb-ec2-service-role \
    --assume-role-policy-document file:///tmp/pulldb-ec2-trust-policy.json \
    --description "EC2 service role for pullDB API and Worker services" \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development

# Verify
aws iam get-role --role-name pulldb-ec2-service-role
```

### Step 1.2: Add Secrets Manager Access Policy

Create policy allowing retrieval of MySQL credentials from Secrets Manager.

**Create policy document:**

```bash
cat > /tmp/pulldb-secrets-manager-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GetPullDBSecrets",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/*"
      ]
    },
    {
      "Sid": "ListSecretsForDiscovery",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:ListSecrets"
      ],
      "Resource": "*",
      "Condition": {
        "StringLike": {
          "secretsmanager:ResourceTag/Service": "pulldb"
        }
      }
    },
    {
      "Sid": "DecryptSecretsWithKMS",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": [
            "secretsmanager.us-east-1.amazonaws.com"
          ]
        }
      }
    }
  ]
}
EOF
```

**Create and attach policy:**

```bash
aws iam create-policy \
    --policy-name pulldb-secrets-manager-access \
    --policy-document file:///tmp/pulldb-secrets-manager-policy.json \
    --description "Allows pullDB to retrieve MySQL credentials from Secrets Manager"

aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access

# Verify
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

### Step 1.3: Add Cross-Account Assumption Policy (Optional)

Only needed if using cross-account role assumption pattern (production access).

**Create policy document:**

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
```

**Create and attach policy:**

```bash
aws iam create-policy \
    --policy-name pulldb-cross-account-assume-role \
    --policy-document file:///tmp/pulldb-assume-role-policy.json \
    --description "Allows pullDB to assume cross-account roles for S3 access"

aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-cross-account-assume-role
```

### Step 1.4: Add Staging S3 Read Policy (Direct Access)

This policy grants direct S3 access to the staging bucket without AssumeRole.

**Create policy document:**

```bash
cat > /tmp/pulldb-staging-s3-read.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListStagingBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs"
    },
    {
      "Sid": "ReadStagingBackups",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:HeadObject"],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
    },
    {
      "Sid": "DenyWriteOperations",
      "Effect": "Deny",
      "Action": ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs/*"
    },
    {
      "Sid": "KMSDecryptForS3",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:DescribeKey"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "s3.us-east-1.amazonaws.com"
        }
      }
    }
  ]
}
EOF
```

**Create and attach policy:**

```bash
aws iam create-policy \
    --policy-name pulldb-staging-s3-read \
    --policy-document file:///tmp/pulldb-staging-s3-read.json \
    --description "Read-only access to staging S3 backups"

aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-staging-s3-read
```

### Step 1.5: Create Instance Profile

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

### Step 1.6: Attach Instance Profile to EC2

```bash
# Get your instance ID
INSTANCE_ID="i-0dcd59209b7e932c3"  # Replace with your instance ID

# Check if instance already has a profile
aws ec2 describe-iam-instance-profile-associations \
    --filters "Name=instance-id,Values=$INSTANCE_ID"

# If no profile attached, associate it
aws ec2 associate-iam-instance-profile \
    --instance-id $INSTANCE_ID \
    --iam-instance-profile Name=pulldb-instance-profile

# If replacing existing profile, first disassociate
ASSOCIATION_ID=$(aws ec2 describe-iam-instance-profile-associations \
    --filters "Name=instance-id,Values=$INSTANCE_ID" \
    --query 'IamInstanceProfileAssociations[0].AssociationId' \
    --output text)

aws ec2 disassociate-iam-instance-profile --association-id $ASSOCIATION_ID
aws ec2 associate-iam-instance-profile \
    --instance-id $INSTANCE_ID \
    --iam-instance-profile Name=pulldb-instance-profile

# Verify
aws ec2 describe-instances --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].IamInstanceProfile'
```

**Summary - Development Account:**
- ✅ EC2 service role created
- ✅ Secrets Manager access policy attached
- ✅ Staging S3 read policy attached
- ✅ Instance profile created and attached to EC2

---

## Part 2: Staging Account Setup

All commands in this section run in the **staging account (333204494849)**.

### Step 2.1: Update S3 Bucket Policy

Add a statement to the staging bucket policy allowing the dev account role.

**Check existing bucket policy:**

```bash
aws s3api get-bucket-policy --bucket pestroutesrdsdbs \
    --query Policy --output text | jq .
```

**Option A: No existing policy - create new:**

```bash
aws s3api put-bucket-policy --bucket pestroutesrdsdbs --policy '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowPullDBDevAccountDirectRead",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"
      },
      "Action": [
        "s3:GetObject",
        "s3:GetObjectMetadata",
        "s3:ListBucket",
        "s3:HeadObject"
      ],
      "Resource": [
        "arn:aws:s3:::pestroutesrdsdbs",
        "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
      ]
    }
  ]
}'
```

**Option B: Existing policy - add statement manually:**

```bash
# Download current policy
aws s3api get-bucket-policy --bucket pestroutesrdsdbs \
    --query Policy --output text > /tmp/current-bucket-policy.json

# Edit /tmp/current-bucket-policy.json and add this statement to the Statement array:
{
  "Sid": "AllowPullDBDevAccountDirectRead",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"
  },
  "Action": [
    "s3:GetObject",
    "s3:GetObjectMetadata",
    "s3:ListBucket",
    "s3:HeadObject"
  ],
  "Resource": [
    "arn:aws:s3:::pestroutesrdsdbs",
    "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
  ]
}

# Apply updated policy
aws s3api put-bucket-policy --bucket pestroutesrdsdbs \
    --policy file:///tmp/updated-bucket-policy.json
```

### Step 2.2: Update KMS Key Policy (If Encrypted)

If the bucket uses KMS encryption, update the key policy.

```bash
# Get KMS key ID
KEY_ID=$(aws s3api get-bucket-encryption --bucket pestroutesrdsdbs \
    --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.KMSMasterKeyID' \
    --output text)

# View current key policy
aws kms get-key-policy --key-id $KEY_ID --policy-name default

# Add this statement to key policy (via console or CLI)
{
  "Sid": "AllowPullDBDecryption",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"
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
```

**Summary - Staging Account:**
- ✅ Bucket policy updated to allow dev account role
- ✅ KMS key policy updated (if applicable)

---

## Part 3: Production Account Setup (Optional)

Only follow this section if configuring production bucket access. Uses cross-account role assumption pattern for stronger security.

All commands in this section run in the **production account (448509429610)**.

### Step 3.1: Create Cross-Account Role

**Create trust policy:**

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
```

**Create the role:**

```bash
aws iam create-role \
    --role-name pulldb-cross-account-readonly \
    --assume-role-policy-document file:///tmp/pulldb-prod-trust-policy.json \
    --description "Cross-account read-only access for pullDB from dev account"
```

### Step 3.2: Add S3 Read Policy to Role

**Create permissions policy:**

```bash
cat > /tmp/pulldb-prod-s3-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListProductionBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    },
    {
      "Sid": "GetProductionBackupObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectMetadata", "s3:GetObjectVersion"],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/*"
    },
    {
      "Sid": "DenyWriteOperations",
      "Effect": "Deny",
      "Action": ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/*"
    },
    {
      "Sid": "KMSDecryptForS3",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:DescribeKey"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "s3.us-east-1.amazonaws.com"
        }
      }
    }
  ]
}
EOF
```

**Attach policy:**

```bash
aws iam create-policy \
    --policy-name pulldb-prod-s3-readonly \
    --policy-document file:///tmp/pulldb-prod-s3-policy.json

aws iam attach-role-policy \
    --role-name pulldb-cross-account-readonly \
    --policy-arn arn:aws:iam::448509429610:policy/pulldb-prod-s3-readonly
```

**Summary - Production Account:**
- ✅ Cross-account role created with external ID
- ✅ S3 read-only policy attached

---

## Part 4: Secrets Manager Configuration

Create MySQL credential secrets in the development account.

### Step 4.1: Create Coordination Database Secret

**MANDATORY for tests and runtime:**

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/coordination-db \
    --description "MySQL credentials for pullDB coordination database" \
    --secret-string '{
        "username": "pulldb_app",
        "password": "REPLACE_WITH_ACTUAL_PASSWORD",
        "host": "localhost",
        "port": 3306,
        "database": "pulldb"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development Key=Purpose,Value=coordination

# Verify
aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db
```

### Step 4.2: Create Target Database Secrets

Create secrets for each target MySQL server where databases will be restored.

**Local sandbox (default):**

```bash
aws secretsmanager create-secret \
  --name /pulldb/mysql/localhost-test \
  --description "MySQL credentials for local sandbox restore target" \
  --secret-string '{
    "username": "pulldb_app",
    "password": "REPLACE_WITH_ACTUAL_PASSWORD",
    "host": "localhost",
    "port": 3306,
    "database": "pulldb_sandbox"
  }' \
  --tags Key=Service,Value=pulldb Key=Environment,Value=development Key=Purpose,Value=local-sandbox

# Verify
aws secretsmanager describe-secret --secret-id /pulldb/mysql/localhost-test
```

**db3-dev (DEV team):**

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/db3-dev \
    --description "MySQL credentials for db3-dev target database server" \
    --secret-string '{
        "username": "pulldb_app",
        "password": "REPLACE_WITH_ACTUAL_PASSWORD",
        "host": "db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com",
        "port": 3306
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development Key=Team,Value=DEV
```

**db4-dev (SUPPORT team):**

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/db4-dev \
  --description "MySQL credentials for db4-dev target database server (support team)" \
    --secret-string '{
        "username": "pulldb_app",
        "password": "REPLACE_WITH_ACTUAL_PASSWORD",
        "host": "db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com",
        "port": 3306
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development Key=Team,Value=SUPPORT
```

**db5-dev (IMPLEMENTATION team):**

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/db5-dev \
    --description "MySQL credentials for db5-dev target database server" \
    --secret-string '{
        "username": "pulldb_app",
        "password": "REPLACE_WITH_ACTUAL_PASSWORD",
        "host": "db-mysql-db5-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com",
        "port": 3306
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development Key=Team,Value=IMPLEMENTATION
```

**Summary - Secrets Manager:**
- ✅ Coordination database secret created
- ✅ Target database secrets created (db-local-dev, db3-dev, db4-dev, db5-dev)

---

## Part 5: Verification

### Step 5.1: Verify Instance Profile

From your EC2 instance:

```bash
# Get instance metadata (IMDSv2)
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" -s)

curl -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/iam/security-credentials/ -s

# Should output: pulldb-ec2-service-role
```

### Step 5.2: Test Caller Identity

```bash
aws sts get-caller-identity

# Should show:
# {
#   "UserId": "AROAXXXXX:i-xxxxxxxxx",
#   "Account": "345321506926",
#   "Arn": "arn:aws:sts::345321506926:assumed-role/pulldb-ec2-service-role/i-xxxxxxxxx"
# }
```

### Step 5.3: Test S3 Access (Staging)

```bash
# List staging backups (should succeed)
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head

# Should show backup files like:
# PRE customer/
# PRE qatemplate/
```

### Step 5.4: Test Secrets Manager Access

```bash
# Test coordination DB secret
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db \
    --query SecretString --output text | jq .

# Should show JSON with username, password, host, port

# Test local sandbox secret
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/localhost-test \
  --query SecretString --output text | jq .

# Should show JSON with localhost host, optional database

# Test target database secrets
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/db3-dev \
    --query SecretString --output text | jq .
```

### Step 5.5: Test Python Integration

```python
# Test credential resolution
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/charleshandshy/Projects/infra.devops/Tools/pullDB')

from pulldb.infra.secrets import CredentialResolver

resolver = CredentialResolver()

# Test coordination DB
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/coordination-db')
print(f"✅ Coordination DB credentials resolved:")
print(f"   Host: {creds['host']}")
print(f"   User: {creds['username']}")
print(f"   Database: {creds.get('database', 'N/A')}")

print("\n✅ All verifications passed!")
EOF
```

---

## Troubleshooting

### Error: Access Denied (S3)

**Symptom**: `AccessDenied when calling the ListObjectsV2 operation`

**Diagnosis**:
```bash
# Check role policies
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role

# Check instance profile
curl -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/iam/info -s
```

**Solutions**:
1. Verify `pulldb-staging-s3-read` policy is attached to role
2. Verify instance profile is attached to EC2 instance
3. Check staging account bucket policy includes dev account role principal

### Error: Access Denied (Secrets Manager)

**Symptom**: `AccessDeniedException when calling the GetSecretValue operation`

**Diagnosis**:
```bash
# Check Secrets Manager policy attachment
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role | \
    grep pulldb-secrets-manager-access
```

**Solutions**:
1. Attach `pulldb-secrets-manager-access` policy to role (Step 1.2)
2. Verify secret exists: `aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db`
3. Check secret is in development account (345321506926)

### Error: Unable to Locate Credentials

**Symptom**: `Unable to locate credentials`

**Diagnosis**:
```bash
# Check instance metadata service
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/ -s
```

**Solutions**:
1. Instance profile not attached - run Step 1.6
2. IMDSv2 required - use TOKEN-based requests (see Step 5.1)
3. Instance profile misconfigured - verify role is added to profile

### Error: ExternalId Mismatch (Production)

**Symptom**: `An error occurred (AccessDenied) when calling the AssumeRole operation`

**Diagnosis**:
```bash
# Check production role trust policy
aws iam get-role --role-name pulldb-cross-account-readonly \
    --query 'Role.AssumeRolePolicyDocument' | jq .
```

**Solutions**:
1. Verify external ID in trust policy matches: `pulldb-dev-access-2025`
2. Check dev account has `pulldb-cross-account-assume-role` policy attached

---

## Security Best Practices

### 1. Least Privilege Access

- ✅ IAM policies scoped to specific resources (`/pulldb/mysql/*`)
- ✅ Read-only S3 access (explicit Deny for write operations)
- ✅ KMS decrypt limited to specific AWS services
- ✅ External ID required for cross-account access

### 2. Credential Management

- ✅ No long-lived credentials on disk
- ✅ Automatic rotation via EC2 instance metadata (every 60 minutes)
- ✅ Secrets Manager for MySQL credentials (enables rotation)
- ✅ KMS encryption at rest for all secrets

### 3. Audit Trail

- ✅ CloudTrail logs all API calls
- ✅ S3 access logs for backup downloads
- ✅ Secrets Manager access logged with caller identity
- ✅ MySQL audit log for database operations

### 4. Network Security

- ✅ EC2 security groups restrict inbound access
- ✅ Private subnets for RDS instances
- ✅ VPC endpoints for AWS services (optional optimization)

---

## Cost Optimization

### AWS Secrets Manager

**Current Setup** (5 secrets):
- 5 secrets × $0.40/month = **$2.00/month**
- API calls: ~10,000/month × $0.05/10k = **$0.05/month**
- **Total**: ~$1.65/month

**Optimization Options**:
1. Cache credentials in application memory (reduce API calls)
2. Use SSM Parameter Store for non-secret config (free tier)
3. Enable automatic rotation only for production credentials

### S3 Transfer Costs

- **Staging account** → Dev account: **$0.00** (same region, cross-account free)
- **Production account** → Dev account: **$0.00** (same region, cross-account free)
- **Data egress**: Only charged if downloading outside AWS

### EC2 Instance Profile

- **Cost**: $0.00 (no additional charge for IAM roles)

---

## Quick Reference Commands

```bash
# Verify instance profile
aws sts get-caller-identity

# List staging backups
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head

# Get coordination DB secret
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db

# Check role policies
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role

# View instance metadata
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" -s)
curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/info -s
```

---

## Summary

This setup provides:
- ✅ Secure cross-account S3 access from dev to staging/production
- ✅ No long-lived credentials - uses EC2 instance profile
- ✅ Automatic credential rotation via AWS SDK
- ✅ Secrets Manager for MySQL credentials with rotation support
- ✅ External ID prevents confused deputy attacks
- ✅ Explicit denies prevent accidental writes
- ✅ Complete audit trail via CloudTrail
- ✅ KMS decrypt scoped to specific AWS services

**Total Setup Time**: ~1 hour
**Monthly Cost**: ~$2 (Secrets Manager only)
**Security**: Production-grade with defense in depth

---

**Last Updated**: November 4, 2025
**Maintained By**: PestRoutes Infrastructure Team
**Related Docs**: See `/docs` directory for detailed component guides
