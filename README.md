# pullDB

[![Release](https://img.shields.io/badge/version-0.2.0-blue)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-520%2B-success.svg)](pulldb/tests/)

**Pull production database backups from S3 and restore them to development environments.**

pullDB automates the tedious process of restoring MySQL backups for development, testing, and debugging. Submit a restore job, and pullDB handles S3 discovery, download, extraction, myloader execution, post-SQL scripts, and atomic deployment—all coordinated through a MySQL job queue.

## Features

- **One-Command Restores**: `pulldb customer=acme` submits a job and tracks progress
- **Web Dashboard**: Real-time job monitoring with progress bars, per-table metrics, and dark mode
- **Multi-Worker Architecture**: Parallel restore execution with per-host concurrency limits
- **Automatic Format Detection**: Handles both legacy (0.9) and modern (0.19+) mydumper/myloader formats
- **Per-Table Progress**: Live processlist monitoring shows individual table completion during restore
- **Atomic Deployment**: Staging database pattern with atomic rename prevents partial restores
- **Database Lifecycle Management**: Expiration, locking, retention extension for deployed databases
- **Self-Service Registration**: Users register and await admin approval before accessing restores
- **Role-Based Access**: User, Manager, and Admin roles with appropriate permissions

## Quick Start

### Client Installation

```bash
# Install the pullDB client
pip install pulldb

# Register and set password
pulldb register
pulldb setpass

# Submit a restore job
pulldb customer=acme

# Check status
pulldb status
```

### Service Installation (Debian)

```bash
# Download the latest release
wget https://github.com/CharlesHandshy/pullDB/releases/download/v0.2.0/pulldb_0.2.0_amd64.deb

# Install (creates user, venv, systemd services)
sudo dpkg -i pulldb_0.2.0_amd64.deb

# Configure
sudo /opt/pulldb.service/scripts/configure-pulldb.sh

# Start services
sudo systemctl enable --now pulldb-api pulldb-worker pulldb-web
```

See [Getting Started](docs/hca/pages/getting-started.md) for complete installation instructions.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  pulldb CLI     │────▶│  pulldb-api     │────▶│    MySQL        │
│  (client)       │     │  (REST API)     │     │  (job queue)    │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
┌─────────────────┐     ┌─────────────────┐              │
│  pulldb-web     │◀────│ pulldb-worker   │◀─────────────┘
│  (Web UI)       │     │ (restore jobs)  │
└─────────────────┘     └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │   S3 → myloader │
                        │   → target DB   │
                        └─────────────────┘
```

**Components:**
- **pulldb-api** (port 8080): REST API for job submission, status queries
- **pulldb-web** (port 8000): Web dashboard with real-time monitoring
- **pulldb-worker**: Background service that executes restore jobs
- **MySQL**: Job queue coordination, state management, event logging

**Restore Workflow:**
1. Client submits job → API enqueues in MySQL
2. Worker claims job → Downloads backup from S3
3. Extracts archive → Detects format (legacy/modern)
4. myloader restores to staging DB (with processlist monitoring)
5. Post-SQL scripts execute → Metadata injected
6. Atomic rename: staging → target database

## CLI Commands

### User Commands

```bash
pulldb customer=acme [dbhost=staging-01]  # Submit restore job
pulldb status [job_id]                     # Check job status
pulldb events <job_id> [--follow]          # Stream job events
pulldb search <customer>                   # Search available backups
pulldb history                             # View completed jobs
pulldb cancel <job_id>                     # Cancel queued/running job
pulldb hosts                               # List available database hosts
pulldb profile <job_id>                    # View performance breakdown
```

### Admin Commands

```bash
pulldb-admin settings list                 # View configuration
pulldb-admin jobs list --active            # View active jobs
pulldb-admin cleanup --dry-run             # Preview database cleanup
pulldb-admin hosts list                    # View database hosts
pulldb-admin users list                    # List all users
pulldb-admin users enable <username>       # Enable user access
```

## Documentation

| Document | Description |
|----------|-------------|
| **[Getting Started](docs/hca/pages/getting-started.md)** | Installation and initial setup |
| [CLI Reference](docs/hca/pages/cli-reference.md) | Complete command documentation |
| [Admin Guide](docs/hca/pages/admin-guide.md) | Operations and maintenance |
| [Architecture](docs/hca/widgets/architecture.md) | System design and data flow |
| [MySQL Schema](docs/hca/entities/mysql-schema.md) | Database schema reference |
| [Development](docs/hca/pages/development.md) | Contributing guidelines |

**Quick Links:**
- [📚 Documentation Index](docs/START-HERE.md) - Navigate by role
- [📋 Knowledge Pool](docs/KNOWLEDGE-POOL.md) - AWS/infra quick reference
- [🗂️ Workspace Index](docs/WORKSPACE-INDEX.md) - Codebase structure

## Development

```bash
# Clone and setup
git clone https://github.com/CharlesHandshy/pullDB.git
cd pullDB
python3 -m venv venv && source venv/bin/activate
pip install -e .[dev]

# Run tests
pytest

# Run linting
ruff check . && mypy pulldb

# Build Debian package
./scripts/build_deb.sh

# Development server (simulation mode)
python scripts/dev_server.py --simulation
```

## Project Structure

```
pulldb/
├── api/          # REST API endpoints (FastAPI)
├── cli/          # Command-line interface (Click)
├── domain/       # Business models and configuration
├── infra/        # MySQL, S3, secrets, logging
├── web/          # Web UI (Jinja2 templates)
├── worker/       # Restore execution engine
└── simulation/   # In-memory simulation for development

schema/           # MySQL migrations (dbmate)
scripts/          # Build, deploy, validation scripts
docs/             # Documentation (HCA organized)
```

## Requirements

- **Python**: 3.12+
- **MySQL**: 8.0+ (for job coordination)
- **AWS**: S3 access for backup retrieval, Secrets Manager for credentials
- **myloader**: 0.9.5 or 0.19.3 (bundled in package)

## License

MIT License - See [LICENSE](LICENSE) for details.

## Contributing

1. Read [constitution.md](constitution.md) for coding standards
2. Follow [FAIL HARD](engineering-dna/protocols/fail-hard.md) protocol
3. Run `make check` before submitting PRs
4. See [Development Guide](docs/hca/pages/development.md) for details

---

*pullDB v0.2.0 - January 2026*
