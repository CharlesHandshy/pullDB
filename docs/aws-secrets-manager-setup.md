# AWS Secrets Manager Setup for pullDB

> STATUS: ACTIVE (Implementation Guide)
> Canonical Authentication Reference: See `aws-authentication-setup.md` for the authoritative end-to-end AWS architecture (accounts, roles, instance profile, cross-account access). This file focuses narrowly on MySQL credential storage and retrieval mechanics. If guidance here conflicts with `aws-authentication-setup.md`, the canonical document wins.
> Scope Reduction (2025-11-01): Architecture diagrams, cross-account role creation, and instance profile steps were consolidated into `aws-authentication-setup.md` to eliminate duplication. Future updates should only extend credential patterns (rotation, schema integration, testing mandate).

> **Purpose**: Configure AWS Secrets Manager access for pullDB to retrieve MySQL credentials for the local sandbox (`db-local-dev`) and the coordination database secret `/pulldb/mysql/coordination-db` used by all tests.

## Overview

pullDB stores MySQL credentials for target database servers in the `db_hosts` table with references to AWS Secrets Manager or SSM Parameter Store. The `credential_ref` field contains paths like:
- `aws-secretsmanager:/pulldb/mysql/localhost-test`

### Secret Structure (IMPORTANT)

**Secrets Manager secrets for `/pulldb/mysql/*` contain only:**
- `host`: MySQL server hostname or endpoint
- `password`: MySQL password

**Other connection parameters come from environment variables (`.env` file):**
- `PULLDB_MYSQL_USER`: MySQL username (required)
- `PULLDB_MYSQL_PORT`: MySQL port (optional, defaults to 3306)
- `PULLDB_MYSQL_DATABASE`: Database name (optional)

This separation ensures sensitive credentials (host + password) are stored securely in AWS, while non-sensitive configuration (username, port) remains in the deployment environment.

When connecting to a target database server, pullDB:
1. Reads the `credential_ref` from the `db_hosts` table
2. Determines the credential type (Secrets Manager or SSM Parameter Store)
3. Retrieves `host` and `password` from AWS
4. Reads `username`, `port` from environment variables
5. Connects to the target MySQL server using the combined credentials

## Secrets Manager vs SSM Parameter Store

**AWS Secrets Manager** (Recommended for MySQL credentials):
- Built specifically for secrets (passwords, API keys, database credentials)
- Automatic credential rotation with Lambda integrations
- Versioning with staging labels (AWSCURRENT, AWSPREVIOUS)
- Direct RDS integration for automatic rotation
- Higher cost: $0.40/secret/month + $0.05 per 10,000 API calls

**SSM Parameter Store** (Alternative):
- General purpose configuration storage
- SecureString type provides encryption at rest
- Manual rotation required
- Lower cost: Free tier for standard parameters, $0.05/parameter/month for advanced
- Higher API call costs: $0.05 per 10,000 API calls

**pullDB Strategy**: Use Secrets Manager for MySQL credentials (supports RDS auto-rotation), use SSM Parameter Store for non-secret configuration values.

## Architecture Context

```
┌────────────────────────────────────────────────────────────┐
│ Development Account (345321506926)                          │
│                                                              │
│ ┌──────────────────────────────────────────────────────────┤
│ │ EC2 Instance: pulldb-dev-01                              │
│ │                                                            │
│ │ ┌────────────────┐  ┌────────────────┐                   │
│ │ │  API Service   │  │ Worker Service │                   │
│ │ │ (Read db_hosts)│  │ (Restore DBs)  │                   │
│ │ └────────┬───────┘  └────────┬───────┘                   │
│ │          │                   │                            │
│ │          └───────────┬───────┘                            │
│ │                      │                                    │
│ │         ┌────────────▼──────────────────┐                │
│ │         │ EC2 Instance Profile          │                │
│ │         │ pulldb-ec2-service-role       │                │
│ │         └────────────┬──────────────────┘                │
│ └──────────────────────┼───────────────────────────────────┤
│                        │                                    │
│         ┌──────────────▼──────────────────┐                │
│         │ AWS Secrets Manager             │                │
│         │ /pulldb/mysql/localhost-test    │                │
│         └─────────────────────────────────┘                │
│                                                              │
│         ┌─────────────────────────────────┐                │
│         │ MySQL Coordination DB           │                │
│         │ Table: db_hosts                 │                │
│         │ - hostname                      │                │
│         │ - credential_ref ───────────────┼─► Points to    │
│         │   "aws-secretsmanager:/..."     │   Secrets Mgr  │
│         └─────────────────────────────────┘                │
│                                                              │
│         ┌─────────────────────────────────┐                │
│         │ Target MySQL Servers            │                │
│         │ - localhost (local sandbox)     │                │
│         └─────────────────────────────────┘                │
└────────────────────────────────────────────────────────────┘
```

