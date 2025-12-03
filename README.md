# pullDB

[![Release](https://img.shields.io/badge/version-0.0.8-blue)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-585%20total-success.svg)](pulldb/tests/)

> Pull production database backups from S3 and restore them into development environments.

## Quick Start

```bash
# Install pullDB
pip install -e .[dev]

# Submit a restore job
pulldb user=charles customer=acme

# Check status
pulldb status
```

See [Getting Started](docs/getting-started.md) for complete installation instructions.

## Documentation

**📚 [Start Here](docs/START-HERE.md)** - Complete documentation index with navigation by role.

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation and setup |
| [CLI Reference](docs/cli-reference.md) | Command-line interface |
| [Admin Guide](docs/admin-guide.md) | Operations and maintenance |
| [Deployment](docs/deployment.md) | Service deployment |
| [Architecture](docs/architecture.md) | System design and data flow |
| [Development](docs/development.md) | Contributing and coding standards |

**Reference:**
- [MySQL Schema](docs/mysql-schema.md) - Database schema
- [Knowledge Pool](docs/KNOWLEDGE-POOL.md) - Quick reference for AWS/infra values

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  pulldb CLI     │────▶│  pulldb-api     │────▶│    MySQL        │
│  (client)       │     │  (API service)  │     │  (coordination) │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                          │
                        ┌─────────────────┐     ┌─────────────────┐
                        │ pulldb-worker   │◀────│  (polls queue)  │
                        │ (worker service)│     └─────────────────┘
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │   S3 + myloader │
                        │   (backups)     │
                        └─────────────────┘
```

**Key Concepts:**
- Two-service architecture: API receives requests, Worker executes restores
- MySQL-based job coordination (queue, state, locks)
- Staging database pattern: restore to staging, atomic rename to target

## Status (December 2025)

**Version 0.0.8** - Phases 0-4 Complete

| Phase | Features | Status |
|-------|----------|--------|
| Phase 0 | Core restore workflow, CLI, API, Worker | ✅ Complete |
| Phase 1 | Cancellation, history, events, cleanup | ✅ Complete |
| Phase 2 | Concurrency controls, host aliases | ✅ Complete |
| Phase 3 | Multi-daemon support, atomic job claiming | ✅ Complete |
| Phase 4 | QA template restore, post_sql validation | ✅ Complete |

**Test Suite:** 449 passing tests

## CLI Overview

### User Commands (pulldb)

```bash
pulldb user=charles customer=acme    # Submit restore job
pulldb status [job_id]               # Check job status
pulldb events <job_id> [--follow]    # View job events
pulldb search <customer>             # Search for backups
pulldb history                       # View completed jobs
pulldb cancel <job_id>               # Cancel a job
pulldb profile <job_id>              # View performance profile
```

### Admin Commands (pulldb-admin)

```bash
pulldb-admin settings list           # View configuration
pulldb-admin jobs list --active      # View active jobs
pulldb-admin cleanup --dry-run       # Preview cleanup
pulldb-admin hosts list              # View database hosts
```

See [CLI Reference](docs/cli-reference.md) for complete documentation.

## Development

```bash
# Setup development environment
python3 -m venv venv
source venv/bin/activate
pip install -e .[dev]

# Run tests
pytest

# Run linting
ruff check .
mypy pulldb

# Run all checks
make check
```

See [Development Guide](docs/development.md) for contributing guidelines.

## Project Governance

- **[constitution.md](constitution.md)** - Project principles and FAIL HARD protocol
- **[CHANGELOG.md](CHANGELOG.md)** - Version history
- **[engineering-dna/](engineering-dna/)** - Shared development protocols (submodule)

## For AI Agents

Start with `.github/copilot-instructions.md` for:
- Tiered context loading (engineering-dna → .pulldb/ → docs/)
- FAIL HARD protocol requirements
- Key architectural constraints

Then read `constitution.md` for coding standards and workflow.
