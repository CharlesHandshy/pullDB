# pullDB Architecture

[← Back to Documentation Index](START-HERE.md)

> **Version**: 1.0.0 | **Last Updated**: January 2026

This document describes the pullDB system architecture, components, and data flow.

**Related:** [MySQL Schema](mysql-schema.md) · [Development Guide](development.md)

---

## Overview

pullDB pulls production database backups from S3 and restores them into development environments. The system consists of three components communicating through MySQL:

```
┌─────────────┐     HTTP      ┌─────────────┐     MySQL     ┌─────────────┐
│    CLI      │ ───────────►  │ API Service │ ◄───────────► │   Worker    │
│  (pulldb)   │               │             │               │   Service   │
└─────────────┘               └─────────────┘               └─────────────┘
                                     │                              │
                                     │                              │
                                     ▼                              ▼
                              ┌─────────────┐               ┌─────────────┐
                              │   MySQL     │               │     S3      │
                              │ Coordination│               │   Backups   │
                              └─────────────┘               └─────────────┘
```

**Key Principles:**
- **MySQL is the coordination layer** - All state, locks, and communication via database
- **Per-target exclusivity** - Only one active job per target database
- **Download-per-job** - No archive reuse; each job downloads fresh
- **Services don't communicate directly** - Only through MySQL queue

---

## Components

### CLI (`pulldb`)

**Purpose:** Thin client for submitting and monitoring jobs

**Location:** `pulldb/cli/`

**Responsibilities:**
- Parse and validate command arguments
- Call API service via HTTP
- Display job status and progress
- NO direct AWS or MySQL access

**Key Commands:**
```bash
pulldb restore customer=acme    # Submit restore job
pulldb status                   # List active jobs
pulldb history                  # Show completed jobs
pulldb cancel <job-id>          # Cancel a job
```

### API Service

**Purpose:** Accept job requests, manage state, provide status queries

**Location:** `pulldb/api/`

**Responsibilities:**
- Accept HTTP REST requests from CLI
- Validate input parameters
- Generate user_code and target database names
- Insert jobs into MySQL queue
- Provide status and history endpoints
- Enforce concurrency limits

**Does NOT:**
- ❌ Download backups from S3
- ❌ Execute myloader
- ❌ Poll the job queue

**Endpoints:**
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/jobs` | Submit new restore job |
| GET | `/api/jobs` | List jobs with filtering |
| GET | `/api/jobs/active` | List active jobs only |
| GET | `/api/jobs/history` | List completed jobs |
| GET | `/api/jobs/search` | Search backups in S3 |
| GET | `/api/jobs/resolve/{prefix}` | Resolve job ID from prefix |
| GET | `/api/jobs/{id}/events` | Get job events |
| GET | `/api/jobs/{id}/profile` | Get job performance profile |
| POST | `/api/jobs/{id}/cancel` | Request cancellation |
| GET | `/api/users/{username}` | Get user info |
| GET | `/api/users/{code}/last-job` | Get user's last job |
| GET | `/api/status` | System status |
| GET | `/api/health` | Health check |

**Admin Endpoints:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/admin/orphan-databases` | List orphaned staging DBs |
| POST | `/api/admin/cleanup-staging` | Clean staging databases |
| POST | `/api/admin/delete-orphans` | Delete orphaned databases |
| POST | `/api/admin/prune-logs` | Prune old job logs |

### Worker Service

**Purpose:** Execute restore jobs from the queue

**Location:** `pulldb/worker/`

**Responsibilities:**
- Poll MySQL for queued jobs
- Claim jobs atomically (prevent duplicates)
- Discover and download backups from S3
- Execute myloader restore to staging database
- Run post-restore SQL scripts
- Perform atomic rename to target database
- Emit job events and update status

**Does NOT:**
- ❌ Accept HTTP requests
- ❌ Receive jobs directly from CLI

**Execution Phases:**
1. **Discovery** - Find backup in S3
2. **Download** - Stream archive to local disk
3. **Extract** - Decompress to work directory
4. **Myloader** - Restore to staging database
5. **Post-SQL** - Run sanitization scripts
6. **Metadata** - Inject restore metadata
7. **Atomic Rename** - Swap staging → target

---

## Data Flow

### Job Lifecycle

```
┌────────┐   POST /api/jobs   ┌────────┐   INSERT   ┌────────────┐
│  CLI   │ ─────────────────► │  API   │ ─────────► │   MySQL    │
└────────┘                    └────────┘            │ jobs table │
                                                    └────────────┘
                                                          │
                                                          │ SELECT queued
                                                          ▼
┌────────────┐   UPDATE running   ┌────────┐   claim    ┌────────┐
│   Target   │ ◄───────────────── │ Worker │ ◄───────── │  Jobs  │
│  Database  │                    └────────┘            └────────┘
└────────────┘                         │
      ▲                                │ download
      │                                ▼
      │                          ┌────────────┐
      │                          │     S3     │
      │                          │  Backups   │
      └──── myloader ────────────┘
```

### Job States

```
QUEUED ──► RUNNING ──► COMPLETE
              │
              ├──► FAILED
              │
              └──► CANCELED
```

| State | Description |
|-------|-------------|
| `queued` | Waiting for worker to pick up |
| `running` | Worker actively processing |
| `complete` | Successfully finished |
| `failed` | Error during execution |
| `canceled` | User-requested cancellation |

---

## MySQL Schema

### Core Tables

