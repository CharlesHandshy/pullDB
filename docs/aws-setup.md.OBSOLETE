# AWS CLI & SDK Setup for pullDB

This guide covers installing and configuring the AWS CLI and Python AWS SDK libraries used by pullDB.

## Overview

pullDB interacts with AWS S3 to discover and download production database backups. The prototype requires:
- AWS CLI v2 (for manual inspection/troubleshooting)
- Python `boto3`/`botocore` libraries (daemon S3 operations)
- Optional: environment profile configuration or IAM role

## Cross-Account Access

pullDB requires cross-account access to read production backups from S3. Choose the appropriate authentication method:

- **For Local Development**: Follow [AWS Cross-Account Setup (IAM User)](aws-cross-account-setup.md) - uses IAM user with access keys in `~/.aws/credentials`
- **For Production Services** (EC2/ECS/Lambda): Follow [AWS Service Role Setup](aws-service-role-setup.md) - uses instance profiles/task roles with automatic credential rotation (RECOMMENDED)

Both guides include complete setup instructions, trust policies, permission policies, and troubleshooting procedures.

## Quick Start

```bash
# 1. Install AWS CLI v2
sudo scripts/setup-aws.sh

# 2. Set up AWS credentials with .env file
scripts/setup-aws-credentials.sh

# 3. Configure your AWS profile (see Step-by-Step Guide below)
aws configure --profile pr-prod

# 4. Update .env with your profile name
# Edit .env and set: PULLDB_AWS_PROFILE=pr-prod

# 5. Verify setup
scripts/setup-aws-credentials.sh
```

## Step-by-Step AWS Profile Setup

### Prerequisites

Before starting, you need:
1. **AWS Account Access** - Contact your AWS administrator
2. **IAM User Credentials** - Access Key ID and Secret Access Key
3. **S3 Bucket Name** - The production backup bucket path (e.g., `pestroutes-rds-backup-prod-vpc-us-east-1-s3`)

**Required IAM Permissions** for the user/role:

#### S3 Backup Access
- `s3:ListBucket` on `arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3`
- `s3:GetObject` on `arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/*`

#### Parameter Store Access (for MySQL credentials)
- `ssm:GetParameter` on `arn:aws:ssm:us-east-1:*:parameter/pulldb/*/mysql/*`
- `kms:Decrypt` for SecureString parameters

**Complete IAM Policy Example:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3BackupReadAccess",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    },
    {
      "Sid": "S3BackupObjectReadAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/*"
    },
    {
      "Sid": "ParameterStoreReadAccess",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": [
        "arn:aws:ssm:us-east-1:*:parameter/pulldb/prod/mysql/*",
        "arn:aws:ssm:us-east-1:*:parameter/pulldb/staging/mysql/*",
        "arn:aws:ssm:us-east-1:*:parameter/pulldb/dev/mysql/*"
      ]
    },
    {
      "Sid": "KMSDecryptForSecureStrings",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ssm.us-east-1.amazonaws.com"
        }
      }
    }
  ]
}
```

**Note:** Replace `123456789012` with your AWS account ID. For production, restrict KMS resource to specific key ARN.

### Step 1: Install AWS CLI

The AWS CLI v2 is required for profile management and testing:

```bash
# Install AWS CLI (idempotent - safe to run multiple times)
sudo scripts/setup-aws.sh

