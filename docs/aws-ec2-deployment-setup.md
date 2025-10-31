# AWS Authentication Setup for pullDB on EC2

## Overview

This guide explains how to configure AWS authentication for pullDB running on an EC2 instance in the development AWS account using a **pure service-backend architecture**.

**Key Architecture Principle**:
- **CLI has NO AWS access** - it calls daemon REST API
- **Daemon has ALL AWS access** - it's the only component that touches S3 and MySQL
- **Developers are isolated** - they never need AWS credentials
- **User identity** comes from OS/SSH authentication, not AWS

## Understanding the Deployment Model

### Architecture: CLI as Thin Client, Daemon as Service Backend

pullDB runs on an **EC2 Ubuntu instance** in the development AWS account with:
- **CLI**: Thin client that validates input and calls daemon REST API (no AWS or MySQL access)
- **Daemon**: Service backend with REST API that manages jobs in MySQL and executes restores using AWS (EC2 instance profile)
- **Developers**: SSH to box, run CLI commands, never need AWS credentials
- **Authentication**: User identity from SSH username, enforced by wrapper script

### The Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     EC2 Instance (Dev Account)                   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Developer SSH Session (charles)                             │ │
│  │                                                              │ │
│  │ $ pullDB customer=acme                                      │ │
│  │                                                              │ │
│  │ Wrapper:                                                    │ │
│  │ • Validates user in pulldb-users group                     │ │
│  │ • Injects user=charles.handshy                             │ │
│  │ • NO AWS credentials needed                                │ │
│  └────────────────────────────────────────────────────────────┘ │
│                          ↓                                        │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ CLI (pulldb-cli binary)                                     │ │
│  │ • Validates options (user=, customer=/qatemplate)          │ │
│  │ • Generates user_code and target name                      │ │
│  │ • Calls daemon REST API (NO AWS or MySQL access)           │ │
│  └────────────────────────────────────────────────────────────┘ │
│                          ↓ HTTP POST                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Daemon (pulldb-daemon) - REST API + Worker                 │ │
│  │                                                              │ │
│  │ API Layer:                                                  │ │
│  │ • POST /api/jobs - create restore job                      │ │
│  │ • GET /api/jobs/{id} - job status                          │ │
│  │ • GET /api/jobs - list jobs                                │ │
│  │                                                              │ │
│  │ Worker:                                                     │ │
│  │ • Polls MySQL for queued jobs                              │ │
│  │ • Uses EC2 instance profile                                │ │
│  │ • Assumes cross-account role                               │ │
│  │ • Downloads from S3                                        │ │
│  │ • Restores to MySQL                                        │ │
│  │ • Updates job status in MySQL                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                          ↓                                        │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ MySQL Database (pulldb)                                     │ │
│  │ • jobs table: restore requests                             │ │
│  │ • job_events: audit trail                                  │ │
│  │ (accessed only by daemon)                                  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│                          ↓                                        │
│                    Production S3 Bucket                          │
│              (cross-account via IAM role)                        │
└─────────────────────────────────────────────────────────────────┘
```

## Why This Architecture?

### Security Benefits

| Concern | Solution |
|---------|----------|
| **Developers need AWS access** | ❌ No they don't - CLI calls daemon REST API |
| **Credential distribution** | ✅ Developers never get AWS credentials |
| **Audit trail** | ✅ User identity from SSH, tracked by daemon in MySQL |
| **Credential rotation** | ✅ Only daemon has credentials (auto-rotated by AWS) |
| **Least privilege** | ✅ Developers can't access S3 or MySQL directly |

### Operational Benefits

| Aspect | Benefit |
|--------|---------|
| **Onboarding** | Add user to `pulldb-users` group (no AWS setup) |
| **Offboarding** | Remove from group (no AWS cleanup) |
| **Development** | Test CLI without AWS credentials or MySQL access |
| **Simplicity** | Single AWS identity (daemon) instead of N developers |

---

## Part 1: Production Account Setup (One-Time)

These steps create the cross-account role that the **daemon** (and only the daemon) will assume.

### Step 1.1: Create Cross-Account Role Trust Policy

**Account**: Production (`448509429610`)
**Create file**: `prod-cross-account-trust.json`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::345321506926:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-cross-account-2024"
        }
      }
    },
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::333204494849:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "pulldb-cross-account-2024"
        }
      }
    }
  ]
}
```