**jobs** - Job queue and state
```sql
CREATE TABLE jobs (
    id CHAR(36) PRIMARY KEY,            -- UUID
    owner_user_id CHAR(36),             -- User who submitted
    target VARCHAR(200),                 -- Target database name
    staging_name VARCHAR(200),           -- Staging database name
    dbhost VARCHAR(200),                 -- Target MySQL host
    status ENUM('queued','running','complete','failed','canceled'),
    submitted_at DATETIME(6),
    started_at DATETIME(6),
    completed_at DATETIME(6),
    worker_id VARCHAR(100),              -- Which worker claimed it
    current_operation VARCHAR(100),      -- Current phase
    active_target_key VARCHAR(200) GENERATED ALWAYS AS (
        IF(status IN ('queued','running'), target, NULL)
    ) STORED,
    UNIQUE KEY uq_active_target (active_target_key)  -- Per-target exclusivity
);
```

**job_events** - Audit trail
```sql
CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36),
    event_type VARCHAR(50),
    detail TEXT,
    logged_at DATETIME(6)
);
```

**auth_users** - User registry
```sql
CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(100) UNIQUE,
    user_code CHAR(6) UNIQUE,
    role ENUM('user','manager','admin') DEFAULT 'user',
    is_admin BOOLEAN DEFAULT FALSE
);
```

### Phase 4 Tables (RBAC)

**auth_credentials** - Password storage
```sql
CREATE TABLE auth_credentials (
    user_id CHAR(36) PRIMARY KEY,
    password_hash VARCHAR(255),
    created_at DATETIME(6),
    updated_at DATETIME(6)
);
```

**sessions** - Session management
```sql
CREATE TABLE sessions (
    session_id CHAR(64) PRIMARY KEY,
    user_id CHAR(36),
    created_at DATETIME(6),
    expires_at DATETIME(6),
    ip_address VARCHAR(45)
);
```

---

## AWS Integration

### Multi-Account Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Development Account (345321506926)            │
│                                                                  │
│  ┌────────────────┐    ┌─────────────────────────────────────┐ │
│  │ EC2 Instance   │    │ Secrets Manager                      │ │
│  │ (pulldb)       │───►│ /pulldb/mysql/coordination-db        │ │
│  │                │    │ /pulldb/mysql/target-hosts/*         │ │
│  └────────────────┘    └─────────────────────────────────────┘ │
│           │                                                      │
└───────────┼──────────────────────────────────────────────────────┘
            │
            │ Cross-Account S3 Access
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Staging Account (333204494849)                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ S3: pestroutesrdsdbs/daily/stg/                              ││
│  │     └── <customer>/daily_mydumper_<customer>_<date>.tar     ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Production Account (448509429610)              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ S3: pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/ ││
│  │     └── <customer>/daily_mydumper_<customer>_<date>.tar     ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### AWS Profiles

| Profile | Account | Purpose |
|---------|---------|---------|
| `pr-dev` | 345321506926 | Secrets Manager access |
| `pr-staging` | 333204494849 | S3 staging bucket |
| `pr-prod` | 448509429610 | S3 production bucket |

---

## Code Structure

```
pulldb/
├── api/                    # API Service
│   ├── main.py            # FastAPI application
│   └── ...
├── auth/                   # Authentication (Phase 4)
│   ├── password.py        # bcrypt utilities
│   ├── repository.py      # Credentials/sessions
│   └── ...
├── cli/                    # CLI Client
│   ├── main.py            # Command handlers
│   ├── parse.py           # Argument parsing
│   └── ...
├── domain/                 # Domain Models
│   ├── config.py          # Configuration
│   ├── models.py          # Job, User, etc.
│   ├── errors.py          # Error types
│   └── permissions.py     # RBAC helpers
├── infra/                  # Infrastructure
│   ├── mysql.py           # Repository layer
│   ├── secrets.py         # Credential resolver
│   ├── s3.py              # S3 client
│   ├── exec.py            # Subprocess wrapper
│   └── logging.py         # Structured logging
├── web/                    # Web UI (Phase 4)
│   ├── routes.py          # HTMX routes
│   └── templates/         # Jinja2 templates
└── worker/                 # Worker Service
    ├── service.py         # Service entrypoint
    ├── loop.py            # Poll loop
    ├── executor.py        # Job orchestration
    ├── downloader.py      # S3 download
    ├── restore.py         # myloader wrapper
    ├── post_sql.py        # Script execution
    ├── staging.py         # Staging lifecycle
    ├── atomic_rename.py   # Cutover
    ├── metadata.py        # Metadata injection
    └── profiling.py       # Performance capture
```

---

## Security Model

### Authentication Flow

```
CLI (sudo user) → API (user lookup) → MySQL (user_code generation)
                                           ↓
                              Job submitted with owner_user_id
```

### Least-Privilege MySQL Users

| User | Grants | Used By |
|------|--------|---------|
| `pulldb_api` | SELECT/INSERT on jobs/events | API Service |
| `pulldb_worker` | SELECT/UPDATE on jobs/events/locks | Worker Service |
| `pulldb_migrate` | ALL on pulldb_service | Migrations |
| `pulldb_restore` | ALL on target databases | myloader |

### RBAC Roles (Phase 4)

| Role | Permissions |
|------|-------------|
| `user` | View own jobs, submit restores |
| `manager` | View all jobs, manage team users |
| `admin` | Full access, user management |

---

## Related Documentation

- [Getting Started](getting-started.md) - Installation guide
- [CLI Reference](cli-reference.md) - Command documentation
- [Deployment](deployment.md) - Service configuration
- [MySQL Schema](mysql-schema.md) - Complete schema reference

---

[← Back to Documentation Index](START-HERE.md) · [Getting Started →](getting-started.md)
