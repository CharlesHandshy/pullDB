# AWS Parameter Store Setup for pullDB

This guide covers configuring AWS Systems Manager Parameter Store to securely store MySQL credentials for pullDB.

## Overview

pullDB supports loading sensitive configuration values (like MySQL passwords) from AWS Systems Manager Parameter Store instead of storing them in `.env` files. This provides:

- **Secure Storage**: Credentials encrypted at rest using AWS KMS
- **Access Control**: IAM-based permissions for who can read parameters
- **Audit Trail**: CloudTrail logs all parameter access
- **Centralized Management**: Update credentials in one place
- **No Secrets in Code**: `.env` only contains parameter paths, not actual secrets

## Parameter Store vs Direct Values

### Direct Values (Development)
```bash
# In .env file
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_USER=root
PULLDB_MYSQL_PASSWORD=my_password
```

### Parameter Store References (Production)
```bash
# In .env file
PULLDB_MYSQL_HOST=/pulldb/prod/mysql/host
PULLDB_MYSQL_USER=/pulldb/prod/mysql/user
PULLDB_MYSQL_PASSWORD=/pulldb/prod/mysql/password
```

When pullDB sees a value starting with `/`, it automatically fetches the actual value from AWS Parameter Store.

## Step-by-Step Setup

### Step 1: Create Parameters in AWS

Use AWS CLI to create SecureString parameters:

```bash
# Set your AWS profile
export AWS_PROFILE=pr-prod

# Create parameters (SecureString type encrypts values with KMS)
aws ssm put-parameter \
    --name "/pulldb/prod/mysql/host" \
    --description "MySQL host for pullDB coordination database" \
    --value "pulldb-db.cluster-abc123.us-east-1.rds.amazonaws.com" \
    --type "String"

aws ssm put-parameter \
    --name "/pulldb/prod/mysql/user" \
    --description "MySQL user for pullDB coordination database" \
    --value "pulldb_app" \
    --type "String"

aws ssm put-parameter \
    --name "/pulldb/prod/mysql/password" \
    --description "MySQL password for pullDB coordination database" \
    --value "your_secure_password_here" \
    --type "SecureString"

aws ssm put-parameter \
    --name "/pulldb/prod/mysql/database" \
    --description "MySQL database name for pullDB" \
    --value "pulldb" \
    --type "String"
```

**Parameter Naming Convention:**
- Use hierarchical paths: `/pulldb/{environment}/{service}/{parameter}`
- Examples:
  - `/pulldb/prod/mysql/password`
  - `/pulldb/staging/mysql/password`
  - `/pulldb/dev/mysql/password`

### Step 2: Verify Parameters Exist

```bash
# List all pullDB parameters
aws ssm get-parameters-by-path \
    --path "/pulldb/prod/mysql" \
    --with-decryption

# Get a specific parameter
aws ssm get-parameter \
    --name "/pulldb/prod/mysql/password" \
    --with-decryption
```

### Step 3: Configure IAM Permissions

The IAM user/role running pullDB needs permission to read these parameters.

**For detailed IAM setup instructions, see [docs/aws-iam-setup.md](aws-iam-setup.md).**

Quick reference - required permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": [
        "arn:aws:ssm:us-east-1:123456789012:parameter/pulldb/prod/mysql/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ssm.us-east-1.amazonaws.com"
        }
      }
    }
  ]
}
```

**Note:** Replace `123456789012` with your AWS account ID. The KMS permission is required for SecureString parameters.

### Step 4: Update .env File

Edit your `.env` file to use parameter references instead of direct values:

```bash
# ============================================
# MySQL Coordination Database
# ============================================
# Use AWS Parameter Store references (values starting with '/')
PULLDB_MYSQL_HOST=/pulldb/prod/mysql/host
PULLDB_MYSQL_USER=/pulldb/prod/mysql/user
PULLDB_MYSQL_PASSWORD=/pulldb/prod/mysql/password
PULLDB_MYSQL_DATABASE=/pulldb/prod/mysql/database

# ============================================
# AWS Configuration
# ============================================
PULLDB_AWS_PROFILE=pr-prod

# ... rest of configuration
```

### Step 5: Test Configuration Loading

Verify that pullDB can resolve parameters correctly:

```bash
# Activate virtual environment
source venv/bin/activate

