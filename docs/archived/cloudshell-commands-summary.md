# pullDB AWS CloudShell Commands by Account

## �� Development Account (345321506926) CloudShell

### Step 1: Create EC2 Trust Policy and Role

```bash
# Create trust policy
cat > /tmp/pulldb-ec2-trust-policy.json <<'POLICY'
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
POLICY

# Create role
aws iam create-role \
    --role-name pulldb-ec2-service-role \
    --assume-role-policy-document file:///tmp/pulldb-ec2-trust-policy.json \
    --description "EC2 service role for pullDB API and Worker services" \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development

# Verify
aws iam get-role --role-name pulldb-ec2-service-role
```

### Step 2: Create and Attach Secrets Manager Policy

```bash
# Create policy document
cat > /tmp/pulldb-secrets-manager-policy.json <<'POLICY'
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
      "Action": ["secretsmanager:ListSecrets"],
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
POLICY

# Create policy
aws iam create-policy \
    --policy-name pulldb-secrets-manager-access \
    --policy-document file:///tmp/pulldb-secrets-manager-policy.json \
    --description "Allows pullDB to retrieve MySQL credentials from Secrets Manager"

# Attach to role
aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access

# Verify
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

### Step 3: Create and Attach Staging S3 Read Policy

```bash
# Create policy document
cat > /tmp/pulldb-staging-s3-read.json <<'POLICY'
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
POLICY

# Create policy
aws iam create-policy \
    --policy-name pulldb-staging-s3-read \
    --policy-document file:///tmp/pulldb-staging-s3-read.json \
    --description "Read-only access to staging S3 backups"

# Attach to role
aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-staging-s3-read

# Verify
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

### Step 4: Create Instance Profile and Attach to EC2

```bash
# Create instance profile
aws iam create-instance-profile \
    --instance-profile-name pulldb-instance-profile

# Add role to profile
aws iam add-role-to-instance-profile \
    --instance-profile-name pulldb-instance-profile \
    --role-name pulldb-ec2-service-role

# Verify
aws iam get-instance-profile --instance-profile-name pulldb-instance-profile

# Attach to EC2 instance (replace with your instance ID)
INSTANCE_ID="i-0dcd59209b7e932c3"

# Check current profile association
aws ec2 describe-iam-instance-profile-associations \
    --filters "Name=instance-id,Values=$INSTANCE_ID"

# If no profile, attach it
aws ec2 associate-iam-instance-profile \
    --instance-id $INSTANCE_ID \
    --iam-instance-profile Name=pulldb-instance-profile

# If replacing existing, first get association ID and disassociate
ASSOCIATION_ID=$(aws ec2 describe-iam-instance-profile-associations \
    --filters "Name=instance-id,Values=$INSTANCE_ID" \
    --query 'IamInstanceProfileAssociations[0].AssociationId' \
    --output text)

aws ec2 disassociate-iam-instance-profile --association-id $ASSOCIATION_ID
aws ec2 associate-iam-instance-profile \
    --instance-id $INSTANCE_ID \
    --iam-instance-profile Name=pulldb-instance-profile

# Final verification
aws ec2 describe-instances --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].IamInstanceProfile'
```

### Step 5: Create Secrets Manager Secrets

```bash
# pullDB uses service-specific MySQL users with separate secrets:
# - /pulldb/mysql/api - API service (pulldb_api user)
# - /pulldb/mysql/worker - Worker service (pulldb_worker user)
# - /pulldb/mysql/loader - myloader operations (pulldb_loader user)
#
# Secrets only store host + password. Username comes from:
#   PULLDB_API_MYSQL_USER or PULLDB_WORKER_MYSQL_USER (required)
#   PULLDB_MYSQL_PORT (default 3306), PULLDB_MYSQL_DATABASE (default pulldb_service)

# Create API service secret
aws secretsmanager create-secret \
    --name /pulldb/mysql/api \
    --description "MySQL credentials for pullDB API service" \
    --secret-string '{
        "password": "REPLACE_WITH_API_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development

# Create Worker service secret
aws secretsmanager create-secret \
    --name /pulldb/mysql/worker \
    --description "MySQL credentials for pullDB Worker service" \
    --secret-string '{
        "password": "REPLACE_WITH_WORKER_PASSWORD",
        "host": "localhost"
    }' \
    --tags Key=Service,Value=pulldb Key=Environment,Value=development

# Create Loader secret (for myloader restore operations on target hosts)
aws secretsmanager create-secret \
  --name /pulldb/mysql/loader \
  --description "MySQL credentials for myloader restore operations" \
  --secret-string '{
    "password": "REPLACE_WITH_LOADER_PASSWORD",
    "host": "localhost"
  }' \
  --tags Key=Service,Value=pulldb Key=Environment,Value=development



# Verify all secrets
aws secretsmanager list-secrets --filters Key=tag-key,Values=Service \
    --query 'SecretList[?Tags[?Key==`Service` && Value==`pulldb`]].Name'
```

