# AWS Secrets Manager Integration Summary

> **Status**: Documentation added, implementation pending

## What We Added

### 1. New Documentation File
**File**: `docs/aws-secrets-manager-setup.md`

Complete guide covering:
- ✅ Secrets Manager vs SSM Parameter Store comparison
- ✅ Step-by-step secret creation for all sandbox + database servers (db-local-dev, db3-dev, db4-dev, db5-dev, coordination-db)
- ✅ IAM policy for Secrets Manager access (scoped to `/pulldb/mysql/*`)
- ✅ Automatic credential rotation setup (90-day rotation with RDS Lambda)
- ✅ Database host table updates (`db_hosts.credential_ref` configuration)
- ✅ Python implementation examples (CredentialResolver class, MySQLConnectionPool)
- ✅ Verification procedures (AWS CLI tests, Python tests, MySQL connection tests)
- ✅ Security best practices (least privilege, encryption, audit trail)
- ✅ Troubleshooting guide (common errors and fixes)
- ✅ Cost optimization (~$2.00/month for 5 secrets)
- ✅ Monitoring with CloudWatch alarms

### 2. Updated Existing Documentation
**File**: `docs/aws-authentication-setup.md`

Added Secrets Manager permissions to the IAM policy workflow:
- ✅ New section 1.2: "Add Secrets Manager Access Policy"
- ✅ Updated section numbering (1.3, 1.4, 1.5 instead of 1.2, 1.3, 1.4)
- ✅ Updated permission matrix table to include `secretsmanager:GetSecretValue`
- ✅ Updated KMS decrypt to note both S3 and Secrets Manager usage
- ✅ Updated Related Documentation section to prioritize Secrets Manager over Parameter Store
- ✅ Updated Summary to highlight Secrets Manager integration

## IAM Policy Addition

The new policy grants pullDB services:

```json
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
```

**Key Security Features**:
- ✅ Scoped to `/pulldb/mysql/*` secrets only (no wildcard access)
- ✅ Read-only permissions (GetSecretValue, DescribeSecret only)
- ✅ ListSecrets filtered by `Service=pulldb` tag
- ✅ KMS decrypt scoped to Secrets Manager service only
- ✅ No write permissions (PutSecretValue, DeleteSecret denied)

## Secrets to Create

pullDB requires 5 secrets in AWS Secrets Manager:

| Secret Name | Purpose | Team | Rotation |
|-------------|---------|------|----------|
| `/pulldb/mysql/localhost-test` | Local sandbox restore target | Development | 90 days |
| `/pulldb/mysql/db3-dev` | Target database server credentials | DEV | 90 days |
| `/pulldb/mysql/db4-dev` | Target database server credentials | SUPPORT | 90 days |
| `/pulldb/mysql/db5-dev` | Target database server credentials | IMPLEMENTATION | 90 days |
| `/pulldb/mysql/coordination-db` | pullDB coordination database | N/A | 90 days |

**Secret Format** (JSON):
```json
{
  "username": "pulldb_app",
  "password": "ACTUAL_PASSWORD_HERE",
  "host": "db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com",
  "port": 3306,
  "dbClusterIdentifier": "db-mysql-db3-dev-vpc-us-east-1-aurora"
}
```

  The local sandbox secret (`/pulldb/mysql/localhost-test`) uses the same structure but sets `host` to `localhost` and may omit the cluster identifier in favor of a `database` field when pointing at a standalone instance.

## Implementation Tasks

### Immediate (AWS Setup)
- [ ] Create IAM policy `pulldb-secrets-manager-access` in development account (345321506926)
- [ ] Attach policy to `pulldb-ec2-service-role`
- [ ] Create 5 secrets in Secrets Manager with actual credentials
- [ ] Enable automatic rotation (90 days) for all secrets
- [ ] Tag all secrets with `Service=pulldb`

### Near-Term (Database Configuration)
- [ ] Update `db_hosts` table with Secrets Manager credential references:
  ```sql
  UPDATE db_hosts
  SET credential_ref = 'aws-secretsmanager:/pulldb/mysql/db3-dev'
  WHERE hostname = 'db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com';
  ```
