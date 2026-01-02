# Getting Started with pullDB

[← Back to Documentation Index](START-HERE.md)

> **Version**: 0.2.0 | **Last Updated**: January 2026

This guide covers installing and configuring pullDB.

**Next Steps:**
- [CLI Reference](cli-reference.md) - Command documentation
- [Architecture](architecture.md) - System design and data flow
- [Deployment](deployment.md) - Service configuration
- [Admin Guide](admin-guide.md) - Maintenance and operations

---

## Quick Start (5 minutes)

### For Developers (CLI Only)

```bash
# Install client package
sudo dpkg -i pulldb-client_0.2.0_amd64.deb

# Set API endpoint
echo 'PULLDB_API_URL=http://pulldb-api.internal:8080' >> ~/.bashrc
source ~/.bashrc

# Verify
pulldb --version
pulldb status
```

### For Server Setup

```bash
# Install service package
sudo dpkg -i pulldb_0.2.0_amd64.deb

# Run setup wizard
sudo /opt/pulldb.service/scripts/install_pulldb.sh

# Start services
sudo systemctl enable --now pulldb-worker pulldb-api
```

---

## Components

| Package | Purpose | Install Location |
|---------|---------|-----------------|
| `pulldb_X.X.X_amd64.deb` | Worker + API services | Database servers |
| `pulldb-client_X.X.X_amd64.deb` | CLI tools only | Developer workstations |

---

## Prerequisites

### System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | Ubuntu 22.04 / Debian 12 | Ubuntu 24.04 |
| Architecture | x86_64 (amd64) | - |
| RAM | 4 GB | 8 GB |
| Disk | 50 GB free | 100 GB free |
| Python | 3.12+ | 3.12 |

### Service Dependencies

- **MySQL 8.0+** - Coordination database
- **AWS CLI v2** - S3 and Secrets Manager access
- **myloader** - Database restore (bundled)

---

## Installation Steps

### Step 1: Install Package

```bash
# Service package (on database servers)
sudo dpkg -i pulldb_0.2.0_amd64.deb

# Fix any missing dependencies
sudo apt-get install -f

# Client package (on developer workstations)
sudo dpkg -i pulldb-client_0.2.0_amd64.deb
```

**Installed Paths:**

| Path | Contents |
|------|----------|
| `/opt/pulldb.service/` | Service files, virtualenv, binaries |
| `/opt/pulldb.service/bin/` | myloader, dbmate |
| `/opt/pulldb.service/migrations/` | Database migrations |
| `/usr/local/bin/pulldb*` | CLI command symlinks |
| `/etc/systemd/system/pulldb-*.service` | systemd units |

### Step 2: Configure MySQL

**Create database and users:**

```bash
sudo mysql << 'EOF'
-- Create coordination database
CREATE DATABASE IF NOT EXISTS pulldb_service 
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create service users (least privilege)
CREATE USER IF NOT EXISTS 'pulldb_api'@'localhost' IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'pulldb_worker'@'localhost' IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'pulldb_migrate'@'localhost' IDENTIFIED BY 'CHANGE_ME';

-- API service permissions
GRANT SELECT, INSERT, UPDATE ON pulldb_service.jobs TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.auth_users TO 'pulldb_api'@'localhost';

-- Worker service permissions
GRANT SELECT, INSERT, UPDATE ON pulldb_service.jobs TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_worker'@'localhost';
GRANT SELECT, UPDATE ON pulldb_service.locks TO 'pulldb_worker'@'localhost';

-- Migration user (full access)
GRANT ALL PRIVILEGES ON pulldb_service.* TO 'pulldb_migrate'@'localhost';

FLUSH PRIVILEGES;
EOF
```

**Apply schema:**

```bash
# Apply schema migrations
sudo pulldb-migrate up --yes

# Or manually apply schema files
cat /opt/pulldb.service/schema/pulldb_service/*.sql | mysql -u pulldb_migrate -p pulldb_service
```

### Step 3: Configure AWS