**Note**: Trust policy allows dev/staging accounts. The daemon's EC2 instance role will be granted permission to assume this role.### Step 1.2: Create Permission Policy

**Create file**: `prod-cross-account-permissions.json`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ReadProductionBackups",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3",
        "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/*"
      ]
    },
    {
      "Sid": "S3ReadStagingBackups",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::pestroutesrdsdbs",
        "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
      ]
    },
    {
      "Sid": "SSMReadParameters",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": [
        "arn:aws:ssm:us-east-1:448509429610:parameter/pulldb/prod/mysql/*"
      ]
    },
    {
      "Sid": "KMSDecryptBackups",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey"
      ],
      "Resource": [
        "arn:aws:kms:us-east-1:448509429610:key/*"
      ],
      "Condition": {
        "StringEquals": {
          "kms:ViaService": [
            "s3.us-east-1.amazonaws.com"
          ]
        }
      }
    }
  ]
}
```

### Step 1.3: Create the IAM Role

```bash
# Switch to production account
aws sts get-caller-identity --profile pr-prod

# Create the role
aws iam create-role \
  --profile pr-prod \
  --role-name pulldb-cross-account-read \
  --assume-role-policy-document file://prod-cross-account-trust.json \
  --description "Cross-account read access for pullDB to S3 backups"

# Attach the inline policy
aws iam put-role-policy \
  --profile pr-prod \
  --role-name pulldb-cross-account-read \
  --policy-name S3ReadAndSSMAccess \
  --policy-document file://prod-cross-account-permissions.json

# Get the role ARN (save this!)
aws iam get-role \
  --profile pr-prod \
  --role-name pulldb-cross-account-read \
  --query 'Role.Arn' \
  --output text
```

**Save the ARN**: You'll need this in the next section.
**Example**: `arn:aws:iam::448509429610:role/pulldb-cross-account-read`

---

## Part 2: Development Account Setup (Daemon Service)

The daemon is the **only component** that needs AWS credentials. Configure EC2 instance profile for the daemon.

### Step 2.1: Create EC2 Instance Role

**Account**: Development (`345321506926`)

**Create trust policy**: `ec2-trust-policy.json`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Create permission policy**: `ec2-assume-cross-account-policy.json`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::448509429610:role/pulldb-cross-account-read"
    }
  ]
}
```

**Create the role**:

```bash
# Create role
aws iam create-role \
  --profile pr-dev \
  --role-name pulldb-ec2-service-role \
  --assume-role-policy-document file://ec2-trust-policy.json \
  --description "EC2 instance role for pullDB daemon"

# Attach assume-role permission
aws iam put-role-policy \
  --profile pr-dev \
  --role-name pulldb-ec2-service-role \
  --policy-name AssumeProductionReadRole \
  --policy-document file://ec2-assume-cross-account-policy.json
```

### Step 2.2: Create Instance Profile

```bash
# Create instance profile
aws iam create-instance-profile \
  --profile pr-dev \
  --instance-profile-name pulldb-ec2-instance-profile

# Add role to instance profile
aws iam add-role-to-instance-profile \
  --profile pr-dev \
  --instance-profile-name pulldb-ec2-instance-profile \
  --role-name pulldb-ec2-service-role
```

### Step 2.3: Attach Instance Profile to EC2 Instance

```bash
# Get instance ID
INSTANCE_ID=$(ec2-metadata --instance-id | cut -d " " -f 2)

# Attach instance profile
aws ec2 associate-iam-instance-profile \
  --profile pr-dev \
  --instance-id $INSTANCE_ID \
  --iam-instance-profile Name=pulldb-ec2-instance-profile
```

**Note**: If the instance already has a different instance profile, you'll need to replace it:

```bash
# Get association ID
ASSOCIATION_ID=$(aws ec2 describe-iam-instance-profile-associations \
  --profile pr-dev \
  --filters "Name=instance-id,Values=$INSTANCE_ID" \
  --query 'IamInstanceProfileAssociations[0].AssociationId' \
  --output text)

# Disassociate old profile
aws ec2 disassociate-iam-instance-profile \
  --profile pr-dev \
  --association-id $ASSOCIATION_ID

# Associate new profile
aws ec2 associate-iam-instance-profile \
  --profile pr-dev \
  --instance-id $INSTANCE_ID \
  --iam-instance-profile Name=pulldb-ec2-instance-profile
```