# Verify installation
aws --version
# Expected output: aws-cli/2.31.x Python/3.x.x Linux/x86_64
```

### Step 2: Create .env Configuration File

pullDB uses a `.env` file for local configuration (gitignored to protect secrets):

```bash
# Run the setup script - it will create .env from template if missing
scripts/setup-aws-credentials.sh
```

This creates a `.env` file from `.env.example` with placeholder values.

### Step 3: Configure AWS Profile

Create a named AWS profile for pullDB to use. This stores credentials in `~/.aws/credentials` and configuration in `~/.aws/config`:

**Prerequisites:** You must have IAM user credentials (Access Key ID and Secret Access Key) from Step 1 above. If you haven't set up IAM permissions yet, see [docs/aws-iam-setup.md](aws-iam-setup.md) first.

```bash
# Configure profile named 'pr-prod' (or your preferred name)
aws configure --profile pr-prod
```

You'll be prompted for:

1. **AWS Access Key ID**: `AKIAIOSFODNN7EXAMPLE` (from IAM user creation)
2. **AWS Secret Access Key**: `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` (from IAM user creation)
3. **Default region name**: `us-east-1` (where your S3 bucket is located)
4. **Default output format**: `json` (recommended for scripting)

**Example interaction:**
```
$ aws configure --profile pr-prod
AWS Access Key ID [None]: AKIAIOSFODNN7EXAMPLE
AWS Secret Access Key [None]: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
Default region name [None]: us-east-1
Default output format [None]: json
```

This creates/updates:
- `~/.aws/credentials` (contains your access keys)
- `~/.aws/config` (contains region and output settings)

### Step 4: Update .env File

Edit the `.env` file to reference your AWS profile:

```bash
# Open .env in your editor
nano .env  # or vim, code, etc.
```

Set the following variables:

```bash
# ============================================
# AWS Configuration
# ============================================
# Use the profile name you configured in Step 3
PULLDB_AWS_PROFILE=pr-prod

# MySQL connection (adjust for your environment)
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_USER=root
PULLDB_MYSQL_PASSWORD=your_password_here
PULLDB_MYSQL_DATABASE=pulldb

# S3 bucket path (usually loaded from MySQL settings table)
PULLDB_S3_BUCKET_PATH=pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod

# Default database host
PULLDB_DEFAULT_DBHOST=db-mysql-db4-dev
```

**Important:** The `.env` file is gitignored and will NOT be committed to version control.

### Step 5: Verify AWS Credentials

Test that your credentials work correctly:

```bash
# Run validation script
scripts/setup-aws-credentials.sh
```

This script will:
1. ✓ Check AWS CLI is installed
2. ✓ Verify .env file exists
3. ✓ Test AWS credentials with `aws sts get-caller-identity`
4. ✓ Test S3 bucket access (list operation)

**Expected successful output:**
```
=== pullDB AWS Credentials Setup ===

✓ AWS CLI found: aws-cli/2.31.26 Python/3.11.8 Linux/6.8.0-48-generic exe/x86_64.ubuntu.22
✓ Found .env file

Using AWS profile: pr-prod

Testing AWS credentials...
✓ AWS credentials valid
{
  "UserId": "AIDAI...",
  "Account": "123456789012",
  "Arn": "arn:aws:iam::123456789012:user/pulldb-user"
}

Testing S3 bucket access...
✓ S3 bucket accessible

=== AWS Setup Complete ===
```

### Step 6: Test Python Integration

Verify that Python can load the credentials from your .env file:

```bash
# Activate virtual environment (if not already active)
source venv/bin/activate

# Test configuration loading
python3 -c "from pulldb.domain.config import Config; cfg = Config.minimal_from_env(); print(f'AWS Profile: {cfg.aws_profile}')"
```

**Expected output:**
```
AWS Profile: pr-prod
```

### Step 7: Test S3 Access from Python

Verify boto3 can use your profile to access S3:

```bash
python3 << 'EOF'
import os
from pulldb.domain.config import Config

# Load config
cfg = Config.minimal_from_env()

# Set profile for boto3
if cfg.aws_profile:
    os.environ['AWS_PROFILE'] = cfg.aws_profile

import boto3

# Test S3 access
s3 = boto3.client('s3')
bucket_name = cfg.s3_bucket_path.split('/')[0]

print(f"Testing access to bucket: {bucket_name}")
response = s3.list_objects_v2(Bucket=bucket_name, Prefix='daily/prod/', MaxKeys=5)

if 'Contents' in response:
    print(f"✓ Successfully listed {len(response['Contents'])} objects")
    for obj in response['Contents'][:3]:
        print(f"  - {obj['Key']}")
