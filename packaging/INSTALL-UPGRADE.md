# pullDB Installation & Upgrade Guide

> **Version**: 0.2.0 | **Last Updated**: January 2, 2026

This guide covers installing and upgrading pullDB packages on a database server.

> **Note**: Fresh installs automatically create an admin user with a random password.
> Save the credentials displayed during installation!

---

## System Requirements

### Recommended

| Component | Requirement |
|-----------|-------------|
| **Operating System** | Ubuntu 22.04 LTS or Ubuntu 24.04 LTS |
| **Python** | 3.12+ (included in Ubuntu 22.04+) |
| **MySQL** | 8.0+ |
| **Disk Space** | 50GB+ for work directory |
| **Memory** | 4GB+ RAM |

### Legacy Support (Ubuntu 20.04)

Ubuntu 20.04 ships with Python 3.8, but pullDB requires Python 3.12+.

**Option 1: Build Python 3.12 from source** (recommended for Ubuntu 20.04):

```bash
# Install build dependencies
sudo apt-get update
sudo apt-get install -y build-essential zlib1g-dev libncurses5-dev \
    libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev \
    libsqlite3-dev wget libbz2-dev

# Download Python 3.12
cd /tmp
wget https://www.python.org/ftp/python/3.12.4/Python-3.12.4.tgz
tar -xf Python-3.12.4.tgz
cd Python-3.12.4

# Build and install (takes ~10 minutes)
./configure --enable-optimizations --prefix=/usr/local
make -j$(nproc)
sudo make altinstall

# Verify installation
python3.12 --version
# Python 3.12.4

# Now install pullDB
sudo dpkg -i pulldb-client_*.deb
# or
sudo dpkg -i pulldb_*.deb
```

> **Note**: `make altinstall` installs Python 3.12 alongside system Python 3.8.
> System Python remains unchanged. Ubuntu 20.04 will reach end of standard support
> in April 2025; consider upgrading to Ubuntu 22.04 LTS.

**Option 2: Upgrade to Ubuntu 22.04** (recommended for production):

Ubuntu 22.04 includes Python 3.10 by default, and Python 3.12 is available via:
```bash
sudo apt-get install python3.12 python3.12-venv
```

---

## Available Packages

| Package | Purpose | Install Path |
|---------|---------|--------------|
| `pulldb` | Full server (worker + API + web) | `/opt/pulldb.service` |
| `pulldb-client` | CLI only (no services) | `/opt/pulldb.client` |

---

## Quick Reference

| Task | Command |
|------|---------|
| Install server package | `sudo dpkg -i pulldb_X.X.X_amd64.deb` |
| Install CLI client | `sudo dpkg -i pulldb-client_X.X.X_amd64.deb` |
| Check migration status | `sudo /opt/pulldb.service/scripts/pulldb-migrate.sh status` |
| Apply migrations | `sudo /opt/pulldb.service/scripts/pulldb-migrate.sh up` |
| Verify schema | `sudo /opt/pulldb.service/scripts/pulldb-migrate.sh verify` |
| Check all services | `sudo systemctl status pulldb-worker pulldb-api pulldb-web` |
| View settings | `sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list` |

---

## Fresh Installation

### Server Package (Full Install)

#### Step 1: Install the Package

```bash
sudo dpkg -i pulldb_0.2.0_amd64.deb
```

The package will:
- Create Linux system user `pulldb_service`
- Install files to `/opt/pulldb.service/`
- Create `pulldb_service` database and apply schema (if MySQL accessible)
- **Create initial admin user with random password** (displayed at end of install)
- **Create `pulldb_service` service account** (for systemd scheduled tasks)
- Set up systemd services (enabled but may not start without config)

> **IMPORTANT**: Save the admin credentials displayed at the end of installation!
> They are also saved to `/opt/pulldb.service/ADMIN_CREDENTIALS.txt` (root-only readable).

**Note on Service Account**: The `pulldb_service` account in the database is a Service Bootstrap/CLI Admin Account (SBCACC). It allows systemd services like `pulldb-retention.timer` to execute admin CLI commands. This account has no password and cannot be used for web login.

#### Step 2: Configure Environment

Edit the configuration file:

```bash
sudo nano /opt/pulldb.service/.env
```

Required settings:
```bash
# AWS credentials (for Secrets Manager access)
PULLDB_AWS_PROFILE=pr-dev
AWS_DEFAULT_REGION=us-east-1

# Coordination database secret
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db

# MySQL users
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker
```

### Step 3: Install dbmate (if not present)

```bash
sudo /opt/pulldb.service/scripts/install-dbmate.sh
```

### Step 4: Apply Database Migrations

```bash
# Check what migrations are pending
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh status

# Apply all pending migrations
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh up

# Verify schema is correct
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh verify
```

### Step 5: Start Services

```bash
sudo systemctl start pulldb-worker
sudo systemctl start pulldb-api

# Verify they're running
sudo systemctl status pulldb-worker pulldb-api
```

### Step 6: Verify Installation

```bash
# Check settings are loading
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list

# Check version
sudo /opt/pulldb.service/venv/bin/pulldb --version
```

---

### Web UI Service

The web UI is included in the server package and runs on port 8000.

#### Enable the Web Service

```bash
# Enable and start the web UI
sudo systemctl enable --now pulldb-web

# Verify it's running
sudo systemctl status pulldb-web
```

The web UI uses the same configuration file as the server (`/opt/pulldb.service/.env`).

#### Access the Web UI

Open a browser and navigate to:
```
http://<server-ip>:8000
```

Log in with the admin credentials displayed during installation (or check `/opt/pulldb.service/ADMIN_CREDENTIALS.txt`).