---

## �� Staging Account (333204494849) CloudShell

### Step 1: Update S3 Bucket Policy

```bash
# Check existing bucket policy
aws s3api get-bucket-policy --bucket pestroutesrdsdbs \
    --query Policy --output text | jq .

# Download current policy to file
aws s3api get-bucket-policy --bucket pestroutesrdsdbs \
    --query Policy --output text > /tmp/current-bucket-policy.json

# Edit the file and add this statement to the Statement array:
cat >> /tmp/current-bucket-policy.json << 'POLICY'

ADD THIS TO THE "Statement" ARRAY:

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
POLICY

# OR if no existing policy, create new one:
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

# Verify
aws s3api get-bucket-policy --bucket pestroutesrdsdbs \
    --query Policy --output text | jq .
```

### Step 2: Update KMS Key Policy (If Bucket Encrypted)

```bash
# Get KMS key ID
KEY_ID=$(aws s3api get-bucket-encryption --bucket pestroutesrdsdbs \
    --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.KMSMasterKeyID' \
    --output text)

echo "KMS Key ID: $KEY_ID"

# View current key policy
aws kms get-key-policy --key-id $KEY_ID --policy-name default

# Add this statement to the key policy (manual edit required or use console):
cat << 'POLICY'

ADD THIS TO THE KEY POLICY "Statement" ARRAY:

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
POLICY
```

---

## 🔴 Production Account (448509429610) CloudShell (OPTIONAL)

**Note**: Only needed if configuring production backup access. Skip for initial staging-only setup.

### Step 1: Create Cross-Account Role

```bash
# Create trust policy
cat > /tmp/pulldb-prod-trust-policy.json <<'POLICY'
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
POLICY

# Create role
aws iam create-role \
    --role-name pulldb-cross-account-readonly \
    --assume-role-policy-document file:///tmp/pulldb-prod-trust-policy.json \
    --description "Cross-account read-only access for pullDB from dev account"

# Verify
aws iam get-role --role-name pulldb-cross-account-readonly
```

### Step 2: Create and Attach S3 Read Policy

```bash
# Create policy document
cat > /tmp/pulldb-prod-s3-policy.json <<'POLICY'
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
POLICY

# Create policy
aws iam create-policy \
    --policy-name pulldb-prod-s3-readonly \
    --policy-document file:///tmp/pulldb-prod-s3-policy.json \
    --description "Read-only access to production S3 backups"

# Attach to role
aws iam attach-role-policy \
    --role-name pulldb-cross-account-readonly \
    --policy-arn arn:aws:iam::448509429610:policy/pulldb-prod-s3-readonly

# Verify
aws iam list-attached-role-policies --role-name pulldb-cross-account-readonly
```

---

## ✅ Verification Commands (Run from EC2 Instance)

After applying all CloudShell commands, SSH to your EC2 instance and verify:

```bash
# 1. Verify instance profile
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" -s)
curl -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/iam/security-credentials/ -s
# Expected: pulldb-ec2-service-role

# 2. Verify caller identity
aws sts get-caller-identity
# Expected: Account 345321506926, Role pulldb-ec2-service-role

# 3. Test staging S3 access
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head
# Expected: List of customer/qatemplate directories

# 4. Test secrets access
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db \
    --query SecretString --output text | jq .
# Expected: JSON with password, host (username/port come from env vars)

# 5. Test Python integration
python3 << 'PYTHON'
import sys
sys.path.insert(0, '/home/charleshandshy/Projects/infra.devops/Tools/pullDB')

from pulldb.infra.secrets import CredentialResolver

resolver = CredentialResolver()
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/coordination-db')
print(f"✅ Coordination DB: {creds['host']} as {creds['username']}")
PYTHON
```

---

## Summary Checklist

### Development Account (345321506926)
- [ ] EC2 service role created
- [ ] Secrets Manager policy attached to role
- [ ] Staging S3 read policy attached to role
- [ ] Instance profile created
- [ ] Instance profile attached to EC2 instance
- [ ] Coordination DB secret created
- [ ] Target DB secrets created (db-local-dev)

### Staging Account (333204494849)
- [ ] Bucket policy updated with dev account role principal
- [ ] KMS key policy updated (if bucket encrypted)

### Production Account (448509429610) - OPTIONAL
- [ ] Cross-account role created with external ID
- [ ] S3 read policy attached to cross-account role

### Verification
- [ ] Instance profile visible in EC2 metadata
- [ ] STS caller identity shows correct role
- [ ] S3 listing works for staging bucket
- [ ] Secrets Manager retrieval works
- [ ] Python credential resolver works

---

**Estimated Time**: 30-45 minutes total
**Order**: Development → Staging → (Optional: Production) → Verification
