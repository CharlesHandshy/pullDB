# pullDB Installation Guide

> **Version**: 0.0.4 | **Last Updated**: November 28, 2025

This guide covers installing, configuring, and upgrading pullDB components.

---

## Components

pullDB has two distribution packages:

| Package | Purpose | Install On |
|---------|---------|------------|
| `pulldb_X.X.X_amd64.deb` | Worker + API services | Database servers |
| `pulldb-client_X.X.X_amd64.deb` | CLI tools only | Developer workstations |

---

## Prerequisites

### System Requirements

- **OS**: Ubuntu 22.04 LTS or Debian 12+
- **Architecture**: x86_64 (amd64)
- **RAM**: 4GB minimum, 8GB recommended
- **Disk**: 50GB+ free in work directory

### Dependencies

**Service Package:**
- MySQL 8.0+
- AWS CLI v2
- Python 3.11+

**Client Package:**
- Python 3.11+
- Network access to pulldb-api

---

## Quick Install

### Client (Developer Workstation)

```bash
# Download latest client package
curl -O https://releases.example.com/pulldb-client_0.0.4_amd64.deb

# Install
sudo dpkg -i pulldb-client_0.0.4_amd64.deb

# Configure
mkdir -p ~/.pulldb
cat > ~/.pulldb/config.yaml << 'EOF'
api:
  url: https://pulldb-api.example.com
  auth_token: ${PULLDB_AUTH_TOKEN}
EOF

# Verify
pulldb --version
```

### Service (Database Server)

```bash
# Download service package
curl -O https://releases.example.com/pulldb_0.0.4_amd64.deb

# Install
sudo dpkg -i pulldb_0.0.4_amd64.deb

# Run initial setup
sudo /opt/pulldb.service/scripts/install_pulldb.sh

# Verify
sudo systemctl status pulldb-worker
pulldb-admin settings list
```

---

## Detailed Installation

### 1. Install Package

```bash
# Service package
sudo dpkg -i pulldb_0.0.4_amd64.deb

# If dependencies fail
sudo apt-get install -f
```

**What gets installed:**

| Path | Contents |
|------|----------|
| `/opt/pulldb.service/` | Service files, venv, binaries |
| `/opt/pulldb.service/bin/` | dbmate, myloader |
| `/opt/pulldb.service/config/` | Configuration files |
| `/opt/pulldb.service/migrations/` | Database migrations |
| `/opt/pulldb.service/scripts/` | Utility scripts |
| `/usr/local/bin/pulldb*` | CLI command symlinks |
| `/etc/systemd/system/pulldb-*.service` | systemd unit files |

### 2. Configure MySQL

**Create coordination database:**

```bash
sudo mysql << 'EOF'
-- Create database
CREATE DATABASE IF NOT EXISTS pulldb_service 
  CHARACTER SET utf8mb4 
  COLLATE utf8mb4_unicode_ci;

-- Create service users
CREATE USER IF NOT EXISTS 'pulldb_worker'@'localhost' IDENTIFIED BY 'worker_password';
CREATE USER IF NOT EXISTS 'pulldb_migrate'@'localhost' IDENTIFIED BY 'migrate_password';

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.* TO 'pulldb_worker'@'localhost';
GRANT ALL PRIVILEGES ON pulldb_service.* TO 'pulldb_migrate'@'localhost';

FLUSH PRIVILEGES;
EOF
```

**Apply migrations:**

```bash
sudo pulldb-migrate up --yes
```

### 3. Configure AWS

**Set up AWS credentials:**

```bash
# Option 1: IAM role (EC2 instances) - Recommended
# Attach appropriate IAM role to EC2 instance

# Option 2: Shared credentials file
aws configure
# Enter AWS Access Key ID, Secret, and region

# Option 3: Environment variables
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
```

**Store secrets in AWS Secrets Manager:**