---

### CLI Client Package (CLI Only)

For systems that only need CLI access (no background services):

```bash
sudo dpkg -i pulldb-client_0.2.0_amd64.deb

# Verify installation
pulldb --help
```

---

## Upgrading

> **IMPORTANT**: `dpkg -i` installs files but does NOT automatically run database migrations.

### Standard Upgrade Process

```bash
# Step 1: Install the new package
sudo dpkg -i pulldb_0.0.4_amd64.deb

# Step 2: Check for pending migrations
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh status

# Step 3: Apply migrations
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh up

# Step 4: Verify schema
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh verify

# Step 5: Restart services (to pick up code changes)
sudo systemctl restart pulldb-worker pulldb-api

# Step 6: Verify
sudo /opt/pulldb.service/venv/bin/pulldb --version
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list
```

### Using the Upgrade Script

For convenience, there's an upgrade script that handles steps 2-5:

```bash
# Install package first
sudo dpkg -i pulldb_0.0.4_amd64.deb

# Then run upgrade script
sudo /opt/pulldb.service/scripts/upgrade_pulldb.sh
```

The upgrade script will:
1. Stop the worker service
2. Run `pulldb-migrate up --yes`
3. Update Python packages
4. Restart the worker service

### Rollback (if needed)

If a migration fails:

```bash
# Check what went wrong
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh status

# Rollback last migration
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh rollback

# Install previous version
sudo dpkg -i pulldb_0.0.3_amd64.deb
```

---

## Command Reference (Full Paths)

### Migration Commands

```bash
# Check migration status
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh status

# Apply pending migrations
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh up

# Apply without confirmation prompt
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh up --yes

# Rollback last migration
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh rollback

# Verify schema integrity
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh verify

# Wait for database to be available
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh wait

# Create new migration
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh new <migration_name>
```

### Admin Commands

```bash
# List all settings
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list

# Get specific setting
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings get <key>

# Set a value (updates both db and .env)
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings set <key> <value>

# Show differences between db and .env
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings diff

# Sync database → .env
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings pull

# Sync .env → database
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings push

# List jobs
sudo /opt/pulldb.service/venv/bin/pulldb-admin jobs list

# List active jobs only
sudo /opt/pulldb.service/venv/bin/pulldb-admin jobs list --active
```

### Service Commands

```bash
# Start services
sudo systemctl start pulldb-worker
sudo systemctl start pulldb-api

# Stop services
sudo systemctl stop pulldb-worker
sudo systemctl stop pulldb-api

# Restart services
sudo systemctl restart pulldb-worker pulldb-api

# Check status
sudo systemctl status pulldb-worker pulldb-api

# View logs
sudo journalctl -u pulldb-worker -f
sudo journalctl -u pulldb-api -f

# View recent errors
sudo journalctl -u pulldb-worker -p err --since "1 hour ago"
```

### Utility Scripts

```bash
# Interactive configuration wizard
sudo /opt/pulldb.service/scripts/configure-pulldb.sh

# Validate service installation
sudo /opt/pulldb.service/scripts/service-validate.sh

# Monitor active jobs
sudo /opt/pulldb.service/scripts/monitor_jobs.py

# Uninstall (removes package, keeps data)
sudo /opt/pulldb.service/scripts/uninstall_pulldb.sh
```

---

## File Locations

| Path | Description |
|------|-------------|
| `/opt/pulldb.service/` | Main installation directory |
| `/opt/pulldb.service/.env` | Environment configuration |
| `/opt/pulldb.service/venv/` | Python virtual environment |
| `/opt/pulldb.service/scripts/` | Utility scripts |
| `/opt/pulldb.service/migrations/` | Database migration files |
| `/opt/pulldb.service/bin/` | Binary tools (myloader, dbmate) |
| `/opt/pulldb.service/logs/` | Application logs |
| `/opt/pulldb.service/work/` | Working directory for restores |
| `/mnt/data/work/pulldb.service/` | Default work directory (configurable) |
| `/mnt/data/logs/pulldb.service/` | Default log directory (configurable) |

---

## Troubleshooting

### Package Installation Fails

```bash
# Check for dependency issues
sudo apt-get install -f

# View package info
dpkg -I pulldb_0.0.4_amd64.deb

# View package contents
dpkg -c pulldb_0.0.4_amd64.deb
```

### Migration Fails

```bash
# Check status
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh status

# Enable verbose mode
sudo /opt/pulldb.service/scripts/pulldb-migrate.sh --verbose up

# Check database directly
sudo mysql -e "SELECT * FROM pulldb_service.schema_migrations"
```

### Services Won't Start

```bash
# Check logs
sudo journalctl -u pulldb-worker -n 50 --no-pager

# Validate configuration
sudo /opt/pulldb.service/scripts/service-validate.sh

# Check .env file
sudo cat /opt/pulldb.service/.env

# Test Python import
sudo /opt/pulldb.service/venv/bin/python -c "import pulldb; print('OK')"
```

### Settings Not Loading

```bash
# Check what's in .env
sudo grep -v '^#' /opt/pulldb.service/.env | grep -v '^$'

# Check database connection
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list

# Audit differences
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings diff
```

---

## Version History

| Version | Date | Key Changes |
|---------|------|-------------|
| 0.0.4 | 2025-11-28 | Settings sync (pull/push/diff), AWS region fix |
| 0.0.3 | 2025-11-27 | Phase 2 concurrency controls |
| 0.0.2 | 2025-11-20 | Phase 1 cancellation support |
| 0.0.1 | 2025-11-15 | Initial release |
