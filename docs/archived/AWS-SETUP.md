# AWS Setup Guide for pullDB

> **Complete Step-by-Step AWS Configuration**
>
> This guide is split into two sections:
> - **Section A: Service Installation** - For deploying pullDB to production/staging EC2 instances
> - **Section B: Developer Test Environment** - For local development and running tests
>
> **Last Updated**: December 2025 (MySQL user separation)

## Table of Contents

### Section A: Service Installation
- [A.1 Overview](#a1-overview)
- [A.2 Prerequisites](#a2-prerequisites)
- [A.3 EC2 Instance Profile Setup](#a3-ec2-instance-profile-setup)
- [A.4 Cross-Account S3 Access](#a4-cross-account-s3-access)
- [A.5 Secrets Manager Configuration](#a5-secrets-manager-configuration)
- [A.6 Service Verification](#a6-service-verification)

### Section B: Developer Test Environment
- [B.1 Overview](#b1-overview)
- [B.2 Prerequisites](#b2-prerequisites)
- [B.3 AWS CLI Profile Setup](#b3-aws-cli-profile-setup)
- [B.4 Test Environment Variables](#b4-test-environment-variables)
- [B.5 Running Tests](#b5-running-tests)
- [B.6 Developer Verification](#b6-developer-verification)

### Reference
- [Troubleshooting](#troubleshooting)
- [Security Best Practices](#security-best-practices)
- [Quick Reference Commands](#quick-reference-commands)

---

# Section A: Service Installation

> **Audience**: System administrators, DevOps engineers deploying pullDB to EC2 instances.
>
> **Goal**: Configure AWS resources for the pullDB service running as `pulldb_service` user on an EC2 instance with an attached instance profile.

---

## A.1 Overview

### Architecture

The pullDB service uses EC2 instance profiles for AWS authentication (no stored credentials):

```
┌─────────────────────────────────────────────────────────────────┐
│ EC2 Instance: pulldb-dev-01                                      │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ pullDB Service (/opt/pulldb.service)                         │ │
│ │   User: pulldb_service                                       │ │
│ │                                                               │ │
│ │ ┌─────────────────┐  ┌─────────────────┐                    │ │
│ │ │  API Service    │  │ Worker Service  │                    │ │
│ │ │ • List S3       │  │ • Download S3   │                    │ │
│ │ │ • HeadObject    │  │ • GetObject     │                    │ │
│ │ └─────────────────┘  └─────────────────┘                    │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                         ↓                                         │
│    ┌────────────────────────────────────┐                        │
│    │ EC2 Instance Profile               │                        │
│    │ pulldb-instance-profile            │                        │
│    │   Attached Role:                   │                        │
│    │   pulldb-ec2-service-role          │                        │
│    └────────────────────────────────────┘                        │
│                         ↓                                         │
└─────────────────────────┼───────────────────────────────────────┘
                          ↓
         ┌────────────────┴────────────────┐
         ↓                                  ↓
┌─────────────────────┐          ┌─────────────────────┐
│ Secrets Manager     │          │ S3 Buckets          │
│ /pulldb/mysql/*     │          │ (Cross-Account)     │
└─────────────────────┘          └─────────────────────┘
```

### Components

| Component | AWS Access | Identity Source | Accesses |
|-----------|----------|-----------------|----------|
| **CLI** | ❌ None | SSH username | Daemon API only |
| **API Service** | ✅ Yes | EC2 instance profile | S3 (list/head), Secrets Manager |
| **Worker Service** | ✅ Yes | EC2 instance profile | S3 (download), MySQL, Secrets Manager |

---

## A.2 Prerequisites

### Required Access

- **Development account** (345321506926) - IAM role creation permissions
- **Staging account** (333204494849) - S3 bucket policy modification permissions
- **Production account** (448509429610) - Optional, only for production access

### EC2 Instance Requirements

- Ubuntu 24.04 LTS or later
- Instance ID known (for attaching instance profile)
- SSH access to instance
- pullDB package installed (`sudo dpkg -i pulldb_*.deb`)

---

## A.3 EC2 Instance Profile Setup

All commands run in the **development account (345321506926)**.

### Step A.3.1: Create EC2 Service Role

```bash
# Create trust policy
cat > /tmp/pulldb-ec2-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": ["ec2.amazonaws.com"]
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

### Step A.3.2: Attach Secrets Manager Policy

```bash
cat > /tmp/pulldb-secrets-manager-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GetPullDBSecrets",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
      "Resource": ["arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/*"]
    },
    {
      "Sid": "ListSecretsForDiscovery",
      "Effect": "Allow",
      "Action": ["secretsmanager:ListSecrets"],
      "Resource": "*"
    },
    {
      "Sid": "DecryptSecretsWithKMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:DescribeKey"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["secretsmanager.us-east-1.amazonaws.com"]
        }
      }
    }
  ]
}
EOF

aws iam create-policy \
    --policy-name pulldb-secrets-manager-access \
    --policy-document file:///tmp/pulldb-secrets-manager-policy.json

aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access
```

> **Note on ListSecrets**: The `ListSecrets` action requires `Resource: "*"` because AWS does not support
> resource-level permissions or condition keys (like `secretsmanager:ResourceTag`) for this action.
> See [AWS Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awssecretsmanager.html).
> Filtering is done client-side using `--filters Key=name,Values=/pulldb`.

### Step A.3.3: Attach S3 Read Policy (Staging)

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
        "StringEquals": {"kms:ViaService": "s3.us-east-1.amazonaws.com"}
      }
    }
  ]
}
EOF

aws iam create-policy \
    --policy-name pulldb-staging-s3-read \
    --policy-document file:///tmp/pulldb-staging-s3-read.json

aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-staging-s3-read
```

### Step A.3.4: Create and Attach Instance Profile

```bash
# Create instance profile
aws iam create-instance-profile \
    --instance-profile-name pulldb-instance-profile

# Add role to instance profile
aws iam add-role-to-instance-profile \
    --instance-profile-name pulldb-instance-profile \
    --role-name pulldb-ec2-service-role

# Attach to EC2 instance (replace with your instance ID)
INSTANCE_ID="i-0dcd59209b7e932c3"
aws ec2 associate-iam-instance-profile \
    --instance-id $INSTANCE_ID \
    --iam-instance-profile Name=pulldb-instance-profile
```

---

## A.4 Cross-Account S3 Access

### Staging Account (333204494849)

Add bucket policy statement allowing dev account role:

```bash
# Run in staging account
aws s3api put-bucket-policy --bucket pestroutesrdsdbs --policy '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowPullDBDevAccountDirectRead",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"
      },
      "Action": ["s3:GetObject", "s3:ListBucket", "s3:HeadObject"],
      "Resource": [
        "arn:aws:s3:::pestroutesrdsdbs",
        "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
      ]
    }
  ]
}'
```

### Production Account (448509429610) - Optional

For production access, create a cross-account role with external ID:

```bash
# Run in production account
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
        "StringEquals": {"sts:ExternalId": "pulldb-dev-access-2025"}
      }
    }
  ]
}
EOF

aws iam create-role \
    --role-name pulldb-cross-account-readonly \
    --assume-role-policy-document file:///tmp/pulldb-prod-trust-policy.json
```

---

## A.5 Secrets Manager Configuration

Create MySQL credential secrets in the development account.

**IMPORTANT**: pullDB uses **service-specific MySQL users** with least-privilege access. Each service has its own secret containing `host` and `password`. The username is set via service-specific environment variables.

### Secrets Structure (Three Service Users)

| Secret | User | Purpose |
|--------|------|---------|
| `/pulldb/mysql/api` | `pulldb_api` | API service - job queue read/write |
| `/pulldb/mysql/worker` | `pulldb_worker` | Worker service - job processing |
| `/pulldb/mysql/loader` | `pulldb_loader` | Target hosts - myloader restore operations |
| `/pulldb/mysql/coordination-db` | `pulldb_api` | Coordination database (alias) |
| `/pulldb/mysql/localhost-test` | `pulldb_test` | Local testing |

### Required Tags

All `/pulldb/*` secrets **must** be tagged with `Service=pulldb` for organizational consistency and future ABAC policies:

```bash
# Tag existing secrets
aws secretsmanager tag-resource \
    --secret-id /pulldb/mysql/api \
    --tags Key=Service,Value=pulldb

# Always include tags when creating new secrets (see examples below)
```

### Create API Service Secret (Required)

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/api \
    --description "MySQL credentials for pullDB API service" \
    --secret-string '{
        "password": "REPLACE_WITH_API_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development
```

### Create Worker Service Secret (Required)

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/worker \
    --description "MySQL credentials for pullDB Worker service" \
    --secret-string '{
        "password": "REPLACE_WITH_WORKER_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development
```

### Create Loader Secret (Required)

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/loader \
    --description "MySQL credentials for myloader restore operations on target hosts" \
    --secret-string '{
        "password": "REPLACE_WITH_LOADER_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development
```

### Create Coordination DB Secret (Required)

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/coordination-db \
    --description "MySQL credentials for pullDB coordination database" \
    --secret-string '{
        "password": "REPLACE_WITH_COORDINATION_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development
```

### Create Localhost Test Secret (Optional - for local testing)

```bash
aws secretsmanager create-secret \
    --name /pulldb/mysql/localhost-test \
    --description "MySQL credentials for local testing" \
    --secret-string '{
        "password": "REPLACE_WITH_TEST_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development
```

**Required environment variables** (add to `.env` or systemd environment):
```bash
# Service-specific users (REQUIRED - services fail without these)
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker

# Common settings
PULLDB_MYSQL_PORT=3306
PULLDB_MYSQL_DATABASE=pulldb_service
```

---

## A.6 Service Verification

Run these commands **on the EC2 instance** after installing the pullDB package.

### Verify Instance Profile

```bash
# Get instance metadata (IMDSv2)
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" -s)

curl -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/iam/security-credentials/ -s
# Should output: pulldb-ec2-service-role
```

### Test AWS Identity

```bash
aws sts get-caller-identity
# Should show assumed-role/pulldb-ec2-service-role/i-xxxxxxxxx
```

### Test S3 Access

```bash
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head
# Should show backup directories
```

### Test Secrets Manager Access

```bash
aws secretsmanager get-secret-value \
    --secret-id /pulldb/mysql/api \
    --query SecretString --output text | jq .
# Should show JSON with host and password
```

### Test Python Integration

```bash
/opt/pulldb.service/venv/bin/python3 << 'EOF'
from pulldb.infra.secrets import CredentialResolver

resolver = CredentialResolver()
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/api')
print(f"✅ API credentials resolved:")
print(f"   Host: {creds.host}")
print(f"   Password: {'*' * len(creds.password)}")
print("\n✅ Service verification passed!")
EOF
```

### Verify Service Status

```bash
sudo systemctl status pulldb-worker
# Should show: Active: active (running)
```

---

# Section B: Developer Test Environment

> **Audience**: Developers working on pullDB, running tests locally or on the EC2 dev instance.
>
> **Goal**: Configure AWS CLI profiles and environment variables to run the test suite.

---

## B.1 Overview

### Developer Authentication Flow

Developers authenticate using **named AWS CLI profiles** rather than instance profiles:

```
┌─────────────────────────────────────────────────────────────────┐
│ Developer Workstation / EC2 Dev Instance                         │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ ~/.aws/credentials                                           │ │
│ │   [pr-dev]       → Secrets Manager (Dev Account)            │ │
│ │   [pr-staging]   → S3 Staging Bucket                        │ │
│ │   [pr-prod]      → S3 Production Bucket (optional)          │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                         ↓                                         │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Environment Variables                                        │ │
│ │   PULLDB_AWS_PROFILE=pr-dev                                 │ │
│ │   AWS_DEFAULT_REGION=us-east-1                              │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                         ↓                                         │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ pytest / Test Suite                                          │ │
│ │   Uses CredentialResolver with pr-dev profile               │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Profile Usage Matrix

| Profile | Account | Purpose | Accesses |
|---------|---------|---------|----------|
| `pr-dev` | 345321506926 | Default for tests | Secrets Manager, SSM |
| `pr-staging` | 333204494849 | S3 discovery tests | Staging S3 bucket |
| `pr-prod` | 448509429610 | Production S3 tests | Production S3 bucket |

---

## B.2 Prerequisites

### Required Software

```bash
# Python 3.11+ with venv
python3 --version  # Should be 3.11+

# AWS CLI v2
aws --version  # Should be 2.x.x

# Project dependencies
cd ~/Projects/pullDB
pip install -e ".[dev]"
```

### Required Access

You need IAM user credentials or SSO access for:
- **Development account** (345321506926) - For Secrets Manager
- **Staging account** (333204494849) - For S3 backup discovery tests

---

## B.3 AWS CLI Profile Setup

### Option A: IAM User Credentials

Create `~/.aws/credentials`:

```ini
[pr-dev]
aws_access_key_id = AKIAXXXXXXXXXXXXXXXXXX
aws_secret_access_key = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

[pr-staging]
aws_access_key_id = AKIAYYYYYYYYYYYYYYYY
aws_secret_access_key = yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy

[pr-prod]
aws_access_key_id = AKIAZZZZZZZZZZZZZZZZ
aws_secret_access_key = zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz
```

Create `~/.aws/config`:

```ini
[profile pr-dev]
region = us-east-1
output = json

[profile pr-staging]
region = us-east-1
output = json

[profile pr-prod]
region = us-east-1
output = json
```

### Option B: AWS SSO (Recommended for Teams)

```bash
# Configure SSO for each profile
aws configure sso --profile pr-dev
aws configure sso --profile pr-staging

# Login before running tests
aws sso login --profile pr-dev
```

### Option C: Assume Role from Instance Profile

If developing on the EC2 instance with the instance profile attached:

```ini
# ~/.aws/config
[profile pr-dev]
region = us-east-1
# Uses instance profile automatically

[profile pr-staging]
role_arn = arn:aws:iam::333204494849:role/pulldb-cross-account-readonly
source_profile = pr-dev
external_id = pulldb-dev-access-2025
region = us-east-1
```

---

## B.4 Test Environment Variables

### Create test-env/.env file

```bash
cd ~/Projects/pullDB
mkdir -p test-env
cat > test-env/.env << 'EOF'
# AWS Configuration for Tests
PULLDB_AWS_PROFILE=pr-dev
AWS_DEFAULT_REGION=us-east-1

# Service-specific MySQL users (REQUIRED)
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker
PULLDB_MYSQL_DATABASE=pulldb_service

# Credential References (Secrets Manager)
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/api

# S3 Bucket Configuration
PULLDB_S3_BUCKET_STAGING=pestroutesrdsdbs
PULLDB_S3_PREFIX_STAGING=daily/stg/
PULLDB_S3_PROFILE_STAGING=pr-staging

# Logging
PULLDB_LOG_LEVEL=DEBUG
EOF
```

### Load Environment for Testing

```bash
# Option 1: Source before running tests
source test-env/.env && pytest

# Option 2: Use direnv (recommended)
echo "dotenv test-env/.env" > .envrc
direnv allow

# Option 3: Export in shell profile
echo "export PULLDB_AWS_PROFILE=pr-dev" >> ~/.bashrc
```

---

## B.5 Running Tests

### Quick Test Run

```bash
cd ~/Projects/pullDB

# Ensure profile is set
export PULLDB_AWS_PROFILE=pr-dev

# Run all tests
pytest

# Run specific test categories
pytest tests/unit/              # Unit tests (no AWS calls)
pytest tests/integration/       # Integration tests (requires AWS)
pytest -k "secrets"             # Only secrets-related tests
pytest -k "s3 or discovery"     # S3 discovery tests
```

### Test with Verbose Output

```bash
pytest -v --tb=short tests/integration/test_secrets.py
```

### Test with Coverage

```bash
pytest --cov=pulldb --cov-report=html tests/
open htmlcov/index.html
```

---

## B.6 Developer Verification

Run these commands to verify your developer environment is correctly configured.

### Verify AWS Profile

```bash
# Test pr-dev profile
aws sts get-caller-identity --profile pr-dev
# Should show your IAM user/role ARN in account 345321506926

# Test pr-staging profile (if configured)
aws sts get-caller-identity --profile pr-staging
# Should show account 333204494849
```

### Verify Secrets Manager Access

```bash
# Using AWS CLI
aws secretsmanager get-secret-value \
    --secret-id /pulldb/mysql/api \
    --profile pr-dev \
    --query SecretString --output text | jq .
```

### Verify S3 Access

```bash
# List staging backups
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ --profile pr-staging | head
```

### Verify Python Integration

```bash
cd ~/Projects/pullDB

# Activate virtual environment if using one
source .venv/bin/activate

# Test credential resolution
python3 << 'EOF'
import os
os.environ.setdefault('PULLDB_AWS_PROFILE', 'pr-dev')
os.environ.setdefault('PULLDB_API_MYSQL_USER', 'pulldb_api')

from pulldb.infra.secrets import CredentialResolver

resolver = CredentialResolver()
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/api')
print(f"✅ API credentials resolved:")
print(f"   Host: {creds.host}")
print(f"   Password: {'*' * len(creds.password)}")
print("\n✅ Developer environment verification passed!")
EOF
```

### Run Smoke Tests

```bash
# Quick sanity check that AWS integration works
pytest tests/integration/test_secrets.py -v -k "test_resolve"
```

---

# Reference

## Troubleshooting

### Error: Access Denied (S3)

**Symptom**: `AccessDenied when calling the ListObjectsV2 operation`

**For Service Installation**:
1. Verify instance profile is attached: `curl http://169.254.169.254/latest/meta-data/iam/security-credentials/`
2. Check role policies: `aws iam list-attached-role-policies --role-name pulldb-ec2-service-role`
3. Verify staging bucket policy includes dev account role

**For Developer Environment**:
1. Verify correct profile: `aws sts get-caller-identity --profile pr-staging`
2. Check profile has S3 permissions
3. Ensure `PULLDB_AWS_PROFILE` is set correctly

### Error: Access Denied (Secrets Manager)

**Symptom**: `AccessDeniedException when calling the GetSecretValue operation`

**For Service Installation**:
1. Check Secrets Manager policy is attached to role
2. Verify secret exists: `aws secretsmanager describe-secret --secret-id /pulldb/mysql/api`

**For Developer Environment**:
1. Verify `pr-dev` profile has Secrets Manager access
2. Check `PULLDB_AWS_PROFILE=pr-dev` is set
3. Ensure secret is in development account (345321506926)

### Error: Unable to Locate Credentials

**Symptom**: `Unable to locate credentials`

**For Service Installation**:
1. Instance profile not attached - run Step A.3.4
2. IMDSv2 required - use TOKEN-based metadata requests

**For Developer Environment**:
1. Check `~/.aws/credentials` exists and has correct profile
2. For SSO: run `aws sso login --profile pr-dev`
3. Verify profile name matches `PULLDB_AWS_PROFILE`

### Error: Profile Not Found

**Symptom**: `ProfileNotFound: The config profile (pr-dev) could not be found`

**Solution**:
1. Create the profile in `~/.aws/credentials` and `~/.aws/config`
2. Or use SSO: `aws configure sso --profile pr-dev`

---

## Security Best Practices

### For Service Installations

- ✅ Use EC2 instance profiles (no stored credentials)
- ✅ IAM policies scoped to specific resources (`/pulldb/mysql/*`)
- ✅ Read-only S3 access with explicit Deny for writes
- ✅ External ID required for cross-account access
- ✅ KMS decrypt limited to specific AWS services

### For Developer Environments

- ✅ Use IAM users with minimal permissions or SSO
- ✅ Never commit AWS credentials to source control
- ✅ Use named profiles instead of default credentials
- ✅ Rotate access keys regularly
- ✅ Use `aws-vault` or similar for credential encryption

---

## Quick Reference Commands

### Service Installation

```bash
# Verify instance profile
aws sts get-caller-identity

# List staging backups
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head

# Get coordination DB secret
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/api

# Check service status
sudo systemctl status pulldb-worker

# View service logs
sudo journalctl -u pulldb-worker -f
```

### Developer Environment

```bash
# Verify profile
aws sts get-caller-identity --profile pr-dev

# List staging backups (with profile)
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ --profile pr-staging | head

# Get secret (with profile)
aws secretsmanager get-secret-value \
    --secret-id /pulldb/mysql/api \
    --profile pr-dev

# Run tests
PULLDB_AWS_PROFILE=pr-dev pytest

# Run specific integration test
pytest tests/integration/test_secrets.py -v
```

---

**Last Updated**: December 2025
**Maintained By**: PestRoutes Infrastructure Team

**Architecture Change**: pullDB now uses service-specific MySQL users (`pulldb_api`, `pulldb_worker`, `pulldb_loader`) 
instead of a single shared user. See `docs/mysql-schema.md` for grant details.