## Step 1: Create Secrets in AWS Secrets Manager

> Use profile names standardized in `aws-authentication-setup.md`: `pr-dev` for development account Secrets Manager work, `pr-staging` for staging-bucket access, and `pr-prod` for production-bucket access. When running directly on the EC2 host you can omit `AWS_PROFILE` entirely and rely on the instance profile (preferred).

### 1.1 Create Secret for localhost-test (Local Sandbox)

```bash
# Local sandbox secret used by default in development environments
# NOTE: Only host and password are stored in Secrets Manager
# username, port, and database come from environment variables
aws secretsmanager create-secret \
    --name /pulldb/mysql/localhost-test \
    --description "MySQL credentials for local sandbox restore target (host + password only)" \
    --secret-string '{
        "password": "REPLACE_WITH_ACTUAL_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development Key=Purpose,Value=local-sandbox

aws secretsmanager describe-secret --secret-id /pulldb/mysql/localhost-test
```



### 1.5 Create Secret for Coordination Database (MANDATORY FOR TESTS)

```bash
# Create secret for pullDB's own coordination MySQL database
# NOTE: Only host and password are stored in Secrets Manager
# username, port, and database come from environment variables
aws secretsmanager create-secret \
    --name /pulldb/mysql/coordination-db \
    --description "MySQL credentials for pullDB coordination database (host + password only)" \
    --secret-string '{
        "password": "REPLACE_WITH_ACTUAL_PASSWORD",
        "host": "pulldb-coordination-db.cluster-xxxxx.us-east-1.rds.amazonaws.com"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development Key=Purpose,Value=coordination

aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db
```

**Required environment variables for coordination database access:**
```bash
# Add to .env file or systemd environment
PULLDB_MYSQL_USER=pulldb_app
PULLDB_MYSQL_PORT=3306
PULLDB_MYSQL_DATABASE=pulldb
```

## Step 2: Update IAM Policy for Secrets Manager Access

> IAM role and instance profile creation details live in `aws-authentication-setup.md`. Only the incremental Secrets Manager permissions are documented here.

### 2.1 Create Secrets Manager Policy

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

# Create the policy
aws iam create-policy \
    --policy-name pulldb-secrets-manager-access \
    --policy-document file:///tmp/pulldb-secrets-manager-policy.json \
    --description "Allows pullDB to retrieve MySQL credentials from Secrets Manager"

# Attach policy to EC2 service role
aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access

# Verify attachment
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

### 2.2 Alternative: Update Existing Cross-Account Policy

If you want to add Secrets Manager permissions to an existing policy instead of creating a new one:

```bash
# Get current policy version
POLICY_ARN="arn:aws:iam::345321506926:policy/pulldb-cross-account-assume-role"
VERSION_ID=$(aws iam get-policy --policy-arn $POLICY_ARN --query 'Policy.DefaultVersionId' --output text)

# Get current policy document
aws iam get-policy-version \
    --policy-arn $POLICY_ARN \
    --version-id $VERSION_ID \
    --query 'PolicyVersion.Document' > /tmp/current-policy.json

# Edit /tmp/current-policy.json to add Secrets Manager statements
# Then create new policy version
aws iam create-policy-version \
    --policy-arn $POLICY_ARN \
    --policy-document file:///tmp/updated-policy.json \
    --set-as-default
```

## Step 3: Configure Automatic Secret Rotation (Optional but Recommended)

### 3.1 Enable RDS Automatic Rotation for localhost-test

```bash
# Create rotation Lambda function (AWS managed)
aws secretsmanager rotate-secret \
    --secret-id /pulldb/mysql/localhost-test \
    --rotation-lambda-arn arn:aws:serverlessrepo:us-east-1:297356227924:applications/SecretsManagerRDSMySQLRotationSingleUser \
    --rotation-rules AutomaticallyAfterDays=90

# Verify rotation is enabled
aws secretsmanager describe-secret --secret-id /pulldb/mysql/localhost-test \
    --query 'RotationEnabled'
```