else:
    print("✓ Bucket accessible (no objects found with prefix)")
EOF
```

## Security Policy

**pullDB only supports AWS named profiles.** Explicit credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env) are not supported for security reasons:

- Credentials are stored separately in `~/.aws/credentials` with proper file permissions (0600)
- Reduces risk of accidental credential exposure in logs or environment dumps
- Works consistently with AWS CLI and all AWS SDKs
- Follows AWS security best practices
- Easy to rotate credentials without code changes

### Troubleshooting Common Issues

#### Issue: "NoCredentialsError: Unable to locate credentials"

**Cause:** AWS SDK cannot find credentials

**Solution:**
```bash
# Check if profile exists
aws configure list --profile pr-prod

# Verify .env has correct profile name
grep PULLDB_AWS_PROFILE .env

# Test profile directly
AWS_PROFILE=pr-prod aws sts get-caller-identity
```

#### Issue: "An error occurred (InvalidAccessKeyId)"

**Cause:** Access key is incorrect or has been deleted

**Solution:**
1. Verify the access key in AWS IAM console
2. Reconfigure the profile with correct credentials:
   ```bash
   aws configure --profile pr-prod
   ```

#### Issue: "AccessDenied" when accessing S3

**Cause:** IAM user/role lacks required S3 permissions

**Solution:**
1. Contact AWS administrator to verify IAM policy
2. Required policy (see Prerequisites section for complete policy):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
         "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3"
       },
       {
         "Effect": "Allow",
         "Action": ["s3:GetObject", "s3:GetObjectVersion"],
         "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/*"
       }
     ]
   }
   ```

#### Issue: "AccessDenied" when accessing Parameter Store

**Cause:** IAM user/role lacks SSM GetParameter permission

**Solution:**
1. Verify IAM policy includes Parameter Store permissions:
   ```json
   {
     "Effect": "Allow",
     "Action": ["ssm:GetParameter", "ssm:GetParameters"],
     "Resource": "arn:aws:ssm:us-east-1:*:parameter/pulldb/*/mysql/*"
   }
   ```
2. For SecureString parameters, also ensure KMS decrypt permission:
   ```json
   {
     "Effect": "Allow",
     "Action": "kms:Decrypt",
     "Resource": "*",
     "Condition": {
       "StringEquals": {
         "kms:ViaService": "ssm.us-east-1.amazonaws.com"
       }
     }
   }
   ```

#### Issue: ".env file not found"

**Cause:** .env was not created

**Solution:**
```bash
# Create from template
cp .env.example .env

# Edit with your values
nano .env
```

#### Issue: "Profile not found" in boto3

**Cause:** Environment variable not set when Python runs

**Solution:**
```python
# In your Python code, ensure profile is set before importing boto3
import os
os.environ['AWS_PROFILE'] = 'pr-prod'
import boto3
```

Or use the Config class which handles this automatically:
```python
from pulldb.domain.config import Config
cfg = Config.minimal_from_env()
# Profile will be set automatically when needed
```

## Script: `scripts/setup-aws.sh`

### Features
- Installs AWS CLI v2 if not present
- Supports `--force` flag for reinstallation
- Optional profile configuration with `--configure <name> <region> <output>`
- Validates installation and prints a summary
- Safe to run multiple times (idempotent unless `--force` used)

### Usage Examples
```bash
# Basic install
sudo scripts/setup-aws.sh

# Force reinstall
sudo scripts/setup-aws.sh --force

# Install and configure profile 'pr-prod' for us-east-1
sudo scripts/setup-aws.sh --configure pr-prod us-east-1 json
```

### Output Example
```
[INFO] AWS CLI Installed: aws-cli/2.31.x Python/3.13.x Linux/x86_64
[INFO] Verifying basic AWS CLI functionality (no credentials)...
[INFO] STS call failed as expected (no credentials yet). This is normal.
============================================
AWS CLI Setup Complete
============================================
Binary: /usr/local/bin/aws
Version: aws-cli/2.31.x Python/3.13.x Linux/x86_64
Force Reinstall: 0
Profile Configured: 1 (pr-prod)
```

