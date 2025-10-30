# AWS CLI & SDK Setup for pullDB

This guide covers installing and configuring the AWS CLI and Python AWS SDK libraries used by pullDB.

## Overview

pullDB interacts with AWS S3 to discover and download production database backups. The prototype requires:
- AWS CLI v2 (for manual inspection/troubleshooting)
- Python `boto3`/`botocore` libraries (daemon S3 operations)
- Optional: environment profile configuration or IAM role

## Quick Start

```bash
# 1. Install AWS CLI v2 (idempotent)
sudo scripts/setup-aws.sh

# 2. (Optional) Configure a named profile
sudo scripts/setup-aws.sh --configure pr-prod us-east-1 json

# 3. Activate virtual environment and install Python AWS libs (already in requirements.txt)
source venv/bin/activate
pip install -r requirements.txt

# 4. Verify installation
aws --version
python -c "import boto3, botocore; print(boto3.__version__, botocore.__version__)"
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

### Prototype
- Use a named profile (`AWS_PROFILE=pr-prod`) or instance IAM role in development.
- Do NOT hardcode credentials. Favor environment variables or AWS role-based access.

### Recommended Production Approach
- Assign IAM role to daemon EC2 instance with least-privilege S3 access:
  - `s3:ListBucket` for backup bucket
  - `s3:GetObject` for backup object keys
- Deny write/delete privileges explicitly

### Environment Variables (if needed)
```
export AWS_PROFILE=pr-prod
export AWS_REGION=us-east-1
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
1. Run MySQL setup scripts (if not done)
2. Implement downloader module (`pulldb/daemon/downloader.py`)
3. Add unit tests mocking S3 via `moto`

See `IMPLEMENTATION-PLAN.md` for roadmap alignment.