### 3.2 Enable Rotation for Other Secrets

```bash
# coordination-db
aws secretsmanager rotate-secret \
    --secret-id /pulldb/mysql/coordination-db \
    --rotation-lambda-arn arn:aws:serverlessrepo:us-east-1:297356227924:applications/SecretsManagerRDSMySQLRotationSingleUser \
    --rotation-rules AutomaticallyAfterDays=90
```

## Step 4: Create db_hosts Table with Secrets Manager References

Since this is a new project, create the `db_hosts` table with the `credential_ref` column from the start.

### 4.1 Table Definition with credential_ref Column

When creating the pullDB schema, use this `db_hosts` table definition:

```sql
CREATE TABLE db_hosts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    credential_ref VARCHAR(512) NOT NULL,
    max_concurrent_restores INT NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
```

**Column Descriptions**:
- `hostname`: Fully qualified domain name of the target MySQL server
- `credential_ref`: Reference to AWS Secrets Manager or SSM Parameter Store
  - Secrets Manager format: `aws-secretsmanager:/pulldb/mysql/localhost-test` (recommended)
  - SSM Parameter Store format: `aws-ssm:/pulldb/mysql/localhost-test-credentials` (alternative)
- `max_concurrent_restores`: Maximum simultaneous restore operations on this host
- `enabled`: Boolean flag to enable/disable host without deleting record

### 4.2 Initial Data Population with Secrets Manager References

After creating the table, populate it with the target database servers:

```sql
-- Connect to pulldb coordination database
mysql -u pulldb_app -p pulldb

-- Insert db_hosts with Secrets Manager credential references
INSERT INTO db_hosts (hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('localhost',
     'aws-secretsmanager:/pulldb/mysql/localhost-test',
     1,
     TRUE);

-- Verify records were inserted
SELECT id, hostname, credential_ref, enabled FROM db_hosts;

-- Expected output:
-- +----+------------------------------------------------------------------------------+----------------------------------------+--------+
-- | id | hostname                                                                     | credential_ref                         | enabled|
-- +----+------------------------------------------------------------------------------+----------------------------------------+--------+
-- |  1 | localhost                                                                    | aws-secretsmanager:/pulldb/mysql/localhost-test |      1 |
-- +----+------------------------------------------------------------------------------+----------------------------------------+--------+
```

**Important**: These credential references must match the secret names created in Step 1. The Worker service will resolve these references at runtime to retrieve the actual MySQL credentials.

## Step 5: Implement Credential Resolution in Python

### 5.1 Create Secrets Manager Client Utility

```python
# pulldb/infra/secrets.py
"""AWS Secrets Manager credential resolution."""

import json
from typing import Dict, Any

import boto3
from botocore.exceptions import ClientError


class CredentialResolver:
    """Resolves credential references from AWS Secrets Manager or SSM Parameter Store."""

    def __init__(self, aws_profile: str = None):
        """Initialize credential resolver.

        Args:
            aws_profile: AWS profile name for boto3 session (optional)
        """
        session = boto3.Session(profile_name=aws_profile) if aws_profile else boto3.Session()
        self.secretsmanager = session.client('secretsmanager')
        self.ssm = session.client('ssm')

    def resolve(self, credential_ref: str) -> Dict[str, Any]:
        """Resolve credential reference to actual credential values.

        Args:
            credential_ref: Reference string in format:
                - "aws-secretsmanager:/pulldb/mysql/localhost-test"
                - "aws-ssm:/pulldb/mysql/localhost-test-credentials"

        Returns:
            Dictionary with credential fields:
                - username: MySQL username
                - password: MySQL password
                - host: MySQL hostname
                - port: MySQL port (default 3306)
                - database: Database name (optional)

        Raises:
            ValueError: If credential_ref format is invalid
            ClientError: If AWS API call fails
        """
        if credential_ref.startswith('aws-secretsmanager:'):
            secret_name = credential_ref.replace('aws-secretsmanager:', '')
            return self._get_from_secrets_manager(secret_name)
        elif credential_ref.startswith('aws-ssm:'):
            parameter_name = credential_ref.replace('aws-ssm:', '')
            return self._get_from_parameter_store(parameter_name)
        else:
            raise ValueError(
                f"Invalid credential reference format: {credential_ref}. "
                f"Must start with 'aws-secretsmanager:' or 'aws-ssm:'"
            )

    def _get_from_secrets_manager(self, secret_name: str) -> Dict[str, Any]:
        """Retrieve secret from AWS Secrets Manager.

        Args:
            secret_name: Name of the secret (e.g., /pulldb/mysql/localhost-test)

        Returns:
            Parsed secret as dictionary

        Raises:
            ClientError: If secret not found or access denied
        """
        try:
            response = self.secretsmanager.get_secret_value(SecretId=secret_name)
            secret_string = response['SecretString']
            return json.loads(secret_string)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                raise ValueError(f"Secret not found: {secret_name}") from e
            elif error_code == 'AccessDeniedException':
                raise PermissionError(f"Access denied to secret: {secret_name}") from e
            else:
                raise

    def _get_from_parameter_store(self, parameter_name: str) -> Dict[str, Any]:
        """Retrieve parameter from AWS SSM Parameter Store.

        Args:
            parameter_name: Name of the parameter (e.g., /pulldb/mysql/localhost-test-credentials)

        Returns:
            Parsed parameter value as dictionary

        Raises:
            ClientError: If parameter not found or access denied
        """
        try:
            response = self.ssm.get_parameter(Name=parameter_name, WithDecryption=True)
            parameter_value = response['Parameter']['Value']
            return json.loads(parameter_value)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ParameterNotFound':
                raise ValueError(f"Parameter not found: {parameter_name}") from e
            elif error_code == 'AccessDeniedException':
                raise PermissionError(f"Access denied to parameter: {parameter_name}") from e
            else:
                raise
```