---

## Part 3: Daemon Configuration (System Service)

Configure the daemon process to use EC2 instance profile credentials.

### Step 3.1: Create Daemon User

```bash
# Create system user
sudo adduser --system --group --home /var/lib/pulldb pulldb

# Create working directories
sudo mkdir -p /var/lib/pulldb/work
sudo mkdir -p /var/lib/pulldb/.aws
sudo chown -R pulldb:pulldb /var/lib/pulldb
```

### Step 3.2: Configure AWS Profile for Daemon

**Create AWS config for daemon**: `/var/lib/pulldb/.aws/config`

```bash
sudo tee /var/lib/pulldb/.aws/config > /dev/null <<'EOF'
[default]
region = us-east-1

[profile pr-prod-via-instance]
role_arn = arn:aws:iam::448509429610:role/pulldb-cross-account-read
credential_source = Ec2InstanceMetadata
external_id = pulldb-cross-account-2024
region = us-east-1
EOF

sudo chown pulldb:pulldb /var/lib/pulldb/.aws/config
sudo chmod 600 /var/lib/pulldb/.aws/config
```

**Key Configuration**:
- `credential_source = Ec2InstanceMetadata` - Gets credentials from instance metadata (no access keys)
- `role_arn` - Cross-account role to assume
- `external_id` - Security token for cross-account access

### Step 3.3: Test Daemon AWS Access

```bash
# Test as pulldb user - get instance role identity
sudo -u pulldb AWS_PROFILE=pr-prod-via-instance \
  aws sts get-caller-identity

# Should show:
# {
#   "UserId": "AROA...:i-...",
#   "Account": "448509429610",
#   "Arn": "arn:aws:sts::448509429610:assumed-role/pulldb-cross-account-read/i-..."
# }

# Test S3 access
sudo -u pulldb AWS_PROFILE=pr-prod-via-instance \
  aws s3 ls s3://pestroutesrdsdbs/daily/stg/
```

### Step 3.4: Configure Daemon Environment

**Create**: `/etc/pulldb/daemon.env`

```bash
sudo mkdir -p /etc/pulldb
sudo tee /etc/pulldb/daemon.env > /dev/null <<'EOF'
# AWS Configuration
PULLDB_AWS_PROFILE=pr-prod-via-instance

# S3 Configuration
PULLDB_S3_BUCKET_PATH=s3://pestroutesrdsdbs/daily/stg/

# MySQL Configuration (coordination database)
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_USER=pulldb
PULLDB_MYSQL_PASSWORD=your_daemon_password
PULLDB_MYSQL_DATABASE=pulldb

# Working Directories
PULLDB_WORK_DIR=/var/lib/pulldb/work
PULLDB_CUSTOMERS_AFTER_SQL_DIR=/opt/pulldb/customers_after_sql
PULLDB_QA_TEMPLATE_AFTER_SQL_DIR=/opt/pulldb/qa_template_after_sql
EOF

sudo chmod 600 /etc/pulldb/daemon.env
sudo chown root:root /etc/pulldb/daemon.env
```

### Step 3.5: Create Systemd Service

**Create**: `/etc/systemd/system/pulldb-daemon.service`

```ini
[Unit]
Description=pullDB Daemon - Database Restore Service
Documentation=https://github.com/PestRoutes/infra.devops/tree/main/Tools/pullDB
After=network.target mysql.service
Requires=mysql.service

[Service]
Type=simple
User=pulldb
Group=pulldb
WorkingDirectory=/var/lib/pulldb

# Load environment variables
EnvironmentFile=/etc/pulldb/daemon.env

# Set HOME for AWS credential chain
Environment="HOME=/var/lib/pulldb"

# Start daemon
ExecStart=/usr/local/bin/pulldb-daemon

# Restart policy
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pulldb-daemon

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/pulldb /tmp/pulldb-work

[Install]
WantedBy=multi-user.target
```

