# pullDB Client Operations Guide

## Overview

The pullDB client provides command-line access to the pullDB restore service. It communicates with the pullDB API server to submit restore jobs and check their status.

## System Requirements

| Component | Requirement |
|-----------|-------------|
| **Operating System** | Ubuntu 22.04+ (recommended) or Ubuntu 20.04 (legacy) |
| **Python** | 3.12+ |
| **Network** | Outbound access to pullDB API server (port 8000) |

### Ubuntu 20.04 (Legacy Support)

Ubuntu 20.04 requires building Python 3.12 from source before installing the client:

```bash
# Install build dependencies
sudo apt-get update
sudo apt-get install -y build-essential zlib1g-dev libncurses5-dev \
    libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev \
    libsqlite3-dev wget libbz2-dev

# Download and build Python 3.12 (~10 minutes)
cd /tmp
wget https://www.python.org/ftp/python/3.12.4/Python-3.12.4.tgz
tar -xf Python-3.12.4.tgz
cd Python-3.12.4
./configure --enable-optimizations --prefix=/usr/local
make -j$(nproc)
sudo make altinstall

# Verify
python3.12 --version

# Then install pulldb-client
sudo dpkg -i pulldb-client_*.deb
```

> **Note**: System Python 3.8 remains unchanged. Consider upgrading to Ubuntu 22.04 LTS.

## Related Packages

| Package | Purpose | Install Path |
|---------|---------|--------------|
| **pulldb** | Full server (worker + API + web) | `/opt/pulldb.service` |
| **pulldb-client** | CLI only (this package) | `/opt/pulldb.client` |

## Installation

The client is installed as the `pulldb_service` system user (shared with the server package if installed).

### Installation Location

```
/opt/pulldb.client/
├── dist/                    # Python wheel package
│   └── pulldb-*.whl
└── venv/                    # Python virtual environment
    └── bin/
        └── pulldb           # CLI executable

/usr/local/bin/pulldb        # Symlink (accessible to all users)
```

### System User

- **User**: `pulldb_service`
- **Group**: `pulldb_service`  
- **Home**: `/opt/pulldb.service` (if server installed) or `/opt/pulldb.client`

The user/group is shared with the `pulldb` server package. If both packages are installed, they share the same system user.

## CLI Command Reference

### Authentication Commands

Before using pullDB, you need to register an account or request an API key.

#### Register Command

Create a new pullDB account:

```bash
pulldb register
```

This command:
1. Creates an account using your system username
2. Prompts for a password (minimum 8 characters)
3. Saves API credentials to `~/.pulldb/credentials`
4. Account is created in **pending approval** state

After registering, contact an administrator to approve your account.

#### Existing User - New Host

If you already have a pullDB account but need access from a different machine, run `register` again:

```bash
pulldb register
```

The command detects that your username already exists and offers to request a new API key for this host:
1. Prompts for your password to verify identity
2. Creates a new API key for this host
3. Saves credentials to `~/.pulldb/credentials`
4. Key is created in **pending approval** state

Contact an administrator to approve the new API key.

---

### Restore Command

Submit a database restore job:

```bash
pulldb restore user=<username> customer=<id> [dbhost=<host>] [overwrite]
pulldb restore user=<username> qatemplate [dbhost=<host>] [overwrite]
```

**Arguments:**
| Argument | Required | Description |
|----------|----------|-------------|
| `user=<username>` | Yes (first) | Username (must have ≥6 letters for user_code generation) |
| `customer=<dbname>` | One of | Customer database name to restore |
| `qatemplate` | One of | Restore QA template instead of customer |
| `dbhost=<host>` | No | Target database host (defaults to configured host) |
| `overwrite` | No | Allow overwriting existing target database |

**Examples:**
```bash
# Restore customer database
pulldb restore user=jsmith customer=acmecorp

# Restore QA template
pulldb restore user=jsmith qatemplate

# Restore with specific host and overwrite
pulldb restore user=jsmith customer=acmecorp dbhost=dev-db1 overwrite
```

**User Code Generation:**
- The first 6 alphabetic characters of the username become the `user_code`
- Example: `john.smith` → `johnso`, `JSmith123` → `jsmith`
- Target database: `<user_code><sanitized_customer>` (max 51 chars)

### Status Command

View job status:

```bash
pulldb status [OPTIONS]
```

**Options:**
| Option | Description |
|--------|-------------|
| `--json` | Output JSON instead of table |
| `--wide` | Show additional columns (staging name) |
| `--limit N` | Limit rows (default: 100, max: 1000) |
| `--active` | Show active jobs (queued/running) - default |
| `--history` | Show historical jobs (completed/failed/canceled) |
| `--filter JSON` | Filter by column values |
| `--job-id ID` | Filter to specific job |
| `--rt --job-id ID` | Stream real-time events for a job |

**Examples:**
```bash
# Show active jobs
pulldb status

# Show recent history
pulldb status --history --limit 50

# Stream events for a running job
pulldb status --rt --job-id abc12345

# JSON output for scripting
pulldb status --json --filter '{"status": "failed"}'
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PULLDB_API_URL` | `http://localhost:8080` | API server URL |
| `PULLDB_API_TIMEOUT` | `30.0` | API request timeout (seconds) |

### System-Wide Configuration

Create `/etc/profile.d/pulldb.sh` for all users:

```bash
# /etc/profile.d/pulldb.sh
export PULLDB_API_URL="http://pulldb-api.internal:8080"
export PATH="/opt/pulldb.client/venv/bin:$PATH"
```

---

## Administrator Setup Guide