### 5.2 Integrate with MySQL Connection Pool

```python
# pulldb/infra/mysql.py
"""MySQL connection pool with credential resolution."""

import mysql.connector
from mysql.connector import pooling

from pulldb.infra.secrets import CredentialResolver


class MySQLConnectionPool:
    """Connection pool for MySQL databases with AWS credential resolution."""

    def __init__(self, credential_ref: str, pool_size: int = 5, aws_profile: str = None):
        """Initialize connection pool.

        Args:
            credential_ref: AWS Secrets Manager or SSM Parameter Store reference
            pool_size: Number of connections in pool
            aws_profile: AWS profile for credential resolution
        """
        # Resolve credentials from AWS
        resolver = CredentialResolver(aws_profile=aws_profile)
        creds = resolver.resolve(credential_ref)

        # Create connection pool
        self.pool = pooling.MySQLConnectionPool(
            pool_name=f"pulldb_{creds['host']}",
            pool_size=pool_size,
            host=creds['host'],
            port=creds.get('port', 3306),
            user=creds['username'],
            password=creds['password'],
            database=creds.get('database'),
        )

    def get_connection(self):
        """Get connection from pool."""
        return self.pool.get_connection()
```

## Step 6: Verification

### 6.1 Test Secrets Manager Access from EC2

```bash
# SSH to pulldb EC2 instance
ssh ec2-user@pulldb-dev-01

# Switch to pulldb service user
sudo -u pulldb bash

# Test retrieving secret
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/localhost-test

# Should return JSON with SecretString containing credentials (host + password only)
# {
#   "ARN": "arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/localhost-test-xxxxx",
#   "Name": "/pulldb/mysql/localhost-test",
#   "VersionId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
#   "SecretString": "{\"password\":\"...\",\"host\":\"...\"}",
#   "CreatedDate": "2025-10-31T12:00:00.000Z"
# }
# NOTE: username, port, and database come from PULLDB_MYSQL_* env vars

# Test coordination database secret
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db

# Exit pulldb user shell
exit
```

### 6.2 Test Python Credential Resolution