**Enable and start the service**:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pulldb-daemon
sudo systemctl start pulldb-daemon
sudo systemctl status pulldb-daemon

# View logs
sudo journalctl -u pulldb-daemon -f
```

---

## Part 4: CLI Configuration (No AWS Access)

The CLI does **NOT** need AWS credentials or MySQL access. It calls the daemon's REST API.

### Step 4.1: Create CLI Wrapper Script

**Create**: `/usr/local/bin/pullDB` (wrapper script)

```bash
sudo tee /usr/local/bin/pullDB > /dev/null <<'EOFWRAPPER'
#!/bin/bash
set -euo pipefail

# Get the actual user (not root if using sudo)
ACTUAL_USER="${SUDO_USER:-${USER}}"

# Validate user is in allowed group
if ! groups "$ACTUAL_USER" | grep -q "pulldb-users"; then
    echo "ERROR: User $ACTUAL_USER is not authorized to use pullDB" >&2
    echo "Contact your administrator to be added to the pulldb-users group" >&2
    exit 1
fi

# Inject user= parameter if not already provided
if [[ ! "$*" =~ user= ]]; then
    exec /usr/local/bin/pulldb-cli "user=$ACTUAL_USER" "$@"
else
    # Validate user= matches actual user (prevent spoofing)
    if [[ "$*" =~ user=([^[:space:]]+) ]]; then
        PROVIDED_USER="${BASH_REMATCH[1]}"
        if [[ "$PROVIDED_USER" != "$ACTUAL_USER" ]]; then
            echo "ERROR: user= parameter ($PROVIDED_USER) does not match authenticated user ($ACTUAL_USER)" >&2
            exit 1
        fi
    fi
    exec /usr/local/bin/pulldb-cli "$@"
fi
EOFWRAPPER

sudo chmod 755 /usr/local/bin/pullDB
sudo chown root:root /usr/local/bin/pullDB
```

**Key Features**:
- ✅ Validates user authorization via group membership
- ✅ Automatically injects `user=` parameter from SSH identity
- ✅ Prevents user spoofing (can't fake identity)
- ❌ **NO AWS credential handling** (not needed!)
- ❌ **NO MySQL credential handling** (not needed!)

### Step 4.2: Create User Authorization Group

```bash
# Create group for authorized users
sudo groupadd pulldb-users

# Add users to group
sudo usermod -aG pulldb-users charles.handshy
sudo usermod -aG pulldb-users john.doe

# Verify membership
groups charles.handshy
```

### Step 4.3: Configure CLI API Endpoint

The CLI needs to know where to reach the daemon's REST API.

**Option 1**: Use environment variable (per user)

```bash
# In ~/.bashrc or ~/.profile
export PULLDB_API_URL=http://localhost:8080
```

**Option 2**: Use global config file

```bash
# Create shared config
sudo mkdir -p /etc/pulldb
sudo tee /etc/pulldb/cli.conf > /dev/null <<'EOF'
[api]
url = http://localhost:8080
timeout = 30
EOF

sudo chmod 644 /etc/pulldb/cli.conf
```

### Step 4.4: Test CLI Access

```bash
# As developer (no AWS or MySQL credentials needed!)
pullDB customer=acme

# Output:
# [pulldb] Job queued successfully
# Job ID: 550e8400-e29b-41d4-a716-446655440000
# Job ID: 550e8400-e29b-41d4-a716-446655440000
# User: charles.handshy
# Target: charlesacme
# Status: pending
#
# The restore will be processed by the daemon shortly.
# Use 'pullDB status' to check progress.
```

**What happened**:
1. Wrapper validated you're in `pulldb-users` group
2. Wrapper injected `user=charles.handshy`
3. CLI validated options and generated target name
4. CLI called daemon REST API: `POST /api/jobs` with job details
5. Daemon validated, inserted job into MySQL, returned job ID
6. **No AWS calls made by CLI** - daemon will handle that

---

## Part 5: Developer Onboarding (Simple!)

Adding a new developer is trivial - no AWS setup needed.

### Onboard New Developer

```bash
# 1. Create system account (if not exists)
sudo adduser john.doe

# 2. Add to pulldb-users group
sudo usermod -aG pulldb-users john.doe

