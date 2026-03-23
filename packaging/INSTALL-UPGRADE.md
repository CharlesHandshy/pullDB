# pullDB Installation & Upgrade Guide

> **Version**: 1.3.0 | **Last Updated**: March 2026

This guide covers installing and upgrading pullDB on a database server, including Docker-based stations.

> **IMPORTANT**: Fresh installs automatically create an admin user with a random password.
> Save the credentials displayed at the end of installation — they are shown once and also
> written to `/opt/pulldb.service/ADMIN_CREDENTIALS.txt` (root-readable only).

---

## System Requirements

| Component | Requirement |
|-----------|-------------|
| **Operating System** | Ubuntu 22.04 LTS or Ubuntu 24.04 LTS |
| **Python** | 3.12+ (installed automatically by `preinst` via deadsnakes PPA) |
| **MySQL** | 8.0+ — **must be running before `dpkg -i`** (see Prerequisites) |
| **openssl** | Required for TLS certificate generation — **must be installed before `dpkg -i`** |
| **Disk Space** | 50 GB+ for work directory |
| **Memory** | 4 GB+ RAM |

---

## Available Packages

| Package | Purpose | Install Path |
|---------|---------|--------------|
| `pulldb` | Full server (worker + API + web UI) | `/opt/pulldb.service` |
| `pulldb-client` | CLI only (no background services) | `/opt/pulldb.client` |

---

## Prerequisites (Required Before `dpkg -i`)

The `pulldb` server package has two hard dependencies that are **not automatically installed
by dpkg** and will cause the install to fail if absent. Install them first on any system,
including Docker.

### 1. `software-properties-common` (Pre-Depends — blocks unpack if missing)

The package has `Pre-Depends: software-properties-common`. dpkg enforces Pre-Depends before
it unpacks the package — before any script runs. If this package is not installed, `dpkg -i`
fails immediately:

```
dpkg: error processing archive pulldb_1.3.0_amd64.deb
  pre-dependency problem — not installing pulldb:
  pulldb pre-depends on software-properties-common; however:
    Package software-properties-common is not installed.
```

### 2. `openssl` (Required for TLS — postinst exits if missing)

The postinst generates a self-signed TLS certificate. If `openssl` is not present, the
entire install aborts with `FATAL: Failed to generate TLS certificate`.

### 3. MySQL 8.0+ server (Required for schema — postinst exits if not running)

The postinst creates the `pulldb_service` database and applies the schema. If MySQL is not
running and reachable via Unix socket, the install aborts with `FATAL: Cannot connect to MySQL`.

### Install all prerequisites in one step

```bash
sudo apt-get update
sudo apt-get install -y software-properties-common openssl ca-certificates mysql-server
sudo service mysql start   # or: sudo systemctl start mysql
```

---

## Fresh Installation — Standard Ubuntu Server

Use the one-step installer. Copy `install-pulldb-server.sh` alongside the `.deb` file and run:

```bash
sudo ./install-pulldb-server.sh pulldb_1.3.0_amd64.deb
```

The script handles everything in order:
1. Installs `software-properties-common`, `openssl`, `ca-certificates` (prerequisites that block `dpkg -i` if absent)
2. Installs and starts `mysql-server` if not already running
3. Installs the `.deb` package (Python 3.12 auto-installed via deadsnakes PPA)
4. Applies schema to remote MySQL if needed (sidecar scenario)
5. Replaces placeholder MySQL passwords with randomly generated ones and writes them to `.env`
6. Generates a session secret and writes it to `.env`
7. Starts `pulldb-api` and `pulldb-worker`

At the end it prints the admin credentials and service URLs.

> **IMPORTANT**: Save the admin credentials — they are displayed once and stored in
> `/opt/pulldb.service/ADMIN_CREDENTIALS.txt` (root-readable only).

### After install: configure environment

Edit `/opt/pulldb.service/.env` to set your AWS and S3 details, then restart services:

```bash
sudo nano /opt/pulldb.service/.env
```

Required settings:
```bash
PULLDB_AWS_PROFILE=pr-dev
AWS_DEFAULT_REGION=us-east-1
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db
```

Or use the interactive wizard:
```bash
sudo /opt/pulldb.service/scripts/configure-pulldb.sh
```