```python
# Test from Python on EC2 instance
sudo -u pulldb bash
cd /opt/pulldb
source venv/bin/activate

# Ensure environment variables are set
export PULLDB_MYSQL_USER=pulldb_app
export PULLDB_MYSQL_PORT=3306

python3 << 'EOF'
from pulldb.infra.secrets import CredentialResolver

# Test resolving Secrets Manager reference
resolver = CredentialResolver()

# Test localhost-test credentials
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/localhost-test')
print(f"✅ localhost-test credentials resolved:")
print(f"   Username: {creds.username}")  # From PULLDB_MYSQL_USER env var
print(f"   Host: {creds.host}")
print(f"   Port: {creds.get('port', 3306)}")

print("\n✅ All Secrets Manager credential resolutions successful!")
EOF

### 6.4 Profile Usage Clarification

Secret creation and retrieval for paths under `/pulldb/mysql/*` occur in the **development account (345321506926)**. Cross-account profiles `pr-staging` and `pr-prod` are for accessing backup objects in staging/production S3 buckets—do not use them to create or update development secrets. If you previously used a legacy profile name like `dev-pulldb` and secret access stopped working:

1. Confirm you are either on the EC2 instance (instance profile) or using a valid dev admin profile (e.g. `dev-admin`).
2. Avoid setting `AWS_PROFILE=pr-staging` for secret CRUD; this may attempt role assumption into staging instead of the dev account.
3. Re-run:
```bash
unset AWS_PROFILE  # if on EC2
aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db --region us-east-1 --query 'ARN'
```
4. If AccessDenied persists, verify the `pulldb-secrets-manager-access` policy is attached to `pulldb-ec2-service-role` (see Step 2) and that the secret resides in the dev account (expected ARN account id matches 345321506926).

Temporary overrides for tests (`PULLDB_TEST_MYSQL_HOST` etc.) should only be used when this secret retrieval is blocked during initial IAM propagation—not as a long-term solution.
```

### 6.3 Test MySQL Connection with Resolved Credentials

```python
sudo -u pulldb bash
cd /opt/pulldb
source venv/bin/activate

python3 << 'EOF'
from pulldb.infra.mysql import MySQLConnectionPool

# Test connection to localhost-test using Secrets Manager credentials
pool = MySQLConnectionPool(
    credential_ref='aws-secretsmanager:/pulldb/mysql/localhost-test',
    pool_size=2
)

# Get connection and test query
conn = pool.get_connection()
cursor = conn.cursor()
cursor.execute("SELECT VERSION(), DATABASE(), USER()")
result = cursor.fetchone()
print(f"✅ Connected to localhost-test:")
print(f"   MySQL Version: {result[0]}")
print(f"   Database: {result[1]}")
print(f"   User: {result[2]}")

cursor.close()
conn.close()

print("\n✅ MySQL connection with Secrets Manager credentials successful!")
EOF
```

## Security Best Practices

### 1. Least Privilege Access
- IAM policy scoped to `/pulldb/mysql/*` secrets only
- No `secretsmanager:*` wildcard permissions
- Read-only access (GetSecretValue, DescribeSecret)
- No PutSecretValue, DeleteSecret, or UpdateSecret permissions

### 2. Resource-Based Policies
- Tag secrets with `Service=pulldb` for filtering
- Use resource tags in IAM Condition clauses
- Prevent unauthorized secret enumeration

### 3. Encryption at Rest
- All secrets encrypted with AWS KMS
- KMS decrypt permission scoped to `secretsmanager.us-east-1.amazonaws.com` service
- Use customer-managed KMS keys for additional control (optional)

### 4. Automatic Rotation
- Enable 90-day rotation for RDS MySQL secrets
- Use AWS-managed Lambda rotation functions
- Test rotation with non-production secrets first

### 5. Audit Trail
- CloudTrail logs all GetSecretValue API calls
- CloudWatch alarms for unauthorized access attempts
- Regular reviews of IAM policy and secret access patterns

### 6. Secret Versioning
- Secrets Manager maintains version history
- Use version stages (AWSCURRENT, AWSPREVIOUS) for rollback
- Test new credentials before promoting to AWSCURRENT

## Troubleshooting

### Error: Access Denied when retrieving secret

**Symptom**: `An error occurred (AccessDeniedException) when calling the GetSecretValue operation`

**Causes**:
1. IAM policy not attached to EC2 role
2. Secret ARN doesn't match IAM policy resource pattern
3. KMS key policy doesn't allow decrypt

**Fix**:
```bash
# Verify IAM policy is attached
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role

# Verify secret ARN matches policy
aws secretsmanager describe-secret --secret-id /pulldb/mysql/localhost-test \
    --query 'ARN'

# Check KMS key permissions (if using customer-managed key)
KEY_ID=$(aws secretsmanager describe-secret --secret-id /pulldb/mysql/localhost-test \
    --query 'KmsKeyId' --output text)
aws kms get-key-policy --key-id $KEY_ID --policy-name default
```

### Error: ResourceNotFoundException

**Symptom**: `An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation`

**Cause**: Secret doesn't exist or wrong secret name

**Fix**:
```bash
# List all secrets with pulldb prefix
aws secretsmanager list-secrets \
    --filters Key=name,Values=/pulldb/

# Verify exact secret name
aws secretsmanager describe-secret --secret-id /pulldb/mysql/localhost-test
```

### Error: Invalid JSON in secret value

**Symptom**: `json.decoder.JSONDecodeError: Expecting value`

**Cause**: Secret value is not valid JSON

**Fix**:
```bash
# View secret value
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/localhost-test \
    --query 'SecretString' --output text

# Update secret with valid JSON (host + password only)
aws secretsmanager put-secret-value \
    --secret-id /pulldb/mysql/localhost-test \
    --secret-string '{
        "password": "password_here",
        "host": "localhost"
    }'
# NOTE: username and port come from PULLDB_MYSQL_USER and PULLDB_MYSQL_PORT env vars
```

## Cost Optimization

### Secrets Manager Costs

**Current Setup** (2 secrets):
- 2 secrets × $0.40/month = $0.80/month
- API calls: ~10,000/month × $0.05/10k = $0.05/month
- **Total**: ~$0.85/month

**Cost Reduction Options**:
1. **Use SSM Parameter Store for non-rotating secrets**: $0/month (free tier)
2. **Reduce API calls**: Cache credentials in application memory (1 hour TTL)
3. **Consolidate secrets**: Store multiple database credentials in one secret (not recommended - reduces granularity)

### Recommended Approach
Keep using Secrets Manager for all MySQL credentials due to:
- RDS automatic rotation integration
- Better security audit trail
- Credential versioning with rollback
- Cost is minimal (~$2/month) compared to benefits

## Monitoring

### CloudWatch Metrics

```bash
# Create CloudWatch alarm for unauthorized access attempts
aws cloudwatch put-metric-alarm \
    --alarm-name pulldb-secrets-access-denied \
    --alarm-description "Alert on Secrets Manager access denied errors" \
    --metric-name UserErrorCount \
    --namespace AWS/SecretsManager \
    --statistic Sum \
    --period 300 \
    --evaluation-periods 1 \
    --threshold 5 \
    --comparison-operator GreaterThanThreshold \
    --treat-missing-data notBreaching
```

### CloudTrail Event Queries

```bash
# Query recent GetSecretValue calls
aws cloudtrail lookup-events \
    --lookup-attributes AttributeKey=EventName,AttributeValue=GetSecretValue \
    --max-results 50

# Filter by secret name
aws cloudtrail lookup-events \
    --lookup-attributes AttributeKey=ResourceName,AttributeValue=/pulldb/mysql/localhost-test \
    --max-results 50
```

## Related Documentation

- `aws-authentication-setup.md` (Canonical AWS authentication & cross-account access)
- `parameter-store-setup.md` (Optional non-secret config pattern; not for MySQL credentials in tests)
- `mysql-schema.md` (Complete db_hosts table structure and coordination DB schema)
- `design/two-service-architecture.md` (API/Worker separation context)
- `SECRETS-MANAGER-SUMMARY.md` (High-level recap; superseded for detailed steps by this file)

## Summary

This Secrets Manager setup provides:
- ✅ Secure storage of MySQL credentials with encryption at rest
- ✅ Automatic credential rotation with RDS integration
- ✅ IAM-based access control scoped to pullDB secrets only
- ✅ Complete audit trail via CloudTrail
- ✅ Version history with rollback capability
- ✅ KMS encryption with service-scoped decrypt permissions
- ✅ Python integration for credential resolution
- ✅ Connection pooling with transparent credential retrieval

**Setup Order for New Projects**:
1. Create AWS Secrets Manager secrets (Step 1)
2. Create IAM policy and attach to EC2 role (Step 2)
3. Create pullDB database and db_hosts table with `credential_ref` column (Step 4.1)
4. Populate db_hosts with Secrets Manager references (Step 4.2)
5. Configure automatic rotation (Step 3, optional)
6. Implement Python credential resolution code (Step 5)
7. Verify connectivity (Step 6)

Both API and Worker services retrieve credentials from Secrets Manager when connecting to:
- Target MySQL servers (localhost-test) for restore operations
- Coordination database for job queue management
