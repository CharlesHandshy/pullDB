# AWS Authentication Setup for pullDB

> **Primary AWS Documentation**: This is the complete, consolidated guide for AWS authentication supporting the two-service architecture (API Service + Worker Service).

## Overview

pullDB consists of two services that need AWS access with different permission levels:
- **API Service**: Read-only S3 access for backup discovery (ListBucket, HeadObject)
- **Worker Service**: Full S3 read access for downloading backups (GetObject)
- **CLI**: No AWS access - calls API service via HTTP

Both services run on an **EC2 instance** in the development AWS account and use **EC2 instance profile** for authentication (no access keys, automatic credential rotation).

## Setup Decision Tree

**For Staging Bucket Access** (account 333204494849):
- ✅ **Recommended**: Direct cross-account access
  - Development account: Steps 1.1-1.6 (add `pulldb-staging-s3-read` policy)
  - Staging account: Step 2.3 (bucket policy allowing dev account role)
  - Advantage: No profile switching, no AssumeRole latency

- Alternative: Cross-account role assumption
  - Development account: Steps 1.1-1.3 (add `pulldb-cross-account-assume-role` policy)
  - Staging account: Steps 2.1-2.3 (create assumable role with S3 permissions)
  - Advantage: External ID validation, separate audit trail per account

**For Production Bucket Access** (account 448509429610):
- ✅ **Recommended**: Cross-account role assumption
  - Development account: Steps 1.1-1.3
  - Production account: Steps 3.1-3.2
  - Advantage: Stricter security boundary, explicit external ID requirement

**For Both**: Add Secrets Manager policy (Step 1.2) for MySQL credential resolution.

> Fast Path (Development Convenience)
> ----------------------------------
> For development access to staging backups, you have two options:
>
- **Complete Setup Guide**: See `AWS-SETUP.md` for consolidated AWS setup instructions
>
> The optional real S3 listing test skips gracefully on `AccessDenied` to avoid blocking the suite when permissions are not yet configured.

### Direct EC2 Role Usage (After Step 1.6 Setup)

After attaching the staging S3 read policy to your instance role:

```bash
# Confirm instance role identity (should show the dev account ID)
aws sts get-caller-identity

# List staging backups directly using instance role credentials
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head

# Head one object (replace with an existing key)
aws s3api head-object \
  --bucket pestroutesrdsdbs \
  --key daily/stg/qatemplate/daily_mydumper_qatemplate_2025-10-30T03-00-00Z_Wed_dbimp.tar || true

# (Optional) Partial object read without full download
aws s3api get-object \
  --bucket pestroutesrdsdbs \
  --key daily/stg/qatemplate/daily_mydumper_qatemplate_2025-10-30T03-00-00Z_Wed_dbimp.tar \
  --range bytes=0-1023 /tmp/preview.part || true
```

If these commands succeed, S3 access is working. If you prefer cross‑account role assumption instead, continue to profile configuration sections below.

### When to Use Each Approach

**Direct Instance Profile (Step 1.6)** - Best for:
- Development environments with single staging bucket
- Simplified configuration (no profile switching)
- Faster iteration (no AssumeRole latency)

**Cross-Account Assumption (Steps 2-4)** - Required for:
- Production bucket access (different AWS account)
- Multi-account environments with strict separation
- Audit requirements needing external ID validation

### Minimal IAM Actions Required

| Action | Purpose | Required For |
|--------|---------|--------------|
| `s3:ListBucket` | Enumerate backup keys under `daily/stg/` | API + Worker |
| `s3:GetObject` | Download backup archives / schema files | Worker (API may only need small schema reads) |
| `s3:HeadObject` | Size / metadata preflight | API + Worker |

All other actions (Put/Delete) should remain absent or explicitly denied.

### Optional Test Behavior

The test `test_real_staging_backup_listing_optional` now treats an `AccessDenied` encountered **during paginator iteration** as a skip:

```
Skipping real S3 listing: AccessDenied during paginator iteration
```

This ensures lack of list permission does not mark the suite as failed. Once `s3:ListBucket` permission is granted the test will proceed and assert at least one matching backup key exists.

### When to Add Identity-Based Policy

Add a scoped inline or managed policy granting only the three S3 read actions above when:
1. You begin restricting the instance role’s broader inherited permissions.
2. You need explicit audit separation (e.g. CloudTrail queries by policy Sid).
3. You introduce production access patterns requiring different bucket ARNs.

