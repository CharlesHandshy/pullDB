# Feature Request Developer Tool - Design Document

> **Status**: Implemented | **Date**: 2026-01-31  
> **Author**: AI Research Agent  
> **Location**: `tools/feature-requests-review.py` (STANDALONE - NOT part of pulldb package)

---

## Table of Contents

1. [Overview](#overview)
2. [Important: This is NOT Part of pullDB](#important-this-is-not-part-of-pulldb)
3. [Usage](#usage)
4. [Schema Reference](#schema-reference)
5. [Environment Configuration](#environment-configuration)
6. [Implementation Details](#implementation-details)

---

## Overview

A **standalone development tool** for reviewing production feature requests.
This tool is designed for **developers and AI agents** to query feature request
data without using the web UI.

**Key Characteristics**:
- ✅ Self-contained Python script
- ✅ Minimal dependencies (boto3, pymysql only)
- ✅ NOT deployed with pullDB
- ✅ JSON output for AI agent workflows
- ✅ Direct database queries (no service layer)
- ✅ Supports partial ID matching

---

## Important: This is NOT Part of pullDB

⚠️ **DO NOT**:
- Import this tool into the pulldb package
- Add it to pulldb-admin CLI
- Deploy it with pullDB service
- Include it in pip packages

✅ **DO**:
- Run it directly from the repo: `python tools/feature-requests-review.py`
- Use it in dev/AI agent workflows
- Keep it self-contained with minimal dependencies

### Why Standalone?

1. **Development-only tool** - Not needed in production deployments
2. **AI agent workflows** - Optimized for programmatic use with JSON output
3. **Minimal footprint** - No dependencies on pulldb internals
4. **Easy maintenance** - Changes don't affect pulldb package

---

## Usage

### Prerequisites

```bash
# Required Python packages (not from pulldb requirements)
pip install boto3 pymysql

# AWS credentials configured
export AWS_PROFILE=pr-dev  # or your profile
```

### Commands

```bash
# List feature requests (sorted by votes)
python tools/feature-requests-review.py list

# Filter by status
python tools/feature-requests-review.py list --status open
python tools/feature-requests-review.py list --status in_progress

# Sort by date instead of votes
python tools/feature-requests-review.py list --sort date

# Limit results
python tools/feature-requests-review.py list --limit 50

# JSON output (for AI agents)
python tools/feature-requests-review.py list --json

# Show specific request (partial ID supported)
python tools/feature-requests-review.py show abc12345
python tools/feature-requests-review.py show 12345678-1234-1234-1234-123456789abc

# Statistics
python tools/feature-requests-review.py stats
python tools/feature-requests-review.py stats --json
```

### Example Outputs

**Table Format (default)**:
```
Feature Requests (showing 10 of 25)

ID        VOTES  STATUS       DATE        USER      TITLE
--------  -----  -----------  ----------  --------  --------------------------------------------------
abc12345  20     Open         2026-01-15  jsmith    Add bulk restore capability
def67890  12     In Progress  2026-01-20  jdoe      Custom naming for staging databases
...
```

**JSON Format** (`--json`):
```json
{
  "total": 25,
  "showing": 10,
  "requests": [
    {
      "request_id": "abc12345-...",
      "title": "Add bulk restore capability",
      "status": "open",
      "vote_score": 20,
      "upvote_count": 20,
      "downvote_count": 0,
      "submitted_by": "jsmith",
      "created_at": "2026-01-15T10:30:00"
    }
  ]
}
```

---

## Schema Reference

### Tables

The tool queries these tables in `pulldb_service`:

#### `feature_requests`
```sql
CREATE TABLE feature_requests (
    request_id CHAR(36) PRIMARY KEY,
    submitted_by_user_id CHAR(36) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    status ENUM('open', 'in_progress', 'complete', 'declined') DEFAULT 'open',
    vote_score INT DEFAULT 0,
    upvote_count INT UNSIGNED DEFAULT 0,
    downvote_count INT UNSIGNED DEFAULT 0,
    created_at TIMESTAMP(6),
    updated_at TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    admin_response TEXT NULL
);
```

#### `feature_request_notes`
```sql
CREATE TABLE feature_request_notes (
    note_id CHAR(36) PRIMARY KEY,
    request_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    note_text TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### `auth_users` (joined for display names)
```sql
-- Only username and user_code columns are used
SELECT username, user_code FROM auth_users WHERE user_id = ?
```

---

## Environment Configuration

### Required

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_PROFILE` | AWS profile for Secrets Manager | None (required) |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `PULLDB_AWS_PROFILE` | Alternative to AWS_PROFILE | Falls back to AWS_PROFILE |
| `PULLDB_COORDINATION_SECRET` | Secret path | `aws-secretsmanager:/pulldb/mysql/coordination-db` |
| `PULLDB_API_MYSQL_USER` | MySQL user | `pulldb_api` |
| `PULLDB_MYSQL_DATABASE` | Database name | `pulldb_service` |

### Example Setup

```bash
# Option 1: Use AWS_PROFILE
export AWS_PROFILE=pr-dev
python tools/feature-requests-review.py list

# Option 2: One-liner
AWS_PROFILE=pr-dev python tools/feature-requests-review.py list --json
```

---

## Implementation Details

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 tools/feature-requests-review.py            │
│  (Standalone Script - NOT part of pulldb package)           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ argparse CLI    │    │ Self-contained:                 │ │
│  │ - list          │    │ - Domain models (dataclasses)   │ │
│  │ - show          │    │ - Credential resolution (boto3) │ │
│  │ - stats         │    │ - Direct SQL queries (pymysql)  │ │
│  └─────────────────┘    │ - Output formatting             │ │
│                         └─────────────────────────────────┘ │
│                                      │                       │
└──────────────────────────────────────│───────────────────────┘
                                       │
                                       │ AWS Secrets Manager
                                       │ MySQL (3306)
                                       ▼
                          ┌─────────────────────────────────┐
                          │     Production Environment      │
                          │  ┌─────────────────────────────┐│
                          │  │ AWS Secrets Manager         ││
                          │  │ /pulldb/mysql/coordination  ││
                          │  └─────────────────────────────┘│
                          │  ┌─────────────────────────────┐│
                          │  │ MySQL (pulldb_service)      ││
                          │  │ - feature_requests          ││
                          │  │ - feature_request_notes     ││
                          │  │ - auth_users                ││
                          │  └─────────────────────────────┘│
                          └─────────────────────────────────┘
```

### Why Self-Contained?

The tool intentionally **does not import from pulldb** to:

1. **Avoid deployment coupling** - Changes to pulldb don't affect this tool
2. **Minimize dependencies** - Only boto3 and pymysql needed
3. **Simplify AI agent use** - Can be copied/run anywhere with Python
4. **Reduce complexity** - No service layer, no factories, just SQL

### Read-Only Design

This tool is **read-only** by design:
- No INSERT/UPDATE/DELETE operations
- Uses `pulldb_api` user (could use read-only user)
- Safe to run without affecting production data

### Future Extensions

If write operations are needed (adding notes, updating status):
- Create a separate tool or add `--write` flag
- Require explicit confirmation
- Log all mutations for audit

---

## Historical Context

### Previous (Incorrect) Implementation

The tool was initially added to `pulldb/cli/admin_feature_requests.py` and
integrated with `pulldb-admin`. This was **incorrect** because:

1. Developer-only tools shouldn't be deployed
2. Added complexity to pulldb package
3. Required pulldb imports (coupling)
4. Would ship unnecessary code to production

### Refactoring (2026-01-31)

- Removed from `pulldb/cli/admin.py` command registration
- Deleted `pulldb/cli/admin_feature_requests.py`
- Deleted `tests/unit/cli/test_admin_feature_requests.py`
- Created standalone `tools/feature-requests-review.py`

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [KNOWLEDGE-POOL.md](KNOWLEDGE-POOL.md) | AWS secrets paths |
| [mysql-schema.md](mysql-schema.md) | Full schema reference |
| [.pulldb/extensions/mysql-user-separation.md](../.pulldb/extensions/mysql-user-separation.md) | MySQL user privileges |