## Python AWS Libraries

Installed via `requirements.txt`:
- `boto3` – High-level AWS SDK
- `botocore` – Low-level API calls and authentication
- `s3transfer` – Efficient S3 multipart transfers

### Minimal S3 Usage Example
```python
import boto3

s3 = boto3.client('s3')
# List objects (requires credentials/profile configured)
resp = s3.list_objects_v2(Bucket='pestroutes-rds-backup-prod-vpc-us-east-1-s3', Prefix='daily/prod/customer123/')
for obj in resp.get('Contents', []):
    print(obj['Key'])
```

## Authentication Strategy

### Development Environment
- **Required**: Use a named AWS profile configured via `aws configure --profile <name>`
- Set `PULLDB_AWS_PROFILE` in `.env` file
- Explicit credentials are NOT supported (security policy)

### Production Environment (Future)
- Assign IAM role to daemon EC2 instance with least-privilege S3 access:
  - `s3:ListBucket` for backup bucket
  - `s3:GetObject` for backup object keys
- Deny write/delete privileges explicitly
- No credentials in .env required (EC2 instance profile provides credentials automatically)

### Environment Variables
```bash
# Development: Profile-based authentication
export PULLDB_AWS_PROFILE=pr-prod

# Production: IAM role (no profile needed)
# AWS SDK automatically uses EC2 instance profile
```

## Manual Installation (Without Script)

```bash
# Download and install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
sudo apt install -y unzip
unzip awscliv2.zip
sudo ./aws/install

# Verify
aws --version

# Configure profile
aws configure --profile pr-prod
# Enter AWS Access Key ID, Secret, region (us-east-1), output (json)
```

## Verification Steps

1. Check version:
   ```bash
   aws --version
   ```
2. List S3 bucket (requires credentials):
   ```bash
   aws s3 ls s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/ | head
   ```
3. Python imports:
   ```bash
   python -c "import boto3, botocore; print(boto3.__version__, botocore.__version__)"
   ```

## Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| `aws: command not found` | Installation failed or PATH not updated | Re-run script with `--force` and check `/usr/local/bin/aws` |
| STS errors | Missing credentials | Configure profile or attach IAM role |
| AccessDenied on S3 | Insufficient IAM permissions | Update role/policy with required actions |
| Profile not applied | Missing `AWS_PROFILE` export | `export AWS_PROFILE=pr-prod` in shell or service unit |
| Python import error | venv not active | `source venv/bin/activate` before running scripts |

## Integration in pullDB

The daemon will:
1. Use `boto3.client('s3')` with default credential provider chain.
2. List latest backup objects under prefix: `daily/prod/<customer_or_qatemplate>/`.
3. Select newest tarball matching pattern.
4. Download and stream to disk with space pre-check.

## Security Notes
- Never commit credentials or `.aws/` directories.
- Use IAM roles where possible (EC2 Instance Profile).
- Rotate any access keys used for development quarterly.
- Principle of least privilege: restrict S3 access to required bucket/prefix.

## Next Steps
After AWS setup:
1. **Cross-Account Access (if needed)**: If dev and prod are in different AWS accounts, complete [Cross-Account Setup Guide](aws-cross-account-setup.md)
2. **Set up IAM permissions**: Complete IAM user/role setup with required policies: [docs/aws-iam-setup.md](aws-iam-setup.md)
3. **(Recommended) Configure AWS Parameter Store** for secure MySQL credentials: [docs/parameter-store-setup.md](parameter-store-setup.md)
4. Run MySQL setup scripts (if not done)
5. Implement downloader module (`pulldb/daemon/downloader.py`)
6. Add unit tests mocking S3 via `moto`

See `IMPLEMENTATION-PLAN.md` for roadmap alignment.