Until then, direct instance profile usage keeps configuration minimal and avoids drift between documentation and runtime behavior.

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

### Current Secret Residency (2025-11-01)
All Secrets Manager secrets referenced by pullDB (`/pulldb/mysql/db3-dev`, `/pulldb/mysql/db4-dev`, `/pulldb/mysql/db5-dev`, `/pulldb/mysql/coordination-db`) exist only in the development account (345321506926). They are not replicated to staging or production accounts. Use the instance profile or a dev admin profile for secret CRUD; do not use `pr-staging` or `pr-prod` profiles for these operations. If future replication is required it will be documented prior to implementation.

### Secrets Manager Permission Evaluation (MANDATORY)

The runtime (API + Worker) only needs to READ MySQL credential secrets. Write / admin operations are restricted to provisioning workflows and are intentionally excluded from the `pulldb-ec2-service-role` to preserve least privilege.

Required runtime actions:
- `secretsmanager:GetSecretValue` (retrieve credential JSON)
- `secretsmanager:DescribeSecret` (optional metadata checks / future rotation planning)
- `kms:Decrypt` (if the secret is encrypted with a customer managed KMS key)

Optional discovery action (already granted with tag condition):
- `secretsmanager:ListSecrets` (filtering by `Service=pulldb` tag for diagnostic tooling)

Intentionally NOT granted to the instance profile (reserved for admin roles):
- `secretsmanager:CreateSecret`, `UpdateSecret`, `TagResource`, `UntagResource`, `RotateSecret`, `PutSecretValue`, `DeleteSecret`, `RestoreSecret`

Current policy (`pulldb-secrets-manager-access`) already grants:
```jsonc
{
  "Sid": "GetPullDBSecrets", // Get + Describe for /pulldb/mysql/*
  "Sid": "ListSecretsForDiscovery", // ListSecrets with tag condition
  "Sid": "DecryptSecretsWithKMS" // kms:Decrypt + kms:DescribeKey via Secrets Manager
}
```

#### Verification Procedure

**IMPORTANT**: The verification script requires IAM read permissions (`iam:ListAttachedRolePolicies`, `iam:GetRole`, `iam:SimulatePrincipalPolicy`) which the EC2 instance profile does NOT have. You must run these commands using an AWS CLI profile with IAM read access (e.g., a user or role with `IAMReadOnlyAccess` or equivalent).

**Automated Verification Script**:
```bash
# Run with an admin profile that has IAM read permissions
./scripts/verify-secrets-perms.sh --profile default
```

This script performs comprehensive verification:
1. Checks policy attachment (`pulldb-secrets-manager-access` on `pulldb-ec2-service-role`)
2. Simulates required actions (GetSecretValue, DescribeSecret, ListSecrets, kms:Decrypt)
3. Live secret operations (DescribeSecret + GetSecretValue)
4. Negative simulation (admin actions should be denied)
5. Optional KMS key policy inspection

**Manual Verification** (requires IAM read permissions):

Run the following commands using a profile with IAM read access (not the instance profile):

```bash
# 1. Confirm policy attached (requires iam:ListAttachedRolePolicies)
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role \
  --query 'AttachedPolicies[?PolicyName==`pulldb-secrets-manager-access`].PolicyName' \
  --profile dev-admin

# 2. Simulate allowed actions on a target secret (requires iam:SimulatePrincipalPolicy)
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::345321506926:role/pulldb-ec2-service-role \
  --action-names secretsmanager:GetSecretValue secretsmanager:DescribeSecret secretsmanager:ListSecrets kms:Decrypt \
  --resource-arns arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/coordination-db-* \
  --profile dev-admin

# 3. Describe secret (metadata)
aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db \
  --query '{Name:Name,ARN:ARN,RotationEnabled:RotationEnabled}'

# 4. Get secret value (first 120 chars for sanity) – should succeed
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db \
  --query 'SecretString' --output text | head -c 120; echo

# 5. Negative test: Simulate denied admin actions (should return Decision=implicitDeny)
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::345321506926:role/pulldb-ec2-service-role \
  --action-names secretsmanager:CreateSecret secretsmanager:PutSecretValue secretsmanager:DeleteSecret \
  --resource-arns arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/coordination-db-* \
  --profile dev-admin
```