- [ ] Repeat for localhost (db-local-dev), db4-dev, and db5-dev

### Code Implementation (Milestone 1.3 - Configuration Module)
- [ ] Implement `pulldb/infra/secrets.py` with `CredentialResolver` class
- [ ] Integrate with `pulldb/infra/mysql.py` for connection pooling
- [ ] Add unit tests for credential resolution (mocked Secrets Manager)
- [ ] Add integration tests with actual Secrets Manager (dev environment)
- [ ] Update configuration module to use Secrets Manager for coordination database

## Verification Steps

### 1. Test IAM Permissions (from EC2 instance)
```bash
sudo -u pulldb bash
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/db3-dev
# Should return secret value (not "Access Denied")
```

### 2. Test Python Credential Resolution
```python
from pulldb.infra.secrets import CredentialResolver

resolver = CredentialResolver()
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/db3-dev')
print(f"Username: {creds['username']}, Host: {creds['host']}")
```

### 3. Test MySQL Connection
```python
from pulldb.infra.mysql import MySQLConnectionPool

pool = MySQLConnectionPool(
    credential_ref='aws-secretsmanager:/pulldb/mysql/db3-dev',
    pool_size=2
)
conn = pool.get_connection()
cursor = conn.cursor()
cursor.execute("SELECT VERSION()")
print(cursor.fetchone())
```

## Why Secrets Manager Over Parameter Store?

| Feature | Secrets Manager | SSM Parameter Store |
|---------|----------------|---------------------|
| **Automatic Rotation** | ✅ Built-in with Lambda | ❌ Manual only |
| **RDS Integration** | ✅ Direct integration | ❌ No integration |
| **Versioning** | ✅ AWSCURRENT/AWSPREVIOUS | ❌ Limited versions |
| **Audit Trail** | ✅ CloudTrail + history | ✅ CloudTrail |
| **Cost** | $2.00/month (5 secrets) | $0 (free tier) |
| **Best For** | Database credentials | Configuration values |

**Decision**: Use Secrets Manager for all MySQL credentials due to automatic rotation and RDS integration. The $1.65/month cost is negligible compared to security benefits.

## Security Benefits

1. **No Hardcoded Credentials**: All passwords stored in AWS Secrets Manager, never in code or config files
2. **Automatic Rotation**: RDS Lambda rotates passwords every 90 days without manual intervention
3. **Least Privilege**: IAM policy scoped to specific secret paths only
4. **Encryption at Rest**: All secrets encrypted with AWS KMS
5. **Audit Trail**: CloudTrail logs every GetSecretValue call
6. **Version Rollback**: Previous secret versions preserved for emergency rollback
7. **Instance Profile**: No long-lived credentials on EC2 instance

## Cost Analysis

**Monthly Costs**:
- 5 secrets × $0.40/secret = $2.00/month
- ~10,000 API calls × $0.05/10k = $0.05/month
- **Total: $1.65/month**

**Alternative (SSM Parameter Store)**:
- 4 parameters × $0 (free tier) = $0/month
- But: No automatic rotation, manual password updates required

**Recommendation**: Accept $1.65/month cost for automatic rotation and RDS integration.

## Related Documentation

- **Primary**: `docs/aws-secrets-manager-setup.md` - Complete setup guide
- **IAM Setup**: `docs/aws-authentication-setup.md` - EC2 instance profile + policies
- **Alternative**: `docs/parameter-store-setup.md` - SSM Parameter Store (for config values)
- **Database Schema**: `docs/mysql-schema.md` - db_hosts table structure
- **Architecture**: `design/two-service-architecture.md` - API/Worker separation

## Next Steps

1. **Review** the new `docs/aws-secrets-manager-setup.md` documentation
2. **Create IAM policy** following Step 2.1 in the Secrets Manager setup guide
3. **Create secrets** following Step 1 in the Secrets Manager setup guide
4. **Update db_hosts table** following Step 4 in the Secrets Manager setup guide
5. **Implement Python code** in Milestone 1.3 (Configuration Module)
6. **Test thoroughly** following Step 6 verification procedures

## Questions?

See the troubleshooting section in `docs/aws-secrets-manager-setup.md` for common issues and solutions.