# Test configuration loading
python3 << 'EOF'
from pulldb.domain.config import Config

# Load config (will fetch from Parameter Store)
cfg = Config.minimal_from_env()

# Print resolved values (mask password)
print(f"MySQL Host: {cfg.mysql_host}")
print(f"MySQL User: {cfg.mysql_user}")
print(f"MySQL Password: {'*' * len(cfg.mysql_password)}")
print(f"MySQL Database: {cfg.mysql_database}")
EOF
```

**Expected output:**
```
MySQL Host: pulldb-db.cluster-abc123.us-east-1.rds.amazonaws.com
MySQL User: pulldb_app
MySQL Password: **********************
MySQL Database: pulldb
```

## Environment-Specific Configuration

Use different parameter paths for different environments:

### Development (.env)
```bash
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_USER=root
PULLDB_MYSQL_PASSWORD=dev_password
```

### Staging (.env)
```bash
PULLDB_MYSQL_HOST=/pulldb/staging/mysql/host
PULLDB_MYSQL_USER=/pulldb/staging/mysql/user
PULLDB_MYSQL_PASSWORD=/pulldb/staging/mysql/password
```

### Production (.env)
```bash
PULLDB_MYSQL_HOST=/pulldb/prod/mysql/host
PULLDB_MYSQL_USER=/pulldb/prod/mysql/user
PULLDB_MYSQL_PASSWORD=/pulldb/prod/mysql/password
```

## Parameter Updates

To rotate credentials:

```bash
# Update the parameter value
aws ssm put-parameter \
    --name "/pulldb/prod/mysql/password" \
    --value "new_secure_password" \
    --type "SecureString" \
    --overwrite

# Restart pullDB daemon to pick up new value
sudo systemctl restart pulldb-daemon
```

## Security Best Practices

1. **Use SecureString Type**: Always use `--type "SecureString"` for passwords
2. **Least Privilege IAM**: Grant only `ssm:GetParameter` on specific parameter paths
3. **Rotate Regularly**: Update passwords quarterly using parameter overwrites
4. **Audit Access**: Enable CloudTrail logging for parameter access
5. **Separate Environments**: Use different parameter paths for dev/staging/prod
6. **No Wildcards**: Avoid `*` in IAM policies; specify exact parameter paths

## Troubleshooting

### Error: "Failed to resolve AWS Parameter Store reference"

**Cause:** Parameter doesn't exist or IAM permissions insufficient

**Solution:**
```bash
# Verify parameter exists
aws ssm get-parameter --name "/pulldb/prod/mysql/password" --with-decryption

# Check IAM permissions
aws ssm describe-parameters --filters "Key=Name,Values=/pulldb/prod/mysql/password"
```

### Error: "AccessDeniedException: User is not authorized"

**Cause:** IAM user/role lacks `ssm:GetParameter` permission

**Solution:** Add the IAM policy shown in Step 3 to the user/role

### Error: "ParameterNotFound"

**Cause:** Typo in parameter name or parameter deleted

**Solution:** Verify parameter path exactly matches (case-sensitive):
```bash
aws ssm get-parameters-by-path --path "/pulldb/prod/mysql"
```

### Error: "KMS AccessDeniedException"

**Cause:** Missing `kms:Decrypt` permission for SecureString parameters

**Solution:** Add KMS decrypt permission to IAM policy (see Step 3)

## Verification Checklist

Before deploying to production:

- [ ] All parameters created in AWS Parameter Store
- [ ] Parameters use SecureString type for sensitive values
- [ ] IAM policy attached with ssm:GetParameter and kms:Decrypt permissions
- [ ] .env file updated with parameter paths (starting with `/`)
- [ ] Local test confirms parameters resolve correctly
- [ ] CloudTrail logging enabled for audit trail
- [ ] Parameter paths follow naming convention (`/pulldb/{env}/{service}/{param}`)
- [ ] Documentation updated with parameter paths for team reference

## Next Steps

After Parameter Store setup:
1. Review complete IAM permissions: [docs/aws-iam-setup.md](aws-iam-setup.md)
2. Update deployment documentation with parameter paths
3. Configure systemd service with AWS_PROFILE environment variable
4. Test full restore workflow with production credentials
5. Set up credential rotation schedule (quarterly recommended)

See `docs/aws-setup.md` for AWS profile configuration.