```bash
# Store MySQL credentials
aws secretsmanager create-secret \
  --name /pulldb/mysql/coordination-db \
  --secret-string '{"username":"pulldb_worker","password":"worker_password","host":"localhost","port":3306,"database":"pulldb_service"}'
```

### 4. Configure pullDB

**Edit configuration:**

```bash
sudo nano /opt/pulldb.service/config/pulldb.yaml
```

**Minimal configuration:**

```yaml
# Coordination database
coordination_db:
  secret_id: aws-secretsmanager:/pulldb/mysql/coordination-db

# S3 backup source
s3:
  bucket: your-backup-bucket
  prefix: backups/

# Worker settings
worker:
  poll_interval: 10
  work_dir: /opt/pulldb.service/work
```

### 5. Start Services

```bash
# Enable and start worker
sudo systemctl enable pulldb-worker
sudo systemctl start pulldb-worker

# Verify
sudo systemctl status pulldb-worker
```

### 6. Verify Installation

```bash
# Check service status
sudo systemctl status pulldb-worker

# Check database schema
sudo pulldb-migrate verify

# Check settings
pulldb-admin settings list

# Test a restore (dry run)
pulldb restore mydb --to staging_mydb --dry-run
```

---

## Client Installation

### From Package

```bash
# Install client package
sudo dpkg -i pulldb-client_0.0.4_amd64.deb
```

### From Source

```bash
# Clone repository
git clone https://github.com/your-org/pulldb.git
cd pulldb

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install
pip install -e .

# Verify
pulldb --version
```

### Client Configuration

**Create config file:**

```bash
mkdir -p ~/.pulldb
cat > ~/.pulldb/config.yaml << 'EOF'
# API endpoint
api:
  url: https://pulldb-api.example.com
  timeout: 300

# Default restore settings
restore:
  target_host: localhost
  wait: true
EOF
```

**Environment variables:**

```bash
# Add to ~/.bashrc or ~/.zshrc
export PULLDB_API_URL=https://pulldb-api.example.com
export PULLDB_AUTH_TOKEN=your_auth_token
```

---

## Upgrade

### Package Upgrade

```bash
# Download new version
curl -O https://releases.example.com/pulldb_0.0.4_amd64.deb

# Install (handles service restart)
sudo dpkg -i pulldb_0.0.4_amd64.deb

# Verify
pulldb --version
pulldb-admin settings list
```

### Manual Upgrade

```bash
# Stop services
sudo systemctl stop pulldb-worker pulldb-api

# Backup configuration
sudo cp -a /opt/pulldb.service/config /opt/pulldb.service/config.backup

# Apply migrations
sudo pulldb-migrate up --yes

# Update packages
sudo /opt/pulldb.service/venv/bin/pip install --upgrade pulldb

# Restart services
sudo systemctl start pulldb-worker pulldb-api

# Verify
sudo pulldb-migrate verify
pulldb-admin settings list
```

### Using Upgrade Script

```bash
sudo /opt/pulldb.service/scripts/upgrade_pulldb.sh
```

---

## Configuration Reference

### Complete Configuration File

```yaml
# /opt/pulldb.service/config/pulldb.yaml

# MySQL coordination database
coordination_db:
  # Option 1: AWS Secrets Manager (recommended)
  secret_id: aws-secretsmanager:/pulldb/mysql/coordination-db
  
  # Option 2: Direct credentials (not recommended)
  # host: localhost
  # port: 3306
  # database: pulldb_service
  # username: pulldb_worker
  # password: secret

# S3 backup source
s3:
  bucket: your-backup-bucket
  prefix: backups/
  region: us-east-1

# Worker service settings
worker:
  poll_interval: 10           # Seconds between job polls
  work_dir: /opt/pulldb.service/work
  max_concurrent_jobs: 2      # Per-worker limit
  cleanup_interval: 300       # Seconds between cleanup runs

# myloader settings
myloader:
  binary: /opt/pulldb.service/bin/myloader
  threads: 4
  overwrite_tables: true
  default_charset: utf8mb4

# Logging
logging:
  level: INFO                 # DEBUG, INFO, WARNING, ERROR
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: /opt/pulldb.service/logs/worker.log
```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `PULLDB_CONFIG` | Config file path | `/opt/pulldb.service/config/pulldb.yaml` |
| `PULLDB_LOG_LEVEL` | Logging level | `INFO` |
| `PULLDB_WORK_DIR` | Work directory | `/opt/pulldb.service/work` |
| `PULLDB_COORDINATION_SECRET` | AWS secret ID | `aws-secretsmanager:/pulldb/mysql/coordination-db` |
| `AWS_REGION` | AWS region | `us-east-1` |