# 3. Done! Developer can now use pullDB
```

That's it! No:
- ❌ AWS IAM user creation
- ❌ Access key generation
- ❌ Profile configuration
- ❌ Credential distribution

### Offboard Developer

```bash
# Remove from group
sudo gpasswd -d john.doe pulldb-users

# Optional: disable system account
sudo usermod -L john.doe
```

---

## Summary: How It All Works Together

### Developer Flow

```
Developer                    CLI                  Daemon API              Daemon Worker
    |                         |                        |                         |
    |-- pullDB customer=acme->|                        |                         |
    |                         |                        |                         |
    |                         |-- POST /api/jobs ----->|                         |
    |                         |   (user, customer)     |                         |
    |                         |                        |-- Validate ------------>|
    |                         |                        |-- Insert to MySQL ----->|
    |                         |<-- 201 Created --------|                         |
    |                         |    Job ID: 550e8400    |                         |
    |<-- "Job queued" --------|                        |                         |
    |                         |                        |                         |
    |                                                   |                         |-- Poll MySQL
    |                                                   |                         |-- Get S3 backup
    |                                                   |                         |-- Extract archive
    |                                                   |                         |-- Restore to MySQL
    |                                                   |                         |-- Update status
    |                         |                        |                         |
    |-- pullDB status ------->|                        |                         |
    |                         |-- GET /api/jobs ------>|                         |
    |                         |                        |-- Query MySQL --------->|
    |                         |<-- 200 OK -------------|                         |
    |                         |    Job list            |                         |
    |<-- "Running (65%)" -----|                        |                         |
```

### Authentication Model

| Component | Needs AWS? | Gets Identity From | Accesses |
|-----------|------------|-------------------|----------|
| **Developer** | ❌ No | SSH username | CLI only |
| **CLI** | ❌ No | User parameter | Daemon API only |
| **Daemon** | ✅ Yes | EC2 instance metadata | MySQL + S3 |

### Security Model

```
Developer (charles.handshy)
  ↓ SSH authentication
EC2 Instance
  ↓ Group membership check (pulldb-users)
CLI Wrapper
  ↓ Inject user=charles.handshy
CLI Binary
  ↓ Validate + Call daemon API
Daemon REST API
  ↓ Insert job into MySQL
MySQL Database (jobs table)
  ↓ Poll pending jobs
Daemon Worker (pulldb user)
  ↓ EC2 instance profile
EC2 Instance Metadata Service
  ↓ Temporary credentials
Assume Cross-Account Role
  ↓ Read access
Production S3 Bucket
```

### Key Benefits

| Aspect | Old Model (Developer AWS Access) | New Model (Daemon Only) |
|--------|----------------------------------|-------------------------|
| **Developer setup** | IAM user + keys + profile config | Add to Unix group |
| **AWS credentials** | N developers + 1 daemon | 1 daemon only |
| **Credential rotation** | N users × quarterly | 1 daemon × automatic |
| **Audit trail** | Mixed (AWS + MySQL) | Clean (MySQL only) |
| **Security surface** | Large (N credential sets) | Minimal (1 credential) |
| **Onboarding time** | 30 minutes | 30 seconds |
| **CLI testing** | Needs AWS access | Works offline |

---

## Troubleshooting

### CLI: User Not Authorized

```bash
# Error: User john.doe is not authorized to use pullDB

# Check group membership
groups john.doe | grep pulldb-users

# Add to group if missing
sudo usermod -aG pulldb-users john.doe

# User needs to log out and back in for group change to take effect
```

### CLI: Cannot Connect to Daemon API

```bash
# Error: Connection refused to http://localhost:8080

# Check daemon is running
sudo systemctl status pulldb-daemon

# Check API is listening
sudo netstat -tlnp | grep 8080

# Test API endpoint
curl http://localhost:8080/api/health

# Check firewall (if daemon on different host)
sudo ufw status | grep 8080
```

### Daemon: Cannot Assume Role

```bash
# Check instance profile is attached
curl http://169.254.169.254/latest/meta-data/iam/info

# Output should show:
# {
#   "InstanceProfileArn": "arn:aws:iam::345321506926:instance-profile/pulldb-ec2-instance-profile",
#   ...
# }

