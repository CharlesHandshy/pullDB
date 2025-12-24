# pullDB Installation & Upgrade Guide

> **Version**: 0.0.11 | **Last Updated**: December 24, 2025

This guide covers installing and upgrading pullDB on a database server.

---

## Quick Reference

| Task | Command |
|------|---------|
| Install package | `sudo dpkg -i pulldb_X.X.X_amd64.deb` |
| Check migration status | `sudo /opt/pulldb.service/scripts/pulldb-migrate.sh status` |
| Apply migrations | `sudo /opt/pulldb.service/scripts/pulldb-migrate.sh up` |
| Verify schema | `sudo /opt/pulldb.service/scripts/pulldb-migrate.sh verify` |
| Check services | `sudo systemctl status pulldb-worker pulldb-api` |
| View settings | `sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list` |

---

## Fresh Installation

### Step 1: Install the Package

```bash
sudo dpkg -i pulldb_0.0.11_amd64.deb
```

The package will:
- Create system user `pulldb_service`
- Install files to `/opt/pulldb.service/`
- Set up systemd services (enabled but may not start without config)

### Step 2: Configure Environment

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