Then restart:
```bash
sudo systemctl restart pulldb-api pulldb-worker
```

### Enable the web UI

The web UI is not auto-started. Enable it once:

```bash
sudo systemctl enable --now pulldb-web
```

Access at `https://<server-ip>:8000`.

> **Note**: The server uses a self-signed TLS certificate. Your browser will show a security
> warning on first access. Accept the exception, or import the certificate from
> `/opt/pulldb.service/tls/cert.pem` into your system or browser trust store.

### Verify the install

```bash
# Tables
sudo mysql -e "SHOW TABLES IN pulldb_service"

# Users created
sudo mysql -e "SELECT username, role FROM pulldb_service.auth_users"

# Services running
sudo systemctl status pulldb-api pulldb-worker
```

---

## Fresh Installation — Docker Station

This section covers deploying pullDB on a Docker station running a minimal Ubuntu image.
The key differences from a bare-metal install:

- **Do not build the package on the target** — copy a pre-built `.deb` from the build machine
- **No `sudo`** — Docker containers run as root by default; `sudo` is typically not installed
- **systemd is not running** in a standard Docker container — services must be managed manually
  or the container must be configured for systemd (e.g., `--privileged` with `systemd` as PID 1)
- **MySQL must be pre-installed or provided as a sidecar** — the postinst cannot start MySQL for you

### Option A: Single container (MySQL + pullDB together)

Suitable for development/testing stations. Copy the installer and `.deb` into the image
and run the one-step installer:

```dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

# Copy the pre-built package and installer (built on dev machine via `make server`)
COPY pulldb_1.3.0_amd64.deb install-pulldb-server.sh /tmp/

# Run the one-step installer
# --yes skips the "Continue? [Y/n]" prompt
# The installer installs prerequisites, MySQL, the package, sets passwords, and starts services
RUN chmod +x /tmp/install-pulldb-server.sh \
    && /tmp/install-pulldb-server.sh --yes /tmp/pulldb_1.3.0_amd64.deb \
    && rm /tmp/pulldb_1.3.0_amd64.deb /tmp/install-pulldb-server.sh

EXPOSE 8000 8080
```

> **Systemd note**: Without systemd, the installer detects the Docker environment and
> starts `pulldb-api` and `pulldb-worker` directly as background processes.
> To start the web UI: `exec /opt/pulldb.service/venv/bin/pulldb-web`

### Option B: Sidecar MySQL (docker-compose)

If MySQL runs in a separate container, pass `--skip-mysql` and `--mysql-host` so the
installer connects to the sidecar for schema application instead of using the Unix socket:

```yaml
# docker-compose.yml
services:
  db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: rootpass
      MYSQL_DATABASE: pulldb_service
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      retries: 10

  pulldb:
    build: .
    depends_on:
      db:
        condition: service_healthy
```

```dockerfile
# Dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

COPY pulldb_1.3.0_amd64.deb install-pulldb-server.sh /tmp/

RUN chmod +x /tmp/install-pulldb-server.sh \
    && /tmp/install-pulldb-server.sh \
        --yes \
        --skip-mysql \
        --mysql-host db \
        --mysql-root-pass rootpass \
        /tmp/pulldb_1.3.0_amd64.deb \
    && rm /tmp/pulldb_1.3.0_amd64.deb /tmp/install-pulldb-server.sh

EXPOSE 8000 8080
```

The installer will:
- Skip local MySQL install
- Connect to `db:3306` to apply schema (since postinst cannot reach remote MySQL)
- Set MySQL user passwords on the remote host
- Write connection details to `.env`

### Verifying the Docker install

```bash
# Check the Python module loaded correctly
/opt/pulldb.service/venv/bin/python -c "import pulldb; print('OK')"

# Check CLI
/usr/local/bin/pulldb --version

# Check database tables
mysql -e "SHOW TABLES IN pulldb_service"
```

---

## CLI Client Package (CLI Only)

For systems that only need CLI access (no background services):

```bash
# The client installer handles Python 3.12 automatically
sudo ./install-pulldb-client.sh pulldb-client_1.3.0_amd64.deb

# Or manually:
sudo apt-get install -y software-properties-common
sudo dpkg -i pulldb-client_1.3.0_amd64.deb

# Verify
pulldb --help
```