pullDB uses AWS for:
- **Secrets Manager** - Database credentials (development account)
- **S3** - Backup archives (staging/production accounts)

#### Option A: EC2 Instance Profile (Recommended)

Attach an IAM role with required permissions to your EC2 instance. See [AWS-SETUP.md](AWS-SETUP.md) for complete IAM policy.

#### Option B: AWS CLI Profiles

```bash
# Configure profiles
aws configure --profile pr-dev      # Secrets Manager access
aws configure --profile pr-staging  # S3 staging bucket access
aws configure --profile pr-prod     # S3 production bucket access

# Set environment
cat >> /opt/pulldb.service/.env << 'EOF'
PULLDB_AWS_PROFILE=pr-dev
PULLDB_S3_AWS_PROFILE=pr-staging
EOF
```

#### Required IAM Permissions

**Secrets Manager (pr-dev account):**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ],
    "Resource": "arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/*"
  }]
}
```

**S3 (staging/prod accounts):**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:GetObject",
      "s3:ListBucket",
      "s3:HeadObject"
    ],
    "Resource": [
      "arn:aws:s3:::pestroutesrdsdbs",
      "arn:aws:s3:::pestroutesrdsdbs/*"
    ]
  }]
}
```

### Step 4: Configure Environment

Edit `/opt/pulldb.service/.env`:

```bash
# AWS Configuration
PULLDB_AWS_PROFILE=pr-dev
PULLDB_S3_AWS_PROFILE=pr-staging
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db

# S3 Backup Locations
PULLDB_S3_BACKUP_LOCATIONS=pr-staging:pestroutesrdsdbs/daily/stg,pr-prod:pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod

# Service Users
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker
```

### Step 5: Start Services

```bash
# Enable and start services
sudo systemctl enable pulldb-api pulldb-worker
sudo systemctl start pulldb-api pulldb-worker

# Verify
sudo systemctl status pulldb-api pulldb-worker
curl http://localhost:8080/api/health
```

---

## Verification

### Check Service Health

```bash
# API health
curl -s http://localhost:8080/api/health | jq

# Service status
sudo systemctl status pulldb-api pulldb-worker

# View logs
sudo journalctl -u pulldb-worker -f
```

### Test CLI

```bash
# Check status
pulldb status

# List recent jobs
pulldb history

# Submit test restore (dry run)
pulldb restore --help
```

### Verify AWS Access

```bash
# Check Secrets Manager access
aws --profile pr-dev secretsmanager describe-secret \
  --secret-id /pulldb/mysql/coordination-db

# Check S3 access  
aws --profile pr-staging s3 ls s3://pestroutesrdsdbs/daily/stg/ --max-items 5
```

---

## Next Steps

1. **[CLI Reference](cli-reference.md)** - Learn available commands
2. **[Architecture](architecture.md)** - Understand system design
3. **[Deployment](deployment.md)** - Configure services for production
4. **[Admin Guide](admin-guide.md)** - Manage migrations and cleanup

---

## Troubleshooting

### Common Issues

**"Cannot connect to API"**
```bash
# Check API is running
sudo systemctl status pulldb-api

# Check port binding
ss -tlnp | grep 8080

# Check logs
sudo journalctl -u pulldb-api --since "5 minutes ago"
```

**"Access denied to Secrets Manager"**
```bash
# Verify AWS profile
aws --profile pr-dev sts get-caller-identity

# Check secret exists
aws --profile pr-dev secretsmanager describe-secret \
  --secret-id /pulldb/mysql/coordination-db
```

**"MySQL connection failed"**
```bash
# Test credentials from secret
mysql -u pulldb_api -p -e "SELECT 1"

# Verify database exists
mysql -u root -p -e "SHOW DATABASES LIKE 'pulldb%'"
```

For more troubleshooting, see [AWS-SETUP.md](AWS-SETUP.md#troubleshooting).

---

[← Back to Documentation Index](START-HERE.md) · [CLI Reference →](cli-reference.md)