---

## Multi-Host Setup

For production environments with multiple database hosts:

### Architecture

```
                    ┌─────────────────┐
                    │  pulldb-api     │
                    │  (single host)  │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ worker-1 │   │ worker-2 │   │ worker-3 │
        │ (host-1) │   │ (host-2) │   │ (host-3) │
        └──────────┘   └──────────┘   └──────────┘
```

### Setup Steps

1. **Install on each database host:**
```bash
sudo dpkg -i pulldb_0.0.4_amd64.deb
```

2. **Share coordination database:**
   - All workers connect to same MySQL coordination database
   - Use remote MySQL or RDS

3. **Configure each worker:**
```yaml
# /opt/pulldb.service/config/pulldb.yaml
coordination_db:
  host: coordination-mysql.example.com  # Shared
  port: 3306
  database: pulldb_service
```

4. **Register target hosts:**
```bash
# On each worker, register as target host
pulldb-admin hosts add db-server-1.example.com
pulldb-admin hosts add db-server-2.example.com
```

---

## Uninstall

### Remove Package

```bash
# Stop services
sudo systemctl stop pulldb-worker pulldb-api

# Remove package
sudo dpkg -r pulldb

# Remove configuration (optional)
sudo rm -rf /opt/pulldb.service
```

### Clean Database

```bash
sudo mysql << 'EOF'
DROP DATABASE pulldb_service;
DROP USER 'pulldb_worker'@'localhost';
DROP USER 'pulldb_migrate'@'localhost';
FLUSH PRIVILEGES;
EOF
```

---

## Troubleshooting Installation

### Package Installation Fails

```bash
# Check for dependency issues
sudo apt-get install -f

# View package contents
dpkg -c pulldb_0.0.4_amd64.deb

# Check what's installed
dpkg -L pulldb
```

### MySQL Connection Issues

```bash
# Test MySQL connection
mysql -u pulldb_worker -p -e "SELECT 1"

# Check socket location
mysqladmin variables | grep socket

# Test with socket
mysql -u root --socket=/var/run/mysqld/mysqld.sock -e "SELECT 1"
```

### AWS Credentials Issues

```bash
# Verify AWS access
aws sts get-caller-identity

# Test Secrets Manager access
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db

# Test S3 access
aws s3 ls s3://your-backup-bucket/backups/
```

### Service Won't Start

```bash
# Check logs
sudo journalctl -u pulldb-worker -n 50

# Validate configuration
python3 -c "import yaml; yaml.safe_load(open('/opt/pulldb.service/config/pulldb.yaml'))"

# Check permissions
ls -la /opt/pulldb.service/
ls -la /opt/pulldb.service/config/

# Run manually for debugging
sudo /opt/pulldb.service/venv/bin/python -m pulldb.worker.service
```

### Migration Issues

```bash
# Check migration status
sudo pulldb-migrate status

# Verify schema
sudo pulldb-migrate verify

# Check schema_migrations table
sudo mysql -e "SELECT * FROM pulldb_service.schema_migrations"
```

---

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 0.0.4 | 2025-11-28 | Schema drift repair, Phase 2 concurrency |
| 0.0.3 | 2025-11-27 | Phase 2 implementation |
| 0.0.2 | 2025-11-20 | Phase 1 cancellation support |
| 0.0.1 | 2025-11-15 | Initial release |