**Note on Secret Access from EC2**: Once the policy is attached, the EC2 instance profile CAN read secrets directly (commands #3 and #4 work without `--profile`). However, IAM introspection commands (#1, #2, #5) require a separate admin profile because the instance profile doesn't (and shouldn't) have `iam:*` permissions for least privilege.

Expected results:
- Actions `GetSecretValue`, `DescribeSecret`, `ListSecrets` (conditional), and `kms:Decrypt` show `allowed`.
- Admin actions show `implicitDeny` (unless a broader admin role is used instead of the instance profile).

#### KMS Key Considerations
If using a customer managed KMS key for secret encryption, ensure the key policy does NOT restrict the instance profile. The current policy stanza allowing `kms:Decrypt` with condition `"kms:ViaService": "secretsmanager.us-east-1.amazonaws.com"` is sufficient for Secrets Manager decryption.

Quick key policy check:
```bash
SECRET_ARN=$(aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db --query 'ARN' --output text)
KEY_ID=$(aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db --query 'KmsKeyId' --output text)
aws kms get-key-policy --key-id "$KEY_ID" --policy-name default | grep -E 'pulldb|Decrypt' || echo 'Review key policy – ensure decrypt allowed.'
```

#### CI Test Path Readiness
Before adding test assertions on secret residency or ARN account ID, confirm all CI runners:
1. Use the instance profile or federated role with identical permissions.
2. Successfully pass the simulation and live retrieval commands above.
3. Never trigger fallback local credential overrides during normal test runs.

Once confirmed, a test can parse the secret ARN and assert account `345321506926`.

### FAIL HARD AWS Authentication Guardrail

All AWS authentication failures MUST halt operations with diagnostic output; no silent retries with downgraded behaviour.

Template:
```
Goal: Retrieve secret /pulldb/mysql/coordination-db
Problem: ResourceNotFoundException
Root Cause: Secret not created in development account (expected 345321506926)
Solutions:
  1. Create secret (see docs/aws-secrets-manager-setup.md)
  2. Verify AWS_PROFILE and region exports
  3. Re-run verification script: ./scripts/verify-secrets-perms.sh --profile dev-admin
```

Apply this pattern for IAM AccessDenied, STS credential issues, and Secrets Manager retrieval errors.


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
- `pulldb-cross-account-assume-role` - Cross-account S3 access (add if missing, Step 1.3)
- `pulldb-secrets-manager-access` - Secrets Manager for MySQL credentials (add if missing, Step 1.2)
- `pulldb-staging-s3-read` - Direct staging S3 access (add if missing, Step 1.6)
- `pulldb-production-s3-read` - Direct production S3 access (optional, Step 1.7)

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

### 1.2 Add Secrets Manager Access Policy

This policy allows pullDB services to retrieve MySQL credentials from AWS Secrets Manager.

**Check if policy already exists**:
```bash
# Check for existing policy
aws iam get-policy --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access 2>/dev/null

# If policy exists, verify it's attached to role
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role | grep pulldb-secrets-manager-access
```

**If policy doesn't exist, create it**:
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

# Create policy
aws iam create-policy \
    --policy-name pulldb-secrets-manager-access \
    --policy-document file:///tmp/pulldb-secrets-manager-policy.json \
    --description "Allows pullDB to retrieve MySQL credentials from Secrets Manager"
```

**Attach policy to role** (if not already attached):
```bash
aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access

# Verify attachment
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

### 1.3 Add Cross-Account Assumption Policy

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

### 1.4 Create Instance Profile

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

### 1.5 Attach Instance Profile to EC2

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

### 1.6 Add Staging S3 Read Policy (Same-Account Access)

This policy allows the EC2 role to read from the staging S3 bucket **in the same account** (333204494849).

**Check if policy already exists**:
```bash
# Check for existing policy
aws iam get-policy --policy-arn arn:aws:iam::345321506926:policy/pulldb-staging-s3-read 2>/dev/null

# If policy exists, verify it's attached to role
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role | grep pulldb-staging-s3-read
```

**If policy doesn't exist, create it**:
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

# Create policy
aws iam create-policy \
    --policy-name pulldb-staging-s3-read \
    --policy-document file:///tmp/pulldb-staging-s3-read.json \
    --description "Read-only access to staging S3 backups in same account"
```

**Attach policy to role** (if not already attached):
```bash
aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-staging-s3-read

# Verify attachment
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role
```

**Test access**:
```bash
# Should now succeed without --profile flag (uses instance profile)
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head

# Head object test
aws s3api head-object \
    --bucket pestroutesrdsdbs \
    --key daily/stg/qatemplate/daily_mydumper_qatemplate_2025-10-30T03-00-00Z_Wed_dbimp.tar
```

> **Note**: This policy grants access to the staging bucket which resides in the **staging account 333204494849** (cross-account access from dev account 345321506926). The bucket owner (staging account) must also grant access via:
> 1. **Bucket policy** allowing the dev account role as principal (Step 2.3), OR
> 2. **IAM role assumption** where dev account assumes a role in staging account with bucket permissions (Steps 1.3 + 2.1-2.2)
>
> **Recommended approach for staging**: Use direct cross-account bucket access (Steps 1.6 + 2.3 bucket policy). This avoids AssumeRole latency and profile switching.
>
> **Recommended approach for production**: Use cross-account role assumption (Steps 1.3 + 3.x) for stricter audit trail and external ID validation.

### 1.7 Add Production S3 Read Policy (Optional)

Similar to staging, you can add direct access to the production bucket if it also resides in an account you control.

**If policy doesn't exist, create it**:
```bash
cat > /tmp/pulldb-production-s3-read.json <<'EOF'
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
      "Sid": "ReadProductionBackups",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:HeadObject"],
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

# Create policy
aws iam create-policy \
    --policy-name pulldb-production-s3-read \
    --policy-document file:///tmp/pulldb-production-s3-read.json \
    --description "Read-only access to production S3 backups"

# Attach to role
aws iam attach-role-policy \
    --role-name pulldb-ec2-service-role \
    --policy-arn arn:aws:iam::345321506926:policy/pulldb-production-s3-read
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

**When Required**:
- **Option A (Step 1.6 direct access)**: Required to allow dev account role `pulldb-ec2-service-role` to access bucket
- **Option B (Step 1.3 cross-account assumption)**: Required to allow assumed role `pulldb-cross-account-readonly` to access bucket
- **Skip if**: Bucket already has permissive policy or uses IAM-only authorization

**Check if bucket policy modification is needed**:
```bash
# Check current bucket policy
aws s3api get-bucket-policy --bucket pestroutesrdsdbs --query Policy --output text 2>/dev/null | jq .

# If no policy exists or policy doesn't have explicit Deny statements, skip this step
# If you see an error "NoSuchBucketPolicy", you can skip this step
```

**Test if IAM permissions alone work**:
```bash
# From the dev account EC2 instance, test assuming the role and listing the bucket
aws sts assume-role \
    --role-arn arn:aws:iam::333204494849:role/pulldb-cross-account-readonly \
    --role-session-name test-access \
    --external-id pulldb-dev-access-2025

# Use the temporary credentials to test S3 access
# If this works, you don't need to modify the bucket policy
```

**Only if bucket policy modification is required** (bucket policy has explicit Deny or conflicting Allow):

```bash
# Get existing bucket policy
aws s3api get-bucket-policy --bucket pestroutesrdbs --query Policy --output text > /tmp/current-bucket-policy.json

# View current policy
cat /tmp/current-bucket-policy.json | jq .

# Create the statement to add (DO NOT apply directly - merge manually)
# Choose the appropriate principal ARN based on your approach:

# Option A: Direct access from dev account (Step 1.6)
cat > /tmp/pulldb-statement-direct-access.json <<'EOF'
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
EOF

# Option B: Cross-account role assumption (Steps 1.3 + 2.1-2.2)
cat > /tmp/pulldb-statement-assumed-role.json <<'EOF'
{
  "Sid": "AllowPullDBCrossAccountRead",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::333204494849:role/pulldb-cross-account-readonly"
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
EOF

echo "=== MANUAL MERGE REQUIRED ==="
echo "1. Review the current bucket policy above"
echo "2. Choose Option A (direct) or Option B (assumed role) statement from above"
echo "3. Add the chosen pullDB statement to the existing policy's Statement array"
echo "4. Save the merged policy to /tmp/updated-bucket-policy.json"
echo "5. Validate JSON: cat /tmp/updated-bucket-policy.json | jq ."
echo "6. Apply: aws s3api put-bucket-policy --bucket pestroutesrdsdbs --policy file:///tmp/updated-bucket-policy.json"
echo ""
echo "Example merged policy structure (using Option A - direct access):"
cat <<'EXAMPLE'
{
  "Version": "2012-10-17",
  "Statement": [
    ... existing statements here ...,
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
EXAMPLE
```

**Alternative: If bucket has no existing policy**:
```bash
# Only use this if the bucket currently has NO policy
aws s3api put-bucket-policy --bucket pestroutesrdsdbs --policy '{
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
}'
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

Configure AWS profiles on the EC2 instance for the `pulldb` service user.

### 4.1 Create Service User and AWS Directory

```bash
# Create dedicated service user (if not already exists)
sudo useradd -r -s /bin/bash -d /opt/pulldb -m pulldb

# Create AWS configuration directory with proper permissions
sudo mkdir -p /opt/pulldb/.aws/cli/cache
sudo chown -R pulldb:pulldb /opt/pulldb/.aws
sudo chmod 700 /opt/pulldb/.aws
sudo chmod 700 /opt/pulldb/.aws/cli
```

### 4.2 Create AWS Config

```bash
# Create AWS config file as root, then fix ownership
sudo tee /opt/pulldb/.aws/config > /dev/null <<'EOF'
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

# Set proper ownership and permissions
sudo chown pulldb:pulldb /opt/pulldb/.aws/config
sudo chmod 600 /opt/pulldb/.aws/config

# Verify setup
sudo ls -la /opt/pulldb/.aws/
```

**Key Settings**:
- `credential_source = Ec2InstanceMetadata` - Uses instance profile instead of access keys
- `external_id` - Prevents confused deputy problem
- No `[default]` profile needed - services explicitly use named profiles
- Config file owned by `pulldb` user with restrictive permissions (600)

### 4.3 Environment Configuration

```bash
# Create environment files directory
sudo mkdir -p /etc/pulldb
sudo chown pulldb:pulldb /etc/pulldb
sudo chmod 755 /etc/pulldb

# Create API service environment file
sudo tee /etc/pulldb/api.env > /dev/null <<'EOF'
# API Service Environment Variables
PULLDB_AWS_PROFILE=pr-staging
PULLDB_S3_BUCKET_STAGING=pestroutesrdsdbs
PULLDB_S3_BUCKET_PROD=pestroutes-rds-backup-prod-vpc-us-east-1-s3
PULLDB_S3_PREFIX_STAGING=daily/stg
PULLDB_S3_PREFIX_PROD=daily/prod
HOME=/opt/pulldb
EOF

# Create Worker service environment file
sudo tee /etc/pulldb/worker.env > /dev/null <<'EOF'
# Worker Service Environment Variables
PULLDB_AWS_PROFILE=pr-staging
PULLDB_S3_BUCKET_STAGING=pestroutesrdsdbs
PULLDB_S3_BUCKET_PROD=pestroutes-rds-backup-prod-vpc-us-east-1-s3
PULLDB_S3_PREFIX_STAGING=daily/stg
PULLDB_S3_PREFIX_PROD=daily/prod
PULLDB_WORK_DIR=/mnt/data/pulldb/work
HOME=/opt/pulldb
EOF

# Set proper permissions
sudo chown pulldb:pulldb /etc/pulldb/*.env
sudo chmod 600 /etc/pulldb/*.env

# Create work directory
sudo mkdir -p /mnt/data/pulldb/work
sudo chown -R pulldb:pulldb /mnt/data/pulldb
sudo chmod 755 /mnt/data/pulldb
```

**Important**: `HOME=/opt/pulldb` ensures AWS SDK finds config in `/opt/pulldb/.aws/config`

## Step 5: Verification

### 5.1 Test Instance Profile

```bash
# Test as pulldb service user
sudo -u pulldb bash

# Get IMDSv2 session token (required for newer EC2 instances)
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

# Verify instance metadata service with token
curl -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Should return: pulldb-ec2-service-role

# Get temporary credentials with token
curl -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/iam/security-credentials/pulldb-ec2-service-role

# Should return JSON with AccessKeyId, SecretAccessKey, Token

# Alternative: Use IMDSv1 if IMDSv2 is not enforced (older instances)
# curl http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

### 5.2 Test Cross-Account Role Assumption

```bash
# Test as pulldb service user
sudo -u pulldb bash

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

# Exit pulldb user shell
exit
```

**Troubleshooting Permission Denied Errors**:
```bash
# If you see "[Errno 13] Permission denied: '/opt/pulldb/.aws/cli'"
# Fix AWS directory permissions:
sudo mkdir -p /opt/pulldb/.aws/cli/cache
sudo chown -R pulldb:pulldb /opt/pulldb/.aws
sudo chmod 700 /opt/pulldb/.aws
sudo chmod 700 /opt/pulldb/.aws/cli

# Verify ownership
sudo ls -la /opt/pulldb/.aws/
# Should show: drwx------ pulldb pulldb
```

### 5.3 Test S3 Access

```bash
# Test as pulldb service user
sudo -u pulldb bash

# List staging backups
AWS_PROFILE=pr-staging aws s3 ls s3://pestroutesrdbs/daily/stg/

# List production backups
AWS_PROFILE=pr-prod aws s3 ls s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/

# Test read access (adjust path to actual backup)
AWS_PROFILE=pr-staging aws s3api head-object \
    --bucket pestroutesrdbs \
    --key daily/stg/customer/daily_mydumper_customer_2025-10-30T03-00-00Z_Wed_dbimp.tar

# Verify write is denied
echo "test" > /tmp/test.txt
AWS_PROFILE=pr-staging aws s3 cp /tmp/test.txt s3://pestroutesrdbs/test.txt
# Should return: Access Denied error

# Cleanup
rm /tmp/test.txt
exit
```

### 5.4 Test from Python (Services)

```python
import boto3

# Test as API service would (read-only listing)
session = boto3.Session(profile_name='pr-staging')
s3_client = session.client('s3')

# List objects (allowed)
response = s3_client.list_objects_v2(
    Bucket='pestroutesrdbs',
    Prefix='daily/stg/',
    MaxKeys=10
)
print(f"Found {len(response.get('Contents', []))} backups")

# Get first backup for testing (if any exist)
if response.get('Contents'):
    first_backup = response['Contents'][0]
    backup_key = first_backup['Key']
    print(f"Testing with: {backup_key}")

    # Head object metadata (allowed)
    metadata = s3_client.head_object(
        Bucket='pestroutesrdbs',
        Key=backup_key
    )
    print(f"Backup size: {metadata['ContentLength']:,} bytes")
    print(f"Last modified: {metadata['LastModified']}")

    # Test download (allowed for worker service)
    # Note: Only test with small files or use Range header for large backups
    try:
        # For large tar files, just verify access without full download
        print("Verifying download access (not downloading full file)...")
        response = s3_client.get_object(
            Bucket='pestroutesrdbs',
            Key=backup_key,
            Range='bytes=0-1023'  # Just get first 1KB
        )
        print(f"Download access: ✅ Verified (read {len(response['Body'].read())} bytes)")
    except Exception as e:
        print(f"Download access: ❌ Failed - {e}")
else:
    print("No backups found in daily/stg/ - check bucket path")
```

**Expected Output**:
```
Found 10 backups
Testing with: daily/stg/qatemplate/daily_mydumper_qatemplate_2025-10-30T03-00-00Z_Wed_dbimp.tar
Backup size: 45,678,901 bytes
Last modified: 2025-10-30 03:15:23+00:00
Verifying download access (not downloading full file)...
Download access: ✅ Verified (read 1024 bytes)
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
| `kms:Decrypt` | ✅ Allowed (via S3) | ✅ Allowed (via S3/Secrets) | SSE-KMS |
| `ssm:GetParameter` | ✅ Allowed | ✅ Allowed | Config values |
| `secretsmanager:GetSecretValue` | ✅ Allowed | ✅ Allowed | MySQL creds |

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
2. Wrong credential_source in `/opt/pulldb/.aws/config`
3. Metadata service unavailable
4. IMDSv2 required but token not provided (401 Unauthorized)
5. AWS directory permissions incorrect (owned by root instead of pulldb user)

**Fix**:
```bash
# Check instance profile
aws ec2 describe-instances --instance-ids i-xxxxx \
    --query 'Reservations[0].Instances[0].IamInstanceProfile'

# Test metadata service (IMDSv2 - required for newer instances)
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
curl -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/iam/security-credentials/

# If you get "401 - Unauthorized" without token, IMDSv2 is enforced (expected for security)

# Fix AWS directory permissions if owned by wrong user
sudo chown -R pulldb:pulldb /opt/pulldb/.aws
sudo chmod 700 /opt/pulldb/.aws
sudo mkdir -p /opt/pulldb/.aws/cli/cache
sudo chmod 700 /opt/pulldb/.aws/cli

# Verify config file has credential_source = Ec2InstanceMetadata
sudo cat /opt/pulldb/.aws/config
```

### Error: KMS Decrypt Access Denied
### Error: AccessDeniedException retrieving `/pulldb/mysql/coordination-db`

**Symptom**: `secretsmanager:GetSecretValue AccessDeniedException` while tests attempt to load coordination DB credentials.

**Causes**:
1. `pulldb-secrets-manager-access` policy not attached to `pulldb-ec2-service-role`.
2. Secret created in a different account/region than expected (verify account id 345321506926 and region `us-east-1`).
3. AWS profile mismatch (using a legacy profile name like `dev-pulldb` instead of `pr-staging` or instance profile context).
4. Secret name typo (`/pulldb/mysql/coordination-db` must match exactly).

**Fix Steps**:
```bash
# 1. Verify policy attachment
aws iam list-attached-role-policies --role-name pulldb-ec2-service-role \
  --query 'AttachedPolicies[?PolicyName==`pulldb-secrets-manager-access`].PolicyName'

# 2. Describe secret in dev account (no profile if on EC2 with instance profile)
aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db --region us-east-1 \
  --query 'ARN'

# 3. Test retrieval (staging profile only affects cross-account S3; Secrets are local to dev account)
AWS_PROFILE=pr-staging aws secretsmanager get-secret-value \
  --secret-id /pulldb/mysql/coordination-db --region us-east-1 \
  --query 'SecretString' --output text | head -c 200

# 4. If policy missing, create/attach (idempotent check first)
aws iam get-policy --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access 2>/dev/null || {
  echo 'Creating secrets manager policy';
  cat > /tmp/pulldb-secrets-manager-policy.json <<'EOF'
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "GetPullDBSecrets",
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue","secretsmanager:DescribeSecret"],
        "Resource": ["arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/*"]
      },
      {
        "Sid": "DecryptSecretsWithKMS",
        "Effect": "Allow",
        "Action": ["kms:Decrypt","kms:DescribeKey"],
        "Resource": "*",
        "Condition": {"StringEquals": {"kms:ViaService": ["secretsmanager.us-east-1.amazonaws.com"]}}
      }
    ]
  }
EOF
  aws iam create-policy --policy-name pulldb-secrets-manager-access \
    --policy-document file:///tmp/pulldb-secrets-manager-policy.json \
    --description 'Allows pullDB to retrieve MySQL credentials from Secrets Manager';
}

aws iam attach-role-policy --role-name pulldb-ec2-service-role \
  --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access || true

# 5. Re-test
AWS_PROFILE=pr-staging aws secretsmanager get-secret-value \
  --secret-id /pulldb/mysql/coordination-db --region us-east-1 --query 'SecretString' --output text | jq .
```

**Legacy Profile Cleanup**:
Replace any usage of `dev-pulldb`, `pulldb-dev`, or similar with `pr-staging` (prototype primary) or `pr-prod` (production backups). Profiles in `~/.aws/config` should only define these two plus any temporary override used for external ID rotation.

**Test Suite Mandate**:
All integration/repository tests must resolve coordination DB credentials via the secret—environment variable overrides (`PULLDB_TEST_MYSQL_HOST` etc.) are temporary local-development fallbacks only.

**Symptom**: `An error occurred (AccessDenied) when calling the GetObject operation: Access Denied`

**Cause**: KMS key policy doesn't allow dev account to decrypt

**Fix**:
```bash
# Get KMS key ID from bucket encryption
KEY_ID=$(aws s3api get-bucket-encryption --bucket pestroutesrdbs \
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
- **Secrets Manager Setup**: See `aws-secrets-manager-setup.md` for MySQL credential storage (recommended)
- **Parameter Store Setup**: See `parameter-store-setup.md` for alternative credential storage
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
- ✅ Secrets Manager access for MySQL credentials with auto-rotation
- ✅ KMS decrypt scoped to S3 and Secrets Manager services only

Both API and Worker services use the same instance profile but implement different access patterns:
- API service lists and inspects backups (discovery), retrieves MySQL credentials
- Worker service downloads and restores backups (execution), connects to target databases
