# pullDB REST API Reference

> **Complete API documentation for pullDB v1.0.0**
>
> The pullDB API is a FastAPI-based REST service running on port **8080** (combined API + Web UI).
> In web-only mode, the service runs on port **8000**.
> Interactive documentation is available at `/api/docs` (Swagger) and `/api/redoc` (ReDoc) when the service is running.

## Table of Contents

- [Authentication](#authentication)
- [Base URL](#base-url)
- [Health & Status](#health--status)
- [Jobs](#jobs)
- [Users](#users)
- [Hosts](#hosts)
- [Backups](#backups)
- [Manager Endpoints](#manager-endpoints)
- [Admin Endpoints](#admin-endpoints)
- [Error Handling](#error-handling)

---

## Authentication

pullDB supports three authentication modes configured via `PULLDB_AUTH_MODE`:

| Mode | Description | Header/Cookie |
|------|-------------|---------------|
| `trusted` | Trust `X-Pulldb-User` header from CLI | `X-Pulldb-User: username` |
| `session` | Cookie-based sessions with bcrypt passwords | `session_token` cookie |
| `both` | Accept either method (default) | Either of the above |

### Trusted Mode (CLI)

```bash
curl -H "X-Pulldb-User: jsmith" http://localhost:8080/api/jobs
```

### Session Mode (Web UI)

Login via `/web/login` to obtain a session cookie, then include it in requests:

```bash
curl -b "session_token=abc123..." http://localhost:8080/api/jobs
```

### Role-Based Access Control (RBAC)

| Role | Permissions |
|------|-------------|
| `USER` | Submit/view own jobs, cancel own jobs |
| `MANAGER` | View team jobs, manage team members |
| `ADMIN` | Full access, system configuration |

---

## Base URL

| Environment | URL |
|-------------|-----|
| Production | `http://pulldb-server:8080/api` |
| Development | `http://localhost:8080/api` |
| Web-Only Mode | `http://localhost:8080/api` |

All endpoints are prefixed with `/api`.

---

## Health & Status

### GET /api/health

Health check endpoint. Returns `200 OK` if the service is running.

**Request:**
```bash
curl http://localhost:8080/api/health
```

**Response:**
```json
{
  "status": "ok"
}
```

---

### GET /api/status

System status with queue depth and active restore count.

**Request:**
```bash
curl http://localhost:8080/api/status
```

**Response:**
```json
{
  "queue_depth": 3,
  "active_restores": 2,
  "service": "api"
}
```

---

## Jobs

### POST /api/jobs

Submit a new restore job.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user` | string | ✅ | User code (e.g., `jsmith`) |
| `customer` | string | ❌ | Customer name for backup search |
| `qatemplate` | boolean | ❌ | Use QA template instead of customer backup (default: false) |
| `dbhost` | string | ❌ | Target database host (default from settings) |
| `date` | string | ❌ | Specific backup date `YYYY-MM-DD` |
| `env` | string | ❌ | S3 environment: `staging` or `prod` |
| `overwrite` | boolean | ❌ | Overwrite existing database (default: false) |
| `suffix` | string | ❌ | 1-3 lowercase letter suffix for target database (pattern: `^[a-z]{1,3}$`) |
| `backup_path` | string | ❌ | Full S3 path to specific backup |

**Example - Customer Restore:**
```bash
curl -X POST http://localhost:8080/api/jobs \
  -H "Content-Type: application/json" \
  -H "X-Pulldb-User: jsmith" \
  -d '{
    "user": "jsmith",
    "customer": "acme_pest",
    "dbhost": "dev-mysql-01"
  }'
```

**Example - QA Template:**
```bash
curl -X POST http://localhost:8080/api/jobs \
  -H "Content-Type: application/json" \
  -H "X-Pulldb-User: jsmith" \
  -d '{
    "user": "jsmith",
    "qatemplate": true
  }'
```

**Response (201 Created):**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "target": "cust_12345",
  "staging_name": "pulldb_stg_8b4c4a3a",
  "status": "queued",
  "owner_username": "jsmith",
  "owner_user_code": "jsmith",
  "submitted_at": "2026-01-02T15:30:00Z"
}
```

**Error Response (409 Conflict):**
```json
{
  "detail": "Restore already in progress for target 'cust_12345'"
}
```

---

### GET /api/jobs

List jobs with optional filters.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Max results (1-1000) |
| `active` | boolean | false | Only active (queued/running) jobs |
| `history` | boolean | false | Only completed/failed/canceled jobs |
| `filter` | string | null | Filter by user code prefix |

**Example:**
```bash
curl "http://localhost:8080/api/jobs?active=true&limit=10"
```

**Response:**
```json
[
  {
    "id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
    "target": "cust_12345",
    "status": "running",
    "user_code": "cust_12345",
    "owner_user_code": "jsmith",
    "submitted_at": "2026-01-02T15:30:00Z",
    "started_at": "2026-01-02T15:30:05Z",
    "completed_at": null,
    "staging_name": "pulldb_stg_8b4c4a3a",
    "current_operation": "downloading",
    "dbhost": "dev-mysql-01",
    "source": "s3://bucket/daily/stg/acme_pest/...",
    "can_cancel": true
  }
]
```

---

### GET /api/jobs/active

Shortcut for listing only active jobs.

```bash
curl "http://localhost:8080/api/jobs/active"
```

---

### GET /api/jobs/history

Shortcut for listing completed/failed/canceled jobs.

```bash
curl "http://localhost:8080/api/jobs/history?limit=50"
```

---

### GET /api/jobs/paginated

Paginated job listing for LazyTable widget with offset-based pagination.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 0 | Page number (0-indexed) |
| `pageSize` | integer | 50 | Page size (10-200) |
| `view` | string | `active` | View: `active` or `history` |
| `sortColumn` | string | - | Column to sort by |
| `sortDirection` | string | - | Sort direction: `asc` or `desc` |
| `filter_status` | string | - | Filter by status (comma-separated for OR) |
| `filter_dbhost` | string | - | Filter by host (comma-separated for OR) |
| `filter_user_code` | string | - | Filter by user code (comma-separated for OR) |
| `filter_target` | string | - | Filter by target (substring match) |
| `filter_id` | string | - | Filter by job ID (wildcards: `*`) |
| `filter_submitted_at` | string | - | Filter by date MM/DD/YYYY (wildcards: `*`) |
| `days` | integer | 30 | History retention days (1-365) |

**Response:**
```json
{
  "rows": [...],
  "totalCount": 156,
  "filteredCount": 42,
  "page": 0,
  "pageSize": 50
}
```

---

### GET /api/jobs/{job_id}

Get detailed information about a specific job.

```bash
curl "http://localhost:8080/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f"
```

---

### GET /api/jobs/resolve/{prefix}

Resolve a short job ID prefix to full job ID.

**Example:**
```bash
curl "http://localhost:8080/api/jobs/resolve/8b4c4a3a"
```

**Response (single match):**
```json
{
  "resolved_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "matches": [...],
  "count": 1
}
```

**Response (multiple matches):**
```json
{
  "resolved_id": null,
  "matches": [
    {"id": "8b4c4a3a-85a1-...", "target": "cust_12345", "status": "completed"},
    {"id": "8b4c4a3a-92f7-...", "target": "cust_67890", "status": "running"}
  ],
  "count": 2
}
```

---

### GET /api/jobs/{job_id}/events

Get event log for a job.

```bash
curl "http://localhost:8080/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f/events"
```

**Response:**
```json
[
  {
    "id": 1,
    "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
    "event_type": "job_queued",
    "detail": "Job submitted by jsmith",
    "logged_at": "2026-01-02T15:30:00Z"
  },
  {
    "id": 2,
    "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
    "event_type": "download_started",
    "detail": "Downloading from s3://...",
    "logged_at": "2026-01-02T15:30:05Z"
  }
]
```

---

### GET /api/jobs/{job_id}/profile

Get performance breakdown for a completed job.

```bash
curl "http://localhost:8080/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f/profile"
```

**Response:**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "started_at": "2026-01-02T15:30:05Z",
  "completed_at": "2026-01-02T15:34:10Z",
  "total_duration_seconds": 245.5,
  "total_bytes": 1234567890,
  "phases": {
    "download": {
      "phase": "download",
      "started_at": "2026-01-02T15:30:05Z",
      "completed_at": "2026-01-02T15:30:50Z",
      "duration_seconds": 45.2,
      "bytes_processed": 1234567890,
      "bytes_per_second": 27312345.1,
      "mbps": 26.0,
      "metadata": {}
    },
    "extraction": {...},
    "myloader": {...},
    "post_sql": {...}
  },
  "phase_breakdown_percent": {
    "download": 18.4,
    "extraction": 5.2,
    "myloader": 73.5,
    "post_sql": 2.9
  },
  "error": null
}
```

---

### POST /api/jobs/{job_id}/cancel

Cancel a running or queued job. Users can cancel their own jobs. Managers can cancel team member jobs. Admins can cancel any job.

```bash
curl -X POST "http://localhost:8080/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f/cancel" \
  -H "X-Pulldb-User: jsmith"
```

**Response (200 OK - Queued Job):**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "status": "canceled",
  "message": "Job canceled successfully (was queued)"
}
```

**Response (200 OK - Running Job):**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "status": "canceling",
  "message": "Cancellation requested; worker will stop at next checkpoint"
}
```

---

### GET /api/jobs/my-last

Get the authenticated user's most recent job. Requires `user_code` query parameter.

```bash
curl "http://localhost:8080/api/jobs/my-last?user_code=jsmith"
```

**Response:**
```json
{
  "job": {
    "id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
    "target": "jsmith_acme",
    "status": "complete",
    ...
  },
  "user_code": "jsmith"
}
```

---

### GET /api/jobs/search

Search jobs by ID, target, username, or user code. **Minimum 4 characters required.**

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | - | Search query (min 4 chars) |
| `limit` | integer | 50 | Max results (1-200) |
| `exact` | boolean | false | Force exact matching |

```bash
curl "http://localhost:8080/api/jobs/search?q=jsmith&limit=10"
```

**Response:**
```json
{
  "query": "jsmith",
  "count": 3,
  "exact_match": true,
  "jobs": [
    {
      "id": "8b4c4a3a-...",
      "target": "jsmith_acme",
      "status": "complete",
      "user_code": "jsmith",
      "owner_username": "jsmith",
      ...
    }
  ]
}

---

## Users

### GET /api/users/{username}

Get user information by username.

```bash
curl "http://localhost:8080/api/users/jsmith"
```

**Response:**
```json
{
  "username": "jsmith",
  "user_code": "JSMITH",
  "is_admin": false,
  "is_disabled": false,
  "has_password": true
}
```

---

### GET /api/users/{user_code}/last-job

Get a user's most recent job (by user code).

```bash
curl "http://localhost:8080/api/users/cust_12345/last-job"
```

**Response:**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "target": "cust_12345",
  "status": "completed",
  "submitted_at": "2026-01-02T15:30:00Z",
  "started_at": "2026-01-02T15:30:05Z",
  "completed_at": "2026-01-02T15:34:10Z",
  "found": true
}
```

---

### POST /api/auth/register

Register a new user account. Account is created in **disabled state** and must be enabled by an administrator.

**Request Body:**
```json
{
  "username": "newuser",
  "password": "securepassword123"
}
```

> **Note:** `user_code` is auto-generated from the username. Password must be at least 8 characters.

**Response (201 Created):**
```json
{
  "username": "newuser",
  "user_code": "NEWUSE",
  "message": "Account created successfully. Contact an administrator to enable your account."
}
```

---

### POST /api/auth/change-password

Change user password.

**Request Body:**
```json
{
  "username": "jsmith",
  "current_password": "oldpassword",
  "new_password": "newsecurepassword"
}
```

---

## Hosts

### GET /api/hosts

List available database hosts for restore targets.

```bash
curl "http://localhost:8080/api/hosts"
```

**Response:**
```json
{
  "hosts": [
    {
      "hostname": "dev-mysql-01.internal",
      "alias": "dev-mysql-01",
      "enabled": true
    },
    {
      "hostname": "staging-mysql.internal",
      "alias": "staging",
      "enabled": true
    }
  ],
  "total": 2
}
```

---

## Backups

### GET /api/backups/search

Search for available backups in S3.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `customer` | string | - | Customer name or wildcard pattern (supports `*` and `?`) |
| `environment` | string | `both` | Environment: `staging`, `prod`, or `both` |
| `date_from` | string | 7 days ago | Start date filter `YYYYMMDD` |
| `limit` | integer | 5 | Max results per page (1-100) |
| `offset` | integer | 0 | Pagination offset |

**Example:**
```bash
curl "http://localhost:8080/api/backups/search?customer=acme&environment=staging&limit=5"
```

**Response:**
```json
{
  "backups": [
    {
      "customer": "acme_pest",
      "timestamp": "2026-01-02T00:00:00Z",
      "date": "20260102",
      "size_mb": 1234.5,
      "environment": "staging",
      "key": "daily/stg/acme_pest/daily_mydumper_2026-01-02.tar",
      "bucket": "pestroutesrdsdbs"
    }
  ],
  "total": 1,
  "query": "acme",
  "environment": "staging",
  "offset": 0,
  "limit": 5,
  "has_more": false
}
```

---

### GET /api/customers/search

Search for customer names.

```bash
curl "http://localhost:8080/api/customers/search?q=acme"
```

---

## Manager Endpoints

These endpoints require `MANAGER` or `ADMIN` role.

### GET /api/manager/team

List team members and their jobs.

```bash
curl -H "X-Pulldb-User: manager1" "http://localhost:8080/api/manager/team"
```

---

### GET /api/manager/team/distinct

Get distinct user codes in the manager's team.

---

## Admin Endpoints

These endpoints require `ADMIN` role.

### POST /api/admin/jobs/bulk-cancel

Bulk cancel jobs matching filters.

**Request Body:**
```json
{
  "view": "active",
  "filter_status": "queued",
  "filter_dbhost": "dev-mysql-01",
  "filter_user_code": "jsmith",
  "filter_target": "acme",
  "confirmation": "CANCEL ALL"
}
```

### POST /api/admin/prune-logs

Prune old job event logs from database.

### POST /api/admin/cleanup-staging

Clean up orphaned staging databases.

### GET /api/admin/orphan-databases

List orphaned staging databases across all hosts.

### GET /api/admin/orphan-databases/paginated

Paginated list of orphan databases for LazyTable widget.

### GET /api/admin/orphan-databases/{dbhost}/{db_name}/meta

Get metadata from `pullDB` table inside an orphan database.

### DELETE /api/admin/orphan-databases/{dbhost}/{db_name}

Delete a single orphan database.

### POST /api/admin/delete-orphans

Bulk delete orphan databases.

### POST /api/admin/hosts/{host_id}/rotate-secret

Rotate MySQL credentials for a database host. Performs atomic 7-phase rotation:

1. Fetch current credentials from AWS Secrets Manager
2. Validate current credentials work on MySQL
3. Generate new secure password
4. Update MySQL user password
5. Verify new password works
6. Update AWS Secrets Manager
7. Final verification (AWS → MySQL round-trip)

**Request Body:**
```json
{
  "new_password": null,
  "password_length": 32
}
```

---

## Dropdown Endpoints

These endpoints power the web UI autocomplete dropdowns. Each returns a standard response format:

```json
{
  "results": [{"value": "...", "label": "...", "sublabel": "..."}],
  "total": 1
}
```

### GET /api/dropdown/customers

Search customers for dropdown. **Minimum 5 characters required.**

```bash
curl "http://localhost:8080/api/dropdown/customers?q=actionp&limit=10"
```

### GET /api/dropdown/users

Search users for dropdown. **Minimum 3 characters required.**

```bash
curl "http://localhost:8080/api/dropdown/users?q=jsm&limit=10"
```

### GET /api/dropdown/hosts

Search hosts for dropdown. **Minimum 3 characters required.**

```bash
curl "http://localhost:8080/api/dropdown/hosts?q=dev&limit=10"
```

---

## Error Handling

All errors return JSON with a `detail` field:

### 400 Bad Request

```json
{
  "detail": "Invalid date format. Use YYYY-MM-DD."
}
```

### 401 Unauthorized

```json
{
  "detail": "Authentication required"
}
```

### 403 Forbidden

```json
{
  "detail": "Admin role required"
}
```

### 404 Not Found

```json
{
  "detail": "Job not found: 8b4c4a3a-..."
}
```

### 409 Conflict

```json
{
  "detail": "Restore already in progress for target 'cust_12345'"
}
```

### 500 Internal Server Error

```json
{
  "detail": "Internal server error",
  "error_id": "err_abc123"
}
```

---

## Interactive Documentation

When the service is running, interactive API documentation is available:

- **Swagger UI**: `http://localhost:8080/api/docs`
- **ReDoc**: `http://localhost:8080/api/redoc`
- **OpenAPI JSON**: `http://localhost:8080/api/openapi.json`

---

## See Also

- [CLI Reference](cli-reference.md) - Command-line interface documentation
- [Getting Started](getting-started.md) - Installation and quick start
- [Architecture](../widgets/architecture.md) - System design overview