---

## Upgrading

> **Important**: Schema upgrades are **not automatic**. The postinst detects an existing
> schema and skips all SQL application. New schema files introduced in an upgrade must be
> applied manually before restarting services.

### Standard Upgrade Process

```bash
# Step 1: Stop services before installing new package
sudo systemctl stop pulldb-worker pulldb-api pulldb-web

# Step 2: Install the new package
sudo dpkg -i pulldb_1.3.0_amd64.deb

# Step 3: Apply any new schema files manually (see "Schema Upgrades" below)

# Step 4: Restart services
sudo systemctl start pulldb-api pulldb-worker

# Step 5: Verify
/opt/pulldb.service/venv/bin/pulldb --version
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list
```

### Schema Upgrades (Manual)

The installer does not apply schema changes to existing installations. To find and apply
new schema files introduced in an upgrade:

```bash
# See what tables exist now
sudo mysql -e "SHOW TABLES IN pulldb_service"

# Apply a specific new schema file
sudo mysql pulldb_service < /opt/pulldb.service/schema/pulldb_service/00_tables/<new_file>.sql

# Apply all files in a category (safe — all files use CREATE TABLE IF NOT EXISTS / INSERT IGNORE)
for f in /opt/pulldb.service/schema/pulldb_service/00_tables/*.sql; do
    echo "Applying $f..."
    sudo mysql pulldb_service < "$f"
done
```

Schema files are safe to re-apply:
- Tables: `CREATE TABLE IF NOT EXISTS` — skipped if already present
- Views: `CREATE OR REPLACE VIEW` — updated in place
- Seed data: `INSERT IGNORE` — skipped if already present
- Users: `CREATE USER IF NOT EXISTS` — skipped if already present

### Rollback

```bash
# Reinstall the previous version
sudo dpkg -i pulldb_1.2.0_amd64.deb
sudo systemctl restart pulldb-api pulldb-worker
```

No schema downgrade tooling exists. If a new schema file added columns or tables, they
persist after rollback but are ignored by the older code.

---

## Quick Reference

| Task | Command |
|------|---------|
| Install server (one step) | `sudo ./install-pulldb-server.sh pulldb_1.3.0_amd64.deb` |
| Install server (Docker, local MySQL) | `./install-pulldb-server.sh --yes pulldb_1.3.0_amd64.deb` |
| Install server (Docker, sidecar MySQL) | `./install-pulldb-server.sh --yes --skip-mysql --mysql-host db pulldb_*.deb` |
| Install CLI client | `sudo dpkg -i pulldb-client_1.3.0_amd64.deb` |
| Show all database tables | `sudo mysql -e "SHOW TABLES IN pulldb_service"` |
| Check all services | `sudo systemctl status pulldb-worker pulldb-api pulldb-web` |
| View settings | `sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list` |
| Read admin credentials | `sudo cat /opt/pulldb.service/ADMIN_CREDENTIALS.txt` |
| Re-run configuration wizard | `sudo /opt/pulldb.service/scripts/configure-pulldb.sh` |

---

## File Locations

| Path | Description |
|------|-------------|
| `/opt/pulldb.service/` | Main installation directory |
| `/opt/pulldb.service/.env` | Environment configuration |
| `/opt/pulldb.service/venv/` | Python virtual environment |
| `/opt/pulldb.service/tls/` | Self-signed TLS certificate and key |
| `/opt/pulldb.service/scripts/` | Utility scripts |
| `/opt/pulldb.service/schema/pulldb_service/` | Database schema files (subdirs: `00_tables/` `01_views/` `02_seed/` `03_users/`) |
| `/opt/pulldb.service/bin/` | Binary tools (myloader) |
| `/opt/pulldb.service/ADMIN_CREDENTIALS.txt` | Initial admin password (root-readable, delete after saving) |
| `/mnt/data/work/pulldb.service/` | Default work directory for restore operations (configurable) |
| `/mnt/data/logs/pulldb.service/` | Default log directory (configurable) |
| `/usr/local/bin/pulldb` | CLI symlink |
| `/usr/local/bin/pulldb-admin` | Admin CLI wrapper (auto-escalates to `pulldb_service` user) |
| `/etc/sudoers.d/pulldb-admin` | Passwordless sudo rule for `pulldb-admin` |