### User Management

Each developer using pullDB needs:
1. A username with at least 6 alphabetic characters
2. (Optional) A personalized wrapper script for convenience

### Creating Sudo Wrappers

Administrators can create wrapper scripts that pre-fill the `user=` parameter for each developer, simplifying their workflow.

#### Option 1: Per-User Wrapper Scripts

Create individual wrappers in `/usr/local/bin/`:

```bash
#!/bin/bash
# /usr/local/bin/pulldb-jsmith
# Wrapper for developer John Smith (user_code: johnso)

exec /opt/pulldb.client/venv/bin/pulldb restore user=jsmith "$@"
```

Make executable:
```bash
sudo chmod +x /usr/local/bin/pulldb-jsmith
```

Developer usage:
```bash
pulldb-jsmith customer=acme_corp
pulldb-jsmith qatemplate
```

#### Option 2: Generic Wrapper with Current User

Create a single wrapper that uses the system username:

```bash
#!/bin/bash
# /usr/local/bin/pulldb-restore
# Auto-detects username from system

USERNAME="${SUDO_USER:-$USER}"
exec /opt/pulldb.client/venv/bin/pulldb restore user="$USERNAME" "$@"
```

Developer usage:
```bash
pulldb-restore customer=acme_corp
```

#### Option 3: Default Source Wrapper

For teams that frequently restore from a specific customer:

```bash
#!/bin/bash
# /usr/local/bin/pulldb-default
# Default restore: current user + default customer

USERNAME="${SUDO_USER:-$USER}"
DEFAULT_CUSTOMER="${PULLDB_DEFAULT_CUSTOMER:-demo_corp}"

if [[ "$1" == "qatemplate" ]]; then
    exec /opt/pulldb.client/venv/bin/pulldb restore user="$USERNAME" qatemplate "${@:2}"
else
    exec /opt/pulldb.client/venv/bin/pulldb restore user="$USERNAME" customer="$DEFAULT_CUSTOMER" "$@"
fi
```

Developer can override:
```bash
# Use default customer
pulldb-default

# Use QA template
pulldb-default qatemplate

# Override with environment
PULLDB_DEFAULT_CUSTOMER=other_corp pulldb-default
```

### Batch User Setup Script

For setting up multiple developers:

```bash
#!/bin/bash
# /opt/pulldb.client/scripts/setup-user-wrappers.sh

WRAPPER_DIR="/usr/local/bin"
PULLDB_BIN="/opt/pulldb.client/venv/bin/pulldb"

# List of developers: "wrapper_name:username"
DEVELOPERS=(
    "pulldb-jsmith:john.smith"
    "pulldb-mjones:mary.jones"
    "pulldb-bwilson:bob.wilson"
)

for entry in "${DEVELOPERS[@]}"; do
    wrapper="${entry%%:*}"
    username="${entry##*:}"
    
    cat > "${WRAPPER_DIR}/${wrapper}" << EOF
#!/bin/bash
# Auto-generated pulldb wrapper for ${username}
exec ${PULLDB_BIN} restore user=${username} "\$@"
EOF
    
    chmod +x "${WRAPPER_DIR}/${wrapper}"
    echo "Created ${WRAPPER_DIR}/${wrapper} for user ${username}"
done

echo "Done. Wrappers created in ${WRAPPER_DIR}/"
```

### Sudoers Configuration (Optional)

If restore operations require elevated privileges:

```bash
# /etc/sudoers.d/pulldb
# Allow developers group to run pulldb without password
%developers ALL=(ALL) NOPASSWD: /opt/pulldb.client/venv/bin/pulldb
```

---

## Troubleshooting

### Client Not Found

If `pulldb` command is not found:

```bash
# Check if installed
ls -la /opt/pulldb.client/venv/bin/pulldb

# Add to PATH or use full path
/opt/pulldb.client/venv/bin/pulldb --version

# Or add to your shell profile
echo 'export PATH="/opt/pulldb.client/venv/bin:$PATH"' >> ~/.bashrc
```

### Connection Refused

If you get connection errors:

1. Verify the API server is running
2. Check the API URL is correct: `echo $PULLDB_API_URL`
3. Test connectivity: `curl -s $PULLDB_API_URL/health`
4. Check firewall rules allow the connection

### Username Validation Errors

```
CLIParseError: Username must contain at least 6 alphabetic letters
```

**Solution:** Use a longer username or one with more letters:
- ❌ `user=bob` (only 3 letters)
- ❌ `user=123456` (no letters)
- ✅ `user=bobsmith` (8 letters)
- ✅ `user=bob.smith` (8 letters after sanitization)

### Target Name Too Long

```
CLIParseError: Target database name exceeds max length 51
```

**Solution:** Shorten the username or customer ID in the request.

## Uninstallation

```bash
sudo dpkg -r pulldb-client
```

This removes:
- `/opt/pulldb.client/` directory
- Wrapper scripts in `/usr/local/bin/pulldb-*` (if created manually, remove separately)

## Quick Reference

| Task | Command |
|------|---------|
| Check version | `pulldb --version` |
| Get help | `pulldb --help` |
| **Register account** | `pulldb register` |
| **Request host key (existing user)** | `pulldb register` (detects existing user) |
| Restore customer | `pulldb restore user=NAME customer=ID` |
| Restore QA template | `pulldb restore user=NAME qatemplate` |
| View active jobs | `pulldb status` |
| View job history | `pulldb status --history` |
| Stream job events | `pulldb status --rt --job-id ID` |

## Support

For issues or questions, contact the PestRoutes Engineering team.