# If no instance profile, attach it
INSTANCE_ID=$(ec2-metadata --instance-id | cut -d " " -f 2)
aws ec2 associate-iam-instance-profile \
  --instance-id $INSTANCE_ID \
  --iam-instance-profile Name=pulldb-ec2-instance-profile
```

### Daemon: Cannot Access S3

```bash
# Test as daemon user
sudo -u pulldb AWS_PROFILE=pr-prod-via-instance \
  aws sts get-caller-identity

# Should show assumed role in production account (448509429610)

# Test S3 access
sudo -u pulldb AWS_PROFILE=pr-prod-via-instance \
  aws s3 ls s3://pestroutesrdsdbs/daily/stg/ --debug

# Check role trust policy allows dev account
aws iam get-role \
  --profile pr-prod \
  --role-name pulldb-cross-account-read \
  --query 'Role.AssumeRolePolicyDocument'
```

### Daemon: ExternalId Mismatch

```bash
# Verify external ID in role trust policy (production)
aws iam get-role \
  --profile pr-prod \
  --role-name pulldb-cross-account-read \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'

# Verify external ID in daemon config
sudo cat /var/lib/pulldb/.aws/config | grep external_id

# Must match exactly: pulldb-cross-account-2024
```

---

## Security Considerations

### Why Isolate Developers from AWS and MySQL?

**Problem**: Giving developers AWS or MySQL credentials creates security risks:
- Developers can bypass audit trail
- Developers could access S3 or MySQL directly (bypassing application logic)
- More credentials = larger attack surface
- Credential leaks affect all developers

**Solution**: CLI has no AWS or MySQL access:
- ✅ All actions go through daemon API (complete audit trail)
- ✅ Application logic cannot be bypassed
- ✅ Minimal attack surface (1 credential set for AWS, 1 for MySQL)
- ✅ Developer credential leak = no AWS/MySQL impact

### Defense in Depth

```
Layer 1: SSH Authentication
  → User must have valid SSH access to EC2 instance

Layer 2: Group Authorization
  → User must be in pulldb-users group

Layer 3: CLI Validation
  → User identity injected and validated by wrapper

Layer 4: MySQL Authorization
  → User must be registered in auth_users table

Layer 5: Daemon Isolation
  → Daemon runs as separate user with AWS access

Layer 6: Cross-Account Role
  → Daemon must successfully assume production role

Layer 7: S3 Bucket Policy
  → Role must have explicit read permissions
```

### Instance Profile Benefits

1. **No Secrets on Disk**: Credentials exist only in memory
2. **Auto-Rotation**: AWS rotates every 60 minutes automatically
3. **Audit Trail**: CloudTrail shows EC2 instance as actor
4. **Revocation**: Detach instance profile to revoke immediately
5. **Least Privilege**: Single identity with minimum required permissions

### Why This is Better

| Security Principle | Implementation |
|-------------------|----------------|
| **Principle of Least Privilege** | Developers get NO AWS/MySQL access, only what they need (daemon API) |
| **Defense in Depth** | Multiple layers: SSH → Group → CLI → API → Daemon → MySQL → AWS |
| **Audit Trail** | All developer actions logged by daemon in MySQL with username |
| **Credential Rotation** | Automatic via EC2 instance metadata (no manual rotation) |
| **Separation of Concerns** | CLI = validation/UI, Daemon = API/business logic/AWS integration |

---

## Next Steps

1. **Part 1**: Set up cross-account role in production (15 minutes)
2. **Part 2**: Configure EC2 instance profile in dev (10 minutes)
3. **Part 3**: Set up daemon service (20 minutes)
4. **Part 4**: Deploy CLI wrapper (10 minutes)
5. **Part 5**: Onboard first developer (2 minutes)
6. **Test**: Submit job and verify daemon processes it (5 minutes)

**Total Setup Time**: ~1 hour (one-time setup)
**Per-Developer Time**: 2 minutes (ongoing)

## Related Documentation

- [Configuration Guide](../README.md#configuration) - Environment variable reference
- [Security Model](../design/security-model.md) - Overall security architecture
- [MySQL Schema](../docs/sqlite-schema.md) - Database structure
- [System Overview](../design/system-overview.md) - Architecture diagrams