---

## Service Management

```bash
# Start / stop / restart
sudo systemctl start pulldb-api pulldb-worker
sudo systemctl stop pulldb-api pulldb-worker
sudo systemctl restart pulldb-api pulldb-worker

# Enable web UI (not auto-enabled)
sudo systemctl enable --now pulldb-web

# Enable scheduled cleanup (not auto-enabled)
sudo systemctl enable --now pulldb-retention.timer

# View logs
sudo journalctl -u pulldb-worker -f
sudo journalctl -u pulldb-api -f
sudo journalctl -u pulldb-worker -p err --since "1 hour ago"

# Multi-worker mode
sudo systemctl start pulldb-worker@1 pulldb-worker@2
```

---

## Admin Commands

```bash
# List all settings
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings list

# Sync database settings to .env
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings pull --yes

# Sync .env to database
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings push

# Show differences between database and .env
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings diff

# List jobs
sudo /opt/pulldb.service/venv/bin/pulldb-admin jobs list

# List active jobs only
sudo /opt/pulldb.service/venv/bin/pulldb-admin jobs list --active
```

---

## Troubleshooting

### Package installation fails — Pre-Depends error

```
dpkg: error: pulldb pre-depends on software-properties-common
```

**Fix:**
```bash
sudo apt-get install -y software-properties-common
sudo dpkg -i pulldb_1.3.0_amd64.deb
```

### Package installation fails — TLS certificate error

```
FATAL: Failed to generate TLS certificate
```

**Fix:**
```bash
sudo apt-get install -y openssl
sudo dpkg -i pulldb_1.3.0_amd64.deb
```

### Package installation fails — MySQL not running

```
FATAL: Cannot connect to MySQL
```

**Fix:**
```bash
sudo apt-get install -y mysql-server
sudo systemctl start mysql
sudo dpkg -i pulldb_1.3.0_amd64.deb
```

### Services won't start

```bash
# Check logs
sudo journalctl -u pulldb-worker -n 50 --no-pager
sudo journalctl -u pulldb-api -n 50 --no-pager

# Validate configuration
sudo /opt/pulldb.service/scripts/service-validate.sh

# Inspect .env
sudo cat /opt/pulldb.service/.env

# Test Python import
sudo /opt/pulldb.service/venv/bin/python -c "import pulldb; print('OK')"
```

### TLS certificate not trusted by browser or CLI

The self-signed certificate is added to the system trust store during install. If it was
not trusted (e.g., `update-ca-certificates` failed):

```bash
sudo cp /opt/pulldb.service/tls/cert.pem /usr/local/share/ca-certificates/pulldb-service.crt
sudo update-ca-certificates
```

To regenerate the certificate (e.g., if the server IP changed):

```bash
sudo rm /opt/pulldb.service/tls/cert.pem /opt/pulldb.service/tls/key.pem
sudo dpkg-reconfigure pulldb
```

### Web UI shows SSL error

The web UI runs on HTTPS (port 8000), not HTTP. Use:
```
https://<server-ip>:8000
```
not `http://`.

### Settings not loading after upgrade

```bash
# Check what's in .env
sudo grep -v '^#' /opt/pulldb.service/.env | grep -v '^$'

# Sync from database
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings diff
sudo /opt/pulldb.service/venv/bin/pulldb-admin settings pull --yes
```

### Schema check shows no migrations

The `schema_migrations` table is not populated by the installer. Use `SHOW TABLES` instead:
```bash
sudo mysql -e "SHOW TABLES IN pulldb_service"
```

---

## Known Limitations

| Limitation | Detail |
|---|---|
| Schema upgrades are manual | The postinst skips schema application on existing installs. New SQL files must be applied manually. |
| MySQL service user passwords | Seeded with placeholder values (`CHANGE_ME_API`, `CHANGE_ME_WORKER`). Change immediately after install. |
| Sidecar MySQL not supported by postinst | Postinst connects via Unix socket only. For remote MySQL, apply schema manually. |
| `schema_migrations` table always empty | The table exists but is not written to by the installer. Do not rely on it to verify schema state. |
| systemd required for auto-start | Services do not start automatically in Docker without systemd. Start binaries directly in the container entrypoint. |
